"""
LLM-backed scraper code generator.

Thin wrapper around `core.llm_client.LLMClient` that handles:
- Fetching a page-structure snippet (so the LLM has something to anchor to)
- Calling the model with the system + user prompt
- Stripping the ```python``` fence from the response
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from app.core.llm_client import LLMClient, LLMResponse
from app.phase1_llm_scraper.prompts import (
    SYSTEM_PROMPT,
    build_feedback_prompt,
    build_generation_prompt,
)
from app.utils.logger import get_logger

log = get_logger(__name__)

_CODE_FENCE = re.compile(r"```(?:python)?\s*(.*?)```", re.DOTALL)


@dataclass
class GeneratedScraper:
    code: str
    model: str
    cost_usd: float
    raw_response: str


class ScraperGenerator:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    # --- public API ---------------------------------------------------

    async def generate(self, url: str, model: str | None = None) -> GeneratedScraper:
        html_snippet = await self._fetch_snippet(url)
        domain = urlparse(url).netloc
        user_msg = build_generation_prompt(url=url, domain=domain, html_snippet=html_snippet)

        resp = await self.llm.chat(
            system=SYSTEM_PROMPT,
            user=user_msg,
            model=model,
        )
        return self._parse(resp)

    async def regenerate(
        self,
        url: str,
        iteration: int,
        max_iterations: int,
        outcome: str,
        error: str,
        expected_docs: int,
        downloaded: int,
        model: str | None = None,
    ) -> GeneratedScraper:
        user_msg = build_feedback_prompt(
            iteration=iteration,
            max_iterations=max_iterations,
            url=url,
            outcome=outcome,
            error=error,
            expected_docs=expected_docs,
            downloaded=downloaded,
        )
        resp = await self.llm.chat(system=SYSTEM_PROMPT, user=user_msg, model=model)
        return self._parse(resp)

    # --- internals ----------------------------------------------------

    async def _fetch_snippet(self, url: str) -> str:
        """Grab a lightweight HTML snippet. Best-effort; failures are fine."""
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                r = await client.get(url, headers={"User-Agent": "VergabepilotBot/0.1"})
                return r.text
        except Exception as e:  # noqa: BLE001
            log.warning("phase1.snippet_fetch_failed", url=url, error=str(e))
            return "<!-- could not fetch page -->"

    def _parse(self, resp: LLMResponse) -> GeneratedScraper:
        match = _CODE_FENCE.search(resp.text)
        code = match.group(1).strip() if match else resp.text.strip()
        return GeneratedScraper(
            code=code,
            model=resp.model,
            cost_usd=resp.cost_usd,
            raw_response=resp.text,
        )
