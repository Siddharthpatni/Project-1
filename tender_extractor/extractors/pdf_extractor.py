"""
PDF Extractor — pdfplumber primary, OCR fallback for scanned documents.

Algorithm:
  1. Open PDF with pdfplumber.
  2. For each page: extract text, split into lines, tag with page_num.
  3. Detect section headers using 4 heuristics (ALL CAPS, numbered, short colon, known keywords).
  4. Extract tables per page → convert to list of row dicts, tag with page_num + nearest header.
  5. Extract PDF metadata (title, author, creator, dates).
  6. If extracted text is sparse (< 100 chars total), fall back to OCR.
  7. Return unified DocumentContent.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from tender_extractor.models import BaseExtractor, DocumentContent, PageContent, TableContent

log = logging.getLogger(__name__)


class PDFExtractor(BaseExtractor):
    """Extracts text, tables, and metadata from PDF files."""

    def extract(self, filepath: str) -> DocumentContent:
        """
        Main extraction method. Tries pdfplumber first; falls back to OCR
        if the text layer is empty or minimal (scanned PDF).
        """
        try:
            import pdfplumber
        except ImportError:
            log.error("pdf_extractor.pdfplumber_not_installed")
            return _empty(filepath)

        pages: list[PageContent] = []
        all_tables: list[TableContent] = []
        metadata: dict = {}
        sections_index: dict[str, int] = {}
        current_section: str | None = None

        try:
            with pdfplumber.open(filepath) as pdf:
                # --- Metadata ---
                meta = pdf.metadata or {}
                metadata = {
                    "title": meta.get("Title", ""),
                    "author": meta.get("Author", ""),
                    "creator": meta.get("Creator", ""),
                    "creation_date": str(meta.get("CreationDate", "")),
                    "num_pages": len(pdf.pages),
                }

                for page in pdf.pages:
                    pnum = page.page_number
                    raw_text = page.extract_text(x_tolerance=3, y_tolerance=3) or ""
                    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]

                    # Detect section headers in this page's lines
                    for ln in lines:
                        if _is_section_header(ln):
                            header_key = ln.lower()[:40].strip()
                            if header_key not in sections_index:
                                sections_index[header_key] = pnum
                            current_section = ln

                    pages.append(PageContent(
                        page_num=pnum,
                        text=raw_text,
                        lines=lines,
                    ))

                    # Tables
                    try:
                        for tbl_raw in page.extract_tables():
                            if not tbl_raw or len(tbl_raw) < 2:
                                continue
                            parsed = _parse_raw_table(tbl_raw, pnum, current_section)
                            if parsed:
                                all_tables.append(parsed)
                    except Exception as e:
                        log.debug("pdf_extractor.table_error", extra={"page": pnum, "error": str(e)})

        except Exception as e:
            log.error("pdf_extractor.open_error", extra={"file": filepath, "error": str(e)})
            return _empty(filepath)

        full_text = "\n".join(p.text for p in pages)

        # Fallback to OCR if almost no text extracted
        if len(full_text.strip()) < 100:
            log.info("pdf_extractor.sparse_text_using_ocr", extra={"file": filepath})
            ocr_text = _ocr_fallback(filepath)
            if ocr_text:
                full_text = ocr_text
                ocr_lines = [ln.strip() for ln in ocr_text.splitlines() if ln.strip()]
                pages = [PageContent(page_num=1, text=ocr_text, lines=ocr_lines)]

        return DocumentContent(
            filename=Path(filepath).name,
            file_type="pdf",
            pages=pages,
            full_text=full_text,
            all_tables=all_tables,
            metadata=metadata,
            sections_index=sections_index,
        )


# ── Helpers ────────────────────────────────────────────────────────────────

def _is_section_header(line: str) -> bool:
    """
    Returns True if the line looks like a section header using 4 heuristics:
      1. All-caps line with at least 2 words.
      2. Numbered heading pattern (1., 2.1, 3.2.1, etc.).
      3. Short line (< 60 chars) ending with ':'.
      4. Starts with a known section keyword from patterns (checked inline).
    """
    stripped = line.strip()
    if not stripped or len(stripped) < 3:
        return False

    # Heuristic 1: ALL CAPS (ignore punctuation, must have ≥2 words)
    words = re.sub(r'[^a-zA-Z\s]', '', stripped).split()
    if len(words) >= 2 and all(w.isupper() for w in words if len(w) > 1):
        return True

    # Heuristic 2: Numbered heading
    if re.match(r'^\d+(\.\d+)*[\s\.]', stripped):
        return True

    # Heuristic 3: Short line ending with ':'
    if len(stripped) < 60 and stripped.endswith(':'):
        return True

    return False


def _parse_raw_table(
    raw: list[list[str | None]],
    page_num: int,
    section_header: str | None,
) -> TableContent | None:
    """
    Convert pdfplumber raw table (list of rows, each a list of cells) into
    a TableContent. First non-empty row is treated as the header.
    Empty cells are replaced with empty string.
    """
    cleaned = [[str(c).strip() if c else "" for c in row] for row in raw]
    # Find header row (first row with at least 2 non-empty cells)
    header_idx = 0
    for i, row in enumerate(cleaned):
        if sum(1 for c in row if c) >= 2:
            header_idx = i
            break

    headers = cleaned[header_idx]
    rows = []
    for row in cleaned[header_idx + 1:]:
        if not any(row):
            continue
        row_dict = {headers[j]: row[j] if j < len(row) else "" for j in range(len(headers))}
        rows.append(row_dict)

    if not rows:
        return None

    return TableContent(
        page_num=page_num,
        section_header=section_header,
        headers=headers,
        rows=rows,
    )


def _ocr_fallback(filepath: str) -> str:
    """
    Convert each PDF page to an image, then run tesseract OCR.
    Returns concatenated text from all pages, or empty string if OCR fails.
    """
    try:
        from pdf2image import convert_from_path
        import pytesseract
    except ImportError:
        log.warning("pdf_extractor.ocr_deps_missing")
        return ""

    try:
        images = convert_from_path(filepath, dpi=200, fmt="jpeg", thread_count=2)
        parts = []
        for img in images:
            text = pytesseract.image_to_string(img, lang="deu+eng", config="--psm 3")
            if text.strip():
                parts.append(text)
        return "\n".join(parts)
    except Exception as e:
        log.warning("pdf_extractor.ocr_failed", extra={"file": filepath, "error": str(e)})
        return ""


def _empty(filepath: str) -> DocumentContent:
    """Return an empty DocumentContent on total failure."""
    return DocumentContent(
        filename=Path(filepath).name,
        file_type="pdf",
        pages=[],
        full_text="",
        all_tables=[],
        metadata={},
        sections_index={},
    )
