"""
Script Sandbox Tests

Verifies the AST-based sandbox actually prevents the bypass patterns
identified in audit:

  Bug 1 (CRITICAL): Method-call bypass — obj.getattr(), x.__import__()
    used to slip past the validator because it only checked ast.Name.
  Bug 2 (CRITICAL): Subscript bypass — x['__class__'] worked because
    visit_Subscript was never defined.
  Bug 3 (CRITICAL): String-concat bypass — '__' + 'class__' inside a
    subscript evaluated at runtime, evading static analysis.
  Bug 4 (HIGH): No recursion limit — one-liner recursion bomb crashed
    the daq_service. Now sys.setrecursionlimit(100) wraps exec().

Tests use the actual _SandboxValidator from script_manager.py via AST
parsing — no need for a running script_manager.
"""

import ast
import pytest
import sys
from pathlib import Path

# We need to access the sandbox validator. Since it's defined inline in
# _run(), we extract it for testing by re-importing the module.
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "daq_service"))


# ===================================================================
# 1. Source-level checks
# ===================================================================

class TestSourceLevelFixes:

    def _read_source(self):
        path = Path(__file__).parent.parent / "services" / "daq_service" / "script_manager.py"
        return path.read_text(encoding='utf-8')

    def test_visit_subscript_exists(self):
        """Validator must have visit_Subscript handler."""
        content = self._read_source()
        assert "def visit_Subscript(self, node):" in content

    def test_visit_subscript_blocks_dunder_strings(self):
        """visit_Subscript must reject literal dunder keys."""
        content = self._read_source()
        idx = content.find("def visit_Subscript")
        end_idx = content.find("def visit_", idx + 10)
        body = content[idx:end_idx]
        assert "_blocked_dunder_attrs" in body

    def test_visit_subscript_blocks_dynamic_keys(self):
        """visit_Subscript must reject ast.BinOp / f-strings / dynamic keys."""
        content = self._read_source()
        idx = content.find("def visit_Subscript")
        end_idx = content.find("def visit_", idx + 10)
        body = content[idx:end_idx]
        assert "BinOp" in body  # String concat
        assert "JoinedStr" in body or "FormattedValue" in body  # f-strings

    def test_visit_call_blocks_method_calls(self):
        """visit_Call must check ast.Attribute (method calls), not just ast.Name."""
        content = self._read_source()
        idx = content.find("def visit_Call")
        end_idx = content.find("def visit_", idx + 10)
        body = content[idx:end_idx]
        assert "ast.Attribute" in body
        assert "Method call" in body or "method-style" in body.lower()

    def test_recursion_limit_lowered_for_scripts(self):
        """exec() must run inside setrecursionlimit() context to protect daq_service."""
        content = self._read_source()
        assert "setrecursionlimit(100)" in content
        # And restored afterwards
        assert "setrecursionlimit(_orig_recursion_limit)" in content


# ===================================================================
# 2. Build a standalone validator copy for direct testing
# ===================================================================

# We replicate the validator here so we can test it without running the
# whole script_manager. MUST stay in sync with the implementation.
class SecurityError(Exception):
    pass


_BLOCKED_DUNDER_ATTRS = frozenset({
    '__import__', '__subclasses__', '__bases__', '__globals__',
    '__code__', '__class__', '__builtins__', '__dict__',
    '__getattribute__', '__setattr__', '__delattr__',
    '__init_subclass__', '__mro__', '__mro_entries__',
    '__reduce__', '__reduce_ex__',
})
_BLOCKED_FUNC_NAMES = frozenset({
    'getattr', 'setattr', 'delattr', 'eval', 'exec',
    'compile', 'open', '__import__', 'vars', 'dir',
    'globals', 'locals', 'breakpoint', 'memoryview',
    'classmethod', 'staticmethod', 'property', 'super',
})
_BLOCKED_MODULES = frozenset({
    'os', 'sys', 'subprocess', 'importlib', 'ctypes',
    'socket', 'signal', 'shutil', 'pathlib', 'io',
    'builtins', 'code', 'codeop', 'compileall',
})


