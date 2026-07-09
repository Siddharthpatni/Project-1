"""
Job submission and retrieval API — the primary interface for the scraping pipeline.

Every scraping operation starts here: a client submits a list of URLs, this module
creates the Job + JobItem DB records, and kicks off a Celery task that fans out
to the Phase 3 cascade pipeline.

Endpoints:
──────────
POST /api/jobs                         → create a job (async Celery task kicked off)
POST /api/jobs/smart-domain            → smart domain-aware batch: 1 URL/domain, auto-fallback to backup URL on failure
POST /api/jobs/upload                  → upload CSV/Excel containing URL list
GET  /api/jobs                         → list recent jobs
GET  /api/jobs/{id}                    → full job detail with items
GET  /api/jobs/{id}/documents          → flat list of downloaded documents
GET  /api/jobs/{id}/download-all       → download all docs as ZIP
GET  /api/jobs/{id}/error-report       → per-attempt error breakdown (JSON or CSV)
GET  /api/jobs/{id}/diagnostics        → full domain-level failure analysis with audit trail
GET  /api/jobs/local-files             → list locally stored files (when S3 unavailable)
POST /api/jobs/{id}/items/{item_id}/retry → retry a single failed item
POST /api/jobs/{id}/stop               → cancel a running/pending job
DELETE /api/jobs/{id}                  → delete job and all its records

Job lifecycle:
──────────────
  PENDING → RUNNING (worker picks it up) → SUCCESS / PARTIAL / FAILED
  PARTIAL: some URLs succeeded, some failed
  Jobs with > JOB_CHUNK_SIZE URLs are fanned out across multiple Celery workers
  for horizontal scale-out. Items already in SUCCESS state are skipped on retry.
"""
import io
import zipfile
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, File, UploadFile, Response
from sqlalchemy.orm import Session, joinedload
import pandas as pd

from app.config import settings
from app.database import get_db
from app.models import Job, JobItem, JobStatus
from app.schemas import (
    DocumentRead,
    JobCreateRequest,
    JobItemRead,
    JobRead,
    JobSummary,
    LocalFileRead,
    SmartDomainBatchRequest,
    SmartDomainBatchResult,
)
from app.workers.tasks import process_job_task

router = APIRouter()


@router.post("", response_model=JobRead, status_code=201)
def create_job(payload: JobCreateRequest, db: Session = Depends(get_db)):
    """
    Create a new scraping job and immediately queue it on the Celery task queue.

    The response is returned synchronously after DB commit — the actual scraping
    runs asynchronously in a Celery worker. Poll GET /api/jobs/{id} for progress.

    Optional overrides:
      force_strategy: skip the cascade and use exactly one strategy (e.g. "llm_generated_scraper")
      force_model:    override the LLM model used for generation (e.g. "anthropic/claude-3-haiku")
    """
    job = Job(
        submitted_by=payload.submitted_by,
        total_urls=len(payload.urls),
        status=JobStatus.PENDING.value,
    )
    db.add(job)
    # flush() assigns the DB-generated ID without committing so we can create
    # JobItems referencing job.id in the same transaction.
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

    # Kick off the Celery task — returns immediately, task runs in background.
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
        raise HTTPException(400, f"Failed to parse file: {str(e)}") from e

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


@router.post("/smart-domain", response_model=SmartDomainBatchResult, status_code=202)
def create_smart_domain_batch(payload: SmartDomainBatchRequest, db: Session = Depends(get_db)):
    """
    Smart domain-aware batch job.

    For each domain in `domain_urls`:
    - Submit the **first** URL as the primary target.
    - If the primary fails after cascade, the system automatically retries
      with the **second** URL (backup) for that domain.

    Maximum 2 URL attempts per domain. Only one URL is in-flight per
    domain at any time — the fallback job is queued after the primary
    finishes so the scraper registry is populated before the retry.
    """
    from app.workers.tasks import smart_domain_batch_task  # noqa: PLC0415

    domain_urls = payload.domain_urls
    if not domain_urls:
        raise HTTPException(400, "domain_urls must not be empty")

    # Build primary job (one URL per domain)
    primary_urls = [urls[0] for urls in domain_urls.values() if urls]
    domains_with_backup = sum(1 for urls in domain_urls.values() if len(urls) >= 2)

    primary_job = Job(
        submitted_by=payload.submitted_by or "smart-domain-batch",
        total_urls=len(primary_urls),
        status=JobStatus.PENDING.value,
    )
    db.add(primary_job)
    db.flush()

    for url in primary_urls:
        db.add(JobItem(
            job_id=primary_job.id,
            url=url,
            domain=urlparse(url).netloc,
            status=JobStatus.PENDING.value,
        ))

    db.commit()
    db.refresh(primary_job)

    # Build backup mapping: domain → backup_url
    backup_map: dict[str, str] = {
        domain: urls[1]
        for domain, urls in domain_urls.items()
        if len(urls) >= 2
    }

    # Run primary job, then auto-queue fallback for failed domains.
    smart_domain_batch_task.delay(
        primary_job_id=primary_job.id,
        backup_map=backup_map,
        submitted_by=payload.submitted_by,
        force_strategy=payload.force_strategy,
        force_model=payload.force_model,
    )

    return SmartDomainBatchResult(
        primary_job_id=primary_job.id,
        fallback_job_id=None,    # set by the Celery task after primary finishes
        domains_total=len(domain_urls),
        domains_with_backup=domains_with_backup,
        status="queued",
    )


