"""
Feedback loop that iteratively regenerates a scraper until it works or
the iteration budget is exhausted. This is the entry point Phase 1 and
Phase 3 both call into.

Each iteration we:
  1. Generate (or regenerate) Python source.
  2. Statically validate it (AST-walk for forbidden constructs).
  3. Execute it inside the subprocess sandbox.
  4. Evaluate the result against ground truth (or a permissive default).
  5. If we still don't have what we want, feed the diagnostics back
     into the generator and try again.

Files downloaded by failed iterations are cleaned up so disk doesn't
grow unboundedly. Files from the successful iteration are kept and the
caller is responsible for moving them into S3.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.config import settings
from app.core.llm_client import LLMClient
from app.phase1_llm_scraper.evaluator import (
    EvaluationMetrics,
    GroundTruth,
    evaluate,
)
from app.phase1_llm_scraper.executor import (
    ExecutionResult,
    cleanup_output_dir,
    execute,
)
from app.phase1_llm_scraper.generator import GeneratedScraper, ScraperGenerator
from app.phase1_llm_scraper.validator import validate
from app.utils.logger import get_logger

log = get_logger(__name__)


@dataclass
class LoopResult:
    final_scraper: GeneratedScraper | None
    final_execution: ExecutionResult | None
    metrics: EvaluationMetrics | None
    iterations: int
    total_cost_usd: float = 0.0
    history: list[dict] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return bool(self.metrics and self.metrics.success)


async def run_feedback_loop(
    url: str,
    llm: LLMClient,
    ground_truth: GroundTruth | None = None,
    model: str | None = None,
    max_iterations: int | None = None,
    route_map=None,           # phase1_llm_scraper.route_learner.RouteMap | None
    platform: str | None = None,
    html_snippet: str | None = None,
    cua_hint: str | None = None,
) -> LoopResult:
    """Generate → validate → execute → evaluate → retry until success.

    Optional ``route_map`` (from `route_learner.learn_route`) is passed to
    the generator on the FIRST iteration to give the LLM a verified click
    sequence. Optional ``platform`` (from `platform_classifier`) splices
    domain-specific guidance into the prompt. Optional ``html_snippet``
    lets the caller pass a pre-fetched page to avoid a second HTTP fetch.
    """
    max_iter = max_iterations or settings.max_feedback_iterations
    generator = ScraperGenerator(llm)

    truth = ground_truth or GroundTruth(url=url, expected_doc_count=0, expected_extensions=[])
    loop = LoopResult(final_scraper=None, final_execution=None, metrics=None, iterations=0)

    scraper: GeneratedScraper | None = None
    exec_result: ExecutionResult | None = None
    metrics: EvaluationMetrics | None = None
    success_output_dir: str | None = None

    for i in range(1, max_iter + 1):
        loop.iterations = i
        log.info("phase1.loop.iteration", url=url, iteration=i, model=model)

        # 1. Generate or regenerate
        if scraper is None:
            scraper = await generator.generate(
                url, model=model, route_map=route_map, platform=platform,
                html_snippet=html_snippet,  # skip re-fetch if caller supplied it
                cua_hint=cua_hint,
            )
        else:
            outcome = (
                "execution_failed"
                if (not exec_result or not exec_result.success)
                else "insufficient_recall"
            )
            error_text = ""
            if exec_result:
                error_text = (exec_result.error or exec_result.stderr or "")[:1500]
            scraper = await generator.regenerate(
                url=url,
                iteration=i,
                max_iterations=max_iter,
                outcome=outcome,
                error=error_text,
                expected_docs=truth.expected_doc_count,
                downloaded=metrics.downloaded_count if metrics else 0,
                model=model,
                # Without the failing code the model regenerates blind — pass
                # it so "self-healing" is an actual targeted fix.
                previous_code=scraper.code,
            )

        loop.total_cost_usd += scraper.cost_usd

        # 2. Validate
        validation = validate(scraper.code)
        if not validation.ok:
            log.warning("phase1.loop.validation_failed", errors=validation.errors)
            exec_result = ExecutionResult(
                success=False,
                error="validation failed: " + "; ".join(validation.errors),
            )
            loop.history.append({
                "iteration": i,
                "stage": "validation",
                "ok": False,
                "errors": validation.errors,
            })
            continue

        # 3. Execute (sandboxed)
        prev_failed_output_dir = (
            exec_result.output_dir
            if (exec_result and not exec_result.success and exec_result.output_dir)
            else None
        )
        exec_result = execute(scraper.code, url=url)

        # Clean up the previous failed iteration's empty output dir.
        if prev_failed_output_dir:
            cleanup_output_dir(prev_failed_output_dir)

        # 4. Evaluate
        metrics = evaluate(truth, exec_result)
        loop.history.append({
            "iteration": i,
            "stage": "execute",
            "exec_success": exec_result.success,
            "downloaded": metrics.downloaded_count,
            "recall": metrics.recall,
            "runtime": metrics.runtime_seconds,
            "error": exec_result.error,
        })

        if metrics.success:
            log.info(
                "phase1.loop.success",
                url=url,
                iteration=i,
                downloaded=metrics.downloaded_count,
            )
            success_output_dir = exec_result.output_dir
            break

        # iteration failed → drop the (likely empty) output dir
        if exec_result.output_dir and exec_result.output_dir != success_output_dir:
            cleanup_output_dir(exec_result.output_dir)
            # Don't re-clean it later — wipe the field
            exec_result.output_dir = None

    loop.final_scraper = scraper
    loop.final_execution = exec_result
    loop.metrics = metrics
    return loop
