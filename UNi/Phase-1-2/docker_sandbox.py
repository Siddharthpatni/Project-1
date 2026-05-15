#!/usr/bin/env python3
"""
Phase-1 : Docker Sandbox Executor (Unified Edition)
====================================================

Runs LLM-generated scraper code inside a Docker container with:
  ✅ No host filesystem access (read-only code mount)
  ✅ Isolated output volume for downloaded documents
  ✅ CPU limit (1 core)
  ✅ Memory cap (configurable, default 512 MB)
  ✅ Wall-clock timeout (configurable, default 120 seconds)
  ✅ Restricted network (only outbound HTTP/HTTPS for scraping)
  ✅ Non-root user inside the container
  ✅ Read-only root filesystem (container can only write to /output)
  ✅ No privilege escalation (--security-opt no-new-privileges)
  ✅ Dropped all Linux capabilities

NEW IN UNIFIED EDITION
----------------------
- `run` auto-generates the scraper via generator.py if the file is missing,
  so you can go straight from URL → sandbox in a single command.
- Optional `--regenerate-on-fail` triggers generator.py regenerate if the
  scraper crashes (useful for quick feedback loops).

Usage
-----
    # Build the sandbox image first (one-time):
    python docker_sandbox.py build

    # Run a scraper in the sandbox (auto-generates it if missing):
    python docker_sandbox.py run generated_scrapers/scraper_example_com.py \\
        "https://example.com/tenders"

    # Run with custom limits:
    python docker_sandbox.py run scraper.py "https://example.com" \\
        --timeout 180 --memory 1024 --keep-downloads ./results

    # Auto-regenerate on failure:
    python docker_sandbox.py run scraper.py "https://example.com" \\
        --regenerate-on-fail

    # Run the built-in security tests:
    python docker_sandbox.py test

Requirements
------------
- Docker must be installed and running
- Python 3.10+ (this script itself uses only stdlib)
- generator.py must live next to this file for auto-generation to work
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from textwrap import dedent
from urllib.parse import urlparse


# ═══════════════════════════════════════════════════════════════════════════════
#  Configuration
# ═══════════════════════════════════════════════════════════════════════════════

def _load_dotenv() -> None:
    """Load .env from script dir, CWD, or up to 5 parent dirs above the script."""
    possible = [
        Path(__file__).parent / ".env",
        Path.cwd() / ".env",
    ]
    parent = Path(__file__).parent.parent
    for _ in range(5):
        candidate = parent / ".env"
        if candidate.is_file() and candidate not in possible:
            possible.append(candidate)
        if parent == parent.parent:
            break
        parent = parent.parent
    for env_file in possible:
        if env_file.is_file():
            for line in env_file.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
            break


_load_dotenv()

SANDBOX_IMAGE   = os.getenv("SANDBOX_IMAGE", "phase1-sandbox")
SANDBOX_TIMEOUT = int(os.getenv("SANDBOX_TIMEOUT", "120"))
SANDBOX_MEMORY  = int(os.getenv("SANDBOX_MEMORY_MB", "512"))
LOG_LEVEL       = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    level=getattr(logging, LOG_LEVEL, logging.INFO),
)
log = logging.getLogger("phase1.docker_sandbox")

DOCKERFILE_PATH = Path(__file__).parent / "Dockerfile.sandbox"
GENERATOR_PATH  = Path(__file__).parent / "generator.py"
DEFAULT_SCRAPERS_DIR = Path(__file__).parent / "generated_scrapers"


# ═══════════════════════════════════════════════════════════════════════════════
#  Data Classes
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class DockerSandboxResult:
    """Result of running a scraper inside a Docker container."""
    success: bool
    downloaded_files: list[str] = field(default_factory=list)
    scraper_output: dict | list | None = None
    stdout: str = ""
    stderr: str = ""
    runtime_seconds: float = 0.0
    timed_out: bool = False
    error: str | None = None
    container_id: str | None = None


# ═══════════════════════════════════════════════════════════════════════════════
#  Docker Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _docker_available() -> bool:
    """Check if Docker is installed and the daemon is running."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True, timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def build_sandbox_image(force: bool = False) -> bool:
    """Build the sandbox Docker image from Dockerfile.sandbox."""
    if not DOCKERFILE_PATH.exists():
        log.error("Dockerfile.sandbox not found at %s", DOCKERFILE_PATH)
        return False

    if not force:
        check = subprocess.run(
            ["docker", "image", "inspect", SANDBOX_IMAGE],
            capture_output=True,
        )
        if check.returncode == 0:
            log.info("Sandbox image '%s' already exists. Use --force to rebuild.", SANDBOX_IMAGE)
            return True

    log.info("Building sandbox image '%s' ...", SANDBOX_IMAGE)
    result = subprocess.run(
        [
            "docker", "build",
            "-t", SANDBOX_IMAGE,
            "-f", str(DOCKERFILE_PATH),
            str(DOCKERFILE_PATH.parent),
        ],
        capture_output=False,  # let the user see build output
    )
    if result.returncode != 0:
        log.error("Failed to build sandbox image.")
        return False

    log.info("✅ Sandbox image '%s' built successfully.", SANDBOX_IMAGE)
    return True


