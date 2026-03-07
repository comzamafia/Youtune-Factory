"""Synchronous pipeline — runs all stages in a background thread (no Celery needed).

Used when ``USE_CELERY=false`` (e.g. single-dyno Railway deploys without a
separate worker service).  The API still returns immediately with a job ID;
the actual work happens on a daemon thread.

Jobs are serialized through a global queue — only ONE pipeline runs at a time.
Additional jobs wait in the queue (status="queued") until the current job finishes.
"""

from __future__ import annotations

import asyncio
import logging
import queue
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

# ── Global job queue (FIFO, serialized execution) ─────────────────────────────
# Each item: (novel_id_str, job_id_str, resume_bool)
_job_queue: queue.Queue[tuple[str, str, bool]] = queue.Queue()
_queue_worker_started = False
_queue_lock = threading.Lock()


def _queue_worker():
    """Single background thread that drains the job queue one-at-a-time."""
    logger.info("Pipeline queue worker started.")
    while True:
        novel_id, job_id, resume = _job_queue.get()
        try:
            logger.info("Queue worker: starting job %s (novel=%s, resume=%s)", job_id, novel_id, resume)
            _pipeline_thread(novel_id, job_id, resume)
        except Exception as exc:
            logger.exception("Queue worker: unhandled exception for job %s: %s", job_id, exc)
        finally:
            _job_queue.task_done()


def _ensure_worker():
    """Start the queue worker thread if not already running (idempotent)."""
    global _queue_worker_started
    with _queue_lock:
        if not _queue_worker_started:
            t = threading.Thread(target=_queue_worker, daemon=True, name="pipeline-queue-worker")
            t.start()
            _queue_worker_started = True


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _set_job(
    db,
    job_id: uuid.UUID,
    status: str,
    error: str | None = None,
    step: str | None = None,
    progress: int | None = None,
):
    job = db.query(Job).filter(Job.job_id == job_id).first()
    if not job:
        return
    job.status = status
    now = datetime.now(timezone.utc)
    if status == "running" and not job.started_at:
        job.started_at = now
    if status in ("completed", "failed"):
        job.finished_at = now
    if error:
        job.error_message = error
    if step is not None:
        job.current_step = step
    if progress is not None:
        job.progress = progress
    db.commit()


def queue_depth() -> int:
    """Return the number of jobs currently waiting in the queue (not yet started)."""
    return _job_queue.qsize()


# ── Public entry points ───────────────────────────────────────────────────────

def run_pipeline_sync(novel_id: str | uuid.UUID) -> str:
    """Enqueue a full pipeline job. Returns the job ID immediately.

    The job runs after all previously queued jobs complete (FIFO).
    """
    _ensure_worker()
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

    _job_queue.put((str(nid), str(job_id), False))
    pos = _job_queue.qsize()
    logger.info("Sync pipeline enqueued for novel %s (job=%s, queue_depth=%d)", nid, job_id, pos)
    return str(job_id)


def resume_pipeline_sync(novel_id: str | uuid.UUID) -> str:
    """Enqueue a resume pipeline job. Returns the job ID immediately.

    Skips steps that already have valid output files on disk.
    """
    _ensure_worker()
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

    _job_queue.put((str(nid), str(job_id), True))
    pos = _job_queue.qsize()
    logger.info("Sync pipeline RESUME enqueued for novel %s (job=%s, queue_depth=%d)", nid, job_id, pos)
    return str(job_id)


# ── Pipeline thread ──────────────────────────────────────────────────────────

def _file_ok(path: str | None, min_bytes: int = 100) -> bool:
    """Return True if path points to an existing file with at least min_bytes."""
    if not path:
        return False
    p = Path(path)
    return p.exists() and p.stat().st_size >= min_bytes


# ── Pipeline thread ──────────────────────────────────────────────────────────

