"""Tests for the subtitle generator — validates SRT formatting."""

from __future__ import annotations

from pathlib import Path
import tempfile

from app.ai.subtitle_generator import _format_srt_time, generate_subtitles_from_scenes


def test_format_srt_time_zero():
    assert _format_srt_time(0.0) == "00:00:00,000"


def test_format_srt_time_seconds():
    assert _format_srt_time(5.5) == "00:00:05,500"


def test_format_srt_time_minutes():
    assert _format_srt_time(65.123) == "00:01:05,123"


def test_format_srt_time_hours():
    assert _format_srt_time(3661.0) == "01:01:01,000"


def test_generate_subtitles_from_scenes_creates_srt():
    """Generates a valid SRT file from scene data."""
    scenes = [
        {"scene_number": 1, "text": "The night was dark.", "start_time": 0.0, "end_time": 5.0},
        {"scene_number": 2, "text": "A shadow appeared.", "start_time": 5.0, "end_time": 11.0},
    ]

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "test.srt"
        result = generate_subtitles_from_scenes(scenes, out)

        assert result.exists()
        content = result.read_text(encoding="utf-8")

        assert "1" in content
        assert "00:00:00,000 --> 00:00:05,000" in content
        assert "The night was dark." in content
        assert "2" in content
        assert "00:00:05,000 --> 00:00:11,000" in content
        assert "A shadow appeared." in content
