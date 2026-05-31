"""
The cascaded pipeline — the heart of Phase 3.

Given a URL, try strategies in order until one succeeds:
    1. Manual reference scraper (Phase 0 / V1)
    2. Existing scraper (registry lookup by domain)
    3. Deterministic platform template (DTVP/Satellite family — no LLM)
    4. LLM-generated scraper (Phase 1 feedback loop, optionally route-guided)
    5. Computer-use agent (Phase 2)

The DETERMINISTIC strategy was added based on the proven dev-branch
classifier — for known portals (DTVP-family), it constructs the ZIP
URL directly and downloads it without spinning up Playwright or
calling the LLM.

The LLM_GENERATED strategy was upgraded with the route-learning idea
from the implementation plan: before asking the LLM to write the scraper,
a Playwright visit traces the actual click path to the documents and
hands that route to the LLM as ground truth.

Each strategy's runner is responsible for:
  * pulling files into a local directory we control,
  * extending `result.downloaded` with absolute paths,
  * and returning a `StrategyOutcome` describing how it went.

The pipeline never trusts the per-strategy temp dirs — it copies files
into one canonical `result.downloaded` list before persisting them.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.config import settings
from app.core.llm_client import LLMClient
from app.core.security import is_url_allowed, classify_risk, detect_prompt_injection
from app.core.storage import ObjectStorage
from app.models import Document, JobItem, JobStatus, Strategy
from app.utils.audit import CRITICAL, ERROR, INFO, WARNING, write_audit
from app.phase0_manual.v1_reference import scrape as manual_scrape
from app.phase1_llm_scraper.executor import (
    cleanup_output_dir,
    execute as exec_scraper,
)
from app.phase1_llm_scraper.feedback_loop import run_feedback_loop
from app.phase1_llm_scraper.route_learner import RouteMap, learn_route
from app.phase2_cua.orchestrator import run_agent
from app.phase3_integration import platform_classifier, scraper_registry
from app.phase3_integration.deterministic import try_deterministic
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
    # Internal: directories we created during the run that should be
    # cleaned up after files are persisted to S3.
    _scratch_dirs: list[str] = field(default_factory=list)


def _job_downloads_dir(item: JobItem) -> Path:
    """A per-job-item directory that survives the strategy loop."""
    base = Path(settings.downloads_dir)
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError:
        base = Path(tempfile.gettempdir()) / "vergabepilot-downloads"
        base.mkdir(parents=True, exist_ok=True)
    out = base / f"job-{item.job_id}-{item.id}"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _move_into(scratch: Path, sources: list[str]) -> list[str]:
    """Copy `sources` into `scratch` (preserving names; deduping by name) and
    return the new absolute paths. Skips files that don't exist."""
    moved: list[str] = []
    seen: set[str] = set()
    for src in sources:
        if not src or not os.path.isfile(src):
            continue
        name = os.path.basename(src)
        # de-dupe filename collisions across strategies
        candidate = name
        counter = 1
        while candidate in seen or (scratch / candidate).exists():
            stem, ext = os.path.splitext(name)
            candidate = f"{stem}__{counter}{ext}"
            counter += 1
        target = scratch / candidate
        try:
            shutil.copy2(src, target)
            seen.add(candidate)
            moved.append(str(target))
        except Exception as e:  # noqa: BLE001
            log.warning("phase3.pipeline.copy_failed", src=src, error=str(e))
    return moved


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

    write_audit("pipeline.start", f"Processing URL: {url}", level=INFO,
                job_id=item.job_id, item_id=item.id, domain=domain, url=url)

    # SSRF / scheme guard before we spin anything up.
    allowed, reason = is_url_allowed(url)
    if not allowed:
        result.error = f"url not allowed: {reason}"
        item.status = JobStatus.FAILED.value
        item.strategy = Strategy.NONE.value
        item.error_message = result.error
        write_audit("security.blocked_url", reason, level=CRITICAL,
                    job_id=item.job_id, item_id=item.id, domain=domain, url=url)
        db.commit()
        return result

    # 1. Prompt Injection check — only scan the URL path/query fragment, NOT
    #    the whole URL string (which may contain % encodings that look like hex
    #    sequences). URLs cannot inject into LLM prompts; only fetched HTML can.
    #    Prompt injection in fetched HTML is caught in generator._fetch_snippet().
    from app.core.security import detect_prompt_injection
    from urllib.parse import unquote
    url_decoded = unquote(url)
    injection_hits = detect_prompt_injection(url_decoded)
    if injection_hits:
        result.error = f"prompt injection in URL: {injection_hits[:2]}"
        item.status = JobStatus.FAILED.value
        item.strategy = Strategy.NONE.value
        item.error_message = result.error
        write_audit("security.prompt_injection", f"URL patterns: {injection_hits[:3]}", level=CRITICAL,
                    job_id=item.job_id, item_id=item.id, domain=domain, url=url)
        db.commit()
        return result

    # 2. Lightweight DNS-only pre-flight check.
    #
    # We ONLY abort here when the domain does not resolve in DNS — that means
    # the URL is completely unreachable and no strategy can help. All other
    # failures (TCP refused, SSL errors, HTTP 4xx/5xx, VPN-gated, slow servers)
    # are handled gracefully inside the cascade strategies themselves.
    #
    # Previous approach tried HEAD→GET and aborted on ConnectError — this was
    # too aggressive for bulk runs: 100 simultaneous connections to the same
    # IP triggered rate-limiting/connection resets, appearing as ConnectError
    # even for valid domains. DNS failures are the only truly unrecoverable case.
    import socket as _socket
    try:
        _socket.getaddrinfo(domain, None, proto=_socket.IPPROTO_TCP)
    except _socket.gaierror:
        result.error = f"dns resolution failed: {domain} does not exist"
        item.status = JobStatus.FAILED.value
        item.strategy = Strategy.NONE.value
        item.error_message = result.error
        write_audit("pipeline.dns_fail", f"DNS resolution failed for {domain}", level=ERROR,
                    job_id=item.job_id, item_id=item.id, domain=domain, url=url)
        db.commit()
        return result

    scratch = _job_downloads_dir(item)
    result._scratch_dirs.append(str(scratch))

    strategies = [force_strategy] if force_strategy else [
        Strategy.MANUAL,
        Strategy.EXISTING,
        Strategy.DETERMINISTIC,
        Strategy.LLM_GENERATED,
        Strategy.CUA,
    ]

    last_outcome: StrategyOutcome | None = None
    for strategy in strategies:
        if strategy is Strategy.CUA and not settings.enable_fallback_cua:
            continue

        log.info("phase3.pipeline.attempt", url=url, strategy=strategy.value)
        write_audit("strategy.attempt", f"Trying {strategy.value}", level=INFO,
                    job_id=item.job_id, item_id=item.id, domain=domain, url=url, strategy=strategy.value)

        outcome = await _run_strategy(
            db, strategy, url, domain, llm, scratch, result
        )
        last_outcome = outcome

        # --- Self-Healing and High-Risk Management Layer ---
        if not outcome.success and outcome.error:
            risk = classify_risk(outcome.error)
            if risk == "high":
                log.error("phase3.pipeline.high_risk_detected", strategy=strategy.value, error=outcome.error)
                outcome.error = f"[CRITICAL] {outcome.error}"
                result.error = outcome.error
                write_audit("security.high_risk_abort", outcome.error[:500], level=CRITICAL,
                            job_id=item.job_id, item_id=item.id, domain=domain, url=url, strategy=strategy.value)
                result.attempts.append({
                    "strategy": strategy.value,
                    "success": False,
                    "downloaded": 0,
                    "error": outcome.error,
                })
                break

            elif risk == "moderate":
                log.info("phase3.pipeline.self_healing_triggered", strategy=strategy.value, error=outcome.error)
                write_audit("self_heal.triggered", f"Moderate risk on {strategy.value} — retrying in 2s", level=WARNING,
                            job_id=item.job_id, item_id=item.id, domain=domain, url=url, strategy=strategy.value,
                            metadata={"error": (outcome.error or "")[:300]})
                await asyncio.sleep(2.0)
                try:
                    retry_outcome = await _run_strategy(
                        db, strategy, url, domain, llm, scratch, result
                    )
                    if retry_outcome.success:
                        log.info("phase3.pipeline.self_healing_success", strategy=strategy.value)
                        write_audit("self_heal.success", f"Auto-recovered {strategy.value}", level=INFO,
                                    job_id=item.job_id, item_id=item.id, domain=domain, url=url, strategy=strategy.value)
                        outcome = retry_outcome
                        last_outcome = outcome
                        item.error_message = f"[SELF-HEALED] Automatically resolved: {retry_outcome.error}"
                    else:
                        log.warning("phase3.pipeline.self_healing_failed", strategy=strategy.value)
                        write_audit("self_heal.failed", f"Self-heal retry failed for {strategy.value}", level=WARNING,
                                    job_id=item.job_id, item_id=item.id, domain=domain, url=url, strategy=strategy.value)
                except Exception as retry_err:
                    log.warning("phase3.pipeline.self_healing_exception", strategy=strategy.value, err=str(retry_err))

        result.attempts.append({
            "strategy": strategy.value,
            "success": outcome.success,
            "downloaded": outcome.downloaded,
            "error": outcome.error,
        })

        if outcome.success:
            result.success = True
            result.strategy_used = outcome.strategy
            write_audit("pipeline.success", f"Strategy {outcome.strategy.value} downloaded {outcome.downloaded} doc(s)", level=INFO,
                        job_id=item.job_id, item_id=item.id, domain=domain, url=url, strategy=outcome.strategy.value,
                        metadata={"downloaded": outcome.downloaded})
            break

        write_audit("strategy.failed", outcome.error or "no documents", level=WARNING,
                    job_id=item.job_id, item_id=item.id, domain=domain, url=url, strategy=strategy.value,
                    metadata={"error": (outcome.error or "")[:500]})

        if next_strategy(strategy, outcome, settings.enable_fallback_cua) is None:
            break

    result.runtime_seconds = time.time() - t0
    if not result.success and last_outcome:
        # Prepend critical label if it was determined high risk earlier
        if last_outcome.error and last_outcome.error.startswith("[CRITICAL]"):
            result.error = last_outcome.error
        else:
            result.error = last_outcome.error

    # Persist documents if we have any
    if result.downloaded:
        try:
            _persist_documents(db, item, result.downloaded, storage)
        except Exception as e:  # noqa: BLE001
            log.exception("phase3.pipeline.persist_failed", error=str(e))
            result.error = (result.error or "") + f"; persist failed: {e}"

    # Final outcome audit
    if not result.success:
        write_audit("pipeline.failure", result.error or "all strategies exhausted", level=ERROR,
                    job_id=item.job_id, item_id=item.id, domain=domain, url=url,
                    metadata={"attempts": len(result.attempts), "runtime_s": round(result.runtime_seconds, 2)})

    # Update item record
    item.status = JobStatus.SUCCESS.value if result.success else JobStatus.FAILED.value
    item.strategy = result.strategy_used.value
    item.iterations = result.iterations
    item.runtime_seconds = result.runtime_seconds
    
    # Store clean self-healed indicator or the failed error
    if result.success and item.error_message and item.error_message.startswith("[SELF-HEALED]"):
        pass # keep our self-healed message!
    elif last_outcome and last_outcome.cua_discovery_report:
        prefix = "[CUA-DISCOVERY]" if result.success else f"[CUA-DISCOVERY-FAILED] Scraper failed: {result.error}\n\n"
        item.error_message = f"{prefix} {last_outcome.cua_discovery_report}"
    else:
        item.error_message = result.error if not result.success else None
        
    db.commit()

    # Clean up scratch dirs once everything is in S3.
    for d in result._scratch_dirs:
        cleanup_output_dir(d)

    return result


