"""Quick Test — Run the full pipeline directly without Celery/Redis.

Usage:
    python quick_test.py

This script:
1. Creates a short sample novel in SQLite DB
2. Sends it to Qwen3.5 (Ollama) for scene splitting
3. Generates voice with Edge TTS
4. Creates placeholder images with Pillow
5. Renders video clips with FFmpeg
6. Builds final video with subtitles
7. Skips YouTube upload

Requirements:
    - Ollama running with qwen3.5
    - FFmpeg installed
    - edge-tts installed
    - .env configured (SQLite mode)
"""

from __future__ import annotations

import asyncio
import logging
import sys
import os
import time
from pathlib import Path

# Fix Windows console encoding
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("quick_test")


async def main():
    print("")
    print("=" * 55)
    print("  QUICK TEST MODE - AI YouTube Novel Factory")
    print("  Pipeline: Novel > Script > Voice > Image > Video")
    print("=" * 55)
    print("")

    from app.config import settings
    from app.core.database import Base, SessionLocal, engine
    from app.core.models import Novel, Scene, Video

    # -- Step 0: Setup --
    logger.info("[SETUP] Setting up directories and database...")
    settings.ensure_dirs()
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    # -- Step 1: Create sample novel --
    sample_text = """
    The ancient forest stretched endlessly under a moonlit sky.
    Shadows danced between gnarled trees as an old traveler walked the forgotten path.
    He carried a lantern that flickered with an otherworldly blue flame.
    Deep in the forest, a ruined temple stood covered in vines and moss.
    The traveler pushed open the heavy stone door and stepped inside.
    A vast chamber opened before him, filled with golden light from an unknown source.
    In the center stood a crystal pedestal holding a glowing red gemstone.
    As he reached for the gem, whispers filled the air, warning him of the curse.
    But the traveler smiled. He had come too far to turn back now.
    He grasped the gemstone, and the temple began to tremble.
    """.strip()

    novel = Novel(
        title="The Cursed Temple",
        author="AI Writer",
        text=sample_text,
        status="pending",
    )
    db.add(novel)
    db.commit()
    db.refresh(novel)
    logger.info("[OK] Novel created: '%s' (id=%s)", novel.title, novel.id)

    # -- Step 2: Generate scenes with LLM --
    logger.info("[LLM] Generating scenes with %s...", settings.llm_model)
    start = time.perf_counter()

    try:
        from app.core.story_processor import process_novel
        scenes = await process_novel(novel.id, db)
        elapsed = time.perf_counter() - start
        logger.info("[OK] %d scenes generated in %.1fs", len(scenes), elapsed)
    except Exception as e:
        logger.error("[FAIL] Scene generation failed: %s", e)
        logger.error("  Make sure Ollama is running: ollama serve")
        logger.error("  And qwen3.5 is pulled: ollama pull qwen3.5")
        db.close()
        return

    # -- Step 3: Generate voice for each scene --
    logger.info("[TTS] Generating voice with Edge TTS (%s)...", settings.edge_tts_voice)
    from app.ai.voice_generator import get_voice_generator
    voice_gen = get_voice_generator()

    for scene in scenes:
        output_path = settings.voice_dir / f"scene_{scene.scene_number:03d}.mp3"
        try:
            await voice_gen.generate(scene.scene_text, output_path)
            scene.voice_path = str(output_path)
        except Exception as e:
            logger.error("[FAIL] Voice gen failed for scene %d: %s", scene.scene_number, e)
            db.close()
            return
    db.commit()
    logger.info("[OK] Voice generated for %d scenes", len(scenes))

    # -- Step 4: Generate images for each scene --
    logger.info("[IMG] Generating placeholder images...")
    from app.ai.image_generator import get_image_generator
    img_gen = get_image_generator()

    for scene in scenes:
        output_path = settings.scenes_dir / f"scene_{scene.scene_number:03d}.png"
        prompt = scene.image_prompt or scene.scene_text
        try:
            await img_gen.generate(prompt, output_path)
            scene.image_path = str(output_path)
        except Exception as e:
            logger.error("[FAIL] Image gen failed for scene %d: %s", scene.scene_number, e)
            db.close()
            return
    db.commit()
    logger.info("[OK] Images generated for %d scenes", len(scenes))

    # -- Step 5: Generate subtitles --
    logger.info("[SUB] Generating subtitles...")
    from app.ai.subtitle_generator import generate_subtitles_from_scenes

    subtitle_path = settings.subtitles_dir / f"{novel.title.replace(' ', '_')}.srt"
    scene_dicts = [
        {
            "scene_number": s.scene_number,
            "text": s.scene_text,
            "start_time": s.start_time or 0.0,
            "end_time": s.end_time or 6.0,
        }
        for s in scenes
    ]
    generate_subtitles_from_scenes(scene_dicts, subtitle_path)
    logger.info("[OK] Subtitles -> %s", subtitle_path.name)

    # -- Step 6: Render scene clips --
    logger.info("[RENDER] Rendering scene clips with FFmpeg...")
    from app.video.renderer import render_scene

    clip_paths = []
    for scene in scenes:
        clip_path = settings.scenes_dir / f"clip_{scene.scene_number:03d}.mp4"
        duration = (scene.end_time or 6.0) - (scene.start_time or 0.0)
        try:
            render_scene(
                image_path=Path(scene.image_path),
                audio_path=Path(scene.voice_path),
                output_path=clip_path,
                duration=duration,
            )
            scene.clip_path = str(clip_path)
            clip_paths.append(clip_path)
        except Exception as e:
            logger.error("[FAIL] Render failed for scene %d: %s", scene.scene_number, e)
            logger.error("  Make sure FFmpeg is installed: winget install ffmpeg")
            db.close()
            return
    db.commit()
    logger.info("[OK] Rendered %d scene clips", len(clip_paths))

    # -- Step 7: Build final video --
    logger.info("[BUILD] Building final video...")
    from app.video.builder import build_final_video

    final_path = settings.video_output_dir / f"{novel.title.replace(' ', '_')}.mp4"
    try:
        build_final_video(
            scene_clips=clip_paths,
            output_path=final_path,
            subtitle_path=subtitle_path,
        )
    except Exception as e:
        logger.error("[FAIL] Video build failed: %s", e)
        db.close()
        return

    # -- Step 8: Update DB --
    video = Video(
        novel_id=novel.id,
        video_path=str(final_path),
        subtitle_path=str(subtitle_path),
        status="rendered",
    )
    db.add(video)
    novel.status = "completed"
    db.commit()

    db.close()

    # -- Done! --
    total_time = time.perf_counter() - start
    print("")
    print("=" * 55)
    print("  PIPELINE COMPLETE!")
    print("=" * 55)
    print(f"  Video:     {final_path}")
    print(f"  Subtitles: {subtitle_path}")
    print(f"  Scenes:    {len(scenes)}")
    print(f"  Time:      {total_time:.1f}s")
    print("=" * 55)
    print("")


if __name__ == "__main__":
    asyncio.run(main())
