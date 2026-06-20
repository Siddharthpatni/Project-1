from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from tender_agent.utils import slugify


@dataclass(slots=True)
class SiteArtifactLayout:
    site_root: Path
    site_metadata_path: Path
    discovery_dir: Path
    results_dir: Path
    staging_download_dir: Path
    kept_download_dir: Path
    final_result_path: Path

    def ensure(self) -> None:
        self.site_root.mkdir(parents=True, exist_ok=True)
        self.discovery_dir.mkdir(parents=True, exist_ok=True)
        self.results_dir.mkdir(parents=True, exist_ok=True)

    def write_json(self, path: Path, payload: object) -> None:
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


@dataclass(slots=True)
class RunArtifactLayout:
    run_root: Path
    sites_root: Path
    summary_path: Path

    def ensure(self) -> None:
        self.sites_root.mkdir(parents=True, exist_ok=True)

    def site_layout(self, url: str, index: int) -> SiteArtifactLayout:
        prefix = f"{index:03d}"
        parsed = urlparse(url)
        host_slug = slugify(parsed.netloc or "site", max_length=40)
        short_hash = hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]
        site_root = self.sites_root / f"{prefix}_{host_slug}_{short_hash}"
        return SiteArtifactLayout(
            site_root=site_root,
            site_metadata_path=site_root / "site.json",
            discovery_dir=site_root / "discovery" / "screenshots",
            results_dir=site_root / "results",
            staging_download_dir=site_root / "documents" / "_staging",
            kept_download_dir=site_root / "documents" / "kept",
            final_result_path=site_root / "results" / "final.json",
        )


def create_run_layout(output_root: Path) -> RunArtifactLayout:
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_root = output_root / "runs" / run_id
    return RunArtifactLayout(
        run_root=run_root,
        sites_root=run_root / "sites",
        summary_path=run_root / "run.json",
    )
