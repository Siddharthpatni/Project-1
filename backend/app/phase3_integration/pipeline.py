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

# Maps security.classify_error categories → plain-English reason shown in UI
_ERROR_REASON_MAP: dict[str, str] = {
    # Infrastructure
    "timeout":               "Request timed out — portal too slow or overloaded",
    "network":               "Network error — connection refused or reset by portal",
    "dns":                   "DNS resolution failed — domain does not exist",
    "ssl":                   "SSL/TLS error — certificate problem on portal",
    "redirect_loop":         "Redirect loop detected — URL keeps redirecting indefinitely",
    "encoding_error":        "Encoding/decode error — response could not be read (charset issue)",
    # Security / validation
    "code_validation":       "Generated scraper failed validation — unsafe or wrong signature",
    "prompt_injection":      "Prompt injection pattern detected in URL or page content",
    "blocked_url":           "URL blocked — private network or disallowed scheme (SSRF protection)",
    "sandbox":               "Sandbox resource limit exceeded — scraper used too much memory/CPU",
    # Access / auth
    "login_required":        "Login required — portal shows a sign-in wall (no hard 401/403)",
    "registration_required": "Registration required — must create an account to access documents",
    "auth":                  "Access denied (HTTP 401/403) — portal requires authentication",
    # Bot protection
    "captcha":               "CAPTCHA / bot detection triggered — Cloudflare or reCAPTCHA blocked access",
    # HTTP codes
    "not_found":             "Page not found (HTTP 404) — URL may be expired or removed",
    "rate_limit":            "Rate limited (HTTP 429) — too many requests to portal",
    "server_error":          "Portal server error (5xx) — backend issue on the tender site",
    # Tender lifecycle
    "expired":               "Tender expired or archived — documents no longer publicly available",
    "maintenance":           "Site under maintenance — try again later",
    # Scraper content issues
    "js_required":           "JavaScript required — page needs browser rendering, plain HTTP failed",
    "empty_page":            "Empty/blank page — portal loaded but returned no usable content",
    "scraper_crash":         "Scraper crashed — unhandled exception in generated or stored scraper code",
    # Documents / storage
    "no_documents":          "No downloadable documents found on the page",
    "storage":               "File storage error — could not save to S3/MinIO",
    # Pipeline-level
    "no_strategy":           "No matching strategy — deterministic template does not apply",
    "loop_exhausted":        "LLM feedback loop exhausted — all iterations failed to produce valid scraper",
    "unknown":               "Unexpected error — check error_raw for details",
}
# Global semaphore: limits concurrent LLM generation threads across all URLs
# in the same asyncio event loop (one per Celery worker task).
# Without this, 8 concurrent URLs each spawn a thread that calls OpenRouter
# simultaneously — triggering 403 rate-limit on most of them.
import asyncio as _asyncio
_LLM_GENERATION_SEM: _asyncio.Semaphore | None = None

def _get_llm_sem() -> _asyncio.Semaphore:
    global _LLM_GENERATION_SEM
    if _LLM_GENERATION_SEM is None:
        _LLM_GENERATION_SEM = _asyncio.Semaphore(settings.llm_global_concurrency)
    return _LLM_GENERATION_SEM

