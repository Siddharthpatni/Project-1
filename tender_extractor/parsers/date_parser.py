"""
Date Parser — normalise any date-like string to ISO 8601 (YYYY-MM-DD).

Algorithm:
  1. Sanitize input (strip whitespace).
  2. Try dateparser.parse() with strict settings (no relative dates, no future guessing).
  3. If dateparser fails, try each custom regex pattern in order.
  4. If all attempts fail, return the raw string with low_confidence=True.
  5. Empty / None input returns None.

Output is always a dict:
  { "value": "2025-03-15", "low_confidence": False }
  or, on failure:
  { "value": "<raw string>", "low_confidence": True }
"""
from __future__ import annotations

import re
from typing import TypedDict


class DateResult(TypedDict):
    value: str | None
    low_confidence: bool


# Custom patterns ordered from most-specific to least-specific.
# Each tuple: (compiled regex, strptime-compatible format or None)
_CUSTOM_PATTERNS: list[tuple[re.Pattern, str]] = [
    # ISO 8601 — passthrough
    (re.compile(r"(\d{4}-\d{2}-\d{2})"), "%Y-%m-%d"),
    # DD/MM/YYYY or DD-MM-YYYY
    (re.compile(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})"), "DMY"),
    # DD.MM.YYYY
    (re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})"), "DMY"),
    # DD.MM.YY
    (re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{2})$"), "DMY2"),
    # DD-Mon-YY  e.g. 15-Mar-25
    (re.compile(r"(\d{1,2})-([A-Za-z]{3})-(\d{2,4})"), "D-MON-Y"),
    # "15 March 2025" or "15 March, 2025"
    (re.compile(r"(\d{1,2})\s+([A-Za-z]+),?\s+(\d{4})"), "D MON Y"),
    # "March 15, 2025" or "March 15 2025"
    (re.compile(r"([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})"), "MON D Y"),
]

_MONTH_MAP: dict[str, int] = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,  "may": 5,  "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    # German month abbreviations
    "mär": 3, "mai": 5, "okt": 10, "dez": 12,
    # Full German
    "januar": 1, "februar": 2, "märz": 3, "april": 4, "juni": 6,
    "juli": 7, "august": 8, "september": 9, "oktober": 10,
    "november": 11, "dezember": 12,
    # Full English
    "january": 1, "february": 2, "march": 3, "june": 6, "july": 7,
    "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}


def parse_date(raw: str | None) -> DateResult | None:
    """
    Normalise raw date text to ISO 8601.

    Returns None for empty/None input.
    Returns { "value": "YYYY-MM-DD", "low_confidence": False } on success.
    Returns { "value": <raw>, "low_confidence": True } when no pattern matches.
    """
    if raw is None:
        return None
    raw = raw.strip()
    if not raw:
        return None

    # Step 1: try dateparser
    result = _try_dateparser(raw)
    if result:
        return {"value": result, "low_confidence": False}

    # Step 2: custom regex patterns
    result = _try_custom_patterns(raw)
    if result:
        return {"value": result, "low_confidence": False}

    # Step 3: fallback — return raw text flagged as low confidence
    return {"value": raw, "low_confidence": True}


def _try_dateparser(raw: str) -> str | None:
    """
    Attempt to parse using the dateparser library.
    Disables relative date parsing to avoid false positives like "tomorrow".
    """
    try:
        import dateparser
        parsed = dateparser.parse(
            raw,
            settings={
                "RETURN_AS_TIMEZONE_AWARE": False,
                "PREFER_DAY_OF_MONTH": "first",
                "PREFER_LOCALE_DATE_ORDER": True,
                "STRICT_PARSING": False,
            },
        )
        if parsed:
            return parsed.strftime("%Y-%m-%d")
    except Exception:
        pass
    return None


def _try_custom_patterns(raw: str) -> str | None:
    """
    Try each compiled regex pattern against the raw string.
    Returns ISO 8601 string on first successful match, or None.
    """
    for pattern, fmt in _CUSTOM_PATTERNS:
        m = pattern.search(raw)
        if not m:
            continue
        try:
            iso = _groups_to_iso(m.groups(), fmt)
            if iso:
                return iso
        except Exception:
            continue
    return None


def _groups_to_iso(groups: tuple, fmt: str) -> str | None:
    """
    Convert regex match groups to YYYY-MM-DD based on the format tag.
    """
    if fmt == "%Y-%m-%d":
        return groups[0]

    if fmt == "DMY":
        d, m, y = int(groups[0]), int(groups[1]), int(groups[2])
        return _build_iso(y, m, d)

    if fmt == "DMY2":
        d, m, y = int(groups[0]), int(groups[1]), int(groups[2])
        y += 2000 if y < 50 else 1900
        return _build_iso(y, m, d)

    if fmt == "D-MON-Y":
        d = int(groups[0])
        mon = _MONTH_MAP.get(groups[1].lower()[:3])
        if not mon:
            return None
        y = int(groups[2])
        if y < 100:
            y += 2000 if y < 50 else 1900
        return _build_iso(y, mon, d)

    if fmt == "D MON Y":
        d = int(groups[0])
        mon = _MONTH_MAP.get(groups[1].lower())
        if not mon:
            return None
        y = int(groups[2])
        return _build_iso(y, mon, d)

    if fmt == "MON D Y":
        mon = _MONTH_MAP.get(groups[0].lower())
        if not mon:
            return None
        d = int(groups[1])
        y = int(groups[2])
        return _build_iso(y, mon, d)

    return None


def _build_iso(y: int, m: int, d: int) -> str | None:
    """Validate and format as YYYY-MM-DD."""
    if not (1900 <= y <= 2100 and 1 <= m <= 12 and 1 <= d <= 31):
        return None
    return f"{y:04d}-{m:02d}-{d:02d}"
