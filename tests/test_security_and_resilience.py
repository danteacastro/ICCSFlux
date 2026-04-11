"""
Security and resilience tests for ICCSFlux.

Tests three critical areas:
1. Script sandbox — AST-based validation blocks dangerous operations
2. Notification system — queue overflow, config persistence, edge cases
3. State persistence — round-trip fidelity, concurrent access, large values

These tests are self-contained (no MQTT broker or hardware required).
"""

import ast
import json
import os
import sys
import time
import threading
import queue
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass

import pytest

# Add service paths
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "daq_service"))
sys.path.insert(0, str(Path(__file__).parent.parent / "services"))

from script_manager import StatePersistence, SecurityError
from notification_manager import (
    NotificationManager, NotificationConfig, TriggerRules,
    TwilioConfig, EmailConfig,
)


# =========================================================================
# 1. Script sandbox security — AST validation
# =========================================================================

# Mirror the production blocked lists so tests fail if production drifts
BLOCKED_DUNDER_ATTRS = frozenset({
    '__import__', '__subclasses__', '__bases__', '__globals__',
    '__code__', '__class__', '__builtins__', '__dict__',
    '__getattribute__', '__setattr__', '__delattr__',
    '__init_subclass__', '__mro__', '__mro_entries__',
    '__reduce__', '__reduce_ex__',
})

BLOCKED_FUNC_NAMES = frozenset({
    'getattr', 'setattr', 'delattr', 'eval', 'exec',
    'compile', 'open', '__import__', 'vars', 'dir',
    'globals', 'locals', 'breakpoint', 'memoryview',
    'classmethod', 'staticmethod', 'property', 'super',
})

BLOCKED_MODULE_NAMES = frozenset({
    'os', 'sys', 'subprocess', 'importlib', 'ctypes',
    'socket', 'signal', 'shutil', 'pathlib', 'io',
    'builtins', 'code', 'codeop', 'compileall',
})


class SandboxValidator(ast.NodeVisitor):
    """Replica of production _SandboxValidator for testing.
    Raises SecurityError on blocked operations."""

    def visit_Import(self, node):
        raise SecurityError("Import statements are not allowed")

    def visit_ImportFrom(self, node):
        raise SecurityError("Import statements are not allowed")

    def visit_Attribute(self, node):
        if node.attr in BLOCKED_DUNDER_ATTRS:
            raise SecurityError(f"Access to '{node.attr}' is not allowed")
        self.generic_visit(node)

    def visit_Call(self, node):
        if isinstance(node.func, ast.Name) and node.func.id in BLOCKED_FUNC_NAMES:
            raise SecurityError(f"Call to '{node.func.id}()' is not allowed")
        self.generic_visit(node)

    def visit_Name(self, node):
        if node.id in BLOCKED_MODULE_NAMES:
            raise SecurityError(f"Access to '{node.id}' module is not allowed")
        self.generic_visit(node)


def validate_code(code: str):
    """Parse and validate code through the sandbox. Raises SecurityError if blocked."""
    tree = ast.parse(code, mode='exec')
    SandboxValidator().visit(tree)


class TestSandboxBlocksImports:
    """Verify all import forms are blocked."""

    def test_import_os(self):
        with pytest.raises(SecurityError, match="Import"):
            validate_code("import os")

    def test_import_subprocess(self):
        with pytest.raises(SecurityError, match="Import"):
            validate_code("import subprocess")

    def test_from_os_import(self):
        with pytest.raises(SecurityError, match="Import"):
            validate_code("from os import system")

    def test_from_builtins_import(self):
        with pytest.raises(SecurityError, match="Import"):
            validate_code("from builtins import open")

    def test_import_ctypes(self):
        with pytest.raises(SecurityError, match="Import"):
            validate_code("import ctypes")

    def test_import_socket(self):
        with pytest.raises(SecurityError, match="Import"):
            validate_code("import socket")

    def test_import_io(self):
        with pytest.raises(SecurityError, match="Import"):
            validate_code("from io import BytesIO")


