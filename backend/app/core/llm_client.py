"""
Unified LLM client — OpenRouter by default, direct providers as fallback.

Model ids prefixed "ollama/" (e.g. "ollama/qwen2.5-coder:7b") are routed to a
local Ollama server (settings.ollama_base_url) instead: same OpenAI-compatible
wire format, no API key, zero cost.

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


# Model ids with this prefix are served by the local Ollama server.
OLLAMA_PREFIX = "ollama/"


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

    def _route(self, model: str, payload: dict) -> tuple[dict, str, dict, int]:
        """Resolve (payload, url, headers, timeout) for a model id.

        "ollama/<name>" goes to the local Ollama server (no auth, bare model
        name on the wire, longer timeout — local generation is slow);
        everything else goes to OpenRouter.
        """
        if model.startswith(OLLAMA_PREFIX):
            payload = {**payload, "model": model[len(OLLAMA_PREFIX):]}
            url = f"{settings.ollama_base_url.rstrip('/')}/chat/completions"
            headers = {"Content-Type": "application/json"}
            timeout = settings.ollama_timeout_seconds
        else:
            payload = {**payload, "model": model}
            url = f"{self.base_url}/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "HTTP-Referer": "https://vergabepilot.ai",
                "X-Title": "Vergabepilot.AI",
                "Content-Type": "application/json",
            }
            timeout = 120
        return payload, url, headers, timeout

    async def _call(self, payload: dict, model: str) -> LLMResponse:
        is_local = bool(model) and model.startswith(OLLAMA_PREFIX)
        if not is_local and not self.api_key:
            log.warning("llm.no_api_key", note="returning stub response")
            return LLMResponse(text="```python\n# stub: no API key configured\n```", model=model)

        payload, url, headers, timeout = self._route(model, payload)

        import asyncio

        # Retry policy per HTTP status:
        #   429 Rate-limit  → wait longer (10s, 20s, 30s) then retry same model
        #   403 Forbidden   → switch to fallback model immediately (concurrent-call limit hit)
        #   5xx Server error → short retry (3s, 6s)
        #   Network error   → short retry (2s, 4s)
        # Never retry 401 (bad key) or 400 (bad request) — they won't fix themselves.
        _NO_RETRY_CODES = {400, 401}
        _RATE_LIMIT_CODE = 429
        _FORBIDDEN_CODE  = 403

        max_retries = 3
        last_error: Exception | None = None
        data = None

        async with httpx.AsyncClient() as client:
            for attempt in range(1, max_retries + 1):
                try:
                    r = await client.post(url, json=payload, headers=headers, timeout=timeout)

                    # 403: OpenRouter concurrent-call cap or key issue.
                    # Switch to fallback model and retry once — do NOT re-hit
                    # the same model because it will 403 again immediately.
                    if r.status_code == _FORBIDDEN_CODE:
                        fallback = settings.llm_model_fallback
                        if fallback and fallback != model:
                            log.warning("llm.403_switching_to_fallback",
                                        primary=model, fallback=fallback)
                            model = fallback
                            payload, url, headers, timeout = self._route(model, payload)
                            await asyncio.sleep(2)
                            continue
                        # No usable fallback — raise
                        r.raise_for_status()

                    # 429: rate limit — back off much longer than network errors
                    if r.status_code == _RATE_LIMIT_CODE:
                        wait = 10 * attempt   # 10s, 20s, 30s
                        log.warning("llm.rate_limited", wait_s=wait, attempt=attempt)
                        if attempt < max_retries:
                            await asyncio.sleep(wait)
                            continue
                        r.raise_for_status()

                    if r.status_code in _NO_RETRY_CODES:
                        r.raise_for_status()   # raise immediately, no retry

                    r.raise_for_status()
                    data = r.json()
                    break

                except httpx.HTTPStatusError:
                    raise   # already logged above; let it propagate
                except (httpx.RemoteProtocolError, httpx.TimeoutException,
                        httpx.ConnectError, Exception) as e:
                    last_error = e
                    log.warning("llm.call_retry", attempt=attempt, error=str(e)[:200])
                    if attempt < max_retries:
                        await asyncio.sleep(attempt * 2)   # 2s, 4s

        if data is None:
            log.error("llm.call_failed", error=str(last_error))
            raise last_error  # type: ignore[misc]

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
