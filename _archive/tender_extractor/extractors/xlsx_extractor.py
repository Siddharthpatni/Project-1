"""
XLSX Extractor — openpyxl based extraction of spreadsheet tender documents.

Algorithm:
  1. Open the workbook with openpyxl (data_only=True so formulas are resolved).
  2. For each sheet, auto-detect layout:
       key_value : column A contains labels, column B contains values
                   (detected when >50% of populated rows follow A=label, B=value)
       table     : first row is a header row, subsequent rows are data
  3. Key-value sheets produce a flat dict; table sheets produce list of row dicts.
  4. Return a DocumentContent whose sheets field carries all sheet results and
     whose full_text is a concatenation of all cell values for text-search purposes.
"""
from __future__ import annotations

import logging
from pathlib import Path

from tender_extractor.models import BaseExtractor, DocumentContent, PageContent, TableContent

log = logging.getLogger(__name__)


class XLSXExtractor(BaseExtractor):
    """Extracts structured data from XLSX spreadsheets."""

    def extract(self, filepath: str) -> DocumentContent:
        """
        Open the workbook, detect each sheet's layout, and return a unified
        DocumentContent.  The sheets field carries per-sheet results.
        full_text is built by concatenating all cell values for downstream
        text-based field parsing.
        """
        try:
            import openpyxl
        except ImportError:
            log.error("xlsx_extractor.openpyxl_not_installed")
            return _empty(filepath)

        try:
            wb = openpyxl.load_workbook(filepath, data_only=True, read_only=True)
        except Exception as e:
            log.error("xlsx_extractor.open_error", extra={"file": filepath, "error": str(e)})
            return _empty(filepath)

        sheets_result: list[dict] = []
        all_tables: list[TableContent] = []
        text_parts: list[str] = []

        for sheet_name in wb.sheetnames:
            try:
                ws = wb[sheet_name]
                rows = _read_rows(ws)
                if not rows:
                    continue

                layout = _detect_layout(rows)

                if layout == "key_value":
                    data = _parse_key_value(rows)
                    sheets_result.append({"name": sheet_name, "layout": "key_value", "data": data})
                    for k, v in data.items():
                        text_parts.append(f"{k}: {v}")
                else:
                    headers = [str(c) for c in rows[0]]
                    table_rows: list[dict[str, str]] = []
                    for row in rows[1:]:
                        if not any(row):
                            continue
                        row_dict = {headers[j]: (str(row[j]) if j < len(row) else "") for j in range(len(headers))}
                        table_rows.append(row_dict)
                    sheets_result.append({"name": sheet_name, "layout": "table", "rows": table_rows})
                    all_tables.append(TableContent(
                        page_num=None,
                        section_header=sheet_name,
                        headers=headers,
                        rows=table_rows,
                    ))
                    for r in table_rows:
                        text_parts.append(" | ".join(str(v) for v in r.values()))
            except Exception as e:
                log.warning("xlsx_extractor.sheet_error", extra={"sheet": sheet_name, "error": str(e)})

        wb.close()

        full_text = "\n".join(text_parts)
        lines = [ln.strip() for ln in full_text.splitlines() if ln.strip()]

        return DocumentContent(
            filename=Path(filepath).name,
            file_type="xlsx",
            pages=[PageContent(page_num=1, text=full_text, lines=lines)],
            full_text=full_text,
            all_tables=all_tables,
            metadata={"num_sheets": len(sheets_result)},
            sections_index={},
            sheets=sheets_result,
        )


# ── Helpers ────────────────────────────────────────────────────────────────

def _read_rows(ws) -> list[list]:
    """
    Read all rows from an openpyxl worksheet into a list of lists.
    Stops at the first fully-empty row after at least one data row.
    """
    rows: list[list] = []
    for row in ws.iter_rows(values_only=True):
        cells = [c for c in row]
        if not any(c is not None for c in cells):
            if rows:
                break
            continue
        rows.append([str(c).strip() if c is not None else "" for c in cells])
    return rows


def _detect_layout(rows: list[list]) -> str:
    """
    Heuristic: if >50% of rows have a non-empty string in col-0 and a non-empty
    value in col-1 with no header-like first row, classify as key_value.
    Otherwise classify as table (first row = headers).
    """
    if not rows or len(rows[0]) < 2:
        return "table"

    # Check if first row looks like column headers (short strings, no numbers)
    header_row = rows[0]
    numeric_in_header = sum(1 for c in header_row if _is_numeric(str(c)))
    if numeric_in_header > len(header_row) // 2:
        return "key_value"

    # Count rows where col-0 is a short non-empty label and col-1 has a value
    kv_score = 0
    for row in rows:
        if len(row) >= 2 and row[0] and len(str(row[0])) < 60 and row[1]:
            kv_score += 1

    return "key_value" if kv_score > len(rows) * 0.5 else "table"


def _parse_key_value(rows: list[list]) -> dict[str, str]:
    """
    Build a label→value dict from rows where col-0 is the label, col-1 is the value.
    Merges continuation rows (empty col-0, non-empty col-1) into the previous label.
    """
    result: dict[str, str] = {}
    last_key: str | None = None
    for row in rows:
        if not row:
            continue
        key = str(row[0]).strip().rstrip(":") if row[0] else ""
        val = str(row[1]).strip() if len(row) > 1 and row[1] else ""
        if key:
            result[key] = val
            last_key = key
        elif val and last_key:
            # Continuation value — append to previous key
            result[last_key] = (result[last_key] + " " + val).strip()
    return result


def _is_numeric(s: str) -> bool:
    """Return True if the string represents a number."""
    try:
        float(s.replace(",", "").replace(" ", ""))
        return True
    except ValueError:
        return False


def _empty(filepath: str) -> DocumentContent:
    """Return an empty DocumentContent on total failure."""
    return DocumentContent(
        filename=Path(filepath).name,
        file_type="xlsx",
        pages=[],
        full_text="",
        all_tables=[],
        metadata={},
        sections_index={},
        sheets=[],
    )
