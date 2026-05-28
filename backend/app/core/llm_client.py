"""
Unified LLM client — OpenRouter by default, direct providers as fallback.

Exposes two high-level methods:
    chat(system, user)                → text completion
    chat_with_image(system, user, b64) → vision completion (for Phase 2)

Cost is estimated from usage tokens using a small static price table.
Override via environment variables or extend as needed.
"""
from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.config import settings
from app.utils.logger import get_logger

log = get_logger(__name__)

# Very rough cost table in USD per 1M tokens (input, output).
# Used only for rough tracking; real billing comes from OpenRouter.
_COSTS = {
    "anthropic/claude-sonnet-4.5": (3.0, 15.0),
    "anthropic/claude-haiku-4.5":  (1.0, 5.0),
    "openai/gpt-4o":               (2.5, 10.0),
    "openai/gpt-4o-mini":          (0.15, 0.6),
    "google/gemini-2.5-pro":       (1.25, 5.0),
    "google/gemini-2.5-flash":     (0.15, 0.6),
    "google/gemini-2.5-flash-lite": (0.0, 0.0),  # free tier
}


@dataclass
class LLMResponse:
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


class LLMClient:
    """Async OpenRouter-compatible client."""

    def __init__(self, default_model: str | None = None):
        self.base_url = settings.openrouter_base_url.rstrip("/")
        self.api_key = settings.openrouter_api_key
        self._client = httpx.AsyncClient(timeout=120)
        self.default_model = default_model or settings.llm_model_primary

    async def chat(self, system: str, user: str, model: str | None = None) -> LLMResponse:
        model = model or self.default_model
        # Cache the system prompt for Anthropic models — saves ~80% on re-use.
        system_content: str | list
        if model and model.startswith("anthropic/"):
            system_content = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        else:
            system_content = system
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_content},
                {"role": "user", "content": user},
            ],
        }
        return await self._call(payload, model)

    async def chat_with_image(
        self,
        system: str,
        user: str,
        image_b64: str,
        model: str | None = None,
    ) -> LLMResponse:
        model = model or self.default_model
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                        },
                    ],
                },
            ],
        }
        return await self._call(payload, model)

    async def _call(self, payload: dict, model: str) -> LLMResponse:
        if not self.api_key:
            log.warning("llm.no_api_key", note="returning stub response")
            return LLMResponse(text="```python\n# stub: no API key configured\n```", model=model)

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "https://vergabepilot.ai",
            "X-Title": "Vergabepilot.AI",
            "Content-Type": "application/json",
        }

        import asyncio
        max_retries = 3
        last_error = None
        data = None

        for attempt in range(1, max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=120) as client:
                    r = await client.post(url, json=payload, headers=headers)
                    r.raise_for_status()
                    data = r.json()
                    break
            except (httpx.HTTPError, httpx.RemoteProtocolError, Exception) as e:
                last_error = e
                log.warning("llm.call_retry", attempt=attempt, error=str(e))
                if attempt < max_retries:
                    await asyncio.sleep(attempt * 1.5)
                continue
        else:
            log.error("llm.call_failed", error=str(last_error))
            raise last_error

        content = data["choices"][0]["message"]["content"]
        if isinstance(content, list):
            # vision models sometimes return list of parts
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))

        usage = data.get("usage", {})
        in_tok = usage.get("prompt_tokens", 0)
        out_tok = usage.get("completion_tokens", 0)
        from app.phase1_llm_scraper.pricing import calc_cost
        cost = calc_cost(in_tok, out_tok, model)

        return LLMResponse(
            text=content,
            model=model,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=cost,
        )
