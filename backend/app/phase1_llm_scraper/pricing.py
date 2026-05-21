"""
Model pricing data and cost calculation utilities.

Ported from the standalone benchmark evaluator in
_archive/Vergabepilot-v1-development/evaluator.py and adapted
for backend use. Prices are per million tokens (input, output)
as listed on https://openrouter.ai/models.
"""
from __future__ import annotations


# OpenRouter pricing per million tokens: (input_price, output_price)
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "google/gemini-2.5-flash":        (0.30, 2.50),
    "google/gemini-2.5-flash-lite":   (0.075, 0.30),
    "google/gemini-2.5-pro":          (1.25, 10.00),
    "google/gemini-3.0-flash":        (0.15, 0.60),
    "openai/gpt-4o":                  (2.50, 10.00),
    "openai/gpt-4o-mini":             (0.15, 0.60),
    "openai/gpt-4.1":                 (2.00, 8.00),
    "openai/gpt-4.1-mini":            (0.40, 1.60),
    "openai/gpt-4.1-nano":            (0.10, 0.40),
    "anthropic/claude-sonnet-4":      (3.00, 15.00),
    "anthropic/claude-haiku":         (0.80, 4.00),
    "deepseek/deepseek-chat-v3-0324": (0.14, 0.28),
    "meta-llama/llama-4-maverick":    (0.20, 0.60),
}


def calc_cost(
    prompt_tokens: int,
    completion_tokens: int,
    model: str,
) -> float:
    """Estimate USD cost from token counts and model slug.

    Returns 0.0 for unknown models.
    """
    input_price, output_price = MODEL_PRICING.get(model, (0.0, 0.0))
    return (prompt_tokens * input_price + completion_tokens * output_price) / 1_000_000


def format_comparison_table(results: list[dict]) -> str:
    """Return a formatted CLI comparison table string.

    Each dict in *results* should have at minimum::

        {
            "model": str,
            "total_urls": int,
            "successes": int,
            "success_rate_pct": float,
            "total_cost_usd": float,
            "avg_cost_per_url_usd": float,
            "elapsed_s": float,
        }

    Failures (list of dicts with "url", "domain", "error") are
    optional — if present a cross-comparison block is appended.
    """
    lines: list[str] = []
    sep = "=" * 80

    lines.append(f"\n\n{sep}")
    lines.append("  MODEL COMPARISON")
    lines.append(sep)
    lines.append(
        f"  {'Model':<35} {'Success':>8} {'Rate':>7} "
        f"{'Cost':>10} {'$/URL':>10} {'Time':>8}"
    )
    lines.append(
        f"  {'-'*35} {'-'*8} {'-'*7} "
        f"{'-'*10} {'-'*10} {'-'*8}"
    )

    sorted_results = sorted(results, key=lambda x: -x["success_rate_pct"])
    for data in sorted_results:
        lines.append(
            f"  {data['model']:<35} "
            f"{data['successes']:>3}/{data['total_urls']:<4} "
            f"{data['success_rate_pct']:>6.1f}% "
            f"${data['total_cost_usd']:>8.4f} "
            f"${data['avg_cost_per_url_usd']:>9.6f} "
            f"{data['elapsed_s']:>7.1f}s"
        )

    lines.append(sep)

    # Failure cross-comparison (when multiple models)
    models = [d["model"] for d in sorted_results]
    if len(models) > 1:
        all_fail_urls: set[str] = set()
        model_url_results: dict[str, list[dict]] = {}
        for data in sorted_results:
            model_url_results[data["model"]] = data.get("url_results", [])
            for f in data.get("failures", []):
                all_fail_urls.add(f["url"])

        if all_fail_urls:
            lines.append("\n  FAILURE COMPARISON:")
            from urllib.parse import urlsplit

            for url in sorted(all_fail_urls):
                statuses = []
                for m in models:
                    url_data = next(
                        (u for u in model_url_results.get(m, []) if u["url"] == url),
                        None,
                    )
                    if url_data:
                        statuses.append(
                            "OK" if url_data["status"] == "success" else "FAIL"
                        )
                    else:
                        statuses.append("--")
                domain = urlsplit(url).netloc
                lines.append(f"    {domain:<35} {' | '.join(statuses)}")
            lines.append(
                f"    {'Model legend:':<35} "
                f"{' | '.join(m.split('/')[-1][:12] for m in models)}"
            )

    return "\n".join(lines)
