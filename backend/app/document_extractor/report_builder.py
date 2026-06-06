"""
Report builder: converts a TenderFields + source document list into a PDF or DOCX.

No LLM — purely structural document generation using reportlab (PDF) and
python-docx (DOCX).
"""
from __future__ import annotations

import io
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Literal

from app.document_extractor.field_extractor import TenderFields
from app.document_extractor.parsers import ParsedDocument


# ---------------------------------------------------------------------------
# PDF builder (reportlab)
# ---------------------------------------------------------------------------

def build_pdf(
    fields: TenderFields,
    source_docs: list[ParsedDocument],
    source_url: str = "",
) -> bytes:
    try:
        from reportlab.lib import colors  # type: ignore
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
        )
    except ImportError:
        raise RuntimeError("reportlab is required: pip install reportlab")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        leftMargin=2.5 * cm,
        rightMargin=2.5 * cm,
        title="Vergabepilot.AI — Extrahierte Ausschreibungsdaten",
    )
    styles = getSampleStyleSheet()

    BRAND   = colors.HexColor("#1a3c5e")
    ACCENT  = colors.HexColor("#3b7dd8")
    LIGHT   = colors.HexColor("#f0f4fa")
    MUTED   = colors.HexColor("#6b7a8d")

    h1_style = ParagraphStyle("H1", parent=styles["Heading1"],
                               textColor=BRAND, fontSize=16, spaceAfter=6)
    h2_style = ParagraphStyle("H2", parent=styles["Heading2"],
                               textColor=BRAND, fontSize=12, spaceBefore=14, spaceAfter=4)
    body_style = ParagraphStyle("Body", parent=styles["Normal"],
                                 fontSize=9, leading=13)
    label_style = ParagraphStyle("Label", parent=styles["Normal"],
                                  fontSize=8, textColor=MUTED, leading=11)
    caption_style = ParagraphStyle("Caption", parent=styles["Normal"],
                                    fontSize=7, textColor=MUTED, leading=10)

    story = []

    # Header block
    story.append(Paragraph("Vergabepilot.AI", h1_style))
    story.append(Paragraph("Automatisch extrahierte Ausschreibungsdaten", body_style))
    story.append(Spacer(1, 0.3 * cm))
    story.append(HRFlowable(width="100%", thickness=2, color=ACCENT))
    story.append(Spacer(1, 0.4 * cm))

    meta_rows = [
        ["Extrahiert am", datetime.now(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")],
        ["Quell-URL", source_url or "—"],
        ["Quelldokumente", ", ".join(d.filename for d in source_docs) or "—"],
    ]
    meta_tbl = Table(meta_rows, colWidths=[4 * cm, 13 * cm])
    meta_tbl.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("TEXTCOLOR", (0, 0), (0, -1), MUTED),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(meta_tbl)
    story.append(Spacer(1, 0.5 * cm))

    # ---- Structured Fields Table ----------------------------------------
    story.append(Paragraph("Kerndaten der Ausschreibung", h2_style))

    field_rows: list[tuple[str, str]] = [
        ("Vergabenummer",        fields.vergabenummer or "—"),
        ("TED-Referenz",         fields.ted_reference or "—"),
        ("Auftraggeber",         fields.auftraggeber or "—"),
        ("Vergabestelle",        fields.vergabestelle or fields.auftraggeber or "—"),
        ("Titel",                fields.titel or "—"),
        ("Vergabeverfahren",     fields.vergabeverfahren or "—"),
        ("Auftragsart",          fields.auftragsart or "—"),
        ("Veröffentlicht",       fields.veroeffentlichungsdatum or "—"),
        ("Abgabefrist",          fields.abgabefrist or "—"),
        ("Bindefrist",           fields.bindefrist or "—"),
        ("CPV-Code(s)",          ", ".join(fields.cpv_codes) if fields.cpv_codes else "—"),
        ("NUTS-Code(s)",         ", ".join(fields.nuts_codes) if fields.nuts_codes else "—"),
        ("Auftragswert",         f"{fields.auftragswert} {fields.waehrung or ''}".strip() if fields.auftragswert else "—"),
        ("Leistungsort",         fields.leistungsort or "—"),
        ("Laufzeit",             fields.laufzeit or "—"),
        ("Ansprechpartner",      fields.ansprechpartner or "—"),
        ("E-Mail",               fields.email or "—"),
        ("Telefon",              fields.telefon or "—"),
        ("Fax",                  fields.fax or "—"),
    ]

    tbl_data = [[Paragraph(f"<b>{label}</b>", label_style), Paragraph(val, body_style)]
                for label, val in field_rows]
    tbl = Table(tbl_data, colWidths=[5 * cm, 12 * cm])
    tbl.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0),  (0, -1), LIGHT),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, LIGHT]),
        ("GRID",         (0, 0),  (-1, -1), 0.3, colors.HexColor("#d0d8e8")),
        ("VALIGN",       (0, 0),  (-1, -1), "TOP"),
        ("TOPPADDING",   (0, 0),  (-1, -1), 5),
        ("BOTTOMPADDING",(0, 0),  (-1, -1), 5),
        ("LEFTPADDING",  (0, 0),  (-1, -1), 6),
        ("RIGHTPADDING", (0, 0),  (-1, -1), 6),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 0.5 * cm))

    # ---- Zuschlagskriterien ---------------------------------------------
    if fields.zuschlagskriterien:
        story.append(Paragraph("Zuschlagskriterien", h2_style))
        for crit in fields.zuschlagskriterien:
            story.append(Paragraph(f"• {crit}", body_style))
        story.append(Spacer(1, 0.3 * cm))

    # ---- Lose -----------------------------------------------------------
    if fields.lose:
        story.append(Paragraph("Lose / Teillose", h2_style))
        for lot in fields.lose:
            story.append(Paragraph(f"• {lot}", body_style))
        story.append(Spacer(1, 0.3 * cm))

    # ---- Full text extract (truncated) ----------------------------------
    for parsed in source_docs:
        if not parsed.text.strip():
            continue
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#d0d8e8")))
        story.append(Spacer(1, 0.3 * cm))
        story.append(Paragraph(f"Volltext: {parsed.filename}", h2_style))
        # Limit to first 3000 chars to keep the report readable
        excerpt = parsed.text[:3000].replace("\n", "<br/>")
        if len(parsed.text) > 3000:
            excerpt += "<br/>...[gekürzt]"
        story.append(Paragraph(excerpt, body_style))
        story.append(Spacer(1, 0.3 * cm))

    # ---- Footer ---------------------------------------------------------
    story.append(Spacer(1, 0.5 * cm))
    story.append(HRFlowable(width="100%", thickness=1, color=ACCENT))
    story.append(Spacer(1, 0.2 * cm))
    story.append(Paragraph(
        "Erstellt durch Vergabepilot.AI — Automatische Dokumentenanalyse ohne KI-Modelle / LLM",
        caption_style,
    ))

    doc.build(story)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# DOCX builder (python-docx)
