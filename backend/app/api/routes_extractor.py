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
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Document, ExtractionRecord, Job, JobItem, JobStatus

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

    # Re-parse source documents for full text
    from pathlib import Path
    from app.document_extractor.parsers import parse_file, ParsedDocument
    from app.document_extractor.report_builder import build_report

    parsed_docs: list[ParsedDocument] = []
    docs = db.query(Document).filter(Document.job_item_id == job_item_id).all()
    from app.core.storage import ObjectStorage
    storage = ObjectStorage()
    for doc in docs:
        try:
            data = storage.get(doc.s3_key)
            import io, tempfile
            suffix = Path(doc.filename).suffix.lower()
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(data)
                tmp_path = Path(tmp.name)
            parts = parse_file(tmp_path)
            for p in parts:
                p.filename = doc.filename
            parsed_docs.extend(parts)
            tmp_path.unlink(missing_ok=True)
        except Exception:
            parsed_docs.append(ParsedDocument(filename=doc.filename, text=""))

    try:
        report_bytes, mime = build_report(tf, parsed_docs, record.source_url, fmt)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Report generation failed: {e}")

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
    Trigger deep extraction for all items in a job.

    Works in two modes:
    - S3 mode: retrieves previously stored documents from MinIO/S3
    - Live mode: downloads documents directly from the source URL when S3
      has nothing (fallback for jobs where scraping failed or files were deleted)
    """
    job = db.query(Job).filter(Job.id == job_id).first()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    # Include ALL items (not just success) so live fetch can rescue failed scrapes
    items = (
        db.query(JobItem)
        .filter(JobItem.job_id == job_id)
        .all()
    )

    from app.core.storage import ObjectStorage
    from app.document_extractor.extractor import DeepExtractor
    from app.document_extractor.live_fetcher import fetch_documents
    from dataclasses import asdict as _asdict
    from pathlib import Path
    import tempfile

    storage  = ObjectStorage()
    extractor = DeepExtractor()
    results: list[dict] = []

    for item in items:
        tmp_paths: list[str] = []
        source   = "s3"
        try:
            # ── 1. Try S3 first ─────────────────────────────────────
            docs = db.query(Document).filter(Document.job_item_id == item.id).all()
            for doc in docs:
                try:
                    data = storage.get(doc.s3_key)
                    suffix = Path(doc.filename).suffix.lower()
                    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
                    tmp.write(data)
                    tmp.close()
                    tmp_paths.append(tmp.name)
                except Exception:  # noqa: BLE001
                    pass  # S3 retrieval failed for this doc, try next

            # ── 2. Live fetch fallback when S3 returned nothing ──────
            if not tmp_paths:
                source = "live"
                tmp_paths = fetch_documents(item.url)

            if not tmp_paths:
                results.append({
                    "job_item_id": item.id,
                    "url": item.url,
                    "error": (
                        "no documents found — S3 empty and live fetch returned nothing. "
                        "The portal may require authentication or the tender may be expired."
                    ),
                })
                continue

            # ── 3. Extract fields from whatever we got ───────────────
            result = extractor.run(
                document_paths=tmp_paths,
                source_url=item.url,
                db=db,
                job_item_id=item.id,
            )
            fields_dict  = _asdict(result.fields)
            fields_found = sum(
                1 for v in fields_dict.values()
                if v and (not isinstance(v, list) or len(v) > 0)
            )
            results.append({
                "job_item_id":    item.id,
                "url":            item.url,
                "source":         source,
                "docs_parsed":    len(result.parsed_docs),
                "fields_found":   fields_found,
                "runtime_seconds": result.runtime_seconds,
            })

        except Exception as e:  # noqa: BLE001
            results.append({
                "job_item_id": item.id,
                "url":         item.url,
                "error":       f"{type(e).__name__}: {e}",
            })
        finally:
            # Only clean up live-fetched temp files; S3 temps are cleaned above
            if source == "live":
                for p in tmp_paths:
                    Path(p).unlink(missing_ok=True)

    successful = [r for r in results if "error" not in r]
    failed     = [r for r in results if "error" in r]
    live_fetched = [r for r in successful if r.get("source") == "live"]

    return {
        "job_id":      job_id,
        "extracted":   len(successful),
        "failed":      len(failed),
        "live_fetched": len(live_fetched),
        "results":     results,
    }


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
