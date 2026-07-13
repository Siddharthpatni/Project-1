"""
Static security validation of LLM-generated scraper code.

Two-layer defense model:
  Layer 1 (this module): AST-level static analysis — rejects dangerous code at
    parse time before it ever reaches the interpreter. Fast and deterministic.
  Layer 2 (core.sandbox): Subprocess isolation with CPU/memory limits — contains
    any harm that static analysis missed (e.g. obfuscated eval via base64).

Both layers must agree for the code to be executed. The static check runs first
so we don't waste sandbox resources on obviously malicious code.

Why AST-based instead of regex?
  Regex patterns on source text can be bypassed with whitespace, comments,
  or string splitting. AST analysis sees the code as the Python interpreter
  does — eval("ex" + "ec") still resolves to ast.Call(func=ast.Name(id="eval")).
  This makes it significantly harder to evade.

Design philosophy: Allowlist mindset
  Rather than trying to blacklist every possible harmful pattern, the scraper
  API contract is narrow: write a `scrape(url, output_dir)` function that uses
  httpx/requests/playwright to download files. Any call outside that contract
  is suspicious and should be rejected until proven necessary.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field

# ── Forbidden call names ────────────────────────────────────────────────────────
# Each entry blocks a specific Python built-in or library call that could:
#   - Execute arbitrary shell commands (eval, exec, os.system, subprocess.*)
#   - Load and run arbitrary modules (__import__, compile)
#   - Open raw network sockets (socket.socket) — scrapers must use httpx/requests
#   - Delete files outside the sandbox (shutil.rmtree)
FORBIDDEN_CALLS = {
    "eval",             # arbitrary Python execution
    "exec",             # same
    "compile",          # builds code objects that can then be eval'd
    "__import__",       # dynamic module loading bypasses the import blocklist
    "os.system",        # shell command execution
    "os.popen",         # same, returns a file-like pipe to shell stdout
    "subprocess.run",   # explicit subprocess spawning
    "subprocess.Popen", # same
    "subprocess.call",  # same
    "subprocess.check_call",  # same
    "socket.socket",    # raw socket — scrapers must use requests/httpx, not sockets
    "shutil.rmtree",    # could delete files outside the sandboxed output dir
}

# ── Forbidden top-level imports ─────────────────────────────────────────────────
# Imports at the module level that should never appear in generated scrapers.
# Note: we block the top-level module name so `import subprocess as sp` and
# `from subprocess import run` are both caught.
FORBIDDEN_IMPORTS = {
    "subprocess",      # shell execution — all subprocess usage is forbidden
    "ctypes",          # direct memory access and DLL loading
    "socket",          # raw network sockets
    "multiprocessing", # spawning additional processes from within the sandbox
}

# The scraper API contract: every generated scraper must export this function.
# Checked at validation time to catch scrapers that produce code but forget
# the entry point (e.g. if the LLM wraps it in a class or uses a different name).
REQUIRED_FUNCTION = "scrape"


@dataclass
class ValidationResult:
    """
    Result of the static validation pass.

    Attributes:
        ok:       True iff the code passed all checks and is safe to sandbox-run.
        errors:   Blocking issues — code MUST NOT be executed when any are present.
        warnings: Non-blocking observations (unused imports, style, etc.) —
                  currently not populated but reserved for future quality checks.
    """
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def validate(code: str) -> ValidationResult:
    """
    Validate a scraper's source code before sandboxed execution.

    Performs three checks in order:
      1. Syntax validity — `ast.parse()` raises SyntaxError on invalid Python.
      2. Required function — the `scrape(url, output_dir)` entry point must exist.
      3. Forbidden constructs — dangerous imports and call sites.

    Args:
        code: Raw Python source string as returned by the LLM.

    Returns:
        ValidationResult with ok=True only if all checks pass.
    """
    result = ValidationResult(ok=True)

    # ── Step 1: Parse ──────────────────────────────────────────────────────────
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        # Unparseable code can't be validated further; return immediately.
        return ValidationResult(ok=False, errors=[f"SyntaxError: {e}"])

    # ── Step 2: Require scrape() entry point ───────────────────────────────────
    has_scrape = any(
        isinstance(node, ast.FunctionDef) and node.name == REQUIRED_FUNCTION
        for node in ast.walk(tree)
    )
    if not has_scrape:
        result.errors.append(f"missing required function `{REQUIRED_FUNCTION}(url, output_dir)`")

    # ── Step 3: Walk AST for forbidden constructs ─────────────────────────────
    for node in ast.walk(tree):
        # Check import statements (covers both `import X` and `from X import Y` forms)
        if isinstance(node, ast.Import):
            for alias in node.names:
                # Normalise to top-level module name: `import subprocess.run` → "subprocess"
                top = alias.name.split(".")[0]
                if top in FORBIDDEN_IMPORTS:
                    result.errors.append(f"forbidden import: {alias.name}")

        elif isinstance(node, ast.ImportFrom):
            # `from subprocess import run` → module is "subprocess"
            mod = (node.module or "").split(".")[0]
            if mod in FORBIDDEN_IMPORTS:
                result.errors.append(f"forbidden import-from: {node.module}")

        # Check function/method calls
        if isinstance(node, ast.Call):
            # Resolve the dotted name of the called function (e.g. "os.system")
            name = _resolve_call_name(node.func)
            if name in FORBIDDEN_CALLS:
                result.errors.append(f"forbidden call: {name}")

    result.ok = not result.errors
    return result


def _resolve_call_name(func: ast.AST) -> str:
    """
    Resolve an AST call target to a dotted name string.

    Handles three forms:
      - `eval(...)` → "eval"  (ast.Name)
      - `os.system(...)` → "os.system"  (ast.Attribute chain)
      - `complex_expr(...)` → ""  (anything else — ignored)

    We only need to match against a known set of forbidden names so returning
    an empty string for unresolvable call targets is safe.
    """
    if isinstance(func, ast.Name):
        return func.id

    if isinstance(func, ast.Attribute):
        # Walk the attribute chain right-to-left to reconstruct "a.b.c"
        parts: list[str] = []
        cur: ast.AST = func
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
        return ".".join(reversed(parts))

    return ""
