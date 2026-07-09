"""
Robust ZIP expansion for the download pipeline.

Many German procurement portals deliver all tender documents as a single ZIP
archive. This module expands ZIPs (recursively, up to MAX_DEPTH levels) so
every contained file is surfaced as an individual download — PDFs, DOCX, XLSX,
GAEB/X81/X83, etc. — rather than being buried inside an opaque blob.

Design goals
------------
* Format-agnostic: works for any ZIP regardless of which portal produced it.
* Recursive: nested ZIPs (ZIP-in-ZIP) are expanded up to MAX_DEPTH levels.
* Safe: guards against ZIP bombs via MAX_TOTAL_BYTES and MAX_FILE_COUNT.
* Non-destructive: original ZIP is kept alongside the extracted files so the
  caller can still serve it as a "download all" artifact.
* Zero external dependencies: uses stdlib zipfile only.

Integration
-----------
Called from phase3_integration.pipeline after files land in the scratch dir
and before _persist_documents writes to S3. The caller passes the current list
of paths; expand_zips returns an augmented list that also contains every valid
document extracted from any ZIPs found.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

from app.phase1_llm_scraper.document_validator import is_real_document_file
from app.utils.logger import get_logger

log = get_logger(__name__)

# Safety limits
MAX_DEPTH        = 3          # maximum nesting level for ZIP-in-ZIP
MAX_FILE_COUNT   = 500        # max number of files extracted across all ZIPs in one job
MAX_TOTAL_BYTES  = 500 * 1024 * 1024   # 500 MB total uncompressed
MAX_SINGLE_BYTES = 200 * 1024 * 1024   # 200 MB per individual file

# File extensions we want to keep from inside ZIPs
_KEEP_EXTENSIONS = frozenset({
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".odt", ".ods", ".txt", ".csv",
    ".gaeb", ".x81", ".x83", ".d83", ".d84",
    ".zip",   # kept so nested ZIPs can be re-expanded at next depth
    ".rar", ".7z",
    ".xml", ".json",
})

# Extensions to always skip (signatures, thumbs, system files)
_SKIP_EXTENSIONS = frozenset({
    ".lnk", ".url",
    ".exe", ".dll", ".bat", ".sh", ".js", ".vbs",
})

# OS junk identified by basename, not extension — Path("Thumbs.db").suffix is
# ".db" and Path(".DS_Store").suffix is "", so an extension set can't catch them.
_SKIP_BASENAMES = frozenset({"thumbs.db", ".ds_store", "desktop.ini"})


def _safe_extract_name(member_name: str, dest_dir: Path, depth: int, index: int) -> Path:
    """
    Build a safe destination path for a ZIP member.

    Prevents path traversal (../../etc/passwd tricks) by stripping leading
    slashes and collapsing '..' components. Also flattens directory separators
    into underscores for the top-level so all extracted files land in dest_dir
    directly — no nested subdirectory creation.
    """
    # Normalise platform path separators
    safe = member_name.replace("\\", "/")
    # Strip leading slashes / drive letters
    while safe.startswith(("/", "..")):
        safe = safe.lstrip("/").lstrip(".")
    # Replace internal directory separators with underscores to avoid creating
    # subdirectories (keeps the output flat and prevents traversal).
    safe = safe.replace("/", "__").replace("..", "_")
    if not safe:
        safe = f"extracted_{depth}_{index}.bin"
    return dest_dir / safe


class _BudgetExceeded(Exception):
    pass


def _expand_one(
    zip_path: Path,
    dest_dir: Path,
    depth: int,
    budget: dict,   # mutable shared state: {"files": int, "bytes": int}
) -> list[Path]:
    """
    Extract valid documents from a single ZIP into dest_dir.
    Returns the list of extracted file paths (not the ZIP itself).
    """
    extracted: list[Path] = []

    try:
        with zipfile.ZipFile(str(zip_path), "r") as zf:
            members = zf.infolist()
            for idx, info in enumerate(members):
                # Skip directories
                if info.filename.endswith("/") or info.file_size == 0:
                    continue

                ext = Path(info.filename).suffix.lower()
                base = Path(info.filename.replace("\\", "/")).name.lower()

                # Skip OS junk and junk extensions entirely
                if base in _SKIP_BASENAMES or "__macosx" in info.filename.lower():
                    continue
                if ext in _SKIP_EXTENSIONS:
                    continue

                # Only extract known-useful extensions (or no extension)
                if ext and ext not in _KEEP_EXTENSIONS:
                    log.debug("zip_expander.skip_unknown_ext", name=info.filename, ext=ext)
                    continue

                # Per-file size guard
                if info.file_size > MAX_SINGLE_BYTES:
                    log.warning(
                        "zip_expander.file_too_large",
                        name=info.filename,
                        size_mb=round(info.file_size / 1_048_576, 1),
                    )
                    continue

                # Total bytes guard (bomb protection)
                budget["bytes"] += info.file_size
                if budget["bytes"] > MAX_TOTAL_BYTES:
                    log.warning("zip_expander.total_size_budget_exceeded", zip=str(zip_path))
                    raise _BudgetExceeded()

                # Total file count guard
                budget["files"] += 1
                if budget["files"] > MAX_FILE_COUNT:
                    log.warning("zip_expander.file_count_budget_exceeded", zip=str(zip_path))
                    raise _BudgetExceeded()

                dest_path = _safe_extract_name(info.filename, dest_dir, depth, idx)

                # Avoid overwriting if the same name appears in multiple ZIPs
                if dest_path.exists():
                    stem, suffix = dest_path.stem, dest_path.suffix
                    dest_path = dest_dir / f"{stem}__{idx}{suffix}"

                try:
                    data = zf.read(info.filename)
                    dest_path.write_bytes(data)
                except Exception as e:  # noqa: BLE001
                    log.warning("zip_expander.read_error", name=info.filename, error=str(e))
                    continue

                # Validate the extracted file.
                # ZIP files use magic-byte check only — they may legitimately
                # be small (e.g. a nested archive with few tiny files) and the
                # 200-byte size guard in is_real_document_file would reject them.
                if ext == ".zip":
                    header = dest_path.read_bytes()[:4]
                    if header != b"PK\x03\x04":
                        log.debug("zip_expander.rejected_invalid_zip", name=info.filename)
                        dest_path.unlink(missing_ok=True)
                        budget["files"] -= 1
                        budget["bytes"] -= info.file_size
                        continue
                else:
                    ok, reason = is_real_document_file(str(dest_path))
                    if not ok:
                        log.debug("zip_expander.rejected", name=info.filename, reason=reason)
                        dest_path.unlink(missing_ok=True)
                        budget["files"] -= 1
                        budget["bytes"] -= info.file_size
                        continue

                extracted.append(dest_path)
                log.debug("zip_expander.extracted", name=info.filename, dest=str(dest_path))

    except zipfile.BadZipFile:
        log.warning("zip_expander.bad_zip", path=str(zip_path))
    except _BudgetExceeded:
        pass  # already logged above
    except Exception as e:  # noqa: BLE001
        log.warning("zip_expander.error", path=str(zip_path), error=str(e))

    return extracted


def expand_zips(file_paths: list[str]) -> list[str]:
    """
    Given a list of downloaded file paths, expand any ZIPs found and return
    the augmented list (original non-ZIP files + all extracted document files).

    The original ZIP files are retained in the returned list so they can still
    be served as "download all" artifacts. Extracted files land next to the ZIP
    in the same directory.

    This function is idempotent — calling it twice on the same list is safe.
    """
    if not file_paths:
        return file_paths

    result: list[str] = []
    seen: set[str] = set()
    budget: dict = {"files": 0, "bytes": 0}

    def _add(p: str) -> None:
        if p not in seen:
            seen.add(p)
            result.append(p)

    for path_str in file_paths:
        _add(path_str)
        p = Path(path_str)
        if not p.is_file():
            continue
        if p.suffix.lower() != ".zip":
            continue

        # Expand this ZIP into the same directory
        dest_dir = p.parent
        extracted = _expand_zip_recursive(p, dest_dir, depth=0, budget=budget)

        added = 0
        for ep in extracted:
            if ep.suffix.lower() != ".zip":   # don't re-add intermediate nested ZIPs
                _add(str(ep))
                added += 1

        if added:
            log.info(
                "zip_expander.expanded",
                zip=p.name,
                files_extracted=added,
                total_budget_files=budget["files"],
            )

    return result


def _expand_zip_recursive(
    zip_path: Path,
    dest_dir: Path,
    depth: int,
    budget: dict,
) -> list[Path]:
    """Recursively expand a ZIP and any nested ZIPs, up to MAX_DEPTH."""
    if depth >= MAX_DEPTH:
        return []

    extracted = _expand_one(zip_path, dest_dir, depth, budget)
    all_files = list(extracted)

    # Recurse into any nested ZIPs we just extracted
    for ep in extracted:
        if ep.suffix.lower() == ".zip":
            nested = _expand_zip_recursive(ep, dest_dir, depth + 1, budget)
            all_files.extend(nested)

    return all_files
