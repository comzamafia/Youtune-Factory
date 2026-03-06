"""Novel routes — CRUD + pipeline trigger."""

from __future__ import annotations

import math
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.auth import verify_token
from app.api.schemas import (
    BatchPipelineRequest,
    BatchPipelineResponse,
    NovelCreate,
    NovelDetail,
    NovelResponse,
    PipelineResponse,
)
from app.core.database import get_db
from app.core.models import Novel
from app.core.pipeline import run_batch, run_pipeline

router = APIRouter(prefix="/novels", tags=["novels"])


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
