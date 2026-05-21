"""
Playwright-driven computer-use agent.

Uses a vision-capable LLM as the "brain" and Playwright as the "hands".
At each step:
  1. Capture a screenshot + DOM outline.
  2. Send to LLM with the action schema.
  3. Parse the chosen action and execute it against the Playwright page.
  4. Repeat until the agent emits `finish` or the step budget is exhausted.

This is the reference implementation for Phase 2. Other agents (e.g. one
wired to the Anthropic / OpenAI computer-use APIs) can be added as
sibling files and registered in orchestrator.AGENT_REGISTRY.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from textwrap import dedent

from app.config import settings
from app.core.llm_client import LLMClient
from app.phase2_cua.action_space import (
    ACTION_SCHEMA,
    Action,
    Click,
    DownloadLink,
    Finish,
    Navigate,
    Scroll,
    Type,
    WaitFor,
    from_dict,
)
from app.phase2_cua.base_agent import AgentRunOutcome, BaseAgent
from app.phase2_cua.screenshot import save_screenshot
from app.utils.logger import get_logger

log = get_logger(__name__)

SYSTEM_PROMPT = dedent(f"""
    You are a computer-use agent browsing a German / EU public procurement website.
    Your goal is to locate and download every tender document (PDF, DOCX, ZIP, XML) linked from the current page.

    Follow this structured, reliable logic:
    1. Navigation & Consent: Immediately after navigation, scan the viewport for any cookie consent banner or privacy overlays. If found, prioritize clicking options labeled "Akzeptieren", "Alle akzeptieren", "Zustimmen", or "OK" to clear the view.
    2. Direct Download Execution: Check if the document links, file icons, or download buttons are ALREADY visible on the screen. 
       - If you see a table listing files, or individual PDF/ZIP buttons, or a unified download button like "Gesamt-ZIP herunterladen", "Unterlagen herunterladen", "Dokumente herunterladen", "Download ZIP", or "Download PDF" — SKIP clicking tabs! Immediately trigger the download actions on those files/buttons.
    3. Tab Discovery (Fallback): If no download files or tables are visible, only then scan the page for tabs, sections, list items, or buttons related to tender documents. Actively look for labels like "Vergabeunterlagen", "Dokumente", "Unterlagen", "Ausschreibungsunterlagen", or "Dateien". Click them to reveal file download nodes.
    4. Action Schema Selection: Choose the optimal action to progress. Respond with a SINGLE JSON object describing the action. Do not wrap in markdown.
    
    The available action types and fields are:
    {json.dumps(ACTION_SCHEMA, indent=2)}

    Strategy hints:
    - On tables, look for file extension icons (.pdf, .zip) or download icon columns, and trigger their download.
    - Prefer `download_link` with a CSS selector over `click` with pixel coordinates when you can identify a stable selector.
    - If standard CSS selectors are obfuscated or dynamic, use precise pixel coordinate clicks `{"type": "click", "x": ..., "y": ...}` centered on the PDF or ZIP icons visible in the screenshot.
    - Use `wait_for` after navigation or clicks to let dynamic elements and file listings render.
    - VISUAL VERIFICATION: Before concluding the run with `finish`, look at the page and confirm that the document download actions have been successfully triggered or represented on the screen.
    - Emit `finish` with a descriptive reason when all tender documents are saved and visually verified.
""").strip()


class PlaywrightCUA(BaseAgent):
    name = "playwright_cua"

    def __init__(self, llm: LLMClient):
        self.llm = llm

    async def run(self, url: str, max_steps: int) -> AgentRunOutcome:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return AgentRunOutcome(success=False, error="playwright not installed")

        max_steps = max_steps or settings.cua_max_steps
        run_id = str(uuid.uuid4())[:8]
        downloads: list[str] = []
        trace: list[dict] = []
        total_cost = 0.0

        t0 = time.time()

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context(accept_downloads=True)
            page = await context.new_page()

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            except Exception as e:  # noqa: BLE001
                await browser.close()
                return AgentRunOutcome(success=False, error=f"navigation failed: {e}")

            conversation: list[dict] = []

            for step in range(1, max_steps + 1):
                # 1. Screenshot
                png = await page.screenshot(full_page=False)
                shot = save_screenshot(png, run_id=run_id, step=step)

                # 2. Ask the LLM for the next action
                user_msg = (
                    f"Step {step}/{max_steps}. Current URL: {page.url}\n"
                    f"Documents downloaded so far: {len(downloads)}\n"
                    f"Respond with one JSON action."
                )
                try:
                    resp = await self.llm.chat_with_image(
                        system=SYSTEM_PROMPT,
                        user=user_msg,
                        image_b64=shot.to_base64(),
                        model=settings.llm_model_vision,
                    )
                except Exception as e:  # noqa: BLE001
                    trace.append({"step": step, "error": f"llm call failed: {e}"})
                    break

                total_cost += resp.cost_usd
                action = _parse_action(resp.text)

                trace.append({
                    "step": step,
                    "url": page.url,
                    "action": action.__dict__,
                    "screenshot": shot.path,
                })

                # 3. Execute
                if isinstance(action, Finish):
                    log.info("phase2.agent.finish", reason=action.reason)
                    break

                try:
                    await _apply_action(page, action, downloads)
                except Exception as e:  # noqa: BLE001
                    trace[-1]["error"] = str(e)

            await browser.close()

        return AgentRunOutcome(
            success=len(downloads) > 0,
            downloaded_files=downloads,
            steps=len(trace),
            runtime_seconds=time.time() - t0,
            cost_usd=total_cost,
            trace=trace,
        )


# ---------- helpers --------------------------------------------------


def _parse_action(text: str) -> Action:
    text = text.strip()
    # LLMs sometimes wrap in ```json despite the instruction
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return from_dict(json.loads(text))
    except Exception as e:  # noqa: BLE001
        log.warning("phase2.action.parse_failed", error=str(e), text=text[:200])
        return Finish(reason=f"failed to parse action: {e}")


async def _apply_action(page, action: Action, downloads: list[str]) -> None:
    if isinstance(action, Navigate):
        await page.goto(action.url, wait_until="domcontentloaded", timeout=30_000)
    elif isinstance(action, Click):
        await page.mouse.click(action.x, action.y)
    elif isinstance(action, Type):
        await page.keyboard.type(action.text)
    elif isinstance(action, Scroll):
        await page.mouse.wheel(0, action.dy)
    elif isinstance(action, WaitFor):
        await page.wait_for_selector(action.selector, timeout=action.timeout_ms)
    elif isinstance(action, DownloadLink):
        async with page.expect_download() as dl_info:
            await page.click(action.selector)
        download = await dl_info.value
        out = Path("/tmp/vergabepilot-downloads") / download.suggested_filename
        out.parent.mkdir(parents=True, exist_ok=True)
        await download.save_as(str(out))
        downloads.append(str(out))
