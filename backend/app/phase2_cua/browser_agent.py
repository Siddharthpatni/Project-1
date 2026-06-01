"""
Playwright-driven computer-use agent.

Uses the `browser-use` library with a vision-capable LLM as the "brain"
and Playwright as the "hands". The agent autonomously observes the page,
decides actions, and executes them in a loop until it finishes or the
step budget is exhausted.
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

# Global semaphore: limit simultaneous Chromium browsers across the process.
# Without this, 100 concurrent jobs each launching CUA will exhaust RAM/CPU
# and cause BrowserType.launch timeouts (the actual observed failure mode).
# Max 2 concurrent browsers per worker process; CUA worker has concurrency=2
# so this effectively limits to 4 system-wide per worker-cua container.
_BROWSER_SEM: asyncio.Semaphore | None = None


def _get_browser_sem() -> asyncio.Semaphore:
    global _BROWSER_SEM
    if _BROWSER_SEM is None:
        _BROWSER_SEM = asyncio.Semaphore(2)
    return _BROWSER_SEM
from app.utils.logger import get_logger

log = get_logger(__name__)

_DOC_SUFFIXES = frozenset({".pdf", ".zip", ".docx", ".xlsx", ".doc", ".xml", ".odt", ".ods"})


def build_agent_task(url: str) -> str:
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
    name = "playwright_cua"

    def __init__(self, model_name: str | None = None):
        self.llm_model = model_name or settings.llm_model_fallback or "openai/gpt-4o-mini"

    async def run(self, url: str, max_steps: int) -> AgentRunOutcome:
        # Acquire global browser semaphore BEFORE launching Chromium.
        # Prevents resource exhaustion when many jobs run CUA simultaneously.
        async with _get_browser_sem():
            return await self._run_with_browser(url, max_steps)

    async def _run_with_browser(self, url: str, max_steps: int) -> AgentRunOutcome:
        t0 = time.time()
        run_id = uuid.uuid4().hex[:8]
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
            disable_security=True,
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )

        # Restrict the agent to browser-only actions — no web search.
        # Relying solely on the task prompt to prevent search is insufficient:
        # adversarial page content or model drift can override prompt instructions.
        # browser-use exposes a `registered_actions` / `available_actions` param;
        # if the current version doesn't support it the Agent falls back gracefully.
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
            # Older browser-use versions don't accept available_actions
            agent = Agent(
                task=build_agent_task(url),
                llm=llm,
                browser=browser,
            )

        try:
            log.info("phase2.playwright_cua.start", url=url)
            result = await agent.run(max_steps=max_steps or 30)

            # Prefer files the browser explicitly tracked; fall back to dir scan.
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
            log.error("phase2.playwright_cua.failed", error=str(e))
            return AgentRunOutcome(success=False, error=f"playwright_cua run failed: {e}")
        finally:
            try:
                await browser.stop()
            except Exception:
                pass
