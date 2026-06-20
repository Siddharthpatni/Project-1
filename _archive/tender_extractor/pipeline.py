"""
Pipeline — orchestrates the full extraction workflow for a batch of documents.

Algorithm:
  1. Accept input_path (file, folder, or ZIP) and detect its type.
  2. Use zip_handler.collect_files() to get a flat list of RawContent objects.
  3. For each file: route to the correct extractor, run field parsing,
     date/value normalisation, summarisation, and write the result JSON.
  4. Collect all results into master_results.json.
  5. Print a rich table summary in the terminal.
  6. Per-file errors are caught and logged; they never stop the batch.
"""
from __future__ import annotations

import csv
import json
import logging
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from tender_extractor.extractors.pdf_extractor  import PDFExtractor
from tender_extractor.extractors.docx_extractor import DOCXExtractor
from tender_extractor.extractors.xlsx_extractor import XLSXExtractor
from tender_extractor.extractors.txt_extractor  import TXTExtractor
from tender_extractor.extractors.zip_handler    import collect_files
from tender_extractor.models import (
    DocumentContent, ExtractedField, ExtractionResult, RawContent,
)
from tender_extractor.parsers.date_parser   import parse_date
from tender_extractor.parsers.field_parser  import (
    extract_all_fields, extract_tender_type,
)
from tender_extractor.parsers.table_parser  import find_value_in_tables
from tender_extractor.parsers.value_parser  import parse_value
from tender_extractor.summarizer.rule_summarizer import generate_summary

log = logging.getLogger(__name__)

_PATTERNS_PATH = Path(__file__).parent / "config" / "patterns.yaml"

_EXTRACTORS = {
    "pdf":  PDFExtractor(),
    "docx": DOCXExtractor(),
    "xlsx": XLSXExtractor(),
    "txt":  TXTExtractor(),
}

# Fields that should be passed through the date normaliser
_DATE_FIELDS = {"publication_date", "submission_deadline"}

# Fields that should be passed through the value/money normaliser
_VALUE_FIELDS = {"tender_value"}


