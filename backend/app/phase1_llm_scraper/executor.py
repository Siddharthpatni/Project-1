"""
Execute LLM-generated scraper code in a sandbox.

We shell out via `core.sandbox.run_script` which wraps the code in a
subprocess with CPU/memory limits and a strict working directory. The
executor returns downloaded file paths plus captured stdout/stderr for
the feedback loop.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from app.config import settings
from app.core.sandbox import SandboxResult, run_script
from app.utils.logger import get_logger

log = get_logger(__name__)


@dataclass
class ExecutionResult:
    success: bool
    downloaded_files: list[str] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    runtime_seconds: float = 0.0
    error: str | None = None


# Wrapper code that imports the generated scraper as a module and writes
# the returned list of files to a known path so we can read it back.
_RUNNER_TEMPLATE = '''
import json, sys, traceback, time
sys.path.insert(0, {workdir!r})
from scraper import scrape

t0 = time.time()
try:
    files = scrape({url!r}, {output_dir!r}) or []
    result = {{"ok": True, "files": files, "elapsed": time.time() - t0}}
except Exception as e:
    result = {{"ok": False, "error": str(e), "traceback": traceback.format_exc(), "elapsed": time.time() - t0}}

with open({result_path!r}, "w") as f:
    json.dump(result, f)
'''


def execute(code: str, url: str) -> ExecutionResult:
    with tempfile.TemporaryDirectory(prefix="vergabepilot-run-") as workdir:
        work = Path(workdir)
        output_dir = work / "downloads"
        output_dir.mkdir()

        (work / "scraper.py").write_text(code)
        result_path = work / "result.json"

        runner = _RUNNER_TEMPLATE.format(
            workdir=str(work),
            url=url,
            output_dir=str(output_dir),
            result_path=str(result_path),
        )
        runner_path = work / "_runner.py"
        runner_path.write_text(runner)

        sb: SandboxResult = run_script(
            script_path=str(runner_path),
            workdir=str(work),
            timeout=settings.sandbox_timeout_seconds,
            memory_mb=settings.sandbox_memory_mb,
        )

        if not result_path.exists():
            return ExecutionResult(
                success=False,
                stdout=sb.stdout,
                stderr=sb.stderr,
                runtime_seconds=sb.elapsed,
                error="scraper produced no result.json (likely crashed or timed out)",
            )

        try:
            payload = json.loads(result_path.read_text())
        except Exception as e:  # noqa: BLE001
            return ExecutionResult(
                success=False, stderr=sb.stderr, runtime_seconds=sb.elapsed,
                error=f"failed to parse result.json: {e}",
            )

        if not payload.get("ok"):
            return ExecutionResult(
                success=False,
                stdout=sb.stdout,
                stderr=sb.stderr,
                runtime_seconds=payload.get("elapsed", sb.elapsed),
                error=payload.get("error") or "unknown error",
            )

        # Move downloads out of the temp dir so caller can keep them.
        files = []
        for f in payload.get("files", []):
            if os.path.isfile(f):
                files.append(f)
        return ExecutionResult(
            success=True,
            downloaded_files=files,
            stdout=sb.stdout,
            stderr=sb.stderr,
            runtime_seconds=payload.get("elapsed", sb.elapsed),
        )
