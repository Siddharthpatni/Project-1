"""
Shared dataclasses and ABCs — defined by the Architect.
All other modules import from here. Nothing instantiates until interfaces are agreed.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


# ── Raw input ──────────────────────────────────────────────────────────────

@dataclass
class RawContent:
    """One file extracted from a ZIP or read directly from disk."""
    filename: str               # original basename
    source_zip: str | None      # parent ZIP path, or None if read directly
    file_type: str              # "pdf" | "docx" | "xlsx" | "txt" | "other"
    filepath: str               # absolute path to the temp/extracted file
    size_bytes: int = 0


# ── Extracted document ─────────────────────────────────────────────────────

@dataclass
class PageContent:
    page_num: int
    text: str
    lines: list[str]

@dataclass
class TableContent:
    page_num: int | None
    section_header: str | None
    headers: list[str]
    rows: list[dict[str, str]]
    layout: str = "data_table"   # "data_table" | "key_value"

@dataclass
class DocumentContent:
    """Unified output of any extractor (PDF / DOCX / XLSX)."""
    filename: str
    file_type: str
    pages: list[PageContent]
    full_text: str
    all_tables: list[TableContent]
    metadata: dict[str, Any]
    sections_index: dict[str, int]   # section_name → page_num
    sheets: list[dict] | None = None  # XLSX only


# ── Field extraction ───────────────────────────────────────────────────────

@dataclass
class ExtractedField:
    """
    One extracted field with its provenance.

    confidence:
      1.0 = label matched + value passed validation regex
      0.8 = label matched + value extracted, no strict validation
      0.5 = standalone regex match, no label found
      0.2 = fallback / heuristic guess — flag for manual review
      0.0 = not found
    """
    value: Any                    # str | dict | list | None
    confidence: float             # 0.0 – 1.0
    source_page: int | None = None
    source_line: int | None = None
    raw_text: str | None = None
    low_confidence: bool = False


# ── Final output ───────────────────────────────────────────────────────────

@dataclass
class ExtractionResult:
    """Final per-document result written to JSON."""
    file: str
    source_zip: str | None
    processed_at: str
    summary: str
    summary_bullets: list[str]
    fields: dict[str, ExtractedField]
    low_confidence_fields: list[str]
    tables_extracted: int
    pages: int
    error: str | None = None


# ── Extractor ABC ──────────────────────────────────────────────────────────

class BaseExtractor(ABC):
    """All file-type extractors implement this interface."""

    @abstractmethod
    def extract(self, filepath: str) -> DocumentContent:
        """
        Extract all content from the given file.
        Returns a unified DocumentContent regardless of file type.
        Must never raise — catch and log internally, return partial content.
        """
