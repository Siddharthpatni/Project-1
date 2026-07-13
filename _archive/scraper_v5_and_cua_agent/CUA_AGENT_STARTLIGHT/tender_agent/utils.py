from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse, urlsplit, urlunsplit

DOCUMENT_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".xlsm",
    ".csv",
    ".zip",
    ".rar",
    ".7z",
    ".dwg",
    ".dxf",
    ".odt",
    ".ods",
    ".rtf",
    ".txt",
    ".ppt",
    ".pptx",
}

IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".webp",
    ".bmp",
    ".ico",
    ".tif",
    ".tiff",
}

UNIMPORTANT_EXTENSIONS = IMAGE_EXTENSIONS | {
    ".mp4",
    ".mov",
    ".avi",
    ".webm",
    ".css",
    ".js",
    ".xml",
    ".json",
}

IMPORTANT_KEYWORDS = {
    "boq",
    "bill of quantity",
    "bill of quantities",
    "specification",
    "specifications",
    "technical",
    "terms",
    "conditions",
    "contract",
    "tender",
    "notice",
    "official notice",
    "requirements",
    "requirement",
    "scope",
    "drawing",
    "drawings",
    "schedule",
    "annex",
    "annexure",
    "addendum",
    "corrigendum",
    "rfp",
    "rft",
    "ifb",
    "bid document",
    "bekanntmachung",
    "vergabeunterlagen",
    "teilnahmeunterlagen",
    "ausschreibungsunterlagen",
    "leistungsverzeichnis",
    "leistungsbeschreibung",
    "vertragsunterlagen",
    "vertragsbedingungen",
    "preisblatt",
    "angebotsformular",
    "bewertungsmatrix",
    "zuschlagskriterien",
    "zeichnungsunterlagen",
    "anlagen",
    "anhang",
}

UNIMPORTANT_KEYWORDS = {
    "image",
    "images",
    "advert",
    "advertisement",
    "gallery",
    "photo",
    "logo",
    "banner",
    "privacy",
    "cookie",
    "help",
    "navigation",
    "home",
    "contact",
    "sitemap",
    "brochure",
    "promo",
}

SECTION_KEYWORDS = {
    "document",
    "documents",
    "attachment",
    "attachments",
    "download",
    "downloads",
    "notice",
    "tender",
    "bid",
    "corrigendum",
    "addendum",
    "detail",
    "details",
    "dokument",
    "dokumente",
    "unterlage",
    "unterlagen",
    "vergabeunterlagen",
    "teilnahmeunterlagen",
    "bekanntmachung",
    "ausschreibung",
    "anhang",
    "anhaenge",
    "anlage",
    "anlagen",
    "datei",
    "dateien",
    "leistungsverzeichnis",
}

PAGINATION_KEYWORDS = {
    "next",
    "more",
    "older",
    "page 2",
    "page 3",
    "weiter",
    "mehr",
    "naechste",
}

DETAIL_PAGE_KEYWORDS = {
    "detail",
    "details",
    "overview",
    "bekanntmachung",
    "ausschreibung",
    "verfahren",
    "notice",
    "announcement",
    "tender",
}

DOWNLOAD_HINT_KEYWORDS = {
    "/download",
    "download=",
    "download/",
    "attachment",
    "attachments",
    "file=",
    "docid=",
    "document",
    "documents",
    "dokument",
    "dokumente",
    "unterlage",
    "unterlagen",
    "bekanntmachung",
    "vergabeunterlagen",
    "teilnahmeunterlagen",
    "leistungsverzeichnis",
}


def normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def slugify(value: str, max_length: int = 80) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return cleaned[:max_length] or "site"


def normalize_url(url: str) -> str:
    parts = urlsplit(url)
    path = parts.path or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


def extract_extension(url: str) -> str:
    path = urlparse(url).path
    return Path(path).suffix.lower()


def guess_name_from_url(url: str) -> str:
    path = urlparse(url).path
    name = Path(path).name
    return name or normalize_whitespace(url)


def is_same_site(reference_url: str, candidate_url: str) -> bool:
    return urlparse(reference_url).netloc.lower() == urlparse(candidate_url).netloc.lower()


def is_probably_document_url(url: str) -> bool:
    lower_url = url.lower()
    extension = extract_extension(lower_url)
    if extension in DOCUMENT_EXTENSIONS:
        return True
    return any(token in lower_url for token in DOWNLOAD_HINT_KEYWORDS)


def looks_like_document_text(text: str) -> bool:
    normalized = normalize_whitespace(text).lower()
    return any(keyword in normalized for keyword in IMPORTANT_KEYWORDS | SECTION_KEYWORDS)


def looks_like_detail_page_text(text: str) -> bool:
    normalized = normalize_whitespace(text).lower()
    return any(keyword in normalized for keyword in DETAIL_PAGE_KEYWORDS)


def looks_like_unimportant_text(text: str) -> bool:
    normalized = normalize_whitespace(text).lower()
    return any(keyword in normalized for keyword in UNIMPORTANT_KEYWORDS)


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix
    counter = 1
    while True:
        candidate = path.with_name(f"{stem}-{counter}{suffix}")
        if not candidate.exists():
            return candidate
        counter += 1
