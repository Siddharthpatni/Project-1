"""
Field Parser — proximity-search extraction of structured fields from document text.

Algorithm (per field):
  1. Load label variants and value_regex from patterns.yaml (no strings hardcoded here).
  2. Walk all lines in the document. For each line, check case-insensitive substring
     match against every label variant.
  3. If label found on same line: check text after ":" or "-" for a value.
  4. If no same-line value: scan the next `search_window` lines for a candidate.
  5. Validate candidate with the field's value_regex.
  6. Assign confidence:
       1.0 = label matched + value passed validation regex
       0.8 = label matched + value found, regex skipped or not defined
       0.5 = standalone regex match, no label found
       0.2 = fallback heuristic guess
       0.0 = not found
  7. Also run standalone regex scan across the full text for email/CPV/phone/ID fields.
  8. Return ExtractedField with value, confidence, source_page, source_line.

Two additional utilities:
  - extract_section_body(pages, section_keywords, max_lines): locate a section header
    and return up to max_lines of body text as a joined string.
  - extract_tender_type(full_text, tender_types_cfg): scan for type keywords and
    return the matched type + confidence.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml

from tender_extractor.models import DocumentContent, ExtractedField, PageContent

log = logging.getLogger(__name__)

# Path to the single patterns file — resolved relative to this file's location
_PATTERNS_PATH = Path(__file__).parent.parent / "config" / "patterns.yaml"


def _load_config() -> dict:
    """Load and cache patterns.yaml. Returns the parsed dict."""
    if not hasattr(_load_config, "_cache"):
        with open(_PATTERNS_PATH, encoding="utf-8") as fh:
            _load_config._cache = yaml.safe_load(fh)  # type: ignore[attr-defined]
    return _load_config._cache  # type: ignore[attr-defined]


def extract_all_fields(doc: DocumentContent) -> dict[str, ExtractedField]:
    """
    Run extraction for every field defined in patterns.yaml against the document.
    Returns a dict mapping field_name → ExtractedField.
    """
    cfg = _load_config()
    field_defs: dict = cfg.get("fields", {})
    standalone_pats: dict = cfg.get("standalone_patterns", {})
    settings: dict = cfg.get("settings", {})
    global_window: int = int(settings.get("search_window", 5))

    # Build flat line list with page attribution
    # Each entry: (page_num, line_index_on_page, line_text)
    tagged_lines: list[tuple[int, int, str]] = []
    for page in doc.pages:
        for i, line in enumerate(page.lines):
            tagged_lines.append((page.page_num, i, line))

    results: dict[str, ExtractedField] = {}

    for field_name, field_cfg in field_defs.items():
        # Section-body fields use a different extraction path
        if "section_keywords" in field_cfg and "labels" not in field_cfg:
            section_kws = field_cfg.get("section_keywords", [])
            max_lines = int(field_cfg.get("max_lines", settings.get("max_section_lines", 40)))
            body = extract_section_body(doc.pages, section_kws, max_lines)
            if body:
                results[field_name] = ExtractedField(
                    value=body,
                    confidence=0.8,
                    low_confidence=False,
                )
            else:
                results[field_name] = ExtractedField(value=None, confidence=0.0, low_confidence=False)
            continue

        labels: list[str] = field_cfg.get("labels", [])
        value_regex: str | None = field_cfg.get("value_regex")
        window: int = int(field_cfg.get("search_window", global_window))
        is_list: bool = bool(field_cfg.get("is_list", False))

        ef = _extract_field(
            field_name=field_name,
            labels=labels,
            value_regex=value_regex,
            tagged_lines=tagged_lines,
            full_text=doc.full_text,
            search_window=window,
            standalone_pats=standalone_pats,
            is_list=is_list,
        )
        results[field_name] = ef

    return results


def _extract_field(
    field_name: str,
    labels: list[str],
    value_regex: str | None,
    tagged_lines: list[tuple[int, int, str]],
    full_text: str,
    search_window: int,
    standalone_pats: dict[str, str],
    is_list: bool,
) -> ExtractedField:
    """
    Core proximity-search algorithm for a single field.
    Returns an ExtractedField (value=None, confidence=0.0 if nothing found).
    """
    norm_labels = [lb.lower().strip() for lb in labels]
    compiled_val_re = re.compile(value_regex, re.IGNORECASE) if value_regex else None

    best: ExtractedField = ExtractedField(value=None, confidence=0.0)

    for line_idx, (page_num, line_pos, line_text) in enumerate(tagged_lines):
        norm_line = line_text.lower()

        # Check if any label variant appears in this line
        matched_label = None
        for norm_lb in norm_labels:
            if norm_lb in norm_line:
                matched_label = norm_lb
                break

        if matched_label is None:
            continue

        # Label found — try to extract value from same line (after ":", "-", or label text)
        candidate, conf = _extract_same_line(line_text, matched_label, compiled_val_re)

        # If same-line extraction failed, look at the next `search_window` lines
        if candidate is None:
            candidate, conf, src_pg, src_ln = _extract_next_lines(
                tagged_lines, line_idx, search_window, compiled_val_re
            )
            if candidate:
                ef = ExtractedField(
                    value=candidate,
                    confidence=conf,
                    source_page=src_pg,
                    source_line=src_ln,
                    raw_text=candidate,
                    low_confidence=conf < 0.5,
                )
                if ef.confidence > best.confidence:
                    best = ef
            continue

        if candidate:
            ef = ExtractedField(
                value=candidate,
                confidence=conf,
                source_page=page_num,
                source_line=line_pos,
                raw_text=line_text,
                low_confidence=conf < 0.5,
            )
            if ef.confidence > best.confidence:
                best = ef

    # If still not found, try standalone regex scan
    if best.value is None and compiled_val_re:
        m = compiled_val_re.search(full_text)
        if m:
            val = m.group(0).strip()
            if val:
                best = ExtractedField(
                    value=val,
                    confidence=0.5,
                    low_confidence=False,
                )

    # CPV codes: collect all matches as a list
    if is_list and compiled_val_re:
        all_matches = [m.group(0).strip() for m in compiled_val_re.finditer(full_text) if m.group(0).strip()]
        if all_matches:
            unique = list(dict.fromkeys(all_matches))
            best = ExtractedField(
                value=unique,
                confidence=0.5 if best.confidence == 0.0 else best.confidence,
                low_confidence=False,
            )

    return best


def _extract_same_line(
    line: str,
    label: str,
    val_re: re.Pattern | None,
) -> tuple[str | None, float]:
    """
    Look for a value on the same line as the label.
    Strategy: find the label position, then check text after ':', '-', or
    after the label itself.
    Returns (value, confidence) or (None, 0.0).
    """
    # Find where the label ends in the line
    idx = line.lower().find(label)
    if idx == -1:
        return None, 0.0

    after = line[idx + len(label):].strip()

    # Strip leading separator characters
    after = re.sub(r"^[\s:;\-–—\|]+", "", after).strip()

    if not after or len(after) < 2:
        return None, 0.0

    # Validate with field regex if available
    if val_re:
        m = val_re.match(after)
        if m:
            return m.group(0).strip(), 1.0
        # Regex defined but didn't match — very low confidence (heuristic fallback)
        return after[:200], 0.2

    # No regex defined — label matched, value present: medium confidence
    return after[:200], 0.8


def _extract_next_lines(
    tagged_lines: list[tuple[int, int, str]],
    label_idx: int,
    window: int,
    val_re: re.Pattern | None,
) -> tuple[str | None, float, int | None, int | None]:
    """
    Scan the next `window` lines after the label line for a candidate value.
    Stops at the next label-like line (short line ending with ':', or ALL CAPS).
    Returns (value, confidence, page_num, line_pos).
    """
    end = min(label_idx + window + 1, len(tagged_lines))
    for i in range(label_idx + 1, end):
        page_num, line_pos, line_text = tagged_lines[i]
        text = line_text.strip()
        if not text or len(text) < 2:
            continue

        # Stop if this looks like a new section header / label
        if _is_label_line(text):
            break

        if val_re:
            m = val_re.search(text)
            if m:
                return m.group(0).strip(), 1.0, page_num, line_pos
            # Text exists but regex didn't match — heuristic fallback
            return text[:200], 0.2, page_num, line_pos

        return text[:200], 0.8, page_num, line_pos

    return None, 0.0, None, None


def _is_label_line(text: str) -> bool:
    """Return True if the line looks like a section header or label (not a value)."""
    if text.endswith(":") and len(text) < 60:
        return True
    words = re.sub(r"[^a-zA-Z\s]", "", text).split()
    if len(words) >= 2 and all(w.isupper() for w in words if len(w) > 1):
        return True
    return False


def extract_section_body(
    pages: list[PageContent],
    section_keywords: list[str],
    max_lines: int,
) -> str | None:
    """
    Find a section header matching any of the keywords, then collect up to
    max_lines of body text until the next section header is detected.

    Returns the joined body text, or None if the section was not found.
    """
    norm_kws = [kw.lower().strip() for kw in section_keywords]
    collecting = False
    body_lines: list[str] = []

    for page in pages:
        for line in page.lines:
            norm = line.lower().strip()

            if not collecting:
                # Detect section header matching any keyword
                if any(kw in norm for kw in norm_kws):
                    collecting = True
                continue

            # Already collecting — stop at next section header
            if _is_label_line(line) and not any(kw in norm for kw in norm_kws):
                if len(body_lines) > 2:
                    break  # good enough — new section started
            body_lines.append(line.strip())
            if len(body_lines) >= max_lines:
                break

        if body_lines and len(body_lines) >= max_lines:
            break

    if not body_lines:
        return None

    return "\n".join(body_lines)


def extract_tender_type(
    full_text: str,
    tender_types_cfg: dict[str, dict],
) -> ExtractedField:
    """
    Scan full_text for tender-type keywords from patterns.yaml.
    Each type has a list of keyword phrases; the first match wins.

    Confidence:
      0.9 = multi-word keyword found (e.g. "open tender")
      0.7 = single-word keyword found (e.g. "rfp")
    Returns ExtractedField with value=type_name or value=None.
    """
    norm_text = full_text.lower()

    for type_name, type_cfg in tender_types_cfg.items():
        keywords: list[str] = type_cfg.get("keywords", [])
        for kw in keywords:
            if kw.lower() in norm_text:
                word_count = len(kw.split())
                conf = 0.9 if word_count >= 2 else 0.7
                display = type_name.upper() if len(type_name) <= 4 else type_name.capitalize()
                return ExtractedField(value=display, confidence=conf, low_confidence=False)

    return ExtractedField(value=None, confidence=0.0, low_confidence=False)
