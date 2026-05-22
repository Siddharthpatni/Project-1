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


# Order encoded once so the pipeline driver and the fallback policy stay
# in sync. DETERMINISTIC slots between EXISTING and LLM_GENERATED: it's
# cheaper than the LLM and produces fewer false positives than a stale
# registry entry.
CASCADE_ORDER: list[Strategy] = [
    Strategy.DETERMINISTIC,
    Strategy.MANUAL,
    Strategy.EXISTING,
    Strategy.LLM_GENERATED,
    Strategy.CUA,
]


def next_strategy(current: Strategy, outcome: StrategyOutcome, enable_cua: bool) -> Strategy | None:
    """
    Return the next strategy to try, or None if the cascade is exhausted.

    Cascade order:
        MANUAL → EXISTING → DETERMINISTIC → LLM_GENERATED → CUA → (stop)
    """
    if outcome.success:
        return None

    try:
        idx = CASCADE_ORDER.index(current)
    except ValueError:
        return Strategy.EXISTING  # safe default if forced into an unknown state

    for nxt in CASCADE_ORDER[idx + 1:]:
        if nxt is Strategy.CUA and not enable_cua:
            return None
        return nxt
    return None