@router.get("", response_model=list[JobSummary])
def list_jobs(limit: int = 50, db: Session = Depends(get_db)):
    jobs = (
        db.query(Job)
        .options(joinedload(Job.items))
        .order_by(Job.created_at.desc())
        .limit(limit)
        .all()
    )
    result = []
    for job in jobs:
        domains = list(dict.fromkeys(i.domain for i in job.items if i.domain))
        first_url = job.items[0].url if job.items else None
        result.append(JobSummary(
            id=job.id,
            created_at=job.created_at,
            status=job.status,
            total_urls=job.total_urls,
            completed=job.completed,
            cost_usd=job.cost_usd,
            domains=domains,
            first_url=first_url,
        ))
    return result


@router.get("/local-files", response_model=list[LocalFileRead])
def list_local_files(db: Session = Depends(get_db)):
    """List all files persisted in local fallback storage, organized by domain."""
    fallback_dir = Path(settings.downloads_dir) / "_s3_fallback" / "jobs"
    result = []
    if not fallback_dir.exists():
        return result

    for job_dir in sorted(fallback_dir.iterdir()):
        if not job_dir.is_dir():
            continue
        job_id = job_dir.name
        job = db.query(Job).filter(Job.id == job_id).first()
        for item_dir in sorted(job_dir.iterdir()):
            if not item_dir.is_dir():
                continue
            item_id = item_dir.name
            domain = ""
            if job:
                item = next((i for i in job.items if i.id == item_id), None)
                domain = item.domain if item else ""
            for f in sorted(item_dir.iterdir()):
                if f.is_file():
                    result.append(LocalFileRead(
                        filename=f.name,
                        size_bytes=f.stat().st_size,
                        domain=domain,
                        job_id=job_id,
                        item_id=item_id,
                        download_url=f"/jobs/{job_id}/documents-by-path/{item_id}/{f.name}",
                    ))
    return result


@router.get("/needs-manual")
def needs_manual_queue(limit: int = 200, job_id: str | None = None, db: Session = Depends(get_db)):
    """Items whose only path forward is a human stepping in (login / CAPTCHA).

    These are not silent failures — the cascade correctly determined that no
    automated strategy can succeed without credentials or solving a bot check.
    Surfacing them lets an operator act (log in, then retry) instead of the URL
    quietly counting as "failed".
    """
    from app.phase3_integration.outcomes import (  # noqa: PLC0415
        NEEDS_MANUAL_CATEGORIES, SUGGESTED_ACTIONS, BUCKET_LABELS, bucket_for,
    )

    q = (
        db.query(JobItem)
        .filter(JobItem.status == JobStatus.FAILED.value)
        .filter(JobItem.failure_category.in_(tuple(NEEDS_MANUAL_CATEGORIES)))
    )
    if job_id:
        q = q.filter(JobItem.job_id == job_id)
    items = q.order_by(JobItem.id).limit(limit).all()

    rows = []
    for it in items:
        bucket = bucket_for(it.failure_category)
        rows.append({
            "job_id":           it.job_id,
            "item_id":          it.id,
            "url":              it.url,
            "domain":           it.domain,
            "failure_category": it.failure_category,
            "bucket":           bucket,
            "bucket_label":     BUCKET_LABELS.get(bucket, bucket),
            "reason":           (it.error_message or "")[:300],
            "suggested_action": SUGGESTED_ACTIONS.get(bucket, ""),
            "retry_url":        f"/jobs/{it.job_id}/items/{it.id}/retry",
        })
    return {"total": len(rows), "items": rows}


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

    result = []
    for item in job.items:
        for doc in item.documents:
            doc_data = {
                "id": doc.id,
                "job_item_id": item.id,          # lets the frontend group docs under their URL
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
        raise HTTPException(500, f"Failed to fetch document from storage: {e}") from e

    return Response(
        content=data,
        media_type=target_doc.mime_type or "application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{target_doc.filename}"'
        }
    )

