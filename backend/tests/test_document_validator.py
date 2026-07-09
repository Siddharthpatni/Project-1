"""Tests for app.phase1_llm_scraper.document_validator."""
from __future__ import annotations

import os

# pyrefly: ignore [missing-import]

from app.phase1_llm_scraper.document_validator import (
    is_document_url,
    is_real_document_file,
)


# ---------------------------------------------------------------------------
# is_real_document_file — local file validation
# ---------------------------------------------------------------------------

class TestIsRealDocumentFile:
    """Validates downloaded files by content, magic bytes, and extension."""

    def test_empty_file_rejected(self, tmp_path):
        p = tmp_path / "foo.pdf"
        p.write_bytes(b"")
        ok, reason = is_real_document_file(str(p))
        assert ok is False
        assert reason == "too_small"

    def test_tiny_file_rejected(self, tmp_path):
        p = tmp_path / "foo.pdf"
        p.write_bytes(b"x" * 100)
        ok, reason = is_real_document_file(str(p))
        assert ok is False
        assert reason == "too_small"

    def test_html_doctype_rejected(self, tmp_path):
        p = tmp_path / "foo.pdf"
        p.write_bytes(b"<!DOCTYPE html>" + b"x" * 500)
        ok, reason = is_real_document_file(str(p))
        assert ok is False
        assert reason == "html_content"

    def test_html_tag_rejected(self, tmp_path):
        p = tmp_path / "download.bin"
        p.write_bytes(b"<html><head><title>Error</title></head>" + b"x" * 500)
        ok, reason = is_real_document_file(str(p))
        assert ok is False
        assert reason == "html_content"

    def test_html_extension_rejected(self, tmp_path):
        p = tmp_path / "foo.html"
        p.write_bytes(b"x" * 500)
        ok, reason = is_real_document_file(str(p))
        assert ok is False
        assert reason == "html_extension"

    def test_htm_extension_rejected(self, tmp_path):
        p = tmp_path / "page.htm"
        p.write_bytes(b"x" * 500)
        ok, reason = is_real_document_file(str(p))
        assert ok is False
        assert reason == "html_extension"

    def test_pdf_accepted(self, tmp_path):
        p = tmp_path / "foo.pdf"
        p.write_bytes(b"%PDF-1.4\n" + b"\x00" * 500)
        ok, reason = is_real_document_file(str(p))
        assert ok is True
        assert reason == "pdf"

    def test_zip_accepted(self, tmp_path):
        p = tmp_path / "foo.zip"
        p.write_bytes(b"PK\x03\x04" + b"\x00" * 500)
        ok, reason = is_real_document_file(str(p))
        assert ok is True
        assert reason == "zip_or_ooxml"

    def test_ole_office_accepted(self, tmp_path):
        p = tmp_path / "report.doc"
        p.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 500)
        ok, reason = is_real_document_file(str(p))
        assert ok is True
        assert reason == "ms_office_ole"

    def test_7z_accepted(self, tmp_path):
        p = tmp_path / "archive.7z"
        p.write_bytes(b"7z\xbc\xaf\x27\x1c" + b"\x00" * 500)
        ok, reason = is_real_document_file(str(p))
        assert ok is True
        assert reason == "7z"

    def test_rar_accepted(self, tmp_path):
        p = tmp_path / "archive.rar"
        p.write_bytes(b"Rar!\x1a\x07" + b"\x00" * 500)
        ok, reason = is_real_document_file(str(p))
        assert ok is True
        assert reason == "rar"

    def test_random_bin_rejected(self, tmp_path):
        # Use bytes that definitely don't start with any known magic number
        data = b"\x01\x02\x03\x04\x05\x06\x07\x08" + os.urandom(492)
        p = tmp_path / "foo.bin"
        p.write_bytes(data)
        ok, reason = is_real_document_file(str(p))
        assert ok is False
        assert reason == "unknown_content"

    def test_txt_accepted(self, tmp_path):
        p = tmp_path / "foo.txt"
        p.write_bytes(b"Tender notice\nDate: 2026-01-15" + b" " * 200)
        ok, reason = is_real_document_file(str(p))
        assert ok is True
        assert reason == "extension_text_ok"

    def test_csv_accepted(self, tmp_path):
        p = tmp_path / "data.csv"
        p.write_bytes(b"col1,col2,col3\nval1,val2,val3\n" + b"x," * 200)
        ok, reason = is_real_document_file(str(p))
        assert ok is True
        assert reason == "extension_text_ok"

    def test_nonexistent_file(self, tmp_path):
        ok, reason = is_real_document_file(str(tmp_path / "nope.pdf"))
        assert ok is False
        assert reason == "too_small"

    def test_login_page_rejected(self, tmp_path):
        p = tmp_path / "download.bin"
        content = b"<html><head><title>Login Required</title></head><body>" + b"x" * 500
        p.write_bytes(content)
        ok, reason = is_real_document_file(str(p))
        assert ok is False
        assert reason == "html_content"

    def test_german_error_page_rejected(self, tmp_path):
        p = tmp_path / "download.bin"
        content = b"<html><head><title>Fehler aufgetreten</title></head>" + b"x" * 500
        p.write_bytes(content)
        ok, reason = is_real_document_file(str(p))
        assert ok is False
        assert reason == "html_content"


# ---------------------------------------------------------------------------
# is_document_url — URL-level validation (pattern-only, no network)
# ---------------------------------------------------------------------------

class TestIsDocumentUrl:
    """Smoke tests for URL pattern matching — no live HTTP calls."""

    def test_download_tender_pattern_trusted(self):
        url = "https://example.de/api/_DownloadTenderDocuments?id=123"
        assert is_document_url(url) is True

    def test_wicket_zip_button_trusted(self):
        url = "https://evergabe-online.de/page?zipDownloadButton=true"
        assert is_document_url(url) is True

    def test_html_extension_rejected(self):
        url = "https://example.de/tenderdetails.html?id=999"
        assert is_document_url(url) is False

    def test_pdf_extension_trusted(self):
        url = "https://portal.de/docs/tender_notice.pdf"
        assert is_document_url(url) is True

    def test_zip_extension_trusted(self):
        url = "https://portal.de/download/vergabe.zip"
        assert is_document_url(url) is True

    def test_docx_extension_trusted(self):
        url = "https://portal.de/attachments/specification.docx"
        assert is_document_url(url) is True

    def test_download_all_pattern_trusted(self):
        url = "https://example.de/_DownloadAll?project=ABC"
        assert is_document_url(url) is True

    def test_direct_docload_pattern_trusted(self):
        url = "https://example.de/DirectDocload/file123"
        assert is_document_url(url) is True
