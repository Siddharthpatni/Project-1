"""
Subprocess sandbox for running untrusted LLM-generated scraper code.

This implementation uses `resource.setrlimit` + a strict working
directory + a CPU/wall-clock timeout. For production we recommend
running the worker container itself under gVisor / Firecracker /
Kata-containers; this module is the Python-level inner fence.

The sandbox is intentionally conservative: it runs the script in a
subprocess so crashes, segfaults and infinite loops can't take down the
worker. It captures stdout/stderr for the feedback loop.

NOTE: Generated scrapers legitimately need to import installed packages
(playwright, requests, bs4, lxml, …). We therefore preserve the host's
site-packages by inheriting the parent's `PYTHONPATH` and the Python
import paths derived from the running interpreter. We only strip
sensitive environment variables (e.g. AWS keys, API keys) so the
sandboxed code can't exfiltrate them.

Cross-platform notes
--------------------
- ``resource`` / ``os.setsid`` / ``os.killpg`` are Unix-only.
  On Windows the sandbox uses ``CREATE_NEW_PROCESS_GROUP`` +
  ``taskkill`` to achieve equivalent process-tree management.
- Memory caps are only enforced on systems that support
  ``resource.RLIMIT_AS`` (most Linux/macOS). On Windows the scraper
  runs without a memory cap at the Python level (Docker or Job Objects
  should be used for production).
"""
from __future__ import annotations

import os
import platform
import signal
import site
import subprocess
import sys
import time
from dataclasses import dataclass

# `resource` is Unix-only — import conditionally.
try:
    import resource  # type: ignore[import-not-found]
except ImportError:
    resource = None  # type: ignore[assignment]

IS_WINDOWS = platform.system() == "Windows"

# Environment variables we strip before spawning the sandboxed script.
# Anything that looks like a secret should not be visible to untrusted
# generated code.
_SENSITIVE_ENV_PREFIXES = (
    "AWS_", "ANTHROPIC_", "OPENAI_", "GOOGLE_", "GEMINI_", "OPENROUTER_",
    "MINIO_", "DATABASE_URL", "REDIS_", "SECRET_", "S3_",
    "POSTGRES_", "CELERY_", "AZURE_", "COHERE_", "MISTRAL_", "DEEPSEEK_",
    "GROQ_", "TOGETHER_", "HF_", "HUGGINGFACE_", "SENTRY_",
)

# Substrings that mark a variable as secret regardless of its prefix
# (e.g. MY_APP_PASSWORD, PORTAL_TOKEN).
_SENSITIVE_ENV_SUBSTRINGS = ("PASSWORD", "TOKEN", "APIKEY", "API_KEY", "CREDENTIAL", "PRIVATE_KEY")


@dataclass
class SandboxResult:
    returncode: int
    stdout: str
    stderr: str
    elapsed: float
    timed_out: bool = False


def _preexec(memory_mb: int):
    """Return a preexec_fn for Unix, or None on Windows."""
    if IS_WINDOWS:
        return None

    def _apply():
        # Memory cap (address space)
        if resource is not None:
            try:
                bytes_cap = memory_mb * 1024 * 1024
                resource.setrlimit(resource.RLIMIT_AS, (bytes_cap, bytes_cap))
            except Exception:
                pass
            # No core dumps
            try:
                resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
            except Exception:
                pass
        # New process group so we can kill the whole tree
        os.setsid()
    return _apply


