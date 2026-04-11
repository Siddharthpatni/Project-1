"""
The cascaded pipeline — the heart of Phase 3.

Given a URL, try strategies in order until one succeeds:
    1. Existing scraper (registry lookup by domain)
    2. LLM-generated scraper (Phase 1 feedback loop)
    3. Computer-use agent (Phase 2)

Each attempt is logged. The final set of downloaded files is uploaded
to S3 and returned as Document records.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.config import settings
from app.core.llm_client import LLMClient
from app.core.storage import ObjectStorage
from app.models import Document, JobItem, JobStatus, Strategy
from app.phase0_manual.v1_reference import scrape as manual_scrape
from app.phase1_llm_scraper.executor import execute as exec_scraper
from app.phase1_llm_scraper.feedback_loop import run_feedback_loop
from app.phase2_cua.orchestrator import run_agent
from app.phase3_integration import scraper_registry
from app.phase3_integration.fallback import StrategyOutcome, next_strategy
from app.utils.logger import get_logger

log = get_logger(__name__)


@dataclass
class PipelineResult:
    success: bool
    strategy_used: Strategy
    downloaded: list[str]
    iterations: int = 0
    runtime_seconds: float = 0.0
    cost_usd: float = 0.0
    attempts: list[dict] = field(default_factory=list)
    error: str | None = None


async def process_url(
    db: Session,
    item: JobItem,
    llm: LLMClient,
    storage: ObjectStorage,
    force_strategy: Strategy | None = None,
) -> PipelineResult:
    """Run the full cascade for a single URL and persist downloaded files."""
    url = item.url
    domain = urlparse(url).netloc

    result = PipelineResult(success=False, strategy_used=Strategy.NONE, downloaded=[])
    t0 = time.time()

    strategies = [force_strategy] if force_strategy else [
        Strategy.MANUAL,
        Strategy.EXISTING,
        Strategy.LLM_GENERATED,
        Strategy.CUA,
    ]

    for strategy in strategies:
        if strategy is Strategy.CUA and not settings.enable_fallback_cua:
            continue

        log.info("phase3.pipeline.attempt", url=url, strategy=strategy.value)
        outcome = await _run_strategy(db, strategy, url, domain, llm, result)

        result.attempts.append({
            "strategy": strategy.value,
            "success": outcome.success,
            "downloaded": outcome.downloaded,
            "error": outcome.error,
        })

        if outcome.success:
            result.success = True
            result.strategy_used = strategy
            break

        if next_strategy(strategy, outcome, settings.enable_fallback_cua) is None:
            break

    result.runtime_seconds = time.time() - t0

    # Persist documents if we have any
    if result.downloaded:
        _persist_documents(db, item, result.downloaded, storage)

    # Update item record
    item.status = JobStatus.SUCCESS if result.success else JobStatus.FAILED
    item.strategy = result.strategy_used
    item.iterations = result.iterations
    item.runtime_seconds = result.runtime_seconds
    item.error_message = result.error if not result.success else None
    db.commit()

    return result


# ---------- per-strategy runners ----------

async def _run_strategy(
    db: Session,
    strategy: Strategy,
    url: str,
    domain: str,
    llm: LLMClient,
    result: PipelineResult,
) -> StrategyOutcome:
    if strategy is Strategy.MANUAL:
        return await _try_manual(url, result)
    if strategy is Strategy.EXISTING:
        return await _try_existing(db, url, domain, result)
    if strategy is Strategy.LLM_GENERATED:
        return await _try_llm_generated(db, url, domain, llm, result)
    if strategy is Strategy.CUA:
        return await _try_cua(url, llm, result)
    return StrategyOutcome(strategy=strategy, success=False, downloaded=0, error="no runner")


async def _try_manual(url: str, result: PipelineResult) -> StrategyOutcome:
    import os
    import tempfile
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # run in thread pool since playwright.sync_api is used in scrape
        try:
            files = await asyncio.to_thread(manual_scrape, url, tmpdir)
            if files:
                # Scrape returns list of local paths. We need to move them 
                # or read them before the tmpdir is deleted.
                # Actually, result.downloaded should contain paths that _persist_documents can read.
                # But _persist_documents is called AFTER the strategy loop.
                # So we need to copy them to a more permanent 'downloads' dir.
                
                out_dir = os.path.join(settings.workspace_dir, "downloads", str(time.time()))
                os.makedirs(out_dir, exist_ok=True)
                
                saved_files = []
                for f in files:
                    target = os.path.join(out_dir, os.path.basename(f))
                    import shutil
                    shutil.copy(f, target)
                    saved_files.append(target)
                
                result.downloaded.extend(saved_files)
                return StrategyOutcome(Strategy.MANUAL, True, len(saved_files))
            return StrategyOutcome(Strategy.MANUAL, False, 0, "no files found")
        except Exception as e:
            return StrategyOutcome(Strategy.MANUAL, False, 0, str(e))


async def _try_existing(db: Session, url: str, domain: str, result: PipelineResult) -> StrategyOutcome:
    tpl = scraper_registry.get_for_domain(db, domain)
    if not tpl:
        return StrategyOutcome(Strategy.EXISTING, success=False, downloaded=0, error="no template")

    # executor is sync; run in thread pool
    ex = await asyncio.to_thread(exec_scraper, tpl.code, url)
    scraper_registry.record_outcome(db, tpl, success=ex.success, runtime=ex.runtime_seconds)

    if ex.success and ex.downloaded_files:
        result.downloaded.extend(ex.downloaded_files)
        return StrategyOutcome(Strategy.EXISTING, True, len(ex.downloaded_files))
    return StrategyOutcome(Strategy.EXISTING, False, 0, ex.error or "no files")


async def _try_llm_generated(
    db: Session, url: str, domain: str, llm: LLMClient, result: PipelineResult
) -> StrategyOutcome:
    loop = await run_feedback_loop(url=url, llm=llm)
    result.iterations += loop.iterations
    result.cost_usd += loop.total_cost_usd

    if loop.success and loop.final_scraper and loop.final_execution:
        result.downloaded.extend(loop.final_execution.downloaded_files)
        # Promote to registry
        scraper_registry.upsert_from_generation(db, domain, loop.final_scraper.code)
        return StrategyOutcome(Strategy.LLM_GENERATED, True, len(loop.final_execution.downloaded_files))

    err = (loop.final_execution.error if loop.final_execution else None) or "loop exhausted"
    return StrategyOutcome(Strategy.LLM_GENERATED, False, 0, err)


async def _try_cua(url: str, llm: LLMClient, result: PipelineResult) -> StrategyOutcome:
    outcome = await run_agent("playwright_cua", url=url, llm=llm, max_steps=settings.cua_max_steps)
    result.cost_usd += outcome.cost_usd
    if outcome.success:
        result.downloaded.extend(outcome.downloaded_files)
        return StrategyOutcome(Strategy.CUA, True, len(outcome.downloaded_files))
    return StrategyOutcome(Strategy.CUA, False, 0, outcome.error or "agent failed")


# ---------- persistence ----------

def _persist_documents(db: Session, item: JobItem, files: list[str], storage: ObjectStorage) -> None:
    import os
    for path in files:
        if not os.path.isfile(path):
            continue
        data = open(path, "rb").read()
        key = f"jobs/{item.job_id}/{item.id}/{os.path.basename(path)}"
        storage.put(key, data)
        from app.phase3_integration.versioning import checksum
        db.add(Document(
            job_item_id=item.id,
            filename=os.path.basename(path),
            s3_key=key,
            mime_type="application/octet-stream",
            size_bytes=len(data),
            version=1,
            checksum=checksum(data),
        ))
    db.commit()
