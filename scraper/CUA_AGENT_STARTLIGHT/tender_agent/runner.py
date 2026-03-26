from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from tender_agent.config import (
    DEFAULT_BATCH_LIMIT,
    DEFAULT_MODEL,
    RuntimeConfig,
)
from tender_agent.browser import TenderBrowserCrawler
from tender_agent.downloader import download_selected_documents
from tender_agent.filtering import select_important_documents
from tender_agent.input_loader import load_urls
from tender_agent.llm_selector import LLMDocumentSelector, LLMSelectorConfig
from tender_agent.models import SiteResult
from tender_agent.storage import RunArtifactLayout, create_run_layout
from tender_agent.system_prompt import SELECTION_SYSTEM_PROMPT

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional runtime dependency
    load_dotenv = None

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_project_env() -> None:
    if load_dotenv is None:
        return

    dotenv_path = PROJECT_ROOT / ".env"
    env_example_path = PROJECT_ROOT / ".env.example"

    if dotenv_path.exists():
        load_dotenv(dotenv_path=dotenv_path)
    elif env_example_path.exists():
        load_dotenv(dotenv_path=env_example_path)


_load_project_env()


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


class TenderDocumentAgent:
    def __init__(
        self,
        config: RuntimeConfig,
        run_layout: RunArtifactLayout,
    ) -> None:
        self.config = config
        self.run_layout = run_layout
        self.crawler = TenderBrowserCrawler(
            output_root=config.output_dir,
            max_pages=config.max_pages,
            max_scrolls=config.max_scrolls,
            headless=config.headless,
        )
        self.selector = self._build_selector()

    def _build_selector(self) -> LLMDocumentSelector | None:
        if not self.config.llm_enabled:
            return None

        try:
            return LLMDocumentSelector(
                LLMSelectorConfig(
                    model=self.config.model,
                    api_key=self.config.api_key or "",
                    api_base_url=self.config.api_base_url,
                )
            )
        except RuntimeError:
            return None

    async def process_url(self, url: str, index: int) -> SiteResult:
        layout = self.run_layout.site_layout(url=url, index=index)
        layout.ensure()
        layout.write_json(
            layout.site_metadata_path,
            {
                "url": url,
                "model": self.config.model,
                "llm_enabled": self.selector is not None,
            },
        )
        try:
            candidates, screenshots, browser_session = await self.crawler.discover_documents(
                url,
                screenshot_dir=layout.discovery_dir,
            )
            layout.write_json(
                layout.results_dir / "candidates.json",
                [candidate.to_dict() for candidate in candidates],
            )

            selection_manifest: dict[str, object]
            if self.selector is not None:
                try:
                    important_candidates, selection_manifest = self.selector.select(url, candidates)
                except Exception as exc:
                    important_candidates, _ = select_important_documents(candidates)
                    selection_manifest = {
                        "mode": "heuristic_fallback",
                        "selected_count": len(important_candidates),
                        "fallback_reason": str(exc),
                    }
            else:
                important_candidates, _ = select_important_documents(candidates)
                selection_manifest = {
                    "mode": "heuristic",
                    "selected_count": len(important_candidates),
                }

            layout.write_json(
                layout.results_dir / "selection.json",
                {
                    **selection_manifest,
                    "selected_documents": [candidate.to_dict() for candidate in important_candidates],
                },
            )
            downloaded_documents = download_selected_documents(
                important_candidates,
                staging_dir=layout.staging_download_dir,
                kept_dir=layout.kept_download_dir,
                browser_session=browser_session,
            )
            layout.write_json(
                layout.results_dir / "downloads.json",
                [document.to_manifest() for document in downloaded_documents],
            )

            result = SiteResult(
                url=url,
                total_documents_found=len(candidates),
                important_documents=downloaded_documents,
                screenshots=screenshots,
                artifact_root=layout.site_root,
            )
        except Exception as exc:
            layout.write_json(
                layout.results_dir / "error.json",
                {
                    "url": url,
                    "error": str(exc),
                },
            )
            result = SiteResult(
                url=url,
                total_documents_found=0,
                important_documents=[],
                screenshots=[],
                artifact_root=layout.site_root,
            )

        layout.final_result_path.write_text(
            json.dumps(result.to_output(), indent=2),
            encoding="utf-8",
        )
        return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Navigate tender pages, download only high-value documents, and output cleaned JSON results.",
    )
    parser.add_argument("urls", nargs="*", help="Tender URLs to inspect.")
    parser.add_argument(
        "--csv",
        default=os.getenv("TENDER_CSV_PATH"),
        help="Path to a CSV file containing tender URLs.",
    )
    parser.add_argument(
        "--csv-column",
        help="CSV column name that contains URLs. If omitted, the URL column is auto-detected.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=_env_int("TENDER_LIMIT", DEFAULT_BATCH_LIMIT),
        help="Maximum number of URLs to process from the combined direct URLs and CSV input.",
    )
    parser.add_argument(
        "--output-dir",
        default="artifacts",
        help="Directory where screenshots, downloads, and JSON results are written.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=12,
        help="Maximum number of same-site pages to inspect per tender URL.",
    )
    parser.add_argument(
        "--max-scrolls",
        type=int,
        default=6,
        help="Number of incremental scroll steps to run on each page.",
    )
    parser.add_argument(
        "--headful",
        action="store_true",
        help="Show the Chromium browser instead of running headless.",
    )
    parser.add_argument(
        "--show-prompt",
        action="store_true",
        help="Print the document-selection system prompt and exit.",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("OPENAI_MODEL", DEFAULT_MODEL),
        help="OpenAI model to use for document selection. Default: gpt-4o-mini.",
    )
    parser.add_argument(
        "--api-key",
        "--playwright-api-key",
        default=(
            os.getenv("AGENT_API_KEY")
            or os.getenv("PLAYWRIGHT_API_KEY")
            or os.getenv("OPENAI_API_KEY")
        ),
        help="API key for the OpenAI or OpenAI-compatible model provider.",
    )
    parser.add_argument(
        "--base-url",
        default=(
            os.getenv("AGENT_BASE_URL")
            or os.getenv("PLAYWRIGHT_BASE_URL")
            or os.getenv("OPENAI_BASE_URL")
        ),
        help="Optional OpenAI-compatible base URL, for example a proxy/provider endpoint.",
    )
    return parser


