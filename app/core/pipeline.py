"""Pipeline Orchestrator — Chains all stages into a full automated workflow."""

from __future__ import annotations

import logging
import uuid
from itertools import groupby

from celery import chain, chord, group

from app.config import settings
from app.core.celery_app import celery_app
from app.core.database import SessionLocal
from app.core.models import Job, Novel, Scene
from app.core.tasks import (
    task_generate_image,
    task_generate_script,
    task_generate_thumbnail,
    task_generate_voice,
    task_render_video,
    task_update_scene_timings,
    task_upload_youtube,
)
from app.core.story_processor import assign_media_to_scenes

logger = logging.getLogger(__name__)


def _create_job(novel_id: uuid.UUID, job_type: str) -> uuid.UUID:
    """Insert a Job record and return its ID."""
    db = SessionLocal()
    try:
        job = Job(novel_id=novel_id, job_type=job_type, status="queued")
        db.add(job)
        db.commit()
        db.refresh(job)
        return job.job_id
    finally:
        db.close()


def _update_job_status(job_id: uuid.UUID, status: str) -> None:
    """Update a Job record's status."""
    from datetime import datetime, timezone

    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.job_id == job_id).first()
        if job:
            job.status = status
            if status == "running":
                job.started_at = datetime.now(timezone.utc)
            if status in ("completed", "failed"):
                job.finished_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()


def run_pipeline(novel_id: str | uuid.UUID) -> str:
    """
    Run the full pipeline for a single novel (async via Celery).

    Pipeline stages:
    1. generate_script  →  splits novel into scenes
    2. generate_voice + generate_image  (parallel per scene, after step 1)
    3. render_video  →  assemble clips + subtitles
    4. upload_youtube

    Returns the pipeline job ID.
    """
    nid = uuid.UUID(str(novel_id))

    # Create the top-level pipeline job
    pipeline_job_id = _create_job(nid, "full_pipeline")
    script_job_id = _create_job(nid, "generate_script")

    # Step 1: generate script → then kick off parallel voice/image + render + upload
    # We use the callback pattern since we don't know scene IDs until step 1 completes.
    task_generate_script.apply_async(
        args=[str(nid), str(script_job_id)],
        link=_pipeline_after_script.s(str(nid), str(pipeline_job_id)),
    )

    logger.info("Pipeline started for novel %s (job=%s)", nid, pipeline_job_id)

    # Mark pipeline job as running
    _update_job_status(pipeline_job_id, "running")

    return str(pipeline_job_id)


@celery_app.task(bind=True, max_retries=1, default_retry_delay=30)
def _pipeline_after_script(self, script_result: dict, novel_id: str, pipeline_job_id: str):
    """
    Called after script generation completes.
    Spawns parallel voice + image tasks for each scene (with concurrency limits),
    then chains render + upload per video part.
    """
    nid = uuid.UUID(novel_id)
    pid = uuid.UUID(pipeline_job_id)

    db = SessionLocal()
    try:
        scenes = (
            db.query(Scene)
            .filter(Scene.novel_id == nid)
            .order_by(Scene.scene_number)
            .all()
        )

        if not scenes:
            _update_job_status(pid, "failed")
            raise ValueError(f"No scenes found for novel {nid} after script generation")

        # Assign user-supplied media from input/media/ before generating images.
        # Scenes that receive a video/image here will skip AI image generation.
        assign_media_to_scenes(scenes, db)

        # Group scenes by part_number for multi-part video support
        part_groups: dict[int, list[Scene]] = {}
        for scene in scenes:
            part_groups.setdefault(scene.part_number, []).append(scene)

        total_parts = len(part_groups)
        logger.info(
            "Novel %s: %d scenes in %d part(s)", nid, len(scenes), total_parts,
        )

        # Create batched voice + image tasks respecting concurrency limits
        # Voice and image tasks are dispatched for ALL scenes at once,
        # but Celery rate-limiting controls actual concurrency.
        voice_tasks = []
        image_tasks = []
        for scene in scenes:
            voice_job_id = _create_job(nid, "generate_voice")
            image_job_id = _create_job(nid, "generate_image")
            voice_tasks.append(
                task_generate_voice.si(str(scene.id), str(voice_job_id))
            )
            image_tasks.append(
                task_generate_image.si(str(scene.id), str(image_job_id))
            )

        # Batch voice and image tasks separately to respect concurrency limits.
        # Voice tasks: batched by voice_task_concurrency
        # Image tasks: batched by image_task_concurrency (prevents GPU OOM)
        voice_batch_size = settings.voice_task_concurrency
        image_batch_size = settings.image_task_concurrency

        batched_parallel = []
        for i in range(0, len(voice_tasks), voice_batch_size):
            batched_parallel.append(group(voice_tasks[i : i + voice_batch_size]))
        for i in range(0, len(image_tasks), image_batch_size):
            batched_parallel.append(group(image_tasks[i : i + image_batch_size]))

        all_generation_tasks = group(voice_tasks + image_tasks)

        # After all voice + image tasks complete →
        #   update timings → render → thumbnail → upload  (per part)
        render_upload_chain_tasks = []
        for part_num in sorted(part_groups.keys()):
            render_job_id = _create_job(nid, "render_video")
            thumbnail_job_id = _create_job(nid, "generate_thumbnail")
            upload_job_id = _create_job(nid, "upload_youtube")
            render_upload_chain_tasks.append(
                chain(
                    task_update_scene_timings.si(novel_id, part_num),
                    task_render_video.si(novel_id, str(render_job_id), part_num),
                    task_generate_thumbnail.si(novel_id, str(thumbnail_job_id), part_num),
                    task_upload_youtube.si(novel_id, str(upload_job_id), part_num),
                )
            )

        # chord: all generation tasks → then render+upload per part in parallel
        if len(render_upload_chain_tasks) == 1:
            after_generation = render_upload_chain_tasks[0]
        else:
            after_generation = group(render_upload_chain_tasks)

        workflow = chord(all_generation_tasks, after_generation)
        workflow.apply_async()
        logger.info(
            "Dispatched %d voice + %d image tasks for %d part(s)",
            len(voice_tasks), len(image_tasks), total_parts,
        )

    except Exception as exc:
        _update_job_status(pid, "failed")
        raise self.retry(exc=exc)
    finally:
        db.close()


def run_batch(novel_ids: list[str | uuid.UUID]) -> list[str]:
    """
    Launch the pipeline for multiple novels in parallel.

    Returns a list of pipeline job IDs.
    """
    job_ids = []
    for nid in novel_ids:
        jid = run_pipeline(nid)
        job_ids.append(jid)
    logger.info("Batch pipeline started for %d novels", len(novel_ids))
    return job_ids