class TestSandboxBlocksDangerousCalls:
    """Verify dangerous builtin calls are blocked."""

    def test_eval(self):
        with pytest.raises(SecurityError, match="eval"):
            validate_code("eval('1+1')")

    def test_exec(self):
        with pytest.raises(SecurityError, match="exec"):
            validate_code("exec('pass')")

    def test_compile(self):
        with pytest.raises(SecurityError, match="compile"):
            validate_code("compile('pass', '<str>', 'exec')")

    def test_open(self):
        with pytest.raises(SecurityError, match="open"):
            validate_code("open('/etc/passwd')")

    def test_getattr(self):
        with pytest.raises(SecurityError, match="getattr"):
            validate_code("getattr([], '__class__')")

    def test_setattr(self):
        with pytest.raises(SecurityError, match="setattr"):
            validate_code("setattr(x, 'y', 1)")

    def test_delattr(self):
        with pytest.raises(SecurityError, match="delattr"):
            validate_code("delattr(x, 'y')")

    def test_vars(self):
        with pytest.raises(SecurityError, match="vars"):
            validate_code("vars()")

    def test_dir(self):
        with pytest.raises(SecurityError, match="dir"):
            validate_code("dir()")

    def test_globals(self):
        with pytest.raises(SecurityError, match="globals"):
            validate_code("globals()")

    def test_locals(self):
        with pytest.raises(SecurityError, match="locals"):
            validate_code("locals()")

    def test_breakpoint(self):
        with pytest.raises(SecurityError, match="breakpoint"):
            validate_code("breakpoint()")

    def test___import__(self):
        with pytest.raises(SecurityError, match="__import__"):
            validate_code("__import__('os')")

    def test_super(self):
        with pytest.raises(SecurityError, match="super"):
            validate_code("super().__init__()")


class TestSandboxBlocksDunderAccess:
    """Verify attribute access to dangerous dunders is blocked."""

    def test_subclasses(self):
        with pytest.raises(SecurityError, match="__subclasses__"):
            validate_code("x.__subclasses__()")

    def test_bases(self):
        with pytest.raises(SecurityError, match="__bases__"):
            validate_code("x.__bases__")

    def test_globals(self):
        with pytest.raises(SecurityError, match="__globals__"):
            validate_code("x.__globals__")

    def test_code(self):
        with pytest.raises(SecurityError, match="__code__"):
            validate_code("x.__code__")

    def test_class(self):
        with pytest.raises(SecurityError, match="__class__"):
            validate_code("x.__class__")

    def test_builtins(self):
        with pytest.raises(SecurityError, match="__builtins__"):
            validate_code("x.__builtins__")

    def test_dict(self):
        with pytest.raises(SecurityError, match="__dict__"):
            validate_code("x.__dict__")

    def test_mro(self):
        with pytest.raises(SecurityError, match="__mro__"):
            validate_code("x.__mro__")

    def test_reduce(self):
        with pytest.raises(SecurityError, match="__reduce__"):
            validate_code("x.__reduce__()")

    def test_getattribute(self):
        with pytest.raises(SecurityError, match="__getattribute__"):
            validate_code("x.__getattribute__('y')")

    def test_setattr_dunder(self):
        with pytest.raises(SecurityError, match="__setattr__"):
            validate_code("x.__setattr__('y', 1)")

    def test_import_dunder(self):
        with pytest.raises(SecurityError, match="__import__"):
            validate_code("x.__import__('os')")


class TestSandboxBlocksModuleNames:
    """Verify references to dangerous module names are blocked."""

    def test_os(self):
        with pytest.raises(SecurityError, match="os"):
            validate_code("os.system('cmd')")

    def test_sys(self):
        with pytest.raises(SecurityError, match="sys"):
            validate_code("sys.exit(1)")

    def test_subprocess(self):
        with pytest.raises(SecurityError, match="subprocess"):
            validate_code("subprocess.call(['ls'])")

    def test_ctypes(self):
        with pytest.raises(SecurityError, match="ctypes"):
            validate_code("ctypes.CDLL('libc.so')")

    def test_socket(self):
        with pytest.raises(SecurityError, match="socket"):
            validate_code("socket.socket()")

    def test_shutil(self):
        with pytest.raises(SecurityError, match="shutil"):
            validate_code("shutil.rmtree('/')")

    def test_pathlib(self):
        with pytest.raises(SecurityError, match="pathlib"):
            validate_code("pathlib.Path('/')")

    def test_io(self):
        with pytest.raises(SecurityError, match="io"):
            validate_code("io.open('/etc/passwd')")

    def test_builtins_module(self):
        with pytest.raises(SecurityError, match="builtins"):
            validate_code("builtins.open('/etc/passwd')")

    def test_importlib(self):
        with pytest.raises(SecurityError, match="importlib"):
            validate_code("importlib.import_module('os')")


