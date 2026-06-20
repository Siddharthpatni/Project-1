"""
QA Engineer — pytest test suite for the Tender Extractor system.

Covers:
  - test_date_parser     : all date format variants + failure paths
  - test_value_parser    : currency + multiplier variants
  - test_field_parser    : same-line, next-line, standalone-regex, not-found
  - test_rule_summarizer : all-fields, partial-fields, all-None
  - test_pipeline_integration : full synthetic pipeline run
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure the package root is on the path when run directly
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest

from tender_extractor.parsers.date_parser  import parse_date
from tender_extractor.parsers.value_parser import parse_value


# ══════════════════════════════════════════════════════════════════════════════
# DATE PARSER
# ══════════════════════════════════════════════════════════════════════════════

class TestDateParser:
    """Verify date normalisation to ISO 8601."""

    def test_dd_mm_yyyy_slash(self):
        result = parse_date("15/03/2025")
        assert result is not None
        assert result["value"] == "2025-03-15"
        assert result["low_confidence"] is False

    def test_written_date_dmy(self):
        result = parse_date("15 March 2025")
        assert result is not None
        assert result["value"] == "2025-03-15"
        assert result["low_confidence"] is False

    def test_written_date_mdy(self):
        result = parse_date("March 15, 2025")
        assert result is not None
        assert result["value"] == "2025-03-15"
        assert result["low_confidence"] is False

    def test_dd_mm_yy_dots(self):
        result = parse_date("15.03.25")
        assert result is not None
        assert result["value"] == "2025-03-15"
        assert result["low_confidence"] is False

    def test_dd_mon_yy(self):
        result = parse_date("15-Mar-25")
        assert result is not None
        assert result["value"] == "2025-03-15"
        assert result["low_confidence"] is False

    def test_iso_passthrough(self):
        result = parse_date("2025-03-15")
        assert result is not None
        assert result["value"] == "2025-03-15"
        assert result["low_confidence"] is False

    def test_garbage_text_returns_raw(self):
        result = parse_date("garbage text")
        assert result is not None
        assert result["value"] == "garbage text"
        assert result["low_confidence"] is True

    def test_empty_string_returns_none(self):
        result = parse_date("")
        assert result is None

    def test_none_input_returns_none(self):
        result = parse_date(None)
        assert result is None


# ══════════════════════════════════════════════════════════════════════════════
# VALUE PARSER
# ══════════════════════════════════════════════════════════════════════════════

class TestValueParser:
    """Verify currency extraction and amount normalisation."""

    def test_eur_code_with_commas(self):
        result = parse_value("EUR 1,500,000")
        assert result is not None
        assert result["amount"] == 1_500_000
        assert result["currency"] == "EUR"

    def test_million_suffix_usd(self):
        result = parse_value("1.5M USD")
        assert result is not None
        assert result["amount"] == 1_500_000
        assert result["currency"] == "USD"

    def test_dollar_symbol_decimal(self):
        result = parse_value("$250,000.00")
        assert result is not None
        assert result["amount"] == 250_000
        assert result["currency"] == "USD"

    def test_rupee_lakhs(self):
        result = parse_value("Rs. 45 Lakhs")
        assert result is not None
        assert result["amount"] == 4_500_000
        assert result["currency"] == "INR"

    def test_euro_symbol_crores(self):
        result = parse_value("€ 2 Crores")
        assert result is not None
        assert result["amount"] == 20_000_000
        assert result["currency"] == "EUR"

    def test_gbp_simple(self):
        result = parse_value("GBP 999")
        assert result is not None
        assert result["amount"] == 999
        assert result["currency"] == "GBP"


# ══════════════════════════════════════════════════════════════════════════════
# FIELD PARSER
# ══════════════════════════════════════════════════════════════════════════════

class TestFieldParser:
    """Verify proximity-search extraction with confidence scoring."""

    def _run(self, text: str, field_name: str = "tender_id"):
        """Helper: build a minimal DocumentContent and extract one field."""
        from tender_extractor.models import DocumentContent, PageContent
        from tender_extractor.parsers.field_parser import extract_all_fields

        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        doc = DocumentContent(
            filename="test.txt",
            file_type="txt",
            pages=[PageContent(page_num=1, text=text, lines=lines)],
            full_text=text,
            all_tables=[],
            metadata={},
            sections_index={},
        )
        fields = extract_all_fields(doc)
        return fields.get(field_name)

    def test_label_same_line_high_confidence(self):
        ef = self._run("Tender No: RFP-2025-001")
        assert ef is not None
        assert ef.value is not None
        assert "RFP-2025-001" in str(ef.value)
        assert ef.confidence >= 0.9

    def test_label_next_line(self):
        ef = self._run("Reference No\nRFP-2025-001")
        assert ef is not None
        assert ef.value is not None
        assert "RFP-2025-001" in str(ef.value)
        assert ef.confidence >= 0.8

    def test_standalone_regex_confidence(self):
        # No label, but the tender ID pattern should match standalone
        ef = self._run("The document relates to RFP-2025-099 for procurement.")
        assert ef is not None
        if ef.value is not None:
            assert ef.confidence <= 0.8  # standalone ≤ 0.8

    def test_not_found_returns_none(self):
        ef = self._run("This document has no reference number at all.")
        # Either None value or very low confidence
        assert ef is None or ef.value is None or ef.confidence <= 0.5

    def test_email_extraction(self):
        ef = self._run("Contact email: procurement@ministry.gov.uk", "contact_email")
        assert ef is not None
        assert ef.value is not None
        assert "@" in str(ef.value)
        assert ef.confidence >= 0.9

    def test_deadline_extraction(self):
        ef = self._run("Submission deadline: 15/06/2025", "submission_deadline")
        assert ef is not None
        assert ef.value is not None


# ══════════════════════════════════════════════════════════════════════════════
# RULE SUMMARIZER
# ══════════════════════════════════════════════════════════════════════════════

class TestRuleSummarizer:
    """Verify template-based summary generation."""

    def _fields(self, **overrides):
        """Build a minimal fields dict with ExtractedField objects."""
        from tender_extractor.models import ExtractedField

        defaults = {
            "tender_type":       ExtractedField(value="Open",                   confidence=0.9),
            "issuing_authority": ExtractedField(value="Ministry of Finance",    confidence=0.9),
            "tender_title":      ExtractedField(value="Supply of IT Equipment", confidence=0.9),
            "tender_id":         ExtractedField(value="RFP-2025-042",           confidence=0.9),
            "publication_date":  ExtractedField(value="2025-01-01",             confidence=0.9),
            "submission_deadline": ExtractedField(value="2025-03-15",           confidence=0.9),
            "tender_value":      ExtractedField(
                                     value={"amount": 500_000, "currency": "EUR"},
                                     confidence=0.85,
                                 ),
            "contact_email":     ExtractedField(value="procurement@ministry.gov", confidence=1.0),
        }
        defaults.update(overrides)
        return defaults

    def test_all_fields_produces_paragraph_and_bullets(self):
        from tender_extractor.summarizer.rule_summarizer import generate_summary

        fields = self._fields()
        result = generate_summary(fields, "test.pdf")
        assert result["paragraph"] and len(result["paragraph"]) > 20
        assert len(result["bullets"]) > 0

    def test_half_fields_no_na_placeholder(self):
        from tender_extractor.models import ExtractedField
        from tender_extractor.summarizer.rule_summarizer import generate_summary

        fields = self._fields(
            tender_type=ExtractedField(value=None, confidence=0.0),
            issuing_authority=ExtractedField(value=None, confidence=0.0),
            tender_value=ExtractedField(value=None, confidence=0.0),
        )
        result = generate_summary(fields, "test.pdf")
        assert "N/A" not in result["paragraph"]
        assert all("N/A" not in b for b in result["bullets"])

    def test_all_fields_none_no_crash(self):
        from tender_extractor.models import ExtractedField
        from tender_extractor.summarizer.rule_summarizer import generate_summary

        fields = {
            name: ExtractedField(value=None, confidence=0.0)
            for name in [
                "tender_type", "issuing_authority", "tender_title", "tender_id",
                "publication_date", "submission_deadline", "tender_value",
                "contact_email", "contact_name", "contact_phone",
                "scope_of_work", "eligibility", "cpv_codes",
            ]
        }
        result = generate_summary(fields, "empty.pdf")
        assert isinstance(result["paragraph"], str)
        assert isinstance(result["bullets"], list)


# ══════════════════════════════════════════════════════════════════════════════
# PIPELINE INTEGRATION
# ══════════════════════════════════════════════════════════════════════════════

class TestPipelineIntegration:
    """End-to-end synthetic pipeline test."""

    _SYNTHETIC_TEXT = """
    OPEN TENDER FOR SUPPLY OF IT EQUIPMENT

    Tender No: RFP-2025-042
    Issued by: Ministry of Finance, Government of Exampleland
    Publication date: 01/01/2025
    Submission deadline: 15/03/2025
    Estimated value: EUR 500,000
    CPV Code: 30200000
    Contact email: procurement@ministry.gov.example

    SCOPE OF WORK
    The contractor shall supply and install 200 desktop computers and associated
    peripherals as per the technical specification annexed hereto.

    ELIGIBILITY
    - Registered company with minimum 5 years experience
    - Minimum annual turnover of EUR 1,000,000
    """

    def _run_pipeline(self, tmp_path):
        """Write synthetic text to a temp PDF-like .txt, run pipeline, return results."""
        import json

        # We use a .txt file routed through the pipeline's txt handler
        # (the pipeline falls through to raw text when file_type == "txt")
        input_file = tmp_path / "synthetic_tender.txt"
        input_file.write_text(self._SYNTHETIC_TEXT, encoding="utf-8")

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        from tender_extractor.pipeline import process_batch
        results = process_batch(
            input_path=str(input_file),
            output_dir=str(output_dir),
            file_format="json",
            verbose=False,
        )
        return results

    def test_result_has_required_top_level_keys(self, tmp_path):
        results = self._run_pipeline(tmp_path)
        assert len(results) >= 1
        r = results[0]
        required_keys = {"file", "source_zip", "processed_at", "summary",
                         "summary_bullets", "fields", "low_confidence_fields",
                         "tables_extracted", "pages"}
        assert required_keys.issubset(set(r.keys()))

    def test_confidence_scores_in_range(self, tmp_path):
        results = self._run_pipeline(tmp_path)
        for r in results:
            for fname, fdata in r.get("fields", {}).items():
                conf = fdata.get("confidence", 0.0)
                assert 0.0 <= conf <= 1.0, f"Field {fname} confidence {conf} out of range"

    def test_date_fields_iso_format(self, tmp_path):
        import re
        results = self._run_pipeline(tmp_path)
        iso_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}$")
        for r in results:
            for fname in ("publication_date", "submission_deadline"):
                fdata = r.get("fields", {}).get(fname)
                if fdata and fdata.get("value"):
                    val = fdata["value"]
                    if isinstance(val, str) and len(val) == 10:
                        assert iso_pattern.match(val), \
                            f"Date field {fname} value '{val}' is not ISO 8601"

    def test_no_crash_on_empty_input(self, tmp_path):
        input_file = tmp_path / "empty.txt"
        input_file.write_text("", encoding="utf-8")
        output_dir = tmp_path / "output_empty"
        output_dir.mkdir()

        from tender_extractor.pipeline import process_batch
        # Should not raise; empty file returns result with no fields
        results = process_batch(str(input_file), str(output_dir))
        assert isinstance(results, list)