from app.core.metrics import (
    SCRAPE_TOTAL, SCRAPE_DURATION, DOCUMENTS_DOWNLOADED,
    ZIP_EXPANSIONS, ZIP_FILES_EXTRACTED, JOB_URLS_PROCESSED,
)
from app.core.zip_expander import expand_zips
from app.phase0_manual.v1_reference import scrape as manual_scrape
from app.phase1_llm_scraper.executor import (
    cleanup_output_dir,
    execute as exec_scraper,
)
from app.phase1_llm_scraper.feedback_loop import run_feedback_loop
from app.phase1_llm_scraper.route_learner import RouteMap, learn_route
from app.phase2_cua.orchestrator import run_agent
from app.phase2_cua.route_learner import learn_from_cua, replay as replay_learned_route
from app.phase3_integration import platform_classifier, scraper_registry
from app.phase3_integration.adaptive_scraper import run_adaptive
from app.phase3_integration.deterministic import try_deterministic
from app.phase3_integration.fallback import StrategyOutcome, next_strategy
from app.phase3_integration.url_intelligence import (
    classify_url_type, get_strategy_order, circuit_breaker, rate_limiter, UrlType,
)
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
    """Copy `sources` into `scratch` (preserving names; deduping by name),
    expand any ZIPs found, and return the full list of absolute paths.
    Skips files that don't exist."""
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

    try:
        expanded = expand_zips(moved)
        new_files = len(expanded) - len(moved)
        if new_files > 0:
            log.info(
                "phase3.pipeline.zip_expanded",
                original=len(moved),
                after_expansion=len(expanded),
            )
            ZIP_EXPANSIONS.inc()
            ZIP_FILES_EXTRACTED.inc(new_files)
        moved = expanded
    except Exception as e:  # noqa: BLE001
        log.warning("phase3.pipeline.zip_expand_failed", error=str(e))

    return moved


