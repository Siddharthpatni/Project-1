"""
Rule Summarizer — template-based narrative generation from extracted fields.

Algorithm:
  Pure string composition. No LLM, no API, no inference.
  Only fields that have a non-None value contribute to the output.
  Fields with None are silently skipped — 'N/A' never appears.

  generate_summary(fields, filename) → dict with:
    "paragraph" : 100–180 word prose introduction
    "bullets"   : list of short "Label: value" strings
"""
from __future__ import annotations

import re


def generate_summary(fields: dict, filename: str) -> dict:
    """
    Compose a human-readable summary from the extracted fields dict.

    `fields` is the same dict structure returned by extract_all_fields:
    { field_name: ExtractedField | dict }.  Both dataclass and plain dict
    are handled so the function can be called in tests without full pipeline.

    Returns:
      { "paragraph": str, "bullets": list[str] }
    Both keys are always present; values may be empty string / empty list
    if no fields have values.
    """
    # Normalise field values — accept both ExtractedField and plain dict
    def _val(name: str):
        f = fields.get(name)
        if f is None:
            return None
        if hasattr(f, "value"):
            return f.value if f.value not in (None, "", [], {}) else None
        if isinstance(f, dict):
            v = f.get("value")
            return v if v not in (None, "", [], {}) else None
        return f if f not in (None, "", [], {}) else None

    tender_type        = _val("tender_type")
    issuing_authority  = _val("issuing_authority")
    tender_title       = _val("tender_title")
    tender_id          = _val("tender_id")
    publication_date   = _val("publication_date")
    submission_deadline = _val("submission_deadline")
    tender_value       = _val("tender_value")
    scope_of_work      = _val("scope_of_work")
    eligibility        = _val("eligibility")
    contact_email      = _val("contact_email")
    contact_name       = _val("contact_name")
    contact_phone      = _val("contact_phone")
    cpv_codes          = _val("cpv_codes")

    sentences: list[str] = []
    bullets: list[str] = []

    # ── Introduction sentence ──────────────────────────────────────────────
    intro_parts: list[str] = []

    if tender_type:
        intro_parts.append(f"{tender_type} tender")
    else:
        intro_parts.append("Tender")

    if issuing_authority:
        intro_parts.append(f"issued by {issuing_authority}")
        bullets.append(f"Issuing authority: {issuing_authority}")

    if tender_title:
        intro_parts.append(f"for {_truncate(tender_title, 120)}")
        bullets.append(f"Title: {_truncate(tender_title, 120)}")

    if tender_id:
        intro_parts.append(f"(Reference: {tender_id})")
        bullets.append(f"Reference: {tender_id}")

    sentences.append(" ".join(intro_parts) + ".")

    # ── Publication & deadline ─────────────────────────────────────────────
    if publication_date:
        sentences.append(f"This tender was published on {_fmt_date(publication_date)}.")
        bullets.append(f"Publication date: {_fmt_date(publication_date)}")

    if submission_deadline:
        sentences.append(f"The closing date for submissions is {_fmt_date(submission_deadline)}.")
        bullets.append(f"Deadline: {_fmt_date(submission_deadline)}")

    # ── Value ─────────────────────────────────────────────────────────────
    if tender_value:
        value_str = _fmt_value(tender_value)
        if value_str:
            sentences.append(f"The estimated contract value is {value_str}.")
            bullets.append(f"Estimated value: {value_str}")

    # ── Tender type bullet ─────────────────────────────────────────────────
    if tender_type:
        bullets.append(f"Type: {tender_type}")

    # ── CPV codes ─────────────────────────────────────────────────────────
    if cpv_codes:
        if isinstance(cpv_codes, list):
            cpv_str = ", ".join(str(c) for c in cpv_codes[:5])
        else:
            cpv_str = str(cpv_codes)
        sentences.append(f"CPV code(s): {cpv_str}.")
        bullets.append(f"CPV codes: {cpv_str}")

    # ── Scope (first 2 sentences) ─────────────────────────────────────────
    if scope_of_work:
        scope_text = _extract_first_sentences(str(scope_of_work), n=2)
        if scope_text:
            sentences.append(scope_text)

    # ── Eligibility (first 3 bullet-like sentences) ───────────────────────
    if eligibility:
        elig_bullets = _extract_bullet_sentences(str(eligibility), n=3)
        if elig_bullets:
            sentences.append("Eligibility: " + "; ".join(elig_bullets) + ".")

    # ── Contact ───────────────────────────────────────────────────────────
    contact_parts: list[str] = []
    if contact_name:
        contact_parts.append(contact_name)
    if contact_email:
        contact_parts.append(contact_email)
        bullets.append(f"Contact: {contact_email}")
    if contact_phone:
        contact_parts.append(f"Tel: {contact_phone}")

    if contact_parts:
        sentences.append(f"Contact: {', '.join(contact_parts)}.")

    paragraph = " ".join(sentences).strip()

    # Trim to a reasonable prose length (keep under ~300 chars per sentence rule)
    paragraph = _trim_to_word_budget(paragraph, max_words=180)

    return {"paragraph": paragraph, "bullets": bullets}


