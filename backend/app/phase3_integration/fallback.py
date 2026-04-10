"""
Fallback policy for the cascaded pipeline.

Encapsulates the decision of whether to move on from one strategy to
the next. Kept separate from `pipeline.py` so it can be unit-tested and
swapped out for experiments.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.models import Strategy


@dataclass
class StrategyOutcome:
    strategy: Strategy
    success: bool
    downloaded: int
    error: str | None = None


def next_strategy(current: Strategy, outcome: StrategyOutcome, enable_cua: bool) -> Strategy | None:
    """
    Return the next strategy to try, or None if the cascade is exhausted.

    Cascade order:
        EXISTING  →  LLM_GENERATED  →  CUA  →  (stop)
    """
    if outcome.success:
        return None

    if current is Strategy.EXISTING:
        return Strategy.LLM_GENERATED
    if current is Strategy.LLM_GENERATED:
        return Strategy.CUA if enable_cua else None
    if current is Strategy.CUA:
        return None
    return Strategy.EXISTING
