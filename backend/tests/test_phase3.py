"""Unit tests for Phase 3 fallback + versioning."""
from app.models import Strategy
from app.phase3_integration.fallback import StrategyOutcome, next_strategy
from app.phase3_integration.versioning import compare_snapshots


# ---------- fallback ----------

def test_success_stops_cascade():
    out = StrategyOutcome(Strategy.EXISTING, success=True, downloaded=3)
    assert next_strategy(Strategy.EXISTING, out, enable_cua=True) is None


def test_existing_to_deterministic():
    """EXISTING now falls through to DETERMINISTIC (the new platform-template strategy)."""
    out = StrategyOutcome(Strategy.EXISTING, success=False, downloaded=0)
    assert next_strategy(Strategy.EXISTING, out, enable_cua=True) is Strategy.DETERMINISTIC


def test_deterministic_to_adaptive():
    """When the deterministic template doesn't apply, fall through to the free
    universal adaptive scraper before spending LLM budget."""
    out = StrategyOutcome(Strategy.DETERMINISTIC, success=False, downloaded=0)
    assert next_strategy(Strategy.DETERMINISTIC, out, enable_cua=True) is Strategy.ADAPTIVE


def test_adaptive_to_llm():
    out = StrategyOutcome(Strategy.ADAPTIVE, success=False, downloaded=0)
    assert next_strategy(Strategy.ADAPTIVE, out, enable_cua=True) is Strategy.LLM_GENERATED


def test_llm_to_learned_route():
    """LLM_GENERATED now falls through to LEARNED_ROUTE (replay a CUA-learned path)."""
    out = StrategyOutcome(Strategy.LLM_GENERATED, success=False, downloaded=0)
    assert next_strategy(Strategy.LLM_GENERATED, out, enable_cua=True) is Strategy.LEARNED_ROUTE


def test_learned_route_to_cua():
    out = StrategyOutcome(Strategy.LEARNED_ROUTE, success=False, downloaded=0)
    assert next_strategy(Strategy.LEARNED_ROUTE, out, enable_cua=True) is Strategy.CUA


def test_cua_disabled():
    """With CUA disabled the cascade still reaches LEARNED_ROUTE (cheap, no CUA),
    then stops there because the only remaining step (CUA) is gated off."""
    out = StrategyOutcome(Strategy.LLM_GENERATED, success=False, downloaded=0)
    assert next_strategy(Strategy.LLM_GENERATED, out, enable_cua=False) is Strategy.LEARNED_ROUTE
    out2 = StrategyOutcome(Strategy.LEARNED_ROUTE, success=False, downloaded=0)
    assert next_strategy(Strategy.LEARNED_ROUTE, out2, enable_cua=False) is None


def test_cua_terminal():
    # Cascade order: EXISTING → DETERMINISTIC → LLM_GENERATED → LEARNED_ROUTE → CUA → MANUAL
    # CUA is NOT the last strategy — MANUAL (legacy phase-0 scraper) follows it.
    out = StrategyOutcome(Strategy.CUA, success=False, downloaded=0)
    assert next_strategy(Strategy.CUA, out, enable_cua=True) is Strategy.MANUAL


def test_manual_is_terminal():
    # MANUAL is the last fallback — nothing follows it.
    out = StrategyOutcome(Strategy.MANUAL, success=False, downloaded=0)
    assert next_strategy(Strategy.MANUAL, out, enable_cua=True) is None


# ---------- versioning ----------

def test_version_delta():
    old = {"a.pdf": "h1", "b.pdf": "h2"}
    new = {"a.pdf": "h1", "b.pdf": "h2_new", "c.pdf": "h3"}
    delta = compare_snapshots(old, new)
    assert delta.added == ["c.pdf"]
    assert delta.modified == ["b.pdf"]
    assert delta.removed == []
