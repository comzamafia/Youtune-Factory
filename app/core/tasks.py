"""Celery tasks — one per pipeline stage with retry logic."""

from __future__ import annotations

import asyncio
import logging
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings
from app.core.celery_app import celery_app
from app.core.database import SessionLocal
from app.core.models import Job, Novel, Scene, Video
from app.core.utils import safe_filename

logger = logging.getLogger(__name__)


def _run_async(coro):
    """Helper to run an async function from sync Celery task."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _update_job(job_id: uuid.UUID, status: str, error_message: str | None = None):
    """Update a Job record's status."""
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.job_id == job_id).first()
        if job:
            job.status = status
            if status == "running":
                job.started_at = datetime.now(timezone.utc)
            if status in ("completed", "failed"):
                job.finished_at = datetime.now(timezone.utc)
            if error_message:
                job.error_message = error_message
            db.commit()
    finally:
        db.close()


def _check_disk_space() -> None:
    """Raise if free disk space is below the configured minimum."""
    disk = shutil.disk_usage(settings.root_path)
    free_gb = disk.free / (1024 ** 3)
    if free_gb < settings.min_free_disk_gb:
        raise RuntimeError(
            f"Insufficient disk space: {free_gb:.1f} GB free, "
            f"need at least {settings.min_free_disk_gb} GB"
        )


# ──────────────────────────────────────────────────────────────────────────────
# Task: Generate Script (scene splitting)
# ──────────────────────────────────────────────────────────────────────────────


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def task_generate_script(self, novel_id: str, job_id: str | None = None):
    """Split a novel into scenes using the LLM."""
    from app.core.story_processor import process_novel

    nid = uuid.UUID(novel_id)
    jid = uuid.UUID(job_id) if job_id else None
    if jid:
        _update_job(jid, "running")

    try:
        db = SessionLocal()
        try:
            scenes = _run_async(process_novel(nid, db))
            if jid:
                _update_job(jid, "completed")
            return {"novel_id": novel_id, "scenes_count": len(scenes)}
        finally:
            db.close()
    except Exception as exc:
        if jid:
            _update_job(jid, "failed", str(exc))
        raise self.retry(exc=exc)


# ──────────────────────────────────────────────────────────────────────────────
# Task: Generate Voice (TTS per scene)
# ──────────────────────────────────────────────────────────────────────────────


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def task_generate_voice(self, scene_id: str, job_id: str | None = None):
    """Generate TTS audio for a single scene."""
    from app.ai.voice_generator import get_voice_generator

    sid = uuid.UUID(scene_id)
    jid = uuid.UUID(job_id) if job_id else None
    if jid:
        _update_job(jid, "running")

    try:
        db = SessionLocal()
        try:
            scene = db.query(Scene).filter(Scene.id == sid).first()
            if not scene:
                raise ValueError(f"Scene {sid} not found")

            voice_gen = get_voice_generator()
            output_path = settings.voice_dir / f"scene_{scene.scene_number:04d}.wav"
            _run_async(voice_gen.generate(scene.scene_text, output_path))

            scene.voice_path = str(output_path)
            db.commit()

            if jid:
                _update_job(jid, "completed")
            return {"scene_id": scene_id, "voice_path": str(output_path)}
        finally:
            db.close()
    except Exception as exc:
        if jid:
            _update_job(jid, "failed", str(exc))
        raise self.retry(exc=exc)


# ──────────────────────────────────────────────────────────────────────────────
# Task: Generate Image (per scene)
# ──────────────────────────────────────────────────────────────────────────────


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def task_generate_image(self, scene_id: str, job_id: str | None = None):
    """Generate an AI image for a single scene."""
    from app.ai.image_generator import get_image_generator

    sid = uuid.UUID(scene_id)
    jid = uuid.UUID(job_id) if job_id else None
    if jid:
        _update_job(jid, "running")

    try:
        db = SessionLocal()
        try:
            scene = db.query(Scene).filter(Scene.id == sid).first()
            if not scene:
                raise ValueError(f"Scene {sid} not found")

            img_gen = get_image_generator()
            output_path = settings.scenes_dir / f"scene_{scene.scene_number:04d}.png"
            _run_async(img_gen.generate(scene.image_prompt or scene.scene_text, output_path))

            scene.image_path = str(output_path)
            db.commit()

            if jid:
                _update_job(jid, "completed")
            return {"scene_id": scene_id, "image_path": str(output_path)}
        finally:
            db.close()
    except Exception as exc:
        if jid:
            _update_job(jid, "failed", str(exc))
        raise self.retry(exc=exc)