def _pipeline_thread(novel_id: str, job_id: str, resume: bool = False):
    """Run all pipeline stages sequentially.

    When ``resume=True`` the pipeline skips any step whose output already
    exists on disk, continuing from the earliest incomplete step.
    """
    nid = uuid.UUID(novel_id)
    jid = uuid.UUID(job_id)
    db = SessionLocal()
    mode = "RESUME" if resume else "FRESH"
    try:
        _set_job(db, jid, "running", step="1/6 สร้างบทจากนิยาย…", progress=0)

        novel = db.query(Novel).filter(Novel.id == nid).first()
        if not novel:
            _set_job(db, jid, "failed", "Novel not found")
            return

        novel.status = "processing"
        db.commit()

        if not resume:
            # ── Fresh run: Delete old scenes/videos ──────────────────
            old_scenes = db.query(Scene).filter(Scene.novel_id == nid).all()
            if old_scenes:
                logger.info("[%s] Deleting %d old scenes from previous run", mode, len(old_scenes))
                for s in old_scenes:
                    db.delete(s)
                db.commit()
            old_videos = db.query(Video).filter(Video.novel_id == nid).all()
            for v in old_videos:
                db.delete(v)
            if old_videos:
                db.commit()

        # ── Step 1: Generate script (LLM scene splitting) ────────────
        existing_scenes = (
            db.query(Scene)
            .filter(Scene.novel_id == nid)
            .order_by(Scene.scene_number)
            .all()
        )
        if resume and existing_scenes:
            scenes = existing_scenes
            logger.info("[%s] Step 1/6: Skipping — %d scenes already in DB", mode, len(scenes))
            _set_job(db, jid, "running", step=f"1/6 ✓ บทเดิม ({len(scenes)} ฉาก)", progress=15)
        else:
            logger.info("[%s] Step 1/6: Generating script for '%s'…", mode, novel.title)
            from app.core.story_processor import process_novel
            scenes = _run_async(process_novel(nid, db))
            logger.info("[%s] Script done — %d scenes created.", mode, len(scenes))


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

        # Assign user-supplied media (safe to re-run — idempotent)
        assign_media_to_scenes(scenes, db, novel_id=novel_id)
        _set_job(db, jid, "running", step=f"1/6 สร้างบทจากนิยาย… ({len(scenes)} ฉาก)", progress=15)

        # ── Step 2: Generate voice (TTS) ─────────────────────────────
        n_scenes = len(scenes)
        voice_ext = ".mp3" if settings.tts_engine.lower() == "edge_tts" else ".wav"
        voices_needed = [s for s in scenes if not _file_ok(s.voice_path)]
        if resume and not voices_needed:
            logger.info("[%s] Step 2/6: Skipping — all voice files exist", mode)
            _set_job(db, jid, "running", step=f"2/6 ✓ เสียงพากย์ครบแล้ว ({n_scenes} ฉาก)", progress=40)
        else:
            _set_job(db, jid, "running", step=f"2/6 สร้างเสียงพากย์ (0/{n_scenes} ฉาก…)", progress=15)
            logger.info("[%s] Step 2/6: Generating voice (%d missing)…", mode, len(voices_needed))
            from app.ai.voice_generator import get_voice_generator
            voice_gen = get_voice_generator()
            for i, s in enumerate(scenes):
                out = settings.voice_dir / f"scene_{s.scene_number:04d}{voice_ext}"
                cleaned_text = s.scene_text.strip() if s.scene_text else ""
                if not cleaned_text:
                    logger.warning("[%s] Scene %d has empty text — skipping voice", mode, s.scene_number)
                    pct = 15 + int((i + 1) / n_scenes * 25)
                    _set_job(db, jid, "running", step=f"2/6 สร้างเสียงพากย์ ({i+1}/{n_scenes} ฉาก…)", progress=pct)
                    continue
                if resume and _file_ok(str(out)):
                    logger.info("[%s] Scene %d voice exists — skipping", mode, s.scene_number)
                    s.voice_path = str(out)
                    pct = 15 + int((i + 1) / n_scenes * 25)
                    _set_job(db, jid, "running", step=f"2/6 สร้างเสียงพากย์ ({i+1}/{n_scenes} ฉาก…)", progress=pct)
                    continue
                _run_async(voice_gen.generate(s.scene_text, out))
                if not out.exists() or out.stat().st_size < 100:
                    raise RuntimeError(f"Voice file empty or missing: {out} (text: {s.scene_text[:50]})")
                s.voice_path = str(out)
                pct = 15 + int((i + 1) / n_scenes * 25)
                _set_job(db, jid, "running", step=f"2/6 สร้างเสียงพากย์ ({i+1}/{n_scenes} ฉาก…)", progress=pct)
                logger.info("[%s] Voice scene %d: %d bytes", mode, s.scene_number, out.stat().st_size)
            db.commit()
            logger.info("[%s] Voice done.", mode)

        # ── Step 3: Generate images ──────────────────────────────────
        images_needed = [s for s in scenes if not s.video_source_path and not _file_ok(s.image_path)]
        if resume and not images_needed:
            logger.info("[%s] Step 3/6: Skipping — all images exist", mode)
            _set_job(db, jid, "running", step=f"3/6 ✓ ภาพครบแล้ว ({n_scenes} ฉาก)", progress=62)
        else:
            _set_job(db, jid, "running", step=f"3/6 สร้างภาพ (0/{n_scenes} ฉาก…)", progress=40)
            logger.info("[%s] Step 3/6: Generating images (%d missing)…", mode, len(images_needed))
            from app.ai.image_generator import get_image_generator
            img_gen = get_image_generator()
            img_idx = 0
            for i, s in enumerate(scenes):
                if s.video_source_path:
                    img_idx += 1
                    continue
                out = settings.scenes_dir / f"scene_{s.scene_number:04d}.png"
                if resume and _file_ok(str(out)):
                    logger.info("[%s] Scene %d image exists — skipping", mode, s.scene_number)
                    s.image_path = str(out)
                    img_idx += 1
                    pct = 40 + int(img_idx / n_scenes * 20)
                    _set_job(db, jid, "running", step=f"3/6 สร้างภาพ ({img_idx}/{n_scenes} ฉาก…)", progress=pct)
                    continue
                if s.image_path and _file_ok(s.image_path):
                    img_idx += 1
                    continue  # user-supplied image already assigned
                _run_async(img_gen.generate(s.image_prompt or s.scene_text, out))
                s.image_path = str(out)
                img_idx += 1
                pct = 40 + int(img_idx / n_scenes * 20)
                _set_job(db, jid, "running", step=f"3/6 สร้างภาพ ({img_idx}/{n_scenes} ฉาก…)", progress=pct)
            db.commit()
            logger.info("[%s] Images done.", mode)

        # ── Step 4: Update scene timings ─────────────────────────────
        _set_job(db, jid, "running", step="4/6 คำนวณเวลา…", progress=62)
        logger.info("[%s] Step 4/6: Updating timings…", mode)
        from app.core.story_processor import update_scene_timings_from_audio
        update_scene_timings_from_audio(scenes, db)
        logger.info("[%s] Timings done.", mode)

        # ── Step 5: Render video (per part) ──────────────────────────
        _set_job(db, jid, "running", step="5/6 เรนเดอร์วิดีโอ…", progress=65)
        logger.info("[%s] Step 5/6: Rendering video…", mode)
        from app.ai.subtitle_generator import generate_subtitles_from_scenes
        from app.video.builder import build_final_video
        from app.video.renderer import render_scenes_parallel

        part_groups: dict[int, list[Scene]] = {}
        for s in scenes:
            part_groups.setdefault(s.part_number, []).append(s)

        total_parts = len(part_groups)
        is_multipart = total_parts > 1

        for part_num, part_scenes in sorted(part_groups.items()):
            safe_title = safe_filename(novel.title)
            part_suffix = f"_part{part_num}" if is_multipart else ""
            vid_name = f"{safe_title}{part_suffix}.mp4"
            vid_path = settings.video_output_dir / vid_name

            # Resume: skip render if final video already exists
            if resume and vid_path.exists() and vid_path.stat().st_size > 10_000:
                logger.info("[%s] Part %d/%d video exists — skipping render", mode, part_num, total_parts)
                _set_job(db, jid, "running", step=f"5/6 ✓ วิดีโอส่วนที่ {part_num}/{total_parts} มีแล้ว", progress=75 + int(part_num / total_parts * 15))
            else:
                # Render clips — skip scenes with no audio (empty text scenes)
                render_data = []
                renderable_scenes = []
                for s in part_scenes:
                    if not s.voice_path and not s.video_source_path:
                        logger.warning("[%s] Scene %d has no audio and no video source — skipping render", mode, s.scene_number)
                        continue
                    clip = settings.scenes_dir / f"clip_{s.scene_number:04d}.mp4"
                    render_data.append({
                        "image_path": s.image_path,
                        "video_source_path": s.video_source_path,
                        "audio_path": s.voice_path,
                        "output_path": str(clip),
                        "duration": (s.end_time or 6.0) - (s.start_time or 0.0),
                        "scene_index": s.scene_number - 1,
                    })
                    renderable_scenes.append(s)
                _set_job(db, jid, "running", step=f"5/6 เรนเดอร์วิดีโอ (ตัดต่อ clips ส่วนที่ {part_num}/{total_parts}…)", progress=65)
                clip_paths = render_scenes_parallel(render_data, max_workers=1)
                _set_job(db, jid, "running", step=f"5/6 เรนเดอร์วิดีโอ (รวมวิดีโอส่วนที่ {part_num}/{total_parts}…)", progress=75 + int((part_num - 1) / total_parts * 15))

                for s, cp in zip(renderable_scenes, clip_paths):
                    s.clip_path = str(cp)
                db.commit()

                # Subtitles
                sub_path = settings.subtitles_dir / f"{safe_title}{part_suffix}.srt"
                generate_subtitles_from_scenes(
                    [{"scene_number": s.scene_number, "text": s.scene_text,
                      "start_time": s.start_time or 0.0, "end_time": s.end_time or 6.0}
                     for s in part_scenes],
                    sub_path,
                )

                # Build video
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
                    logger.warning("[%s] 16:9 conversion failed (non-fatal): %s", mode, e16)
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
                sub_path_obj = settings.subtitles_dir / f"{safe_title}{part_suffix}.srt"
                video.subtitle_path = str(sub_path_obj)
                video.status = "rendered"

                # ── Produce combined MP3 (concatenate voice clips) ──────────
                voice_files = [Path(s.voice_path) for s in part_scenes if s.voice_path and Path(s.voice_path).exists()]
                if voice_files:
                    audio_out = settings.video_output_dir / f"{safe_title}{part_suffix}.mp3"
                    try:
                        import tempfile, subprocess
                        concat_txt = Path(tempfile.mktemp(suffix=".txt"))
                        concat_txt.write_text(
                            "\n".join(f"file '{vf.resolve()}'" for vf in voice_files),
                            encoding="utf-8",
                        )
                        subprocess.run(
                            [
                                "ffmpeg", "-y",
                                "-f", "concat", "-safe", "0",
                                "-i", str(concat_txt),
                                "-c:a", "libmp3lame", "-q:a", "2",
                                str(audio_out),
                            ],
                            check=True,
                            capture_output=True,
                            timeout=300,
                        )
                        concat_txt.unlink(missing_ok=True)
                        video.audio_path = str(audio_out)
                        logger.info("[%s] Combined audio MP3: %s", mode, audio_out)
                    except Exception as ae:
                        logger.warning("[%s] Audio concat failed (non-fatal): %s", mode, ae)

                db.commit()

                # Cleanup
                if settings.cleanup_clips_after_build:
                    for cp in clip_paths:
                        try:
                            Path(cp).unlink(missing_ok=True)
                        except OSError:
                            pass

            _set_job(db, jid, "running", step=f"5/6 เรนเดอร์วิดีโอ (เสร็จส่วนที่ {part_num}/{total_parts})", progress=75 + int(part_num / total_parts * 15))
            logger.info("[%s] Part %d/%d rendered → %s", mode, part_num, total_parts, vid_path)

        # ── Step 6: Thumbnail ────────────────────────────────────────
        _set_job(db, jid, "running", step="6/6 สร้างรูปปก…", progress=92)
        logger.info("[%s] Step 6/6: Generating thumbnail…", mode)
        from app.ai.thumbnail_generator import generate_thumbnail
        for part_num in sorted(part_groups.keys()):
            first = part_groups[part_num][0]
            safe_title = safe_filename(novel.title)
            part_suffix = f"_part{part_num}" if is_multipart else ""
            thumb_path = settings.thumbnail_output_dir / f"{safe_title}{part_suffix}_thumb.jpg"
            # Resume: skip if thumbnail already exists
            if resume and _file_ok(str(thumb_path)):
                logger.info("[%s] Thumbnail for part %d exists — skipping", mode, part_num)
                video = db.query(Video).filter(
                    Video.novel_id == nid, Video.part_number == part_num
                ).first()
                if video and not video.thumbnail:
                    video.thumbnail = str(thumb_path)
                continue
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
        logger.info("[%s] Thumbnail done.", mode)

        # ── Done ─────────────────────────────────────────────────────
        novel.status = "completed"
        db.commit()
        _set_job(db, jid, "completed", step="เสร็จสมบูรณ์", progress=100)
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