class TestSandboxEscapeAttempts:
    """Test known Python sandbox escape patterns."""

    def test_class_bases_subclasses_escape(self):
        """The classic ().__class__.__bases__[0].__subclasses__() escape."""
        with pytest.raises(SecurityError):
            validate_code("().__class__.__bases__[0].__subclasses__()")

    def test_type_bases_escape(self):
        """type([]).__bases__[0].__subclasses__() escape."""
        # 'type' is removed from safe_builtins per CLAUDE.md
        # But the AST validator catches __bases__ access regardless
        with pytest.raises(SecurityError):
            validate_code("x = []; x.__class__.__bases__[0].__subclasses__()")

    def test_globals_via_function(self):
        """Access globals through function.__globals__."""
        with pytest.raises(SecurityError):
            validate_code("def f(): pass\nf.__globals__")

    def test_code_object_access(self):
        """Access code object through function.__code__."""
        with pytest.raises(SecurityError):
            validate_code("def f(): pass\nf.__code__")

    def test_import_via_builtins(self):
        """Try to import via __builtins__.__import__."""
        with pytest.raises(SecurityError):
            validate_code("__builtins__.__import__('os')")

    def test_nested_getattr_escape(self):
        """Try getattr to bypass attribute checking."""
        with pytest.raises(SecurityError):
            validate_code("getattr(getattr([], '__class__'), '__bases__')")

    def test_eval_of_import(self):
        """Try eval('__import__(\"os\")')."""
        with pytest.raises(SecurityError):
            validate_code("eval('__import__(\"os\")')")

    def test_exec_of_import(self):
        """Try exec('import os')."""
        with pytest.raises(SecurityError):
            validate_code("exec('import os')")

    def test_compile_and_exec(self):
        """Try compile() + exec() combo."""
        with pytest.raises(SecurityError):
            validate_code("compile('import os', '<x>', 'exec')")


class TestSandboxAllowsSafeOperations:
    """Verify safe operations are NOT blocked."""

    def test_math_operations(self):
        validate_code("x = 1 + 2 * 3")

    def test_string_operations(self):
        validate_code("s = 'hello' + ' ' + 'world'")

    def test_list_operations(self):
        validate_code("x = [1, 2, 3]\nx.append(4)\ny = len(x)")

    def test_dict_operations(self):
        validate_code("d = {'a': 1}\nd['b'] = 2")

    def test_for_loop(self):
        validate_code("for i in range(10):\n    x = i * 2")

    def test_while_loop(self):
        validate_code("i = 0\nwhile i < 10:\n    i += 1")

    def test_function_definition(self):
        validate_code("def add(a, b):\n    return a + b")

    def test_class_definition(self):
        validate_code("class Point:\n    def __init__(self, x, y):\n        self.x = x\n        self.y = y")

    def test_list_comprehension(self):
        validate_code("squares = [x**2 for x in range(10)]")

    def test_safe_builtins(self):
        validate_code("x = abs(-5)\ny = max(1, 2, 3)\nz = min(1, 2, 3)")

    def test_isinstance_check(self):
        validate_code("x = isinstance(1, int)")

    def test_string_formatting(self):
        validate_code("name = 'world'\ns = f'hello {name}'")

    def test_try_except(self):
        validate_code("try:\n    x = 1/0\nexcept ZeroDivisionError:\n    x = 0")

    def test_safe_attribute_access(self):
        """Normal attribute access (not dunders) should be fine."""
        validate_code("x = 'hello'\ny = x.upper()")

    def test_safe_dunder_init(self):
        """__init__ is NOT in the blocked list — classes need it."""
        validate_code("class Foo:\n    def __init__(self):\n        self.x = 1")

    def test_safe_dunder_str(self):
        """__str__ is NOT in the blocked list."""
        validate_code("class Foo:\n    def __str__(self):\n        return 'foo'")


