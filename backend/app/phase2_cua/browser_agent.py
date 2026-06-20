"""
Playwright-driven computer-use agent (primary Phase 2 implementation).

This is the main CUA strategy — used as last resort when all other strategies
(manual, existing, deterministic, LLM-generated) have failed.

How it works:
─────────────
  1. A headless Chromium browser is launched via the `browser-use` library.
  2. A vision-capable LLM (e.g. GPT-4o, Gemini Flash) acts as the "brain":
     it observes a screenshot of the current page and decides the next action.
  3. The browser-use library translates the LLM's decision into a real browser
     action (click, navigate, download, etc.) and executes it.
  4. This loop continues until the agent calls done() or the step budget runs out.

Security constraints:
─────────────────────
  - `available_actions` explicitly excludes web search to prevent the agent from
    leaving the target domain. Adversarial page content could otherwise coax the
    agent to search for credentials or exfiltrate data via a search URL.
  - The browser semaphore prevents > 2 simultaneous Chromium instances per process,
    which is the main cause of BrowserType.launch timeouts under load.

Cost model:
───────────
  CUA is the most expensive strategy (~30-120s, 15K-150K tokens per step × 30 steps).
  The pipeline only reaches here after EXISTING, DETERMINISTIC, and LLM_GENERATED all
  fail, and only when settings.enable_fallback_cua is True.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path
from textwrap import dedent

from browser_use import Agent, Browser
from browser_use.llm.openrouter.chat import ChatOpenRouter

from app.config import settings
from app.phase2_cua.base_agent import AgentRunOutcome, BaseAgent

# ── Global browser semaphore ───────────────────────────────────────────────────
# Limits simultaneous Chromium browsers across the entire worker process.
# Without this, 100 concurrent jobs each launching CUA would exhaust RAM/CPU and
# trigger BrowserType.launch timeouts (the actual observed failure mode in load tests).
# Max 2 concurrent per worker; with CUA worker concurrency=2 this caps at 4 system-wide.
_BROWSER_SEM: asyncio.Semaphore | None = None


def _get_browser_sem() -> asyncio.Semaphore:
    """Lazy-initialise the browser semaphore (must happen inside an event loop)."""
    global _BROWSER_SEM
    if _BROWSER_SEM is None:
        _BROWSER_SEM = asyncio.Semaphore(2)
    return _BROWSER_SEM


from app.utils.logger import get_logger

log = get_logger(__name__)

# File extensions we consider valid procurement documents.
# Used to filter downloads — avoids counting CSS/JS/image files as documents.
_DOC_SUFFIXES = frozenset({".pdf", ".zip", ".docx", ".xlsx", ".doc", ".xml", ".odt", ".ods"})


def build_agent_task(url: str) -> str:
    """
    Construct the natural-language task description given to the LLM agent.

    Key design choices:
    - CRITICAL RULES section is placed first and written in uppercase to make
      it harder for adversarial page content to override via prompt injection.
    - The agent is forbidden from using search engines or leaving the domain —
      this prevents data exfiltration and ensures scraping stays on-target.
    - Immediate stop on 404 prevents the agent from wasting 30 steps navigating
      a dead URL (a common pattern on expired tender portals).
    - Cookie consent dismissal is explicit because most German portals show one;
      without dismissal the agent often wastes steps trying to click under the banner.
    - The step priority (visible downloads first, then tabs) reflects what actually
      works on DTVP/NetServer/Evergabe portals from empirical observation.
    """
    return dedent(f"""
        Your objective is to download public procurement tender documents from a German website.

        Target URL: {url}

        CRITICAL RULES — read before acting:
        - You MUST stay on the Target URL domain. NEVER navigate to any other website,
          search engine, or unrelated page. If you are not on the original domain, stop.
        - If the page returns a 404, "not found", "file not found", or any error page,
          call done() IMMEDIATELY with success=False. Do not try to search or navigate elsewhere.
        - If you cannot find download links after 3 steps, call done() with success=False.
        - NEVER use search engines (DuckDuckGo, Google, Bing) or browse other websites.

        Instructions:
        1. Navigate to the Target URL.
        2. If the page shows a 404 or error — stop immediately (done, failed).
        3. Dismiss any cookie consent banner ("Akzeptieren", "Alle akzeptieren", "Zustimmen").
        4. Look for download buttons/links ALREADY visible (PDF/ZIP icons, "Alle herunterladen").
           Click them directly — do NOT navigate to tabs first if files are visible.
        5. If no downloads visible, look for tabs "Vergabeunterlagen", "Dokumente", "Unterlagen".
           Click the tab, then download the files.
        6. Once downloads are triggered, call done().
    """).strip()


class PlaywrightCUA(BaseAgent):
    """
    Primary CUA implementation using browser-use + Playwright + vision LLM.

    Registered as "playwright_cua" in the orchestrator registry.
    """
    name = "playwright_cua"

    def __init__(self, model_name: str | None = None):
        # Default to the configured fallback model; CUA needs vision capability
        # so don't use the scraper-generation model (Gemini Flash Lite is text-only).
        self.llm_model = model_name or settings.llm_model_fallback or "openai/gpt-4o-mini"

    async def run(self, url: str, max_steps: int) -> AgentRunOutcome:
        # Acquire the global browser semaphore BEFORE launching Chromium.
        # This is the outer gate that prevents RAM exhaustion from concurrent launches.
        async with _get_browser_sem():
            return await self._run_with_browser(url, max_steps)

    async def _run_with_browser(self, url: str, max_steps: int) -> AgentRunOutcome:
        t0 = time.time()
        run_id = uuid.uuid4().hex[:8]
        # Each run gets its own downloads directory so files from concurrent runs
        # don't collide and we can clean up precisely after the run finishes.
        downloads_path = Path("/tmp") / f"vergabepilot-cua-{run_id}"
        downloads_path.mkdir(parents=True, exist_ok=True)

        api_key = settings.openrouter_api_key
        if not api_key:
            return AgentRunOutcome(
                success=False,
                error="OPENROUTER_API_KEY environment variable is missing",
            )

        llm = ChatOpenRouter(
            model=self.llm_model,
            api_key=api_key,
            http_referer="https://vergabepilot.ai",
        )

        browser = Browser(
            headless=True,
            downloads_path=str(downloads_path),
            accept_downloads=True,
            # disable_security=True allows navigating sites with mixed content / CORS
            # restrictions — common on older German procurement portals that embed
            # document iframes from a different subdomain.
            disable_security=True,
            user_agent=(
                # Standard Chrome UA prevents bot-detection fingerprinting.
                # DTVP and several NRW portals actively block requests from
                # non-browser UAs (including Python's default requests UA).
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            args=[
                # Hides Chromium's automation flag from portal bot-detection scripts.
                "--disable-blink-features=AutomationControlled",
                # Required in containerised environments (no SUID sandbox available).
                "--no-sandbox",
            ],
        )

        # Restrict the agent to browser-only actions — explicitly no web search.
        # Relying solely on the task prompt is insufficient: adversarial page content
        # or model drift can override prompt instructions. The available_actions
        # parameter is the hard enforcement layer.
        _ALLOWED_ACTIONS = [
            "navigate", "go_back", "click", "input_text", "scroll",
            "wait", "extract_content", "done", "save_file",
        ]
        try:
            agent = Agent(
                task=build_agent_task(url),
                llm=llm,
                browser=browser,
                available_actions=_ALLOWED_ACTIONS,
            )
        except TypeError:
            # browser-use < 0.1.x doesn't accept `available_actions` — fall back
            # gracefully and rely on the task prompt for search prevention.
            agent = Agent(
                task=build_agent_task(url),
                llm=llm,
                browser=browser,
            )

        try:
            log.info("phase2.playwright_cua.start", url=url)
            result = await agent.run(max_steps=max_steps or 30)

            # Collect downloaded files.
            # Strategy: prefer the browser's own download tracker (most accurate),
            # fall back to scanning the downloads directory (catches edge cases where
            # the tracker misses programmatic downloads triggered by JS redirects).
            downloaded_files: list[str] = []
            try:
                tracked = browser.downloaded_files
                if tracked:
                    downloaded_files = [str(f) for f in tracked if Path(str(f)).suffix.lower() in _DOC_SUFFIXES]
            except Exception:
                pass
            if not downloaded_files:
                # Scan download dir as fallback
                for entry in downloads_path.iterdir():
                    if entry.is_file() and entry.suffix.lower() in _DOC_SUFFIXES:
                        downloaded_files.append(str(entry))

            steps_count = len(result) if result is not None else (max_steps or 30)

            # Estimate cost: assume ~15K input tokens + ~150 output tokens per step
            # (one screenshot + action prompt per vision call). This is a rough
            # approximation — real cost varies by page complexity and response length.
            from app.phase1_llm_scraper.pricing import calc_cost
            cost = calc_cost(steps_count * 15_000, steps_count * 150, self.llm_model)

            return AgentRunOutcome(
                success=bool(downloaded_files),
                downloaded_files=downloaded_files,
                steps=steps_count,
                runtime_seconds=time.time() - t0,
                cost_usd=cost,
                # Store raw state strings in the trace — the pipeline converts these
                # into a human-readable cua_hint text stored in the scraper registry
                # so future LLM generation on this domain gets the verified nav path.
                trace=[{"step": i, "state": str(s)} for i, s in enumerate(result or [])],
            )
        except Exception as e:
            log.error("phase2.playwright_cua.failed", error=str(e))
            return AgentRunOutcome(success=False, error=f"playwright_cua run failed: {e}")
        finally:
            # Always stop the browser even if an exception occurred — leaked Chromium
            # processes are the main source of worker-container memory leaks.
            try:
                await browser.stop()
            except Exception:
                pass
