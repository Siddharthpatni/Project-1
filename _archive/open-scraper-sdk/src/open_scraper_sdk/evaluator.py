"""
Evaluation metrics for generic web scraping.
"""
from __future__ import annotations
from dataclasses import dataclass
from open_scraper_sdk.sandbox import SandboxResult


@dataclass
class EvaluationMetrics:
    success: bool
    runtime_seconds: float
    error_message: str | None = None
    has_data: bool = False
    downloaded_count: int = 0


def evaluate(sandbox_result: SandboxResult, scraper_output: dict | None) -> EvaluationMetrics:
    """
    Evaluate the scraper run.
    Checks if execution succeeded and returned structured keys or saved files.
    """
    success = sandbox_result.returncode == 0
    error_message = sandbox_result.stderr if not success else None
    
    has_data = False
    downloaded_count = 0

    if scraper_output:
        # Check if they returned items
        non_empty_keys = [k for k, v in scraper_output.items() if v]
        if non_empty_keys:
            has_data = True
        
        # Check if they downloaded files
        downloaded = scraper_output.get("downloaded_files")
        if isinstance(downloaded, list):
            downloaded_count = len(downloaded)

    # Success conditions:
    # 1. Sandbox execution return code must be 0 (no runtime error)
    # 2. Output must not be completely empty
    final_success = success and has_data

    return EvaluationMetrics(
        success=final_success,
        runtime_seconds=sandbox_result.elapsed,
        error_message=error_message,
        has_data=has_data,
        downloaded_count=downloaded_count
    )
