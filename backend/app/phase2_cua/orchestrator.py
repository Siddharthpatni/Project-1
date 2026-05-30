"""
Orchestrator / registry for computer-use agents.

Selects an agent by name, runs it, and persists the outcome to the
`agent_runs` table. This is the single entry point the Phase-3 cascaded
pipeline uses for its CUA fallback.

Imports of browser_agent / browser_use_agent are deferred to function
call time so the orchestrator module can be imported even when the
browser-use library is not installed (e.g. in CI/CD test environments).
"""
from __future__ import annotations

from app.phase2_cua.base_agent import AgentRunOutcome


def _build_registry(model_name: str | None = None) -> dict:
    """Build agent registry with lazy imports — safe when browser-use missing."""
    registry: dict = {}
    try:
        from app.phase2_cua.browser_agent import PlaywrightCUA  # noqa: PLC0415
        registry["playwright_cua"] = PlaywrightCUA(model_name=model_name)
    except Exception:  # noqa: BLE001
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
    registry = _build_registry(model_name)
    if agent_name not in registry:
        return AgentRunOutcome(
            success=False,
            error=f"agent '{agent_name}' unavailable (browser-use library not installed or import failed)",
        )
    agent = registry[agent_name]
    return await agent.run(url=url, max_steps=max_steps or 30)


def available_agents() -> list[str]:
    return list(_build_registry().keys())
