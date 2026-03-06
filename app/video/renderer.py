"""Video Renderer — Creates individual scene clips using FFmpeg."""

from __future__ import annotations

import logging
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)


def _build_ffmpeg_cmd(
    image_path: Path,
    audio_path: Path,
    output_path: Path,
    duration: float | None = None,
) -> list[str]:
    """Construct the FFmpeg command for a single scene clip."""
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

    # Duration: use audio length or explicit duration
    if duration:
        cmd.extend(["-t", str(duration)])
    else:
        cmd.extend(["-shortest"])

    cmd.append(str(output_path))
    return cmd


def render_scene(
    image_path: Path,
    audio_path: Path,
    output_path: Path,
    duration: float | None = None,
) -> Path:
    """Render a single scene clip from an image + audio pair."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = _build_ffmpeg_cmd(image_path, audio_path, output_path, duration)
    logger.info("Rendering scene: %s", output_path.name)

    # Scale timeout: 120s base + extra for long scenes
    timeout = max(120, int((duration or 6.0) * 20))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        logger.error("FFmpeg error: %s", proc.stderr[-500:])
        raise RuntimeError(f"FFmpeg render failed for {output_path.name}: {proc.stderr[-200:]}")

    logger.info("Scene rendered: %s", output_path.name)
    return output_path


def render_scenes_parallel(
    scenes: list[dict],
    max_workers: int | None = None,
) -> list[Path]:
    """
    Render multiple scenes in parallel.

    Each *scene* dict must have keys: ``image_path``, ``audio_path``,
    ``output_path``, and optionally ``duration``.
    """
    if max_workers is None:
        max_workers = settings.ffmpeg_max_workers

    results: list[Path] = [Path()] * len(scenes)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_map = {}
        for i, s in enumerate(scenes):
            future = pool.submit(
                render_scene,
                Path(s["image_path"]),
                Path(s["audio_path"]),
                Path(s["output_path"]),
                s.get("duration"),
            )
            future_map[future] = i

        for future in as_completed(future_map):
            idx = future_map[future]
            results[idx] = future.result()  # raises on error

    logger.info("Rendered %d scenes in parallel.", len(results))
    return results
