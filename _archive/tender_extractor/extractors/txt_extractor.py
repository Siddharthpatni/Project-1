"""
TXT Extractor — plain text file support.

Algorithm:
  Read the file as UTF-8 (with fallback to latin-1), split into lines,
  detect any section headers using the same heuristics as pdf_extractor,
  and return a unified DocumentContent.
"""
from __future__ import annotations

import logging
from pathlib import Path

from tender_extractor.models import BaseExtractor, DocumentContent, PageContent

log = logging.getLogger(__name__)


class TXTExtractor(BaseExtractor):
    """Wraps a plain-text file into a DocumentContent for downstream parsing."""

    def extract(self, filepath: str) -> DocumentContent:
        """
        Read the file, split into lines, detect section headers,
        and return as a single-page DocumentContent.
        """
        try:
            text = Path(filepath).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                text = Path(filepath).read_text(encoding="latin-1")
            except Exception as e:
                log.error("txt_extractor.read_error", extra={"file": filepath, "error": str(e)})
                return _empty(filepath)
        except Exception as e:
            log.error("txt_extractor.open_error", extra={"file": filepath, "error": str(e)})
            return _empty(filepath)

        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        sections_index: dict[str, int] = {}

        import re
        for ln in lines:
            stripped = ln.strip()
            if not stripped or len(stripped) < 3:
                continue
            words = re.sub(r"[^a-zA-Z\s]", "", stripped).split()
            if (len(words) >= 2 and all(w.isupper() for w in words if len(w) > 1)) or \
               re.match(r"^\d+(\.\d+)*[\s\.]", stripped) or \
               (len(stripped) < 60 and stripped.endswith(":")):
                key = stripped.lower()[:40]
                if key not in sections_index:
                    sections_index[key] = 1

        return DocumentContent(
            filename=Path(filepath).name,
            file_type="txt",
            pages=[PageContent(page_num=1, text=text, lines=lines)],
            full_text=text,
            all_tables=[],
            metadata={"num_lines": len(lines)},
            sections_index=sections_index,
        )


def _empty(filepath: str) -> DocumentContent:
    return DocumentContent(
        filename=Path(filepath).name,
        file_type="txt",
        pages=[],
        full_text="",
        all_tables=[],
        metadata={},
        sections_index={},
    )
