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
    cua_discovery_report: str | None = None


# Canonical cascade order — pipeline.py iterates this directly and
# next_strategy() uses it for the break-early check.
#
#   MANUAL      → Phase 0 reference scraper (best-effort legacy)
#   EXISTING    → Registry lookup: cached scraper from a prior successful run
#   DETERMINISTIC → URL-template shortcut for known portal families (DTVP etc.)
#   LLM_GENERATED → Generate + sandbox + feedback loop
#   CUA         → Last-resort visual agent
#
# DETERMINISTIC sits AFTER EXISTING because a working cached scraper is
# preferred: it handles URL variations that the deterministic template may miss.
CASCADE_ORDER: list[Strategy] = [
    Strategy.MANUAL,
    Strategy.EXISTING,
    Strategy.DETERMINISTIC,
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
