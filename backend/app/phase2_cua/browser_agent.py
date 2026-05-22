"""
Playwright-driven computer-use agent.

Uses the `browser-use` library with a vision-capable LLM as the "brain"
and Playwright as the "hands". The agent autonomously observes the page,
decides actions, and executes them in a loop until it finishes or the
step budget is exhausted.

This mirrors the proven logic from `cua_pure_agent.py` in the archive,
adapted as a first-class strategy in the Phase 2 CUA orchestrator.
"""
from __future__ import annotations

import time
import uuid
from pathlib import Path
from textwrap import dedent

from pydantic import computed_field

from browser_use import Agent, Browser
from browser_use.llm.openrouter.chat import ChatOpenRouter

from app.config import settings
from app.phase2_cua.base_agent import AgentRunOutcome, BaseAgent
from app.utils.logger import get_logger

log = get_logger(__name__)


# ── Task prompt ────────────────────────────────────────────────────────
# Follows the exact proven structure from cua_pure_agent.py

def build_agent_task(url: str) -> str:
    """
    Constructs the CUA prompt instructing the agent how to interact
    with German public procurement tender pages visually.
    """
    return dedent(f"""
        Your objective is to download public procurement tender documents from a German website.
        
        Target URL: {url}
        
        Instructions:
        1. Navigate to the Target URL.
        2. Immediately look for a cookie consent banner. If present, click "Akzeptieren", "Alle akzeptieren", or "Zustimmen".
        3. Direct Download Execution: Check if the document links, file icons, or download buttons are ALREADY visible on the page (e.g., in a table or list).
           - German public procurement notice tables often feature direct download icons (like PDF, ZIP, or download arrow columns).
           - If you see any such download icons, buttons, or direct links — SKIP clicking tabs (like "Vergabeunterlagen", "Ausschreibungsunterlagen", "Unterlagen")! Immediately trigger the download actions on those files/buttons.
        4. Tab Discovery (Fallback): If no download files or tables are visible, scan the page for tabs, sections, list items, or buttons related to tender documents. Common German labels include "Vergabeunterlagen", "Dokumente", or "Unterlagen". Click them to reveal the file listing.
        5. Click the download buttons/links to initiate the downloads.
        6. VISUAL VERIFICATION: Before finishing, look at the screen and confirm that the documents you intended to download are indeed represented as having been clicked or initiated. If there is a "Downloads" status or a change in the button state, verify it visually.
        7. Once you have successfully initiated the downloads and visually verified the action, conclude the task successfully.
    """).strip()


# ── Agent implementation ───────────────────────────────────────────────

class PlaywrightCUA(BaseAgent):
    name = "playwright_cua"

    def __init__(self, model_name: str | None = None):
        self.llm_model = model_name or "google/gemini-2.5-flash"

    async def run(self, url: str, max_steps: int) -> AgentRunOutcome:
        t0 = time.time()
        downloads_path = Path("/tmp/vergabepilot-downloads")
        downloads_path.mkdir(parents=True, exist_ok=True)

        api_key = settings.openrouter_api_key
        if not api_key:
            return AgentRunOutcome(
                success=False,
                error="OPENROUTER_API_KEY environment variable is missing",
            )

        # 1. Initialise the LLM with OpenRouter
        llm = ChatOpenRouter(
            model=self.llm_model,
            api_key=api_key,
        )

        # 2. Configure browser session
        #    Follows the same minimal setup as cua_pure_agent.py:
        #    headless + downloads path — browser-use handles the rest.
        browser = Browser(
            headless=True,
            downloads_path=str(downloads_path),
            disable_security=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )

        task_prompt = build_agent_task(url)

        agent = Agent(
            task=task_prompt,
            llm=llm,
            browser=browser,
        )

        try:
            log.info("phase2.playwright_cua.start", url=url)
            result = await agent.run(max_steps=max_steps or 30)

            # Collect any downloaded files
            downloaded_files: list[str] = []
            for entry in downloads_path.iterdir():
                if entry.is_file() and entry.suffix.lower() in [
                    ".pdf", ".zip", ".docx", ".xlsx", ".doc", ".xml",
                ]:
                    downloaded_files.append(str(entry))

            success = len(downloaded_files) > 0
            return AgentRunOutcome(
                success=success,
                downloaded_files=downloaded_files,
                steps=len(result.history) if hasattr(result, "history") else max_steps,
                runtime_seconds=time.time() - t0,
                cost_usd=0.0,
                trace=[
                    {"step": i, "state": str(s)}
                    for i, s in enumerate(getattr(result, "history", []))
                ],
            )
        except Exception as e:
            log.error("phase2.playwright_cua.failed", error=str(e))
            return AgentRunOutcome(
                success=False, error=f"playwright_cua run failed: {e}"
            )
        finally:
            await browser.stop()
