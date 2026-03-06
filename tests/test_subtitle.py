"""Tests for the subtitle generator — validates SRT formatting."""

from __future__ import annotations

from pathlib import Path
import tempfile

from app.ai.subtitle_generator import (
    _format_srt_time,
    _split_text_to_lines,
    generate_subtitles_from_scenes,
)


def test_format_srt_time_zero():
    assert _format_srt_time(0.0) == "00:00:00,000"


def test_format_srt_time_seconds():
    assert _format_srt_time(5.5) == "00:00:05,500"


def test_format_srt_time_minutes():
    assert _format_srt_time(65.123) == "00:01:05,123"


def test_format_srt_time_hours():
    assert _format_srt_time(3661.0) == "01:01:01,000"


# ── _split_text_to_lines ───────────────────────────────────────────────────────


def test_split_short_text_stays_one_line():
    """Text shorter than max_chars should remain as a single entry."""
    result = _split_text_to_lines("Short text.", max_chars=28)
    assert result == ["Short text."]


def test_split_long_english_text():
    """Long English text is split on word boundaries into ≤ max_chars lines."""
    text = "The ancient temple stood silently in the dark forest waiting."
    result = _split_text_to_lines(text, max_chars=28)
    assert len(result) > 1
    for line in result:
        assert len(line) <= 28


def test_split_preserves_all_words():
    """No words are lost during splitting."""
    text = "The ancient temple stood silently in the dark forest waiting for dawn."
    result = _split_text_to_lines(text, max_chars=28)
    assert " ".join(result) == text


def test_split_thai_no_spaces():
    """Thai text (no spaces) is split by character count."""
    text = "ลึกในเทือกเขา วิหารโบราณรอการค้นพบมาพันปี"
    # Strip spaces for test of pure Thai char-count splitting
    text_nospace = "ลึกในเทือกเขาวิหารโบราณรอการค้นพบมาพันปี"
    result = _split_text_to_lines(text_nospace, max_chars=15)
    assert len(result) > 1
    for line in result:
        assert len(line) <= 15


def test_split_empty_returns_empty():
    assert _split_text_to_lines("", max_chars=28) == []


# ── generate_subtitles_from_scenes ────────────────────────────────────────────


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


def test_generate_subtitles_long_text_produces_multiple_entries():
    """A long scene text should be split into several SRT entries, each ≤ max_chars."""
    long_text = (
        "The ancient temple stood silently waiting in the dark forest "
        "as the thunder rolled across the mountains above."
    )
    scenes = [{"scene_number": 1, "text": long_text, "start_time": 0.0, "end_time": 12.0}]

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "long.srt"
        generate_subtitles_from_scenes(scenes, out, max_chars_per_line=28)
        content = out.read_text(encoding="utf-8")

    # Multiple numbered entries expected
    assert "1\n" in content
    assert "2\n" in content

    # All original words still present
    for word in ["ancient", "temple", "thunder", "mountains"]:
        assert word in content


def test_generate_subtitles_timing_covers_full_scene():
    """The last chunk's end time should equal the scene's end_time."""
    scenes = [
        {
            "scene_number": 1,
            "text": "Word one two three four five six seven eight nine ten.",
            "start_time": 3.0,
            "end_time": 9.0,
        }
    ]

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "timing.srt"
        generate_subtitles_from_scenes(scenes, out, max_chars_per_line=20)
        content = out.read_text(encoding="utf-8")

    # Scene started at 3.0 → first timestamp starts at 00:00:03,000
    assert "00:00:03,000" in content
    # Scene ends at 9.0 → last chunk ends at 00:00:09,000
    assert "00:00:09,000" in content

