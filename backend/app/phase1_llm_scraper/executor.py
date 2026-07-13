"""
Execute LLM-generated scraper code in a sandbox.

We shell out via `core.sandbox.run_script` which wraps the code in a
subprocess with CPU/memory limits and a strict working directory. The
executor returns downloaded file paths plus captured stdout/stderr for
the feedback loop.

IMPORTANT: scrapers download into an `output_dir` that lives OUTSIDE the
temp workdir, so the files survive after the workdir is cleaned up. The
caller (feedback loop / pipeline) is then responsible for moving them
into S3/MinIO via `_persist_documents` and for cleaning up the per-run
output directory when it is finished with it via `cleanup_output_dir`.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import uuid
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
    output_dir: str | None = None  # persistent dir holding the downloads
    stdout: str = ""
    stderr: str = ""
    runtime_seconds: float = 0.0
    error: str | None = None


# Wrapper code that imports the generated scraper as a module and writes
# the returned list of files to a known path so we can read it back.
#
# `scrape()` may legally return:
#   * list[str]                              — list of file paths
#   * dict with key "downloaded_files"       — preferred (per the prompt)
# We normalise both shapes into a flat list.
_RUNNER_TEMPLATE = '''
import json, sys, traceback, time, os
sys.path.insert(0, {workdir!r})
from scraper import scrape

t0 = time.time()
try:
    raw = scrape({url!r}, {output_dir!r})
    blocked = ""
    if raw is None:
        files = []
    elif isinstance(raw, dict):
        files = raw.get("downloaded_files") or raw.get("files") or []
        blocked = str(raw.get("blocked_reason") or "")[:300]
    else:
        files = list(raw)
    files = [str(f) for f in files if isinstance(f, (str, bytes, os.PathLike)) and os.path.isfile(str(f))]
    result = {{"ok": True, "files": files, "blocked": blocked, "elapsed": time.time() - t0}}
except Exception as e:
    result = {{"ok": False, "error": str(e), "traceback": traceback.format_exc(), "elapsed": time.time() - t0}}

with open({result_path!r}, "w") as f:
    json.dump(result, f)
'''


def _make_persistent_output_dir() -> Path:
    """A directory that survives this function's lifetime; caller cleans up."""
    base = Path(settings.downloads_dir)
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError:
        # Fall back to system temp if the configured dir isn't writable
        # (e.g. local dev where /app/data/downloads doesn't exist).
        base = Path(tempfile.gettempdir()) / "vergabepilot-downloads"
        base.mkdir(parents=True, exist_ok=True)
    out = base / f"run-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    out.mkdir(parents=True, exist_ok=True)
    return out


def execute(code: str, url: str) -> ExecutionResult:
    """Run the scraper code in a sandbox and return what it produced.

    The downloads land in a persistent directory; only the temporary
    workdir (which holds scraper.py + result.json) is cleaned up here.
    """
    output_dir = _make_persistent_output_dir()

    with tempfile.TemporaryDirectory(prefix="vergabepilot-run-") as workdir:
        work = Path(workdir)
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
            err_tail = (sb.stderr or "")[-1500:]
            log.warning("phase1.executor.no_result_json", stderr=err_tail[:500])
            return ExecutionResult(
                success=False,
                output_dir=str(output_dir),
                stdout=sb.stdout,
                stderr=sb.stderr,
                runtime_seconds=sb.elapsed,
                error=f"scraper produced no result.json (likely crashed or timed out). stderr tail: {err_tail}",
            )

        try:
            payload = json.loads(result_path.read_text())
        except Exception as e:  # noqa: BLE001
            return ExecutionResult(
                success=False,
                output_dir=str(output_dir),
                stderr=sb.stderr,
                runtime_seconds=sb.elapsed,
                error=f"failed to parse result.json: {e}",
            )

        if not payload.get("ok"):
            return ExecutionResult(
                success=False,
                output_dir=str(output_dir),
                stdout=sb.stdout,
                stderr=sb.stderr,
                runtime_seconds=payload.get("elapsed", sb.elapsed),
                error=(payload.get("error") or "unknown error")
                + (f"\n{payload.get('traceback','')[:1500]}" if payload.get("traceback") else ""),
            )

    # workdir is cleaned up at the end of the `with` — but downloads live
    # in `output_dir`, so they survive. Confirm they're on disk AND that
    # they are real documents (not HTML error pages / login redirects).
    from app.phase1_llm_scraper.document_validator import is_real_document_file

    surviving: list[str] = []
    rejected: list[tuple[str, str]] = []

    def _consider(path: str) -> None:
        if not os.path.isfile(path) or path in surviving:
            return
        ok, reason = is_real_document_file(path)
        if ok:
            surviving.append(path)
        else:
            rejected.append((path, reason))
            log.warning(
                "phase1.executor.rejected_non_document",
                path=path, reason=reason,
            )
            try:
                os.remove(path)
            except OSError:
                pass

    for f in payload.get("files", []):
        _consider(str(f))
    # Also pick up anything in output_dir that the scraper saved without
    # including in its return value (defensive — generated code is sloppy).
    if os.path.isdir(output_dir):
        for entry in sorted(os.listdir(output_dir)):
            _consider(str(output_dir / entry))

    if not surviving:
        # A scraper-reported access wall (login/CAPTCHA/registration) is a more
        # honest failure reason than the generic "no valid documents", and
        # classify_error() maps it to the right category for the admin panel.
        blocked = (payload.get("blocked") or "").strip()
        return ExecutionResult(
            success=False,
            downloaded_files=[],
            output_dir=str(output_dir),
            stdout=sb.stdout,
            stderr=sb.stderr,
            runtime_seconds=payload.get("elapsed", sb.elapsed),
            error=blocked or (
                f"scraper produced no valid documents "
                f"(rejected {len(rejected)} non-document file(s): "
                f"{[r for _, r in rejected[:5]]})"
            ),
        )

    return ExecutionResult(
        success=True,
        downloaded_files=surviving,
        output_dir=str(output_dir),
        stdout=sb.stdout,
        stderr=sb.stderr,
        runtime_seconds=payload.get("elapsed", sb.elapsed),
    )


def cleanup_output_dir(output_dir: str | None) -> None:
    """Remove a previously-created output directory. Safe to call with None."""
    if not output_dir:
        return
    try:
        shutil.rmtree(output_dir, ignore_errors=True)
    except Exception as e:  # noqa: BLE001
        log.warning("phase1.executor.cleanup_failed", dir=output_dir, error=str(e))
