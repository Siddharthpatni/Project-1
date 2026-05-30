from __future__ import annotations

import json
from dataclasses import dataclass

from tender_agent.models import DocumentCandidate
from tender_agent.system_prompt import SELECTION_SYSTEM_PROMPT
from tender_agent.utils import normalize_url

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - runtime dependency
    OpenAI = None

try:
    from pydantic import BaseModel, Field
except ImportError:  # pragma: no cover - runtime dependency
    BaseModel = object

    def Field(*, default=None, default_factory=None):
        if default_factory is not None:
            return default_factory()
        return default


class SelectedDocumentRecord(BaseModel):
    url: str
    name: str
    reason: str
    priority: str = "medium"

    model_config = {"extra": "ignore"}


class PostDownloadRecord(BaseModel):
    name: str
    status: str
    reason: str = ""

    model_config = {"extra": "ignore"}


class SelectionResponse(BaseModel):
    total_documents_found: int = 0
    selected_documents: list[SelectedDocumentRecord] = Field(default_factory=list)
    post_download: list[PostDownloadRecord] = Field(default_factory=list)

    model_config = {"extra": "ignore"}


@dataclass(slots=True)
class LLMSelectorConfig:
    model: str
    api_key: str
    api_base_url: str | None = None


def _normalize_priority(value: str) -> str:
    normalized = (value or "").strip().lower()
    if normalized in {"high", "medium", "low"}:
        return normalized
    return "medium"


def _score_for_priority(priority: str) -> int:
    normalized = _normalize_priority(priority)
    if normalized == "high":
        return 8
    if normalized == "medium":
        return 6
    return 4


class LLMDocumentSelector:
    def __init__(self, config: LLMSelectorConfig) -> None:
        if OpenAI is None or BaseModel is object:
            raise RuntimeError(
                "OpenAI and Pydantic are required for LLM selection. "
                "Run `pip install -r requirements.txt`."
            )

        client = OpenAI(
            api_key=config.api_key,
            base_url=config.api_base_url,
        )

        self.client = client
        self.model = config.model

    def select(
        self,
        source_url: str,
        candidates: list[DocumentCandidate],
    ) -> tuple[list[DocumentCandidate], dict[str, object]]:
        prompt_payload = {
            "source_url": source_url,
            "stage": "selection",
            "instructions": (
                "Return only high-value documents that materially help someone understand or "
                "apply for the tender. Populate selected_documents and keep post_download empty "
                "because downloads have not happened yet."
            ),
            "documents": [candidate.to_dict() for candidate in candidates],
        }

        response = self.client.responses.parse(
            model=self.model,
            instructions=(
                SELECTION_SYSTEM_PROMPT
                + "\nYou are currently in the pre-download selection step."
                + "\nUse only the provided candidate list."
                + "\nPopulate selected_documents, set post_download to an empty list,"
                + " and return valid structured output only."
            ),
            input=json.dumps(prompt_payload, ensure_ascii=False, indent=2),
            text_format=SelectionResponse,
        )

        parsed = response.output_parsed
        if parsed is None:
            raise RuntimeError("LLM selection did not return structured output.")

        selected_lookup: dict[str, dict[str, str]] = {}
        manifest_selected_documents: dict[str, dict[str, str]] = {}
        for item in parsed.selected_documents:
            if not item.url:
                continue

            selection = {
                "reason": item.reason,
                "priority": _normalize_priority(item.priority),
            }
            manifest_selected_documents[item.url] = selection
            selected_lookup[item.url] = selection
            selected_lookup[normalize_url(item.url)] = selection

        selected: list[DocumentCandidate] = []
        for candidate in candidates:
            selection = selected_lookup.get(candidate.url) or selected_lookup.get(
                normalize_url(candidate.url)
            )
            if selection is None:
                continue
            candidate.reason = selection["reason"]
            candidate.priority = selection["priority"]
            candidate.score = max(candidate.score, _score_for_priority(candidate.priority))
            selected.append(candidate)

        manifest = {
            "mode": "llm",
            "model": self.model,
            "reported_total_documents_found": parsed.total_documents_found,
            "selected_count": len(selected),
            "selected_urls": manifest_selected_documents,
        }
        return selected, manifest
