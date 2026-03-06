"""Centralized application settings loaded from environment variables."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration values, loaded from .env file or environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Paths ──────────────────────────────────────────────────────────
    root_path: Path = Path(__file__).resolve().parent.parent
    input_dir: str = "input"
    assets_dir: str = "assets"
    processing_dir: str = "processing"
    output_dir: str = "output"

    # ── Database ───────────────────────────────────────────────────────
    database_url: str = "postgresql://postgres:password@localhost:5432/aiyoutube"

    # ── Redis / Celery ─────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"

    # ── CORS ──────────────────────────────────────────────────────────
    # Comma-separated list of allowed origins, or "*" for development only
    cors_origins: str = "*"

    # ── API Security ───────────────────────────────────────────────────
    api_secret_key: str = "change-me-to-a-secure-random-string"
    admin_username: str = "admin"
    admin_password: str = "admin"

    # ── LLM ────────────────────────────────────────────────────────────
    llm_api_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = "ollama"
    llm_model: str = "qwen3.5"

    # ── TTS ────────────────────────────────────────────────────────────
    tts_engine: str = "edge_tts"  # coqui | elevenlabs | edge_tts
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = ""
    edge_tts_voice: str = "th-TH-PremwadeeNeural"  # Thai female (free)

    # ── Image Generation ───────────────────────────────────────────────
    image_engine: str = "stable_diffusion"  # stable_diffusion | comfyui | replicate | placeholder
    sd_api_url: str = "http://localhost:7860"
    comfyui_api_url: str = "http://localhost:8188"
    # Replicate API (cloud GPU — no local GPU needed, pay-per-use)
    replicate_api_key: str = ""
    replicate_model_id: str = "stability-ai/sdxl:39ed52f2319f9f5d3c65f7b5d7f756b8d5c5e5e5"

    # ── YouTube ────────────────────────────────────────────────────────
    youtube_client_secret_file: str = "client_secret.json"
    youtube_credentials_file: str = "youtube_credentials.json"
    # ── Video Dimensions ────────────────────────────────────────────────────
    # 1080x1920 = 9:16 vertical (YouTube Shorts / TikTok / Reels)
    # 1920x1080 = 16:9 horizontal (standard YouTube)
    video_width: int = 1080
    video_height: int = 1920
    # Subtitle font size (pixels). For 1080px-wide portrait: ~38px is readable
    # without covering the frame. For 1920px-wide landscape use ~28px.
    subtitle_font_size: int = 38
    # Max characters per subtitle line (controls wrapping before splitting to new SRT entry)
    subtitle_max_chars_per_line: int = 28
    # Vertical margin from the bottom edge of the frame (pixels)
    subtitle_margin_v: int = 80
    # ── GPU / FFmpeg ───────────────────────────────────────────────────
    use_gpu: bool = True
    ffmpeg_hwaccel: str = "cuda"
    ffmpeg_vcodec: str = "h264_nvenc"
    ffmpeg_max_workers: int = 4

    # ── Celery / Worker ────────────────────────────────────────────────
    # Set to false to run pipeline synchronously (no Celery/Redis needed)
    use_celery: bool = True

    # ── Long-Content / Multi-Part ──────────────────────────────────────
    # Maximum characters per LLM chunk (must fit model context window)
    llm_chunk_max_chars: int = 3000
    # Maximum scenes per video part (0 = unlimited / single video)
    max_scenes_per_part: int = 150
    # Maximum total scenes allowed for a single novel (safety limit)
    max_total_scenes: int = 3000
    # Celery concurrency limit for image tasks (prevents GPU OOM)
    image_task_concurrency: int = 2
    # Celery concurrency limit for voice tasks
    voice_task_concurrency: int = 4
    # Minimum free disk space in GB before starting render
    min_free_disk_gb: float = 10.0
    # Delete intermediate scene clips after final video is built
    cleanup_clips_after_build: bool = True

    # ── Helpers ────────────────────────────────────────────────────────
    @property
    def novels_dir(self) -> Path:
        return self.root_path / self.input_dir / "novels"

    @property
    def scripts_dir(self) -> Path:
        return self.root_path / self.input_dir / "scripts"

    @property
    def media_input_dir(self) -> Path:
        """Drop video clips (.mp4/.mov/.avi) and images (.jpg/.png) here.
        The pipeline will assign them to scenes in alternating order."""
        return self.root_path / self.input_dir / "media"

    @property
    def images_dir(self) -> Path:
        return self.root_path / self.assets_dir / "images"

    @property
    def music_dir(self) -> Path:
        return self.root_path / self.assets_dir / "music"

    @property
    def fonts_dir(self) -> Path:
        return self.root_path / self.assets_dir / "fonts"

    @property
    def scenes_dir(self) -> Path:
        return self.root_path / self.processing_dir / "scenes"

    @property
    def voice_dir(self) -> Path:
        return self.root_path / self.processing_dir / "voice"

    @property
    def subtitles_dir(self) -> Path:
        return self.root_path / self.processing_dir / "subtitles"

    @property
    def video_output_dir(self) -> Path:
        return self.root_path / self.output_dir / "video"

    @property
    def thumbnail_output_dir(self) -> Path:
        return self.root_path / self.output_dir / "thumbnail"

    def ensure_dirs(self) -> None:
        """Create all required directories if they don't exist."""
        dirs = [
            self.novels_dir,
            self.scripts_dir,
            self.media_input_dir,
            self.images_dir,
            self.music_dir,
            self.fonts_dir,
            self.scenes_dir,
            self.voice_dir,
            self.subtitles_dir,
            self.video_output_dir,
            self.thumbnail_output_dir,
            self.root_path / "database",
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)


# Singleton — import this everywhere
settings = Settings()
