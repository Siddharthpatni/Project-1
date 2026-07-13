"""
Self-correcting feedback loop that iteratively generates, validates,
executes, and regenerates a scraper until it succeeds or budgets are exhausted.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import time
import urllib.parse
from dataclasses import dataclass, field
import requests
import google.generativeai as genai

from open_scraper_sdk.sandbox import SandboxResult, run_script
from open_scraper_sdk.validator import validate
from open_scraper_sdk.evaluator import EvaluationMetrics, evaluate
from open_scraper_sdk.prompts import (
    SYSTEM_PROMPT,
    build_generation_prompt,
    build_feedback_prompt,
)

_CODE_FENCE = re.compile(r"```(?:python)?\s*(.*?)```", re.DOTALL)


@dataclass
class GeneratedScraper:
    code: str
    model: str
    raw_response: str


@dataclass
class LoopResult:
    success: bool
    final_scraper: GeneratedScraper | None = None
    final_output: dict | None = None
    metrics: EvaluationMetrics | None = None
    iterations: int = 0
    history: list[dict] = field(default_factory=list)


class ScraperGenerator:
    """Helper to coordinate LLM calls for scraper generation and regeneration."""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        genai.configure(api_key=self.api_key)
        self.model_name = "gemini-1.5-flash"

    def generate(
        self,
        url: str,
        schema_json: str,
        html_snippet: str,
        additional_prompt: str = ""
    ) -> GeneratedScraper:
        model = genai.GenerativeModel(self.model_name)
        domain = urllib.parse.urlparse(url).netloc
        
        user_msg = build_generation_prompt(
            url=url,
            domain=domain,
            schema_json=schema_json,
            html_snippet=html_snippet,
            additional_prompt=additional_prompt
        )
        
        response = model.generate_content(
            contents=[SYSTEM_PROMPT, user_msg]
        )
        
        code = self._parse_code(response.text)
        return GeneratedScraper(code=code, model=self.model_name, raw_response=response.text)

    def regenerate(
        self,
        url: str,
        iteration: int,
        max_iterations: int,
        outcome: str,
        error: str,
        downloaded: int,
    ) -> GeneratedScraper:
        model = genai.GenerativeModel(self.model_name)
        
        user_msg = build_feedback_prompt(
            iteration=iteration,
            max_iterations=max_iterations,
            url=url,
            outcome=outcome,
            error=error,
            downloaded=downloaded
        )
        
        response = model.generate_content(
            contents=[SYSTEM_PROMPT, user_msg]
        )
        
        code = self._parse_code(response.text)
        return GeneratedScraper(code=code, model=self.model_name, raw_response=response.text)

    def _parse_code(self, text: str) -> str:
        match = _CODE_FENCE.search(text)
        if match:
            return match.group(1).strip()
        return text.strip()


# Wrapper code template used to invoke the generated scraper's `scrape` function
# within the isolated subprocess sandbox and write the output safely to a file.
_RUNNER_TEMPLATE = '''
import json, sys, traceback
sys.path.insert(0, {workdir!r})
from scraper import scrape

try:
    result = scrape({url!r}, {output_dir!r})
    if not isinstance(result, dict):
        result = {{"error": "Scrape function must return a dictionary", "ok": False}}
    else:
        result["ok"] = True
except Exception as e:
    result = {{"ok": False, "error": str(e), "traceback": traceback.format_exc()}}

with open({result_path!r}, "w") as f:
    json.dump(result, f)
'''


def _fetch_html_snippet(url: str) -> str:
    """Fetch a lightweight HTML snippet to give structural context to the LLM."""
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        }
        r = requests.get(url, headers=headers, timeout=10)
        return r.text[:15000]
    except Exception as e:
        return f"<!-- Snippet fetch failed: {e} -->"


def run_feedback_loop(
    url: str,
    gemini_api_key: str,
    schema_json: str,
    additional_prompt: str = "",
    max_iterations: int = 3,
    timeout_seconds: int = 45,
    memory_mb: int = 512,
) -> LoopResult:
    """
    Executes the self-correcting generation & sandboxing retry loop.
    Generates → Validates → Executes → Evaluates → Regenerates upon error.
    """
    generator = ScraperGenerator(gemini_api_key)
    html_snippet = _fetch_html_snippet(url)
    
    loop_result = LoopResult(success=False)
    
    scraper: GeneratedScraper | None = None
    sandbox_res: SandboxResult | None = None
    metrics: EvaluationMetrics | None = None
    parsed_output: dict | None = None

    for i in range(1, max_iterations + 1):
        loop_result.iterations = i
        print(f"[Feedback Loop] Iteration {i} of {max_iterations}...")

        # 1. Code Generation/Regeneration
        if scraper is None:
            scraper = generator.generate(
                url=url,
                schema_json=schema_json,
                html_snippet=html_snippet,
                additional_prompt=additional_prompt
            )
        else:
            outcome = "execution_failed"
            error_details = ""
            if sandbox_res:
                error_details = sandbox_res.stderr or sandbox_res.stdout or "unknown runtime error"
                if parsed_output and "error" in parsed_output:
                    error_details += f"\nScraper reported error: {parsed_output['error']}"
                    if "traceback" in parsed_output:
                        error_details += f"\nTraceback: {parsed_output['traceback']}"
            
            scraper = generator.regenerate(
                url=url,
                iteration=i,
                max_iterations=max_iterations,
                outcome=outcome,
                error=error_details,
                downloaded=metrics.downloaded_count if metrics else 0
            )

        # 2. AST Security Validation
        validation = validate(scraper.code)
        if not validation.ok:
            print(f"[Feedback Loop] AST Validation failed in iteration {i}: {validation.errors}")
            sandbox_res = SandboxResult(
                returncode=-2,
                stdout="",
                stderr=f"AST Static Validation Failed: {'; '.join(validation.errors)}",
                elapsed=0.0
            )
            loop_result.history.append({
                "iteration": i,
                "stage": "validation",
                "ok": False,
                "errors": validation.errors
            })
            continue

        # 3. isolated Sandboxed Execution
        with tempfile.TemporaryDirectory(prefix="scraper-sandbox-") as workdir:
            work = os.path.abspath(workdir)
            
            # Write generated script to scraper.py
            with open(os.path.join(work, "scraper.py"), "w") as f:
                f.write(scraper.code)
                
            result_path = os.path.join(work, "result.json")
            output_dir = os.path.join(work, "downloads")
            os.makedirs(output_dir, exist_ok=True)

            runner_code = _RUNNER_TEMPLATE.format(
                workdir=work,
                url=url,
                output_dir=output_dir,
                result_path=result_path
            )
            
            runner_path = os.path.join(work, "_runner.py")
            with open(runner_path, "w") as f:
                f.write(runner_code)

            # Spawn subprocess
            sandbox_res = run_script(
                script_path=runner_path,
                workdir=work,
                timeout=timeout_seconds,
                memory_mb=memory_mb
            )

            # 4. Parse execution results
            parsed_output = None
            if os.path.exists(result_path):
                try:
                    with open(result_path) as f:
                        parsed_output = json.load(f)
                except Exception as e:
                    sandbox_res.stderr += f"\nFailed to parse runner output: {e}"

        # 5. Evaluate Outcomes
        metrics = evaluate(sandbox_res, parsed_output)
        loop_result.history.append({
            "iteration": i,
            "stage": "execution",
            "success": metrics.success,
            "runtime": metrics.runtime_seconds,
            "has_data": metrics.has_data,
            "downloaded": metrics.downloaded_count
        })

        if metrics.success:
            print(f"[Feedback Loop] Successful scraper generated and executed on iteration {i}!")
            loop_result.success = True
            loop_result.final_scraper = scraper
            loop_result.final_output = parsed_output
            loop_result.metrics = metrics
            break

    # If loop ended and we didn't succeed, return best effort metrics
    if not loop_result.success:
        loop_result.final_scraper = scraper
        loop_result.final_output = parsed_output
        loop_result.metrics = metrics

    return loop_result
