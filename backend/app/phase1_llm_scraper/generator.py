"""
LLM-backed scraper code generator.

Thin wrapper around `core.llm_client.LLMClient` that handles:
- Fetching a page-structure snippet (so the LLM has something to anchor to)
- Calling the model with the system + user prompt
- Stripping the ```python``` fence from the response

Supports two prompt modes:
- Plain generation (`build_generation_prompt`) — the LLM infers everything
  from the HTML snippet alone.
- Route-guided generation (`build_route_guided_prompt`) — when a RouteMap
  produced by `route_learner.learn_route()` is passed in, the LLM gets
  the exact click sequence the route learner discovered. This makes the
  output deterministic and reliable for the target domain.

Also accepts an optional `platform` hint from `platform_classifier` so
the prompt can splice in domain-specific guidance.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from app.core.llm_client import LLMClient, LLMResponse
from app.core.security import detect_prompt_injection, sanitize_web_content
from app.phase1_llm_scraper.prompts import (
    SYSTEM_PROMPT,
    build_feedback_prompt,
    build_generation_prompt,
    build_route_guided_prompt,
    build_cua_hint_section,
)
from app.phase1_llm_scraper.route_learner import RouteMap
from app.phase3_integration import platform_classifier
from app.utils.logger import get_logger

log = get_logger(__name__)

_CODE_FENCE = re.compile(r"```(?:python)?\s*(.*?)```", re.DOTALL)


@dataclass
class GeneratedScraper:
    code: str
    model: str
    cost_usd: float
    raw_response: str
    route_used: bool = False  # whether a learned RouteMap shaped this scraper


class ScraperGenerator:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    # --- public API ---------------------------------------------------

    async def generate(
        self,
        url: str,
        model: str | None = None,
        route_map: RouteMap | None = None,
        platform: str | None = None,
        html_snippet: str | None = None,
        cua_hint: str | None = None,
    ) -> GeneratedScraper:
        """
        Generate a scraper. If `route_map` is provided and represents a
        successfully-learned route, the route-guided prompt is used and
        the LLM is asked to follow the exact discovered click sequence.
        Otherwise we fall back to the plain generation prompt.

        Pass `html_snippet` when the caller already has a pre-fetched and
        sanitized copy of the page — avoids a second HTTP round-trip.
        """
        if html_snippet is None:
            html_snippet = await self._fetch_snippet(url)
        domain = urlparse(url).netloc

        # Refine platform via HTML classification if not already known.
        resolved_platform = platform or platform_classifier.classify_html(url, html_snippet)
        if resolved_platform == "unknown":
            resolved_platform = None

        used_route = bool(route_map and route_map.learned)
        if used_route:
            user_msg = build_route_guided_prompt(
                url=url,
                domain=domain,
                html_snippet=html_snippet,
                route_summary=route_map.format_for_prompt(),
                discovered_links=route_map.document_links,
                platform=resolved_platform,
                cua_hint=cua_hint,
            )
            log.info(
                "phase1.generate.route_guided",
                domain=domain, platform=resolved_platform,
                discovered_docs=route_map.total_documents_found,
                cua_hint_present=bool(cua_hint),
            )
        else:
            user_msg = build_generation_prompt(
                url=url, domain=domain,
                html_snippet=html_snippet,
                platform=resolved_platform or "unknown",
                cua_hint=cua_hint,
            )

        resp = await self.llm.chat(
            system=SYSTEM_PROMPT,
            user=user_msg,
            model=model,
        )
        parsed = self._parse(resp)
        parsed.route_used = used_route
        return parsed

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
        """Grab a lightweight HTML snippet. Best-effort; failures are fine.

        The returned HTML is scanned for prompt injection patterns and
        wrapped in ``<untrusted_web_content>`` tags so the LLM treats it
        as data, not instructions.
        """
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                r = await client.get(
                    url,
                    headers={
                        "User-Agent": "VergabepilotBot/0.1",
                        "Accept-Language": "de-DE,de;q=0.9,en;q=0.7",
                    },
                )
                raw = r.text
        except Exception as e:  # noqa: BLE001
            log.warning("phase1.snippet_fetch_failed", url=url, error=str(e))
            return "<!-- could not fetch page -->"

        # Scan for prompt injection in fetched HTML
        injection_hits = detect_prompt_injection(raw)
        if injection_hits:
            log.error(
                "phase1.prompt_injection_detected",
                url=url,
                patterns=injection_hits[:5],
            )
            raise ValueError(f"prompt injection detected: HTML payload matches forbidden patterns {injection_hits[:5]}")

        return sanitize_web_content(raw, max_length=20_000)

    def _parse(self, resp: LLMResponse) -> GeneratedScraper:
        match = _CODE_FENCE.search(resp.text)
        code = match.group(1).strip() if match else resp.text.strip()
        return GeneratedScraper(
            code=code,
            model=resp.model,
            cost_usd=resp.cost_usd,
            raw_response=resp.text,
        )
