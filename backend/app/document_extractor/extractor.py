"""
DeepExtractor — orchestrates parsing + field extraction + report generation.

Called by the pipeline after documents are downloaded. Stores result in DB.
All processing is pure-code: no LLM, no external API.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from sqlalchemy.orm import Session

from app.document_extractor.field_extractor import TenderFields, extract_fields, merge_fields
from app.document_extractor.llm_enhancer import enhance_with_llm
from app.document_extractor.parsers import ParsedDocument, parse_file
from app.document_extractor.report_builder import build_report
from app.document_extractor.summarizer import generate_summary
from app.utils.logger import get_logger

log = get_logger(__name__)


class DeepExtractor:
    """
    Given a list of downloaded document paths, extracts structured fields
    and builds a report PDF/DOCX — without any LLM involvement.
    """

    def run(
        self,
        document_paths: list[str],
        source_url: str = "",
        db: Session | None = None,
        job_item_id: str | None = None,
    ) -> ExtractionResult:
        t0 = time.time()
        parsed_docs: list[ParsedDocument] = []

        for path_str in document_paths:
            p = Path(path_str)
            if not p.exists():
                log.warning("extractor.file_missing", path=path_str)
                continue
            try:
                docs = parse_file(p)
                parsed_docs.extend(docs)
                log.info("extractor.parsed", filename=p.name, count=len(docs))
            except Exception as e:  # noqa: BLE001
                log.warning("extractor.parse_error", path=path_str, error=str(e))

        # Step 1: regex baseline from all document text
        combined_text = "\n\n".join(d.text for d in parsed_docs)
        per_doc_fields = [extract_fields(d.text) for d in parsed_docs if d.text.strip()]
        regex_fields = merge_fields([extract_fields(combined_text)] + per_doc_fields)

        # Step 2: LLM enhancement (Gemini 2.5 Flash Lite, free tier)
        # Merges LLM results with regex baseline — LLM wins on specificity.
        # Skipped silently if no API key or LLM call fails.
        try:
            merged = enhance_with_llm(combined_text, regex_fields)
        except Exception as _llm_err:  # noqa: BLE001
            log.warning("extractor.llm_enhance_failed", error=str(_llm_err))
            merged = regex_fields

        # Step 3: deterministic summary — offline, no API, no cost
        try:
            merged = generate_summary(merged)
        except Exception as _sum_err:  # noqa: BLE001
            log.warning("extractor.summarizer_failed", error=str(_sum_err))

        result = ExtractionResult(
            id=str(uuid.uuid4()),
            job_item_id=job_item_id or "",
            source_url=source_url,
            fields=merged,
            parsed_docs=parsed_docs,
            runtime_seconds=round(time.time() - t0, 3),
            created_at=datetime.now(timezone.utc),
        )

        # Persist to DB if session provided
        if db is not None and job_item_id:
            _persist(db, result)

        log.info(
            "extractor.done",
            job_item_id=job_item_id,
            docs=len(parsed_docs),
            vergabenummer=merged.vergabenummer,
            runtime_s=result.runtime_seconds,
        )
        return result

    def build_report(
        self,
        result: "ExtractionResult",
        fmt: Literal["pdf", "docx"] = "pdf",
    ) -> tuple[bytes, str]:
        return build_report(result.fields, result.parsed_docs, result.source_url, fmt)


class ExtractionResult:
    def __init__(
        self,
        id: str,
        job_item_id: str,
        source_url: str,
        fields: TenderFields,
        parsed_docs: list[ParsedDocument],
        runtime_seconds: float,
        created_at: datetime,
    ):
        self.id = id
        self.job_item_id = job_item_id
        self.source_url = source_url
        self.fields = fields
        self.parsed_docs = parsed_docs
        self.runtime_seconds = runtime_seconds
        self.created_at = created_at

    def to_dict(self) -> dict:
        f = asdict(self.fields)
        return {
            "id": self.id,
            "job_item_id": self.job_item_id,
            "source_url": self.source_url,
            "created_at": self.created_at.isoformat(),
            "runtime_seconds": self.runtime_seconds,
            "documents_parsed": len(self.parsed_docs),
            "fields": f,
        }


# ---------------------------------------------------------------------------
# DB persistence helpers
# ---------------------------------------------------------------------------

def _persist(db: Session, result: ExtractionResult) -> None:
    """Upsert an ExtractionRecord row for the given job_item_id."""
    from app.models import ExtractionRecord  # imported here to avoid circular

    try:
        existing = db.query(ExtractionRecord).filter(
            ExtractionRecord.job_item_id == result.job_item_id
        ).first()

        fields_json = json.dumps(asdict(result.fields), ensure_ascii=False)

        if existing:
            existing.fields_json = fields_json
            existing.runtime_seconds = result.runtime_seconds
            existing.docs_parsed = len(result.parsed_docs)
            existing.updated_at = datetime.now(timezone.utc)
        else:
            record = ExtractionRecord(
                id=result.id,
                job_item_id=result.job_item_id,
                source_url=result.source_url,
                fields_json=fields_json,
                runtime_seconds=result.runtime_seconds,
                docs_parsed=len(result.parsed_docs),
            )
            db.add(record)

        db.commit()
        log.info("extractor.db_persisted", job_item_id=result.job_item_id)
    except Exception as e:  # noqa: BLE001
        log.warning("extractor.db_persist_failed", error=str(e))
        db.rollback()
