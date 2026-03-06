"""Video Renderer — Creates individual scene clips using FFmpeg."""

from __future__ import annotations

import logging
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)


def _build_ffmpeg_image_cmd(
    image_path: Path,
    audio_path: Path,
    output_path: Path,
    duration: float | None = None,
) -> list[str]:
    """Construct the FFmpeg command for a scene rendered from a static image + audio."""
    cmd = ["ffmpeg", "-y"]

    # GPU acceleration
    if settings.use_gpu:
        cmd.extend(["-hwaccel", settings.ffmpeg_hwaccel])

    # Input: loop image + audio
    cmd.extend(["-loop", "1", "-i", str(image_path)])
    cmd.extend(["-i", str(audio_path)])

    # Video codec
    if settings.use_gpu:
        cmd.extend(["-c:v", settings.ffmpeg_vcodec])
    else:
        cmd.extend(["-c:v", "libx264", "-preset", "fast"])

    cmd.extend(["-c:a", "aac", "-b:a", "192k"])
    cmd.extend(["-pix_fmt", "yuv420p"])

    # Scale and pad to configured output dimensions (default 1080×1920 = 9:16 vertical)
    vf = (
        f"scale={settings.video_width}:{settings.video_height}"
        f":force_original_aspect_ratio=decrease,"
        f"pad={settings.video_width}:{settings.video_height}"
        f":(ow-iw)/2:(oh-ih)/2"
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

    The source video is loop-streamed so that clips shorter than the audio are
    automatically repeated.  The TTS audio replaces the original video soundtrack.
    """
    cmd = ["ffmpeg", "-y"]

    if settings.use_gpu:
        cmd.extend(["-hwaccel", settings.ffmpeg_hwaccel])

    # -stream_loop -1 loops the video indefinitely; trimmed by -t or -shortest
    cmd.extend(["-stream_loop", "-1", "-i", str(video_source)])
    cmd.extend(["-i", str(audio_path)])

    # Map video from source, audio from TTS (drop original video audio)
    cmd.extend(["-map", "0:v:0", "-map", "1:a:0"])

    if settings.use_gpu:
        cmd.extend(["-c:v", settings.ffmpeg_vcodec])
    else:
        cmd.extend(["-c:v", "libx264", "-preset", "fast"])

    cmd.extend(["-c:a", "aac", "-b:a", "192k", "-pix_fmt", "yuv420p"])

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
        cmd = _build_ffmpeg_image_cmd(ip, audio_path, output_path, duration)
        scene_type = "image"

    logger.info("Rendering scene (%s): %s | cmd: %s", scene_type, output_path.name, " ".join(cmd))

    # Scale timeout: 120s base + extra time for long scenes
    timeout = max(120, int((duration or 6.0) * 20))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        logger.error("FFmpeg FULL stderr:\n%s", proc.stderr)
        # Extract meaningful error lines (skip version/config noise and progress)
        err_lines = []
        for line in proc.stderr.splitlines():
            low = line.lower()
            # Skip noisy lines: version, config, progress
            if any(skip in low for skip in [
                "ffmpeg version", "built with", "configuration:", "--enable-",
                "--disable-", "libavutil", "libavcodec", "libavformat",
                "libavdevice", "libavfilter", "libswscale", "libswresample",
                "libpostproc", "speed=n/a", "bitrate=n/a",
            ]):
                continue
            if line.strip():
                err_lines.append(line.strip())
        err_summary = "\n".join(err_lines[:30]) or proc.stderr[:800]
        raise RuntimeError(f"FFmpeg render failed for {output_path.name}:\n{err_summary}")

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
