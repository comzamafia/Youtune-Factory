"""Tests for ORM models — validates schema & relationships."""

from __future__ import annotations

import uuid

from app.core.models import Job, Novel, Scene, Video


def test_create_novel(db):
    """Novel can be created with required fields."""
    novel = Novel(title="Test Novel", author="Author", text="Once upon a time…")
    db.add(novel)
    db.commit()
    db.refresh(novel)

    assert novel.id is not None
    assert isinstance(novel.id, uuid.UUID)
    assert novel.title == "Test Novel"
    assert novel.status == "pending"
    assert novel.created_at is not None


def test_novel_scenes_relationship(db):
    """Scenes are linked to their parent novel."""
    novel = Novel(title="Test", author="A", text="text")
    db.add(novel)
    db.commit()
    db.refresh(novel)

    scene = Scene(
        novel_id=novel.id,
        scene_number=1,
        scene_text="The night was dark.",
        image_prompt="dark night sky",
        mood="mysterious",
    )
    db.add(scene)
    db.commit()

    assert len(novel.scenes) == 1
    assert novel.scenes[0].scene_text == "The night was dark."


def test_novel_cascade_delete(db):
    """Deleting a novel cascades to scenes and videos."""
    novel = Novel(title="Del", author="A", text="x")
    db.add(novel)
    db.commit()
    db.refresh(novel)

    scene = Scene(novel_id=novel.id, scene_number=1, scene_text="scene")
    video = Video(novel_id=novel.id, status="pending")
    db.add_all([scene, video])
    db.commit()

    db.delete(novel)
    db.commit()

    assert db.query(Scene).count() == 0
    assert db.query(Video).count() == 0


def test_create_job(db):
    """Job can be created with valid type and status."""
    job = Job(job_type="generate_script", status="queued", priority=5)
    db.add(job)
    db.commit()
    db.refresh(job)

    assert job.job_id is not None
    assert job.status == "queued"
    assert job.priority == 5


def test_video_status_defaults(db):
    """Video defaults to 'pending' status."""
    novel = Novel(title="V", author="A", text="t")
    db.add(novel)
    db.commit()

    video = Video(novel_id=novel.id)
    db.add(video)
    db.commit()
    db.refresh(video)

    assert video.status == "pending"
    assert video.youtube_url is None
