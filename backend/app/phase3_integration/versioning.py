"""
Document versioning for periodic re-checks.

Celery beat runs `check_for_updates` on a schedule (see workers.tasks).
For each domain with known documents, we re-run the existing scraper
and compare checksums. Changed documents get a bumped `version`.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass
class VersionDelta:
    added: list[str]
    modified: list[str]
    removed: list[str]


def checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compare_snapshots(old: dict[str, str], new: dict[str, str]) -> VersionDelta:
    """
    Given two {filename: checksum} mappings, return the delta.

    Used by the periodic versioning task to decide which documents need
    a new row in the `documents` table.
    """
    old_keys = set(old.keys())
    new_keys = set(new.keys())

    added    = sorted(new_keys - old_keys)
    removed  = sorted(old_keys - new_keys)
    modified = sorted(k for k in (old_keys & new_keys) if old[k] != new[k])

    return VersionDelta(added=added, modified=modified, removed=removed)
