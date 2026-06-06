"""
Raw text extraction from PDF, DOCX, XLSX, and ZIP files.
No LLM — pure library parsing only.

OCR fallback: when a PDF yields fewer than MIN_CHARS_PER_PAGE characters per
page (typical of scanned documents), pytesseract is tried if available.
"""
from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from app.utils.logger import get_logger

log = get_logger(__name__)

# Threshold: if extracted text per page is below this, assume scanned and try OCR
_MIN_CHARS_PER_PAGE = 50


@dataclass
class ParsedDocument:
    filename: str
    text: str
    tables: list[list[list[str]]] = field(default_factory=list)
    pages: int = 0
    mime: str = ""
    parse_error: str | None = None
    ocr_used: bool = False


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

def parse_pdf(path: Path) -> ParsedDocument:
    try:
        import pdfplumber  # type: ignore
    except ImportError:
        return _pdf_pypdf_fallback(path)

    text_parts: list[str] = []
    tables: list[list[list[str]]] = []
    pages = 0
    try:
        with pdfplumber.open(str(path)) as pdf:
            pages = len(pdf.pages)
            for page in pdf.pages:
                raw = page.extract_text(x_tolerance=3, y_tolerance=3)
                if raw:
                    text_parts.append(raw)
                for tbl in page.extract_tables():
                    if tbl:
                        tables.append([[cell or "" for cell in row] for row in tbl])
    except Exception as e:  # noqa: BLE001
        log.warning("parsers.pdf.pdfplumber_error", filename=path.name, error=str(e))
        return ParsedDocument(
            filename=path.name, text="\n".join(text_parts),
            tables=tables, pages=pages, mime="application/pdf",
            parse_error=str(e),
        )

    combined = "\n".join(text_parts)

    # OCR fallback: scanned PDFs produce almost no text
    if pages > 0 and len(combined) / max(pages, 1) < _MIN_CHARS_PER_PAGE:
        log.info("parsers.pdf.low_text_trying_ocr", filename=path.name, pages=pages)
        ocr_text = _ocr_pdf(path)
        if ocr_text and len(ocr_text) > len(combined):
            log.info("parsers.pdf.ocr_improved", filename=path.name, chars=len(ocr_text))
            return ParsedDocument(
                filename=path.name, text=ocr_text,
                tables=tables, pages=pages, mime="application/pdf",
                ocr_used=True,
            )

    return ParsedDocument(
        filename=path.name, text=combined,
        tables=tables, pages=pages, mime="application/pdf",
    )


def _pdf_pypdf_fallback(path: Path) -> ParsedDocument:
    try:
        from pypdf import PdfReader  # type: ignore
        reader = PdfReader(str(path))
        parts = []
        for page in reader.pages:
            t = page.extract_text()
            if t:
                parts.append(t)
        combined = "\n".join(parts)
        pages = len(reader.pages)

        if pages > 0 and len(combined) / max(pages, 1) < _MIN_CHARS_PER_PAGE:
            ocr_text = _ocr_pdf(path)
            if ocr_text and len(ocr_text) > len(combined):
                return ParsedDocument(
                    filename=path.name, text=ocr_text,
                    pages=pages, mime="application/pdf", ocr_used=True,
                )

        return ParsedDocument(
            filename=path.name, text=combined,
            pages=pages, mime="application/pdf",
        )
    except Exception as e:  # noqa: BLE001
        log.warning("parsers.pdf.pypdf_error", filename=path.name, error=str(e))
        return ParsedDocument(filename=path.name, text="", mime="application/pdf", parse_error=str(e))


def _ocr_pdf(path: Path) -> str:
    """
    OCR fallback for scanned PDFs using pytesseract + pdf2image.
    Returns empty string when dependencies are unavailable — callers must
    degrade gracefully.
    """
    try:
        from pdf2image import convert_from_path  # type: ignore
        import pytesseract  # type: ignore
    except ImportError:
        log.debug("parsers.ocr.unavailable", filename=path.name)
        return ""

    try:
        images = convert_from_path(
            str(path),
            dpi=200,
            fmt="jpeg",
            thread_count=2,
        )
        parts: list[str] = []
        for img in images:
            # Primary: German; fallback: German + English
            text = pytesseract.image_to_string(img, lang="deu+eng", config="--psm 3")
            if text.strip():
                parts.append(text)
        return "\n".join(parts)
    except Exception as e:  # noqa: BLE001
        log.warning("parsers.ocr.failed", filename=path.name, error=str(e))
        return ""


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------