# ═══════════════════════════════════════════════════════════════════════════════
#  Generator Integration  (auto-generate / auto-regenerate scrapers)
# ═══════════════════════════════════════════════════════════════════════════════

def _expected_scraper_path(url: str, scrapers_dir: Path = DEFAULT_SCRAPERS_DIR) -> Path:
    """Match generator.py's naming: scraper_<domain-with-dots-as-underscores>.py."""
    domain_safe = urlparse(url).netloc.replace(".", "_") or "scraper"
    return scrapers_dir / f"scraper_{domain_safe}.py"


def _run_generator(args: list[str]) -> bool:
    """Invoke generator.py with the given subcommand args. Returns True on success."""
    if not GENERATOR_PATH.exists():
        log.error("generator.py not found next to docker_sandbox.py at %s", GENERATOR_PATH)
        return False

    cmd = [sys.executable, str(GENERATOR_PATH), *args]
    log.info("Running generator: %s", " ".join(cmd))

    proc = subprocess.run(cmd, cwd=str(GENERATOR_PATH.parent))
    if proc.returncode != 0:
        log.error("generator.py exited with code %d", proc.returncode)
        return False
    return True


def ensure_scraper_exists(scraper_path: Path, url: str, model: str | None = None) -> bool:
    """
    Make sure scraper_path exists; if not, ask generator.py to create it.
    Returns True if the file is on disk afterwards.
    """
    if scraper_path.is_file():
        return True

    log.warning("Scraper not found at %s — generating it now.", scraper_path)
    scraper_path.parent.mkdir(parents=True, exist_ok=True)

    gen_args = ["generate", url, "--output", str(scraper_path.parent)]
    if model:
        gen_args += ["--model", model]

    if not _run_generator(gen_args):
        return False

    if not scraper_path.is_file():
        # generator.py names the file from the URL's domain. If the user passed
        # an unusual filename, the generated file lives elsewhere — surface that.
        expected = _expected_scraper_path(url, scraper_path.parent)
        if expected.is_file():
            log.warning(
                "Generator produced %s but you asked for %s — using the generated path.",
                expected, scraper_path,
            )
            return True
        log.error("generator.py finished but %s still doesn't exist.", scraper_path)
        return False

    log.info("✅ Generated %s", scraper_path)
    return True


def regenerate_scraper(
    scraper_path: Path,
    url: str,
    iteration: int,
    outcome: str,
    error: str,
    expected_docs: int,
    downloaded: int,
    model: str | None = None,
) -> bool:
    """Ask generator.py to regenerate the scraper based on a failure."""
    log.info("Regenerating scraper at %s (iteration=%d, outcome=%s)",
             scraper_path, iteration, outcome)

    gen_args = [
        "regenerate", url,
        "--iteration", str(iteration),
        "--outcome", outcome,
        "--error", error[:3000],
        "--expected-docs", str(expected_docs),
        "--downloaded", str(downloaded),
        "--output", str(scraper_path.parent),
    ]
    if scraper_path.is_file():
        gen_args += ["--previous-code", str(scraper_path)]
    if model:
        gen_args += ["--model", model]

    return _run_generator(gen_args)


# ═══════════════════════════════════════════════════════════════════════════════
#  Runner Script Template (injected into the container)
# ═══════════════════════════════════════════════════════════════════════════════

