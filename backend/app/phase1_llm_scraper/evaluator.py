"""
Evaluation metrics for Phase 1.

Given a ground-truth dataset entry (URL + expected document count/types)
and the output of `executor.execute`, compute:
- success flag
- recall (downloaded vs. expected)
- runtime & cost passthrough
"""
from __future__ import annotations

import json
import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path

from app.phase1_llm_scraper.executor import ExecutionResult
from app.phase1_llm_scraper.pricing import (  # noqa: F401 — re-exported
    MODEL_PRICING,
    calc_cost,
    format_comparison_table,
)


@dataclass
class GroundTruth:
    url: str
    expected_doc_count: int
    expected_extensions: list[str]  # e.g. ["pdf", "docx", "zip"]
    notes: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "GroundTruth":
        return cls(
            url=d["url"],
            expected_doc_count=int(d.get("expected_doc_count", 0)),
            expected_extensions=[e.lower().lstrip(".") for e in d.get("expected_extensions", [])],
            notes=d.get("notes", ""),
        )


@dataclass
class EvaluationMetrics:
    success: bool
    recall: float
    downloaded_count: int
    expected_count: int
    matched_extensions: int
    runtime_seconds: float


def evaluate(truth: GroundTruth, result: ExecutionResult) -> EvaluationMetrics:
    downloaded = result.downloaded_files
    count = len(downloaded)

    # Recall against expected count (capped at 1.0)
    if truth.expected_doc_count > 0:
        recall = min(count / truth.expected_doc_count, 1.0)
    else:
        recall = 1.0 if count > 0 else 0.0

    # Extension match
    got_exts = {_ext(f) for f in downloaded}
    matched = len(got_exts & set(truth.expected_extensions))

    success = result.success and count > 0 and recall >= 0.5

    return EvaluationMetrics(
        success=success,
        recall=round(recall, 3),
        downloaded_count=count,
        expected_count=truth.expected_doc_count,
        matched_extensions=matched,
        runtime_seconds=result.runtime_seconds,
    )


def load_dataset(path: str) -> list[GroundTruth]:
    """Load a JSONL or CSV evaluation dataset."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"dataset not found: {path}")
    out: list[GroundTruth] = []

    if p.suffix.lower() == ".csv":
        import csv
        seen_domains = set()
        # Skipped domains known to require authentication or block requests
        skipped_domains = {
            "bieterportal.noncd.db.de",
            "vergabeplattform.charite.de",
            "www.ausschreibungen.ls.brandenburg.de",
            "www.vergabe.stadt-frankfurt.de",
            "landesverwaltung.vergabe.rlp.de",
        }
        with open(p, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                url = (row.get("url") or "").strip()
                state = (row.get("state") or "").strip().upper()
                domain = (row.get("domain") or "").strip()
                if not url or state != "COMPLETED":
                    continue
                if domain in skipped_domains:
                    continue
                if domain in seen_domains:
                    continue
                seen_domains.add(domain)

                out.append(GroundTruth(
                    url=url,
                    expected_doc_count=1,
                    expected_extensions=["zip"],
                    notes=f"CSV Export - {domain}",
                ))
                if len(out) >= 5:  # Sensible default limit for evaluation runs
                    break
    else:
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            out.append(GroundTruth.from_dict(json.loads(line)))
    return out


def _ext(path: str) -> str:
    ext = os.path.splitext(path)[1].lstrip(".").lower()
    if ext:
        return ext
    mime, _ = mimetypes.guess_type(path)
    if mime:
        return mime.split("/")[-1]
    return ""
