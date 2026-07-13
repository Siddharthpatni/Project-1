"""
DOCX Extractor — python-docx based extraction of tender documents.

Algorithm:
  1. Open the DOCX with python-docx.
  2. Walk all paragraphs, recording the style name (Heading 1, Heading 2, Normal …).
  3. Build a section tree from heading hierarchy; each heading marks a new section.
  4. Detect bold runs inside Normal paragraphs as potential field labels.
  5. Extract all tables: each table becomes a list of row dicts (first row = header).
  6. Return a unified DocumentContent with pages=[PageContent(1, full_text, lines)],
     all_tables, metadata, and sections_index.
"""
from __future__ import annotations

import logging
from pathlib import Path

from tender_extractor.models import BaseExtractor, DocumentContent, PageContent, TableContent

log = logging.getLogger(__name__)


class DOCXExtractor(BaseExtractor):
    """Extracts paragraphs, headings, bold labels, and tables from DOCX files."""

    def extract(self, filepath: str) -> DocumentContent:
        """
        Open the DOCX file, walk paragraphs and tables in document order,
        build full_text, sections_index, and all_tables, then wrap into
        a single PageContent (DOCX has no physical page numbers).
        """
        try:
            from docx import Document
        except ImportError:
            log.error("docx_extractor.python_docx_not_installed")
            return _empty(filepath)

        try:
            doc = Document(filepath)
        except Exception as e:
            log.error("docx_extractor.open_error", extra={"file": filepath, "error": str(e)})
            return _empty(filepath)

        lines: list[str] = []
        sections_index: dict[str, int] = {}
        all_tables: list[TableContent] = []
        current_section: str | None = None
        current_section_page = 1  # DOCX sections are mapped to logical "page" 1

        # Walk body elements in document order using the XML element list
        # Each element is either a paragraph or a table
        for element in doc.element.body:
            tag = element.tag.split("}")[-1] if "}" in element.tag else element.tag

            if tag == "p":
                # Paragraph element — reconstruct via python-docx API
                from docx.oxml.ns import qn
                from docx.text.paragraph import Paragraph
                para = Paragraph(element, doc)
                text = para.text.strip()
                if not text:
                    continue

                style_name = para.style.name if para.style else "Normal"

                # Heading detection
                if style_name.startswith("Heading"):
                    key = text.lower()[:50]
                    if key not in sections_index:
                        sections_index[key] = 1
                    current_section = text
                    lines.append(text)
                else:
                    # Check for bold runs acting as field labels
                    bold_prefix = _extract_bold_prefix(para)
                    if bold_prefix:
                        lines.append(bold_prefix + ": " + text[len(bold_prefix):].lstrip(": ").strip())
                    else:
                        lines.append(text)

            elif tag == "tbl":
                from docx.table import Table
                tbl = Table(element, doc)
                parsed = _parse_docx_table(tbl, current_section)
                if parsed:
                    all_tables.append(parsed)

        full_text = "\n".join(lines)

        # Extract core document properties as metadata
        try:
            cp = doc.core_properties
            metadata = {
                "title":         cp.title or "",
                "author":        cp.author or "",
                "created":       str(cp.created or ""),
                "modified":      str(cp.modified or ""),
                "subject":       cp.subject or "",
                "num_paragraphs": len(doc.paragraphs),
            }
        except Exception:
            metadata = {}

        return DocumentContent(
            filename=Path(filepath).name,
            file_type="docx",
            pages=[PageContent(page_num=1, text=full_text, lines=lines)],
            full_text=full_text,
            all_tables=all_tables,
            metadata=metadata,
            sections_index=sections_index,
        )


# ── Helpers ────────────────────────────────────────────────────────────────

def _extract_bold_prefix(para) -> str | None:
    """
    If a paragraph begins with one or more contiguous bold runs that look like
    a label (short, ends before the rest of the text), return the bold text.
    Returns None if no bold prefix is detected.
    """
    bold_text = []
    for run in para.runs:
        if run.bold and run.text.strip():
            bold_text.append(run.text)
        else:
            break  # bold prefix ends at first non-bold run

    combined = "".join(bold_text).strip().rstrip(":")
    if combined and len(combined) < 80:
        return combined
    return None


def _parse_docx_table(tbl, section_header: str | None) -> TableContent | None:
    """
    Convert a python-docx Table object into a TableContent.
    First row is used as headers; subsequent rows become dicts keyed by header.
    Skips entirely-empty tables.
    """
    rows_raw: list[list[str]] = []
    for row in tbl.rows:
        cells = [cell.text.strip() for cell in row.cells]
        rows_raw.append(cells)

    if len(rows_raw) < 2:
        return None

    headers = rows_raw[0]
    if not any(headers):
        return None

    data_rows: list[dict[str, str]] = []
    for raw_row in rows_raw[1:]:
        if not any(raw_row):
            continue
        row_dict = {headers[j]: (raw_row[j] if j < len(raw_row) else "") for j in range(len(headers))}
        data_rows.append(row_dict)

    if not data_rows:
        return None

    return TableContent(
        page_num=None,
        section_header=section_header,
        headers=headers,
        rows=data_rows,
    )


def _empty(filepath: str) -> DocumentContent:
    """Return an empty DocumentContent on total failure."""
    return DocumentContent(
        filename=Path(filepath).name,
        file_type="docx",
        pages=[],
        full_text="",
        all_tables=[],
        metadata={},
        sections_index={},
    )