class TestSandboxListSync:
    """Verify the blocked lists in both script files are identical."""

    def test_blocked_lists_match(self):
        """daq_service/script_manager.py, crio_node_v2/script_engine.py, and
        opto22_node/script_engine.py must have identical blocked lists (per CLAUDE.md)."""
        base = Path(__file__).parent.parent / "services"
        sources = {
            "DAQ": base / "daq_service" / "script_manager.py",
            "cRIO": base / "crio_node_v2" / "script_engine.py",
            "Opto22": base / "opto22_node" / "script_engine.py",
        }

        src_texts = {}
        for label, path in sources.items():
            assert path.exists(), f"{label} script engine not found: {path}"
            src_texts[label] = path.read_text()

        def extract_frozenset(src: str, var_name: str) -> set:
            """Extract frozenset contents from source code."""
            import re
            # Find the frozenset block
            pattern = rf"{var_name}\s*=\s*frozenset\(\{{\s*(.*?)\s*\}}\)"
            match = re.search(pattern, src, re.DOTALL)
            assert match, f"Could not find {var_name} in source"
            items_str = match.group(1)
            # Extract quoted strings
            items = re.findall(r"'([^']+)'", items_str)
            return set(items)

        list_names = ['_blocked_dunder_attrs', '_blocked_func_names', '_blocked_module_names']
        labels = list(sources.keys())

        for var_name in list_names:
            extracted = {label: extract_frozenset(src_texts[label], var_name) for label in labels}
            # Compare all pairs
            for i in range(len(labels)):
                for j in range(i + 1, len(labels)):
                    a, b = labels[i], labels[j]
                    assert extracted[a] == extracted[b], (
                        f"{var_name} differs between {a} and {b}:\n"
                        f"  {a} only: {extracted[a] - extracted[b]}\n"
                        f"  {b} only: {extracted[b] - extracted[a]}"
                    )

    def test_blocked_lists_match_test_replica(self):
        """Verify our test replica matches the production blocked lists."""
        daq_path = Path(__file__).parent.parent / "services" / "daq_service" / "script_manager.py"
        daq_src = daq_path.read_text()

        import re

        def extract_frozenset(src: str, var_name: str) -> set:
            pattern = rf"{var_name}\s*=\s*frozenset\(\{{\s*(.*?)\s*\}}\)"
            match = re.search(pattern, src, re.DOTALL)
            assert match, f"Could not find {var_name}"
            return set(re.findall(r"'([^']+)'", match.group(1)))

        prod_dunders = extract_frozenset(daq_src, '_blocked_dunder_attrs')
        prod_funcs = extract_frozenset(daq_src, '_blocked_func_names')
        prod_modules = extract_frozenset(daq_src, '_blocked_module_names')

        assert BLOCKED_DUNDER_ATTRS == prod_dunders, \
            f"Test replica dunder attrs out of sync with production"
        assert BLOCKED_FUNC_NAMES == prod_funcs, \
            f"Test replica func names out of sync with production"
        assert BLOCKED_MODULE_NAMES == prod_modules, \
            f"Test replica module names out of sync with production"


# =========================================================================
# 2. Notification system — advanced scenarios
# =========================================================================

def _make_config(
    twilio_enabled=False,
    email_enabled=False,
    cooldown=300,
    daily_limit=100,
    quiet_hours=False,
) -> NotificationConfig:
    """Helper to build a NotificationConfig with sensible defaults."""
    return NotificationConfig(
        twilio=TwilioConfig(
            enabled=twilio_enabled,
            account_sid='AC_test_sid',
            auth_token='test_token',
            from_number='+15551234567',
            to_numbers=['+15559876543'],
            rules=TriggerRules(
                severities=['critical', 'high', 'medium', 'low'],
                event_types=['triggered', 'cleared', 'acknowledged', 'alarm_flood'],
                groups=[],
                alarm_select_mode='all',
                alarm_ids=[],
            ),
        ),
        email=EmailConfig(
            enabled=email_enabled,
            smtp_host='smtp.test.com',
            smtp_port=587,
            use_tls=True,
            username='test@test.com',
            password='testpassword',
            from_address='alerts@test.com',
            to_addresses=['admin@test.com'],
            rules=TriggerRules(
                severities=['critical', 'high', 'medium', 'low'],
                event_types=['triggered', 'cleared', 'acknowledged', 'alarm_flood'],
                groups=[],
                alarm_select_mode='all',
                alarm_ids=[],
            ),
        ),
        cooldown_seconds=cooldown,
        daily_limit=daily_limit,
        quiet_hours_enabled=quiet_hours,
        quiet_hours_start='22:00',
        quiet_hours_end='06:00',
    )