# ──────────────────────────────────────────────────────────────────────────────
# Task: Render Video
# ──────────────────────────────────────────────────────────────────────────────


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def task_render_video(self, novel_id: str, job_id: str | None = None, part_number: int = 1):
    """Render all scene clips and build the final video for a novel (or one part of it)."""
    from app.ai.subtitle_generator import generate_subtitles_from_scenes
    from app.video.builder import build_final_video
    from app.video.renderer import render_scenes_parallel

    nid = uuid.UUID(novel_id)
    jid = uuid.UUID(job_id) if job_id else None
    if jid:
        _update_job(jid, "running")

    try:
        _check_disk_space()

        db = SessionLocal()
        try:
            novel = db.query(Novel).filter(Novel.id == nid).first()
            if not novel:
                raise ValueError(f"Novel {nid} not found")

            scenes = (
                db.query(Scene)
                .filter(Scene.novel_id == nid, Scene.part_number == part_number)
                .order_by(Scene.scene_number)
                .all()
            )
            if not scenes:
                raise ValueError(f"No scenes found for novel {nid} part {part_number}")

            # Check total parts for title suffix
            total_parts = (
                db.query(Scene.part_number)
                .filter(Scene.novel_id == nid)
                .distinct()
                .count()
            )
            is_multipart = total_parts > 1

            # Ensure video record exists for this part
            video = (
                db.query(Video)
                .filter(Video.novel_id == nid, Video.part_number == part_number)
                .first()
            )
            if not video:
                video = Video(novel_id=nid, part_number=part_number, status="rendering")
                db.add(video)
                db.commit()
                db.refresh(video)
            else:
                video.status = "rendering"
                db.commit()

            # Render individual scene clips in parallel (configurable workers)
            scene_render_data = []
            for s in scenes:
                if not s.image_path or not s.voice_path:
                    raise ValueError(f"Scene {s.scene_number} missing image or voice")
                clip_path = settings.scenes_dir / f"clip_{s.scene_number:04d}.mp4"
                scene_render_data.append({
                    "image_path": s.image_path,
                    "audio_path": s.voice_path,
                    "output_path": str(clip_path),
                    "duration": (s.end_time or 6.0) - (s.start_time or 0.0),
                })

            clip_paths = render_scenes_parallel(
                scene_render_data, max_workers=settings.ffmpeg_max_workers,
            )

            # Update scene clip paths
            for s, cp in zip(scenes, clip_paths):
                s.clip_path = str(cp)
            db.commit()

            # Generate subtitles
            safe_title = safe_filename(novel.title)
            part_suffix = f"_part{part_number}" if is_multipart else ""
            subtitle_path = settings.subtitles_dir / f"{safe_title}{part_suffix}.srt"
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

            # Build final video for this part
            video_name = f"{safe_title}{part_suffix}.mp4"
            output_path = settings.video_output_dir / video_name

            # Check for background music
            music_files = list(settings.music_dir.glob("*.mp3")) + list(settings.music_dir.glob("*.wav"))
            music_path = music_files[0] if music_files else None

            build_final_video(
                scene_clips=clip_paths,
                output_path=output_path,
                subtitle_path=subtitle_path,
                music_path=music_path,
            )

            video.video_path = str(output_path)
            video.subtitle_path = str(subtitle_path)
            video.status = "rendered"
            db.commit()

            # Cleanup intermediate clips to free disk space
            if settings.cleanup_clips_after_build:
                for cp in clip_paths:
                    try:
                        Path(cp).unlink(missing_ok=True)
                    except OSError:
                        pass
                logger.info("Cleaned up %d intermediate clips", len(clip_paths))

            if jid:
                _update_job(jid, "completed")
            return {
                "novel_id": novel_id,
                "part_number": part_number,
                "video_path": str(output_path),
            }
        finally:
            db.close()
    except Exception as exc:
        if jid:
            _update_job(jid, "failed", str(exc))
        raise self.retry(exc=exc)


