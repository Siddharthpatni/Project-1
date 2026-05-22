"""
run_demo.py — OpenRouter Multi-Model Demo
==========================================
This script demonstrates how to use the OpenRouterClient wrapper to call
three different LLM providers (OpenAI, Anthropic, Google) through a single
unified API.  Each call is automatically cost-tracked and budget-guarded.

Prerequisites:
    1.  pip install requests python-dotenv
    2.  A valid .env file in this directory with:
            OPENROUTER_API_KEY=sk-or-v1-...
            LLM_BUDGET=50.0
    3.  Run from this directory:
            python run_demo.py

What this script does:
    - Initializes the OpenRouterClient (reads API key & budget from .env)
    - Sends the SAME prompt to three different models
    - Prints each model's response side-by-side
    - Shows a cost summary at the end so you can compare pricing
"""

import sys
from llm_client import OpenRouterClient, BudgetExceededError

# ─────────────────────────────────────────────────────────────────────────────
#  CONFIGURATION — Edit these to experiment with different models / prompts
# ─────────────────────────────────────────────────────────────────────────────

# List of models to test.  Each entry is (display_name, openrouter_model_id).
# You can add or remove models here; the rest of the script adapts automatically.
MODELS = [
    ("GPT-4o  (OpenAI)",              "openai/gpt-4o"),
    ("Claude Sonnet 4.5 (Anthropic)",  "anthropic/claude-sonnet-4.5"),
    ("Gemini 2.5 Pro (Google)",        "google/gemini-2.5-pro"),
]

# The conversation messages sent to every model (standard OpenAI chat format).
# This format works universally across GPT, Claude, and Gemini via OpenRouter.
MESSAGES = [
    {
        "role": "system",
        "content": "You are a helpful assistant. Keep answers brief (2-3 sentences max)."
    },
    {
        "role": "user",
        "content": "What is public procurement and why does it matter?"
    },
]


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN DEMO
# ─────────────────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("  OpenRouter Multi-Model Demo")
    print("=" * 70)

    # ── Step 1: Initialize the client ────────────────────────────────────
    # The constructor automatically loads OPENROUTER_API_KEY and LLM_BUDGET
    # from the .env file (via python-dotenv).  You can also pass an explicit
    # budget:  client = OpenRouterClient(budget=10.0)
    try:
        client = OpenRouterClient()
    except Exception as e:
        print(f"\n[Error] Could not initialize client: {e}")
        print("Make sure your .env file contains a valid OPENROUTER_API_KEY.")
        sys.exit(1)

    print(f"\n  Budget ceiling : ${client.budget:.2f}")
    print(f"  Already spent  : ${client.total_spent:.4f}")
    print("-" * 70)

    # ── Step 2: Send the same prompt to each model ───────────────────────
    # We store results so we can print a cost summary at the end.
    results = []  # list of (display_name, response_text, cost)

    for display_name, model_id in MODELS:
        print(f"\n>>> Sending request to {display_name} ({model_id})...")

        spent_before = client.total_spent  # snapshot so we can calculate per-call cost

        try:
            # client.generate() handles:
            #   - HTTP POST to OpenRouter's /chat/completions endpoint
            #   - Automatic cost calculation from token usage
            #   - Budget guard (warns at 80%, hard-stops at 100%)
            #
            # Extra kwargs (temperature, max_tokens, top_p, etc.) are passed
            # straight through to OpenRouter, just like the OpenAI SDK.
            response = client.generate(
                model=model_id,
                messages=MESSAGES,
                temperature=0.7,      # controls creativity (0 = deterministic, 1 = creative)
                max_tokens=256,       # cap output length to keep costs low in a demo
            )

            # Extract the text from the standard OpenAI-style response format
            text = response["choices"][0]["message"]["content"]
            cost = client.total_spent - spent_before

            results.append((display_name, text, cost))

            # Print the response immediately
            print(f"\n--- {display_name} Response ---")
            print(text)

        except BudgetExceededError as e:
            # The budget guard kicked in — this model call was blocked.
            print(f"\n[Budget Guard] Skipped {display_name}: {e}")
            results.append((display_name, "(blocked by budget guard)", 0.0))

        except Exception as e:
            # Network timeout, invalid API key, model not available, etc.
            print(f"\n[Error] {display_name} failed: {e}")
            results.append((display_name, f"(error: {e})", 0.0))

    # ── Step 3: Print a cost comparison table ────────────────────────────
    print("\n" + "=" * 70)
    print("  COST SUMMARY")
    print("=" * 70)
    print(f"  {'Model':<35} {'Cost':>10}")
    print("  " + "-" * 45)

    for name, _, cost in results:
        print(f"  {name:<35} ${cost:.6f}")

    print("  " + "-" * 45)
    print(f"  {'TOTAL SPENT':<35} ${client.total_spent:.6f}")
    print(f"  {'REMAINING BUDGET':<35} ${client.budget - client.total_spent:.6f}")
    print("=" * 70)


# ─────────────────────────────────────────────────────────────────────────────
#  Entry point — run this file directly:  python run_demo.py
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    main()
