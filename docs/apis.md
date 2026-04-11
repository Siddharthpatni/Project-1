# Model Selection Guide (OpenRouter)

This guide lists cost-effective LLMs available via OpenRouter for Phase 1 (Code Generation) and Phase 2 (CUA/Vision) scraping tasks.

## Phase 1: Code Generation (Scraper Synthesis)
These models are optimized for logic, Python/Playwright syntax, and following complex scraping instructions.

| Model Name | OpenRouter ID | Estimated Cost (In/Out per 1M) | Best For |
| :--- | :--- | :--- | :--- |
| **Devstral 2 2512 (Free)** | `mistralai/mistral-small:free` | **Free** | Fast prototyping, agentic loops |
| **Qwen 2.5 Coder 72B** | `qwen/qwen-2.5-coder-72b-instruct` | $0.12 / $0.75 | High-accuracy niche scrapers |
| **Llama 3.1 70B** | `meta-llama/llama-3.1-70b-instruct` | $0.60 / $0.80 | Reliable logic & structure |
| **Mistral Nemo** | `mistralai/mistral-nemo` | $0.17 / $0.17 | Small/Medium scraping tasks |

## Phase 2: Vision / Computer-Use Agent (CUA)
These models support image/screenshot inputs and are essential for Phase 2 vision-based agents.

| Model Name | OpenRouter ID | Estimated Cost (In/Out per 1M) | Best For |
| :--- | :--- | :--- | :--- |
| **Gemini 1.5 Flash** | `google/gemini-flash-1.5` | $0.075 / $0.30 | High context (1M+), bulk vision |
| **Gemma 4 31B (Free)** | `google/gemma-2-27b-it:free` | **Free** | Basic UI element identification |
| **GPT-4o-mini** | `openai/gpt-4o-mini` | $0.15 / $0.60 | High precision clicking/actions |
| **Llama 3.2 Vision 11B** | `meta-llama/llama-3.2-11b-vision-instruct` | $0.05 / $0.05 | Fastest vision feedback loops |

## All Gemini Models (Google)
Gemini models are often the best choice for this project due to their **1M+ context window** (allowing them to "see" entire web pages) and competitive pricing via OpenRouter.

| Model Name | OpenRouter ID | Notable Strengths |
| :--- | :--- | :--- |
| **Gemini 3.1 Pro (Preview)** | `google/gemini-3.1-pro-preview` | Logic powerhouse, complex scraping logic |
| **Gemini 3 Flash (Preview)** | `google/gemini-3-flash-preview` | Extremely fast, high volume scraping |
| **Gemini 3.1 Flash Lite**| `google/gemini-3.1-flash-lite-preview` | Best for ultra-low-cost, multi-pass agents |
| **Gemini 2.5 Flash** | `google/gemini-flash-1.5` | High stability, reliable vision |
| **Gemini 2.5 Pro** | `google/gemini-pro-1.5` | Deep reasoning, high document recall |

## How to Change Models in the Code

You can change which models the system uses for Phase 1 (LLM Scraper) and Phase 2 (CUA) without rebuilding the Docker containers.

### 1. Update the `.env` file (Recommended)
The easiest way is to edit the `.env` file in the root directory. Look for these keys:

```env
# Change the primary model for Phase 1 code generation
LLM_MODEL_PRIMARY=google/gemini-3.1-pro-preview

# Change the vision model for Phase 2 CUA agents
LLM_MODEL_VISION=google/gemini-flash-1.5

# Change the fallback model if primary fails
LLM_MODEL_FALLBACK=openai/gpt-4o-mini
```

### 2. Update via `backend/app/config.py`
If you want to change the **default** values hardcoded in the application, edit `backend/app/config.py` at lines 22-24:

```python
llm_model_primary: str = "google/gemini-3.1-pro-preview"
llm_model_fallback: str = "openai/gpt-4o-mini"
llm_model_vision: str = "google/gemini-flash-1.5"
```

> [!TIP]
> After updating the `.env` file, restart your containers with `docker compose up -d` to apply the changes.

## Recommendations for Production

### 1. Cost-Performance Winner
Use **Gemini 1.5 Flash** for almost everything. It is extremely cheap, has a massive context window (helpful for long HTML dumps), and handles vision for Phase 2 beautifully.

### 2. High Stability
If a site has complex logic, use **Qwen 2.5 Coder 72B** for Phase 1 and **GPT-4o-mini** for Phase 2. This combination provides a high success rate while keeping costs significantly lower than "Frontier" models like GPT-4o or Claude 3.5 Sonnet.

### 3. The "Hacker" Choice (Zero Cost)
For local testing or low-volume jobs, stick to the `:free` suffixed models on OpenRouter (Devstral/Gemma). Note that these usually have tight rate limits (e.g., 20 requests per minute).

---

*Note: Pricing on OpenRouter is dynamic. Always verify the latest rates at [openrouter.ai/models](https://openrouter.ai/models) before large-scale runs.*