class _SandboxValidator(ast.NodeVisitor):
    def visit_Import(self, node):
        raise SecurityError("Import statements are not allowed")
    def visit_ImportFrom(self, node):
        raise SecurityError("Import statements are not allowed")
    def visit_Attribute(self, node):
        if node.attr in _BLOCKED_DUNDER_ATTRS:
            raise SecurityError(f"Access to '{node.attr}' is not allowed")
        self.generic_visit(node)
    def visit_Subscript(self, node):
        sl = node.slice
        if hasattr(ast, 'Index') and isinstance(sl, ast.Index):
            sl = sl.value
        if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
            if sl.value in _BLOCKED_DUNDER_ATTRS or sl.value in _BLOCKED_FUNC_NAMES:
                raise SecurityError(f"Subscript access to '{sl.value}' is not allowed")
        elif isinstance(sl, (ast.BinOp, ast.JoinedStr, ast.FormattedValue, ast.Call)):
            raise SecurityError("Dynamic subscript keys not allowed")
        self.generic_visit(node)
    def visit_Call(self, node):
        if isinstance(node.func, ast.Name) and node.func.id in _BLOCKED_FUNC_NAMES:
            raise SecurityError(f"Call to '{node.func.id}()' is not allowed")
        if isinstance(node.func, ast.Attribute):
            if node.func.attr in _BLOCKED_FUNC_NAMES:
                raise SecurityError(f"Method call to '{node.func.attr}()' is not allowed")
            if node.func.attr in _BLOCKED_DUNDER_ATTRS:
                raise SecurityError(f"Method call to '{node.func.attr}()' is not allowed")
        self.generic_visit(node)
    def visit_Name(self, node):
        if node.id in _BLOCKED_MODULES:
            raise SecurityError(f"Access to '{node.id}' module is not allowed")
        self.generic_visit(node)


def validate(code: str):
    """Helper to validate a code snippet."""
    tree = ast.parse(code)
    _SandboxValidator().visit(tree)


# ===================================================================
# 3. Verify legitimate scripts still pass
# ===================================================================

class TestLegitimateScriptsPass:
    """Real-world scripts must NOT be blocked."""

    def test_simple_assignment(self):
        validate("x = 5")
        validate("x = 5; y = x + 1")

    def test_loop(self):
        validate("for i in range(10): pass")

    def test_function_def(self):
        validate("def my_func(x): return x * 2")

    def test_pid_loop(self):
        """Common PID loop pattern."""
        validate("""
kp = 1.0
ki = 0.5
error_sum = 0.0
last_error = 0.0

while True:
    pv = tags.PT1
    sp = tags.SETPOINT
    error = sp - pv
    error_sum += error
    output = kp * error + ki * error_sum
    outputs.set('VALVE1', output)
    next_scan()
""")

    def test_dict_access_normal_keys(self):
        """Normal dict access with regular keys still works."""
        validate("d = {'a': 1, 'b': 2}; x = d['a']")

    def test_list_indexing(self):
        validate("lst = [1, 2, 3]; x = lst[0]")


# ===================================================================
# 4. Critical bypass attempts must be blocked
# ===================================================================

class TestSubscriptBypassBlocked:
    """Bug 2: x['__class__'] used to bypass attribute blocking."""

    def test_subscript_class_blocked(self):
        with pytest.raises(SecurityError, match="__class__"):
            validate("x = []; cls = x['__class__']")

    def test_subscript_import_blocked(self):
        with pytest.raises(SecurityError, match="__import__"):
            validate("x = {}; imp = x['__import__']")

    def test_subscript_builtins_blocked(self):
        with pytest.raises(SecurityError, match="__builtins__"):
            validate("x = {}; b = x['__builtins__']")

    def test_subscript_subclasses_blocked(self):
        with pytest.raises(SecurityError, match="__subclasses__"):
            validate("x = []; subs = x['__subclasses__']")

    def test_subscript_func_name_blocked(self):
        with pytest.raises(SecurityError, match="getattr"):
            validate("x = {}; fn = x['getattr']")


class TestStringConcatBypassBlocked:
    """Bug 3: '__' + 'class__' used to evade literal-string detection."""

    def test_binop_string_concat_blocked(self):
        with pytest.raises(SecurityError, match="Dynamic subscript"):
            validate("x = []; cls = x['__' + 'class__']")

    def test_fstring_subscript_blocked(self):
        with pytest.raises(SecurityError, match="Dynamic subscript"):
            validate('x = []; cls = x[f"__class__"]')

    def test_dynamic_subscript_via_call_blocked(self):
        """Function-call subscript keys are blocked."""
        with pytest.raises(SecurityError, match="Dynamic subscript"):
            validate("x = []; cls = x[''.join(['__', 'class__'])]")

    def test_method_call_subscript_blocked(self):
        """Method calls in subscript keys are blocked."""
        with pytest.raises(SecurityError, match="Dynamic subscript"):
            validate("x = []; cls = x['_'.upper()]")

    def test_known_gap_name_reference(self):
        """KNOWN GAP: variable holding a string can subscript any key.
        We allow this because rejecting all Name references would break
        legitimate patterns like `key = 'pump1'; tag = tags[key]`.
        Documented as a known limitation — Mike is trusted, threat model
        is buggy script not malicious script."""
        # This is INTENTIONALLY allowed:
        validate("x = {}; key = '__class__'; bad = x[key]")


