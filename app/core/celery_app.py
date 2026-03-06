"""Celery application and worker configuration."""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.config import settings

celery_app = Celery(
    "aiyoutube",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    # Serialization
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Bangkok",
    enable_utc=True,

    # Routing — different queues for different workloads
    task_routes={
        "app.core.tasks.task_generate_script": {"queue": "script"},
        "app.core.tasks.task_generate_voice": {"queue": "tts"},
        "app.core.tasks.task_generate_image": {"queue": "image"},
        "app.core.tasks.task_render_video": {"queue": "video"},
        "app.core.tasks.task_generate_subtitle": {"queue": "video"},
        "app.core.tasks.task_generate_thumbnail": {"queue": "image"},
        "app.core.tasks.task_upload_youtube": {"queue": "upload"},
        "app.core.tasks.task_full_pipeline": {"queue": "script"},
        "app.core.tasks.task_update_scene_timings": {"queue": "video"},
        "app.core.pipeline._pipeline_after_script": {"queue": "script"},
        "app.core.beat_tasks.task_auto_process_pending": {"queue": "script"},
        "app.core.beat_tasks.task_cleanup_stale_files": {"queue": "video"},
    },

    # Default queue
    task_default_queue="default",

    # Retry defaults
    task_acks_late=True,
    worker_prefetch_multiplier=1,

    # Task time limits (soft=warning, hard=kill)
    task_soft_time_limit=3600,   # 1 hour soft limit per task
    task_time_limit=7200,        # 2 hour hard limit per task

    # Worker concurrency per queue (image queue limited to prevent GPU OOM)
    worker_max_tasks_per_child=100,  # Recycle worker after 100 tasks (memory leak prevention)

    # ── Celery Beat Schedule ──────────────────────────────────────────
    beat_schedule={
        # Scan for pending novels and auto-trigger pipeline every 5 minutes
        "auto-process-pending-novels": {
            "task": "app.core.beat_tasks.task_auto_process_pending",
            "schedule": crontab(minute="*/5"),
        },
        # Clean up stale intermediate files older than 24h every night at 3 AM
        "cleanup-stale-files": {
            "task": "app.core.beat_tasks.task_cleanup_stale_files",
            "schedule": crontab(hour=3, minute=0),
        },
    },
)

# Auto-discover task modules
celery_app.autodiscover_tasks(["app.core"], related_name="tasks")
celery_app.autodiscover_tasks(["app.core"], related_name="pipeline")
celery_app.autodiscover_tasks(["app.core"], related_name="beat_tasks")