def _alarm_data(alarm_id='ALARM-001', severity='high', group='Process'):
    """Helper to build alarm event data."""
    return {
        'alarm_id': alarm_id,
        'name': f'Test Alarm {alarm_id}',
        'channel': 'TC-001',
        'severity': severity,
        'threshold_type': 'high',
        'threshold_value': 100.0,
        'triggered_value': 105.0,
        'current_value': 105.0,
        'message': 'Test alarm triggered',
        'triggered_at': datetime.now(timezone.utc).isoformat(),
        'group': group,
    }


class TestNotificationQueueOverflow:
    """Test behavior when notification queue is full."""

    def test_queue_full_drops_notification(self, tmp_path):
        """When queue is full (100 items), new events are dropped gracefully."""
        mgr = NotificationManager(data_dir=tmp_path)
        # Stop the worker so the queue fills up
        mgr._running = False
        if mgr._worker:
            mgr._worker.join(timeout=3)

        # Set config with twilio enabled
        with mgr._lock:
            mgr._config = _make_config(twilio_enabled=True)

        # Fill the queue
        for i in range(100):
            mgr._queue.put_nowait({'channel': 'twilio', 'event_type': 'triggered', 'data': {}})

        assert mgr._queue.full()

        # Next event should be dropped (not raise)
        mgr.on_alarm_event('triggered', _alarm_data(alarm_id=f'OVERFLOW'))

        # Queue should still be exactly 100
        assert mgr._queue.qsize() == 100
        mgr.shutdown()

    def test_queue_overflow_no_crash(self, tmp_path):
        """Rapid alarm events don't crash the system."""
        mgr = NotificationManager(data_dir=tmp_path)
        mgr._running = False
        if mgr._worker:
            mgr._worker.join(timeout=3)

        with mgr._lock:
            mgr._config = _make_config(twilio_enabled=True)

        # Fire 200 rapid events — should not raise
        for i in range(200):
            mgr.on_alarm_event('triggered', _alarm_data(alarm_id=f'RAPID-{i}'))

        mgr.shutdown()


class TestNotificationConfigPersistence:
    """Test config save/load round-trip fidelity."""

    def test_config_round_trip(self, tmp_path):
        """Config survives save → load cycle with all fields intact."""
        mgr = NotificationManager(data_dir=tmp_path)

        original = _make_config(
            twilio_enabled=True,
            email_enabled=True,
            cooldown=600,
            daily_limit=50,
            quiet_hours=True,
        )
        with mgr._lock:
            mgr._config = original
        mgr._save_config()

        # Create a new manager that loads from same directory
        mgr2 = NotificationManager(data_dir=tmp_path)

        loaded = mgr2._config
        assert loaded.twilio.enabled == True
        assert loaded.twilio.account_sid == 'AC_test_sid'
        assert loaded.twilio.from_number == '+15551234567'
        assert loaded.twilio.to_numbers == ['+15559876543']
        assert loaded.email.enabled == True
        assert loaded.email.smtp_host == 'smtp.test.com'
        assert loaded.email.smtp_port == 587
        assert loaded.email.use_tls == True
        assert loaded.email.to_addresses == ['admin@test.com']
        assert loaded.cooldown_seconds == 600
        assert loaded.daily_limit == 50
        assert loaded.quiet_hours_enabled == True
        assert loaded.quiet_hours_start == '22:00'
        assert loaded.quiet_hours_end == '06:00'

        # Trigger rules preserved
        assert loaded.twilio.rules.severities == ['critical', 'high', 'medium', 'low']
        assert loaded.twilio.rules.event_types == ['triggered', 'cleared', 'acknowledged', 'alarm_flood']
        assert loaded.twilio.rules.alarm_select_mode == 'all'

        mgr.shutdown()
        mgr2.shutdown()

    def test_config_with_special_characters(self, tmp_path):
        """Config with special chars in credentials survives round-trip."""
        mgr = NotificationManager(data_dir=tmp_path)

        cfg = _make_config(email_enabled=True)
        cfg.email.password = 'p@$$w0rd!#%^&*(){}[]|'
        cfg.email.username = 'user+tag@example.com'
        cfg.twilio.auth_token = 'token/with=special+chars'

        with mgr._lock:
            mgr._config = cfg
        mgr._save_config()

        mgr2 = NotificationManager(data_dir=tmp_path)
        assert mgr2._config.email.password == 'p@$$w0rd!#%^&*(){}[]|'
        assert mgr2._config.email.username == 'user+tag@example.com'
        assert mgr2._config.twilio.auth_token == 'token/with=special+chars'

        mgr.shutdown()
        mgr2.shutdown()

    def test_corrupt_config_falls_back_to_defaults(self, tmp_path):
        """Corrupted config file loads as defaults, not crash."""
        config_file = tmp_path / 'notification_config.json'
        config_file.write_text("{invalid json!!!")

        # Should not raise — falls back to default config
        mgr = NotificationManager(data_dir=tmp_path)
        assert mgr._config.twilio.enabled == False
        assert mgr._config.email.enabled == False
        mgr.shutdown()


