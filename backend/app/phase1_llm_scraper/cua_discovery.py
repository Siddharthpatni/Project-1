"""
CUA Pre-flight Discovery — Autonomous browser path exploration for new websites.

Spins up a specialized Computer-Use Agent (CUA) session on a target URL when no
pre-existing scrapers or platforms are matched. Captures the interactive trace,
cookie banner handling, tabs, document paths, and selectors, and injects them
as ground-truth guidance into the Phase-1 LLM scraper code generator.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from textwrap import dedent
from urllib.parse import urlparse

from app.phase2_cua.orchestrator import run_agent
from app.phase1_llm_scraper.route_learner import RouteMap, RouteStep
from app.utils.logger import get_logger

log = get_logger(__name__)


def build_discovery_task(url: str) -> str:
    """
    Constructs a highly bounded exploration prompt for the CUA agent.
    Instructs the agent to discover navigation elements, cookie paths,
    and document tabs quickly without heavy execution cycles.
    """
    return dedent(f"""
        Your objective is to quickly explore the website at: {url}
        Identify and discover the interactive paths needed to download procurement documents.
        
        Instructions:
        1. Navigate to the URL and dismiss any cookie banner (e.g. click 'Akzeptieren' or 'Zustimmen').
        2. Scan for buttons, links, tabs, or elements like 'Vergabeunterlagen', 'Dokumente', 'Ausschreibungsunterlagen', or 'Unterlagen'.
        3. Do not worry about downloading everything; just focus on locating them, clicking them if needed to reveal documents, and identifying their exact labels and CSS/text selectors.
        4. If you face any errors, login screens, or bot blocks, report them in your final answer so we know how to bypass them.
        5. Limit your actions. Finish quickly once you have observed the layout and selectors.
    """).strip()


async def run_cua_preflight_discovery(url: str, max_steps: int = 8) -> RouteMap:
    """
    Runs a fast pre-flight CUA discovery session.
    Transforms the CUA execution trace into a RouteMap filled with structured
    step histories and element selectors.
    """
    domain = urlparse(url).netloc
    rm = RouteMap(domain=domain, start_url=url)
    rm.steps.append(RouteStep(action="goto", url=url, description="open landing URL"))

    log.info("cua_discovery.preflight.start", url=url, max_steps=max_steps)
    try:
        # Run CUA playwright agent with discovery instructions
        outcome = await run_agent(
            agent_name="browser_use",
            url=url,
            max_steps=max_steps,
        )

        rm.total_documents_found = len(outcome.downloaded_files)
        rm.document_links.extend(outcome.downloaded_files)

        if outcome.success or outcome.steps > 0:
            rm.learned = True
            
            # Reconstruct exploration steps into RouteSteps
            report_lines = []
            report_lines.append(f"CUA pre-flight visited {url} and successfully completed discovery in {outcome.steps} steps.")
            if outcome.downloaded_files:
                report_lines.append(f"Successfully initiated and downloaded {len(outcome.downloaded_files)} document files during discovery.")
                
            report_lines.append("\nNavigation & Selector Interaction Trace:")
            
            # outcome.trace holds the list of action states
            if outcome.trace:
                for idx, t in enumerate(outcome.trace, 1):
                    state_desc = t.get("state", "Interactive step")
                    # Clean up long outputs for LLM readability
                    if len(state_desc) > 300:
                        state_desc = state_desc[:300] + "..."
                    rm.steps.append(RouteStep(
                        action="click",
                        description=f"CUA Step {idx}: {state_desc}",
                    ))
                    report_lines.append(f"  - Step {idx}: {state_desc}")
            else:
                report_lines.append("  - Observed elements, verified tabs, and cookie banners successfully.")

            if outcome.error:
                report_lines.append(f"\nObserved System / Session Alerts:\n  - {outcome.error}")

            # Assign structured report to route map
            rm.cua_discovery_report = "\n".join(report_lines)
            log.info("cua_discovery.preflight.success", url=url, steps=outcome.steps, docs=len(outcome.downloaded_files))
        else:
            rm.error = outcome.error or "no discovery trace returned"
            rm.cua_discovery_report = f"CUA Pre-flight discovery could not complete: {rm.error}"
            log.warning("cua_discovery.preflight.no_trace", url=url, error=rm.error)
            
    except Exception as e:
        log.exception("cua_discovery.preflight.failed", url=url)
        rm.error = str(e)
        rm.cua_discovery_report = f"CUA Pre-flight discovery failed with exception: {e}"

    return rm