@router.get("/{job_id}/download-all")
def download_all_documents(job_id: str, db: Session = Depends(get_db)):
    """Download all documents for a job as a single ZIP file."""
    from app.core.storage import ObjectStorage

    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, "job not found")

    storage = ObjectStorage()
    buf = io.BytesIO()
    seen: dict[str, int] = {}

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in job.items:
            domain = item.domain or "unknown"
            for doc in item.documents:
                try:
                    data = storage.get(doc.s3_key)
                except Exception:
                    continue
                # Namespace by domain to avoid collisions across items
                arcname = f"{domain}/{doc.filename}"
                if arcname in seen:
                    seen[arcname] += 1
                    base, ext = doc.filename.rsplit(".", 1) if "." in doc.filename else (doc.filename, "")
                    arcname = f"{domain}/{base}__{seen[arcname]}.{ext}" if ext else f"{domain}/{base}__{seen[arcname]}"
                else:
                    seen[arcname] = 0
                zf.writestr(arcname, data)

    buf.seek(0)
    safe_id = job_id[:8]
    return Response(
        content=buf.read(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="job-{safe_id}-documents.zip"'},
    )


@router.get("/{job_id}/documents-by-path/{item_id}/{filename}")
def download_local_file(job_id: str, item_id: str, filename: str):
    """Serve a file directly from local fallback storage."""
    import mimetypes
    path = Path(settings.downloads_dir) / "_s3_fallback" / "jobs" / job_id / item_id / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(404, "file not found in local storage")
    mime, _ = mimetypes.guess_type(filename)
    return Response(
        content=path.read_bytes(),
        media_type=mime or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{job_id}/items/{item_id}/retry", status_code=202)
def retry_job_item(
    job_id: str,
    item_id: str,
    force_strategy: str | None = None,
    force_model: str | None = None,
    db: Session = Depends(get_db),
):
    """Re-queue a single failed job item through the cascade pipeline."""
    from app.workers.tasks import process_job_task

    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, "job not found")

    item = next((i for i in job.items if i.id == item_id), None)
    if not item:
        raise HTTPException(404, "item not found")

    if item.status not in (JobStatus.FAILED.value, JobStatus.PENDING.value):
        raise HTTPException(400, f"item status is '{item.status}' — only failed or pending items can be retried")

    # Reset the item so the worker processes it fresh.
    item.status = JobStatus.PENDING.value
    item.error_message = None
    item.iterations = 0
    item.runtime_seconds = 0.0
    db.commit()

    # Re-run the whole job task; it will skip already-succeeded items.
    process_job_task.delay(job_id, force_strategy=force_strategy, force_model=force_model)
    return {"status": "queued", "item_id": item_id, "job_id": job_id}


@router.get("/{job_id}/error-report")
def download_error_report(job_id: str, fmt: str = "json", db: Session = Depends(get_db)):
    """
    Download a comprehensive error report for a job.

    ?fmt=json  (default) — structured JSON with full attempt chain per URL
    ?fmt=csv            — flat CSV for import into Excel / Sheets
    """
    import csv
    import io as _io
    from app.core.security import classify_error

    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, "job not found")

    rows = []
    for item in job.items:
        # Build a summary of all strategies attempted
        attempts = item.attempts_detail or []
        for attempt in attempts:
            rows.append({
                "job_id":         job_id,
                "item_id":        item.id,
                "url":            item.url,
                "domain":         item.domain,
                "item_status":    item.status,
                "strategy":       attempt.get("strategy", ""),
                "attempt_success": attempt.get("success", False),
                "documents":      attempt.get("downloaded", 0),
                "duration_s":     attempt.get("duration_s", 0),
                "timestamp":      attempt.get("timestamp", ""),
                "error_category": attempt.get("error_category", ""),
                "error_reason":   attempt.get("error_reason", ""),
                "error_raw":      attempt.get("error_raw", ""),
            })
        # If no attempts were recorded (pre-cascade failure), add one row
        if not attempts:
            err_cat = classify_error(item.error_message)
            rows.append({
                "job_id":         job_id,
                "item_id":        item.id,
                "url":            item.url,
                "domain":         item.domain,
                "item_status":    item.status,
                "strategy":       item.strategy,
                "attempt_success": item.status == "success",
                "documents":      len(item.documents),
                "duration_s":     round(item.runtime_seconds, 2),
                "timestamp":      "",
                "error_category": err_cat,
                "error_reason":   item.error_message or "",
                "error_raw":      item.error_message or "",
            })

    if fmt == "csv":
        buf = _io.StringIO()
        if rows:
            writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        return Response(
            content=buf.getvalue().encode("utf-8"),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="error-report-{job_id[:8]}.csv"'},
        )

    return {
        "job_id": job_id,
        "total_attempts": len(rows),
        "failed_attempts": sum(1 for r in rows if not r["attempt_success"]),
        "rows": rows,
    }


