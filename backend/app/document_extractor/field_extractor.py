"""
Regex + heuristic extraction of structured procurement fields from raw text.

No LLM, no API calls. All patterns are hand-crafted for German/EU procurement
documents (TED, DTVP, NetServer, Cosinex, etc.).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TenderFields:
    # Reference numbers
    vergabenummer: Optional[str] = None
    aktenzeichen: Optional[str] = None
    ted_reference: Optional[str] = None

    # Parties
    auftraggeber: Optional[str] = None
    vergabestelle: Optional[str] = None

    # Tender description
    titel: Optional[str] = None
    leistungsbeschreibung: Optional[str] = None  # brief description of services
    vergabeverfahren: Optional[str] = None
    auftragsart: Optional[str] = None

    # Dates
    veroeffentlichungsdatum: Optional[str] = None
    abgabefrist: Optional[str] = None
    bindefrist: Optional[str] = None

    # Classification
    cpv_codes: list[str] = field(default_factory=list)
    nuts_codes: list[str] = field(default_factory=list)

    # Value
    auftragswert: Optional[str] = None
    waehrung: Optional[str] = None

    # Location & duration
    leistungsort: Optional[str] = None
    laufzeit: Optional[str] = None

    # Contact
    ansprechpartner: Optional[str] = None
    email: Optional[str] = None
    telefon: Optional[str] = None
    fax: Optional[str] = None
    website: Optional[str] = None

    # Award criteria
    zuschlagskriterien: list[str] = field(default_factory=list)
    eignungskriterien: list[str] = field(default_factory=list)

    # Lots
    lose: list[str] = field(default_factory=list)

    # Raw sentences that couldn't be classified
    additional_notes: list[str] = field(default_factory=list)

    # Generated summary (filled by llm_enhancer)
    zusammenfassung: Optional[str] = None        # executive summary paragraph
    kernpunkte: list[str] = field(default_factory=list)  # key bullet points


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _first(text: str, patterns: list[str], flags: int = re.IGNORECASE | re.MULTILINE) -> Optional[str]:
    for pat in patterns:
        m = re.search(pat, text, flags)
        if m:
            return m.group(1).strip()
    return None


def _all(text: str, patterns: list[str], flags: int = re.IGNORECASE) -> list[str]:
    found: list[str] = []
    for pat in patterns:
        for m in re.finditer(pat, text, flags):
            val = m.group(1).strip() if m.lastindex else m.group(0).strip()
            if val and val not in found:
                found.append(val)
    return found


def _clean(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"[|»«]+", "", s).strip()
    return s if s else None


# ---------------------------------------------------------------------------
# Individual field extractors
# ---------------------------------------------------------------------------

def _extract_vergabenummer(text: str) -> Optional[str]:
    return _clean(_first(text, [
        r"Vergabe(?:nr\.?|nummer|kennnummer)\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-/_. ]{2,40})",
        r"Ausschreibungs(?:nr\.?|nummer)\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-/_. ]{2,40})",
        r"Bekanntmachungs(?:nr\.?|nummer|kennnummer)\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-/_. ]{2,40})",
        r"Referenz(?:nr\.?|nummer)\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-/_. ]{2,40})",
        r"Auftrag(?:snummer|snr\.?)\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-/_. ]{2,40})",
        r"\bVN\s*[:\-]\s*([A-Z0-9][A-Z0-9\-/_. ]{2,40})",
    ]))


def _extract_ted_reference(text: str) -> Optional[str]:
    return _clean(_first(text, [
        r"TED[:\s-]*(\d{4}/S[-\s]\d{3}[-\s]\d{6,})",
        r"Supplement(?:ary)?\s+(?:to\s+)?(?:the\s+)?Official Journal[,\s]*(\d{4}/S[^\s,]+)",
        r"S\s+(\d{3}[-–]\d{6,})",
    ]))


def _extract_auftraggeber(text: str) -> Optional[str]:
    return _clean(_first(text, [
        r"(?:Öffentlicher\s+)?Auftraggeber\s*[:\n]\s*(.+?)(?:\n|Anschrift|Postanschrift|Kontaktstelle|Tel\.?|Fax|$)",
        r"Vergabestelle\s*[:\n]\s*(.+?)(?:\n|Anschrift|Kontaktstelle|Tel\.?|Fax|$)",
        r"Beschaffungsstelle\s*[:\n]\s*(.+?)(?:\n|$)",
        r"Auftraggeber\s*:\s*\n?\s*([A-ZÄÖÜ][^\n]{5,80})",
    ]))


def _extract_leistungsbeschreibung(text: str) -> Optional[str]:
    val = _clean(_first(text, [
        r"[Ll]eistungsbeschreibung\s*[:\n]\s*(.{20,500}?)(?:\n\n|\n[A-Z0-9]|$)",
        r"[Bb]eschreibung\s+(?:der\s+)?[Ll]eistung\s*[:\n]\s*(.{20,500}?)(?:\n\n|\n[A-Z0-9]|$)",
        r"[Gg]egenstand\s+(?:der|des)\s+(?:Auftrags?|Leistung)\s*[:\n]\s*(.{20,500}?)(?:\n\n|\n[A-Z0-9]|$)",
        r"[Kk]urzbeschreibung\s*[:\n]\s*(.{20,500}?)(?:\n\n|\n[A-Z0-9]|$)",
        r"[Ii]nformation\s+(?:über\s+)?(?:den\s+)?Auftragsgegenstand\s*[:\n]\s*(.{20,500}?)(?:\n\n|$)",
    ], re.IGNORECASE | re.DOTALL))
    if val:
        # Collapse whitespace and cap to 400 chars
        val = re.sub(r"\s+", " ", val).strip()[:400]
    return val


def _extract_titel(text: str) -> Optional[str]:
    return _clean(_first(text, [
        r"(?:Auftrags|Ausschreibungs|Vergabe)gegenstand\s*[:\n]\s*(.+?)(?:\n\n|\n[A-Z]|$)",
        r"Auftragsbezeichnung\s*[:\n]\s*(.+?)(?:\n)",
        r"Bezeichnung\s+des\s+Auftrags\s*[:\n]\s*(.+?)(?:\n)",
        r"Gegenstand\s+(?:der|des)\s+(?:Ausschreibung|Vergabe|Auftrags)\s*[:\n]\s*(.+?)(?:\n)",
        r"Kurzbezeichnung\s*[:\n]\s*(.+?)(?:\n)",
        r"Titel\s*[:\n]\s*(.{10,150}?)(?:\n|$)",
    ]))


def _extract_vergabeverfahren(text: str) -> Optional[str]:
    val = _clean(_first(text, [
        r"(?:Art\s+des\s+)?Vergabeverfahren\s*[:\n]\s*(.+?)(?:\n)",
        r"Verfahrensart\s*[:\n]\s*(.+?)(?:\n)",
        r"Auftragsart\s*[:\n]\s*(.+?)(?:\n)",
    ]))
    if val:
        return val
    # Keyword scan for procedure type
    procedures = [
        ("Offenes Verfahren", r"offene[sn]?\s+(?:Verfahren|Ausschreibung)"),
        ("Nichtoffenes Verfahren", r"nichtoffene[sn]?\s+Verfahren"),
        ("Verhandlungsverfahren", r"Verhandlungsverfahren"),
        ("Wettbewerblicher Dialog", r"[Ww]ettbewerbliche[rn]?\s+Dialog"),
        ("Innovationspartnerschaft", r"Innovationspartnerschaft"),
        ("Beschleunigtes Verfahren", r"beschleunigtes?\s+Verfahren"),
        ("Freihändige Vergabe", r"[Ff]reihändige\s+Vergabe"),
        ("Beschränkte Ausschreibung", r"[Bb]eschränkte\s+Ausschreibung"),
        ("Öffentliche Ausschreibung", r"[Öö]ffentliche\s+Ausschreibung"),
    ]
    for label, pat in procedures:
        if re.search(pat, text, re.IGNORECASE):
            return label
    return None


def _extract_auftragsart(text: str) -> Optional[str]:
    kinds = [
        ("Bauauftrag", r"Bauauftrag|Bauleistung"),
        ("Lieferauftrag", r"Lieferauftrag|Lieferung"),
        ("Dienstleistungsauftrag", r"Dienstleistungsauftrag|Dienstleistung"),
    ]
    for label, pat in kinds:
        if re.search(pat, text, re.IGNORECASE):
            return label
    return None


def _extract_dates(text: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    # publication date
    pub = _clean(_first(text, [
        r"[Vv]er[öo]ffentlichungsdatum\s*[:\n]\s*(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4})",
        r"[Dd]atum\s+der\s+[Vv]er[öo]ffentlichung\s*[:\n]\s*(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4})",
        r"Bekanntmachungsdatum\s*[:\n]\s*(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4})",
    ]))
    # submission deadline
    deadline = _clean(_first(text, [
        r"(?:Angebotsfrist|Abgabefrist|Einreichungsfrist|[Ss]chlusstermin|Bewerbungsfrist)\s*[:\n]\s*(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4}(?:[,\s]+\d{2}:\d{2}(?::\d{2})?(?:\s*Uhr)?)?)",
        r"[Ff]rist\s+(?:für\s+)?(?:die\s+)?(?:[Ee]inreichung|[Ee]ingang|[Aa]ngebote?)\s*[:\n]\s*(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4})",
        r"[Ee]ingangsfrist\s*[:\n]\s*(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4})",
        r"[Bb]is\s+(?:zum|spätestens)\s+(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4})",
    ]))
    # binding period (Bindefrist)
    binding = _clean(_first(text, [
        r"[Bb]indefrist\s*[:\n]\s*(.+?)(?:\n|$)",
        r"[Zz]uschlagsfrist\s*[:\n]\s*(.+?)(?:\n|$)",
        r"[Bb]indung(?:s(?:frist|dauer))?\s*[:\n]\s*(.+?)(?:\n|$)",
    ]))
    return pub, deadline, binding


def _extract_cpv(text: str) -> list[str]:
    found: list[str] = []
    for m in re.finditer(r"\b(\d{8}(?:-\d)?)\b", text):
        code = m.group(1)
        if code not in found:
            found.append(code)
    return found[:20]


def _extract_nuts(text: str) -> list[str]:
    found: list[str] = []
    for m in re.finditer(r"\bNUTS[:\s-]*([A-Z]{2}\d{0,3}[A-Z0-9]*)\b", text, re.IGNORECASE):
        code = m.group(1).upper()
        if code not in found:
            found.append(code)
    return found


def _extract_value(text: str) -> tuple[Optional[str], Optional[str]]:
    patterns = [
        r"(?:Gesamtwert|Auftragswert|Schätzwert|Auftragswert|Gesamtvolumen|Auftragsvolumen)\s*[:\n]?\s*(?:(?:ca|circa|rund|etwa)\.?\s*)?(?:EUR|€|CHF|USD)?\s*([\d.,]+(?:\s*(?:Mio\.?|T(?:aus(?:end)?)?\.?|k))?)\s*(?:EUR|€|CHF|USD)?",
        r"(?:EUR|€)\s*([\d.,]+(?:\s*(?:Mio\.?|Tsd\.?))?)",
        r"([\d.,]+(?:\s*(?:Mio\.?|Tsd\.?))?\s*(?:EUR|€|CHF|USD))",
    ]
    val_str = _clean(_first(text, patterns, re.IGNORECASE))
    # currency
    cur = None
    if val_str:
        if "EUR" in text.upper() or "€" in text:
            cur = "EUR"
        elif "CHF" in text.upper():
            cur = "CHF"
    return val_str, cur


def _extract_leistungsort(text: str) -> Optional[str]:
    return _clean(_first(text, [
        r"[Ee]rfüllungsort\s*[:\n]\s*(.+?)(?:\n|$)",
        r"[Ll]eistungsort\s*[:\n]\s*(.+?)(?:\n|$)",
        r"[Aa]usführungsort\s*[:\n]\s*(.+?)(?:\n|$)",
        r"NUTS[:\s-]*[A-Z]{2}\d*[A-Z0-9]*\s+(.+?)(?:\n|$)",
        r"Ort\s+der\s+(?:Ausführung|Lieferung|Leistung)\s*[:\n]\s*(.+?)(?:\n|$)",
    ]))


def _extract_laufzeit(text: str) -> Optional[str]:
    return _clean(_first(text, [
        r"[Ll]aufzeit\s+(?:des\s+Auftrags|der\s+(?:Rahmenvereinbarung|Leistung))?\s*[:\n]\s*(.+?)(?:\n|$)",
        r"[Vv]ertragsdauer\s*[:\n]\s*(.+?)(?:\n|$)",
        r"[Ll]eistungszeitraum\s*[:\n]\s*(.+?)(?:\n|$)",
        r"[Bb]eginn\s*[:\n]\s*\d{1,2}[./]\d{1,2}[./]\d{4}\s*.*[Ee]nde\s*[:\n]?\s*(\d{1,2}[./]\d{1,2}[./]\d{4})",
        r"(?:Laufzeit|Ausführungszeitraum)\s*[:\n]\s*(\d+\s*(?:Monate?|Wochen?|Jahre?|Tage?))",
    ]))


def _extract_contact(text: str) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    person = _clean(_first(text, [
        r"[Aa]nsprechpartner\s*[:\n]\s*(.+?)(?:\n|Tel|Fax|E-Mail|$)",
        r"[Kk]ontaktperson\s*[:\n]\s*(.+?)(?:\n|Tel|Fax|E-Mail|$)",
        r"[Bb]earbeiter(?:in)?\s*[:\n]\s*(.+?)(?:\n|Tel|Fax|E-Mail|$)",
        r"[Zz]uständig(?:e[rn]?)?\s*[:\n]\s*(.+?)(?:\n|Tel|Fax|E-Mail|$)",
    ]))
    emails = re.findall(r"[\w.+\-]+@[\w\-]+\.[\w.\-]{2,}", text)
    email = emails[0] if emails else None
    phone = _clean(_first(text, [
        r"[Tt]el(?:efon|\.)\s*[:\-]?\s*(\+?[\d\s()/.\-]{7,25})",
        r"[Pp]hone\s*[:\-]?\s*(\+?[\d\s()/.\-]{7,25})",
        r"[Tt]el\.\s*:\s*(\+?[\d\s()/.\-]{7,25})",
    ]))
    fax = _clean(_first(text, [
        r"[Ff]ax\s*[:\-]?\s*(\+?[\d\s()/.\-]{7,25})",
    ]))
    return person, email, phone, fax


def _extract_zuschlagskriterien(text: str) -> list[str]:
    section = _first(text, [
        r"[Zz]uschlagskriterien?\s*[:\n](.*?)(?:\n[A-Z]|\Z)",
        r"[Aa]warding\s+[Cc]riteria?\s*[:\n](.*?)(?:\n[A-Z]|\Z)",
    ], re.IGNORECASE | re.DOTALL)
    if not section:
        return []
    lines = [l.strip(" \t-•*·") for l in section.split("\n") if l.strip(" \t-•*·")]
    return [l for l in lines if 3 < len(l) < 200][:10]


def _extract_lose(text: str) -> list[str]:
    return _all(text, [
        r"[Ll]os\s+(\d+)\s*[:\-]?\s*(.{5,80})",
        r"[Tt]eillos\s+(\d+)\s*[:\-]?\s*(.{5,80})",
    ])


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def extract_fields(text: str) -> TenderFields:
    """Extract all structured procurement fields from raw document text."""
    f = TenderFields()

    f.vergabenummer        = _extract_vergabenummer(text)
    f.ted_reference        = _extract_ted_reference(text)
    f.auftraggeber         = _extract_auftraggeber(text)
    f.titel                = _extract_titel(text)
    f.leistungsbeschreibung = _extract_leistungsbeschreibung(text)
    f.vergabeverfahren     = _extract_vergabeverfahren(text)
    f.auftragsart          = _extract_auftragsart(text)
    f.cpv_codes            = _extract_cpv(text)
    f.nuts_codes           = _extract_nuts(text)
    f.leistungsort         = _extract_leistungsort(text)
    f.laufzeit             = _extract_laufzeit(text)
    f.zuschlagskriterien   = _extract_zuschlagskriterien(text)
    f.lose                 = _extract_lose(text)

    pub, deadline, binding = _extract_dates(text)
    f.veroeffentlichungsdatum = pub
    f.abgabefrist             = deadline
    f.bindefrist              = binding

    val, cur = _extract_value(text)
    f.auftragswert = val
    f.waehrung     = cur

    person, email, phone, fax = _extract_contact(text)
    f.ansprechpartner = person
    f.email           = email
    f.telefon         = phone
    f.fax             = fax

    return f


def merge_fields(fields_list: list[TenderFields]) -> TenderFields:
    """Merge multiple TenderFields objects, preferring the first non-None value."""
    merged = TenderFields()
    for f in fields_list:
        for attr in merged.__dataclass_fields__:  # type: ignore[attr-defined]
            current = getattr(merged, attr)
            incoming = getattr(f, attr)
            if isinstance(current, list):
                for item in incoming:
                    if item not in current:
                        current.append(item)
            elif current is None and incoming is not None:
                setattr(merged, attr, incoming)
    return merged
