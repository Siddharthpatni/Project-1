"""
Parse free-text procurement deadlines into datetimes.

The deep extractor captures the submission deadline (`abgabefrist`) as the raw
string found in the documents — German day-first dates like "15.03.2024" or
"15.03.2024, 10:00 Uhr", occasionally ISO "2024-03-15". The public tender
directory needs a real datetime to decide whether a tender is still open and to
sort by soonest-closing, so we parse that string here.

Pure, dependency-free, and total: any unrecognised input returns None (the
directory then treats the deadline as unknown — shown, never marked expired).
"""
from __future__ import annotations

import re
from datetime import datetime

# German day-first DD.MM.YYYY with . / - separators, optional ", HH:MM[:SS]".
_DMY = re.compile(
    r"\b(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2,4})"
    r"(?:[,\sT]+(\d{1,2}):(\d{2})(?::(\d{2}))?)?"
)
# ISO YYYY-MM-DD, optional time.
_ISO = re.compile(
    r"\b(\d{4})-(\d{1,2})-(\d{1,2})"
    r"(?:[,\sT]+(\d{1,2}):(\d{2})(?::(\d{2}))?)?"
)


def parse_deadline(text: str | None) -> datetime | None:
    """Parse a deadline string to a naive datetime, or None if unrecognised.

    When no time component is present the deadline defaults to end-of-day
    (23:59:59) so a tender due "today" stays counted as open until midnight
    rather than expiring at 00:00.
    """
    if not text:
        return None
    raw = text.strip()

    iso = _ISO.search(raw)
    if iso:
        return _build(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)),
                      iso.group(4), iso.group(5), iso.group(6))

    dmy = _DMY.search(raw)
    if dmy:
        year = int(dmy.group(3))
        if year < 100:               # 2-digit year → 2000s
            year += 2000
        return _build(year, int(dmy.group(2)), int(dmy.group(1)),
                      dmy.group(4), dmy.group(5), dmy.group(6))

    return None


def _build(year: int, month: int, day: int, hh, mm, ss) -> datetime | None:
    try:
        if hh is not None:
            return datetime(year, month, day, int(hh), int(mm), int(ss or 0))
        return datetime(year, month, day, 23, 59, 59)
    except ValueError:               # impossible date (e.g. 31.02) → unknown
        return None