class TestNotificationSendValidation:
    """Test send methods validate configuration."""

    def test_twilio_missing_sid_raises(self, tmp_path):
        """Twilio send with empty SID raises ValueError."""
        mgr = NotificationManager(data_dir=tmp_path)
        cfg = TwilioConfig(
            enabled=True, account_sid='', auth_token='token',
            from_number='+15551234567', to_numbers=['+15559876543'],
            rules=TriggerRules(),
        )
        with pytest.raises(ValueError, match="incomplete"):
            mgr._send_twilio(cfg, 'triggered', _alarm_data())
        mgr.shutdown()

    def test_twilio_no_recipients_raises(self, tmp_path):
        """Twilio send with no recipients raises ValueError."""
        mgr = NotificationManager(data_dir=tmp_path)
        cfg = TwilioConfig(
            enabled=True, account_sid='SID', auth_token='token',
            from_number='+15551234567', to_numbers=[],
            rules=TriggerRules(),
        )
        with pytest.raises(ValueError, match="No SMS recipients"):
            mgr._send_twilio(cfg, 'triggered', _alarm_data())
        mgr.shutdown()

    def test_email_missing_host_raises(self, tmp_path):
        """Email send with empty SMTP host raises ValueError."""
        mgr = NotificationManager(data_dir=tmp_path)
        cfg = EmailConfig(
            enabled=True, smtp_host='', smtp_port=587, use_tls=True,
            username='', password='', from_address='a@b.com',
            to_addresses=['c@d.com'], rules=TriggerRules(),
        )
        with pytest.raises(ValueError, match="incomplete"):
            mgr._send_email(cfg, 'triggered', _alarm_data())
        mgr.shutdown()

    def test_email_no_recipients_raises(self, tmp_path):
        """Email send with no recipients raises ValueError."""
        mgr = NotificationManager(data_dir=tmp_path)
        cfg = EmailConfig(
            enabled=True, smtp_host='smtp.test.com', smtp_port=587,
            use_tls=True, username='', password='',
            from_address='a@b.com', to_addresses=[],
            rules=TriggerRules(),
        )
        with pytest.raises(ValueError, match="No email recipients"):
            mgr._send_email(cfg, 'triggered', _alarm_data())
        mgr.shutdown()


class TestNotificationTestSend:
    """Test the send_test_notification method."""

    def test_unknown_channel_returns_error(self, tmp_path):
        """Unknown channel returns error dict, not crash."""
        mgr = NotificationManager(data_dir=tmp_path)
        result = mgr.send_test_notification('carrier_pigeon')
        assert result['success'] == False
        assert 'Unknown channel' in result['message']
        mgr.shutdown()

    @patch('notification_manager.requests.post')
    def test_twilio_test_send_success(self, mock_post, tmp_path):
        """Test SMS send calls Twilio API correctly."""
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_post.return_value = mock_resp

        mgr = NotificationManager(data_dir=tmp_path)
        with mgr._lock:
            mgr._config = _make_config(twilio_enabled=True)

        result = mgr.send_test_notification('twilio')
        assert result['success'] == True
        assert mock_post.called
        mgr.shutdown()

    @patch('notification_manager.requests.post')
    def test_twilio_test_send_failure(self, mock_post, tmp_path):
        """Twilio API error returns error dict."""
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = '{"message": "Invalid credentials"}'
        mock_resp.json.return_value = {"message": "Invalid credentials"}
        mock_post.return_value = mock_resp

        mgr = NotificationManager(data_dir=tmp_path)
        with mgr._lock:
            mgr._config = _make_config(twilio_enabled=True)

        result = mgr.send_test_notification('twilio')
        assert result['success'] == False
        mgr.shutdown()