# ---------- per-strategy runners ----------

async def _run_strategy(
    db: Session,
    strategy: Strategy,
    url: str,
    domain: str,
    llm: LLMClient,
    scratch: Path,
    result: PipelineResult,
) -> StrategyOutcome:
    if strategy is Strategy.MANUAL:
        return await _try_manual(db, url, domain, scratch, result)
    if strategy is Strategy.EXISTING:
        return await _try_existing(db, url, domain, scratch, result)
    if strategy is Strategy.DETERMINISTIC:
        return await _try_deterministic(url, scratch, result)
    if strategy is Strategy.LLM_GENERATED:
        return await _try_llm_generated(db, url, domain, llm, scratch, result)
    if strategy is Strategy.CUA:
        return await _try_cua(url, scratch, result)
    return StrategyOutcome(strategy=strategy, success=False, downloaded=0, error="no runner")


async def _try_manual(
    db: Session, url: str, domain: str, scratch: Path, result: PipelineResult,
) -> StrategyOutcome:
    """Phase 0 / V1 reference scraper. Best for known portals."""
    tmp_id = uuid.uuid4().hex[:8]
    tmp_dir = Path(tempfile.gettempdir()) / f"vergabepilot-manual-{tmp_id}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    try:
        # manual_scrape uses playwright.sync_api → run off the event loop.
        files = await asyncio.to_thread(manual_scrape, url, str(tmp_dir))
        files = files or []
        moved = _move_into(scratch, [str(f) for f in files])
        if moved:
            result.downloaded.extend(moved)
            # Register the manual scraper in the scraper registry so it
            # appears in the frontend and is not lost across sessions.
            _register_manual_scraper(db, domain)
            return StrategyOutcome(Strategy.MANUAL, True, len(moved))
        return StrategyOutcome(Strategy.MANUAL, False, 0, "no files found")
    except Exception as e:  # noqa: BLE001
        log.warning("phase3.manual.error", url=url, error=str(e))
        return StrategyOutcome(Strategy.MANUAL, False, 0, str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _register_manual_scraper(db: Session, domain: str) -> None:
    """Register/update a manual scraper entry in the template registry.

    The actual code lives in `phase0_manual.v1_reference` — we store
    a reference comment + the source module text so the frontend can
    display it and the user sees which domains have a working manual
    scraper.
    """
    import inspect
    from app.phase0_manual import v1_reference

    existing = scraper_registry.get_for_domain(db, domain)
    if existing and existing.source == "manual":
        # Already registered — just bump the success counter.
        scraper_registry.record_outcome(db, existing, success=True, runtime=0.0)
        return
    if existing:
        # An LLM-generated scraper already exists for this domain.
        # Don't overwrite it — the manual scraper is a fallback.
        return

    try:
        code = inspect.getsource(v1_reference)
    except Exception:  # noqa: BLE001
        code = "# Manual scraper — see backend/app/phase0_manual/v1_reference.py"

    tpl = scraper_registry.upsert_from_generation(
        db, domain, code, platform=None, route_used=False,
    )
    # Override source to 'manual' (upsert_from_generation sets it to 'llm').
    tpl.source = "manual"
    db.commit()


async def _try_existing(
    db: Session, url: str, domain: str, scratch: Path, result: PipelineResult
) -> StrategyOutcome:
    tpl = scraper_registry.get_for_domain(db, domain)
    if not tpl:
        return StrategyOutcome(Strategy.EXISTING, success=False, downloaded=0, error="no template")

    # executor is sync; run in thread pool
    ex = await asyncio.to_thread(exec_scraper, tpl.code, url)
    scraper_registry.record_outcome(db, tpl, success=ex.success, runtime=ex.runtime_seconds)

    if ex.success and ex.downloaded_files:
        moved = _move_into(scratch, ex.downloaded_files)
        cleanup_output_dir(ex.output_dir)
        if moved:
            result.downloaded.extend(moved)
            return StrategyOutcome(Strategy.EXISTING, True, len(moved))

    cleanup_output_dir(ex.output_dir)
    return StrategyOutcome(
        Strategy.EXISTING, False, 0, ex.error or "no files",
    )


async def _try_deterministic(
    url: str, scratch: Path, result: PipelineResult,
) -> StrategyOutcome:
    """Direct download via known URL template (DTVP family). No LLM, no Playwright."""
    det = await asyncio.to_thread(try_deterministic, url)
    if det.success and det.downloaded_files:
        moved = _move_into(scratch, det.downloaded_files)
        cleanup_output_dir(det.output_dir)
        if moved:
            result.downloaded.extend(moved)
            return StrategyOutcome(Strategy.DETERMINISTIC, True, len(moved))
    cleanup_output_dir(det.output_dir)
    return StrategyOutcome(
        Strategy.DETERMINISTIC, False, 0,
        det.error or "deterministic template did not apply",
    )


async def _try_llm_generated(
    db: Session, url: str, domain: str, llm: LLMClient,
    scratch: Path, result: PipelineResult,
) -> StrategyOutcome:
    # 1. URL-level classification (no HTTP).
    platform = platform_classifier.classify_url(url)

    # 2. Fetch HTML once — used for HTML-level classification AND forwarded to
    #    the LLM generator so it doesn't make a second round-trip.
    html_snippet: str | None = None
    sanitized_snippet: str | None = None
    try:
        import httpx
        from app.core.security import detect_prompt_injection, sanitize_web_content
        async with httpx.AsyncClient(timeout=12, follow_redirects=True, verify=False) as client:  # noqa: S501
            r = await client.get(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept-Language": "de-DE,de;q=0.9,en;q=0.7",
            })
            html_snippet = r.text
        # Security: run injection scan on fetched HTML before handing to LLM.
        hits = detect_prompt_injection(html_snippet)
        if hits:
            log.warning("phase3.llm.prompt_injection_in_html", url=url, patterns=hits[:3])
            html_snippet = None  # discard tainted content; generator will re-fetch safely
        else:
            sanitized_snippet = sanitize_web_content(html_snippet, max_length=20_000)
    except Exception as e:  # noqa: BLE001
        log.warning("phase3.llm.html_fetch_failed", url=url, error=str(e))

    # 3. Refine platform using HTML when URL alone was inconclusive.
    if platform == "unknown" and html_snippet:
        platform = platform_classifier.classify_html(url, html_snippet)

    # 4. If HTML reveals a DTVP URL we missed at URL-level, try deterministic first.
    if platform == "dtvp":
        det = await asyncio.to_thread(try_deterministic, url)
        if det.success and det.downloaded_files:
            moved = _move_into(scratch, det.downloaded_files)
            cleanup_output_dir(det.output_dir)
            if moved:
                result.downloaded.extend(moved)
                return StrategyOutcome(Strategy.DETERMINISTIC, True, len(moved))
        cleanup_output_dir(det.output_dir)

    resolved_platform = platform if platform != "unknown" else None

    # 5. Best-effort route learning (Playwright traces the click path).
    route_map: RouteMap | None = None
    if settings.enable_route_learning:
        try:
            route_map = await asyncio.to_thread(learn_route, url)
            log.info(
                "phase3.route_learning",
                url=url, learned=route_map.learned,
                docs=route_map.total_documents_found,
            )
        except Exception as e:  # noqa: BLE001
            log.warning("phase3.route_learning_failed", url=url, error=str(e))
            route_map = None

        # Fallback to Computer-Use Agent (CUA) Pre-flight Discovery if standard learner failed
        if route_map is None or not route_map.learned:
            try:
                log.info("phase3.route_learning.cua_preflight_trigger", url=url)
                from app.phase1_llm_scraper.cua_discovery import run_cua_preflight_discovery
                route_map = await run_cua_preflight_discovery(url, max_steps=8)
                log.info(
                    "phase3.route_learning.cua_preflight_complete",
                    url=url, learned=route_map.learned,
                    docs=route_map.total_documents_found,
                )
            except Exception as e:
                log.warning("phase3.route_learning.cua_preflight_failed", url=url, error=str(e))

    # 6. Domain-deduplication lock: if another worker is generating a scraper for
    #    this domain right now, wait for it to finish and then use the cached result.
    #    This is critical at scale — 100 URLs from the same domain would otherwise
    #    each trigger their own LLM call (wasted cost + time).
    lock_acquired = False
    _redis = None  # must be initialized before try so the finally block can safely reference it
    try:
        import redis as redis_lib
        _redis = redis_lib.from_url(settings.redis_url, socket_timeout=2.0)
        lock_key = f"vergabepilot:domain_llm_lock:{domain}"
        # Try to acquire with a short poll loop (non-blocking)
        for _ in range(int(settings.domain_llm_lock_ttl / 5)):
            lock_acquired = bool(_redis.set(lock_key, "1", nx=True, ex=settings.domain_llm_lock_ttl))
            if lock_acquired:
                break
            # Another worker holds the lock — check if it already built the scraper
            await asyncio.sleep(5)
            refreshed = scraper_registry.get_for_domain(db, domain)
            if refreshed:
                log.info("phase3.llm.dedup_cache_hit", domain=domain, url=url)
                ex = await asyncio.to_thread(exec_scraper, refreshed.code, url)
                scraper_registry.record_outcome(db, refreshed, success=ex.success, runtime=ex.runtime_seconds)
                if ex.success and ex.downloaded_files:
                    moved = _move_into(scratch, ex.downloaded_files)
                    cleanup_output_dir(ex.output_dir)
                    if moved:
                        result.downloaded.extend(moved)
                        return StrategyOutcome(Strategy.EXISTING, True, len(moved))
                cleanup_output_dir(ex.output_dir)
                return StrategyOutcome(Strategy.EXISTING, False, 0, "dedup scraper did not return files")
        # Timed out waiting for lock — proceed with own LLM generation
    except Exception:  # Redis unavailable — proceed without dedup
        pass

    report_data = route_map.cua_discovery_report if route_map else None

    try:
        # Run the LLM feedback loop (generator uses platform + route + pre-fetched HTML).
        loop = await asyncio.to_thread(
            _run_loop_sync, url, llm.default_model, route_map, resolved_platform, sanitized_snippet,
        )
        result.iterations += loop.iterations
        result.cost_usd += loop.total_cost_usd

        if loop.success and loop.final_scraper and loop.final_execution:
            moved = _move_into(scratch, loop.final_execution.downloaded_files)
            cleanup_output_dir(loop.final_execution.output_dir)
            if moved:
                result.downloaded.extend(moved)
                scraper_registry.upsert_from_generation(
                    db, domain, loop.final_scraper.code,
                    platform=resolved_platform,
                    route_used=loop.final_scraper.route_used,
                )
                return StrategyOutcome(Strategy.LLM_GENERATED, True, len(moved), cua_discovery_report=report_data)

        err = (loop.final_execution.error if loop.final_execution else None) or "loop exhausted"
        if loop.final_execution:
            cleanup_output_dir(loop.final_execution.output_dir)
        return StrategyOutcome(Strategy.LLM_GENERATED, False, 0, err, cua_discovery_report=report_data)
    finally:
        # Always release the domain lock after generation
        if lock_acquired and _redis is not None:
            try:
                _redis.delete(lock_key)
            except Exception:
                pass