# ──────────────────────────────────────────────────────────────────────────────
# Task: Generate Subtitle (standalone)
# ──────────────────────────────────────────────────────────────────────────────


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def task_generate_subtitle(self, novel_id: str, job_id: str | None = None, part_number: int = 1):
    """Generate subtitles for a single video part."""
    from app.ai.subtitle_generator import generate_subtitles_from_scenes

    nid = uuid.UUID(novel_id)
    jid = uuid.UUID(job_id) if job_id else None
    if jid:
        _update_job(jid, "running")

    try:
        db = SessionLocal()
        try:
            novel = db.query(Novel).filter(Novel.id == nid).first()
            if not novel:
                raise ValueError(f"Novel {nid} not found")

            scenes = (
                db.query(Scene)
                .filter(Scene.novel_id == nid, Scene.part_number == part_number)
                .order_by(Scene.scene_number)
                .all()
            )
            if not scenes:
                raise ValueError(f"No scenes for novel {nid} part {part_number}")

            total_parts = (
                db.query(Scene.part_number)
                .filter(Scene.novel_id == nid)
                .distinct()
                .count()
            )
            safe_title = safe_filename(novel.title)
            part_suffix = f"_part{part_number}" if total_parts > 1 else ""
            subtitle_path = settings.subtitles_dir / f"{safe_title}{part_suffix}.srt"

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

            # Link subtitle to video record
            video = (
                db.query(Video)
                .filter(Video.novel_id == nid, Video.part_number == part_number)
                .first()
            )
            if video:
                video.subtitle_path = str(subtitle_path)
                db.commit()

            if jid:
                _update_job(jid, "completed")
            return {"novel_id": novel_id, "part_number": part_number, "subtitle_path": str(subtitle_path)}
        finally:
            db.close()
    except Exception as exc:
        if jid:
            _update_job(jid, "failed", str(exc))
        raise self.retry(exc=exc)


# ──────────────────────────────────────────────────────────────────────────────
# Task: Generate Thumbnail
# ──────────────────────────────────────────────────────────────────────────────


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def task_generate_thumbnail(self, novel_id: str, job_id: str | None = None, part_number: int = 1):
    """Generate a YouTube thumbnail for a video part."""
    from app.ai.thumbnail_generator import generate_thumbnail

    nid = uuid.UUID(novel_id)
    jid = uuid.UUID(job_id) if job_id else None
    if jid:
        _update_job(jid, "running")

    try:
        db = SessionLocal()
        try:
            novel = db.query(Novel).filter(Novel.id == nid).first()
            if not novel:
                raise ValueError(f"Novel {nid} not found")

            # Use image prompt from the first scene of this part
            first_scene = (
                db.query(Scene)
                .filter(Scene.novel_id == nid, Scene.part_number == part_number)
                .order_by(Scene.scene_number)
                .first()
            )
            image_prompt = (
                first_scene.image_prompt if first_scene and first_scene.image_prompt
                else f"dramatic cinematic scene for story: {novel.title}"
            )

            total_parts = (
                db.query(Scene.part_number)
                .filter(Scene.novel_id == nid)
                .distinct()
                .count()
            )
            safe_title = safe_filename(novel.title)
            part_suffix = f"_part{part_number}" if total_parts > 1 else ""
            thumb_path = settings.thumbnail_output_dir / f"{safe_title}{part_suffix}_thumb.jpg"

            title_text = novel.title
            if total_parts > 1:
                title_text = f"{novel.title} (Part {part_number})"

            _run_async(generate_thumbnail(
                title=title_text,
                image_prompt=image_prompt,
                output_path=thumb_path,
            ))

            # Link thumbnail to video record
            video = (
                db.query(Video)
                .filter(Video.novel_id == nid, Video.part_number == part_number)
                .first()
            )
            if video:
                video.thumbnail = str(thumb_path)
                db.commit()

            if jid:
                _update_job(jid, "completed")
            return {"novel_id": novel_id, "part_number": part_number, "thumbnail_path": str(thumb_path)}
        finally:
            db.close()
    except Exception as exc:
        if jid:
            _update_job(jid, "failed", str(exc))
        raise self.retry(exc=exc)


