"""Video Renderer — Creates individual scene clips using FFmpeg."""

from __future__ import annotations

import logging
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

# Direction vectors for Ken Burns panning: (dx, dy).  Cycles per scene_index.
_MOTION_DIRECTIONS = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, -1), (-1, 1)]


def _build_zoompan_vf(
    duration: float,
    width: int,
    height: int,
    effect: str,
    scene_index: int = 0,
) -> str:
    """Build an FFmpeg -vf filter string that animates a static image.

    Uses the zoompan filter with ``-framerate 1 -loop 1`` image input.
    zoompan upconverts to 25 fps, producing smooth cinematic motion —
    no extra libraries required, pure FFmpeg.

    Effects
    -------
    none      – plain scale + letterbox, no animation (fastest)
    zoom_in   – gentle center zoom 1.0 → 1.15
    ken_burns – zoom + directional pan, direction cycles per scene_index
    zoom_3d   – aggressive zoom 1.0 → 1.35 for dramatic openers
    random    – cycles zoom_in / ken_burns / zoom_3d by scene_index
    """
    if effect == "none":
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
        )

    if effect == "random":
        choices = ["zoom_in", "ken_burns", "zoom_3d"]
        effect = choices[scene_index % len(choices)]

    fps = 25
    frames = max(fps, int(duration * fps))  # at least 1 second of frames

    # Pre-scale to 40 % oversized canvas so zoom never exposes black bars.
    # Dimensions must be even for h264/NVENC.
    over_w = (int(width * 1.4) // 2) * 2
    over_h = (int(height * 1.4) // 2) * 2

    prescale = (
        f"scale={over_w}:{over_h}:force_original_aspect_ratio=decrease,"
        f"pad={over_w}:{over_h}:(ow-iw)/2:(oh-ih)/2"
    )

    # zoompan: d=frames outputs exactly ``frames`` frames from one looped
    # input frame; fps=25 sets output PTS for smooth 25 fps downstream.
    zp = f"zoompan=d={frames}:s={width}x{height}:fps={fps}"

    # Centred crop anchor.
    # In z expression: ``zoom`` = previous frame’s zoom (pzoom, starts at 1.0).
    # In x/y expressions: ``zoom`` = current frame’s zoom (result of z expr).
    cx = "iw/2-(iw/zoom/2)"
    cy = "ih/2-(ih/zoom/2)"

    if effect == "zoom_in":
        step = 0.15 / frames
        z = f"min(zoom+{step:.8f},1.15)"
        return f"{prescale},{zp}:z='{z}':x='{cx}':y='{cy}'"

    if effect == "zoom_3d":
        step = 0.35 / frames
        z = f"min(zoom+{step:.8f},1.35)"
        return f"{prescale},{zp}:z='{z}':x='{cx}':y='{cy}'"

    if effect == "ken_burns":
        dx, dy = _MOTION_DIRECTIONS[scene_index % len(_MOTION_DIRECTIONS)]
        zoom_range = 0.12
        step = zoom_range / frames
        z = f"min(zoom+{step:.8f},1.12)"
        # Pan grows proportionally with zoom accumulation.
        # max_pan = 8 % of oversized dimension — stays within image content.
        # pflx/pfly = pixels of pan per unit of zoom change.
        max_pan_x = over_w * 0.08
        max_pan_y = over_h * 0.08
        pflx = max_pan_x / zoom_range
        pfly = max_pan_y / zoom_range
        # Build clamped pan expressions; avoid `+-` by separating sign from magnitude.
        def _pan_expr(base: str, d: int, scale_px: float, dim: str, zoom_dim: str) -> str:
            if not d:
                return base
            sign = "+" if d > 0 else "-"
            mag = abs(d) * scale_px
            return f"max(0,min({dim}-{zoom_dim},{base}{sign}(zoom-1)*{mag:.4f}))"
        x_expr = _pan_expr(cx, dx, pflx, "iw", "iw/zoom")
        y_expr = _pan_expr(cy, dy, pfly, "ih", "ih/zoom")
        return f"{prescale},{zp}:z='{z}':x='{x_expr}':y='{y_expr}'"

    # Unknown effect — plain scale/pad fallback
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
    )


def _build_ffmpeg_image_cmd(
    image_path: Path,
    audio_path: Path,
    output_path: Path,
    duration: float | None = None,
    scene_index: int = 0,
) -> list[str]:
    """Construct the FFmpeg command for a scene rendered from a static image + audio."""
    cmd = ["ffmpeg", "-y"]

    # GPU acceleration
    if settings.use_gpu:
        cmd.extend(["-hwaccel", settings.ffmpeg_hwaccel])

    # Input: loop image with explicit framerate (required for FFmpeg 7.x)
    cmd.extend(["-framerate", "1", "-loop", "1", "-i", str(image_path)])
    cmd.extend(["-i", str(audio_path)])

    # Video codec
    vcodec = settings.ffmpeg_vcodec if settings.use_gpu else "libx264"
    cmd.extend(["-c:v", vcodec])
    if vcodec == "libx264":
        cmd.extend(["-preset", "ultrafast", "-threads", "1"])

    cmd.extend(["-c:a", "aac", "-b:a", "128k", "-ar", "44100"])
    cmd.extend(["-pix_fmt", "yuv420p"])
    cmd.extend(["-r", "25"])

    vf = _build_zoompan_vf(
        duration=duration or 6.0,
        width=settings.video_width,
        height=settings.video_height,
        effect=settings.image_motion_effect,
        scene_index=scene_index,
    )
    cmd.extend(["-vf", vf])

    # Duration: use audio length or explicit duration
    if duration:
        cmd.extend(["-t", str(duration)])
    else:
        cmd.extend(["-shortest"])

    cmd.append(str(output_path))
    return cmd


def _build_ffmpeg_video_cmd(
    video_source: Path,
    audio_path: Path,
    output_path: Path,
    duration: float | None = None,
) -> list[str]:
    """Construct the FFmpeg command for a scene rendered from a source video + TTS audio.

    Uses a two-step approach to stay within Railway's memory limits:
    Step 1 would be optional scaling (done here in single pass).
    The video plays once (no loop) and is trimmed to audio length via -shortest.
    """
    cmd = ["ffmpeg", "-y"]

    if settings.use_gpu:
        cmd.extend(["-hwaccel", settings.ffmpeg_hwaccel])

    # Input video (single pass, no loop to save memory)
    cmd.extend(["-i", str(video_source)])
    cmd.extend(["-i", str(audio_path)])

    # Map video from source, audio from TTS (drop original video audio)
    cmd.extend(["-map", "0:v:0", "-map", "1:a:0"])

    # Video codec
    vcodec = settings.ffmpeg_vcodec if settings.use_gpu else "libx264"
    cmd.extend(["-c:v", vcodec])
    if vcodec == "libx264":
        cmd.extend(["-preset", "ultrafast", "-threads", "1", "-maxrate", "2M", "-bufsize", "1M"])

    cmd.extend(["-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-pix_fmt", "yuv420p"])

    # Scale and pad to configured output dimensions (default 1080×1920 = 9:16 vertical)
    vf = (
        f"scale={settings.video_width}:{settings.video_height}"
        f":force_original_aspect_ratio=decrease,"
        f"pad={settings.video_width}:{settings.video_height}"
        f":(ow-iw)/2:(oh-ih)/2"
    )
    cmd.extend(["-vf", vf])

    if duration:
        cmd.extend(["-t", str(duration)])
    else:
        cmd.extend(["-shortest"])

    cmd.append(str(output_path))
    return cmd


def render_scene(
    scene: dict,
    output_path: Path,
) -> Path:
    """Render a single scene clip.

    ``scene`` must contain ``audio_path`` and either ``video_source_path``
    (user-supplied video clip) or ``image_path`` (AI-generated / user image).
    Optionally ``duration`` (float, seconds).
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    audio_path = Path(scene["audio_path"])
    duration = scene.get("duration")
    video_source = scene.get("video_source_path")
    image_path = scene.get("image_path")

    # Validate inputs exist
    if not audio_path.exists():
        raise RuntimeError(f"Audio file not found: {audio_path}")
    if video_source:
        vs = Path(video_source)
        if not vs.exists():
            raise RuntimeError(f"Video source not found: {vs}")
        cmd = _build_ffmpeg_video_cmd(vs, audio_path, output_path, duration)
        scene_type = "video"
    else:
        if not image_path:
            raise RuntimeError(f"No image_path or video_source_path for {output_path.name}")
        ip = Path(image_path)
        if not ip.exists():
            raise RuntimeError(f"Image file not found: {ip}")
        scene_index = scene.get("scene_index", 0)
        cmd = _build_ffmpeg_image_cmd(ip, audio_path, output_path, duration, scene_index)
        scene_type = "image"

    logger.info("Rendering scene (%s): %s | cmd: %s", scene_type, output_path.name, " ".join(cmd))

    # Scale timeout: 120s base + extra time for long scenes
    timeout = max(120, int((duration or 6.0) * 20))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        logger.error("FFmpeg FULL stderr:\n%s", proc.stderr)
        # Extract meaningful error lines (skip all noise, keep only errors/warnings)
        err_lines = []
        for line in proc.stderr.splitlines():
            low = line.lower()
            # Skip noisy lines
            if any(skip in low for skip in [
                "ffmpeg version", "built with", "configuration:", "--enable-",
                "--disable-", "libavutil", "libavcodec", "libavformat",
                "libavdevice", "libavfilter", "libswscale", "libswresample",
                "libpostproc", "speed=n/a", "bitrate=n/a",
                "input #", "duration:", "stream #", "stream mapping",
                "press [q]", "using cpu capabilities", "profile high",
                "264 - core", "kb/s", "estimating duration",
            ]):
                continue
            if line.strip():
                err_lines.append(line.strip())
        err_summary = "\n".join(err_lines[-20:]) or proc.stderr[-800:]
        raise RuntimeError(
            f"FFmpeg render failed for {output_path.name} (rc={proc.returncode}):\n{err_summary}"
        )

    logger.info("Scene rendered: %s", output_path.name)
    return output_path


def render_scenes_parallel(
    scenes: list[dict],
    max_workers: int | None = None,
) -> list[Path]:
    """
    Render multiple scenes in parallel.

    Each *scene* dict must have: ``audio_path``, ``output_path``, and either
    ``video_source_path`` (user video) or ``image_path`` (static image).
    Optional: ``duration`` (float).
    """
    if max_workers is None:
        max_workers = settings.ffmpeg_max_workers

    results: list[Path] = [Path()] * len(scenes)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_map = {}
        for i, s in enumerate(scenes):
            future = pool.submit(
                render_scene,
                s,
                Path(s["output_path"]),
            )
            future_map[future] = i

        for future in as_completed(future_map):
            idx = future_map[future]
            results[idx] = future.result()  # raises on error

    logger.info("Rendered %d scenes in parallel.", len(results))
    return results
