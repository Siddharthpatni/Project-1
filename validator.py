#!/usr/bin/env python3
"""
Phase-1 : Scraper Validator  (Standalone)
=========================================

Per ARCHITECTURE.md, this is its own module:

    feedback_loop ──▶ generator
                  ──▶ validator    ◀── this file
                  ──▶ executor (sandbox)
                  ──▶ evaluator

What does this script do?
-------------------------
A static AST-based safety check for LLM-generated scraper code.

It looks for:
  1. Syntax errors                        →   ❌ block
  2. Missing `scrape(url, output_dir)`    →   ❌ block
  3. Forbidden imports (subprocess, …)    →   ❌ block
  4. Forbidden function calls (eval, …)   →   ❌ block

NO code is executed during validation — this is a pure-AST walk and
therefore safe to run on completely untrusted input.

Use it as a library
-------------------
    from validator import validate
    result = validate(code_str)
    if not result.ok:
        print(result.errors)

Use it as a CLI
---------------
    python validator.py scraper_example_com.py

Used by
-------
- `executor.py`        — re-exports validate / ValidationResult from here
- `docker_sandbox.py`  — calls validate() before launching the container
"""
from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass, field
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────────────
#  Policy
# ─────────────────────────────────────────────────────────────────────────────

# Imports that scraper code is NOT allowed to use — they could be used to
# escape the sandbox or damage the host system.
FORBIDDEN_IMPORTS: set[str] = {
    "subprocess",       # arbitrary shell commands
    "ctypes",           # C-level calls, bypasses Python safety
    "socket",           # raw network connections
    "multiprocessing",  # uncontrolled child processes
}

# Function calls that are NEVER allowed — even if the module sneaks in.
FORBIDDEN_CALLS: set[str] = {
    "eval",                       # arbitrary expression eval
    "exec",                       # arbitrary code exec
    "compile",                    # often pairs with eval/exec
    "__import__",                 # dynamic imports — bypasses import checks
    "os.system",                  # shell
    "os.popen",                   # shell + capture
    "subprocess.run",
    "subprocess.Popen",
    "subprocess.call",
    "subprocess.check_call",
    "socket.socket",              # raw sockets
    "shutil.rmtree",              # destructive
}

# The scraper MUST define this function — it's the entry point.
REQUIRED_FUNCTION = "scrape"


# ─────────────────────────────────────────────────────────────────────────────
#  Result type
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ValidationResult:
    """
    Result of validating scraper source code.

    ok=True  → all safety checks passed.
    ok=False → dangerous patterns found; DO NOT execute this code.

    errors:   blocking issues  (code will NOT be executed)
    warnings: non-blocking concerns
    """
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
#  Public API
# ─────────────────────────────────────────────────────────────────────────────

def validate(code: str) -> ValidationResult:
    """
    Parse and statically check scraper code.

    Steps:
      1. Try to parse        → catch syntax errors early
      2. Check for `scrape(url, output_dir)` definition
      3. Walk the AST for forbidden imports and function calls
    """
    result = ValidationResult(ok=True)

    # Step 1 — parse
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return ValidationResult(ok=False, errors=[f"SyntaxError: {e}"])

    # Step 2 — required function exists?
    has_scrape = any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == REQUIRED_FUNCTION
        for node in ast.walk(tree)
    )
    if not has_scrape:
        result.errors.append(
            f"Missing required function `{REQUIRED_FUNCTION}(url, output_dir)`. "
            f"The scraper must define this function as its entry point."
        )

    # Step 3 — scan for dangerous patterns
    for node in ast.walk(tree):

        # `import subprocess`, `import ctypes.foo`, ...
        if isinstance(node, ast.Import):
            for alias in node.names:
                top_module = alias.name.split(".")[0]
                if top_module in FORBIDDEN_IMPORTS:
                    result.errors.append(f"Forbidden import: `{alias.name}`")

        # `from subprocess import run`, ...
        elif isinstance(node, ast.ImportFrom):
            module = (node.module or "").split(".")[0]
            if module in FORBIDDEN_IMPORTS:
                result.errors.append(
                    f"Forbidden import: `from {node.module} import ...`"
                )

        # `eval(...)`, `os.system(...)`, ...
        if isinstance(node, ast.Call):
            call_name = _resolve_call_name(node.func)
            if call_name in FORBIDDEN_CALLS:
                result.errors.append(f"Forbidden function call: `{call_name}()`")

    result.ok = len(result.errors) == 0
    return result


def validate_file(path: str | Path) -> ValidationResult:
    """Convenience wrapper: read a .py file and validate its contents."""
    p = Path(path)
    if not p.is_file():
        return ValidationResult(ok=False, errors=[f"File not found: {p}"])
    return validate(p.read_text(encoding="utf-8"))


# ─────────────────────────────────────────────────────────────────────────────
#  Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_call_name(func_node: ast.AST) -> str:
    """
    Turn an AST call-node target into a dotted name string.

    Examples:
        eval(...)           → "eval"
        os.system(...)      → "os.system"
        subprocess.run(...) → "subprocess.run"
    """
    # Simple name:  eval(...)
    if isinstance(func_node, ast.Name):
        return func_node.id

    # Attribute access:  os.system(...) / subprocess.Popen(...)
    if isinstance(func_node, ast.Attribute):
        parts: list[str] = []
        current: ast.AST = func_node
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        return ".".join(reversed(parts))

    return ""


# ─────────────────────────────────────────────────────────────────────────────
#  CLI
# ─────────────────────────────────────────────────────────────────────────────

def _print_result(path: Path, result: ValidationResult) -> None:
    print(f"\n{'═' * 60}")
    print(f"  Validation: {path}")
    print(f"{'═' * 60}")
    print(f"  Status: {'✅ SAFE' if result.ok else '❌ UNSAFE'}")
    if result.errors:
        print(f"\n  Errors ({len(result.errors)}):")
        for err in result.errors:
            print(f"    ❌ {err}")
    if result.warnings:
        print(f"\n  Warnings ({len(result.warnings)}):")
        for w in result.warnings:
            print(f"    ⚠ {w}")
    print(f"{'═' * 60}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase-1 Scraper Validator — static AST safety check",
    )
    parser.add_argument(
        "files",
        nargs="+",
        help="One or more scraper .py files to validate",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Only print failures",
    )
    args = parser.parse_args()

    any_unsafe = False
    for f in args.files:
        path = Path(f)
        result = validate_file(path)
        if not result.ok:
            any_unsafe = True
            _print_result(path, result)
        elif not args.quiet:
            _print_result(path, result)

    sys.exit(1 if any_unsafe else 0)


if __name__ == "__main__":
    main()
