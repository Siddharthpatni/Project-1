from __future__ import annotations

import hashlib
from pathlib import Path

from tender_agent.models import DocumentCandidate
from tender_agent.utils import (
    DOCUMENT_EXTENSIONS,
    IMPORTANT_KEYWORDS,
    IMAGE_EXTENSIONS,
    UNIMPORTANT_EXTENSIONS,
    UNIMPORTANT_KEYWORDS,
    extract_extension,
    is_probably_document_url,
    looks_like_document_text,
    normalize_url,
)


def priority_for_score(score: int) -> str:
    if score >= 7:
        return "high"
    if score >= 4:
        return "medium"
    return "low"


def score_candidate(candidate: DocumentCandidate) -> tuple[int, str]:
    haystack = " ".join(
        part for part in (candidate.name, candidate.link_text, candidate.url) if part
    ).lower()
    extension = candidate.extension or extract_extension(candidate.url)
    score = 0
    reasons: list[str] = []

    if extension in DOCUMENT_EXTENSIONS:
        score += 3
        reasons.append(f"document extension {extension}")

    if is_probably_document_url(candidate.url):
        score += 2
        reasons.append("download-style url")

    if looks_like_document_text(candidate.link_text or candidate.name):
        score += 2
        reasons.append("document-style label")

    for keyword in IMPORTANT_KEYWORDS:
        if keyword in haystack:
            score += 4 if keyword in {"boq", "bill of quantity", "bill of quantities"} else 2
            reasons.append(f"keyword:{keyword}")

    for keyword in UNIMPORTANT_KEYWORDS:
        if keyword in haystack:
            score -= 4
            reasons.append(f"unimportant:{keyword}")

    if extension in IMAGE_EXTENSIONS or extension in UNIMPORTANT_EXTENSIONS:
        score -= 8
        reasons.append(f"blocked extension {extension}")

    if "archive" in haystack or extension in {".zip", ".rar", ".7z"}:
        score += 1
        reasons.append("archive may contain tender pack")

    return score, ", ".join(reasons) or "no strong signal"


def select_important_documents(
    candidates: list[DocumentCandidate],
) -> tuple[list[DocumentCandidate], int]:
    chosen: list[DocumentCandidate] = []
    seen_urls: set[str] = set()

    for candidate in candidates:
        canonical_url = normalize_url(candidate.url)
        if canonical_url in seen_urls:
            continue

        score, reason = score_candidate(candidate)
        candidate.score = score
        candidate.reason = reason
        candidate.priority = priority_for_score(score)
        if score >= 4:
            chosen.append(candidate)
            seen_urls.add(canonical_url)

    return chosen, len(seen_urls)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_download(
    candidate: DocumentCandidate,
    path: Path,
    content_type: str | None,
    known_hashes: set[str],
) -> tuple[bool, str]:
    if not path.exists() or path.stat().st_size == 0:
        return False, "empty file"

    lower_name = path.name.lower()
    if any(keyword in lower_name for keyword in UNIMPORTANT_KEYWORDS):
        return False, "file name looks unrelated to the tender"

    if content_type and content_type.startswith("image/"):
        return False, f"unexpected image content type {content_type}"

    if content_type in {"text/html", "application/xhtml+xml"}:
        return False, f"unexpected page content type {content_type}"

    if path.suffix.lower() in {".html", ".htm"}:
        return False, "download resolved to an HTML page instead of a document"

    file_hash = sha256_file(path)
    if file_hash in known_hashes:
        return False, "duplicate file content"

    known_hashes.add(file_hash)

    if candidate.score < 4:
        return False, "relevance score dropped below threshold"

    return True, candidate.reason
