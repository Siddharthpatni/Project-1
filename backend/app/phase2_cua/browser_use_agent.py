"""
Alternative browser-use CUA agent — secondary Phase 2 strategy.

Functionally identical to PlaywrightCUA but:
  - Registered under a different name ("browser_use") so the evaluation harness
    can benchmark both agents independently on the same URL dataset.
  - Uses a simpler task prompt (no CRITICAL RULES section) to test whether strict
    constraints improve or hurt success rate in practice.
  - Adds wait_between_actions=0.5s to slow down interactions on portals with
    rate-limiting or JS-heavy rendering (some DTVP portals throttle rapid clicks).

Shares the global browser semaphore from browser_agent.py to keep the total
concurrent Chromium count capped across both implementations.
"""
from __future__ import annotations

import time
import uuid
from pathlib import Path
from textwrap import dedent

from browser_use import Agent, Browser
from browser_use.llm.openrouter.chat import ChatOpenRouter

from app.config import settings
from app.phase2_cua.base_agent import AgentRunOutcome, BaseAgent
# Import the shared semaphore — both PlaywrightCUA and BrowserUseCUA count against
# the same 2-browser limit per worker to prevent memory exhaustion.
from app.phase2_cua.browser_agent import _get_browser_sem
from app.utils.logger import get_logger

log = get_logger(__name__)

# Same document extensions as PlaywrightCUA — used to filter directory scan results.
_DOC_SUFFIXES = frozenset({".pdf", ".zip", ".docx", ".xlsx", ".doc", ".xml", ".odt", ".ods"})


def build_agent_task(url: str) -> str:
    """
    Build the task prompt for this agent.

    Intentionally simpler than PlaywrightCUA's prompt — no CRITICAL RULES block —
    to allow the evaluation harness to test whether strict constraints help or hurt.
    """
    return dedent(f"""
        Your objective is to download public procurement tender documents from a German website.

        Target URL: {url}

        Instructions:
        1. Navigate to the Target URL.
        2. Dismiss any cookie consent banner ("Akzeptieren", "Alle akzeptieren", "Zustimmen").
        3. If document download icons/buttons are already visible, click them directly.
        4. Otherwise look for tabs/sections labelled "Vergabeunterlagen", "Dokumente",
           or "Unterlagen" and click them to reveal the file listing.
        5. Click all download buttons/links to initiate the downloads.
        6. Visually verify downloads were triggered, then conclude.
    """).strip()


class BrowserUseCUA(BaseAgent):
    """
    Secondary CUA implementation using browser-use library.

    Registered as "browser_use" in the orchestrator registry.
    Not used in the production cascade (pipeline always calls "playwright_cua");
    available for manual benchmarking via the /api/agents/run endpoint.
    """
    name = "browser_use"

    def __init__(self, model_name: str | None = None):
        self.llm_model = model_name or settings.llm_model_fallback or "openai/gpt-4o-mini"

    async def run(self, url: str, max_steps: int) -> AgentRunOutcome:
        # Shared semaphore caps total Chromium instances across both CUA implementations.
        async with _get_browser_sem():
            return await self._run_with_browser(url, max_steps)

    async def _run_with_browser(self, url: str, max_steps: int) -> AgentRunOutcome:
        t0 = time.time()
        run_id = uuid.uuid4().hex[:8]
        downloads_path = Path("/tmp") / f"vergabepilot-bu-{run_id}"
        downloads_path.mkdir(parents=True, exist_ok=True)

        api_key = settings.openrouter_api_key
        if not api_key:
            return AgentRunOutcome(success=False, error="OPENROUTER_API_KEY missing")

        llm = ChatOpenRouter(
            model=self.llm_model,
            api_key=api_key,
            http_referer="https://vergabepilot.ai",
        )

        browser = Browser(
            headless=True,
            downloads_path=str(downloads_path),
            accept_downloads=True,
            disable_security=True,
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            # Slight delay between actions helps on portals that debounce rapid clicks
            # or that use JS animations between navigation states.
            wait_between_actions=0.5,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )

        agent = Agent(
            task=build_agent_task(url),
            llm=llm,
            browser=browser,
        )

        try:
            log.info("phase2.browser_use.start", url=url)
            result = await agent.run(max_steps=max_steps or 30)

            # Collect downloaded files — same two-stage strategy as PlaywrightCUA:
            # prefer browser tracker, fall back to directory scan.
            downloaded_files: list[str] = []
            try:
                tracked = browser.downloaded_files
                if tracked:
                    downloaded_files = [str(f) for f in tracked if Path(str(f)).suffix.lower() in _DOC_SUFFIXES]
            except Exception:
                pass
            if not downloaded_files:
                for entry in downloads_path.iterdir():
                    if entry.is_file() and entry.suffix.lower() in _DOC_SUFFIXES:
                        downloaded_files.append(str(entry))

            steps_count = len(result) if result is not None else (max_steps or 30)
            from app.phase1_llm_scraper.pricing import calc_cost
            cost = calc_cost(steps_count * 15_000, steps_count * 150, self.llm_model)

            return AgentRunOutcome(
                success=bool(downloaded_files),
                downloaded_files=downloaded_files,
                steps=steps_count,
                runtime_seconds=time.time() - t0,
                cost_usd=cost,
                trace=[{"step": i, "state": str(s)} for i, s in enumerate(result or [])],
            )
        except Exception as e:
            log.error("phase2.browser_use.failed", error=str(e))
            return AgentRunOutcome(success=False, error=f"browser_use run failed: {e}")
        finally:
            try:
                await browser.stop()
            except Exception:
                pass