# ── Helpers ────────────────────────────────────────────────────────────────

def _fmt_date(value) -> str:
    """Format a date value for human display (ISO → readable or passthrough)."""
    s = str(value).strip()
    # ISO 8601 YYYY-MM-DD → "15 March 2025"
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        _MONTHS = ["", "January", "February", "March", "April", "May", "June",
                   "July", "August", "September", "October", "November", "December"]
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12:
            return f"{d} {_MONTHS[mo]} {y}"
    return s


def _fmt_value(value) -> str | None:
    """Format a monetary value dict or raw string for human display."""
    if isinstance(value, dict):
        amount = value.get("amount")
        currency = value.get("currency", "")
        if amount is None:
            return None
        # Format with thousands separator
        if isinstance(amount, float) and not amount.is_integer():
            amt_str = f"{amount:,.2f}"
        else:
            amt_str = f"{int(amount):,}"
        return f"{currency} {amt_str}".strip()
    return str(value) if value else None


def _truncate(s: str, max_chars: int) -> str:
    """Truncate a string to max_chars, appending '…' if cut."""
    s = s.strip()
    if len(s) <= max_chars:
        return s
    return s[:max_chars - 1].rstrip() + "…"


def _extract_first_sentences(text: str, n: int) -> str:
    """Split text into sentences and return the first n joined."""
    # Simple sentence splitter — split on '. ' or '.\n'
    sents = re.split(r"(?<=[.!?])\s+", text.strip())
    selected = [s.strip() for s in sents[:n] if s.strip()]
    return " ".join(selected)


def _extract_bullet_sentences(text: str, n: int) -> list[str]:
    """
    Extract the first n bullet-like items from text.
    Bullet items are lines starting with '-', '•', '*', or numbered '1.'.
    Falls back to first n sentences if no bullets found.
    """
    lines = text.splitlines()
    bullets: list[str] = []
    for line in lines:
        stripped = line.strip()
        if re.match(r"^[-•*•]|^\d+[.)]\s", stripped):
            cleaned = re.sub(r"^[-•*•\d.)]+\s*", "", stripped).strip()
            if cleaned:
                bullets.append(cleaned)
        if len(bullets) >= n:
            break

    if not bullets:
        # Fall back to sentence splitting
        sents = re.split(r"(?<=[.!?])\s+", text.strip())
        bullets = [s.strip() for s in sents[:n] if s.strip()]

    return bullets[:n]


def _trim_to_word_budget(text: str, max_words: int) -> str:
    """
    Trim text to at most max_words words, cutting at the last sentence boundary.
    """
    words = text.split()
    if len(words) <= max_words:
        return text

    truncated = " ".join(words[:max_words])
    # Try to end at a sentence boundary
    last_period = truncated.rfind(".")
    if last_period > len(truncated) * 0.5:
        return truncated[:last_period + 1]
    return truncated + "…"
