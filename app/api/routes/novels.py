"""Novel routes — CRUD + pipeline trigger + file upload."""

from __future__ import annotations

import math
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.api.auth import verify_token
from app.api.schemas import (
    BatchPipelineRequest,
    BatchPipelineResponse,
    MediaListResponse,
    NovelCreate,
    NovelDetail,
    NovelResponse,
    PipelineResponse,
)
from app.config import settings
from app.core.database import get_db
from app.core.models import Novel
from app.core.pipeline import run_batch, run_pipeline

router = APIRouter(prefix="/novels", tags=["novels"])

# Allowed extensions
_TEXT_EXTS = {".txt", ".text"}
_MEDIA_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".mp4", ".mov", ".avi", ".mkv", ".webm"}
_MAX_TEXT_SIZE = 10_000_000  # 10 MB
_MAX_MEDIA_SIZE = 200_000_000  # 200 MB


@router.post("", response_model=NovelResponse, status_code=201)
def create_novel(
    body: NovelCreate,
    db: Session = Depends(get_db),
    _token: str = Depends(verify_token),
):
    """Create a new novel entry."""
    novel = Novel(title=body.title, author=body.author, text=body.text)
    db.add(novel)
    db.commit()
    db.refresh(novel)
    return novel


@router.post("/upload", response_model=NovelResponse, status_code=201)
async def upload_novel(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _token: str = Depends(verify_token),
):
    """Upload a .txt file to create a novel. Title = filename (without extension)."""
    ext = Path(file.filename or "").suffix.lower()
    if ext not in _TEXT_EXTS:
        raise HTTPException(400, f"Only .txt files allowed, got '{ext}'")

    raw = await file.read()
    if len(raw) > _MAX_TEXT_SIZE:
        raise HTTPException(400, f"File too large ({len(raw):,} bytes, max {_MAX_TEXT_SIZE:,})")

    # Try UTF-8 first, fallback to TIS-620 (Thai)
    for enc in ("utf-8", "tis-620", "cp874", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except (UnicodeDecodeError, LookupError):
            continue
    else:
        raise HTTPException(400, "Cannot decode file — please use UTF-8 encoding")

    text = text.strip()
    if len(text) < 50:
        raise HTTPException(400, f"Novel text too short ({len(text)} chars, min 50)")

    title = Path(file.filename or "novel").stem
    novel = Novel(title=title, author="Unknown", text=text)
    db.add(novel)
    db.commit()
    db.refresh(novel)
    return novel


@router.get("", response_model=list[NovelResponse])
def list_novels(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    status: str | None = Query(None),
    db: Session = Depends(get_db),
    _token: str = Depends(verify_token),
):
    """List novels with pagination and optional status filter."""
    q = db.query(Novel)
    if status:
        q = q.filter(Novel.status == status)
    q = q.order_by(Novel.created_at.desc())
    novels = q.offset((page - 1) * limit).limit(limit).all()
    return novels


@router.get("/{novel_id}", response_model=NovelDetail)
def get_novel(
    novel_id: uuid.UUID,
    db: Session = Depends(get_db),
    _token: str = Depends(verify_token),
):
    """Get a single novel with scenes and video info."""
    novel = db.query(Novel).filter(Novel.id == novel_id).first()
    if not novel:
        raise HTTPException(status_code=404, detail="Novel not found")
    return novel


@router.delete("/{novel_id}", status_code=204)
def delete_novel(
    novel_id: uuid.UUID,
    db: Session = Depends(get_db),
    _token: str = Depends(verify_token),
):
    """Delete a novel and all related data (cascading)."""
    novel = db.query(Novel).filter(Novel.id == novel_id).first()
    if not novel:
        raise HTTPException(status_code=404, detail="Novel not found")
    db.delete(novel)
    db.commit()


@router.post("/{novel_id}/process", response_model=PipelineResponse)
def trigger_pipeline(
    novel_id: uuid.UUID,
    db: Session = Depends(get_db),
    _token: str = Depends(verify_token),
):
    """Trigger the full video pipeline for a novel."""
    novel = db.query(Novel).filter(Novel.id == novel_id).first()
    if not novel:
        raise HTTPException(status_code=404, detail="Novel not found")

    # Estimate how many parts the video will be split into
    from app.config import settings as _s
    est_scenes = max(1, len(novel.text) // 200)  # rough: ~200 chars per scene
    est_parts = max(1, est_scenes // _s.max_scenes_per_part) if _s.max_scenes_per_part > 0 else 1

    job_id = run_pipeline(novel_id)
    return PipelineResponse(
        job_id=job_id,
        novel_id=str(novel_id),
        message=f"Pipeline started for '{novel.title}'",
        estimated_parts=est_parts,
    )


@router.post("/batch/process", response_model=BatchPipelineResponse)
def trigger_batch_pipeline(
    body: BatchPipelineRequest,
    db: Session = Depends(get_db),
    _token: str = Depends(verify_token),
):
    """Trigger the pipeline for multiple novels at once."""
    job_ids = run_batch(body.novel_ids)
    return BatchPipelineResponse(
        job_ids=job_ids,
        message=f"Batch pipeline started for {len(body.novel_ids)} novels",
    )


# ── Per-Novel Media Upload ────────────────────────────────────────────────────

_IMAGE_EXTS_ONLY = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
_VIDEO_EXTS_ONLY = {".mp4", ".mov", ".avi", ".mkv", ".webm"}


def _novel_media_dir(novel_id: uuid.UUID) -> Path:
    """Return input/media/{novel_id}/ — creates if absent."""
    d = settings.media_input_dir / str(novel_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _media_type(ext: str) -> str:
    if ext in _IMAGE_EXTS_ONLY:
        return "image"
    return "video"


@router.post("/{novel_id}/media/upload", status_code=201)
async def upload_media(
    novel_id: uuid.UUID,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    _token: str = Depends(verify_token),
):
    """Upload images/videos for a specific novel."""
    novel = db.query(Novel).filter(Novel.id == novel_id).first()
    if not novel:
        raise HTTPException(404, "Novel not found")

    media_dir = _novel_media_dir(novel_id)
    saved = []
    for f in files:
        ext = Path(f.filename or "").suffix.lower()
        if ext not in _MEDIA_EXTS:
            raise HTTPException(400, f"Unsupported file type '{ext}' for '{f.filename}'")
        raw = await f.read()
        if len(raw) > _MAX_MEDIA_SIZE:
            raise HTTPException(400, f"File '{f.filename}' too large ({len(raw):,} bytes, max {_MAX_MEDIA_SIZE:,})")
        safe_name = Path(f.filename or "file").name
        dest = media_dir / safe_name
        dest.write_bytes(raw)
        saved.append(safe_name)

    return {"uploaded": saved, "count": len(saved)}


@router.get("/{novel_id}/media", response_model=MediaListResponse)
def list_media(
    novel_id: uuid.UUID,
    db: Session = Depends(get_db),
    _token: str = Depends(verify_token),
):
    """List media files associated with a novel."""
    novel = db.query(Novel).filter(Novel.id == novel_id).first()
    if not novel:
        raise HTTPException(404, "Novel not found")

    media_dir = settings.media_input_dir / str(novel_id)
    if not media_dir.exists():
        return MediaListResponse(files=[], count=0)

    from app.api.schemas import MediaFileInfo
    items = []
    for f in sorted(media_dir.iterdir()):
        ext = f.suffix.lower()
        if f.is_file() and ext in _MEDIA_EXTS:
            items.append(MediaFileInfo(name=f.name, type=_media_type(ext), size=f.stat().st_size))
    return MediaListResponse(files=items, count=len(items))


@router.delete("/{novel_id}/media/{filename}", status_code=204)
def delete_media(
    novel_id: uuid.UUID,
    filename: str,
    db: Session = Depends(get_db),
    _token: str = Depends(verify_token),
):
    """Delete a single media file for a novel."""
    novel = db.query(Novel).filter(Novel.id == novel_id).first()
    if not novel:
        raise HTTPException(404, "Novel not found")

    media_dir = settings.media_input_dir / str(novel_id)
    safe_name = Path(filename).name
    target = media_dir / safe_name
    if not target.exists() or not target.is_file():
        raise HTTPException(404, f"File '{safe_name}' not found")
    target.unlink()
