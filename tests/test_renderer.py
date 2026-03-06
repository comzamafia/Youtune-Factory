"""Tests for the video renderer — validates FFmpeg command construction."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from app.video.renderer import _build_ffmpeg_image_cmd


def test_build_ffmpeg_cmd_with_gpu():
    """FFmpeg command includes GPU acceleration flags when enabled."""
    with patch("app.video.renderer.settings") as mock_settings:
        mock_settings.use_gpu = True
        mock_settings.ffmpeg_hwaccel = "cuda"
        mock_settings.ffmpeg_vcodec = "h264_nvenc"

        cmd = _build_ffmpeg_image_cmd(
            image_path=Path("scene_001.png"),
            audio_path=Path("scene_001.wav"),
            output_path=Path("scene_001.mp4"),
            duration=6.0,
        )

    assert "-hwaccel" in cmd
    assert "cuda" in cmd
    assert "h264_nvenc" in cmd
    assert "-t" in cmd
    assert "6.0" in cmd


def test_build_ffmpeg_cmd_without_gpu():
    """FFmpeg command uses libx264 when GPU is disabled."""
    with patch("app.video.renderer.settings") as mock_settings:
        mock_settings.use_gpu = False

        cmd = _build_ffmpeg_image_cmd(
            image_path=Path("img.png"),
            audio_path=Path("audio.wav"),
            output_path=Path("out.mp4"),
        )

    assert "libx264" in cmd
    assert "-shortest" in cmd
    assert "-hwaccel" not in cmd


def test_build_ffmpeg_cmd_has_required_flags():
    """All FFmpeg invocations include essential flags."""
    with patch("app.video.renderer.settings") as mock_settings:
        mock_settings.use_gpu = False

        cmd = _build_ffmpeg_image_cmd(
            image_path=Path("i.png"),
            audio_path=Path("a.wav"),
            output_path=Path("o.mp4"),
        )

    assert cmd[0] == "ffmpeg"
    assert "-y" in cmd
    assert "-loop" in cmd
    assert "1" in cmd
    assert "-pix_fmt" in cmd
    assert "yuv420p" in cmd
    assert "aac" in cmd