async def process_url(
    db: Session,
    item: JobItem,
    llm: LLMClient,
    storage: ObjectStorage,
    force_strategy: Strategy | None = None,
) -> PipelineResult:
    """Run the full cascade for a single URL and persist downloaded files."""
    # Rewrite known login-entrance / landing URLs to the public page that
    # actually serves documents (e.g. EU-Supply rwlentrance → PublicPurchase).
    url = platform_classifier.normalize_url(item.url)
    if url != item.url:
        write_audit("pipeline.url_normalized", f"{item.url} → {url}", level=INFO,
                    job_id=item.job_id, item_id=item.id, url=item.url)
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

    # 2. Lightweight DNS-only pre-flight check (non-blocking).
    #
    # CRITICAL: socket.getaddrinfo is synchronous — calling it directly in an
    # async function blocks the entire event loop and freezes all concurrent
    # coroutines. Run it in a thread pool so other URLs keep processing.
    import socket as _socket
    try:
        await asyncio.to_thread(_socket.getaddrinfo, domain, None, _socket.AF_UNSPEC, _socket.SOCK_STREAM)
    except OSError:
        # Catch all socket resolution failures: gaierror (NXDOMAIN), herror
        # (SERVFAIL), and OSError (resolver timeout, network unreachable).
        # Previously only gaierror was caught — herror/OSError escaped unhandled
        # and left the item in PENDING state with no final DB commit.
        result.error = f"dns resolution failed: {domain}"
        item.status = JobStatus.FAILED.value
        item.strategy = Strategy.NONE.value
        item.error_message = result.error
        item.failure_category = "dns"
        write_audit("pipeline.dns_fail", f"DNS resolution failed for {domain}", level=ERROR,
                    job_id=item.job_id, item_id=item.id, domain=domain, url=url)
        db.commit()
        return result

    scratch = _job_downloads_dir(item)
    result._scratch_dirs.append(str(scratch))

    # ── Intelligent URL pre-classification ───────────────────────────────────
    # Classify URL type BEFORE the cascade to select the optimal strategy order.
    # This is the single biggest reliability improvement for 10K+ URL runs:
    #   - Auth-gated URLs skip LLM (saves ~90s + API cost per URL)
    #   - Satellite URLs go straight to deterministic (saves Playwright startup)
    #   - All types get a strategy list tuned to their expected success pattern
    _quick_platform = platform_classifier.classify_url(url)
    _url_type       = classify_url_type(url)

    # ── Circuit breaker check ─────────────────────────────────────────────────
    # If this domain has failed too many times recently, skip it immediately.
    # The circuit re-opens after reset_timeout (30 min) to allow recovery probes.
    if not circuit_breaker.allow_request(domain):
        result.error = f"circuit breaker open for {domain} — too many recent failures"
        item.status = JobStatus.FAILED.value
        item.strategy = Strategy.NONE.value
        item.error_message = result.error
        item.failure_category = "circuit_open"
        write_audit("circuit_breaker.rejected", f"Domain {domain} circuit is open — skipping",
                    level=WARNING, job_id=item.job_id, item_id=item.id, domain=domain, url=url)
        db.commit()
        return result

    # ── Domain rate limiter ───────────────────────────────────────────────────
    # Prevent hammering the same portal from multiple concurrent workers.
    # If we can't acquire a slot, back off briefly and try one more time.
    if not rate_limiter.acquire(domain):
        await asyncio.sleep(5)
        if not rate_limiter.acquire(domain):
            write_audit("rate_limiter.backoff", f"Rate limit hit for {domain}",
                        level=WARNING, job_id=item.job_id, item_id=item.id, domain=domain)

    # ── Strategy order selection ──────────────────────────────────────────────
    if force_strategy:
        strategies = [force_strategy]
    else:
        strategies = get_strategy_order(_url_type, _quick_platform)

    # Log the pre-classification result for analytics
    write_audit("pipeline.url_classified",
                f"URL type={_url_type.value} platform={_quick_platform} strategies={[s.value for s in strategies]}",
                level=INFO, job_id=item.job_id, item_id=item.id, domain=domain, url=url)

    from datetime import datetime as _dt
    from app.core.security import classify_error as _classify_error

    last_outcome: StrategyOutcome | None = None
    attempt_chain: list[dict] = []   # rich per-attempt record persisted to DB

    for strategy in strategies:
        if strategy is Strategy.CUA and not settings.enable_fallback_cua:
            continue

        strategy_t0 = time.time()
        log.info("phase3.pipeline.attempt", url=url, strategy=strategy.value)
        write_audit("strategy.attempt", f"Trying {strategy.value}", level=INFO,
                    job_id=item.job_id, item_id=item.id, domain=domain, url=url, strategy=strategy.value)

        outcome = await _run_strategy(
            db, strategy, url, domain, llm, scratch, result
        )
        strategy_elapsed = round(time.time() - strategy_t0, 2)
        last_outcome = outcome

        # Classify error into a human-readable reason
        error_category = _classify_error(outcome.error) if outcome.error else None
        error_reason   = _ERROR_REASON_MAP.get(error_category, outcome.error or "")

        # Build rich attempt record
        attempt_record = {
            "strategy":       strategy.value,
            "success":        outcome.success,
            "downloaded":     outcome.downloaded,
            "duration_s":     strategy_elapsed,
            "timestamp":      _dt.utcnow().isoformat(),
            "error_raw":      (outcome.error or "")[:500],
            "error_category": error_category,
            "error_reason":   error_reason,
        }

        # --- Self-Healing and High-Risk Management Layer ---
        if not outcome.success and outcome.error:
            risk = classify_risk(outcome.error)
            if risk == "high":
                log.error("phase3.pipeline.high_risk_detected", strategy=strategy.value, error=outcome.error)
                outcome.error = f"[CRITICAL] {outcome.error}"
                result.error = outcome.error
                attempt_record["error_reason"] = "Security block — pipeline aborted"
                write_audit("security.high_risk_abort", outcome.error[:500], level=CRITICAL,
                            job_id=item.job_id, item_id=item.id, domain=domain, url=url, strategy=strategy.value,
                            metadata={"error_category": error_category})
                attempt_chain.append(attempt_record)
                result.attempts.append(attempt_record)
                break

            elif risk == "moderate":
                log.info("phase3.pipeline.self_healing_triggered", strategy=strategy.value, error=outcome.error)
                write_audit("self_heal.triggered",
                            f"Moderate risk on {strategy.value} — retrying in 2s. Reason: {error_reason}",
                            level=WARNING, job_id=item.job_id, item_id=item.id,
                            domain=domain, url=url, strategy=strategy.value,
                            metadata={"error_category": error_category, "error_raw": (outcome.error or "")[:300]})
                await asyncio.sleep(0.3)  # was 2.0 — don't block all concurrent coroutines
                try:
                    retry_outcome = await _run_strategy(db, strategy, url, domain, llm, scratch, result)
                    if retry_outcome.success:
                        log.info("phase3.pipeline.self_healing_success", strategy=strategy.value)
                        write_audit("self_heal.success", f"Auto-recovered {strategy.value}", level=INFO,
                                    job_id=item.job_id, item_id=item.id, domain=domain, url=url, strategy=strategy.value)
                        outcome = retry_outcome
                        last_outcome = outcome
                        attempt_record["healed"] = True
                        item.error_message = f"[SELF-HEALED] Automatically resolved: {retry_outcome.error}"
                    else:
                        log.warning("phase3.pipeline.self_healing_failed", strategy=strategy.value)
                        write_audit("self_heal.failed", f"Self-heal retry failed for {strategy.value}", level=WARNING,
                                    job_id=item.job_id, item_id=item.id, domain=domain, url=url, strategy=strategy.value)
                except Exception as retry_err:
                    log.warning("phase3.pipeline.self_healing_exception", strategy=strategy.value, err=str(retry_err))

        attempt_chain.append(attempt_record)
        result.attempts.append(attempt_record)

        # Prometheus metrics
        SCRAPE_TOTAL.labels(
            strategy=strategy.value,
            status="success" if outcome.success else "failed",
        ).inc()
        SCRAPE_DURATION.labels(strategy=strategy.value).observe(strategy_elapsed)

        if outcome.success:
            result.success = True
            result.strategy_used = outcome.strategy
            # Feed success back to circuit breaker and rate limiter
            circuit_breaker.record_success(domain)
            rate_limiter.release(domain)
            write_audit(
                "pipeline.success",
                f"Strategy {outcome.strategy.value} succeeded — {outcome.downloaded} doc(s) downloaded in {strategy_elapsed}s",
                level=INFO, job_id=item.job_id, item_id=item.id, domain=domain,
                url=url, strategy=outcome.strategy.value,
                metadata={"downloaded": outcome.downloaded, "duration_s": strategy_elapsed},
            )
            break

        # Log detailed failure reason for each strategy
        write_audit(
            "strategy.failed",
            f"{strategy.value} failed — {error_reason or outcome.error or 'no documents'} ({strategy_elapsed}s)",
            level=WARNING, job_id=item.job_id, item_id=item.id,
            domain=domain, url=url, strategy=strategy.value,
            metadata={
                "error_raw":      (outcome.error or "")[:500],
                "error_category": error_category,
                "error_reason":   error_reason,
                "duration_s":     strategy_elapsed,
            },
        )

        if next_strategy(strategy, outcome, settings.enable_fallback_cua, order=strategies) is None:
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

        # Deep extraction — pure regex/structural, no LLM.
        # Runs after successful download; failure never blocks the pipeline.
        try:
            from app.document_extractor.extractor import DeepExtractor
            extractor = DeepExtractor()
            extractor.run(
                document_paths=result.downloaded,
                source_url=url,
                db=db,
                job_item_id=item.id,
            )
        except Exception as _ex:  # noqa: BLE001
            log.warning("extractor.pipeline_hook_failed", error=str(_ex))

    # Feed failure back to circuit breaker — trips after threshold
    if not result.success:
        final_error_category = _classify_error(result.error) if result.error else "unknown"
        circuit_breaker.record_failure(domain, final_error_category)
        rate_limiter.release(domain)

    # Final outcome audit
    if not result.success:
        write_audit("pipeline.failure", result.error or "all strategies exhausted", level=ERROR,
                    job_id=item.job_id, item_id=item.id, domain=domain, url=url,
                    metadata={"attempts": len(result.attempts), "runtime_s": round(result.runtime_seconds, 2)})

    # Update item record
    item.status           = JobStatus.SUCCESS.value if result.success else JobStatus.FAILED.value
    item.strategy         = result.strategy_used.value
    item.iterations       = result.iterations
    item.runtime_seconds  = result.runtime_seconds
    item.attempts_detail  = attempt_chain   # persist full strategy cascade log

    # Derive final failure category from the last recorded error for quick DB filtering.
    if not result.success and result.error:
        item.failure_category = _classify_error(result.error)
    else:
        item.failure_category = None

    # Build a clear, human-readable error summary when failed
    if not result.success:
        failed_summaries = [
            f"[{a['strategy'].replace('_', ' ').upper()}] {a.get('error_reason') or a.get('error_raw') or 'failed'}"
            for a in attempt_chain if not a.get("success")
        ]
        item.error_message = " → ".join(failed_summaries) or result.error
    elif item.error_message and item.error_message.startswith("[SELF-HEALED]"):
        pass  # keep self-healed message
    elif last_outcome and last_outcome.cua_discovery_report:
        prefix = "[CUA-DISCOVERY]" if result.success else f"[CUA-DISCOVERY-FAILED] {result.error}\n\n"
        item.error_message = f"{prefix} {last_outcome.cua_discovery_report}"
    else:
        item.error_message = None

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
    if strategy is Strategy.ADAPTIVE:
        return await _try_adaptive(url, scratch, result)
    if strategy is Strategy.LLM_GENERATED:
        return await _try_llm_generated(db, url, domain, llm, scratch, result)
    if strategy is Strategy.LEARNED_ROUTE:
        return await _try_learned_route(db, url, domain, scratch, result)
    if strategy is Strategy.CUA:
        return await _try_cua(db, url, domain, scratch, result)
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

    # Skip CUA-hint-only stubs — store_cua_hint() creates a ScraperTemplate
    # with source="cua" and a comment-only placeholder code when CUA runs
    # before a real scraper exists. Executing it would always fail, pollute
    # failure_count, and eventually trigger should_retire() on a fake scraper.
    if tpl.source == "cua":
        return StrategyOutcome(Strategy.EXISTING, success=False, downloaded=0, error="no real scraper (cua hint only)")

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


