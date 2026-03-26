from __future__ import annotations

import time
import shutil
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from tender_agent.filtering import validate_download
from tender_agent.models import BrowserSession, DocumentCandidate, DownloadedDocument
from tender_agent.utils import guess_name_from_url, slugify, unique_path

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)


def _filename_from_headers(content_disposition: str | None) -> str | None:
    if not content_disposition:
        return None

    marker = "filename="
    if marker not in content_disposition.lower():
        return None

    filename = content_disposition.split("filename=", maxsplit=1)[1].strip().strip("\"'")
    return filename or None


def _safe_name(name: str) -> str:
    return slugify(name, max_length=120) or "document"


def _bucket_for_suffix(suffix: str) -> str:
    lower_suffix = suffix.lower()
    if lower_suffix == ".pdf":
        return "pdf"
    if lower_suffix in {".xls", ".xlsx", ".xlsm", ".csv", ".ods"}:
        return "spreadsheets"
    if lower_suffix in {".doc", ".docx", ".odt", ".rtf", ".txt"}:
        return "text"
    if lower_suffix in {".zip", ".rar", ".7z"}:
        return "archives"
    if lower_suffix in {".dwg", ".dxf"}:
        return "cad"
    if lower_suffix in {".ppt", ".pptx"}:
        return "presentations"
    return "other"


def _build_request(candidate: DocumentCandidate, session: BrowserSession | None) -> Request:
    headers = {
        "User-Agent": session.user_agent or USER_AGENT,
        "Accept": (
            "application/pdf,application/octet-stream,application/zip,"
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,"
            "application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document,"
            "*/*"
        ),
        "Referer": candidate.source_page,
        "Accept-Language": "en-US,en;q=0.9",
    }

    if session and session.cookie_header:
        headers["Cookie"] = session.cookie_header

    return Request(candidate.url, headers=headers)


def _download_with_retries(
    candidate: DocumentCandidate,
    destination: Path,
    session: BrowserSession | None,
    retries: int = 3,
) -> tuple[str | None, str | None]:
    last_error: Exception | None = None

    for attempt in range(1, retries + 1):
        request = _build_request(candidate, session)
        try:
            with urlopen(request, timeout=90) as response:
                content_disposition = response.headers.get("Content-Disposition")
                content_type = response.headers.get_content_type()
                final_url = response.geturl()
                filename = (
                    _filename_from_headers(content_disposition)
                    or guess_name_from_url(final_url)
                    or candidate.name
                )
                parsed_name = Path(filename)
                suffix = parsed_name.suffix or Path(urlparse(final_url).path).suffix
                base_name = _safe_name(parsed_name.stem or candidate.name)
                download_path = unique_path(destination / f"{base_name}{suffix}")

                with download_path.open("wb") as file_handle:
                    shutil.copyfileobj(response, file_handle)

                return str(download_path), content_type
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            last_error = exc
            time.sleep(min(attempt, 3))

    assert last_error is not None
    raise last_error


def download_selected_documents(
    candidates: list[DocumentCandidate],
    staging_dir: Path,
    kept_dir: Path,
    browser_session: BrowserSession | None = None,
) -> list[DownloadedDocument]:
    staging_dir.mkdir(parents=True, exist_ok=True)
    kept_dir.mkdir(parents=True, exist_ok=True)
    results: list[DownloadedDocument] = []
    known_hashes: set[str] = set()

    for candidate in candidates:
        try:
            staging_path_str, content_type = _download_with_retries(
                candidate=candidate,
                destination=staging_dir,
                session=browser_session,
            )
            staging_path = Path(staging_path_str)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            results.append(
                DownloadedDocument(
                    name=candidate.name,
                    url=candidate.url,
                    status="deleted",
                    reason=f"download failed: {exc}",
                )
            )
            continue

        keep, reason = validate_download(candidate, staging_path, content_type, known_hashes)
        if not keep:
            staging_path.unlink(missing_ok=True)
            results.append(
                DownloadedDocument(
                    name=candidate.name,
                    url=candidate.url,
                    status="deleted",
                    reason=reason,
                    content_type=content_type,
                )
            )
            continue

        bucket = _bucket_for_suffix(staging_path.suffix)
        target_dir = kept_dir / bucket
        target_dir.mkdir(parents=True, exist_ok=True)
        final_path = unique_path(target_dir / staging_path.name)
        shutil.move(str(staging_path), str(final_path))

        results.append(
            DownloadedDocument(
                name=final_path.name,
                url=candidate.url,
                status="kept",
                local_path=final_path,
                reason=reason,
                content_type=content_type,
                bucket=bucket,
            )
        )

    try:
        if staging_dir.exists() and not any(staging_dir.iterdir()):
            staging_dir.rmdir()
    except OSError:
        pass

    return results