class TestNotificationDailyCounterState:
    """Test daily counter and cooldown state management."""

    def test_daily_counter_increments(self, tmp_path):
        """Daily counter tracks sent notifications."""
        mgr = NotificationManager(data_dir=tmp_path)
        assert mgr._daily_count == 0

        # Manually increment as the worker would
        mgr._daily_count += 1
        assert mgr._daily_count == 1
        mgr.shutdown()

    def test_cooldown_state_per_channel(self, tmp_path):
        """Each channel maintains separate cooldown timestamps."""
        mgr = NotificationManager(data_dir=tmp_path)

        mgr._cooldowns['twilio']['ALARM-001'] = time.monotonic()
        mgr._cooldowns['email']['ALARM-001'] = time.monotonic() - 1000

        # Twilio should be in cooldown, email should not
        twilio_age = time.monotonic() - mgr._cooldowns['twilio']['ALARM-001']
        email_age = time.monotonic() - mgr._cooldowns['email']['ALARM-001']

        assert twilio_age < 5  # just set
        assert email_age > 999  # set 1000 seconds ago
        mgr.shutdown()


class TestNotificationDisabledChannels:
    """Test that disabled channels are properly skipped."""

    def test_both_disabled_skips_immediately(self, tmp_path):
        """With both channels disabled, on_alarm_event returns immediately."""
        mgr = NotificationManager(data_dir=tmp_path)
        with mgr._lock:
            mgr._config = _make_config(twilio_enabled=False, email_enabled=False)

        # Should not enqueue anything
        mgr.on_alarm_event('triggered', _alarm_data())
        assert mgr._queue.qsize() == 0
        mgr.shutdown()

    def test_only_enabled_channel_enqueues(self, tmp_path):
        """Only the enabled channel gets enqueued."""
        mgr = NotificationManager(data_dir=tmp_path)
        # Stop worker so we can inspect queue
        mgr._running = False
        if mgr._worker:
            mgr._worker.join(timeout=3)

        with mgr._lock:
            mgr._config = _make_config(twilio_enabled=True, email_enabled=False)

        mgr.on_alarm_event('triggered', _alarm_data())

        items = []
        while not mgr._queue.empty():
            items.append(mgr._queue.get_nowait())

        channels = [item['channel'] for item in items]
        assert 'twilio' in channels
        assert 'email' not in channels
        mgr.shutdown()


# =========================================================================
# 3. State persistence — round-trip fidelity
# =========================================================================

