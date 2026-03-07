"""Video routes — View video records."""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
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
    result = []
    for v in videos:
        d = VideoResponse.model_validate(v)
        if v.novel:
            d.novel_title = v.novel.title
        result.append(d)
    return result


@router.get("/{video_id}/download")
def download_video(
    video_id: uuid.UUID,
    db: Session = Depends(get_db),
    _token: str = Depends(verify_token),
):
    """Download the rendered video file."""
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    if not video.video_path:
        raise HTTPException(status_code=404, detail="No video file available")
    p = Path(video.video_path)
    if not p.exists():
        raise HTTPException(status_code=404, detail="Video file not found on disk")
    return FileResponse(
        path=p,
        media_type="video/mp4",
        filename=p.name,
    )


@router.get("/{video_id}/download-16x9")
def download_video_16x9(
    video_id: uuid.UUID,
    db: Session = Depends(get_db),
    _token: str = Depends(verify_token),
):
    """Download the 16:9 horizontal version of the video."""
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    if not video.video_path_16x9:
        raise HTTPException(status_code=404, detail="No 16:9 video available")
    p = Path(video.video_path_16x9)
    if not p.exists():
        raise HTTPException(status_code=404, detail="16:9 video file not found on disk")
    return FileResponse(
        path=p,
        media_type="video/mp4",
        filename=p.name,
    )


@router.get("/{video_id}/download-audio")
def download_audio(
    video_id: uuid.UUID,
    db: Session = Depends(get_db),
    _token: str = Depends(verify_token),
):
    """Download the combined narration audio as MP3."""
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    if not video.audio_path:
        raise HTTPException(status_code=404, detail="No audio file available")
    p = Path(video.audio_path)
    if not p.exists():
        raise HTTPException(status_code=404, detail="Audio file not found on disk")
    return FileResponse(
        path=p,
        media_type="audio/mpeg",
        filename=p.name,
    )


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


@router.delete("/{video_id}", status_code=204)
def delete_video(
    video_id: uuid.UUID,
    db: Session = Depends(get_db),
    _token: str = Depends(verify_token),
):
    """Delete a single video record."""
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    # Try to remove files from disk
    for p in [video.video_path, video.subtitle_path, video.thumbnail]:
        if p:
            fp = Path(p)
            fp.unlink(missing_ok=True)
    db.delete(video)
    db.commit()


@router.delete("", status_code=204)
def delete_all_videos(
    db: Session = Depends(get_db),
    _token: str = Depends(verify_token),
):
    """Delete all video records."""
    videos = db.query(Video).all()
    for video in videos:
        for p in [video.video_path, video.subtitle_path, video.thumbnail]:
            if p:
                fp = Path(p)
                fp.unlink(missing_ok=True)
        db.delete(video)
    db.commit()
