"""Subtitle Generator — Creates SRT files from audio or text with accurate timing."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def _format_srt_time(seconds: float) -> str:
    """Convert seconds to SRT timestamp format ``HH:MM:SS,mmm``."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def get_audio_duration(audio_path: Path) -> float:
    """Get actual audio duration in seconds using mutagen (WAV/MP3) or ffprobe.

    Edge TTS produces .wav; ElevenLabs produces .mp3. Both are handled natively.
    Falls back to ffprobe for other formats, or returns 6.0 as default.
    """
    path = Path(audio_path)
    suffix = path.suffix.lower()

    try:
        if suffix == ".wav":
            from mutagen.wave import WAVE
            audio = WAVE(str(path))
            return audio.info.length
        else:
            from mutagen.mp3 import MP3
            audio = MP3(str(path))
            return audio.info.length
    except Exception:
        pass

    # Fallback: try ffprobe
    try:
        cmd = [
            "ffprobe", "-v", "quiet",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except Exception:
        pass

    logger.warning("Could not determine audio duration for %s, using 6.0s", audio_path.name)
    return 6.0


# ── Whisper-based subtitle generation ─────────────────────────────────────────


def generate_subtitles_whisper(audio_path: Path, output_path: Path, language: str = "en") -> Path:
    """
    Transcribe *audio_path* with OpenAI Whisper and write an SRT file.

    Requires the ``whisper`` CLI (``pip install openai-whisper``).
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_dir = output_path.parent

    cmd = [
        "whisper",
        str(audio_path),
        "--model", "base",
        "--language", language,
        "--output_format", "srt",
        "--output_dir", str(output_dir),
    ]
    logger.info("Running Whisper on %s", audio_path.name)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        logger.error("Whisper failed: %s", proc.stderr)
        raise RuntimeError(f"Whisper error: {proc.stderr}")

    # Whisper names the output after the input file stem
    generated = output_dir / f"{audio_path.stem}.srt"
    if generated != output_path and generated.exists():
        generated.rename(output_path)

    logger.info("Subtitles -> %s", output_path.name)
    return output_path


# ── Text-based subtitle generation (fallback) ─────────────────────────────────


def _split_text_to_lines(text: str, max_chars: int) -> list[str]:
    """Split *text* into lines of at most *max_chars* characters on word boundaries.

    Works for both space-separated (English) and space-less (Thai/CJK) scripts:
    - Space-separated: break on word boundaries.
    - No spaces (Thai/CJK): break on character count directly.
    """
    text = text.strip()
    if not text:
        return []

    # Space-separated languages (English, etc.)
    if " " in text:
        words = text.split()
        result: list[str] = []
        current = ""
        for word in words:
            candidate = (current + " " + word).strip() if current else word
            if len(candidate) <= max_chars:
                current = candidate
            else:
                if current:
                    result.append(current)
                # If a single word is longer than max_chars, keep it on its own line
                current = word
        if current:
            result.append(current)
        return result

    # No-space scripts (Thai, Japanese, etc.) — slice by character count
    return [text[i : i + max_chars] for i in range(0, len(text), max_chars)]


def generate_subtitles_from_scenes(
    scenes: list[dict],
    output_path: Path,
    max_chars_per_line: int | None = None,
) -> Path:
    """
    Build an SRT file from scene data, splitting each scene's text into
    short timed subtitle entries so only one line appears at a time.

    Each *scene* dict must contain ``scene_number``, ``text``,
    ``start_time`` (float seconds), and ``end_time`` (float seconds).

    *max_chars_per_line* defaults to ``settings.subtitle_max_chars_per_line``.
    """
    from app.config import settings

    if max_chars_per_line is None:
        max_chars_per_line = settings.subtitle_max_chars_per_line

    output_path.parent.mkdir(parents=True, exist_ok=True)

    srt_blocks: list[str] = []
    entry_idx = 1

    for s in scenes:
        scene_start: float = s["start_time"]
        scene_end: float   = s["end_time"]
        duration = max(scene_end - scene_start, 0.1)

        chunks = _split_text_to_lines(s["text"], max_chars_per_line)
        if not chunks:
            continue

        # Distribute scene duration evenly across all chunks
        chunk_dur = duration / len(chunks)
        for i, chunk in enumerate(chunks):
            chunk_start = scene_start + i * chunk_dur
            chunk_end   = chunk_start + chunk_dur
            srt_blocks.append(
                f"{entry_idx}\n"
                f"{_format_srt_time(chunk_start)} --> {_format_srt_time(chunk_end)}\n"
                f"{chunk}\n"
            )
            entry_idx += 1

    output_path.write_text("\n".join(srt_blocks), encoding="utf-8")
    logger.info(
        "Text-based subtitles -> %s (%d scenes → %d entries)",
        output_path.name, len(scenes), entry_idx - 1,
    )
    return output_path


# ── Audio-based subtitle generation ───────────────────────────────────────────


def generate_subtitles_from_audio(
    scenes: list[dict],
    output_path: Path,
) -> Path:
    """Build SRT using actual audio durations instead of estimated times.

    Each *scene* dict must contain ``scene_number``, ``text``,
    and ``voice_path`` (path to the audio file).
    Timing is calculated from actual audio file lengths.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    current_time = 0.0

    for s in scenes:
        voice_path = Path(s["voice_path"])
        duration = get_audio_duration(voice_path)

        start = _format_srt_time(current_time)
        end = _format_srt_time(current_time + duration)
        text = s["text"].strip()

        lines.append(f"{s['scene_number']}")
        lines.append(f"{start} --> {end}")
        lines.append(text)
        lines.append("")

        current_time += duration

    output_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info(
        "Audio-based subtitles -> %s (%d scenes, %.1fs total)",
        output_path.name, len(scenes), current_time,
    )
    return output_path
