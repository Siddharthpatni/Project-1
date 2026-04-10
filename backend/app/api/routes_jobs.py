"""
Job submission and retrieval.

POST /api/jobs                  → create a job (async Celery task kicked off)
GET  /api/jobs                  → list recent jobs
GET  /api/jobs/{id}             → full job detail with items
GET  /api/jobs/{id}/documents   → flat list of downloaded documents
DELETE /api/jobs/{id}           → cancel / delete
"""
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Document, Job, JobItem, JobStatus
from app.schemas import (
    DocumentRead,
    JobCreateRequest,
    JobItemRead,
    JobRead,
    JobSummary,
)
from app.workers.tasks import process_job_task

router = APIRouter()


@router.post("", response_model=JobRead, status_code=201)
def create_job(payload: JobCreateRequest, db: Session = Depends(get_db)):
    job = Job(
        submitted_by=payload.submitted_by,
        total_urls=len(payload.urls),
        status=JobStatus.PENDING,
    )
    db.add(job)
    db.flush()

    for url in payload.urls:
        url_str = str(url)
        db.add(JobItem(job_id=job.id, url=url_str, domain=urlparse(url_str).netloc))

    db.commit()
    db.refresh(job)

    process_job_task.delay(
        job.id,
        force_strategy=payload.force_strategy.value if payload.force_strategy else None,
    )

    return _to_job_read(job)


@router.get("", response_model=list[JobSummary])
def list_jobs(limit: int = 50, db: Session = Depends(get_db)):
    jobs = db.query(Job).order_by(Job.created_at.desc()).limit(limit).all()
    return jobs


@router.get("/{job_id}", response_model=JobRead)
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, "job not found")
    return _to_job_read(job)


@router.get("/{job_id}/documents", response_model=list[DocumentRead])
def get_job_documents(job_id: str, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, "job not found")
    docs: list[Document] = []
    for item in job.items:
        docs.extend(item.documents)
    return docs


@router.delete("/{job_id}", status_code=204)
def delete_job(job_id: str, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, "job not found")
    db.delete(job)
    db.commit()


def _to_job_read(job: Job) -> JobRead:
    items = [
        JobItemRead(
            id=i.id,
            url=i.url,
            domain=i.domain,
            status=i.status,
            strategy=i.strategy,
            iterations=i.iterations,
            runtime_seconds=i.runtime_seconds,
            error_message=i.error_message,
            document_count=len(i.documents),
        )
        for i in job.items
    ]
    return JobRead(
        id=job.id,
        created_at=job.created_at,
        updated_at=job.updated_at,
        status=job.status,
        total_urls=job.total_urls,
        completed=job.completed,
        cost_usd=job.cost_usd,
        items=items,
    )
