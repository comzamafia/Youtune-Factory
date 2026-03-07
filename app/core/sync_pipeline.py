"""Synchronous pipeline — runs all stages in a background thread (no Celery needed).

Used when ``USE_CELERY=false`` (e.g. single-dyno Railway deploys without a
separate worker service).  The API still returns immediately with a job ID;
the actual work happens on a daemon thread.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings
from app.core.database import SessionLocal
from app.core.models import Job, Novel, Scene, Video
from app.core.story_processor import assign_media_to_scenes
from app.core.utils import safe_filename

logger = logging.getLogger(__name__)


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _set_job(db, job_id: uuid.UUID, status: str, error: str | None = None, step: str | None = None):
    job = db.query(Job).filter(Job.job_id == job_id).first()
    if not job:
        return
    job.status = status
    now = datetime.now(timezone.utc)
    if status == "running":
        job.started_at = now
    if status in ("completed", "failed"):
        job.finished_at = now
    if error:
        job.error_message = error
    if step is not None:
        job.current_step = step
    db.commit()


# ── Public entry point ────────────────────────────────────────────────────────

def run_pipeline_sync(novel_id: str | uuid.UUID) -> str:
    """Create a pipeline job and start the sync pipeline on a daemon thread.

    Returns the job ID immediately.
    """
    nid = uuid.UUID(str(novel_id))
    db = SessionLocal()
    try:
        job = Job(novel_id=nid, job_type="full_pipeline", status="queued")
        db.add(job)
        db.commit()
        db.refresh(job)
        job_id = job.job_id
    finally:
        db.close()

    t = threading.Thread(
        target=_pipeline_thread,
        args=(str(nid), str(job_id)),
        daemon=True,
        name=f"pipeline-{nid}",
    )
    t.start()
    logger.info("Sync pipeline started for novel %s (job=%s)", nid, job_id)
    return str(job_id)


# ── Pipeline thread ──────────────────────────────────────────────────────────

def _pipeline_thread(novel_id: str, job_id: str):
    """Run all pipeline stages sequentially."""
    nid = uuid.UUID(novel_id)
    jid = uuid.UUID(job_id)
    db = SessionLocal()
    try:
        _set_job(db, jid, "running", step="1/6 สร้างบทจากนิยาย…")

        novel = db.query(Novel).filter(Novel.id == nid).first()
        if not novel:
            _set_job(db, jid, "failed", "Novel not found")
            return

        novel.status = "processing"
        db.commit()

        # ── Cleanup: Delete old scenes/videos from previous runs ─────
        old_scenes = db.query(Scene).filter(Scene.novel_id == nid).all()
        if old_scenes:
            logger.info("[sync] Deleting %d old scenes from previous run", len(old_scenes))
            for s in old_scenes:
                db.delete(s)
            db.commit()
        old_videos = db.query(Video).filter(Video.novel_id == nid).all()
        for v in old_videos:
            db.delete(v)
        if old_videos:
            db.commit()

        # ── Step 1: Generate script (LLM scene splitting) ────────────
        logger.info("[sync] Step 1/6: Generating script for '%s'…", novel.title)
        from app.core.story_processor import process_novel
        scenes = _run_async(process_novel(nid, db))
        logger.info("[sync] Script done — %d scenes created.", len(scenes))

        # Reload scenes from DB (process_novel committed them)
        scenes = (
            db.query(Scene)
            .filter(Scene.novel_id == nid)
            .order_by(Scene.scene_number)
            .all()
        )
        if not scenes:
            _set_job(db, jid, "failed", "No scenes after script generation")
            novel.status = "failed"
            db.commit()
            return

        # Assign user-supplied media
        assign_media_to_scenes(scenes, db, novel_id=novel_id)

        # ── Step 2: Generate voice (TTS) ─────────────────────────────        _set_job(db, jid, "running", step="2/6 สร้างเสียงพากย์…")        logger.info("[sync] Step 2/6: Generating voice for %d scenes…", len(scenes))
        from app.ai.voice_generator import get_voice_generator
        voice_gen = get_voice_generator()
        # edge_tts produces MP3; other engines may produce WAV
        voice_ext = ".mp3" if settings.tts_engine.lower() == "edge_tts" else ".wav"
        for s in scenes:
            out = settings.voice_dir / f"scene_{s.scene_number:04d}{voice_ext}"
            _run_async(voice_gen.generate(s.scene_text, out))
            if not out.exists() or out.stat().st_size < 100:
                raise RuntimeError(f"Voice file empty or missing: {out} (text: {s.scene_text[:50]})")
            s.voice_path = str(out)
            logger.info("[sync] Voice scene %d: %d bytes", s.scene_number, out.stat().st_size)
        db.commit()
        logger.info("[sync] Voice done.")

        # ── Step 3: Generate images ──────────────────────────────────        _set_job(db, jid, "running", step="3/6 สร้างภาพ…")        logger.info("[sync] Step 3/6: Generating images…")
        from app.ai.image_generator import get_image_generator
        img_gen = get_image_generator()
        for s in scenes:
            if s.image_path or s.video_source_path:
                continue  # user-supplied media
            out = settings.scenes_dir / f"scene_{s.scene_number:04d}.png"
            _run_async(img_gen.generate(s.image_prompt or s.scene_text, out))
            s.image_path = str(out)
        db.commit()
        logger.info("[sync] Images done.")

        # ── Step 4: Update scene timings ─────────────────────────────        _set_job(db, jid, "running", step="4/6 คำนวณเวลา…")        logger.info("[sync] Step 4/6: Updating timings…")
        from app.core.story_processor import update_scene_timings_from_audio
        update_scene_timings_from_audio(scenes, db)
        logger.info("[sync] Timings done.")

        # ── Step 5: Render video (per part) ──────────────────────────
        _set_job(db, jid, "running", step="5/6 เรนเดอร์วิดีโอ…")
        logger.info("[sync] Step 5/6: Rendering video…")
        from app.ai.subtitle_generator import generate_subtitles_from_scenes
        from app.video.builder import build_final_video
        from app.video.renderer import render_scenes_parallel

        part_groups: dict[int, list[Scene]] = {}
        for s in scenes:
            part_groups.setdefault(s.part_number, []).append(s)

        total_parts = len(part_groups)
        is_multipart = total_parts > 1

        for part_num, part_scenes in sorted(part_groups.items()):
            # Render clips
            render_data = []
            for s in part_scenes:
                clip = settings.scenes_dir / f"clip_{s.scene_number:04d}.mp4"
                render_data.append({
                    "image_path": s.image_path,
                    "video_source_path": s.video_source_path,
                    "audio_path": s.voice_path,
                    "output_path": str(clip),
                    "duration": (s.end_time or 6.0) - (s.start_time or 0.0),
                    "scene_index": s.scene_number - 1,
                })
            clip_paths = render_scenes_parallel(render_data, max_workers=1)

            for s, cp in zip(part_scenes, clip_paths):
                s.clip_path = str(cp)
            db.commit()

            # Subtitles
            safe_title = safe_filename(novel.title)
            part_suffix = f"_part{part_num}" if is_multipart else ""
            sub_path = settings.subtitles_dir / f"{safe_title}{part_suffix}.srt"
            generate_subtitles_from_scenes(
                [{"scene_number": s.scene_number, "text": s.scene_text,
                  "start_time": s.start_time or 0.0, "end_time": s.end_time or 6.0}
                 for s in part_scenes],
                sub_path,
            )

            # Build
            vid_name = f"{safe_title}{part_suffix}.mp4"
            vid_path = settings.video_output_dir / vid_name
            music_files = list(settings.music_dir.glob("*.mp3")) + list(settings.music_dir.glob("*.wav"))
            if not music_files:
                from app.ai.music_generator import generate_ambient_music
                ambient = generate_ambient_music(settings.music_dir / "ambient_bg.wav")
                music_files = [ambient]
            build_final_video(
                scene_clips=clip_paths,
                output_path=vid_path,
                subtitle_path=sub_path,
                music_path=music_files[0] if music_files else None,
            )

            # Build 16:9 horizontal version (pillarbox)
            from app.video.builder import build_16x9_from_vertical
            vid_path_16x9 = settings.video_output_dir / f"{safe_title}{part_suffix}_16x9.mp4"
            try:
                build_16x9_from_vertical(vid_path, vid_path_16x9)
            except Exception as e16:
                logger.warning("[sync] 16:9 conversion failed (non-fatal): %s", e16)
                vid_path_16x9 = None

            # DB video record
            video = db.query(Video).filter(
                Video.novel_id == nid, Video.part_number == part_num
            ).first()
            if not video:
                video = Video(novel_id=nid, part_number=part_num)
                db.add(video)
            video.video_path = str(vid_path)
            if vid_path_16x9:
                video.video_path_16x9 = str(vid_path_16x9)
            video.subtitle_path = str(sub_path)
            video.status = "rendered"
            db.commit()

            # Cleanup
            if settings.cleanup_clips_after_build:
                for cp in clip_paths:
                    try:
                        Path(cp).unlink(missing_ok=True)
                    except OSError:
                        pass

            logger.info("[sync] Part %d/%d rendered → %s", part_num, total_parts, vid_path)

        # ── Step 6: Thumbnail ────────────────────────────────────────
        _set_job(db, jid, "running", step="6/6 สร้างรูปปก…")
        logger.info("[sync] Step 6/6: Generating thumbnail…")
        from app.ai.thumbnail_generator import generate_thumbnail
        for part_num in sorted(part_groups.keys()):
            first = part_groups[part_num][0]
            safe_title = safe_filename(novel.title)
            part_suffix = f"_part{part_num}" if is_multipart else ""
            thumb_path = settings.thumbnail_output_dir / f"{safe_title}{part_suffix}_thumb.jpg"
            title_text = f"{novel.title} (Part {part_num})" if is_multipart else novel.title
            _run_async(generate_thumbnail(
                title=title_text,
                image_prompt=first.image_prompt or f"cinematic scene: {novel.title}",
                output_path=thumb_path,
            ))
            video = db.query(Video).filter(
                Video.novel_id == nid, Video.part_number == part_num
            ).first()
            if video:
                video.thumbnail = str(thumb_path)
        db.commit()
        logger.info("[sync] Thumbnail done.")

        # ── Done ─────────────────────────────────────────────────────
        novel.status = "completed"
        db.commit()
        _set_job(db, jid, "completed")
        logger.info("[sync] Pipeline completed for '%s'!", novel.title)

    except Exception as exc:
        logger.exception("[sync] Pipeline failed for novel %s: %s", novel_id, exc)
        _set_job(db, jid, "failed", str(exc)[:1000])
        try:
            novel = db.query(Novel).filter(Novel.id == nid).first()
            if novel:
                novel.status = "failed"
                db.commit()
        except Exception:
            pass
    finally:
        db.close()