# ---------------------------------------------------------------------------

def build_docx(
    fields: TenderFields,
    source_docs: list[ParsedDocument],
    source_url: str = "",
) -> bytes:
    try:
        from docx import Document  # type: ignore
        from docx.enum.text import WD_ALIGN_PARAGRAPH  # type: ignore
        from docx.oxml.ns import qn  # type: ignore
        from docx.shared import Pt, RGBColor  # type: ignore
    except ImportError:
        raise RuntimeError("python-docx is required: pip install python-docx")

    doc = Document()

    # Narrow margins
    for section in doc.sections:
        section.top_margin    = section.bottom_margin    = _cm(2)
        section.left_margin   = section.right_margin     = _cm(2.5)

    # Title
    title_p = doc.add_heading("Vergabepilot.AI — Ausschreibungsdaten", level=0)
    title_p.runs[0].font.color.rgb = RGBColor(0x1a, 0x3c, 0x5e)

    doc.add_paragraph(f"Extrahiert: {datetime.now(timezone.utc).strftime('%d.%m.%Y %H:%M UTC')}")
    if source_url:
        doc.add_paragraph(f"Quelle: {source_url}")
    doc.add_paragraph(f"Dokumente: {', '.join(d.filename for d in source_docs) or '—'}")
    doc.add_paragraph("")

    # Structured fields
    doc.add_heading("Kerndaten der Ausschreibung", level=1)

    field_rows: list[tuple[str, str]] = [
        ("Vergabenummer",     fields.vergabenummer or "—"),
        ("TED-Referenz",      fields.ted_reference or "—"),
        ("Auftraggeber",      fields.auftraggeber or "—"),
        ("Titel",             fields.titel or "—"),
        ("Vergabeverfahren",  fields.vergabeverfahren or "—"),
        ("Auftragsart",       fields.auftragsart or "—"),
        ("Veröffentlicht",    fields.veroeffentlichungsdatum or "—"),
        ("Abgabefrist",       fields.abgabefrist or "—"),
        ("CPV-Code(s)",       ", ".join(fields.cpv_codes) if fields.cpv_codes else "—"),
        ("NUTS-Code(s)",      ", ".join(fields.nuts_codes) if fields.nuts_codes else "—"),
        ("Auftragswert",      f"{fields.auftragswert} {fields.waehrung or ''}".strip() if fields.auftragswert else "—"),
        ("Leistungsort",      fields.leistungsort or "—"),
        ("Laufzeit",          fields.laufzeit or "—"),
        ("Ansprechpartner",   fields.ansprechpartner or "—"),
        ("E-Mail",            fields.email or "—"),
        ("Telefon",           fields.telefon or "—"),
    ]

    tbl = doc.add_table(rows=1, cols=2)
    tbl.style = "Table Grid"
    hdr = tbl.rows[0].cells
    hdr[0].text = "Feld"
    hdr[1].text = "Wert"
    for cell in hdr:
        for run in cell.paragraphs[0].runs:
            run.bold = True

    for label, val in field_rows:
        row = tbl.add_row().cells
        row[0].text = label
        row[1].text = val

    doc.add_paragraph("")

    # Zuschlagskriterien
    if fields.zuschlagskriterien:
        doc.add_heading("Zuschlagskriterien", level=2)
        for crit in fields.zuschlagskriterien:
            doc.add_paragraph(f"• {crit}", style="List Bullet")

    # Lose
    if fields.lose:
        doc.add_heading("Lose / Teillose", level=2)
        for lot in fields.lose:
            doc.add_paragraph(f"• {lot}", style="List Bullet")

    # Full text
    for parsed in source_docs:
        if not parsed.text.strip():
            continue
        doc.add_heading(f"Volltext: {parsed.filename}", level=2)
        excerpt = parsed.text[:3000]
        if len(parsed.text) > 3000:
            excerpt += "\n...[gekürzt]"
        doc.add_paragraph(excerpt)

    # Footer
    doc.add_paragraph("\n— Erstellt durch Vergabepilot.AI — automatische Analyse ohne KI-Modelle")

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _cm(val: float):
    try:
        from docx.shared import Cm  # type: ignore
        return Cm(val)
    except ImportError:
        return int(val * 360000)


# ---------------------------------------------------------------------------
# Unified entry point
# ---------------------------------------------------------------------------

def build_report(
    fields: TenderFields,
    source_docs: list[ParsedDocument],
    source_url: str = "",
    fmt: Literal["pdf", "docx"] = "pdf",
) -> tuple[bytes, str]:
    """Return (bytes, mime_type)."""
    if fmt == "docx":
        return (
            build_docx(fields, source_docs, source_url),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    return build_pdf(fields, source_docs, source_url), "application/pdf"
