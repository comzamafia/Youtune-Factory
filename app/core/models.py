"""SQLAlchemy ORM models for the AI YouTube Novel Factory."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_uuid() -> uuid.UUID:
    return uuid.uuid4()


# ── Novel ──────────────────────────────────────────────────────────────────────


class Novel(Base):
    """A single novel that will be converted into one or more videos."""

    __tablename__ = "novels"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    author: Mapped[str] = mapped_column(Text, nullable=False, default="Unknown")
    text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    # Relationships
    scenes: Mapped[list[Scene]] = relationship(
        "Scene", back_populates="novel", cascade="all, delete-orphan"
    )
    videos: Mapped[list[Video]] = relationship(
        "Video", back_populates="novel", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed')",
            name="ck_novels_status",
        ),
    )


# ── Scene ──────────────────────────────────────────────────────────────────────


class Scene(Base):
    """One scene within a novel — maps to a segment of the final video."""

    __tablename__ = "scenes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    novel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("novels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scene_number: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    scene_text: Mapped[str] = mapped_column(Text, nullable=False)
    start_time: Mapped[float] = mapped_column(Float, nullable=True)
    end_time: Mapped[float] = mapped_column(Float, nullable=True)
    image_prompt: Mapped[str] = mapped_column(Text, nullable=True)
    mood: Mapped[str] = mapped_column(String(50), nullable=True)
    voice_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Source video clip supplied by the user (overrides AI-generated image when set)
    video_source_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    clip_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    part_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Relationships
    novel: Mapped[Novel] = relationship("Novel", back_populates="scenes")


# ── Video ──────────────────────────────────────────────────────────────────────


class Video(Base):
    """Final rendered video and its YouTube upload status."""

    __tablename__ = "videos"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    novel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("novels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    part_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    video_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    video_path_16x9: Mapped[str | None] = mapped_column(Text, nullable=True)
    subtitle_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    thumbnail: Mapped[str | None] = mapped_column(Text, nullable=True)
    youtube_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    # Relationships
    novel: Mapped[Novel] = relationship("Novel", back_populates="videos")

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'rendering', 'rendered', 'uploading', 'uploaded', 'failed')",
            name="ck_videos_status",
        ),
    )


# ── Job ────────────────────────────────────────────────────────────────────────


class Job(Base):
    """Queue entry tracking an asynchronous pipeline task."""

    __tablename__ = "jobs"

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    novel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("novels.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    job_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="queued"
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_step: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed')",
            name="ck_jobs_status",
        ),
        CheckConstraint(
            "job_type IN ('generate_script', 'generate_voice', 'generate_image', "
            "'render_video', 'generate_subtitle', 'generate_thumbnail', 'upload_youtube', 'full_pipeline')",
            name="ck_jobs_type",
        ),
    )
