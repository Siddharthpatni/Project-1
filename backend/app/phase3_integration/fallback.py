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
#   EXISTING      → Registry lookup: reuse cached domain-specific scraper (Phase 3 primary)
#   DETERMINISTIC → Free URL-template shortcut for DTVP/Satellite family (no LLM, no browser)
#   ADAPTIVE      → Free country/language-agnostic heuristic scraper for any portal (no LLM)
#   LLM_GENERATED → Generate new scraper via LLM feedback loop + sandbox (Phase 1)
#   LEARNED_ROUTE → Replay a route the CUA proved works on a prior visit (cheap Playwright, no LLM)
#   CUA           → Last-resort visual agent; trace saved back to registry (Phase 2)
#   MANUAL        → Phase 0 legacy reference scraper; tried only when everything else fails
#
# Per the Phase 3 spec: reuse → LLM generate → CUA fallback.
# DETERMINISTIC and ADAPTIVE are inserted before LLM as zero-cost fast paths —
# ADAPTIVE is the universal heuristic catch-all that serves ordinary public
# portals for free, saving the LLM budget for genuinely hard ones.
# LEARNED_ROUTE sits right before CUA: if a previous CUA-only success was learned
# for this domain, replay it cheaply instead of paying the full CUA cost again.
# MANUAL is kept at the end as a last-ditch attempt for portals it still covers.
CASCADE_ORDER: list[Strategy] = [
    Strategy.EXISTING,
    Strategy.DETERMINISTIC,
    Strategy.ADAPTIVE,
    Strategy.LLM_GENERATED,
    Strategy.LEARNED_ROUTE,
    Strategy.CUA,
    Strategy.MANUAL,
]


def next_strategy(
    current: Strategy,
    outcome: StrategyOutcome,
    enable_cua: bool,
    order: list[Strategy] | None = None,
) -> Strategy | None:
    """
    Return the next strategy to try, or None if the cascade is exhausted.

    ``order`` is the *actual* strategy order the pipeline is executing for this
    URL — it is URL-type-specific (see ``url_intelligence.get_strategy_order``)
    and often places MANUAL in the middle rather than last. We MUST advance
    within that order, not within the canonical ``CASCADE_ORDER`` default;
    otherwise a strategy that happens to be last in ``CASCADE_ORDER`` (e.g.
    MANUAL) would falsely terminate the cascade and skip the LLM/CUA steps that
    still follow it in the tuned order.

    When ``current`` isn't found in ``order`` we return None (the caller's loop
    already iterates the full order, so a missing entry just means "stop here").
    A disabled CUA is skipped over rather than terminating the cascade, so any
    later strategy (e.g. MANUAL after CUA) still runs.
    """
    if outcome.success:
        return None

    seq = order or CASCADE_ORDER
    try:
        idx = seq.index(current)
    except ValueError:
        return None

    for nxt in seq[idx + 1:]:
        if nxt is Strategy.CUA and not enable_cua:
            continue  # skip CUA but keep looking for later strategies
        return nxt
    return None
