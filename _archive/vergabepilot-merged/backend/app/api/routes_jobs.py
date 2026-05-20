"""
Job submission and retrieval.

POST /api/jobs                  → create a job (async Celery task kicked off)
GET  /api/jobs                  → list recent jobs
GET  /api/jobs/{id}             → full job detail with items
GET  /api/jobs/{id}/documents   → flat list of downloaded documents
DELETE /api/jobs/{id}           → cancel / delete
"""
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, File, UploadFile, Response
from sqlalchemy.orm import Session
import pandas as pd
import io

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
        status=JobStatus.PENDING.value,
    )
    db.add(job)
    db.flush()

    for url in payload.urls:
        url_str = str(url)
        db.add(JobItem(
            job_id=job.id,
            url=url_str,
            domain=urlparse(url_str).netloc,
            status=JobStatus.PENDING.value,
        ))

    db.commit()
    db.refresh(job)

    process_job_task.delay(
        job.id,
        force_strategy=payload.force_strategy.value if payload.force_strategy else None,
        force_model=payload.force_model,
    )

    return _to_job_read(job)


@router.post("/upload", response_model=JobRead, status_code=201)
async def upload_job(
    file: UploadFile = File(...),
    submitted_by: str | None = None,
    force_strategy: str | None = None,
    force_model: str | None = None,
    db: Session = Depends(get_db)
):
    """
    Upload a CSV or Excel file containing a list of URLs to scrape.
    Logic:
    1. Read file into a DataFrame.
    2. Look for a 'url' or 'URL' column.
    3. If not found, use the first column.
    4. Validate URLs and create a job.
    """
    content = await file.read()
    filename = file.filename or "upload"
    
    try:
        if filename.endswith(".csv"):
            df = pd.read_csv(io.BytesIO(content))
        elif filename.endswith((".xls", ".xlsx")):
            df = pd.read_excel(io.BytesIO(content))
        else:
            raise HTTPException(400, "Unsupported file format. Use CSV or Excel.")
    except Exception as e:
        raise HTTPException(400, f"Failed to parse file: {str(e)}")

    # Extract URLs
    url_col = None
    for col in df.columns:
        if str(col).lower() == "url":
            url_col = col
            break
    
    if url_col is not None:
        urls = df[url_col].dropna().astype(str).tolist()
    else:
        # Fallback to first column
        urls = df.iloc[:, 0].dropna().astype(str).tolist()

    # Simple validation (ensure it looks like a URL)
    valid_urls = []
    for u in urls:
        u = u.strip()
        if u.startswith(("http://", "https://")):
            valid_urls.append(u)
    
    if not valid_urls:
        raise HTTPException(400, "No valid URLs found in file.")

    job = Job(
        submitted_by=submitted_by or f"upload:{filename}",
        total_urls=len(valid_urls),
        status=JobStatus.PENDING.value,
    )
    db.add(job)
    db.flush()

    for url in valid_urls:
        db.add(JobItem(
            job_id=job.id,
            url=url,
            domain=urlparse(url).netloc,
            status=JobStatus.PENDING.value,
        ))

    db.commit()
    db.refresh(job)

    process_job_task.delay(job.id, force_strategy=force_strategy, force_model=force_model)

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
    from app.core.storage import ObjectStorage
    
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, "job not found")
        
    storage = ObjectStorage()
    result = []
    for item in job.items:
        for doc in item.documents:
            doc_data = {
                "id": doc.id,
                "filename": doc.filename,
                "mime_type": doc.mime_type,
                "size_bytes": doc.size_bytes,
                "version": doc.version,
                "download_url": f"/jobs/{job_id}/documents/{doc.id}/download",
            }
            result.append(doc_data)
            
    return result

@router.get("/{job_id}/documents/{doc_id}/download")
def download_document(job_id: str, doc_id: str, db: Session = Depends(get_db)):
    from app.core.storage import ObjectStorage
    
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, "job not found")
        
    target_doc = None
    for item in job.items:
        for doc in item.documents:
            if doc.id == doc_id:
                target_doc = doc
                break
        if target_doc:
            break
            
    if not target_doc:
        raise HTTPException(404, "document not found")
        
    storage = ObjectStorage()
    try:
        data = storage.get(target_doc.s3_key)
    except Exception as e:
        raise HTTPException(500, f"Failed to fetch document from storage: {e}")
        
    return Response(
        content=data,
        media_type=target_doc.mime_type or "application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{target_doc.filename}"'
        }
    )

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
