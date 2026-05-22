"""
Tests for the validator (executor.py — Section 1 only)
=======================================================
Covers:
  - ValidationResult dataclass
  - _resolve_call_name()
  - validate() — all branches

No mocks needed. Pure AST, no side effects.

Run with:
    pytest test_validator.py -v
"""
from __future__ import annotations

import ast
import sys
import textwrap
from pathlib import Path

# pyrefly: ignore [missing-import]
import pytest

sys.path.insert(0, str(Path(__file__).parent))

from executor import (
    ValidationResult,
    validate,
    _resolve_call_name,
    FORBIDDEN_IMPORTS,
    FORBIDDEN_CALLS,
    REQUIRED_FUNCTION,
)


# ═══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _minimal_scraper(body: str = "    return {'tenders': [], 'downloaded_files': []}") -> str:
    """Valid scraper — just a scrape() function with a safe body."""
    return f"def scrape(url, output_dir):\n{body}\n"


# ═══════════════════════════════════════════════════════════════════════════════
#  ValidationResult dataclass
# ═══════════════════════════════════════════════════════════════════════════════

class TestValidationResult:
    def test_defaults(self):
        vr = ValidationResult(ok=True)
        assert vr.ok is True
        assert vr.errors == []
        assert vr.warnings == []

    def test_failed_result(self):
        vr = ValidationResult(ok=False, errors=["bad import"], warnings=["watch out"])
        assert not vr.ok
        assert len(vr.errors) == 1
        assert len(vr.warnings) == 1

    def test_lists_are_independent_between_instances(self):
        a = ValidationResult(ok=True)
        b = ValidationResult(ok=True)
        a.errors.append("x")
        assert b.errors == []


# ═══════════════════════════════════════════════════════════════════════════════
#  _resolve_call_name
# ═══════════════════════════════════════════════════════════════════════════════

class TestResolveCallName:
    def _parse_call(self, src: str) -> ast.Call:
        return ast.parse(src, mode="eval").body  # type: ignore[return-value]

    def test_simple_name(self):
        node = self._parse_call("eval('x')")
        assert _resolve_call_name(node.func) == "eval"

    def test_attribute_one_level(self):
        node = self._parse_call("os.system('ls')")
        assert _resolve_call_name(node.func) == "os.system"

    def test_attribute_two_levels(self):
        node = self._parse_call("subprocess.Popen(['ls'])")
        assert _resolve_call_name(node.func) == "subprocess.Popen"

    def test_chained_attribute(self):
        node = self._parse_call("a.b.c()")
        assert _resolve_call_name(node.func) == "a.b.c"

    def test_unknown_node_returns_empty_string(self):
        assert _resolve_call_name(ast.Constant(value=42)) == ""


# ═══════════════════════════════════════════════════════════════════════════════
#  validate() — syntax errors
# ═══════════════════════════════════════════════════════════════════════════════

class TestValidateSyntax:
    def test_syntax_error_returns_not_ok(self):
        result = validate("def :(")
        assert not result.ok
        assert any("SyntaxError" in e for e in result.errors)

    def test_empty_string_fails(self):
        result = validate("")
        assert not result.ok

    def test_valid_code_parses_fine(self):
        result = validate(_minimal_scraper())
        assert result.ok


# ═══════════════════════════════════════════════════════════════════════════════
#  validate() — required scrape() function
# ═══════════════════════════════════════════════════════════════════════════════

class TestValidateScrapeFunction:
    def test_missing_scrape_function(self):
        result = validate("x = 1\n")
        assert not result.ok
        assert any("scrape" in e for e in result.errors)

    def test_scrape_function_present(self):
        result = validate(_minimal_scraper())
        assert result.ok

    def test_required_function_constant_value(self):
        assert REQUIRED_FUNCTION == "scrape"


# ═══════════════════════════════════════════════════════════════════════════════
#  validate() — forbidden imports
# ═══════════════════════════════════════════════════════════════════════════════