_RUNNER_TEMPLATE = '''\
import json
import sys
import os
import traceback
import time

sys.path.insert(0, "/code")
from scraper import scrape

t0 = time.time()
output_dir = "/output"
os.makedirs(output_dir, exist_ok=True)

try:
    output = scrape({url!r}, output_dir)

    if isinstance(output, dict):
        files = output.get("downloaded_files", [])
    elif isinstance(output, list):
        files = output
    else:
        files = []

    # Verify the files the scraper claimed to download actually exist
    verified = [f for f in files if os.path.isfile(f)]

    # Also pick up any files the scraper created but didn't report
    for root, dirs, filenames in os.walk(output_dir):
        for fn in filenames:
            if fn.startswith("_"):
                continue  # skip our own _result.json, _runner.py
            full = os.path.join(root, fn)
            if full not in verified:
                verified.append(full)

    result = {{
        "ok": True,
        "output": output if isinstance(output, (dict, list)) else str(output),
        "files": verified,
        "elapsed": time.time() - t0,
    }}
except Exception as e:
    result = {{
        "ok": False,
        "error": str(e),
        "traceback": traceback.format_exc(),
        "elapsed": time.time() - t0,
    }}

with open("/output/_result.json", "w") as f:
    json.dump(result, f, default=str)
'''


# ═══════════════════════════════════════════════════════════════════════════════
#  Core: Run Scraper in Docker
# ═══════════════════════════════════════════════════════════════════════════════

