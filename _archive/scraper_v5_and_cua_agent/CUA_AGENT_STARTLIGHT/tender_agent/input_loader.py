from __future__ import annotations

import csv
from pathlib import Path

URL_COLUMN_CANDIDATES = (
    "url",
    "urls",
    "link",
    "website",
    "website_url",
    "tender_url",
    "tender link",
    "tender",
)


def load_urls(
    direct_urls: list[str],
    csv_path: Path | None = None,
    csv_column: str | None = None,
    limit: int | None = None,
) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()

    for url in direct_urls:
        cleaned = (url or "").strip()
        if not cleaned or cleaned in seen:
            continue
        urls.append(cleaned)
        seen.add(cleaned)

    if csv_path is not None:
        for url in _load_urls_from_csv(csv_path=csv_path, csv_column=csv_column):
            if url in seen:
                continue
            urls.append(url)
            seen.add(url)

    if limit is not None:
        return urls[:limit]
    return urls


def _load_urls_from_csv(csv_path: Path, csv_column: str | None = None) -> list[str]:
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    with csv_path.open("r", encoding="utf-8-sig", newline="") as file_handle:
        sample = file_handle.read(2048)
        file_handle.seek(0)
        try:
            has_header = csv.Sniffer().has_header(sample) if sample.strip() else True
        except csv.Error:
            has_header = True

        if has_header:
            reader = csv.DictReader(file_handle)
            if reader.fieldnames is None:
                return []

            selected_column = csv_column or _detect_url_column(reader.fieldnames)
            if selected_column is None:
                raise ValueError(
                    "Could not detect a URL column in the CSV. "
                    "Pass --csv-column with the correct header name."
                )
            if selected_column not in reader.fieldnames:
                raise ValueError(
                    f"CSV column '{selected_column}' was not found. "
                    f"Available columns: {', '.join(reader.fieldnames)}"
                )

            urls = []
            for row in reader:
                value = (row.get(selected_column) or "").strip()
                if value:
                    urls.append(value)
            return urls

        reader = csv.reader(file_handle)
        urls = []
        for row in reader:
            if not row:
                continue
            value = row[0].strip()
            if value:
                urls.append(value)
        return urls


def _detect_url_column(fieldnames: list[str]) -> str | None:
    normalized_lookup = {name.strip().lower(): name for name in fieldnames}
    for candidate in URL_COLUMN_CANDIDATES:
        if candidate in normalized_lookup:
            return normalized_lookup[candidate]
    return None
