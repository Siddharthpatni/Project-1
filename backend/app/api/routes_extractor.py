"""
API routes for the deep extraction layer.

GET  /extract/{job_item_id}              — return extracted fields as JSON
GET  /extract/{job_item_id}/report       — download structured report (PDF or DOCX)
POST /extract/{job_item_id}/trigger      — re-run extraction for a job item
"""
from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Document, ExtractionRecord, Job, JobItem

router = APIRouter(prefix="/extract", tags=["extraction"])


@router.get("")
def list_extractions(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Return the most recent extraction records with their fields."""
    records = (
        db.query(ExtractionRecord)
        .order_by(ExtractionRecord.created_at.desc())
        .limit(limit)
        .all()
    )
    result = []
    for r in records:
        try:
            fields = json.loads(r.fields_json or "{}")
        except Exception:
            fields = {}
        result.append({
            "id": r.id,
            "job_item_id": r.job_item_id,
            "source_url": r.source_url or "",
            "docs_parsed": r.docs_parsed or 0,
            "runtime_seconds": r.runtime_seconds or 0.0,
            "created_at": r.created_at.isoformat() if r.created_at else "",
            "fields": fields,
        })
    return result


@router.get("/{job_item_id}")
def get_extraction(job_item_id: str, db: Session = Depends(get_db)):
    """Return extracted fields as structured JSON."""
    record = db.query(ExtractionRecord).filter(
        ExtractionRecord.job_item_id == job_item_id
    ).first()
    if record is None:
        raise HTTPException(status_code=404, detail="No extraction result for this job item")

    fields = json.loads(record.fields_json or "{}")
    return {
        "id": record.id,
        "job_item_id": record.job_item_id,
        "source_url": record.source_url,
        "docs_parsed": record.docs_parsed,
        "runtime_seconds": record.runtime_seconds,
        "created_at": record.created_at.isoformat(),
        "fields": fields,
    }


@router.get("/{job_item_id}/report")
def download_report(
    job_item_id: str,
    fmt: Literal["pdf", "docx"] = Query(default="pdf"),
    db: Session = Depends(get_db),
):
    """
    Generate and download a structured extraction report.
    Query param: fmt=pdf (default) or fmt=docx
    """
    record = db.query(ExtractionRecord).filter(
        ExtractionRecord.job_item_id == job_item_id
    ).first()
    if record is None:
        raise HTTPException(status_code=404, detail="No extraction result found")

    item = db.query(JobItem).filter(JobItem.id == job_item_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Job item not found")

    # Rebuild fields object — only pass known fields to handle schema evolution
    from app.document_extractor.field_extractor import TenderFields
    from dataclasses import fields as dc_fields

    fields_dict = json.loads(record.fields_json or "{}")
    known = {f.name for f in dc_fields(TenderFields)}
    tf = TenderFields(**{k: fields_dict[k] for k in known if k in fields_dict})
    # Ensure list fields are lists (guards against null stored in DB)
    for list_field in ("cpv_codes", "nuts_codes", "zuschlagskriterien", "eignungskriterien",
                       "lose", "additional_notes", "kernpunkte"):
        val = getattr(tf, list_field, None)
        if val is None:
            setattr(tf, list_field, [])

    # Use filenames only — re-downloading from S3 is too slow for a synchronous
    # HTTP response and causes the Next.js proxy to ECONNRESET. The extracted
    # fields already contain all the structured data; full-text excerpts are omitted.
    from app.document_extractor.parsers import ParsedDocument
    from app.document_extractor.report_builder import build_report

    docs = db.query(Document).filter(Document.job_item_id == job_item_id).all()
    parsed_docs: list[ParsedDocument] = [
        ParsedDocument(filename=doc.filename, text="") for doc in docs
    ]

    try:
        report_bytes, mime = build_report(tf, parsed_docs, record.source_url, fmt)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Report generation failed: {e}") from e

    ext = "pdf" if fmt == "pdf" else "docx"
    filename = f"vergabepilot_extraction_{job_item_id[:8]}.{ext}"

    return Response(
        content=report_bytes,
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/job/{job_id}")
def trigger_job_extraction(job_id: str, db: Session = Depends(get_db)):
    """
    Dispatch deep extraction for all items in a job as a background Celery task.
    Returns immediately with a task_id the client can poll via GET /extract/task/{task_id}.
    """
    job = db.query(Job).filter(Job.id == job_id).first()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    from app.workers.tasks import extract_job_task
    task = extract_job_task.delay(job_id)
    return {"task_id": task.id, "status": "queued", "job_id": job_id}


@router.get("/task/{task_id}")
def get_task_status(task_id: str):
    """Poll the status of a background extraction task."""
    from app.workers.celery_app import celery_app as _celery
    result = _celery.AsyncResult(task_id)
    state = result.state.lower()
    if result.ready():
        if result.successful():
            return {"status": "done", "result": result.get()}
        return {"status": "failed", "error": str(result.result)}
    return {"status": state}


@router.post("/{job_item_id}/trigger")
def trigger_extraction(job_item_id: str, db: Session = Depends(get_db)):
    """Re-run the deep extractor for a completed job item."""
    item = db.query(JobItem).filter(JobItem.id == job_item_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Job item not found")

    docs = db.query(Document).filter(Document.job_item_id == job_item_id).all()
    if not docs:
        raise HTTPException(status_code=422, detail="No downloaded documents to extract from")

    from app.core.storage import ObjectStorage
    from app.document_extractor.extractor import DeepExtractor
    from pathlib import Path
    import tempfile

    storage = ObjectStorage()
    tmp_paths: list[str] = []
    try:
        for doc in docs:
            data = storage.get(doc.s3_key)
            suffix = Path(doc.filename).suffix.lower()
            tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
            tmp.write(data)
            tmp.close()
            tmp_paths.append(tmp.name)

        extractor = DeepExtractor()
        result = extractor.run(
            document_paths=tmp_paths,
            source_url=item.url,
            db=db,
            job_item_id=job_item_id,
        )
        return result.to_dict()
    finally:
        for p in tmp_paths:
            Path(p).unlink(missing_ok=True)