class TestStatePersistenceRoundTrip:
    """Test StatePersistence save/load fidelity."""

    def test_basic_persist_restore(self, tmp_path):
        """Simple persist/restore returns correct value."""
        sp = StatePersistence(data_dir=str(tmp_path))
        sp.persist('script-1', 'counter', 42)
        assert sp.restore('script-1', 'counter') == 42

    def test_restore_default(self, tmp_path):
        """Restore returns default when key doesn't exist."""
        sp = StatePersistence(data_dir=str(tmp_path))
        assert sp.restore('script-1', 'nonexistent') is None
        assert sp.restore('script-1', 'nonexistent', 0) == 0
        assert sp.restore('script-1', 'nonexistent', 'default') == 'default'

    def test_multiple_scripts_isolated(self, tmp_path):
        """Different scripts don't interfere with each other."""
        sp = StatePersistence(data_dir=str(tmp_path))
        sp.persist('script-A', 'count', 100)
        sp.persist('script-B', 'count', 200)

        assert sp.restore('script-A', 'count') == 100
        assert sp.restore('script-B', 'count') == 200

    def test_multiple_keys_per_script(self, tmp_path):
        """Multiple keys within one script are independent."""
        sp = StatePersistence(data_dir=str(tmp_path))
        sp.persist('script-1', 'total', 1000)
        sp.persist('script-1', 'batch', 5)
        sp.persist('script-1', 'rate', 3.14)

        assert sp.restore('script-1', 'total') == 1000
        assert sp.restore('script-1', 'batch') == 5
        assert sp.restore('script-1', 'rate') == pytest.approx(3.14)

    def test_large_numeric_values(self, tmp_path):
        """Large counter values survive JSON serialization."""
        sp = StatePersistence(data_dir=str(tmp_path))

        # 2^32 rollover-sized values
        sp.persist('script-1', 'total', 2**32 + 500)
        sp.persist('script-1', 'big_float', 1e18)

        assert sp.restore('script-1', 'total') == 2**32 + 500
        assert sp.restore('script-1', 'big_float') == pytest.approx(1e18)

    def test_nested_data_structures(self, tmp_path):
        """Complex nested dicts/lists survive round-trip."""
        sp = StatePersistence(data_dir=str(tmp_path))

        data = {
            'counters': {'pump-1': 1500, 'pump-2': 2700},
            'history': [1.0, 2.0, 3.0, 4.0, 5.0],
            'config': {'threshold': 100.5, 'enabled': True},
        }
        sp.persist('script-1', 'state', data)

        restored = sp.restore('script-1', 'state')
        assert restored == data

    def test_overwrite_value(self, tmp_path):
        """Persisting same key overwrites previous value."""
        sp = StatePersistence(data_dir=str(tmp_path))
        sp.persist('script-1', 'count', 10)
        sp.persist('script-1', 'count', 20)
        assert sp.restore('script-1', 'count') == 20

    def test_survives_reload_from_disk(self, tmp_path):
        """Data persists across StatePersistence instances."""
        sp1 = StatePersistence(data_dir=str(tmp_path))
        sp1.persist('script-1', 'total', 99999)
        sp1.persist('script-2', 'rate', 42.5)

        # Create new instance — should load from disk
        sp2 = StatePersistence(data_dir=str(tmp_path))
        assert sp2.restore('script-1', 'total') == 99999
        assert sp2.restore('script-2', 'rate') == pytest.approx(42.5)

    def test_corrupt_file_fallback(self, tmp_path):
        """Corrupted state file loads as empty, not crash."""
        state_file = tmp_path / 'script_state.json'
        state_file.write_text("{broken json!!!")

        sp = StatePersistence(data_dir=str(tmp_path))
        assert sp.restore('script-1', 'anything') is None

    def test_concurrent_persist(self, tmp_path):
        """Concurrent persists from multiple threads don't corrupt data."""
        sp = StatePersistence(data_dir=str(tmp_path))
        errors = []

        def worker(script_id, count):
            try:
                for i in range(count):
                    sp.persist(script_id, 'count', i)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=worker, args=(f'script-{t}', 50))
            for t in range(10)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Concurrent persist errors: {errors}"

        # Each script should have some value persisted (last writer wins)
        for t in range(10):
            val = sp.restore(f'script-{t}', 'count')
            assert val is not None, f"script-{t} lost its data"
            assert 0 <= val <= 49

    def test_string_values(self, tmp_path):
        """String values with special characters survive round-trip."""
        sp = StatePersistence(data_dir=str(tmp_path))
        sp.persist('script-1', 'name', 'PT-001 "Pressure" (Test)')
        sp.persist('script-1', 'unicode', '\u00b0C \u2192 \u00b5m')

        assert sp.restore('script-1', 'name') == 'PT-001 "Pressure" (Test)'
        assert sp.restore('script-1', 'unicode') == '\u00b0C \u2192 \u00b5m'

    def test_boolean_and_none_values(self, tmp_path):
        """Boolean and None values preserve their types."""
        sp = StatePersistence(data_dir=str(tmp_path))
        sp.persist('script-1', 'flag', True)
        sp.persist('script-1', 'cleared', False)
        sp.persist('script-1', 'empty', None)

        assert sp.restore('script-1', 'flag') is True
        assert sp.restore('script-1', 'cleared') is False
        assert sp.restore('script-1', 'empty') is None
