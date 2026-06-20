"""
Phase 2 Computer-Use Agent orchestrator.

This module is the single entry point through which the Phase 3 cascade pipeline
triggers CUA fallback. It maintains a registry of available CUA implementations and
dispatches to the right one by name.

Available agents:
  - playwright_cua : primary — uses browser-use + Playwright + vision LLM
  - browser_use    : secondary — same library, slightly different task prompt
                     (registered separately so the eval harness can compare them)

Why lazy imports?
─────────────────
The browser-use library (and Playwright) require a running Chromium installation.
In CI/CD environments, unit-test containers, and minimal Docker images, Playwright
may not be installed. Importing browser_agent / browser_use_agent at module load
time would crash the entire backend on import. Deferring imports to _build_registry()
means the backend starts successfully in any environment, and CUA just reports itself
as unavailable if the dependency is missing.
"""
from __future__ import annotations

from app.phase2_cua.base_agent import AgentRunOutcome


def _build_registry(model_name: str | None = None) -> dict:
    """
    Construct the agent registry by attempting to import each agent class.

    Each import is wrapped in a try/except so that a missing dependency (e.g.
    browser-use not installed) silently skips that agent rather than crashing.
    The caller can check the returned dict to see which agents are available.

    Args:
        model_name: Optional LLM model override forwarded to each agent constructor.
                    When None, each agent uses its configured default.

    Returns:
        dict mapping agent_name → agent instance (only successfully imported agents).
    """
    registry: dict = {}
    try:
        from app.phase2_cua.browser_agent import PlaywrightCUA  # noqa: PLC0415
        registry["playwright_cua"] = PlaywrightCUA(model_name=model_name)
    except Exception:  # noqa: BLE001
        # Playwright or browser-use not installed — skip silently
        pass
    try:
        from app.phase2_cua.browser_use_agent import BrowserUseCUA  # noqa: PLC0415
        registry["browser_use"] = BrowserUseCUA(model_name=model_name)
    except Exception:  # noqa: BLE001
        pass
    return registry


async def run_agent(
    agent_name: str,
    url: str,
    max_steps: int | None = None,
    model_name: str | None = None,
    **kwargs,
) -> AgentRunOutcome:
    """
    Run the named CUA agent against a URL and return the outcome.

    Called by:
      - pipeline._try_cua() as the last fallback in the cascade
      - routes_agents.trigger_cua() for manual benchmark runs

    Args:
        agent_name:  One of the keys in the registry (e.g. "playwright_cua").
        url:         The tender portal URL to scrape.
        max_steps:   Maximum number of browser actions before giving up. Default 30.
        model_name:  Vision LLM model override (e.g. "openai/gpt-4o"). Falls back
                     to settings.llm_model_fallback when None.

    Returns:
        AgentRunOutcome with success flag, downloaded file paths, step count,
        cost estimate, and the full step trace for audit persistence.
    """
    registry = _build_registry(model_name)
    if agent_name not in registry:
        # Return a structured failure — never raise so the pipeline can continue
        return AgentRunOutcome(
            success=False,
            error=f"agent '{agent_name}' unavailable (browser-use library not installed or import failed)",
        )
    agent = registry[agent_name]
    return await agent.run(url=url, max_steps=max_steps or 30)


def available_agents() -> list[str]:
    """Return the names of all CUA agents that can be instantiated right now.

    Used by the admin API to report which agents are available in this environment.
    An empty list means browser-use / Playwright is not installed.
    """
    return list(_build_registry().keys())
