"""Unit tests for Phase 1 — focused on the pieces that don't need a real LLM."""
from app.phase1_llm_scraper.evaluator import GroundTruth, evaluate
from app.phase1_llm_scraper.executor import ExecutionResult
from app.phase1_llm_scraper.validator import validate


# ---------- validator ----------

def test_validator_accepts_minimal_scraper():
    code = """
from playwright.sync_api import sync_playwright

def scrape(url, output_dir):
    return []
"""
    result = validate(code)
    assert result.ok
    assert result.errors == []


def test_validator_rejects_subprocess():
    code = """
import subprocess

def scrape(url, output_dir):
    subprocess.run(["ls"])
    return []
"""
    result = validate(code)
    assert not result.ok
    assert any("subprocess" in e for e in result.errors)


def test_validator_rejects_eval():
    code = """
def scrape(url, output_dir):
    eval("1+1")
    return []
"""
    result = validate(code)
    assert not result.ok
    assert any("eval" in e for e in result.errors)


def test_validator_requires_scrape_function():
    code = "def other(): pass"
    result = validate(code)
    assert not result.ok
    assert any("scrape" in e for e in result.errors)


# ---------- evaluator ----------

def test_evaluator_success_case():
    truth = GroundTruth(url="https://x", expected_doc_count=2, expected_extensions=["pdf"])
    result = ExecutionResult(success=True, downloaded_files=["/tmp/a.pdf", "/tmp/b.pdf"], runtime_seconds=1.0)
    m = evaluate(truth, result)
    assert m.success
    assert m.recall == 1.0
    assert m.downloaded_count == 2


def test_evaluator_failure_when_nothing_downloaded():
    truth = GroundTruth(url="https://x", expected_doc_count=5, expected_extensions=["pdf"])
    result = ExecutionResult(success=True, downloaded_files=[], runtime_seconds=1.0)
    m = evaluate(truth, result)
    assert not m.success
    assert m.recall == 0.0


def test_evaluator_partial_recall():
    truth = GroundTruth(url="https://x", expected_doc_count=4, expected_extensions=["pdf"])
    result = ExecutionResult(success=True, downloaded_files=["/tmp/a.pdf", "/tmp/b.pdf"], runtime_seconds=1.0)
    m = evaluate(truth, result)
    assert m.recall == 0.5
    # 0.5 recall counts as success per the current threshold
    assert m.success