class TestValidateForbiddenImports:
    @pytest.mark.parametrize("mod", sorted(FORBIDDEN_IMPORTS))
    def test_forbidden_plain_import(self, mod):
        code = _minimal_scraper() + f"\nimport {mod}\n"
        result = validate(code)
        assert not result.ok
        assert any(mod in e for e in result.errors)

    @pytest.mark.parametrize("mod", sorted(FORBIDDEN_IMPORTS))
    def test_forbidden_from_import(self, mod):
        code = _minimal_scraper() + f"\nfrom {mod} import something\n"
        result = validate(code)
        assert not result.ok
        assert any(mod in e for e in result.errors)

    def test_allowed_imports_pass(self):
        code = _minimal_scraper() + "\nimport json\nimport os\nimport re\n"
        result = validate(code)
        assert result.ok

    def test_forbidden_imports_is_set_of_strings(self):
        assert isinstance(FORBIDDEN_IMPORTS, set)
        assert all(isinstance(m, str) for m in FORBIDDEN_IMPORTS)


# ═══════════════════════════════════════════════════════════════════════════════
#  validate() — forbidden calls
# ═══════════════════════════════════════════════════════════════════════════════

class TestValidateForbiddenCalls:
    def test_eval_blocked(self):
        result = validate(_minimal_scraper() + "\neval('1+1')\n")
        assert not result.ok
        assert any("eval" in e for e in result.errors)

    def test_exec_blocked(self):
        result = validate(_minimal_scraper() + "\nexec('pass')\n")
        assert not result.ok
        assert any("exec" in e for e in result.errors)

    def test_os_system_blocked(self):
        result = validate(_minimal_scraper() + "\nos.system('ls')\n")
        assert not result.ok
        assert any("os.system" in e for e in result.errors)

    def test_os_popen_blocked(self):
        result = validate(_minimal_scraper() + "\nos.popen('ls')\n")
        assert not result.ok

    def test_subprocess_run_blocked(self):
        result = validate(_minimal_scraper() + "\nsubprocess.run(['ls'])\n")
        assert not result.ok

    def test_subprocess_popen_blocked(self):
        result = validate(_minimal_scraper() + "\nsubprocess.Popen(['ls'])\n")
        assert not result.ok

    def test_shutil_rmtree_blocked(self):
        result = validate(_minimal_scraper() + "\nshutil.rmtree('/tmp')\n")
        assert not result.ok

    def test_dunder_import_blocked(self):
        result = validate(_minimal_scraper() + "\n__import__('os')\n")
        assert not result.ok

    def test_compile_blocked(self):
        result = validate(_minimal_scraper() + "\ncompile('pass', '', 'exec')\n")
        assert not result.ok

    def test_socket_socket_blocked(self):
        result = validate(_minimal_scraper() + "\nsocket.socket()\n")
        assert not result.ok

    def test_forbidden_calls_is_set_of_strings(self):
        assert isinstance(FORBIDDEN_CALLS, set)
        assert all(isinstance(c, str) for c in FORBIDDEN_CALLS)


# ═══════════════════════════════════════════════════════════════════════════════
#  validate() — multiple errors & nesting
# ═══════════════════════════════════════════════════════════════════════════════

class TestValidateMultipleErrors:
    def test_multiple_errors_all_collected(self):
        code = _minimal_scraper() + "\nimport subprocess\neval('x')\nos.system('ls')\n"
        result = validate(code)
        assert not result.ok
        assert len(result.errors) >= 2

    def test_deeply_nested_forbidden_call_detected(self):
        code = _minimal_scraper() + textwrap.dedent("""
        def helper():
            class Inner:
                def method(self):
                    eval('x')
        """)
        result = validate(code)
        assert not result.ok

    def test_warnings_do_not_block_ok(self):
        vr = ValidationResult(ok=True, warnings=["something looks off"])
        assert vr.ok