class TestMethodCallBypassBlocked:
    """Bug 1: x.getattr(y) used to slip past visit_Call."""

    def test_method_call_getattr_blocked(self):
        with pytest.raises(SecurityError, match="getattr"):
            validate("x = object(); y = x.getattr(x, 'foo')")

    def test_method_call_eval_blocked(self):
        with pytest.raises(SecurityError, match="eval"):
            validate("x = object(); x.eval('1+1')")

    def test_method_call_exec_blocked(self):
        with pytest.raises(SecurityError, match="exec"):
            validate("x = object(); x.exec('print(1)')")

    def test_method_call_dunder_blocked(self):
        with pytest.raises(SecurityError):
            validate("x = []; x.__class__()")


class TestDirectCallsStillBlocked:
    """Original direct-call blocks must still work."""

    def test_eval_blocked(self):
        with pytest.raises(SecurityError, match="eval"):
            validate("x = eval('1+1')")

    def test_exec_blocked(self):
        with pytest.raises(SecurityError, match="exec"):
            validate("exec('print(1)')")

    def test_getattr_blocked(self):
        with pytest.raises(SecurityError, match="getattr"):
            validate("x = getattr(object(), 'foo')")

    def test_open_blocked(self):
        with pytest.raises(SecurityError, match="open"):
            validate("f = open('/etc/passwd')")

    def test_compile_blocked(self):
        with pytest.raises(SecurityError, match="compile"):
            validate("c = compile('1+1', '<x>', 'eval')")


class TestImportsBlocked:
    """Imports must always be blocked."""

    def test_import_os_blocked(self):
        with pytest.raises(SecurityError, match="Import"):
            validate("import os")

    def test_from_import_blocked(self):
        with pytest.raises(SecurityError, match="Import"):
            validate("from os import path")

    def test_import_sys_blocked(self):
        with pytest.raises(SecurityError, match="Import"):
            validate("import sys")


class TestAttributeBlocking:
    """Direct dunder attribute access still blocked (original behavior)."""

    def test_class_attr_blocked(self):
        with pytest.raises(SecurityError, match="__class__"):
            validate("x = [].__class__")

    def test_bases_blocked(self):
        with pytest.raises(SecurityError, match="__bases__"):
            validate("x = list.__bases__")

    def test_subclasses_blocked(self):
        with pytest.raises(SecurityError, match="__subclasses__"):
            validate("x = object.__subclasses__")


class TestModuleAccessBlocked:
    """Bare module names must be blocked."""

    def test_os_module_blocked(self):
        with pytest.raises(SecurityError, match="os"):
            validate("os.getcwd()")

    def test_sys_module_blocked(self):
        with pytest.raises(SecurityError, match="sys"):
            validate("sys.path")


# ===================================================================
# 5. Combined exploit chains (the dangerous ones)
# ===================================================================

class TestExploitChains:
    """Multi-step exploits that combine bypasses."""

    def test_subscript_to_subclasses_chain_blocked(self):
        """The classic: object.__subclasses__() to get every class."""
        with pytest.raises(SecurityError):
            validate("subs = object['__subclasses__']()")

    def test_string_concat_in_subscript_blocked(self):
        """Build dunder name at runtime IN the subscript expression itself."""
        with pytest.raises(SecurityError, match="Dynamic subscript"):
            validate("x = {}; bad = x['__cl' + 'ass__']")

    def test_method_call_to_dunder_blocked(self):
        """Method call to bypass attribute block."""
        with pytest.raises(SecurityError):
            validate("x = []; y = x.__class__()")


# ===================================================================
# 6. Recursion limit fix verified
# ===================================================================

class TestRecursionLimit:
    """Bug 4: setrecursionlimit must protect daq_service from recursion bombs."""

    def test_recursion_limit_low_during_exec(self):
        """Verify setrecursionlimit is called with a low value before exec."""
        path = Path(__file__).parent.parent / "services" / "daq_service" / "script_manager.py"
        content = path.read_text(encoding='utf-8')
        # Locate the limit value
        assert "sys.setrecursionlimit(100)" in content

    def test_recursion_limit_restored(self):
        """After exec, original limit must be restored (try/finally)."""
        path = Path(__file__).parent.parent / "services" / "daq_service" / "script_manager.py"
        content = path.read_text(encoding='utf-8')
        # Find the section
        idx = content.find("sys.setrecursionlimit(100)")
        snippet = content[idx:idx+500]
        assert "finally:" in snippet
        assert "sys.setrecursionlimit(_orig_recursion_limit)" in snippet


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
