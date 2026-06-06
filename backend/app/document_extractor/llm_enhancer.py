"""
LLM-enhanced field extraction using Gemini 2.5 Flash Lite (free tier).

Takes the already-parsed document text and asks the LLM to extract structured
procurement fields. Results are merged with the regex baseline — LLM values
win wherever they are more specific.

Design:
  - Text is chunked to fit the model context window (max 80k chars)
  - Strict JSON output format with fallback on parse failure
  - Completely optional: if the LLM call fails for any reason, the regex
    baseline is used unchanged
  - Uses the existing LLMClient so no new API keys are needed
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict

from app.document_extractor.field_extractor import TenderFields
from app.utils.logger import get_logger

log = get_logger(__name__)

_MAX_TEXT_CHARS = 80_000   # fits comfortably in Gemini Flash 1M context
_MODEL = "google/gemini-2.5-flash-lite"   # free tier on OpenRouter

_SYSTEM = """You are a procurement document analyst specialising in German and EU public tender notices.
Extract structured data from the document text provided.
Respond ONLY with a valid JSON object — no markdown, no explanation, no code fences.
If a field is not present in the document, use null.
All monetary values should include the currency symbol.
All dates should be in DD.MM.YYYY format where possible."""

_PROMPT_TEMPLATE = """Extract the following fields from this tender document text.

FIELDS TO EXTRACT:
- vergabenummer: Reference/tender number (Vergabenummer, Az., Aktenzeichen)
- ted_reference: TED/OJEU reference number if present
- auftraggeber: Contracting authority full name
- vergabestelle: Procurement office (if different from authority)
- titel: Tender title / subject of contract
- vergabeverfahren: Procurement procedure type (e.g. Offenes Verfahren, Verhandlungsverfahren)
- auftragsart: Contract type (Bauauftrag, Lieferauftrag, Dienstleistungsauftrag)
- veroeffentlichungsdatum: Publication date
- abgabefrist: Submission deadline (date + time if available)
- bindefrist: Offer binding period
- cpv_codes: List of CPV codes (8-digit numbers)
- nuts_codes: List of NUTS region codes
- auftragswert: Estimated contract value (number only, no currency)
- waehrung: Currency (EUR/CHF/USD)
- leistungsort: Place of performance
- laufzeit: Contract duration
- ansprechpartner: Contact person name
- email: Contact email address
- telefon: Contact phone number
- fax: Contact fax number
- zuschlagskriterien: List of award criteria (strings)
- eignungskriterien: List of eligibility criteria (strings)
- lose: List of lots with brief descriptions

DOCUMENT TEXT:
{text}

Return JSON only:
{{
  "vergabenummer": null,
  "ted_reference": null,
  "auftraggeber": null,
  "vergabestelle": null,
  "titel": null,
  "vergabeverfahren": null,
  "auftragsart": null,
  "veroeffentlichungsdatum": null,
  "abgabefrist": null,
  "bindefrist": null,
  "cpv_codes": [],
  "nuts_codes": [],
  "auftragswert": null,
  "waehrung": null,
  "leistungsort": null,
  "laufzeit": null,
  "ansprechpartner": null,
  "email": null,
  "telefon": null,
  "fax": null,
  "zuschlagskriterien": [],
  "eignungskriterien": [],
  "lose": []
}}"""


def enhance_with_llm(text: str, regex_fields: TenderFields) -> TenderFields:
    """
    Call Gemini to extract fields, merge with regex baseline.
    Returns updated TenderFields. Falls back to regex_fields on any error.
    """
    if not text.strip():
        return regex_fields

    # Truncate to model-safe length
    chunk = text[:_MAX_TEXT_CHARS]

    try:
        import httpx
        from app.config import settings

        if not settings.openrouter_api_key:
            log.debug("llm_enhancer.no_api_key_skipping")
            return regex_fields

        prompt = _PROMPT_TEMPLATE.format(text=chunk)
        with httpx.Client(timeout=60) as client:
            resp = client.post(
                f"{settings.openrouter_base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.openrouter_api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://vergabepilot.ai",
                    "X-Title": "Vergabepilot Document Extractor",
                },
                json={
                    "model": _MODEL,
                    "messages": [
                        {"role": "system", "content": _SYSTEM},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 2000,
                },
            )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"]
        if not raw:
            return regex_fields
    except Exception as e:  # noqa: BLE001
        log.warning("llm_enhancer.llm_call_failed", error=str(e))
        return regex_fields

    # Parse JSON response
    try:
        # Strip markdown fences if model included them despite instructions
        clean = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()
        data: dict = json.loads(clean)
    except Exception as e:  # noqa: BLE001
        log.warning("llm_enhancer.json_parse_failed", error=str(e), raw=raw[:200])
        return regex_fields

    # Merge: LLM values override regex where they are non-null/non-empty
    merged = TenderFields(**asdict(regex_fields))
    _str_fields = [
        "vergabenummer", "ted_reference", "auftraggeber", "vergabestelle",
        "titel", "vergabeverfahren", "auftragsart", "veroeffentlichungsdatum",
        "abgabefrist", "bindefrist", "auftragswert", "waehrung",
        "leistungsort", "laufzeit", "ansprechpartner", "email", "telefon", "fax",
    ]
    _list_fields = ["cpv_codes", "nuts_codes", "zuschlagskriterien", "eignungskriterien", "lose"]

    for field in _str_fields:
        llm_val = data.get(field)
        if llm_val and isinstance(llm_val, str) and llm_val.strip():
            setattr(merged, field, llm_val.strip())

    for field in _list_fields:
        llm_val = data.get(field)
        if isinstance(llm_val, list) and llm_val:
            # Merge: prefer LLM list if it has more items
            existing = getattr(merged, field) or []
            if len(llm_val) >= len(existing):
                setattr(merged, field, [str(v).strip() for v in llm_val if v])

    log.info(
        "llm_enhancer.done",
        vergabenummer=merged.vergabenummer,
        titel=merged.titel[:40] if merged.titel else None,
        fields_filled=sum(1 for f in _str_fields if getattr(merged, f)),
    )
    return merged
