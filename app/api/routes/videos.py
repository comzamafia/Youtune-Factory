"""Video routes — View video records."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.auth import verify_token
from app.api.schemas import VideoResponse
from app.core.database import get_db
from app.core.models import Video

router = APIRouter(prefix="/videos", tags=["videos"])


@router.get("", response_model=list[VideoResponse])
def list_videos(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    status: str | None = Query(None),
    db: Session = Depends(get_db),
    _token: str = Depends(verify_token),
):
    """List all videos with optional status filter."""
    q = db.query(Video)
    if status:
        q = q.filter(Video.status == status)
    q = q.order_by(Video.created_at.desc())
    videos = q.offset((page - 1) * limit).limit(limit).all()
    return videos


@router.get("/{video_id}", response_model=VideoResponse)
def get_video(
    video_id: uuid.UUID,
    db: Session = Depends(get_db),
    _token: str = Depends(verify_token),
):
    """Get a single video's details."""
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    return video