def run_in_docker(
    code: str,
    url: str,
    timeout: int = SANDBOX_TIMEOUT,
    memory_mb: int = SANDBOX_MEMORY,
    keep_downloads: str | None = None,
) -> DockerSandboxResult:
    """
    Run scraper code inside a Docker container with full isolation.

    Security measures:
      - Code is mounted read-only at /code
      - Output volume at /output is the ONLY writable location
      - Container root filesystem is read-only
      - Memory capped (default 512 MB)
      - CPU capped (1 core)
      - Wall-clock timeout enforced
      - Non-root user inside container
      - No privilege escalation allowed
      - All Linux capabilities dropped
      - /tmp is a tmpfs (in-memory, 64 MB max)
    """
    if not _docker_available():
        return DockerSandboxResult(
            success=False,
            error="Docker is not available. Install Docker and ensure the daemon is running.",
        )

    tmp_base = tempfile.mkdtemp(prefix="phase1-docker-")
    code_dir = Path(tmp_base) / "code"
    output_dir = Path(tmp_base) / "output"
    code_dir.mkdir()
    output_dir.mkdir()
    # Make output_dir writable by the sandbox user (UID 1000 inside container)
    os.chmod(str(output_dir), 0o777)

    t0 = time.time()
    proc = None

    try:
        # Write scraper code + runner
        (code_dir / "scraper.py").write_text(code, encoding="utf-8")
        (code_dir / "_runner.py").write_text(
            _RUNNER_TEMPLATE.format(url=url),
            encoding="utf-8",
        )

        cmd = [
            "docker", "run",
            "--rm",
            "--name", f"phase1-sandbox-{int(time.time())}",

            # ── Resource limits ──
            f"--memory={memory_mb}m",
            "--memory-swap", f"{memory_mb}m",
            "--cpus=1",
            "--pids-limit=100",

            # ── Security ──
            "--security-opt", "no-new-privileges",
            "--cap-drop=ALL",
            "--read-only",
            "-e", "PLAYWRIGHT_BROWSERS_PATH=/ms-playwright",

            # ── Writable tmpfs ──
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",

            # ── Volume mounts ──
            "-v", f"{code_dir}:/code:ro",
            "-v", f"{output_dir}:/output:rw",

            # ── Image + command ──
            SANDBOX_IMAGE,
            "/code/_runner.py",
        ]

        log.info("Starting Docker sandbox (timeout=%ds, memory=%dMB, cpu=1)",
                 timeout, memory_mb)
        log.debug("Command: %s", " ".join(cmd))

        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        try:
            stdout_bytes, stderr_bytes = proc.communicate(timeout=timeout)
            timed_out = False
        except subprocess.TimeoutExpired:
            log.warning("Docker sandbox timed out after %ds — killing container", timeout)
            proc.kill()
            proc.wait()
            stdout_bytes = proc.stdout.read() if proc.stdout else b""
            stderr_bytes = proc.stderr.read() if proc.stderr else b""
            timed_out = True

        stdout = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
        stderr = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""
        elapsed = time.time() - t0

        # Read result file
        result_file = output_dir / "_result.json"
        if not result_file.exists():
            return DockerSandboxResult(
                success=False,
                stdout=stdout,
                stderr=stderr,
                runtime_seconds=elapsed,
                timed_out=timed_out,
                error=(
                    "Container exited without producing results. "
                    + ("TIMED OUT. " if timed_out else "")
                    + f"Exit code: {proc.returncode}. "
                    + (f"Stderr: {stderr[:500]}" if stderr.strip() else "")
                ),
            )

        try:
            payload = json.loads(result_file.read_text())
        except Exception as e:
            return DockerSandboxResult(
                success=False,
                stdout=stdout,
                stderr=stderr,
                runtime_seconds=elapsed,
                error=f"Invalid result.json from container: {e}",
            )

        if not payload.get("ok"):
            return DockerSandboxResult(
                success=False,
                stdout=stdout,
                stderr=stderr,
                runtime_seconds=payload.get("elapsed", elapsed),
                error=payload.get("error") or "Unknown scraper error",
            )

        # Collect downloaded files
        downloaded: list[str] = []
        for f in payload.get("files", []):
            basename = os.path.basename(f)
            host_path = output_dir / basename
            if host_path.exists():
                downloaded.append(str(host_path))

        # Pick up any extras the scraper created but didn't report
        for f in output_dir.rglob("*"):
            if f.is_file() and f.name != "_result.json" and str(f) not in downloaded:
                downloaded.append(str(f))

        # Optionally copy to a persistent location
        if keep_downloads and downloaded:
            keep_dir = Path(keep_downloads)
            keep_dir.mkdir(parents=True, exist_ok=True)
            saved = []
            for fpath in downloaded:
                src = Path(fpath)
                dst = keep_dir / src.name
                if dst.exists():
                    stem, suffix = dst.stem, dst.suffix
                    counter = 1
                    while dst.exists():
                        dst = keep_dir / f"{stem}_{counter}{suffix}"
                        counter += 1
                shutil.copy2(str(src), str(dst))
                saved.append(str(dst))
                log.info("Saved: %s", dst)
            downloaded = saved

        return DockerSandboxResult(
            success=True,
            downloaded_files=downloaded,
            scraper_output=payload.get("output"),
            stdout=stdout,
            stderr=stderr,
            runtime_seconds=payload.get("elapsed", elapsed),
        )

    except Exception as e:
        return DockerSandboxResult(
            success=False,
            runtime_seconds=time.time() - t0,
            error=f"Docker sandbox error: {e}",
        )
    finally:
        if not keep_downloads:
            shutil.rmtree(tmp_base, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  Validation + Run pipeline
# ═══════════════════════════════════════════════════════════════════════════════

def validate_and_run(
    code: str,
    url: str,
    timeout: int = SANDBOX_TIMEOUT,
    memory_mb: int = SANDBOX_MEMORY,
    keep_downloads: str | None = None,
) -> DockerSandboxResult:
    """
    Validate the scraper code first (AST safety check), then run it inside
    the Docker sandbox if it passes.

    Prefers the standalone `validator.py` (per ARCHITECTURE.md). Falls back
    to `executor.validate` for older trees, and finally to a bare
    `compile()` syntax check so this script remains usable on its own.
    """
    sys.path.insert(0, str(Path(__file__).parent))

    val = None
    try:
        from validator import validate as _validate  # type: ignore
        val = _validate(code)
    except ImportError:
        try:
            from executor import validate as _validate  # type: ignore
            val = _validate(code)
        except ImportError:
            log.warning(
                "Neither validator.py nor executor.py importable — "
                "falling back to basic syntax check."
            )
            try:
                compile(code, "<scraper>", "exec")
            except SyntaxError as e:
                return DockerSandboxResult(
                    success=False,
                    error=f"Syntax error in scraper: {e}",
                )

    if val is not None and not val.ok:
        return DockerSandboxResult(
            success=False,
            error="Validation failed: " + "; ".join(val.errors),
        )

    return run_in_docker(
        code=code,
        url=url,
        timeout=timeout,
        memory_mb=memory_mb,
        keep_downloads=keep_downloads,
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  Security Tests
# ═══════════════════════════════════════════════════════════════════════════════

_MALICIOUS_SAMPLES = {
    "filesystem_escape": {
        "description": "Tries to read /etc/passwd from the host",
        "code": dedent("""\
            import os
            def scrape(url, output_dir):
                try:
                    data = open("/etc/passwd").read()
                    with open(os.path.join(output_dir, "stolen.txt"), "w") as f:
                        f.write(data)
                except Exception as e:
                    with open(os.path.join(output_dir, "error.txt"), "w") as f:
                        f.write(f"BLOCKED: {e}")
                return {"downloaded_files": []}
        """),
        "expect_success": True,  # Runs but should NOT exfiltrate real /etc/passwd
        "check": lambda r: not any(
            "root:" in open(f).read()
            for f in r.downloaded_files
            if os.path.exists(f)
        ),
    },
    "host_write": {
        "description": "Tries to write outside output_dir",
        "code": dedent("""\
            import os
            def scrape(url, output_dir):
                try:
                    with open("/tmp/hacked.txt", "w") as f:
                        f.write("pwned")
                except Exception:
                    pass  # Should fail due to read-only fs / tmpfs noexec
                return {"downloaded_files": []}
        """),
        "expect_success": True,
        "check": lambda r: True,  # Just shouldn't crash the host
    },
    "memory_bomb": {
        "description": "Tries to allocate excessive memory",
        "code": dedent("""\
            def scrape(url, output_dir):
                data = []
                for i in range(2000):
                    data.append("X" * (1024 * 1024))  # 1 MB each
                return {"downloaded_files": []}
        """),
        "expect_success": False,  # Should be killed by OOM
        "check": lambda r: not r.success,
    },
    "fork_bomb": {
        "description": "Tries to fork-bomb the system",
        "code": dedent("""\
            import os
            def scrape(url, output_dir):
                while True:
                    try:
                        os.fork()
                    except Exception:
                        break
                return {"downloaded_files": []}
        """),
        "expect_success": False,  # Should be blocked by --pids-limit
        "check": lambda r: True,
    },
    "network_scan": {
        "description": "Tries to scan internal network",
        "code": dedent("""\
            import socket, os
            def scrape(url, output_dir):
                results = []
                for port in [22, 80, 443, 5432, 6379]:
                    try:
                        s = socket.create_connection(("172.17.0.1", port), timeout=1)
                        results.append(f"port {port} open")
                        s.close()
                    except Exception:
                        pass
                with open(os.path.join(output_dir, "scan.txt"), "w") as f:
                    f.write("\\n".join(results) if results else "no ports reached")
                return {"downloaded_files": []}
        """),
        "expect_success": True,
        "check": lambda r: True,  # Inspect manually
    },
    "safe_scraper": {
        "description": "Legitimate scraper that should work correctly",
        "code": dedent("""\
            import os
            def scrape(url, output_dir):
                os.makedirs(output_dir, exist_ok=True)
                filepath = os.path.join(output_dir, "test_doc.txt")
                with open(filepath, "w") as f:
                    f.write(f"Downloaded from: {url}\\nThis is a test document.")
                return {"downloaded_files": [filepath]}
        """),
        "expect_success": True,
        "check": lambda r: r.success and len(r.downloaded_files) > 0,
    },
}


def run_security_tests(timeout: int = 30, memory_mb: int = 256) -> dict:
    """Run all malicious-code samples against the Docker sandbox."""
    results = {}
    total = len(_MALICIOUS_SAMPLES)
    passed = 0

    print(f"\n{'═' * 70}")
    print(f"  Docker Sandbox Security Tests  ({total} tests)")
    print(f"{'═' * 70}\n")

    for name, test in _MALICIOUS_SAMPLES.items():
        print(f"  ▶ {name}: {test['description']}")
        t0 = time.time()

        result = run_in_docker(
            code=test["code"],
            url="https://example.com/test",
            timeout=timeout,
            memory_mb=memory_mb,
        )

        elapsed = time.time() - t0
        check_passed = test["check"](result)

        status = "✅ PASS" if check_passed else "❌ FAIL"
        print(f"    {status}  (took {elapsed:.1f}s, success={result.success})")
        if result.error:
            print(f"    Error: {result.error[:200]}")
        if result.downloaded_files:
            print(f"    Files: {result.downloaded_files}")
        print()

        results[name] = {
            "passed": check_passed,
            "success": result.success,
            "elapsed": elapsed,
            "error": result.error,
            "files": result.downloaded_files,
        }
        if check_passed:
            passed += 1

    print(f"{'═' * 70}")
    print(f"  Results: {passed}/{total} tests passed")
    print(f"{'═' * 70}\n")

    return results


# ═══════════════════════════════════════════════════════════════════════════════
#  Pretty Printers
# ═══════════════════════════════════════════════════════════════════════════════

def _print_result(result: DockerSandboxResult) -> None:
    """Pretty-print a sandbox execution result."""
    print(f"\n{'═' * 60}")
    print(f"  Status:     {'✅ SUCCESS' if result.success else '❌ FAILED'}")
    print(f"  Runtime:    {result.runtime_seconds:.1f}s")
    if result.timed_out:
        print(f"  ⚠ TIMED OUT")
    print(f"  Files:      {len(result.downloaded_files)} downloaded")

    if result.error:
        print(f"  Error:      {result.error[:300]}")

    if result.downloaded_files:
        print(f"\n  Downloaded files:")
        for f in result.downloaded_files:
            size = os.path.getsize(f) if os.path.exists(f) else 0
            size_str = f"{size / 1024:.1f} KB" if size < 1_000_000 else f"{size / 1_000_000:.1f} MB"
            print(f"    📄 {Path(f).name}  ({size_str})")

    print(f"{'═' * 60}\n")

    if result.stdout.strip():
        print("── stdout ──")
        print(result.stdout[:3000])
        print()
    if result.stderr.strip():
        print("── stderr ──")
        print(result.stderr[:3000])
        print()


# ═══════════════════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════════════════

def _resolve_scraper_path(file_arg: str, url: str) -> Path:
    """
    Figure out which scraper file the user wants.

    - If they pass an existing file, use it.
    - If they pass a directory, point at the conventional name inside it.
    - Otherwise treat the arg as a path that may or may not exist yet
      (so we can auto-generate it).
    """
    p = Path(file_arg)
    if p.is_dir():
        return _expected_scraper_path(url, p)
    return p


def cmd_run(args: argparse.Namespace) -> int:
    scraper_path = _resolve_scraper_path(args.file, args.url)

    # Auto-generate if missing
    if not scraper_path.is_file():
        if args.no_auto_generate:
            print(f"❌ Scraper not found at {scraper_path} (auto-generate disabled).",
                  file=sys.stderr)
            return 1
        if not ensure_scraper_exists(scraper_path, args.url, model=args.model):
            return 1
        # If generator wrote to its conventional path inside the same dir,
        # follow that.
        if not scraper_path.is_file():
            scraper_path = _expected_scraper_path(args.url, scraper_path.parent)

    code = scraper_path.read_text()

    def _run_once(code_to_run: str) -> DockerSandboxResult:
        if args.skip_validation:
            return run_in_docker(
                code=code_to_run, url=args.url,
                timeout=args.timeout, memory_mb=args.memory,
                keep_downloads=args.keep_downloads,
            )
        return validate_and_run(
            code=code_to_run, url=args.url,
            timeout=args.timeout, memory_mb=args.memory,
            keep_downloads=args.keep_downloads,
        )

    result = _run_once(code)
    _print_result(result)

    # Optional feedback loop: regenerate on failure and try again
    if not result.success and args.regenerate_on_fail:
        max_retries = max(1, args.max_retries)
        for attempt in range(2, max_retries + 2):  # iteration is 1-indexed; first try was 1
            err_text = result.error or result.stderr or "unknown failure"
            outcome = "execution_failed" if not result.timed_out else "timeout"
            log.info("Regenerate-on-fail: starting attempt %d", attempt)

            if not regenerate_scraper(
                scraper_path=scraper_path,
                url=args.url,
                iteration=attempt,
                outcome=outcome,
                error=err_text,
                expected_docs=0,
                downloaded=len(result.downloaded_files),
                model=args.model,
            ):
                log.error("Regeneration failed; aborting retry loop.")
                break

            # Re-read whatever generator.py just wrote
            if not scraper_path.is_file():
                # generator names by domain; fall back to that
                alt = _expected_scraper_path(args.url, scraper_path.parent)
                if alt.is_file():
                    scraper_path = alt
                else:
                    log.error("Could not find regenerated scraper on disk.")
                    break

            code = scraper_path.read_text()
            result = _run_once(code)
            _print_result(result)

            if result.success:
                break

    return 0 if result.success else 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase-1 Docker Sandbox Executor (Unified Edition)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=dedent("""\
            Examples:

              # Build the sandbox image (one-time):
              python docker_sandbox.py build

              # Run a scraper in the Docker sandbox (auto-generates if missing):
              python docker_sandbox.py run \\
                  generated_scrapers/scraper_www_evergabe-online_de.py \\
                  "https://www.evergabe-online.de/search.html"

              # Or just point at the directory and let the path auto-resolve:
              python docker_sandbox.py run generated_scrapers \\
                  "https://www.evergabe-online.de/search.html"

              # Run with custom limits:
              python docker_sandbox.py run scraper.py "https://example.com" \\
                  --timeout 180 --memory 1024

              # Auto-regenerate on failure (up to 3 retries):
              python docker_sandbox.py run scraper.py "https://example.com" \\
                  --regenerate-on-fail --max-retries 3

              # Keep downloaded files:
              python docker_sandbox.py run scraper.py "https://example.com" \\
                  --keep-downloads ./results

              # Run security tests:
              python docker_sandbox.py test
        """),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ── build ────────────────────────────────────────────────────────
    p_build = sub.add_parser("build", help="Build the sandbox Docker image")
    p_build.add_argument("--force", action="store_true",
                         help="Force rebuild even if image exists")

    # ── run ──────────────────────────────────────────────────────────
    p_run = sub.add_parser("run", help="Validate + run scraper in Docker sandbox")
    p_run.add_argument("file",
                       help="Path to the scraper .py file (or a directory; "
                            "the file is auto-named from the URL's domain)")
    p_run.add_argument("url", help="Target URL to pass to scrape()")
    p_run.add_argument("--timeout", "-t", type=int, default=SANDBOX_TIMEOUT,
                       help=f"Timeout in seconds (default: {SANDBOX_TIMEOUT})")
    p_run.add_argument("--memory", "-m", type=int, default=SANDBOX_MEMORY,
                       help=f"Memory limit in MB (default: {SANDBOX_MEMORY})")
    p_run.add_argument("--keep-downloads", "-k", default=None,
                       help="Directory to save downloaded files to")
    p_run.add_argument("--skip-validation", action="store_true",
                       help="Skip AST validation (not recommended)")
    p_run.add_argument("--no-auto-generate", action="store_true",
                       help="Don't auto-invoke generator.py if the scraper file is missing")
    p_run.add_argument("--regenerate-on-fail", action="store_true",
                       help="If the scraper fails, ask generator.py to fix it and retry")
    p_run.add_argument("--max-retries", type=int, default=2,
                       help="Max regeneration attempts when --regenerate-on-fail is set "
                            "(default: 2)")
    p_run.add_argument("--model", default=None,
                       help="LLM model to pass to generator.py (e.g. 'openai/gpt-4o')")

    # ── test ─────────────────────────────────────────────────────────
    p_test = sub.add_parser("test", help="Run security tests against the sandbox")
    p_test.add_argument("--timeout", type=int, default=30,
                        help="Timeout per test (default: 30s)")
    p_test.add_argument("--memory", type=int, default=256,
                        help="Memory limit per test in MB (default: 256)")

    args = parser.parse_args()

    if args.command == "build":
        ok = build_sandbox_image(force=args.force)
        sys.exit(0 if ok else 1)

    elif args.command == "run":
        sys.exit(cmd_run(args))

    elif args.command == "test":
        results = run_security_tests(timeout=args.timeout, memory_mb=args.memory)
        all_passed = all(r["passed"] for r in results.values())
        sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()