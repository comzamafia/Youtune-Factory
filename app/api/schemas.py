"""Pydantic schemas for API request/response serialization."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# Maximum novel text size (10 MB of text ~ extremely long novels)
MAX_NOVEL_TEXT_LENGTH = 10_000_000


# ── Novel ──────────────────────────────────────────────────────────────────────


class NovelCreate(BaseModel):
    title: str
    author: str = "Unknown"
    text: str

    @field_validator("text")
    @classmethod
    def validate_text_length(cls, v: str) -> str:
        if len(v.strip()) < 50:
            raise ValueError("Novel text is too short (minimum 50 characters)")
        if len(v) > MAX_NOVEL_TEXT_LENGTH:
            raise ValueError(
                f"Novel text is too long ({len(v):,} chars, max {MAX_NOVEL_TEXT_LENGTH:,})"
            )
        return v


class NovelResponse(BaseModel):
    id: uuid.UUID
    title: str
    author: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class NovelDetail(NovelResponse):
    text: str
    scenes: list[SceneResponse] = []
    videos: list[VideoResponse] = []


# ── Scene ──────────────────────────────────────────────────────────────────────


class SceneResponse(BaseModel):
    id: uuid.UUID
    novel_id: uuid.UUID
    scene_number: int
    scene_text: str
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    image_prompt: Optional[str] = None
    mood: Optional[str] = None
    voice_path: Optional[str] = None
    image_path: Optional[str] = None
    video_source_path: Optional[str] = None
    clip_path: Optional[str] = None
    part_number: int = 1

    model_config = {"from_attributes": True}


# ── Video ──────────────────────────────────────────────────────────────────────


class VideoResponse(BaseModel):
    id: uuid.UUID
    novel_id: uuid.UUID
    part_number: int = 1
    video_path: Optional[str] = None
    subtitle_path: Optional[str] = None
    thumbnail: Optional[str] = None
    youtube_url: Optional[str] = None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Job ────────────────────────────────────────────────────────────────────────


class JobResponse(BaseModel):
    job_id: uuid.UUID
    novel_id: Optional[uuid.UUID] = None
    job_type: str
    status: str
    priority: int
    error_message: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ── Pipeline ───────────────────────────────────────────────────────────────────


class PipelineRequest(BaseModel):
    novel_id: uuid.UUID


class PipelineResponse(BaseModel):
    job_id: str
    novel_id: str
    message: str
    estimated_parts: int = 1


class BatchPipelineRequest(BaseModel):
    novel_ids: list[uuid.UUID]


class BatchPipelineResponse(BaseModel):
    job_ids: list[str]
    message: str


# ── Generic ────────────────────────────────────────────────────────────────────


class PaginatedResponse(BaseModel):
    page: int = 1
    limit: int = 50
    total: int = 0
    total_pages: int = 0


class ErrorResponse(BaseModel):
    error: str


# Forward reference resolution
NovelDetail.model_rebuild()
