"""
Static validation of LLM-generated scraper code.

Parses the generated code with Python's AST (Abstract Syntax Tree) to reject 
dangerous libraries or code blocks before execution in the sandbox.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field

FORBIDDEN_CALLS = {
    "eval", "exec", "compile",
    "__import__",
    "os.system", "os.popen",
    "subprocess.run", "subprocess.Popen", "subprocess.call", "subprocess.check_call",
    "socket.socket",
    "shutil.rmtree",
}

FORBIDDEN_IMPORTS = {
    "subprocess",
    "ctypes",
    "socket",
    "multiprocessing",
}

REQUIRED_FUNCTION = "scrape"


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def validate(code: str) -> ValidationResult:
    result = ValidationResult(ok=True)

    # 1. Parse AST
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return ValidationResult(ok=False, errors=[f"SyntaxError: {e}"])

    # 2. Require scrape(url, output_dir) function
    has_scrape = any(
        isinstance(node, ast.FunctionDef) and node.name == REQUIRED_FUNCTION
        for node in ast.walk(tree)
    )
    if not has_scrape:
        result.errors.append(f"missing required function `{REQUIRED_FUNCTION}(url, output_dir)`")

    # 3. Walk AST for forbidden structures
    for node in ast.walk(tree):
        # Check Imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in FORBIDDEN_IMPORTS:
                    result.errors.append(f"forbidden import: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            mod = (node.module or "").split(".")[0]
            if mod in FORBIDDEN_IMPORTS:
                result.errors.append(f"forbidden import-from: {node.module}")

        # Check Calls
        if isinstance(node, ast.Call):
            name = _resolve_call_name(node.func)
            if name in FORBIDDEN_CALLS:
                result.errors.append(f"forbidden call: {name}")

    result.ok = not result.errors
    return result


def _resolve_call_name(func: ast.AST) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        parts: list[str] = []
        cur: ast.AST = func
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
        return ".".join(reversed(parts))
    return ""
