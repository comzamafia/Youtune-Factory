"""Video Builder — Assembles scene clips into a final video with subtitles and music."""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)


def build_final_video(
    scene_clips: list[Path],
    output_path: Path,
    subtitle_path: Path | None = None,
    music_path: Path | None = None,
    music_volume: float = 0.1,
) -> Path:
    """
    Concatenate scene clips into one video, optionally burn in subtitles
    and mix background music.

    Args:
        scene_clips: Ordered list of scene clip paths.
        output_path: Where to save the final video.
        subtitle_path: Optional SRT file to burn in.
        music_path: Optional background music file.
        music_volume: Volume level for background music (0.0–1.0).

    Returns:
        Path to the final video.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Step 1 — Create a concat list file
    concat_file = Path(tempfile.mktemp(suffix=".txt"))
    lines = [f"file '{clip.resolve()}'" for clip in scene_clips]
    concat_file.write_text("\n".join(lines), encoding="utf-8")

    try:
        # Step 2 — Concatenate clips (timeout scales with clip count)
        concat_output = output_path.with_suffix(".concat.mp4")
        cmd_concat = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_file),
            "-c", "copy",
            str(concat_output),
        ]
        concat_timeout = max(600, len(scene_clips) * 5)
        logger.info("Concatenating %d clips (timeout=%ds)…", len(scene_clips), concat_timeout)
        _run_ffmpeg(cmd_concat, timeout=concat_timeout)

        current_input = concat_output

        # Step 3 — Burn subtitles (if provided)
        if subtitle_path and subtitle_path.exists():
            sub_output = output_path.with_suffix(".sub.mp4")
            # Escape backslashes and colons for FFmpeg subtitles filter on Windows
            sub_str = str(subtitle_path.resolve()).replace("\\", "/").replace(":", "\\:")
            # force_style overrides:
            #   Alignment=2   → bottom-center (standard subtitle position)
            #   MarginV       → px gap from frame bottom
            #   MarginL/R=40  → side padding so long lines don't touch edges
            #   WrapStyle=1   → wrap at word boundary (line length controlled by SRT chunks)
            #   Outline=2     → black outline for readability on any background
            #   Shadow=1      → subtle drop shadow
            sub_style = (
                f"FontSize={settings.subtitle_font_size},"
                f"PrimaryColour=&Hffffff&,"
                f"OutlineColour=&H000000&,"
                f"Outline=2,Shadow=1,"
                f"Alignment=2,"
                f"MarginV={settings.subtitle_margin_v},"
                f"MarginL=40,MarginR=40,"
                f"WrapStyle=1"
            )
            vf = f"subtitles='{sub_str}':force_style='{sub_style}'"

            cmd_sub = [
                "ffmpeg", "-y",
                "-i", str(current_input),
                "-vf", vf,
            ]
            if settings.use_gpu:
                cmd_sub.extend(["-c:v", settings.ffmpeg_vcodec])
            else:
                cmd_sub.extend(["-c:v", "libx264", "-preset", "fast"])
            cmd_sub.extend(["-c:a", "copy", str(sub_output)])

            logger.info("Burning subtitles…")
            sub_timeout = max(600, len(scene_clips) * 5)
            _run_ffmpeg(cmd_sub, timeout=sub_timeout)
            current_input.unlink(missing_ok=True)
            current_input = sub_output

        # Step 4 — Mix background music (if provided)
        if music_path and music_path.exists():
            music_output = output_path.with_suffix(".music.mp4")
            filter_complex = (
                f"[1:a]volume={music_volume}[bg];"
                f"[0:a][bg]amix=inputs=2:duration=first:dropout_transition=3[aout]"
            )
            cmd_music = [
                "ffmpeg", "-y",
                "-i", str(current_input),
                "-i", str(music_path),
                "-filter_complex", filter_complex,
                "-map", "0:v",
                "-map", "[aout]",
                "-c:v", "copy",
                "-c:a", "aac", "-b:a", "192k",
                str(music_output),
            ]
            logger.info("Mixing background music…")
            music_timeout = max(600, len(scene_clips) * 5)
            _run_ffmpeg(cmd_music, timeout=music_timeout)
            current_input.unlink(missing_ok=True)
            current_input = music_output

        # Step 5 — Rename to final output
        if current_input != output_path:
            output_path.unlink(missing_ok=True)
            current_input.rename(output_path)

        logger.info("Final video → %s", output_path.name)
        return output_path

    finally:
        # Cleanup temp files
        concat_file.unlink(missing_ok=True)
        for suffix in (".concat.mp4", ".sub.mp4", ".music.mp4"):
            tmp = output_path.with_suffix(suffix)
            tmp.unlink(missing_ok=True)


def _run_ffmpeg(cmd: list[str], timeout: int = 600) -> None:
    """Run an FFmpeg command and raise on failure."""
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        logger.error("FFmpeg error: %s", proc.stderr[-500:])
        raise RuntimeError(f"FFmpeg failed: {proc.stderr[-200:]}")
