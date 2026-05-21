"""
Browser-Use driven CUA agent implementation.

Integrates the exact pure CUA GUI agent logic from `cua_pure_agent.py`
as a first-class strategy option in Phase 2 CUA.
"""
from __future__ import annotations

import os
import time
import uuid
from pathlib import Path
from textwrap import dedent

from browser_use import Agent, Browser
from langchain_openai import ChatOpenAI

from app.config import settings
from app.phase2_cua.base_agent import AgentRunOutcome, BaseAgent
from app.utils.logger import get_logger

log = get_logger(__name__)


def build_agent_task(url: str) -> str:
    """
    Constructs the target CUA prompt instructions from cua_pure_agent.py.
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


class BrowserUseCUA(BaseAgent):
    name = "browser_use"

    def __init__(self, llm_model: str = "google/gemini-2.5-flash"):
        self.llm_model = llm_model

    async def run(self, url: str, max_steps: int) -> AgentRunOutcome:
        t0 = time.time()
        run_id = str(uuid.uuid4())[:8]
        downloads_path = Path("/tmp/vergabepilot-downloads")
        downloads_path.mkdir(parents=True, exist_ok=True)

        api_key = settings.openrouter_api_key
        if not api_key:
            return AgentRunOutcome(success=False, error="OPENROUTER_API_KEY environment variable is missing")

        # 1. Initialize vision/DOM heavy OpenRouter LLM via standard ChatOpenAI wrapper
        llm = ChatOpenAI(
            model=self.llm_model,
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
        )

        # 2. Configure premium human-mimicking Browser session to bypass anti-bot blocks
        browser = Browser(
            headless=True,
            downloads_path=str(downloads_path),
            accept_downloads=True,
            disable_security=True,
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            window_size=(1280, 800),
            wait_between_actions=0.5,  # 0.5s human-like delay between actions!
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ]
        )
        task_prompt = build_agent_task(url)

        agent = Agent(
            task=task_prompt,
            llm=llm,
            browser=browser
        )

        trace = []
        downloaded_files: list[str] = []

        try:
            log.info("phase2.browser_use.start", url=url)
            # The agent enters its Observation -> Action -> State loop
            result = await agent.run(max_steps=max_steps or 30)
            
            # Find files written in the download directory
            for entry in downloads_path.iterdir():
                if entry.is_file() and entry.suffix.lower() in [".pdf", ".zip", ".docx", ".xlsx", ".doc"]:
                    downloaded_files.append(str(entry))
            
            success = len(downloaded_files) > 0
            return AgentRunOutcome(
                success=success,
                downloaded_files=downloaded_files,
                steps=len(result.history) if hasattr(result, "history") else max_steps,
                runtime_seconds=time.time() - t0,
                cost_usd=0.0, # Tracked internally by OpenRouter
                trace=[{"step": i, "state": str(s)} for i, s in enumerate(getattr(result, "history", []))],
            )
        except Exception as e:
            log.error("phase2.browser_use.failed", error=str(e))
            return AgentRunOutcome(success=False, error=f"browser_use run failed: {e}")
        finally:
            await browser.stop()
