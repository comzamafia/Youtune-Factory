"""Ambient background music generator — creates a soft pad using pure Python."""

from __future__ import annotations

import logging
import math
import struct
import wave
from pathlib import Path

logger = logging.getLogger(__name__)

# Chord frequencies for a soft Am pad (A2, E3, A3, C4)
_CHORD = [110.0, 164.81, 220.0, 261.63]
_SAMPLE_RATE = 44100


def generate_ambient_music(output_path: Path, duration_sec: int = 300) -> Path:
    """Generate a soft ambient background track (WAV).

    Creates a gentle chord pad with slow volume modulation.
    Default duration: 5 minutes (enough for most short videos).
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if output_path.exists() and output_path.stat().st_size > 1000:
        logger.info("Ambient music already exists: %s", output_path)
        return output_path

    logger.info("Generating %ds ambient music → %s", duration_sec, output_path)

    n_samples = _SAMPLE_RATE * duration_sec
    # Pre-compute per-sample amplitude (soft envelope with slow modulation)
    # Base amplitude kept low — the builder's music_volume (0.1) further reduces it
    base_amp = 3000  # out of 32767 — intentionally quiet

    with wave.open(str(output_path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(_SAMPLE_RATE)

        # Write in chunks to avoid high memory usage
        chunk_size = _SAMPLE_RATE  # 1 second per chunk
        for chunk_start in range(0, n_samples, chunk_size):
            chunk_end = min(chunk_start + chunk_size, n_samples)
            frames = bytearray()

            for i in range(chunk_start, chunk_end):
                t = i / _SAMPLE_RATE
                # Slow volume modulation (breathing effect)
                mod = 0.7 + 0.3 * math.sin(2.0 * math.pi * 0.08 * t)
                # Sum chord tones with slight detuning for warmth
                sample = 0.0
                for freq in _CHORD:
                    sample += math.sin(2.0 * math.pi * freq * t)
                    sample += 0.3 * math.sin(2.0 * math.pi * freq * 1.002 * t)

                # Normalize by number of voices
                sample /= len(_CHORD) * 1.3
                # Apply modulation and amplitude
                val = int(sample * mod * base_amp)
                val = max(-32767, min(32767, val))
                frames.extend(struct.pack("<h", val))

            wf.writeframes(bytes(frames))

    logger.info("Ambient music generated: %s (%d bytes)", output_path.name, output_path.stat().st_size)
    return output_path
