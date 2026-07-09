"""
Test-runner API endpoint.

POST /api/tests/run   → run the pytest suite (or a named sub-suite)
                        and return structured results.

The test process is spawned as a subprocess so FastAPI/Celery workers
are never affected by test-suite imports or state. A 120-second timeout
prevents a hung test from blocking the API indefinitely.

Supported suites
----------------
  all        : backend/tests/ (everything)
  phase1     : tests/test_phase1.py
  phase2     : tests/test_phase2.py
  phase3     : tests/test_phase3.py
  platform   : tests/test_platform_classifier.py
  document   : tests/test_document_validator.py
  route      : tests/test_route_and_deterministic.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

from fastapi import APIRouter

from app.schemas import TestCaseResult, TestRunRequest, TestRunResult
from app.utils.logger import get_logger

log = get_logger(__name__)
router = APIRouter()

_TESTS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "tests")

_SUITE_PATHS: dict[str, str] = {
    "all":      "tests/",
    "phase1":   "tests/test_phase1.py",
    "phase2":   "tests/test_phase2.py",
    "phase3":   "tests/test_phase3.py",
    "platform": "tests/test_platform_classifier.py",
    "document": "tests/test_document_validator.py",
    "route":    "tests/test_route_and_deterministic.py",
}


@router.post("/run", response_model=TestRunResult)
def run_tests(payload: TestRunRequest):
    suite = payload.suite if payload.suite in _SUITE_PATHS else "all"
    target = _SUITE_PATHS[suite]

    log.info("tests.run_started", suite=suite, target=target)
    t0 = time.time()

    try:
        result = subprocess.run(
            [
                sys.executable, "-m", "pytest",
                target,
                "--tb=short",
                "--no-header",
                "-q",
                "--json-report",
                "--json-report-file=/tmp/pytest_report.json",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            cwd="/app",
        )
        raw_output = (result.stdout + result.stderr)[:8000]
    except subprocess.TimeoutExpired:
        return TestRunResult(
            suite=suite, total=0, passed=0, failed=0, errors=1, skipped=0,
            duration_seconds=time.time() - t0,
            cases=[],
            raw_output="pytest timed out after 120 seconds",
        )
    except Exception as e:
        return TestRunResult(
            suite=suite, total=0, passed=0, failed=0, errors=1, skipped=0,
            duration_seconds=time.time() - t0,
            cases=[],
            raw_output=f"Failed to spawn pytest: {e}",
        )

    duration = time.time() - t0
    cases: list[TestCaseResult] = []

    # Parse the JSON report if available
    try:
        with open("/tmp/pytest_report.json") as f:
            report = json.load(f)
        for t in report.get("tests", []):
            cases.append(TestCaseResult(
                name=t.get("nodeid", "unknown").split("::")[-1],
                status=t.get("outcome", "unknown"),
                duration_ms=round(t.get("call", {}).get("duration", 0) * 1000, 1),
                error=(
                    (t.get("call") or {}).get("longrepr") or
                    (t.get("setup") or {}).get("longrepr")
                ),
            ))
        summary = report.get("summary", {})
        return TestRunResult(
            suite=suite,
            total=summary.get("total", len(cases)),
            passed=summary.get("passed", 0),
            failed=summary.get("failed", 0),
            errors=summary.get("error", 0),
            skipped=summary.get("skipped", 0),
            duration_seconds=duration,
            cases=cases,
            raw_output=raw_output,
        )
    except Exception:
        # Fallback: parse the plain text output
        passed = raw_output.count(" passed")
        failed = raw_output.count(" failed")
        return TestRunResult(
            suite=suite,
            total=passed + failed,
            passed=passed,
            failed=failed,
            errors=0,
            skipped=0,
            duration_seconds=duration,
            cases=[],
            raw_output=raw_output,
        )
