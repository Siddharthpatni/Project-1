"""
Deterministic strategy — direct download for known platforms.

When the platform classifier identifies a portal whose document URL can
be constructed from the input URL alone (DTVP/Satellite/VMPSatellite),
we skip both the registry lookup and the LLM and just fetch the file.

This is the cheapest, fastest branch of the cascade. On the dev branch's
~100-domain dataset, this path covered the majority of DTVP-family hits
with no LLM calls and no Playwright spin-up.
"""
from __future__ import annotations

import mimetypes
import os
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import requests

from app.config import settings
from app.phase1_llm_scraper.document_validator import is_real_document_file
from app.phase3_integration import platform_classifier
from app.utils.logger import get_logger

log = get_logger(__name__)


_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


@dataclass
class DeterministicResult:
    success: bool
    platform: str
    downloaded_files: list[str]
    output_dir: str | None = None
    error: str | None = None


def _make_output_dir() -> Path:
    base = Path(settings.downloads_dir)
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError:
        base = Path(tempfile.gettempdir()) / "vergabepilot-downloads"
        base.mkdir(parents=True, exist_ok=True)
    out = base / f"det-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _filename_from_url(url: str, content_type: str | None = None) -> str:
    name = os.path.basename(urlparse(url).path) or "download"
    # Strip query strings if any leaked into the basename
    name = name.split("?", 1)[0]
    if "." not in name and content_type:
        ext = mimetypes.guess_extension(content_type.split(";", 1)[0].strip())
        if ext:
            name += ext
    if "." not in name:
        name += ".bin"
    return name


def _download(url: str, dest: Path, timeout: int = 30) -> str | None:
    """Stream-download a URL. Returns the saved path or None on failure."""
    try:
        with requests.get(
            url,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept-Language": "de-DE,de;q=0.9,en;q=0.7",
            },
            stream=True,
            timeout=timeout,
            allow_redirects=True,
        ) as r:
            if r.status_code >= 400:
                log.warning("deterministic.bad_status", url=url, status=r.status_code)
                return None
            name = _filename_from_url(url, r.headers.get("Content-Type"))
            path = dest / name
            with open(path, "wb") as f:
                for chunk in r.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
            if path.stat().st_size == 0:
                log.warning("deterministic.empty_file", url=url)
                path.unlink(missing_ok=True)
                return None
            # Validate that the downloaded content is a real document,
            # not an HTML error page or login redirect.
            ok, reason = is_real_document_file(str(path))
            if not ok:
                log.warning("deterministic.not_a_document", url=url, reason=reason)
                path.unlink(missing_ok=True)
                return None
            return str(path)
    except Exception as e:  # noqa: BLE001
        log.warning("deterministic.download_failed", url=url, error=str(e))
        return None


def try_deterministic(url: str) -> DeterministicResult:
    """
    Identify the platform from the URL alone and, if it's a deterministic
    one (DTVP family), construct + download. No HTTP requests for
    classification — pure URL parsing.
    """
    platform = platform_classifier.classify_url(url)
    if not platform_classifier.is_deterministic(platform):
        return DeterministicResult(
            success=False, platform=platform, downloaded_files=[],
            error=f"platform {platform!r} is not deterministic",
        )

    download_url = platform_classifier.build_download_url(platform, url)
    if not download_url:
        return DeterministicResult(
            success=False, platform=platform, downloaded_files=[],
            error="could not build download URL from input",
        )

    log.info("deterministic.attempt", platform=platform, url=download_url)
    out = _make_output_dir()
    saved = _download(download_url, out)
    if not saved:
        return DeterministicResult(
            success=False, platform=platform, downloaded_files=[],
            output_dir=str(out),
            error="constructed URL did not return a usable file",
        )

    return DeterministicResult(
        success=True, platform=platform, downloaded_files=[saved],
        output_dir=str(out),
    )