def _run_loop_sync(
    url: str,
    default_model: str | None,
    route_map=None,
    platform: str | None = None,
    html_snippet: str | None = None,
):
    """Run the async feedback loop from inside asyncio.to_thread().

    A fresh LLMClient is created here so its httpx.AsyncClient is bound
    to the new event loop started by asyncio.run() — not the outer loop.
    `html_snippet` is the already-sanitized page content forwarded from the
    pipeline so the generator skips its own HTTP fetch.
    """
    llm = LLMClient(default_model=default_model)
    return asyncio.run(run_feedback_loop(
        url=url, llm=llm, route_map=route_map, platform=platform,
        html_snippet=html_snippet,
    ))


async def _try_cua(
    url: str, scratch: Path, result: PipelineResult,
) -> StrategyOutcome:
    outcome = await run_agent(
        "playwright_cua", url=url, max_steps=settings.cua_max_steps,
    )
    result.cost_usd += outcome.cost_usd
    if outcome.success and outcome.downloaded_files:
        moved = _move_into(scratch, outcome.downloaded_files)
        # Clean up the agent's run-specific temp dir once files are in scratch.
        for f in outcome.downloaded_files:
            cua_dir = str(Path(f).parent)
            if cua_dir and cua_dir != str(scratch):
                cleanup_output_dir(cua_dir)
                break
        if moved:
            result.downloaded.extend(moved)
            return StrategyOutcome(Strategy.CUA, True, len(moved))
    return StrategyOutcome(Strategy.CUA, False, 0, outcome.error or "agent failed")


# ---------- persistence ----------

def _persist_documents(
    db: Session, item: JobItem, files: list[str], storage: ObjectStorage,
) -> None:
    import mimetypes
    from app.phase3_integration.versioning import checksum

    persisted = 0
    for path in files:
        if not os.path.isfile(path):
            log.warning("phase3.persist.missing_file", path=path)
            continue
        with open(path, "rb") as f:
            data = f.read()
        key = f"jobs/{item.job_id}/{item.id}/{os.path.basename(path)}"
        try:
            storage.put(key, data)
        except Exception as e:  # noqa: BLE001
            # Don't crash the whole job if S3 is misconfigured locally —
            # we still record the document with the local path so a dev
            # can inspect it.
            log.warning("phase3.persist.s3_failed", key=key, error=str(e))

        mime, _ = mimetypes.guess_type(path)
        db.add(Document(
            job_item_id=item.id,
            filename=os.path.basename(path),
            s3_key=key,
            mime_type=mime or "application/octet-stream",
            size_bytes=len(data),
            version=1,
            checksum=checksum(data),
        ))
        persisted += 1
    db.commit()
    log.info("phase3.persist.complete", job_item=item.id, files=persisted)