def _kill_process_tree(proc: subprocess.Popen):
    """Kill the subprocess and all its children, cross-platform."""
    try:
        if IS_WINDOWS:
            subprocess.call(
                ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except Exception:
        proc.kill()


def _build_python_path(workdir: str) -> str:
    """
    Build a PYTHONPATH that includes:
      - the scraper's workdir (so `from scraper import scrape` works)
      - the site-packages dirs of the host interpreter (so the scraper
        can import installed libs like playwright/requests)
    """
    parts = [workdir]
    # Site-packages and other import paths the host interpreter uses.
    try:
        parts.extend(p for p in site.getsitepackages() if p)
    except Exception:
        pass
    try:
        usp = site.getusersitepackages()
        if usp:
            parts.append(usp)
    except Exception:
        pass
    # sys.path captures everything the running interpreter uses, including
    # virtualenv site-packages, dist-packages, etc.
    for p in sys.path:
        if p and p not in parts:
            parts.append(p)
    # Inherit caller's PYTHONPATH last so it has lowest priority.
    extra = os.environ.get("PYTHONPATH", "")
    if extra:
        for p in extra.split(os.pathsep):
            if p and p not in parts:
                parts.append(p)
    return os.pathsep.join(parts)


def _build_env(workdir: str) -> dict[str, str]:
    """A minimal environment for the sandboxed process.

    Inherits non-sensitive variables from the parent so installed Python
    packages, browser binaries (Playwright), and locale settings work.
    """
    inherit = {}
    for k, v in os.environ.items():
        k_upper = k.upper()
        if any(k_upper.startswith(prefix) for prefix in _SENSITIVE_ENV_PREFIXES):
            continue
        # Filter secrets that don't share a known prefix (MY_APP_PASSWORD,
        # PORTAL_ACCESS_TOKEN, …) by name substring.
        if any(marker in k_upper for marker in _SENSITIVE_ENV_SUBSTRINGS):
            continue
        inherit[k] = v

    overrides = {
        "PYTHONPATH":   _build_python_path(workdir),
        "HOME":         workdir,
        "TMPDIR":       workdir,
        "LC_ALL":       "C.UTF-8",
        "LANG":         "C.UTF-8",
        # Make Playwright work without re-downloading browsers
        # (they are installed system-wide by the Dockerfile).
        "PLAYWRIGHT_BROWSERS_PATH": os.environ.get(
            "PLAYWRIGHT_BROWSERS_PATH", "0"
        ),
    }
    if IS_WINDOWS:
        overrides.update({
            "USERPROFILE": workdir,
            "TEMP":        workdir,
            "TMP":         workdir,
        })

    inherit.update(overrides)
    return inherit


def run_script(
    script_path: str,
    workdir: str,
    timeout: int = 60,
    memory_mb: int = 512,
) -> SandboxResult:
    """
    Run a Python script in a locked-down subprocess.

    - Working directory forced to `workdir`.
    - Environment stripped of secrets but inherits site-packages access.
    - Memory and wall-clock capped.
    """
    env = _build_env(workdir)

    popen_kwargs: dict = {
        "cwd": workdir,
        "env": env,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
    }
    preexec_fn = _preexec(memory_mb)
    if preexec_fn is not None:
        popen_kwargs["preexec_fn"] = preexec_fn
    if IS_WINDOWS:
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    t0 = time.time()
    try:
        proc = subprocess.Popen(
            [sys.executable, script_path],
            **popen_kwargs,
        )
    except Exception as e:  # noqa: BLE001
        return SandboxResult(
            returncode=-1, stdout="", stderr=f"failed to spawn: {e}", elapsed=0.0,
        )

    try:
        stdout_b, stderr_b = proc.communicate(timeout=timeout)
        return SandboxResult(
            returncode=proc.returncode,
            stdout=stdout_b.decode("utf-8", errors="replace"),
            stderr=stderr_b.decode("utf-8", errors="replace"),
            elapsed=time.time() - t0,
        )
    except subprocess.TimeoutExpired:
        _kill_process_tree(proc)
        try:
            stdout_b, stderr_b = proc.communicate(timeout=5)
        except Exception:
            stdout_b, stderr_b = b"", b""
        return SandboxResult(
            returncode=-9,
            stdout=stdout_b.decode("utf-8", errors="replace"),
            stderr=stderr_b.decode("utf-8", errors="replace"),
            elapsed=time.time() - t0,
            timed_out=True,
        )
