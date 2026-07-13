from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass(slots=True)
class BrowserSession:
    user_agent: str = ""
    cookie_header: str = ""


@dataclass(slots=True)
class DocumentCandidate:
    name: str
    url: str
    source_page: str
    link_text: str = ""
    extension: str = ""
    discovered_via: str = "page"
    score: int = 0
    reason: str = ""
    priority: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "url": self.url,
            "source_page": self.source_page,
            "link_text": self.link_text,
            "extension": self.extension,
            "discovered_via": self.discovered_via,
            "score": self.score,
            "reason": self.reason,
            "priority": self.priority,
        }


@dataclass(slots=True)
class DownloadedDocument:
    name: str
    url: str
    status: Literal["kept", "deleted"]
    local_path: Path | None = None
    reason: str = ""
    content_type: str | None = None
    bucket: str = ""

    def to_output(self) -> dict[str, str]:
        return {
            "name": self.name,
            "url": self.url,
            "status": self.status,
        }

    def to_manifest(self) -> dict[str, object]:
        return {
            "name": self.name,
            "url": self.url,
            "status": self.status,
            "reason": self.reason,
            "content_type": self.content_type,
            "bucket": self.bucket,
            "local_path": str(self.local_path) if self.local_path else None,
        }


@dataclass(slots=True)
class SiteResult:
    url: str
    total_documents_found: int
    important_documents: list[DownloadedDocument] = field(default_factory=list)
    screenshots: list[Path] = field(default_factory=list)
    artifact_root: Path | None = None

    def to_output(self) -> dict[str, object]:
        return {
            "url": self.url,
            "total_documents_found": self.total_documents_found,
            "important_documents": [
                document.to_output() for document in self.important_documents
            ],
        }
