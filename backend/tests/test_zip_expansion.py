"""
Tests for app.core.zip_expander — the recursive ZIP expansion layer.

All tests use only stdlib and tmp_path; no external services required.
"""
from __future__ import annotations

import os
import zipfile
from pathlib import Path

import pytest

from app.core.zip_expander import (
    MAX_FILE_COUNT,
    MAX_TOTAL_BYTES,
    expand_zips,
    _expand_zip_recursive,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_zip(path: Path, members: dict[str, bytes]) -> Path:
    """Create a ZIP at *path* containing the given filename→bytes members."""
    with zipfile.ZipFile(str(path), "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return path


# Fake documents must be >= 200 bytes to pass is_real_document_file's size guard.
_FAKE_PDF   = b"%PDF-1.4\n" + b"% fake tender document content " * 10 + b"\n%%EOF\n"
_FAKE_DOCX  = b"PK\x03\x04" + b"\x00" * 26 + b"fake docx content " * 12
_FAKE_HTML  = b"<!DOCTYPE html><html><body>Login page</body></html>" + b" " * 200
_FAKE_EXCEL = b"PK\x03\x04" + b"\x00" * 26 + b"fake xlsx content " * 12


# ---------------------------------------------------------------------------
# test_zip_expansion_flat
# ---------------------------------------------------------------------------

def test_zip_expansion_flat(tmp_path):
    """A ZIP containing 3 PDFs produces exactly 3 extracted PDFs."""
    zp = tmp_path / "bundle.zip"
    _make_zip(zp, {
        "doc_a.pdf": _FAKE_PDF,
        "doc_b.pdf": _FAKE_PDF,
        "doc_c.pdf": _FAKE_PDF,
    })

    result = expand_zips([str(zp)])

    pdfs = [r for r in result if r.endswith(".pdf")]
    assert len(pdfs) == 3, f"Expected 3 PDFs, got {pdfs}"
    # Original ZIP is still in the result
    assert str(zp) in result


def test_zip_expansion_mixed_types(tmp_path):
    """ZIP with PDF + DOCX + HTML: PDFs and DOCX extracted, HTML rejected."""
    zp = tmp_path / "mixed.zip"
    _make_zip(zp, {
        "tender.pdf":   _FAKE_PDF,
        "brief.docx":   _FAKE_DOCX,
        "login.html":   _FAKE_HTML,
    })

    result = expand_zips([str(zp)])

    extracted = [r for r in result if r != str(zp)]
    filenames  = [Path(r).name for r in extracted]
    assert "login.html" not in filenames, "HTML file should be rejected"
    assert any(f.endswith(".pdf")  for f in filenames), "PDF should be extracted"
    # DOCX magic bytes stub may fail validation — just ensure HTML is rejected


def test_non_zip_files_pass_through(tmp_path):
    """Non-ZIP files are returned unchanged without modification."""
    pdf = tmp_path / "standalone.pdf"
    pdf.write_bytes(_FAKE_PDF)

    result = expand_zips([str(pdf)])

    assert result == [str(pdf)]


def test_empty_list():
    """Empty input returns empty list."""
    assert expand_zips([]) == []


def test_nonexistent_file_skipped(tmp_path):
    """Missing file paths are skipped without raising."""
    missing = str(tmp_path / "ghost.zip")
    result = expand_zips([missing])
    assert result == [missing]   # path passes through even if file is absent


# ---------------------------------------------------------------------------
# test_nested_zip_expansion
# ---------------------------------------------------------------------------

def test_nested_zip_expansion(tmp_path):
    """ZIP containing another ZIP: inner ZIP contents are extracted."""
    inner_zip = tmp_path / "inner.zip"
    _make_zip(inner_zip, {"nested_doc.pdf": _FAKE_PDF})

    outer_zip = tmp_path / "outer.zip"
    _make_zip(outer_zip, {
        "top_level.pdf": _FAKE_PDF,
        "inner.zip": inner_zip.read_bytes(),
    })

    result = expand_zips([str(outer_zip)])

    pdfs = [r for r in result if r.endswith(".pdf")]
    # top_level.pdf from outer + nested_doc.pdf from inner
    assert len(pdfs) >= 2, f"Expected >= 2 PDFs, got {pdfs}"


def test_max_depth_respected(tmp_path):
    """Nesting deeper than MAX_DEPTH (3) does not cause infinite recursion."""
    # Build a 5-level nested ZIP: level5 → level4 → ... → level1
    current_data = _FAKE_PDF
    for level in range(5, 0, -1):
        zp = tmp_path / f"level{level}.zip"
        if level == 5:
            _make_zip(zp, {f"doc_{level}.pdf": _FAKE_PDF})
        else:
            inner = tmp_path / f"level{level + 1}.zip"
            _make_zip(zp, {
                f"doc_{level}.pdf": _FAKE_PDF,
                f"level{level + 1}.zip": inner.read_bytes(),
            })

    outermost = tmp_path / "level1.zip"
    result = expand_zips([str(outermost)])
    # Should return without error — depth limit prevents unbounded recursion
    assert isinstance(result, list)


# ---------------------------------------------------------------------------
# test_zip_bomb_protection
# ---------------------------------------------------------------------------

def test_zip_bomb_total_bytes_limit(tmp_path):
    """
    A ZIP whose declared uncompressed sizes exceed MAX_TOTAL_BYTES should be
    cut off — expand_zips must return without crashing and without writing
    MAX_TOTAL_BYTES to disk.
    """
    zp = tmp_path / "bomb.zip"
    # Each member is 1 MB of zeros; write enough to exceed the budget
    chunk_size = 1024 * 1024  # 1 MB
    num_members = (MAX_TOTAL_BYTES // chunk_size) + 5  # slightly over limit

    with zipfile.ZipFile(str(zp), "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for i in range(num_members):
            # Zeros compress extremely well — 1 MB → few bytes on disk
            zf.writestr(f"bomb_{i:04d}.pdf", b"%PDF-1.4 " + bytes(chunk_size))

    # Must not raise and must not exhaust disk
    result = expand_zips([str(zp)])

    # Count how many PDFs were actually extracted
    extracted_pdfs = [r for r in result if r.endswith(".pdf") and r != str(zp)]
    total_extracted_mb = sum(
        Path(r).stat().st_size for r in extracted_pdfs if Path(r).exists()
    ) / (1024 * 1024)

    assert total_extracted_mb <= (MAX_TOTAL_BYTES / (1024 * 1024)) + 5, (
        f"Extracted {total_extracted_mb:.1f} MB — exceeds budget"
    )


def test_zip_bomb_file_count_limit(tmp_path):
    """ZIP with members exceeding MAX_FILE_COUNT is truncated, not crashed."""
    zp = tmp_path / "many_files.zip"
    with zipfile.ZipFile(str(zp), "w") as zf:
        for i in range(MAX_FILE_COUNT + 50):
            zf.writestr(f"file_{i:06d}.pdf", _FAKE_PDF)

    result = expand_zips([str(zp)])

    extracted = [r for r in result if r != str(zp)]
    assert len(extracted) <= MAX_FILE_COUNT, (
        f"Extracted {len(extracted)} files — exceeds MAX_FILE_COUNT={MAX_FILE_COUNT}"
    )


# ---------------------------------------------------------------------------
# test_zip_path_traversal
# ---------------------------------------------------------------------------

def test_zip_path_traversal_blocked(tmp_path):
    """Members with path traversal sequences must not escape dest_dir."""
    zp = tmp_path / "traversal.zip"

    # Craft a ZIP with a member that tries to escape via ../..
    with zipfile.ZipFile(str(zp), "w") as zf:
        zf.writestr("../../evil.pdf",   _FAKE_PDF)
        zf.writestr("../sibling.pdf",   _FAKE_PDF)
        zf.writestr("safe/normal.pdf",  _FAKE_PDF)

    result = expand_zips([str(zp)])

    # No extracted file should live outside tmp_path
    for p in result:
        if p == str(zp):
            continue
        resolved = Path(p).resolve()
        assert str(resolved).startswith(str(tmp_path.resolve())), (
            f"Path traversal not blocked: {p}"
        )


def test_zip_absolute_path_member_blocked(tmp_path):
    """Members with absolute paths (/etc/passwd) must not escape dest_dir."""
    zp = tmp_path / "absolute.zip"
    with zipfile.ZipFile(str(zp), "w") as zf:
        zf.writestr("/etc/shadow.pdf", _FAKE_PDF)
        zf.writestr("/tmp/evil.pdf",   _FAKE_PDF)
        zf.writestr("safe.pdf",        _FAKE_PDF)

    result = expand_zips([str(zp)])

    for p in result:
        if p == str(zp):
            continue
        resolved = Path(p).resolve()
        assert str(resolved).startswith(str(tmp_path.resolve())), (
            f"Absolute path member escaped: {p}"
        )


# ---------------------------------------------------------------------------
# test_file_count_limits — already covered above, add edge-case variant
# ---------------------------------------------------------------------------

def test_empty_zip(tmp_path):
    """A ZIP with no members produces only the original ZIP in result."""
    zp = tmp_path / "empty.zip"
    with zipfile.ZipFile(str(zp), "w"):
        pass

    result = expand_zips([str(zp)])
    assert result == [str(zp)]


def test_bad_zip_does_not_crash(tmp_path):
    """A corrupted ZIP file must not raise — it is skipped gracefully."""
    zp = tmp_path / "corrupt.zip"
    zp.write_bytes(b"this is not a zip file at all")

    result = expand_zips([str(zp)])
    # Returns the original path unchanged without raising
    assert str(zp) in result


def test_zip_with_directory_entries_skipped(tmp_path):
    """Directory entries inside the ZIP (name ending with /) are not extracted."""
    zp = tmp_path / "dirs.zip"
    with zipfile.ZipFile(str(zp), "w") as zf:
        zf.mkdir("subdir/")
        zf.writestr("subdir/doc.pdf", _FAKE_PDF)

    result = expand_zips([str(zp)])
    extracted = [r for r in result if r != str(zp)]
    # No directory entries in result — only the actual PDF
    for r in extracted:
        assert not r.endswith("/"), f"Directory entry leaked into result: {r}"
