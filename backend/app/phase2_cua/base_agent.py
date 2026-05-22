"""
Abstract base class for all computer-use agents.

Each concrete agent (Playwright CUA, Browser-Use CUA, etc.) implements
the same interface so the orchestrator can compare them on the same dataset.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class AgentRunOutcome:
    success: bool
    downloaded_files: list[str] = field(default_factory=list)
    steps: int = 0
    runtime_seconds: float = 0.0
    cost_usd: float = 0.0
    trace: list[dict] = field(default_factory=list)
    error: str | None = None


class BaseAgent(ABC):
    """
    Interface every agent must implement.

    The `run` method takes a URL and a step budget and returns an
    `AgentRunOutcome`. The orchestrator calls `run` and logs the result
    to the `agent_runs` table.
    """

    name: str = "base"

    @abstractmethod
    async def run(self, url: str, max_steps: int) -> AgentRunOutcome: ...
