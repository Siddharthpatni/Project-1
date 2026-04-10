"""
Subprocess sandbox for running untrusted LLM-generated scraper code.

This implementation uses `resource.setrlimit` + a strict working
directory + a CPU/wall-clock timeout. For production we recommend
running the worker container itself under gVisor / Firecracker /
Kata-containers; this module is the Python-level inner fence.

The sandbox is intentionally conservative: it runs the script in a
subprocess so crashes, segfaults and infinite loops can't take down the
worker. It captures stdout/stderr for the feedback loop.
"""
from __future__ import annotations

import os
import resource
import subprocess
import sys
import time
from dataclasses import dataclass


@dataclass
class SandboxResult:
    returncode: int
    stdout: str
    stderr: str
    elapsed: float
    timed_out: bool = False


def _preexec(memory_mb: int):
    def _apply():
        # Memory cap (address space)
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


def run_script(
    script_path: str,
    workdir: str,
    timeout: int = 60,
    memory_mb: int = 512,
) -> SandboxResult:
    """
    Run a Python script in a locked-down subprocess.

    - Working directory forced to `workdir`.
    - Environment stripped to a minimal allowlist.
    - Memory and wall-clock capped.
    """
    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "PYTHONPATH": workdir,
        "HOME": workdir,
        "TMPDIR": workdir,
        "LC_ALL": "C.UTF-8",
        "LANG": "C.UTF-8",
    }

    t0 = time.time()
    try:
        proc = subprocess.Popen(
            [sys.executable, script_path],
            cwd=workdir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=_preexec(memory_mb),
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
        try:
            os.killpg(proc.pid, 9)
        except Exception:
            proc.kill()
        stdout_b, stderr_b = proc.communicate()
        return SandboxResult(
            returncode=-9,
            stdout=stdout_b.decode("utf-8", errors="replace"),
            stderr=stderr_b.decode("utf-8", errors="replace"),
            elapsed=time.time() - t0,
            timed_out=True,
        )