async def _try_adaptive(
    url: str, scratch: Path, result: PipelineResult,
) -> StrategyOutcome:
    """Universal, country/language-agnostic heuristic scraper (free, no LLM).

    Runs a single bounded Playwright session that harvests documents directly or
    after one multilingual click-hop. A miss returns a precise reason (e.g. a
    detected login/captcha wall) so the failure is explained, not generic.
    """
    tmp_id = uuid.uuid4().hex[:8]
    tmp_dir = Path(tempfile.gettempdir()) / f"vergabepilot-adaptive-{tmp_id}"
    try:
        ar = await asyncio.to_thread(run_adaptive, url, str(tmp_dir))
        if ar.success and ar.downloaded_files:
            moved = _move_into(scratch, ar.downloaded_files)
            if moved:
                result.downloaded.extend(moved)
                return StrategyOutcome(Strategy.ADAPTIVE, True, len(moved))
        return StrategyOutcome(
            Strategy.ADAPTIVE, False, 0, ar.error or "no documents found",
        )
    except Exception as e:  # noqa: BLE001
        log.warning("phase3.adaptive.error", url=url, error=str(e))
        return StrategyOutcome(Strategy.ADAPTIVE, False, 0, str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


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
        async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
            r = await client.get(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept-Language": "de-DE,de;q=0.9,en;q=0.7",
            })
            html_snippet = r.text
        hits = detect_prompt_injection(html_snippet)
        if hits:
            log.warning("phase3.llm.prompt_injection_in_html", url=url, patterns=hits[:3])
            html_snippet = None
        else:
            sanitized_snippet = sanitize_web_content(html_snippet, max_length=20_000)
    except httpx.ConnectError as e:
        log.warning("phase3.llm.html_fetch_connect_error", url=url, error=str(e))
    except httpx.SSLError as e:
        # Portal has an invalid cert — log clearly and continue without HTML
        log.warning("phase3.llm.html_fetch_ssl_error", url=url, error=str(e))
    except httpx.TimeoutException as e:
        log.warning("phase3.llm.html_fetch_timeout", url=url, error=str(e))
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
    # Only runs when explicitly enabled — disabled by default because it adds
    # 20-30s of Playwright overhead per URL before LLM generation even starts.
    # Enable via ENABLE_ROUTE_LEARNING=true when quality matters more than speed.
    route_map: RouteMap | None = None
    if settings.enable_route_learning:
        try:
            route_map = await asyncio.to_thread(learn_route, url)
            log.info("phase3.route_learning", url=url, learned=route_map.learned,
                     docs=route_map.total_documents_found)
        except Exception as e:  # noqa: BLE001
            log.warning("phase3.route_learning_failed", url=url, error=str(e))
            route_map = None
        # NOTE: CUA preflight fallback intentionally removed — it adds a second
        # full browser session (30-60s) and the stored cua_hint already provides
        # equivalent navigation knowledge to the LLM generator.

    # 6. Domain-deduplication lock: acquire BEFORE generation starts so concurrent
    #    workers for the same domain queue up rather than each calling the LLM.
    lock_acquired = False
    _redis = None
    lock_key = f"vergabepilot:domain_llm_lock:{domain}"
    try:
        import redis as redis_lib
        _redis = redis_lib.from_url(settings.redis_url, socket_timeout=2.0, decode_responses=True)

        # Attempt to acquire the lock immediately
        lock_acquired = bool(
            _redis.set(lock_key, "1", nx=True, ex=settings.domain_llm_lock_ttl)
        )

        if not lock_acquired:
            log.info("phase3.llm.lock_wait", domain=domain, url=url)
            # Another worker holds the lock — poll every 2s until it releases or
            # the lock TTL expires. The lock-holder will write the scraper to the
            # registry on success, so check after each wait.
            max_polls = max(1, int(settings.domain_llm_lock_ttl / 2))
            for poll in range(max_polls):
                await asyncio.sleep(2)
                db.expire_all()
                refreshed = scraper_registry.get_for_domain(db, domain)
                if refreshed and refreshed.source not in ("cua",):
                    log.info(
                        "phase3.llm.dedup_cache_hit",
                        domain=domain, url=url, polls=poll + 1,
                    )
                    ex = await asyncio.to_thread(exec_scraper, refreshed.code, url)
                    scraper_registry.record_outcome(
                        db, refreshed, success=ex.success, runtime=ex.runtime_seconds
                    )
                    if ex.success and ex.downloaded_files:
                        moved = _move_into(scratch, ex.downloaded_files)
                        cleanup_output_dir(ex.output_dir)
                        if moved:
                            result.downloaded.extend(moved)
                            return StrategyOutcome(Strategy.EXISTING, True, len(moved))
                    cleanup_output_dir(ex.output_dir)
                    return StrategyOutcome(
                        Strategy.EXISTING, False, 0, "dedup scraper did not return files"
                    )
                # Re-try acquiring the lock (may have been released)
                lock_acquired = bool(
                    _redis.set(lock_key, "1", nx=True, ex=settings.domain_llm_lock_ttl)
                )
                if lock_acquired:
                    log.info("phase3.llm.lock_acquired_after_wait", domain=domain, polls=poll + 1)
                    break

            if not lock_acquired:
                log.warning(
                    "phase3.llm.lock_timeout_proceeding",
                    domain=domain,
                    ttl=settings.domain_llm_lock_ttl,
                )
        else:
            log.debug("phase3.llm.lock_acquired", domain=domain)

    except Exception as e:  # noqa: BLE001
        # Redis unavailable — proceed without dedup protection, log so ops can investigate
        log.warning("phase3.llm.redis_lock_unavailable", domain=domain, error=str(e))

    report_data = route_map.cua_discovery_report if route_map else None

    # Pull any CUA interaction knowledge stored for this domain.  If the CUA
    # fallback already ran (in a prior job or earlier in this cascade), the
    # recorded trace dramatically improves LLM generation success rates.
    # Expire first: a concurrent worker may have committed a cua_hint after
    # _try_existing loaded this domain's row into the session identity map.
    cua_hint: str | None = None
    try:
        db.expire_all()
        tpl = scraper_registry.get_for_domain(db, domain)
        if tpl and tpl.cua_hint:
            cua_hint = tpl.cua_hint
    except Exception:  # noqa: BLE001
        pass

    try:
        # Acquire the global LLM semaphore before spawning the generation thread.
        # This caps concurrent OpenRouter calls to settings.llm_global_concurrency
        # (default 2) so simultaneous URL batches don't all fire at once and hit
        # the 403 concurrent-call limit on the API key.
        async with _get_llm_sem():
            loop = await asyncio.to_thread(
                _run_loop_sync, url, llm.default_model, route_map, resolved_platform, sanitized_snippet, cua_hint,
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
        if lock_acquired and _redis is not None:
            try:
                _redis.delete(lock_key)
                log.debug("phase3.llm.lock_released", domain=domain)
            except Exception as e:  # noqa: BLE001
                log.warning("phase3.llm.lock_release_failed", domain=domain, error=str(e))


def _run_loop_sync(
    url: str,
    default_model: str | None,
    route_map=None,
    platform: str | None = None,
    html_snippet: str | None = None,
    cua_hint: str | None = None,
):
    """Run the async feedback loop from inside asyncio.to_thread().

    A fresh LLMClient is created here so its httpx.AsyncClient is bound
    to the new event loop started by asyncio.run() — not the outer loop.
    `html_snippet` is the already-sanitized page content forwarded from the
    pipeline so the generator skips its own HTTP fetch.
    `cua_hint` is the recorded CUA interaction trace for this domain, if any.
    """
    llm = LLMClient(default_model=default_model)
    return asyncio.run(run_feedback_loop(
        url=url, llm=llm, route_map=route_map, platform=platform,
        html_snippet=html_snippet, cua_hint=cua_hint,
    ))


async def _try_learned_route(
    db: Session, url: str, domain: str, scratch: Path, result: PipelineResult,
) -> StrategyOutcome:
    """Replay a route the CUA proved works on a prior visit (cheap Playwright).

    Fast-fails when no route was learned for this domain so the cascade moves on
    to CUA. Replay is best-effort: a miss is treated as a normal strategy failure.
    """
    route = scraper_registry.get_learned_route(db, domain)
    if route is None:
        return StrategyOutcome(Strategy.LEARNED_ROUTE, False, 0, "no learned route for domain")

    tmp_id = uuid.uuid4().hex[:8]
    tmp_dir = Path(tempfile.gettempdir()) / f"vergabepilot-learned-{tmp_id}"
    try:
        files = await asyncio.to_thread(replay_learned_route, route.to_dict(), str(tmp_dir))
        moved = _move_into(scratch, files)
        if moved:
            result.downloaded.extend(moved)
            return StrategyOutcome(Strategy.LEARNED_ROUTE, True, len(moved))
        return StrategyOutcome(Strategy.LEARNED_ROUTE, False, 0, "learned route returned no documents")
    except Exception as e:  # noqa: BLE001
        log.warning("phase3.learned_route.error", url=url, error=str(e))
        return StrategyOutcome(Strategy.LEARNED_ROUTE, False, 0, str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


async def _try_cua(
    db: Session, url: str, domain: str, scratch: Path, result: PipelineResult,
) -> StrategyOutcome:
    outcome = await run_agent(
        "playwright_cua", url=url, max_steps=settings.cua_max_steps,
    )
    result.cost_usd += outcome.cost_usd

    # Always persist the CUA interaction trace as a domain hint, regardless of
    # success/failure. Even a failed trace encodes which steps were tried,
    # which selectors were found, and where the agent got stuck — this is
    # valuable context for the next LLM generation attempt on this domain.
    if outcome.trace:
        hint = _format_cua_hint(url, outcome)
        scraper_registry.store_cua_hint(db, domain, hint)

    if outcome.success and outcome.downloaded_files:
        moved = _move_into(scratch, outcome.downloaded_files)
        for f in outcome.downloaded_files:
            cua_dir = str(Path(f).parent)
            if cua_dir and cua_dir != str(scratch):
                cleanup_output_dir(cua_dir)
                break
        if moved:
            result.downloaded.extend(moved)
            # ── CUA route learning ───────────────────────────────────────────
            # The CUA succeeded. If every cheaper strategy already failed for
            # this URL (i.e. CUA was the only thing that worked), learn the route
            # so the next visit to this domain replays it cheaply instead of
            # paying the full CUA cost again. Never let learning break the win.
            await _maybe_learn_route(db, url, domain, outcome, result)
            return StrategyOutcome(Strategy.CUA, True, len(moved))
    return StrategyOutcome(Strategy.CUA, False, 0, outcome.error or "agent failed")


async def _maybe_learn_route(
    db: Session, url: str, domain: str, outcome, result: PipelineResult,
) -> None:
    """Capture & persist a replayable route after a CUA-only success.

    Guards:
      * gated by settings.enable_cua_route_learning,
      * only when at least one cheaper strategy was tried and failed for this
        URL (so a forced/standalone CUA run doesn't trigger learning),
      * learn_from_cua returns None for unreplayable portals (e.g. login walls),
        in which case we keep relying on CUA.
    """
    if not settings.enable_cua_route_learning:
        return
    prior_failures = any(not a.get("success") for a in result.attempts)
    if not prior_failures:
        return
    try:
        route = await asyncio.to_thread(learn_from_cua, url, outcome)
        if route is not None:
            scraper_registry.store_learned_route(db, domain, route)
            write_audit(
                "route_learner.learned",
                f"Learned replayable CUA route for {domain} "
                f"({len(route.steps)} steps, {len(route.document_links)} docs)",
                level=INFO, domain=domain, url=url, strategy=Strategy.CUA.value,
                metadata={"confidence": route.confidence, "learned_via": route.learned_via},
            )
    except Exception as e:  # noqa: BLE001
        log.warning("phase3.cua.route_learning_failed", url=url, error=str(e))


def _format_cua_hint(url: str, outcome) -> str:
    """Convert a CUA AgentRunOutcome trace into a concise text hint for the LLM.

    Captures the step sequence (action type + description), any download
    events, and the final outcome. Capped at 80 steps to stay prompt-friendly.
    """
    lines: list[str] = [
        f"CUA agent ran on: {url}",
        f"Outcome: {'SUCCESS' if outcome.success else 'FAILED'} — steps taken: {outcome.steps}",
    ]
    if outcome.error:
        lines.append(f"Final error: {outcome.error[:300]}")

    lines.append("\nStep-by-step trace:")
    for i, step in enumerate(outcome.trace[:80], 1):
        action = step.get("action") or step.get("type") or "step"
        desc   = step.get("description") or step.get("text") or step.get("url") or ""
        result = step.get("result") or step.get("outcome") or ""
        line   = f"  {i}. [{action}] {str(desc)[:120]}"
        if result:
            line += f" → {str(result)[:80]}"
        lines.append(line)

    if outcome.downloaded_files:
        lines.append(f"\nFiles downloaded: {[Path(f).name for f in outcome.downloaded_files[:10]]}")

    return "\n".join(lines)


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
