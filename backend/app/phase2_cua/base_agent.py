"""
Abstract base class and shared data types for all computer-use agents.

Every CUA implementation (PlaywrightCUA, BrowserUseCUA, …) must:
  1. Inherit from BaseAgent
  2. Implement the `run(url, max_steps) → AgentRunOutcome` coroutine

This shared interface lets the orchestrator swap implementations transparently
and the evaluation harness compare agents on identical inputs.

AgentRunOutcome is also the type returned up through the pipeline to
pipeline._try_cua(), which persists it to the agent_runs table and uses
the trace to build a CUA hint for future LLM generation on the same domain.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class AgentRunOutcome:
    """
    The result of one CUA agent session against a single URL.

    Fields:
        success:          True only if at least one document was downloaded.
        downloaded_files: Absolute local paths to files downloaded during the run.
                          Empty on failure.
        steps:            Number of browser actions taken (used for cost estimation).
        runtime_seconds:  Wall-clock time of the agent session.
        cost_usd:         Estimated LLM API cost (vision model calls × token price).
        trace:            Step-by-step record of actions taken. Each entry is a dict
                          with at minimum {"step": int, "state": str}. Stored as JSON
                          in agent_runs.trace and also used to build a cua_hint for
                          the scraper registry so future LLM generation on this domain
                          gets the verified navigation path as context.
        error:            Human-readable failure reason when success=False.
    """
    success: bool
    downloaded_files: list[str] = field(default_factory=list)
    steps: int = 0
    runtime_seconds: float = 0.0
    cost_usd: float = 0.0
    trace: list[dict] = field(default_factory=list)
    error: str | None = None


class BaseAgent(ABC):
    """
    Abstract interface every CUA agent must implement.

    The orchestrator calls `run()` and logs the result to the `agent_runs` table.
    Concrete implementations are responsible for:
      - Launching a headless browser (via Playwright or browser-use)
      - Driving the browser with a vision-capable LLM
      - Collecting downloaded files and returning their local paths
      - Building a step trace that can be used as LLM context in future runs

    The `name` class attribute is used as the registry key in orchestrator.py.
    """

    name: str = "base"

    @abstractmethod
    async def run(self, url: str, max_steps: int) -> AgentRunOutcome:
        """
        Run the agent against a URL within a step budget.

        Args:
            url:       The tender portal URL to scrape.
            max_steps: Hard cap on browser actions — prevents runaway agents from
                       consuming API budget indefinitely on complex portals.

        Returns:
            AgentRunOutcome describing success/failure, files found, and the trace.
        """
        ...
