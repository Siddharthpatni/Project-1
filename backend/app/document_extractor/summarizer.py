"""
Deterministic, offline summary generator for TenderFields.

Produces:
  - zusammenfassung: a 2-3 sentence executive summary paragraph
  - kernpunkte: 4-8 concise bullet points

No LLM, no API, no external calls — purely template-based from the
already-extracted structured fields.
"""
from __future__ import annotations

from app.document_extractor.field_extractor import TenderFields


def generate_summary(fields: TenderFields) -> TenderFields:
    """Fill fields.zusammenfassung and fields.kernpunkte from structured data."""
    fields.zusammenfassung = _build_paragraph(fields)
    fields.kernpunkte = _build_bullets(fields)
    return fields


# ---------------------------------------------------------------------------
# Paragraph builder
# ---------------------------------------------------------------------------

def _build_paragraph(f: TenderFields) -> str:
    parts: list[str] = []

    # Sentence 1 — what is being procured and by whom
    auftraggeber = f.auftraggeber or f.vergabestelle
    titel = f.titel
    auftragsart = f.auftragsart

    if titel and auftraggeber:
        art_str = f" ({auftragsart})" if auftragsart else ""
        parts.append(f"{auftraggeber} schreibt {titel}{art_str} aus.")
    elif titel:
        art_str = f" ({auftragsart})" if auftragsart else ""
        parts.append(f"Ausgeschrieben wird: {titel}{art_str}.")
    elif auftraggeber:
        parts.append(f"{auftraggeber} führt ein Vergabeverfahren durch.")
    else:
        parts.append("Es handelt sich um ein öffentliches Vergabeverfahren.")

    # Sentence 2 — procedure + value
    proc_parts: list[str] = []
    if f.vergabeverfahren:
        proc_parts.append(f"Verfahrensart: {f.vergabeverfahren}")
    if f.auftragswert:
        val = f.auftragswert
        cur = f.waehrung or "EUR"
        proc_parts.append(f"Auftragswert: {val} {cur}")
    if proc_parts:
        parts.append(". ".join(proc_parts) + ".")

    # Sentence 3 — deadline + location
    deadline_parts: list[str] = []
    if f.abgabefrist:
        deadline_parts.append(f"Angebotsfrist: {f.abgabefrist}")
    if f.leistungsort:
        deadline_parts.append(f"Leistungsort: {f.leistungsort}")
    if f.laufzeit:
        deadline_parts.append(f"Vertragslaufzeit: {f.laufzeit}")
    if deadline_parts:
        parts.append(". ".join(deadline_parts) + ".")

    return " ".join(parts) if parts else "Keine ausreichenden Informationen für eine Zusammenfassung vorhanden."


# ---------------------------------------------------------------------------
# Bullet points builder
# ---------------------------------------------------------------------------

def _build_bullets(f: TenderFields) -> list[str]:
    bullets: list[str] = []

    # Reference number
    if f.vergabenummer:
        bullets.append(f"Vergabenummer: {f.vergabenummer}")

    # Contracting authority
    ag = f.auftraggeber or f.vergabestelle
    if ag:
        bullets.append(f"Auftraggeber: {ag}")

    # Procedure type
    if f.vergabeverfahren:
        bullets.append(f"Vergabeverfahren: {f.vergabeverfahren}")

    # Contract type
    if f.auftragsart:
        bullets.append(f"Auftragsart: {f.auftragsart}")

    # Contract value
    if f.auftragswert:
        cur = f.waehrung or "EUR"
        bullets.append(f"Geschätzter Auftragswert: {f.auftragswert} {cur}")

    # Submission deadline
    if f.abgabefrist:
        bullets.append(f"Einreichungsfrist: {f.abgabefrist}")

    # Binding period
    if f.bindefrist:
        bullets.append(f"Bindefrist: {f.bindefrist}")

    # Publication date
    if f.veroeffentlichungsdatum:
        bullets.append(f"Veröffentlicht am: {f.veroeffentlichungsdatum}")

    # Place of performance
    if f.leistungsort:
        bullets.append(f"Leistungsort: {f.leistungsort}")

    # Contract duration
    if f.laufzeit:
        bullets.append(f"Vertragslaufzeit: {f.laufzeit}")

    # CPV codes
    if f.cpv_codes:
        codes = ", ".join(f.cpv_codes[:5])
        bullets.append(f"CPV-Code(s): {codes}")

    # NUTS codes
    if f.nuts_codes:
        bullets.append(f"NUTS-Region: {', '.join(f.nuts_codes[:3])}")

    # Number of lots
    if f.lose:
        bullets.append(f"Anzahl Lose: {len(f.lose)}")

    # Award criteria (first two)
    if f.zuschlagskriterien:
        crit_preview = "; ".join(f.zuschlagskriterien[:2])
        bullets.append(f"Zuschlagskriterien: {crit_preview}")

    # Contact email
    if f.email:
        bullets.append(f"Kontakt: {f.email}")
    elif f.ansprechpartner:
        bullets.append(f"Ansprechpartner: {f.ansprechpartner}")

    # TED reference
    if f.ted_reference:
        bullets.append(f"TED-Referenz: {f.ted_reference}")

    return bullets
