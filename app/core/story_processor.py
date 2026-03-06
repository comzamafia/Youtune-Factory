"""Story Processor — Ingests novel text from files or DB, generates scenes."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from app.ai.script_generator import SceneData, get_script_generator
from app.ai.subtitle_generator import get_audio_duration
from app.core.models import Novel, Scene

logger = logging.getLogger(__name__)


# ── File Ingestion ─────────────────────────────────────────────────────────────


def read_novel_file(file_path: Path) -> str:
    """Read a novel from a text file. Supports .txt, .md, and any plain text."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Novel file not found: {path}")

    # Auto-detect encoding
    for encoding in ["utf-8", "utf-8-sig", "cp874", "tis-620", "latin-1"]:
        try:
            text = path.read_text(encoding=encoding)
            logger.info("Read novel file '%s' (%d chars, encoding=%s)", path.name, len(text), encoding)
            return text.strip()
        except (UnicodeDecodeError, UnicodeError):
            continue

    raise ValueError(f"Could not read file with any supported encoding: {path}")


async def ingest_novel_from_file(file_path: Path, db: Session) -> Novel:
    """Read a novel text file and create a Novel record in the database.

    Supports: .txt, .md, or any plain text file.
    Title is derived from the filename.
    """
    text = read_novel_file(file_path)
    title = file_path.stem.replace("_", " ").title()

    novel = Novel(title=title, text=text, status="pending")
    db.add(novel)
    db.commit()
    db.refresh(novel)
    logger.info("Ingested novel '%s' from %s (id=%s)", novel.title, file_path.name, novel.id)
    return novel


# ── Scene Processing ──────────────────────────────────────────────────────────


async def process_novel(novel_id: uuid.UUID, db: Session) -> list[Scene]:
    """
    Take a Novel from the database, send its text to the LLM for scene splitting,
    and persist the resulting Scene records.

    Returns the list of Scene ORM objects.
    """
    novel = db.query(Novel).filter(Novel.id == novel_id).first()
    if not novel:
        raise ValueError(f"Novel {novel_id} not found")

    novel.status = "processing"
    db.commit()

    try:
        generator = get_script_generator()
        scene_datas: list[SceneData] = await generator.generate_scenes(
            novel_text=novel.text,
            title=novel.title,
        )

        # Assign part numbers based on max_scenes_per_part
        from app.config import settings as _settings

        max_per_part = _settings.max_scenes_per_part
        scenes: list[Scene] = []
        current_time = 0.0
        current_part = 1
        scenes_in_part = 0

        for sd in scene_datas:
            # Move to next part if limit reached (0 = unlimited)
            if max_per_part > 0 and scenes_in_part >= max_per_part:
                current_part += 1
                scenes_in_part = 0
                current_time = 0.0  # reset timing for each part

            duration = 6.0  # default 6 sec per scene
            scene = Scene(
                novel_id=novel.id,
                scene_number=sd.scene_number,
                scene_text=sd.text,
                start_time=current_time,
                end_time=current_time + duration,
                image_prompt=sd.image_prompt,
                mood=sd.mood,
                part_number=current_part,
            )
            scenes.append(scene)
            current_time += duration
            scenes_in_part += 1

        db.add_all(scenes)
        db.commit()
        for s in scenes:
            db.refresh(s)

        logger.info(
            "Processed novel '%s' -> %d scenes in %d part(s)",
            novel.title,
            len(scenes),
            current_part,
        )
        return scenes

    except Exception:
        novel.status = "failed"
        db.commit()
        raise


def update_scene_timings_from_audio(scenes: list[Scene], db: Session) -> None:
    """Update scene start_time/end_time based on actual audio file durations.

    Call this AFTER voice generation to ensure subtitles match audio exactly.
    """
    current_time = 0.0
    for scene in scenes:
        if scene.voice_path:
            duration = get_audio_duration(Path(scene.voice_path))
        else:
            duration = scene.end_time - scene.start_time if scene.end_time else 6.0

        scene.start_time = current_time
        scene.end_time = current_time + duration
        current_time += duration

    db.commit()
    logger.info("Updated scene timings from audio: %.1f sec total", current_time)