def parse_docx(path: Path) -> ParsedDocument:
    _MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    try:
        from docx import Document  # type: ignore
    except ImportError:
        return ParsedDocument(
            filename=path.name, text="", mime=_MIME,
            parse_error="python-docx not installed",
        )

    try:
        doc = Document(str(path))
        parts: list[str] = [p.text for p in doc.paragraphs if p.text.strip()]
        tables: list[list[list[str]]] = []
        for tbl in doc.tables:
            rows = [[cell.text.strip() for cell in row.cells] for row in tbl.rows]
            tables.append(rows)
        return ParsedDocument(
            filename=path.name, text="\n".join(parts),
            tables=tables, mime=_MIME,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("parsers.docx.error", filename=path.name, error=str(e))
        return ParsedDocument(filename=path.name, text="", mime=_MIME, parse_error=str(e))


# ---------------------------------------------------------------------------
# XLSX / XLS
# ---------------------------------------------------------------------------

def parse_xlsx(path: Path) -> ParsedDocument:
    """
    Parse Excel workbooks (xlsx/xls) using openpyxl in read-only + data-only
    mode. Reads all sheets and concatenates cell values as TSV-style lines.
    Memory-safe for large spreadsheets: iterates row-by-row without loading
    the entire workbook into RAM.
    """
    _MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    try:
        import openpyxl  # type: ignore
    except ImportError:
        return ParsedDocument(
            filename=path.name, text="", mime=_MIME,
            parse_error="openpyxl not installed",
        )

    try:
        wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
        parts: list[str] = []
        tables: list[list[list[str]]] = []

        for ws in wb.worksheets:
            sheet_rows: list[list[str]] = []
            for row in ws.iter_rows(values_only=True):
                cells = [str(c) if c is not None else "" for c in row]
                line = "\t".join(cells).rstrip("\t")
                if line.strip():
                    parts.append(line)
                    sheet_rows.append(cells)
            if sheet_rows:
                tables.append(sheet_rows)

        wb.close()
        return ParsedDocument(
            filename=path.name,
            text="\n".join(parts),
            tables=tables,
            mime=_MIME,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("parsers.xlsx.error", filename=path.name, error=str(e))
        return ParsedDocument(filename=path.name, text="", mime=_MIME, parse_error=str(e))


# ---------------------------------------------------------------------------
# ZIP — recursive extraction with validation
# ---------------------------------------------------------------------------

def parse_zip(path: Path) -> list[ParsedDocument]:
    results: list[ParsedDocument] = []
    try:
        with zipfile.ZipFile(str(path)) as zf:
            for name in zf.namelist():
                if name.endswith("/"):
                    continue
                suffix = Path(name).suffix.lower()
                try:
                    data = zf.read(name)
                except Exception as e:
                    log.debug("parsers.zip.read_error", name=name, error=str(e))
                    continue

                if suffix == ".pdf":
                    doc = _parse_bytes_as_pdf(data, name)
                elif suffix == ".docx":
                    doc = _parse_bytes_as_docx(data, name)
                elif suffix in (".xlsx", ".xls"):
                    doc = _parse_bytes_as_xlsx(data, name)
                elif suffix in (".txt", ".xml", ".html", ".htm", ".csv"):
                    doc = ParsedDocument(
                        filename=name,
                        text=data.decode("utf-8", errors="replace"),
                        mime="text/plain",
                    )
                else:
                    continue
                results.append(doc)
    except zipfile.BadZipFile as e:
        log.warning("parsers.zip.bad_zip", filename=path.name, error=str(e))
        results.append(ParsedDocument(filename=path.name, text="", parse_error=f"bad zip: {e}"))
    return results


def _parse_bytes_as_pdf(data: bytes, name: str) -> ParsedDocument:
    try:
        import pdfplumber  # type: ignore
        text_parts: list[str] = []
        tables: list[list[list[str]]] = []
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            pages = len(pdf.pages)
            for page in pdf.pages:
                raw = page.extract_text(x_tolerance=3, y_tolerance=3)
                if raw:
                    text_parts.append(raw)
                for tbl in page.extract_tables():
                    if tbl:
                        tables.append([[cell or "" for cell in row] for row in tbl])
        return ParsedDocument(
            filename=name, text="\n".join(text_parts),
            tables=tables, pages=pages, mime="application/pdf",
        )
    except Exception as e:  # noqa: BLE001
        return ParsedDocument(filename=name, text="", mime="application/pdf", parse_error=str(e))


def _parse_bytes_as_docx(data: bytes, name: str) -> ParsedDocument:
    try:
        from docx import Document  # type: ignore
        doc = Document(io.BytesIO(data))
        parts = [p.text for p in doc.paragraphs if p.text.strip()]
        tables: list[list[list[str]]] = []
        for tbl in doc.tables:
            rows = [[cell.text.strip() for cell in row.cells] for row in tbl.rows]
            tables.append(rows)
        return ParsedDocument(filename=name, text="\n".join(parts), tables=tables)
    except Exception as e:  # noqa: BLE001
        return ParsedDocument(filename=name, text="", parse_error=str(e))


def _parse_bytes_as_xlsx(data: bytes, name: str) -> ParsedDocument:
    try:
        import openpyxl  # type: ignore
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        parts: list[str] = []
        for ws in wb.worksheets:
            for row in ws.iter_rows(values_only=True):
                line = "\t".join(str(c) if c is not None else "" for c in row).rstrip("\t")
                if line.strip():
                    parts.append(line)
        wb.close()
        return ParsedDocument(filename=name, text="\n".join(parts))
    except Exception as e:  # noqa: BLE001
        return ParsedDocument(filename=name, text="", parse_error=str(e))


# ---------------------------------------------------------------------------
# Router — dispatch any file to the right parser
# ---------------------------------------------------------------------------

def parse_file(path: Path) -> list[ParsedDocument]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return [parse_pdf(path)]
    if suffix == ".docx":
        return [parse_docx(path)]
    if suffix in (".xlsx", ".xls"):
        return [parse_xlsx(path)]
    if suffix == ".zip":
        return parse_zip(path)
    if suffix in (".txt", ".xml", ".html", ".htm", ".csv"):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            text = ""
        return [ParsedDocument(filename=path.name, text=text, mime="text/plain")]
    return []
