"""
Playwright-driven computer-use agent.

Uses the `browser-use` library with a vision-capable LLM as the "brain"
and Playwright as the "hands". The agent autonomously observes the page,
decides actions, and executes them in a loop until it finishes or the
step budget is exhausted.
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
from app.utils.logger import get_logger

log = get_logger(__name__)

_DOC_SUFFIXES = frozenset({".pdf", ".zip", ".docx", ".xlsx", ".doc", ".xml", ".odt", ".ods"})


def build_agent_task(url: str) -> str:
    return dedent(f"""
        Your objective is to download public procurement tender documents from a German website.

        Target URL: {url}

        Instructions:
        1. Navigate to the Target URL.
        2. Immediately look for a cookie consent banner. If present, click
           "Akzeptieren", "Alle akzeptieren", or "Zustimmen".
        3. Direct Download Execution: Check if document links, file icons, or
           download buttons are ALREADY visible (e.g. in a table or list).
           German portals often show PDF/ZIP download icons directly — if so,
           click them WITHOUT navigating to tabs like "Vergabeunterlagen" first.
        4. Tab Discovery (Fallback): If no download files are visible, look for
           tabs or sections labelled "Vergabeunterlagen", "Dokumente", or
           "Unterlagen" and click them to reveal the file listing.
        5. Click all download buttons/links to initiate the downloads.
        6. Visually verify that downloads were triggered, then conclude.
    """).strip()


class PlaywrightCUA(BaseAgent):
    name = "playwright_cua"

    def __init__(self, model_name: str | None = None):
        self.llm_model = model_name or settings.llm_model_fallback or "openai/gpt-4o-mini"

    async def run(self, url: str, max_steps: int) -> AgentRunOutcome:
        t0 = time.time()
        # Isolate downloads per run so concurrent jobs never contaminate each other.
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