@router.post("/{job_id}/stop", status_code=200)
def stop_job(job_id: str, db: Session = Depends(get_db)):
    """
    Gracefully stop a running or pending job.

    Marks the job and all of its pending/running items as FAILED so
    no new work starts. Already-succeeded items are left untouched.
    Workers that are currently mid-scrape will finish their current
    URL but the pipeline will not process further items.
    """
    from app.utils.audit import WARNING, write_audit

    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, "job not found")

    if job.status not in (JobStatus.PENDING.value, JobStatus.RUNNING.value):
        raise HTTPException(400, f"job is '{job.status}' — only pending/running jobs can be stopped")

    stopped_items = 0
    for item in job.items:
        if item.status in (JobStatus.PENDING.value, JobStatus.RUNNING.value):
            item.status = JobStatus.FAILED.value
            item.error_message = "Manually stopped by user"
            stopped_items += 1

    job.status = JobStatus.FAILED.value
    db.commit()

    write_audit(
        "job.stopped",
        f"Job {job_id} manually stopped — {stopped_items} items cancelled",
        level=WARNING,
        job_id=job_id,
        metadata={"stopped_items": stopped_items},
    )

    return {
        "status": "stopped",
        "job_id": job_id,
        "items_cancelled": stopped_items,
    }


@router.get("/{job_id}/diagnostics")
def job_diagnostics(job_id: str, db: Session = Depends(get_db)):
    """
    Return a detailed failure breakdown for a job — which domains failed,
    why they failed, which strategy was attempted, and how many iterations
    were spent — so operators can understand what went wrong at a glance.
    """
    from app.core.security import classify_error
    from app.models import AuditLog

    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, "job not found")

    # Audit trail for this job
    audit_events = (
        db.query(AuditLog)
        .filter(AuditLog.job_id == job_id)
        .order_by(AuditLog.created_at.asc())
        .all()
    )

    failed_items = [i for i in job.items if i.status == JobStatus.FAILED.value]
    succeeded_items = [i for i in job.items if i.status == JobStatus.SUCCESS.value]
    pending_items = [i for i in job.items if i.status in (JobStatus.PENDING.value, JobStatus.RUNNING.value)]

    # Error category breakdown
    error_summary: dict[str, int] = {}
    for item in failed_items:
        cat = classify_error(item.error_message)
        error_summary[cat] = error_summary.get(cat, 0) + 1

    # Per-domain results
    domain_results: dict[str, dict] = {}
    for item in job.items:
        d = item.domain or "unknown"
        if d not in domain_results:
            domain_results[d] = {"succeeded": 0, "failed": 0, "pending": 0, "urls": []}
        domain_results[d][item.status if item.status in ("succeeded","failed","pending") else item.status] = \
            domain_results[d].get(item.status, 0) + 1
        domain_results[d]["urls"].append({
            "url": item.url,
            "status": item.status,
            "strategy": item.strategy,
            "iterations": item.iterations,
            "runtime_seconds": round(item.runtime_seconds, 2),
            "error": item.error_message[:500] if item.error_message else None,
            "documents": len(item.documents),
        })

    return {
        "job_id": job_id,
        "status": job.status,
        "total_urls": job.total_urls,
        "succeeded": len(succeeded_items),
        "failed": len(failed_items),
        "pending": len(pending_items),
        "cost_usd": round(job.cost_usd or 0.0, 4),
        "error_category_breakdown": error_summary,
        "domain_results": domain_results,
        "audit_trail": [
            {
                "time": str(e.created_at),
                "level": e.level,
                "event": e.event_type,
                "domain": e.domain,
                "strategy": e.strategy,
                "message": e.message[:300],
            }
            for e in audit_events
        ],
    }


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