def process_batch(
    input_path: str,
    output_dir: str,
    file_format: str = "json",
    verbose: bool = False,
) -> list[dict]:
    """
    Main entry point.  Processes all documents found at input_path and writes
    results to output_dir.  Returns the list of result dicts for testing.
    """
    cfg = _load_config()
    tender_types_cfg: dict = cfg.get("tender_types", {})

    output = Path(output_dir)
    results_dir = output / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    # Collect all files
    try:
        raw_files: list[RawContent] = collect_files(input_path)
    except FileNotFoundError as e:
        log.error("pipeline.input_not_found", extra={"error": str(e)})
        return []

    if not raw_files:
        log.warning("pipeline.no_supported_files_found", extra={"path": input_path})
        return []

    all_results: list[dict] = []
    table_rows: list[dict] = []   # for rich terminal table

    for raw in raw_files:
        result_dict = _process_one(raw, tender_types_cfg, verbose)
        all_results.append(result_dict)

        # Write per-file JSON
        if "json" in file_format:
            stem = Path(raw.filename).stem
            out_path = results_dir / f"{stem}.json"
            out_path.write_text(json.dumps(result_dict, ensure_ascii=False, indent=2), encoding="utf-8")

        # Collect row for summary table
        table_rows.append(_make_table_row(result_dict))

    # Write master results
    master_path = output / "master_results.json"
    master_path.write_text(
        json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if "csv" in file_format:
        _write_csv(all_results, output / "master_results.csv")

    _print_rich_table(table_rows)

    return all_results


def _process_one(raw: RawContent, tender_types_cfg: dict, verbose: bool) -> dict:
    """
    Extract, parse, and summarise a single file.
    Returns a plain dict representing the ExtractionResult JSON structure.
    Catches all exceptions so one bad file never kills the batch.
    """
    try:
        extractor = _EXTRACTORS.get(raw.file_type)
        if not extractor:
            return _error_result(raw, f"Unsupported file type: {raw.file_type}")

        doc: DocumentContent = extractor.extract(raw.filepath)

        # Field extraction
        fields: dict[str, ExtractedField] = extract_all_fields(doc)

        # Tender type extraction
        fields["tender_type"] = extract_tender_type(doc.full_text, tender_types_cfg)

        # Normalise date fields
        for fname in _DATE_FIELDS:
            ef = fields.get(fname)
            if ef and ef.value:
                parsed = parse_date(str(ef.value))
                if parsed:
                    ef.value = parsed["value"]
                    if parsed.get("low_confidence"):
                        ef.low_confidence = True
                        ef.confidence = min(ef.confidence, 0.4)

        # Normalise value/money fields
        for fname in _VALUE_FIELDS:
            ef = fields.get(fname)
            if ef and ef.value and isinstance(ef.value, str):
                parsed_money = parse_value(ef.value)
                if parsed_money:
                    ef.value = parsed_money
                # If value_parser returns None keep raw string

        # Try to fill missing fields from tables
        _fill_from_tables(fields, doc, _load_config())

        # Summarise
        summary_dict = generate_summary(fields, raw.filename)

        # Identify low-confidence fields
        low_conf = [
            name for name, ef in fields.items()
            if ef.value is not None and (ef.low_confidence or ef.confidence < 0.5)
        ]

        if verbose:
            _print_verbose(raw.filename, fields)

        return _build_result_dict(raw, doc, fields, summary_dict, low_conf)

    except Exception:
        tb = traceback.format_exc()
        log.error("pipeline.file_error", extra={"file": raw.filename, "traceback": tb})
        return _error_result(raw, tb)


def _fill_from_tables(
    fields: dict[str, ExtractedField],
    doc: DocumentContent,
    cfg: dict,
) -> None:
    """
    For any field with no value yet, attempt to find it in the extracted tables
    using the label variants from patterns.yaml.
    """
    field_defs = cfg.get("fields", {})
    for fname, ef in fields.items():
        if ef.value is not None:
            continue
        labels = field_defs.get(fname, {}).get("labels", [])
        if not labels:
            continue
        val, tbl_idx = find_value_in_tables(doc.all_tables, labels)
        if val:
            fields[fname] = ExtractedField(
                value=val,
                confidence=0.7,
                source_page=None,
                raw_text=val,
                low_confidence=False,
            )


def _build_result_dict(
    raw: RawContent,
    doc: DocumentContent,
    fields: dict[str, ExtractedField],
    summary: dict,
    low_conf: list[str],
) -> dict:
    """Assemble the final JSON-serialisable result dict."""
    serialised_fields: dict[str, Any] = {}
    for name, ef in fields.items():
        if ef.value is None and ef.confidence == 0.0:
            continue  # omit completely-missing fields to keep output clean
        serialised_fields[name] = {
            "value":       ef.value,
            "confidence":  round(ef.confidence, 4),
            "source_page": ef.source_page,
            "low_confidence": ef.low_confidence,
        }

    return {
        "file":        raw.filename,
        "source_zip":  raw.source_zip,
        "processed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "summary":     summary.get("paragraph", ""),
        "summary_bullets": summary.get("bullets", []),
        "fields":      serialised_fields,
        "low_confidence_fields": low_conf,
        "tables_extracted": len(doc.all_tables),
        "pages":       len(doc.pages),
    }


def _error_result(raw: RawContent, error: str) -> dict:
    """Return an error placeholder result for a file that failed to process."""
    return {
        "file":        raw.filename,
        "source_zip":  raw.source_zip,
        "processed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "summary":     "",
        "summary_bullets": [],
        "fields":      {},
        "low_confidence_fields": [],
        "tables_extracted": 0,
        "pages":       0,
        "error":       error[:500],
    }


def _make_table_row(result: dict) -> dict:
    """Extract terminal-table columns from a result dict."""
    fields   = result.get("fields", {})
    found    = sum(1 for f in fields.values() if f.get("value") is not None)
    confs    = [f["confidence"] for f in fields.values() if f.get("value") is not None]
    avg_conf = round(sum(confs) / len(confs), 2) if confs else 0.0
    return {
        "File":   result["file"],
        "Type":   Path(result["file"]).suffix.lstrip(".").upper(),
        "Fields Found": found,
        "Avg Confidence": avg_conf,
        "Low Confidence": ", ".join(result.get("low_confidence_fields", [])[:3]) or "—",
        "Status": "ERROR" if result.get("error") else "OK",
    }


def _print_rich_table(rows: list[dict]) -> None:
    """Print a Rich terminal table of processing results."""
    try:
        from rich.console import Console
        from rich.table import Table

        console = Console()
        table = Table(title="Tender Extraction Results", show_lines=True)
        cols = ["File", "Type", "Fields Found", "Avg Confidence", "Low Confidence", "Status"]
        for col in cols:
            table.add_column(col, overflow="fold")

        for row in rows:
            status = row["Status"]
            style = "red" if status == "ERROR" else "green"
            table.add_row(
                str(row.get("File", "")),
                str(row.get("Type", "")),
                str(row.get("Fields Found", "")),
                str(row.get("Avg Confidence", "")),
                str(row.get("Low Confidence", "")),
                f"[{style}]{status}[/{style}]",
            )
        console.print(table)
    except Exception as e:
        log.warning("pipeline.rich_table_error", extra={"error": str(e)})
        # Plain fallback
        header = " | ".join(["File", "Type", "Fields", "AvgConf", "Status"])
        print(header)
        for row in rows:
            print(f"{row['File']} | {row['Type']} | {row['Fields Found']} | {row['Avg Confidence']} | {row['Status']}")


def _write_csv(all_results: list[dict], path: Path) -> None:
    """Write a flat CSV summary from all results."""
    flat_rows = []
    for r in all_results:
        flat = {
            "file":       r["file"],
            "source_zip": r.get("source_zip") or "",
            "pages":      r.get("pages", 0),
            "tables":     r.get("tables_extracted", 0),
            "status":     "ERROR" if r.get("error") else "OK",
        }
        for fname, fdata in r.get("fields", {}).items():
            val = fdata.get("value")
            flat[fname] = json.dumps(val) if isinstance(val, (dict, list)) else str(val or "")
        flat_rows.append(flat)

    if not flat_rows:
        return

    all_keys = list(dict.fromkeys(k for row in flat_rows for k in row))
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=all_keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(flat_rows)


def _load_config() -> dict:
    """Load patterns.yaml once and cache."""
    if not hasattr(_load_config, "_cache"):
        with open(_PATTERNS_PATH, encoding="utf-8") as fh:
            _load_config._cache = yaml.safe_load(fh)  # type: ignore[attr-defined]
    return _load_config._cache  # type: ignore[attr-defined]


def _print_verbose(filename: str, fields: dict[str, ExtractedField]) -> None:
    """Print per-field extraction details to stdout when --verbose is set."""
    print(f"\n{'─'*60}")
    print(f"  {filename}")
    print(f"{'─'*60}")
    for name, ef in fields.items():
        if ef.value is None:
            continue
        val_display = str(ef.value)[:60]
        low = " [LOW]" if ef.low_confidence else ""
        print(f"  {name:<25} {ef.confidence:.2f}  {val_display}{low}")
