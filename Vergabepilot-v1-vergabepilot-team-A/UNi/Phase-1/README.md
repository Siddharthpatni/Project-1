# OpenRouter Budget Guard LLM Client

A unified Python wrapper for OpenRouter that provides seamless abstraction over multiple LLM providers (OpenAI, Anthropic, Google, etc.) with built-in mathematical cost tracking and robust budget guardrails.

## Features
- **Multi-Model Support:** One single interface for `openai/gpt-4o`, `anthropic/claude-3-opus`, `google/gemini-1.5-pro` and more.
- **Cost Tracking:** Calculates the exact dollar cost for every request using dynamic prompt and completion token math.
- **Budget Guard:** Prevents runaway costs by logging a warning at 80% of budget usage and throwing a hard `BudgetExceededError` at 100%.

## 1. Installation

This client uses `requests` for networking and optionally `python-dotenv` for configuration.

```bash
# Install dependencies
pip install requests python-dotenv
```

Ensure the wrapper (`llm_client.py`) is placed within your project directory.

## 2. Configuration (Environment Variables)

Create a `.env` file in the root of your project directory. This secures your API keys and establishes your safety budget without hardcoding it.

```env
# OpenRouter Authentication
OPENROUTER_API_KEY="sk-or-v1-..."

# Safety Budget Ceiling in USD
LLM_BUDGET=50.00

# (Optional) Dynamic Pricing Overrides per 1,000 tokens
PRICE_OPENAI_GPT4O_PROMPT=0.005
PRICE_OPENAI_GPT4O_COMPLETION=0.015
```

## 3. Quickstart & Worked Example

Here is a full worked example demonstrating how to initialize the client, send a prompt, and handle potential budget limits.

```python
from llm_client import OpenRouterClient, BudgetExceededError

def run_example():
    try:
        # Initialize client (it automatically loads API keys and budget from .env)
        client = OpenRouterClient()
        print(f"Starting Budget: ${client.budget}")

        # Standard OpenAI-style message format
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Write a 3 sentence poem about coding."}
        ]

        # Generate response using Anthropic's Claude 3 Opus
        response = client.generate(
            model="anthropic/claude-3-opus", 
            messages=messages,
            temperature=0.7
        )

        # Print the response text
        output_text = response["choices"][0]["message"]["content"]
        print("\n--- LLM Response ---")
        print(output_text)
        
        # Verify the tracking system!
        print(f"\nTotal spent so far: ${client.total_spent:.6f}")

    except BudgetExceededError as e:
        print(f"REQUEST BLOCKED: {e}")
    except Exception as e:
        print(f"Network or API Error: {e}")

if __name__ == "__main__":
    run_example()
```

## 4. Troubleshooting

- **`ModuleNotFoundError: No module named 'requests'`**
  - **Fix:** Run `pip install requests` in your active Python environment.
- **`WARNING: OPENROUTER_API_KEY environment variable is not set`**
  - **Fix:** Ensure you have created your `.env` file and installed `python-dotenv`. Make sure you are running the script from the same directory where the `.env` file lives.
- **`BudgetExceededError: Budget of $50.00 exceeded.`**
  - **Fix:** The guardrail correctly protected you! If you intentionally want to spend more, increase the `LLM_BUDGET` variable in your `.env` file and restart your script.
- **`requests.exceptions.HTTPError: 401 Client Error`**
  - **Fix:** Your OpenRouter API key is invalid or expired. Check your OpenRouter dashboard.
