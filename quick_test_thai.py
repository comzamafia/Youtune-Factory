"""Quick Test (Thai) — ทดสอบ Pipeline ด้วยนิยายภาษาไทย (Audio-based subtitles)

Usage:
    python quick_test_thai.py                          # ใช้ sample text ในตัว
    python quick_test_thai.py input/novels/mynovel.txt  # อ่านจากไฟล์ text
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("quick_test_thai")

# ── Thai Sample Novel ──────────────────────────────────────────────────────────

THAI_NOVEL = """
คืนนั้นท้องฟ้ามืดสนิท ดวงจันทร์ถูกเมฆหนาบดบัง
ชายหนุ่มนามว่า "สมชาย" เดินลัดเลาะไปตามทางในป่าลึก
เขาถือตะเกียงดวงเก่าที่ส่องแสงสีฟ้าประหลาด
เสียงลมหวีดหวิวผ่านต้นไม้ใหญ่ ราวกับมีใครกระซิบเรียก
ทันใดนั้นเขาก็มาถึงวิหารร้างที่ซ่อนอยู่กลางป่า
ผนังหินเก่าแก่ปกคลุมด้วยเถาวัลย์และตะไคร่น้ำ
สมชายผลักประตูหินหนักเข้าไปข้างใน
ห้องโถงกว้างใหญ่เปิดกว้างต่อหน้าเขา รายล้อมด้วยแสงทองจากแหล่งที่ไม่รู้จัก
ตรงกลางห้องมีแท่นคริสตัลวางอัญมณีสีแดงเรืองแสง
เมื่อเขาเอื้อมมือไปหยิบ เสียงกระซิบดังขึ้นทั่วห้อง เตือนเรื่องคำสาป
แต่สมชายยิ้ม เขามาไกลเกินกว่าจะหันหลังกลับแล้ว
เขาคว้าอัญมณี และวิหารก็เริ่มสั่นสะเทือน
""".strip()


async def main():
    print("")
    print("=" * 55)
    print("  QUICK TEST (THAI) - AI YouTube Novel Factory")
    print("  Pipeline: Novel > Script > Voice > Image > Video")
    print("=" * 55)
    print("")

    from app.config import settings
    from app.core.database import Base, SessionLocal, engine
    from app.core.models import Novel, Scene, Video

    # -- Setup --
    logger.info("[SETUP] Setting up...")
    settings.ensure_dirs()
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    # -- Read novel: from file arg or built-in sample --
    if len(sys.argv) > 1:
        input_file = Path(sys.argv[1])
        logger.info("[INPUT] Reading novel from file: %s", input_file)
        from app.core.story_processor import read_novel_file
        novel_text = read_novel_file(input_file)
        title = input_file.stem.replace("_", " ").title()
    else:
        logger.info("[INPUT] Using built-in Thai sample novel")
        novel_text = THAI_NOVEL
        title = "วิหารแห่งคำสาป"

    novel = Novel(
        title=title,
        author="AI Writer",
        text=novel_text,
        status="pending",
    )
    db.add(novel)
    db.commit()
    db.refresh(novel)
    logger.info("[OK] Novel: '%s' (%d chars)", novel.title, len(novel_text))

    # -- Step 1: Generate scenes with LLM --
    logger.info("[LLM] Generating scenes with %s...", settings.llm_model)
    start = time.perf_counter()

    try:
        from app.core.story_processor import process_novel
        scenes = await process_novel(novel.id, db)
        elapsed = time.perf_counter() - start
        logger.info("[OK] %d scenes generated in %.1fs", len(scenes), elapsed)
        for s in scenes:
            logger.info("  Scene %d: %s", s.scene_number, s.scene_text[:60])
    except Exception as e:
        logger.error("[FAIL] Scene generation failed: %s", e)
        import traceback
        traceback.print_exc()
        db.close()
        return

    # -- Step 2: Generate voice (Thai) --
    logger.info("[TTS] Generating voice with Edge TTS (%s)...", settings.edge_tts_voice)
    from app.ai.voice_generator import get_voice_generator
    voice_gen = get_voice_generator()

    for scene in scenes:
        output_path = settings.voice_dir / f"thai_scene_{scene.scene_number:03d}.mp3"
        try:
            await voice_gen.generate(scene.scene_text, output_path)
            scene.voice_path = str(output_path)
        except Exception as e:
            logger.error("[FAIL] Voice gen failed for scene %d: %s", scene.scene_number, e)
            db.close()
            return
    db.commit()
    logger.info("[OK] Voice generated for %d scenes", len(scenes))

    # -- Step 3: Update timing from actual audio durations --
    logger.info("[TIMING] Updating scene timing from audio durations...")
    from app.core.story_processor import update_scene_timings_from_audio
    update_scene_timings_from_audio(scenes, db)

    # -- Step 4: Generate images --
    logger.info("[IMG] Generating placeholder images...")
    from app.ai.image_generator import get_image_generator
    img_gen = get_image_generator()

    for scene in scenes:
        output_path = settings.scenes_dir / f"thai_scene_{scene.scene_number:03d}.png"
        prompt = scene.image_prompt or scene.scene_text
        try:
            await img_gen.generate(prompt, output_path)
            scene.image_path = str(output_path)
        except Exception as e:
            logger.error("[FAIL] Image gen failed: %s", e)
            db.close()
            return
    db.commit()
    logger.info("[OK] %d images generated", len(scenes))

    # -- Step 4b: Generate Thumbnail --
    logger.info("[THUMB_GEN] Generating thumbnail...")
    from app.ai.thumbnail_generator import generate_thumbnail

    thumb_path = settings.thumbnail_output_dir / "thumbnail.jpg"
    try:
        await generate_thumbnail(
            title=novel.title,
            image_prompt=scenes[0].image_prompt or scenes[0].scene_text,
            output_path=thumb_path,
        )
        logger.info("[OK] Thumbnail generated at %s", thumb_path)
    except Exception as e:
        logger.error("[FAIL] Thumbnail gen failed: %s", e)
        # Note: We don't abort the pipeline if thumbnail fails

    # -- Step 5: Generate subtitles from AUDIO timing --
    logger.info("[SUB] Generating subtitles (audio-based timing)...")
    from app.ai.subtitle_generator import generate_subtitles_from_audio

    subtitle_path = settings.subtitles_dir / "thai_novel.srt"
    scene_dicts = [
        {
            "scene_number": s.scene_number,
            "text": s.scene_text,
            "voice_path": s.voice_path,
        }
        for s in scenes
    ]
    generate_subtitles_from_audio(scene_dicts, subtitle_path)
    logger.info("[OK] Subtitles -> %s", subtitle_path.name)

    # -- Step 6: Render clips (use actual audio duration) --
    logger.info("[RENDER] Rendering scene clips...")
    from app.video.renderer import render_scene

    clip_paths = []
    for scene in scenes:
        clip_path = settings.scenes_dir / f"thai_clip_{scene.scene_number:03d}.mp4"
        duration = scene.end_time - scene.start_time
        try:
            scene_dict = {
                "image_path": scene.image_path,
                "audio_path": scene.voice_path,
                "duration": duration,
                "scene_index": scene.scene_number - 1,
            }
            render_scene(scene_dict, clip_path)
            clip_paths.append(clip_path)
        except Exception as e:
            logger.error("[FAIL] Render failed: %s", e)
            db.close()
            return
    db.commit()
    logger.info("[OK] Rendered %d clips", len(clip_paths))

    # -- Step 7: Build final video --
    logger.info("[BUILD] Building final video...")
    from app.video.builder import build_final_video

    final_path = settings.video_output_dir / "thai_novel.mp4"
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

    # -- Done --
    video = Video(
        novel_id=novel.id,
        video_path=str(final_path),
        subtitle_path=str(subtitle_path),
        status="rendered",
    )
    db.add(video)
    novel.status = "completed"
    db.commit()

    # Capture stats before closing session
    num_scenes = len(scenes)
    total_duration = sum(s.end_time - s.start_time for s in scenes)
    db.close()

    total_time = time.perf_counter() - start
    print("")
    print("=" * 55)
    print("  PIPELINE COMPLETE! (Thai Novel)")
    print("=" * 55)
    print(f"  Video:     {final_path}")
    print(f"  Subtitles: {subtitle_path}")
    if 'thumb_path' in locals() and thumb_path.exists():
        print(f"  Thumbnail: {thumb_path}")
    print(f"  Scenes:    {num_scenes}")
    print(f"  Duration:  {total_duration:.1f}s (from audio)")
    print(f"  Time:      {total_time:.1f}s")
    print("=" * 55)
    print("")


if __name__ == "__main__":
    asyncio.run(main())
