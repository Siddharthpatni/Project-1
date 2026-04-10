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
    """Load a JSONL evaluation dataset."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"dataset not found: {path}")
    out: list[GroundTruth] = []
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
