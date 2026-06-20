"""
ZIP Handler — recursively extracts archives and routes files to the right extractor.

Algorithm:
  1. Accept a single file (PDF/DOCX/XLSX/ZIP) or a folder path as input.
  2. If ZIP: extract to a temp directory, recurse into any nested ZIPs (up to MAX_DEPTH).
  3. For each file found, classify by extension and return a RawContent object.
  4. Unsupported extensions are logged and skipped — they never raise.
  5. Returns a flat list of RawContent objects regardless of archive nesting.
"""
from __future__ import annotations

import logging
import os
import tempfile
import zipfile
from pathlib import Path

from tender_extractor.models import RawContent

log = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS: dict[str, str] = {
    ".pdf":  "pdf",
    ".docx": "docx",
    ".doc":  "docx",
    ".xlsx": "xlsx",
    ".xls":  "xlsx",
    ".txt":  "txt",
    ".xml":  "txt",
}

MAX_DEPTH = 4              # maximum ZIP-in-ZIP nesting depth
MAX_FILES = 500            # safety cap
MAX_UNZIPPED_MB = 500      # bomb protection — total uncompressed size


def collect_files(input_path: str) -> list[RawContent]:
    """
    Entry point.  Accepts a path to a file or folder and returns a flat list
    of RawContent objects ready for extraction.
    """
    p = Path(input_path)
    if not p.exists():
        raise FileNotFoundError(f"Input not found: {input_path}")

    if p.is_dir():
        return _collect_from_folder(str(p))

    suffix = p.suffix.lower()
    if suffix == ".zip":
        return _collect_from_zip(str(p), source_zip=str(p), depth=0, budget={"files": 0, "bytes": 0})

    file_type = SUPPORTED_EXTENSIONS.get(suffix, "other")
    if file_type == "other":
        log.warning("zip_handler.unsupported_extension", extra={"file": str(p), "ext": suffix})
        return []

    return [RawContent(
        filename=p.name,
        source_zip=None,
        file_type=file_type,
        filepath=str(p),
        size_bytes=p.stat().st_size,
    )]


def _collect_from_folder(folder: str) -> list[RawContent]:
    """Walk a directory tree and collect all supported files."""
    results: list[RawContent] = []
    for root, _, files in os.walk(folder):
        for fname in sorted(files):
            fpath = Path(root) / fname
            suffix = fpath.suffix.lower()
            if suffix == ".zip":
                try:
                    results.extend(
                        _collect_from_zip(
                            str(fpath), source_zip=str(fpath),
                            depth=0, budget={"files": 0, "bytes": 0},
                        )
                    )
                except Exception as e:
                    log.warning("zip_handler.folder_zip_error", extra={"file": str(fpath), "error": str(e)})
            elif suffix in SUPPORTED_EXTENSIONS:
                results.append(RawContent(
                    filename=fpath.name,
                    source_zip=None,
                    file_type=SUPPORTED_EXTENSIONS[suffix],
                    filepath=str(fpath),
                    size_bytes=fpath.stat().st_size,
                ))
            else:
                log.debug("zip_handler.skip_unsupported", extra={"file": fname, "reason": f"extension {suffix} not supported"})
    return results


def _collect_from_zip(
    zip_path: str,
    source_zip: str,
    depth: int,
    budget: dict,
) -> list[RawContent]:
    """
    Recursively extract a ZIP file.
    Uses a shared budget dict to track total files and bytes across all levels.
    """
    if depth >= MAX_DEPTH:
        log.warning("zip_handler.max_depth_reached", extra={"zip": zip_path})
        return []

    results: list[RawContent] = []
    tmp_dir = tempfile.mkdtemp(prefix="tender_extractor_")

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for info in zf.infolist():
                if info.filename.endswith("/"):
                    continue

                # Bomb protection
                budget["bytes"] += info.file_size
                if budget["bytes"] > MAX_UNZIPPED_MB * 1024 * 1024:
                    log.warning("zip_handler.size_budget_exceeded", extra={"zip": zip_path})
                    break

                budget["files"] += 1
                if budget["files"] > MAX_FILES:
                    log.warning("zip_handler.file_count_exceeded", extra={"zip": zip_path})
                    break

                # Safe extraction — prevent path traversal
                safe_name = _safe_member_name(info.filename)
                dest = Path(tmp_dir) / safe_name
                dest.parent.mkdir(parents=True, exist_ok=True)

                try:
                    data = zf.read(info.filename)
                    dest.write_bytes(data)
                except Exception as e:
                    log.warning("zip_handler.read_error", extra={"member": info.filename, "error": str(e)})
                    continue

                suffix = dest.suffix.lower()
                if suffix == ".zip":
                    results.extend(
                        _collect_from_zip(str(dest), source_zip=source_zip, depth=depth + 1, budget=budget)
                    )
                elif suffix in SUPPORTED_EXTENSIONS:
                    results.append(RawContent(
                        filename=Path(info.filename).name,
                        source_zip=source_zip,
                        file_type=SUPPORTED_EXTENSIONS[suffix],
                        filepath=str(dest),
                        size_bytes=len(data),
                    ))
                else:
                    log.debug("zip_handler.skip_member", extra={
                        "member": info.filename,
                        "reason": f"extension {suffix} not supported",
                    })

    except zipfile.BadZipFile as e:
        log.warning("zip_handler.bad_zip", extra={"zip": zip_path, "error": str(e)})
    except Exception as e:
        log.error("zip_handler.error", extra={"zip": zip_path, "error": str(e)})

    return results


def _safe_member_name(name: str) -> str:
    """Strip path traversal sequences from ZIP member names."""
    name = name.replace("\\", "/")
    parts = [p for p in name.split("/") if p and p != ".."]
    return "/".join(parts) or "extracted_file"
