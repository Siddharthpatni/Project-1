"""
Orchestrator / registry for computer-use agents.

Selects an agent by name, runs it, and persists the outcome to the
`agent_runs` table. This is the single entry point the Phase-3 cascaded
pipeline uses for its CUA fallback.
"""
from __future__ import annotations

from app.phase2_cua.base_agent import AgentRunOutcome, BaseAgent
from app.phase2_cua.browser_agent import PlaywrightCUA
from app.phase2_cua.browser_use_agent import BrowserUseCUA


def _build_registry(model_name: str | None = None) -> dict[str, BaseAgent]:
    return {
        "playwright_cua": PlaywrightCUA(model_name=model_name),
        "browser_use": BrowserUseCUA(model_name=model_name),
    }


async def run_agent(
    agent_name: str,
    url: str,
    max_steps: int | None = None,
    model_name: str | None = None,
    **kwargs,
) -> AgentRunOutcome:
    registry = _build_registry(model_name)
    if agent_name not in registry:
        return AgentRunOutcome(success=False, error=f"unknown agent: {agent_name}")
    agent = registry[agent_name]
    return await agent.run(url=url, max_steps=max_steps or 30)


def available_agents() -> list[str]:
    return list(_build_registry().keys())
