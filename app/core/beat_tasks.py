"""Celery Beat periodic tasks — scheduled background jobs."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from app.config import settings
from app.core.celery_app import celery_app
from app.core.database import SessionLocal
from app.core.models import Novel

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="app.core.beat_tasks.task_auto_process_pending")
def task_auto_process_pending(self):
    """Scan for novels in 'pending' status and trigger their pipeline automatically.

    Runs every 5 minutes via Celery Beat. This allows novels uploaded via the API
    or dropped into the input directory to be picked up without manual intervention.
    """
    from app.core.pipeline import run_pipeline

    db = SessionLocal()
    try:
        pending = (
            db.query(Novel)
            .filter(Novel.status == "pending")
            .limit(10)
            .all()
        )
        if not pending:
            logger.debug("auto_process: no pending novels")
            return {"triggered": 0}

        job_ids = []
        for novel in pending:
            # Mark as queued so we don't double-trigger
            novel.status = "queued"
            db.commit()
            try:
                job_id = run_pipeline(novel.id)
                job_ids.append(job_id)
                logger.info("auto_process: triggered pipeline for '%s' (job=%s)", novel.title, job_id)
            except Exception as exc:
                # Roll back status so it will be retried next cycle
                novel.status = "pending"
                db.commit()
                logger.error("auto_process: failed to trigger pipeline for %s: %s", novel.id, exc)

        return {"triggered": len(job_ids), "job_ids": job_ids}
    finally:
        db.close()


@celery_app.task(bind=True, name="app.core.beat_tasks.task_cleanup_stale_files")
def task_cleanup_stale_files(self):
    """Delete intermediate processing files older than 24 hours.

    Targets:
    - processing/scenes/*.mp4  (rendered per-scene clips)
    - processing/scenes/*.png  (generated images)
    - processing/voice/*.wav   (generated voice files)

    Final videos and subtitles in output/ are NOT touched.
    Runs nightly at 3 AM via Celery Beat.
    """
    cutoff_seconds = 24 * 3600  # 24 hours
    now = time.time()

    patterns = [
        (settings.scenes_dir, "*.mp4"),
        (settings.scenes_dir, "*.png"),
        (settings.voice_dir, "*.wav"),
    ]

    total_deleted = 0
    total_bytes = 0

    for directory, pattern in patterns:
        if not directory.exists():
            continue
        for f in directory.glob(pattern):
            try:
                age = now - f.stat().st_mtime
                if age > cutoff_seconds:
                    size = f.stat().st_size
                    f.unlink()
                    total_deleted += 1
                    total_bytes += size
            except OSError:
                pass

    freed_mb = total_bytes / (1024 * 1024)
    logger.info(
        "cleanup_stale_files: removed %d files, freed %.1f MB",
        total_deleted, freed_mb,
    )
    return {"deleted": total_deleted, "freed_mb": round(freed_mb, 1)}
