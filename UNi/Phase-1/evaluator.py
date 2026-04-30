#!/usr/bin/env python3
"""
Phase-1 : Scraper Evaluator  (Standalone)
=========================================

What does this script do?
-------------------------
This is the final judge of Phase 1. It compares the actual execution results 
of the LLM-generated scrapers against your manual annotations (the "spreadsheet").

It strictly adheres to Checklist Rule #6: "The spreadsheet is the source of truth."

It calculates:
  - Overall Success Rate (did the scraper run without crashing?)
  - Document Recall (how many documents were downloaded vs. expected?)
  - Cost & Runtime metrics
  - A "Flagged for Review" list (URLs where expected docs != downloaded docs)

Usage
-----
    # Run the evaluation against your spreadsheet and pipeline results:
    python evaluator.py evaluate ground_truth.csv pipeline_results.jsonl

    # Save the flagged URLs to a separate file for human review:
    python evaluator.py evaluate ground_truth.csv pipeline_results.jsonl --export-flags flagged.csv

Input Formats
-------------
1. ground_truth.csv
   Must have a header. Must contain at least 'url' and 'expected_docs'.
   Example:
     url,expected_docs
     https://example.com/tenders/1,3
     https://example.com/tenders/2,0

2. pipeline_results.jsonl
   A JSON Lines file where each line is the combined output of the Generator 
   and Executor for a single URL.
   Example JSON line:
     {"url": "https://example.com/tenders/1", "success": true, "downloaded_count": 3, "runtime_seconds": 12.5, "cost_usd": 0.002}
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from textwrap import dedent

# ═══════════════════════════════════════════════════════════════════════════════
#  SECTION 0 :  Configuration
# ═══════════════════════════════════════════════════════════════════════════════

def _load_dotenv():
    """Loads .env file just to maintain architecture consistency across Phase 1."""
    possible_locations = [
        Path(__file__).parent / ".env",
        Path.cwd() / ".env",
    ]
    for env_file in possible_locations:
        if env_file.is_file():
            for line in env_file.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
            break

_load_dotenv()

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    level=getattr(logging, LOG_LEVEL, logging.INFO),
)
log = logging.getLogger("phase1.evaluator")

# ═══════════════════════════════════════════════════════════════════════════════
#  SECTION 1 :  Data Structures
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class GroundTruthRecord:
    url: str
    expected_docs: int

@dataclass
class PipelineResultRecord:
    url: str
    success: bool
    downloaded_count: int
    runtime_seconds: float
    cost_usd: float
    error: str | None = None

@dataclass
class FlaggedURL:
    url: str
    expected: int
    downloaded: int
    reason: str

@dataclass
class EvaluationReport:
    total_urls: int = 0
    successful_executions: int = 0
    total_expected_docs: int = 0
    total_downloaded_docs: int = 0
    total_cost_usd: float = 0.0
    total_runtime_seconds: float = 0.0
    flagged_urls: list[FlaggedURL] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        if self.total_urls == 0: return 0.0
        return (self.successful_executions / self.total_urls) * 100

    @property
    def document_recall(self) -> float:
        if self.total_expected_docs == 0: return 100.0 if self.total_downloaded_docs == 0 else 0.0
        # Cap recall at 100% in case it downloaded more than expected (which is still a flag)
        recall = (self.total_downloaded_docs / self.total_expected_docs) * 100
        return min(recall, 100.0)

# ═══════════════════════════════════════════════════════════════════════════════
#  SECTION 2 :  Evaluation Logic
# ═══════════════════════════════════════════════════════════════════════════════

def load_ground_truth(csv_path: Path) -> dict[str, GroundTruthRecord]:
    """Reads manual annotations from a CSV file into a dictionary keyed by URL."""
    truth_map = {}
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row_idx, row in enumerate(reader, start=2):
            url = row.get("url", "").strip()
            try:
                expected = int(row.get("expected_docs", 0))
            except ValueError:
                log.warning("Row %d: Invalid expected_docs for %s. Defaulting to 0.", row_idx, url)
                expected = 0
            
            if url:
                truth_map[url] = GroundTruthRecord(url=url, expected_docs=expected)
    
    log.info("Loaded %d manual annotations from %s", len(truth_map), csv_path.name)
    return truth_map

def load_pipeline_results(jsonl_path: Path) -> list[PipelineResultRecord]:
    """Reads execution results from a JSON Lines file."""
    results = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            results.append(PipelineResultRecord(
                url=data.get("url", ""),
                success=data.get("success", False),
                downloaded_count=data.get("downloaded_count", 0),
                runtime_seconds=data.get("runtime_seconds", 0.0),
                cost_usd=data.get("cost_usd", 0.0),
                error=data.get("error")
            ))
    log.info("Loaded %d execution results from %s", len(results), jsonl_path.name)
    return results

def evaluate(truth_map: dict[str, GroundTruthRecord], results: list[PipelineResultRecord]) -> EvaluationReport:
    """Compares the pipeline runs against the ground truth spreadsheet."""
    report = EvaluationReport()
    
    for res in results:
        report.total_urls += 1
        report.total_cost_usd += res.cost_usd
        report.total_runtime_seconds += res.runtime_seconds
        
        if res.success:
            report.successful_executions += 1
            
        truth = truth_map.get(res.url)
        if not truth:
            log.warning("URL executed but missing from ground truth spreadsheet: %s", res.url)
            report.flagged_urls.append(FlaggedURL(
                url=res.url, expected=-1, downloaded=res.downloaded_count, reason="Missing in Spreadsheet"
            ))
            continue

        report.total_expected_docs += truth.expected_docs
        
        # Only count downloaded docs up to the expected amount for pure recall calculation, 
        # but we track the raw number for flagging.
        if res.success:
            report.total_downloaded_docs += min(res.downloaded_count, truth.expected_docs)

        # CHECKLIST #6: Flag mismatches for human review
        if not res.success:
            report.flagged_urls.append(FlaggedURL(
                url=res.url, expected=truth.expected_docs, downloaded=0, reason=f"Execution Failed: {res.error}"
            ))
        elif res.downloaded_count != truth.expected_docs:
            reason = "Over-downloaded" if res.downloaded_count > truth.expected_docs else "Under-downloaded"
            report.flagged_urls.append(FlaggedURL(
                url=res.url, expected=truth.expected_docs, downloaded=res.downloaded_count, reason=reason
            ))

    return report

# ═══════════════════════════════════════════════════════════════════════════════
#  SECTION 3 :  CLI  (Command-Line Interface)
# ═══════════════════════════════════════════════════════════════════════════════

def _print_evaluation_report(report: EvaluationReport, export_flags_path: str | None = None):
    """Pretty-print the final metrics."""
    print(f"\n{'═'*60}")
    print(f"  VERGABEPILOT.AI - PHASE 1 EVALUATION REPORT")
    print(f"{'═'*60}")
    print(f"  Total URLs Evaluated:   {report.total_urls}")
    print(f"  Successful Executions:  {report.successful_executions} ({report.success_rate:.1f}%)")
    print(f"  Document Recall:        {report.document_recall:.1f}% ({report.total_downloaded_docs} / {report.total_expected_docs} expected)")
    print(f"  Total API Cost:         ${report.total_cost_usd:.4f}")
    print(f"  Total Runtime:          {report.total_runtime_seconds:.1f}s")
    print(f"  Flagged for Review:     {len(report.flagged_urls)}")
    print(f"{'═'*60}\n")

    if report.flagged_urls:
        print("── Top 5 Flagged URLs ──")
        for f in report.flagged_urls[:5]:
            print(f"  ⚠ {f.reason}: Expected {f.expected}, Got {f.downloaded} -> {f.url}")
        
        if len(report.flagged_urls) > 5:
            print(f"  ... and {len(report.flagged_urls) - 5} more.")
        print()

    if export_flags_path and report.flagged_urls:
        path = Path(export_flags_path)
        with open(path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["url", "expected", "downloaded", "reason"])
            for flag in report.flagged_urls:
                writer.writerow([flag.url, flag.expected, flag.downloaded, flag.reason])
        log.info("Exported flagged URLs for human review to: %s", path.name)

def cmd_evaluate(args: argparse.Namespace):
    """Run the evaluation sequence."""
    truth_path = Path(args.truth)
    results_path = Path(args.results)

    if not truth_path.is_file():
        log.error("Ground truth CSV not found: %s", truth_path)
        sys.exit(1)
    if not results_path.is_file():
        log.error("Pipeline results JSONL not found: %s", results_path)
        sys.exit(1)

    log.info("Step 1/3: Loading manual spreadsheet annotations...")
    truth_map = load_ground_truth(truth_path)

    log.info("Step 2/3: Loading pipeline execution results...")
    results = load_pipeline_results(results_path)

    log.info("Step 3/3: Evaluating results against source of truth...")
    report = evaluate(truth_map, results)

    _print_evaluation_report(report, export_flags_path=args.export_flags)
    
    # Exit with 1 if there are flags, which is useful if running in CI/CD pipelines
    sys.exit(1 if report.flagged_urls else 0)

def main():
    parser = argparse.ArgumentParser(
        description="Phase-1 Scraper Evaluator — Standalone",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=dedent("""\
            Examples:
              # Run evaluation:
              python evaluator.py evaluate annotations.csv run_results.jsonl
              
              # Run evaluation and save flagged URLs:
              python evaluator.py evaluate annotations.csv run_results.jsonl --export-flags flagged_urls.csv
        """),
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    p_eval = subcommands.add_parser("evaluate", help="Compare execution results against the spreadsheet")
    p_eval.add_argument("truth", help="Path to the manual annotations CSV (must have 'url' and 'expected_docs')")
    p_eval.add_argument("results", help="Path to the pipeline execution results (.jsonl)")
    p_eval.add_argument("--export-flags", "-e", default=None, help="Save flagged URLs to this CSV file for human review")

    args = parser.parse_args()
    
    if args.command == "evaluate":
        cmd_evaluate(args)

if __name__ == "__main__":
    main()