def _build_runtime_config(args: argparse.Namespace) -> RuntimeConfig:
    config = RuntimeConfig(
        output_dir=Path(args.output_dir),
        max_pages=args.max_pages,
        max_scrolls=args.max_scrolls,
        headless=not args.headful,
        csv_path=Path(args.csv) if args.csv else None,
        csv_column=args.csv_column,
        limit=args.limit,
        api_key=args.api_key,
        api_base_url=args.base_url,
        model=args.model,
    )
    config.apply_environment()
    return config


async def _run(args: argparse.Namespace) -> int:
    if args.show_prompt:
        print(SELECTION_SYSTEM_PROMPT)
        return 0

    config = _build_runtime_config(args)
    urls = load_urls(
        direct_urls=args.urls,
        csv_path=config.csv_path,
        csv_column=config.csv_column,
        limit=config.limit,
    )
    if not urls:
        raise SystemExit("No URLs were provided. Pass direct URLs or use --csv <path>.")

    run_layout = create_run_layout(config.output_dir)
    run_layout.ensure()
    agent = TenderDocumentAgent(config=config, run_layout=run_layout)

    results = []
    for index, url in enumerate(urls, start=1):
        results.append((await agent.process_url(url, index=index)).to_output())

    payload: dict[str, object] | list[dict[str, object]]
    payload = results[0] if len(results) == 1 else results
    run_layout.summary_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


def run_cli() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return asyncio.run(_run(args))
