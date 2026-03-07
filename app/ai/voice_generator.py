"""Voice Generator — Text-to-Speech engines for scene narration."""

from __future__ import annotations

import asyncio
import logging
import re
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


def clean_tts_text(text: str) -> str:
    """Clean text before sending to TTS to avoid unnatural pauses and odd speech.

    Removes/replaces characters that cause Edge TTS to stutter or pause:
    - Parentheses (cause pause before/after)
    - Smart quotes and special quote marks
    - Ellipsis and multiple dots → single pause
    - Markdown formatting symbols
    - Multiple spaces/newlines → single space
    """
    # Remove content in parentheses that adds context notes, not narration
    # e.g. "(เช่น ...)" → remove entirely if standalone, else keep content
    text = re.sub(r'\(([^)]{0,30})\)', r'\1', text)   # short parens → keep content
    text = re.sub(r'\([^)]+\)', '', text)              # long parens → remove

    # Smart/curly quotes → straight
    text = text.replace('\u201c', '').replace('\u201d', '')  # " "
    text = text.replace('\u2018', '').replace('\u2019', '')  # ' '
    text = text.replace('\u300c', '').replace('\u300d', '')  # 「 」
    text = text.replace('\u2039', '').replace('\u203a', '')  # ‹ ›

    # Ellipsis → comma pause (reads more naturally)
    text = text.replace('…', ',')
    text = re.sub(r'\.{2,}', ',', text)

    # Remove markdown bold/italic
    text = re.sub(r'\*+', '', text)
    text = re.sub(r'_+', '', text)

    # Collapse multiple spaces/newlines → single space
    text = re.sub(r'[\r\n\t]+', ' ', text)
    text = re.sub(r' {2,}', ' ', text)

    return text.strip()


class VoiceGeneratorBase(ABC):
    """Interface for TTS engines."""

    @abstractmethod
    async def generate(self, text: str, output_path: Path) -> Path:
        """Generate audio from *text* and save to *output_path*. Returns the path."""
        ...


# ── Coqui TTS ─────────────────────────────────────────────────────────────────


class CoquiVoiceGenerator(VoiceGeneratorBase):
    """Uses Coqui TTS (XTTS v2) via the ``tts`` CLI or Python API."""

    def __init__(self, model_name: str = "tts_models/multilingual/multi-dataset/xtts_v2"):
        self.model_name = model_name

    async def generate(self, text: str, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            "tts",
            "--text", text,
            "--model_name", self.model_name,
            "--out_path", str(output_path),
        ]
        logger.info("Coqui TTS → %s", output_path.name)
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if proc.returncode != 0:
            logger.error("TTS failed: %s", proc.stderr)
            raise RuntimeError(f"Coqui TTS error: {proc.stderr}")
        return output_path


# ── ElevenLabs ─────────────────────────────────────────────────────────────────


class ElevenLabsVoiceGenerator(VoiceGeneratorBase):
    """Uses the ElevenLabs REST API for high-quality voice synthesis."""

    API_URL = "https://api.elevenlabs.io/v1/text-to-speech"

    def __init__(
        self,
        api_key: str | None = None,
        voice_id: str | None = None,
    ):
        self.api_key = api_key or settings.elevenlabs_api_key
        self.voice_id = voice_id or settings.elevenlabs_voice_id

    async def generate(self, text: str, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{self.API_URL}/{self.voice_id}",
                json={
                    "text": text,
                    "model_id": "eleven_multilingual_v2",
                    "voice_settings": {
                        "stability": 0.5,
                        "similarity_boost": 0.75,
                    },
                },
                headers={
                    "xi-api-key": self.api_key,
                    "Content-Type": "application/json",
                    "Accept": "audio/mpeg",
                },
            )
            resp.raise_for_status()

        output_path.write_bytes(resp.content)
        logger.info("ElevenLabs TTS → %s (%d bytes)", output_path.name, len(resp.content))
        return output_path


# ── Edge TTS (Free, Microsoft) ─────────────────────────────────────────────────


class EdgeTTSVoiceGenerator(VoiceGeneratorBase):
    """Uses Microsoft Edge TTS — free, no API key, excellent multilingual support.

    Popular voices:
        - Thai: th-TH-PremwadeeNeural (female), th-TH-NiwatNeural (male)
        - English: en-US-AriaNeural, en-US-GuyNeural
        - Japanese: ja-JP-NanamiNeural
    """

    def __init__(self, voice: str | None = None):
        self.voice = voice or settings.edge_tts_voice

    async def generate(self, text: str, output_path: Path) -> Path:
        import edge_tts

        output_path.parent.mkdir(parents=True, exist_ok=True)

        cleaned = clean_tts_text(text)
        if not cleaned:
            cleaned = text.strip()

        communicate = edge_tts.Communicate(cleaned, self.voice)
        await communicate.save(str(output_path))

        logger.info("Edge TTS (%s) → %s", self.voice, output_path.name)
        return output_path


# ── Factory ────────────────────────────────────────────────────────────────────


def get_voice_generator() -> VoiceGeneratorBase:
    """Return the configured TTS engine."""
    engine = settings.tts_engine.lower()
    if engine == "elevenlabs":
        return ElevenLabsVoiceGenerator()
    if engine == "edge_tts":
        return EdgeTTSVoiceGenerator()
    return CoquiVoiceGenerator()
