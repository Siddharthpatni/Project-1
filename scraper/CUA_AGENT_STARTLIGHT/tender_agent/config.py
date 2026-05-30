from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_BATCH_LIMIT = 10
PLACEHOLDER_VALUES = {
    "",
    "your-model-provider-key",
    "your-openai-key",
    "sk-...",
}


def _sanitize_secret(value: str | None) -> str | None:
    if value is None:
        return None

    cleaned = value.strip().strip("\"'")
    if cleaned.lower() in PLACEHOLDER_VALUES:
        return None
    return cleaned or None


def _sanitize_optional(value: str | None) -> str | None:
    if value is None:
        return None

    cleaned = value.strip().strip("\"'")
    return cleaned or None


@dataclass(slots=True)
class RuntimeConfig:
    output_dir: Path
    max_pages: int = 12
    max_scrolls: int = 6
    headless: bool = True
    csv_path: Path | None = None
    csv_column: str | None = None
    limit: int | None = None
    api_key: str | None = None
    api_base_url: str | None = None
    model: str = DEFAULT_MODEL

    @property
    def llm_enabled(self) -> bool:
        return bool(_sanitize_secret(self.api_key))

    def apply_environment(self) -> None:
        self.api_key = _sanitize_secret(self.api_key)
        self.api_base_url = _sanitize_optional(self.api_base_url)
        self.csv_column = _sanitize_optional(self.csv_column)
        self.model = _sanitize_optional(self.model) or DEFAULT_MODEL

        if self.api_key:
            os.environ["OPENAI_API_KEY"] = self.api_key

        if self.api_base_url:
            os.environ["OPENAI_BASE_URL"] = self.api_base_url
