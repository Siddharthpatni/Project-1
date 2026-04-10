"""
Feedback loop that iteratively regenerates a scraper until it works or
the iteration budget is exhausted. This is the entry point Phase 1 and
Phase 3 both call into.
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
from app.phase1_llm_scraper.executor import ExecutionResult, execute
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
) -> LoopResult:
    """Generate → validate → execute → evaluate → retry until success."""
    max_iter = max_iterations or settings.max_feedback_iterations
    generator = ScraperGenerator(llm)

    truth = ground_truth or GroundTruth(url=url, expected_doc_count=0, expected_extensions=[])
    loop = LoopResult(final_scraper=None, final_execution=None, metrics=None, iterations=0)

    scraper: GeneratedScraper | None = None
    exec_result: ExecutionResult | None = None
    metrics: EvaluationMetrics | None = None

    for i in range(1, max_iter + 1):
        loop.iterations = i
        log.info("phase1.loop.iteration", url=url, iteration=i, model=model)

        # 1. Generate or regenerate
        if scraper is None:
            scraper = await generator.generate(url, model=model)
        else:
            outcome = "execution_failed" if not exec_result or not exec_result.success else "insufficient_recall"
            error_text = (exec_result.error or exec_result.stderr or "")[:1500] if exec_result else ""
            scraper = await generator.regenerate(
                url=url,
                iteration=i,
                max_iterations=max_iter,
                outcome=outcome,
                error=error_text,
                expected_docs=truth.expected_doc_count,
                downloaded=metrics.downloaded_count if metrics else 0,
                model=model,
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
                "iteration": i, "stage": "validation", "ok": False,
                "errors": validation.errors,
            })
            continue

        # 3. Execute (sandboxed)
        exec_result = execute(scraper.code, url=url)

        # 4. Evaluate
        metrics = evaluate(truth, exec_result)
        loop.history.append({
            "iteration": i,
            "stage": "execute",
            "exec_success": exec_result.success,
            "downloaded": metrics.downloaded_count,
            "recall": metrics.recall,
            "runtime": metrics.runtime_seconds,
        })

        if metrics.success:
            log.info("phase1.loop.success", url=url, iteration=i)
            break

    loop.final_scraper = scraper
    loop.final_execution = exec_result
    loop.metrics = metrics
    return loop