# ──────────────────────────────────────────────────────────────────────────────
# Task: Update Scene Timings (after voice generation)
# ──────────────────────────────────────────────────────────────────────────────


@celery_app.task(bind=True, max_retries=2, default_retry_delay=10)
def task_update_scene_timings(self, novel_id: str, part_number: int = 1):
    """Recalculate scene start/end times from actual audio durations."""
    from app.core.story_processor import update_scene_timings_from_audio

    nid = uuid.UUID(novel_id)
    try:
        db = SessionLocal()
        try:
            scenes = (
                db.query(Scene)
                .filter(Scene.novel_id == nid, Scene.part_number == part_number)
                .order_by(Scene.scene_number)
                .all()
            )
            if scenes:
                update_scene_timings_from_audio(scenes, db)
            return {"novel_id": novel_id, "part_number": part_number, "scenes_updated": len(scenes)}
        finally:
            db.close()
    except Exception as exc:
        raise self.retry(exc=exc)


# ──────────────────────────────────────────────────────────────────────────────
# Task: Full Pipeline (convenience wrapper)
# ──────────────────────────────────────────────────────────────────────────────


@celery_app.task(bind=True, max_retries=1, default_retry_delay=60)
def task_full_pipeline(self, novel_id: str, job_id: str | None = None):
    """Run the complete pipeline for a novel. Delegates to run_pipeline."""
    from app.core.pipeline import run_pipeline

    jid = uuid.UUID(job_id) if job_id else None
    if jid:
        _update_job(jid, "running")

    try:
        pipeline_job_id = run_pipeline(novel_id)
        if jid:
            _update_job(jid, "completed")
        return {"novel_id": novel_id, "pipeline_job_id": pipeline_job_id}
    except Exception as exc:
        if jid:
            _update_job(jid, "failed", str(exc))
        raise self.retry(exc=exc)


# ──────────────────────────────────────────────────────────────────────────────
# Task: Upload to YouTube
# ──────────────────────────────────────────────────────────────────────────────


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def task_upload_youtube(self, novel_id: str, job_id: str | None = None, part_number: int = 1):
    """Upload the final video to YouTube."""
    from app.youtube.uploader import upload_video

    nid = uuid.UUID(novel_id)
    jid = uuid.UUID(job_id) if job_id else None
    if jid:
        _update_job(jid, "running")

    try:
        db = SessionLocal()
        try:
            novel = db.query(Novel).filter(Novel.id == nid).first()
            video = (
                db.query(Video)
                .filter(Video.novel_id == nid, Video.part_number == part_number)
                .first()
            )
            if not novel or not video or not video.video_path:
                raise ValueError("Video not ready for upload")

            video.status = "uploading"
            db.commit()

            thumbnail_path = None
            if video.thumbnail:
                thumbnail_path = Path(video.thumbnail)

            # Check total parts for title
            total_parts = (
                db.query(Video)
                .filter(Video.novel_id == nid)
                .count()
            )
            title = novel.title
            if total_parts > 1:
                title = f"{novel.title} (Part {part_number}/{total_parts})"

            youtube_url = upload_video(
                video_path=Path(video.video_path),
                title=title,
                description=f"AI-generated story: {novel.title}\nBy: {novel.author}",
                tags=["story", "novel", "AI", "audiobook", novel.title],
                thumbnail_path=thumbnail_path,
            )

            video.youtube_url = youtube_url
            video.status = "uploaded"

            # Mark novel as completed only when ALL parts are uploaded
            all_videos = db.query(Video).filter(Video.novel_id == nid).all()
            if all(v.status == "uploaded" for v in all_videos):
                novel.status = "completed"
            db.commit()

            if jid:
                _update_job(jid, "completed")
            return {
                "novel_id": novel_id,
                "part_number": part_number,
                "youtube_url": youtube_url,
            }
        finally:
            db.close()
    except Exception as exc:
        if jid:
            _update_job(jid, "failed", str(exc))
        raise self.retry(exc=exc)
