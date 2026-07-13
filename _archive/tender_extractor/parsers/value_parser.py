"""
Value Parser — extract structured monetary amounts from free text.

Algorithm:
  1. Scan raw text for a currency symbol (€ $ £ ₹ ¥) or ISO code (EUR USD …).
  2. Find the nearest numeric amount (handles commas, periods, spaces as separators).
  3. Check for a multiplier word (million, lakh, crore, k …) adjacent to the number.
  4. Compute the canonical integer amount.
  5. Return { "amount": int, "currency": "EUR", "raw": "<original text>" }
     or None if no amount found.
"""
from __future__ import annotations

import re
from typing import TypedDict


class MoneyResult(TypedDict):
    amount: int | float
    currency: str
    raw: str


# Loaded from patterns.yaml in production; defined here for self-contained testability
CURRENCY_SYMBOLS: dict[str, str] = {
    "€": "EUR",
    "$": "USD",
    "£": "GBP",
    "¥": "JPY",
    "₹": "INR",
}

CURRENCY_CODES: list[str] = [
    "EUR", "USD", "GBP", "INR", "CHF", "AED", "SAR", "JPY", "CAD", "AUD",
]

MULTIPLIERS: dict[str, int | float] = {
    "million":  1_000_000,
    "millions": 1_000_000,
    "mn":       1_000_000,
    "m":        1_000_000,
    "billion":  1_000_000_000,
    "billions": 1_000_000_000,
    "bn":       1_000_000_000,
    "lakh":     100_000,
    "lakhs":    100_000,
    "lacs":     100_000,
    "crore":    10_000_000,
    "crores":   10_000_000,
    "cr":       10_000_000,
    "k":        1_000,
}

# Regex pieces (built at module load, not per-call)
_SYM_PAT   = "".join(re.escape(s) for s in CURRENCY_SYMBOLS)
_CODE_PAT  = "|".join(CURRENCY_CODES)
_MULT_PAT  = "|".join(re.escape(k) for k in sorted(MULTIPLIERS, key=len, reverse=True))

# Full pattern: optional currency (symbol or code) · optional whitespace ·
#               number · optional multiplier
_MONEY_RE = re.compile(
    rf"(?:[{_SYM_PAT}]|(?:{_CODE_PAT}))?"      # currency prefix (optional)
    rf"\s*"
    rf"([\d][\d\s,\.']*)"                        # the numeric part (group 1)
    rf"\s*"
    rf"(?:({_MULT_PAT})\b)?"                     # optional multiplier (group 2)
    rf"\s*"
    rf"(?:{_CODE_PAT})?",                         # optional currency suffix
    re.IGNORECASE,
)

# Standalone currency prefix to detect which currency was mentioned
_CURRENCY_RE = re.compile(
    rf"([{_SYM_PAT}])|(?:\b({_CODE_PAT})\b)",
    re.IGNORECASE,
)

# Additional aliases not covered by ISO codes
_ALIAS_MAP: dict[str, str] = {
    "rs":    "INR",
    "rs.":   "INR",
    "inr":   "INR",
    "rupee": "INR",
    "rupees":"INR",
}


def parse_value(raw: str | None) -> MoneyResult | None:
    """
    Extract the first monetary value from raw text.

    Returns None if no recognisable amount is found.
    The returned amount is always numeric (int if whole, float otherwise).
    """
    if not raw or not raw.strip():
        return None

    raw = raw.strip()

    # Detect currency from the raw string
    currency = _detect_currency(raw)

    # Find numeric amount + multiplier
    m = _MONEY_RE.search(raw)
    if not m:
        return None

    num_str = m.group(1)
    mult_str = m.group(2)

    if not num_str or not num_str.strip():
        return None

    amount = _parse_number(num_str)
    if amount is None:
        return None

    if mult_str:
        multiplier = MULTIPLIERS.get(mult_str.lower(), 1)
        amount = amount * multiplier

    # Return int when amount is a whole number
    if isinstance(amount, float) and amount.is_integer():
        amount = int(amount)

    if not currency:
        return None  # amount without currency is ambiguous — skip

    return {"amount": amount, "currency": currency, "raw": raw}


# ── Helpers ────────────────────────────────────────────────────────────────

def _detect_currency(text: str) -> str | None:
    """
    Scan text for a currency symbol or ISO code, then an alias.
    Returns the ISO 4217 code or None.
    """
    for sym, code in CURRENCY_SYMBOLS.items():
        if sym in text:
            return code

    upper = text.upper()
    for code in CURRENCY_CODES:
        # word-boundary check: avoid matching "CAD" inside "ARCADE"
        if re.search(rf"\b{code}\b", upper):
            return code

    lower = text.lower()
    for alias, code in _ALIAS_MAP.items():
        if re.search(rf"\b{re.escape(alias)}\b", lower):
            return code

    return None


def _parse_number(s: str) -> float | None:
    """
    Parse a number string that may use ',' as thousands separator or '.' as decimal.
    Handles: "1,500,000"  "1.500.000"  "1 500 000"  "1.5"  "1,5"
    """
    s = s.strip().rstrip(".,")

    # Remove spaces (thousands grouping)
    s = re.sub(r"\s", "", s)

    # Determine whether '.' or ',' is the decimal separator:
    # If there is exactly one '.' and it splits the string into ≤3 trailing digits → decimal
    # If there are multiple '.'  → thousands separators, remove them
    dots   = s.count(".")
    commas = s.count(",")

    if dots == 0 and commas == 0:
        try:
            return float(s)
        except ValueError:
            return None

    if dots == 0 and commas >= 1:
        if commas > 1:
            # Multiple commas: always thousands separators → "1,500,000" → "1500000"
            s = s.replace(",", "")
        else:
            # Single comma: thousands if 3 trailing digits, else decimal
            parts = s.split(",")
            if len(parts[1]) == 3:
                s = s.replace(",", "")
            else:
                s = s.replace(",", ".")
    elif commas == 0 and dots >= 1:
        if dots > 1:
            # Multiple dots: thousands separators → "1.500.000" → "1500000"
            s = s.replace(".", "")
        else:
            # Single dot: thousands if 3 trailing digits, else decimal
            parts = s.split(".")
            if len(parts[1]) == 3:
                s = s.replace(".", "")
            # else decimal — leave as-is
    else:
        # Mixed: determine which is the decimal separator by position
        dot_idx   = s.index(".")
        comma_idx = s.index(",")
        if dot_idx < comma_idx:
            # "1.500.000,00" — dot = thousands, comma = decimal
            s = s.replace(".", "").replace(",", ".")
        else:
            # "1,500,000.00" — comma = thousands, dot = decimal
            s = s.replace(",", "")

    try:
        return float(s)
    except ValueError:
        return None
