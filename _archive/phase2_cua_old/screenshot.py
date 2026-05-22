"""
Screenshot capture utilities for CUA.

The orchestrator captures a full-page screenshot after every action and
passes it back to the LLM as a base64-encoded image in the vision
message. Screenshots are also persisted to disk for trace replay.
"""
from __future__ import annotations

import base64
import os
import time
from dataclasses import dataclass
from pathlib import Path

from app.config import settings


@dataclass
class Screenshot:
    png_bytes: bytes
    path: str
    timestamp: float

    def to_base64(self) -> str:
        return base64.b64encode(self.png_bytes).decode("ascii")


def save_screenshot(png_bytes: bytes, run_id: str, step: int) -> Screenshot:
    """Persist a screenshot to the configured directory."""
    base = Path(settings.cua_screenshot_dir) / run_id
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"step_{step:03d}.png"
    path.write_bytes(png_bytes)
    return Screenshot(png_bytes=png_bytes, path=str(path), timestamp=time.time())
