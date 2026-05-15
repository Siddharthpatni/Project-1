"""
Curated menu of cheap LLMs on OpenRouter
========================================

A single source of truth for "which models can I run for the scraper-generation
loop without burning money?". Used by:

  * ``run.py --list-models`` to print the menu.
  * ``run.py --model <id>`` to override the default per-run.
  * ``generator.COST_PER_MILLION_TOKENS`` (loaded from here at import time) so
    cost estimates work for whatever model you pick.
  * ``multi_llm_evaluator.MODELS`` (loaded from here at import time) so you can
    benchmark a slice of these models against a slice of URLs.

Prices are per **1 million tokens** in USD, sourced from OpenRouter's public
pricing pages around early-mid 2026. They are estimates — the *real* billed
cost comes back from OpenRouter in every API response and is what
``generator.LLMClient`` records. These numbers are only used as a fallback
when a model isn't returned with a ``usage.cost`` field.

Models are organised into tiers:

  * ``free``           — OpenRouter free tier (``:free`` suffix). Rate-limited,
                         not for production, great for prototyping.
  * ``ultra-cheap``    — paid but well under $1 per 1M output tokens.
  * ``cheap``          — under $5 per 1M output tokens. Sweet spot for code-gen.
  * ``mid``            — solid generalists, $5-$15 per 1M output tokens.

Pick by passing the ``model_id`` to ``run.py --model``.

Adding or updating a model? Just append to ``CHEAP_MODELS`` below — every
consumer reads from this list.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class ModelInfo:
    """One row in the menu."""
    name:         str          # short, human-readable label (e.g. "gemini-2.5-flash")
    model_id:     str          # full OpenRouter id (e.g. "google/gemini-2.5-flash")
    provider:     str          # provider slug used by multi_llm_evaluator.PROVIDER_CONCURRENCY
    tier:         str          # one of: "free", "ultra-cheap", "cheap", "mid"
    input_price:  float        # USD per 1M input tokens
    output_price: float        # USD per 1M output tokens
    notes:        str = ""     # free-form: context window, strengths, caveats


# ─── The menu ─────────────────────────────────────────────────────────────────
# Ordered by tier (free → ultra-cheap → cheap → mid), then roughly by cost.

CHEAP_MODELS: list[ModelInfo] = [
    # ── FREE TIER (OpenRouter rate-limits these: ~20 req/min, ~200 req/day) ──
    ModelInfo("deepseek-r1:free",          "deepseek/deepseek-r1:free",
              "deepseek", "free", 0.0, 0.0,
              "Reasoning model. Strong on code. Free but slow + rate-limited."),
    ModelInfo("deepseek-v3:free",          "deepseek/deepseek-chat:free",
              "deepseek", "free", 0.0, 0.0,
              "General chat. 64K context. Free tier."),
    ModelInfo("qwen3-coder-480b:free",     "qwen/qwen3-coder:free",
              "qwen", "free", 0.0, 0.0,
              "Strongest free coding model. 262K context. Slow."),
    ModelInfo("llama-3.3-70b:free",        "meta-llama/llama-3.3-70b-instruct:free",
              "meta-llama", "free", 0.0, 0.0,
              "Solid generalist. 128K context."),
    ModelInfo("mistral-small-3.1:free",    "mistralai/mistral-small-3.1-24b-instruct:free",
              "mistralai", "free", 0.0, 0.0,
              "Fast, light. 128K context."),
    ModelInfo("gemma-3-27b:free",          "google/gemma-3-27b-it:free",
              "google", "free", 0.0, 0.0,
              "Open-weights Google. 128K context."),
    ModelInfo("openrouter-free-router",    "openrouter/free",
              "openrouter", "free", 0.0, 0.0,
              "Auto-routes to whichever free model is healthy. Easiest start."),

    # ── ULTRA-CHEAP (paid, < $1 per 1M output tokens) ────────────────────────
    ModelInfo("gemini-2.5-flash-lite",     "google/gemini-2.5-flash-lite",
              "google", "ultra-cheap", 0.075, 0.30,
              "Fastest Gemini. Good for high-volume, simple tasks."),
    ModelInfo("deepseek-v3",               "deepseek/deepseek-chat",
              "deepseek", "ultra-cheap", 0.14, 0.28,
              "Excellent quality-per-dollar. 64K context. Top pick for code-gen."),
    ModelInfo("deepseek-v3.2",             "deepseek/deepseek-v3.2",
              "deepseek", "ultra-cheap", 0.287, 0.431,
              "Newer DeepSeek with sparse attention. 164K context."),
    ModelInfo("deepseek-r1",               "deepseek/deepseek-r1",
              "deepseek", "ultra-cheap", 0.55, 2.19,
              "Reasoning model. Slower but stronger logic for tricky scrapers."),
    ModelInfo("gpt-4o-mini",               "openai/gpt-4o-mini",
              "openai", "ultra-cheap", 0.15, 0.60,
              "OpenAI's budget option. 128K context. Reliable but bland."),
    ModelInfo("gpt-5-nano",                "openai/gpt-5-nano",
              "openai", "ultra-cheap", 0.05, 0.40,
              "Cheapest GPT-5 tier."),
    ModelInfo("qwen-2.5-72b",              "qwen/qwen-2.5-72b-instruct",
              "qwen", "ultra-cheap", 0.40, 0.40,
              "Strong code generation. 128K context."),
    ModelInfo("llama-3.3-70b",             "meta-llama/llama-3.3-70b-instruct",
              "meta-llama", "ultra-cheap", 0.59, 0.79,
              "Paid version with no rate limits."),
    ModelInfo("mistral-small-3.1",         "mistralai/mistral-small-3.1-24b-instruct",
              "mistralai", "ultra-cheap", 0.10, 0.30,
              "Cheap and fast. Decent at code."),

    # ── CHEAP ($1-$5 per 1M output tokens) ───────────────────────────────────
    ModelInfo("gemini-2.5-flash",          "google/gemini-2.5-flash",
              "google", "cheap", 0.30, 2.50,
              "Excellent code-gen at low cost. 1M context."),
    ModelInfo("claude-haiku-4.5",          "anthropic/claude-haiku-4.5",
              "anthropic", "cheap", 1.0, 5.0,
              "Anthropic's budget tier. Strong instruction-following."),
    ModelInfo("claude-3-5-haiku",          "anthropic/claude-3-5-haiku-20241022",
              "anthropic", "cheap", 0.80, 4.0,
              "Older Haiku, still cheap and reliable."),
    ModelInfo("gpt-4.1-mini",              "openai/gpt-4.1-mini",
              "openai", "cheap", 0.40, 1.60,
              "Newer OpenAI mid-budget. 1M context. Default in .env."),

    # ── MID ($5-$15 per 1M output tokens — flagship cheap variants) ──────────
    ModelInfo("gemini-2.5-pro",            "google/gemini-2.5-pro",
              "google", "mid", 1.25, 5.0,
              "Best Gemini for hard cases. 1M context."),
    ModelInfo("claude-sonnet-4.5",         "anthropic/claude-sonnet-4.5",
              "anthropic", "mid", 3.0, 15.0,
              "Anthropic flagship-cheap. Excellent reasoning."),
    ModelInfo("gpt-4o",                    "openai/gpt-4o",
              "openai", "mid", 2.50, 10.0,
              "Established workhorse."),
]


# ─── Helpers exposed to other modules ────────────────────────────────────────

def by_id(model_id: str) -> ModelInfo | None:
    """Look up a model by its OpenRouter id."""
    for m in CHEAP_MODELS:
        if m.model_id == model_id:
            return m
    return None


def by_tier(tier: str) -> list[ModelInfo]:
    """Return all models in a given tier."""
    return [m for m in CHEAP_MODELS if m.tier == tier]


def cost_table() -> dict[str, tuple[float, float]]:
    """
    Format suitable for ``generator.COST_PER_MILLION_TOKENS``:
        { "openrouter/model-id": (input_price, output_price), ... }
    """
    return {m.model_id: (m.input_price, m.output_price) for m in CHEAP_MODELS}


def evaluator_models() -> list[dict]:
    """
    Format suitable for ``multi_llm_evaluator.MODELS``:
        [ { "name": ..., "provider": ..., "model_id": ... }, ... ]
    Filters to paid (non-free) models — free-tier rate limits make them a poor
    fit for parallel benchmarking.
    """
    return [
        {"name": m.name, "provider": m.provider, "model_id": m.model_id}
        for m in CHEAP_MODELS
        if m.tier != "free"
    ]


def format_menu(models: Iterable[ModelInfo]) -> str:
    """Pretty-print the menu for ``run.py --list-models``."""
    rows = list(models)
    width_name  = max(len(m.name)     for m in rows)
    width_id    = max(len(m.model_id) for m in rows)

    lines = []
    lines.append("Available cheap models (pass --model <id>):\n")
    current_tier = None
    for m in rows:
        if m.tier != current_tier:
            tier_label = {
                "free":        "── FREE TIER (rate-limited) ──",
                "ultra-cheap": "── ULTRA-CHEAP (< $1 / 1M out) ──",
                "cheap":       "── CHEAP ($1-$5 / 1M out) ──",
                "mid":         "── MID ($5-$15 / 1M out) ──",
            }.get(m.tier, m.tier)
            lines.append("")
            lines.append(tier_label)
            current_tier = m.tier

        if m.input_price == 0 and m.output_price == 0:
            price = "FREE"
        else:
            price = f"${m.input_price:>5.2f} in / ${m.output_price:>5.2f} out"
        lines.append(
            f"  {m.name:<{width_name}}  {m.model_id:<{width_id}}  {price:<28}  {m.notes}"
        )
    lines.append("")
    lines.append(
        "Tip: defaults to $LLM_MODEL from .env (currently a paid model). "
        "Try --model openrouter/free for a no-cost first run."
    )
    return "\n".join(lines)


if __name__ == "__main__":
    # Allow `python models.py` as a quick way to see the menu without --list-models.
    print(format_menu(CHEAP_MODELS))
