"""Job routes — View job queue status."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.auth import verify_token
from app.api.schemas import JobResponse
from app.core.database import get_db
from app.core.models import Job

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=list[JobResponse])
def list_jobs(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    status: str | None = Query(None),
    job_type: str | None = Query(None),
    novel_id: uuid.UUID | None = Query(None),
    db: Session = Depends(get_db),
    _token: str = Depends(verify_token),
):
    """List jobs with optional filters."""
    q = db.query(Job)
    if status:
        q = q.filter(Job.status == status)
    if job_type:
        q = q.filter(Job.job_type == job_type)
    if novel_id:
        q = q.filter(Job.novel_id == novel_id)
    q = q.order_by(Job.created_at.desc())
    jobs = q.offset((page - 1) * limit).limit(limit).all()
    return jobs


@router.get("/{job_id}", response_model=JobResponse)
def get_job(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    _token: str = Depends(verify_token),
):
    """Get a single job's status."""
    job = db.query(Job).filter(Job.job_id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
