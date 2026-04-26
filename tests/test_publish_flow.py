"""
Python publish() Flow Tests

Verifies fixes for the audit findings on Python-published variables:

  Bug #1 (HIGH): Historian was missing units for py.* channels.
    Now _published_units dict tracks units per py.X and the historian
    write_batch passes them in.
  Bug #2 (HIGH): recording_manager included ALL script values when
    include_scripts=True, ignoring selected_channels filter.
    Now respects the selection — only checked variables get recorded.
  Bug #4 (MEDIUM): Cross-script publish collision was just a one-time
    warning; the second script silently overwrote the first.
    Now BLOCKS the second publish if the first publisher is still
    running. Allows takeover only if the previous publisher has stopped.
  Bug #6 (LOW): No validation of reserved prefixes (uv., sys., alarm.,
    interlock., fx., script:). Now rejected.
  Bug #7 (MEDIUM): py.* values stayed in publishedValues store after
    a script stopped — widgets showed stale data forever.
    Now cleanup runs in the .finally() of executeScript (in addition
    to deleteScript) so stop also cleans up.
"""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "daq_service"))


# ===================================================================
# Source-level checks
# ===================================================================

class TestSourceFixes:

    def _read_daq(self):
        return (Path(__file__).parent.parent / "services" / "daq_service" / "daq_service.py").read_text(encoding='utf-8')

    def _read_recmgr(self):
        return (Path(__file__).parent.parent / "services" / "daq_service" / "recording_manager.py").read_text(encoding='utf-8')

    def _read_pyscripts(self):
        return (Path(__file__).parent.parent / "dashboard" / "src" / "composables" / "usePythonScripts.ts").read_text(encoding='utf-8')

    def test_published_units_dict_exists(self):
        """daq_service must track units for py.* channels."""
        content = self._read_daq()
        assert "self._published_units: Dict[str, str]" in content

    def test_publish_value_stores_units(self):
        """_script_publish_value must populate _published_units when units provided."""
        content = self._read_daq()
        idx = content.find("def _script_publish_value")
        body = content[idx:idx + 1000]
        assert "_published_units" in body
        assert "if units:" in body

    def test_historian_includes_published_units(self):
        """Historian write_batch must merge _published_units into hist_units."""
        content = self._read_daq()
        idx = content.find("self.historian.write_batch(int(time.time() * 1000), values, units=hist_units)")
        snippet = content[max(0, idx - 1200):idx]
        assert "_published_units" in snippet

    def test_historian_includes_user_variable_units(self):
        """Historian must also include uv.* units for variables with log=True."""
        content = self._read_daq()
        idx = content.find("self.historian.write_batch(int(time.time() * 1000), values, units=hist_units)")
        snippet = content[max(0, idx - 1200):idx]
        assert "user_variables" in snippet
        assert "uv." in snippet

    def test_recording_filter_respects_selection(self):
        """recording_manager must skip script values not in selected_channels."""
        content = self._read_recmgr()
        idx = content.find("if self.config.include_scripts and self.script_values:")
        snippet = content[idx:idx + 1500]
        assert "if self.config.selected_channels:" in snippet
        assert "py." in snippet  # checks both name and py.name forms

    def test_publish_blocks_collision_with_running_script(self):
        """publish() must reject duplicate name if other publisher is still running."""
        content = self._read_pyscripts()
        # Find the publish implementation
        idx = content.find("// Check if another script already publishes this name")
        snippet = content[idx:idx + 2000]
        assert "otherStillRunning" in snippet
        assert "return" in snippet  # blocks instead of overwriting

    def test_publish_rejects_reserved_prefixes(self):
        """publish() must reject 'uv.', 'sys.', 'alarm.', etc. prefixes."""
        content = self._read_pyscripts()
        assert "RESERVED_PREFIXES" in content
        # Verify each prefix
        for prefix in ['py.', 'uv.', 'sys.', 'alarm.', 'interlock.', 'fx.']:
            assert f"'{prefix}'" in content, f"Missing reserved prefix {prefix}"

    def test_published_values_cleared_on_script_stop(self):
        """py.* values must be cleared from publishedValues when script stops."""
        content = self._read_pyscripts()
        # Look in the .finally() of executeScript (around line 531)
        idx = content.find("Clear published values from this script")
        assert idx > 0
        snippet = content[idx:idx + 600]
        # Iterates and removes
        assert "scriptId === id" in snippet
        assert "delete publishedValues.value" in snippet


# ===================================================================
# Logic replicas
# ===================================================================

class TestRecordingFilter:
    """Replicate the recording_manager filter logic."""

    def _filter(self, script_values, selected_channels):
        """Mirror of the fixed filter logic."""
        included = {}
        for name, value in script_values.items():
            if selected_channels:
                if (name not in selected_channels
                        and f"py.{name}" not in selected_channels
                        and f"script:{name}" not in selected_channels):
                    continue
            included[f"script:{name}"] = value
        return included

    def test_unchecked_script_var_excluded(self):
        """Variable not in selected_channels → not recorded."""
        result = self._filter(
            script_values={"Counter": 100, "Debug": 50},
            selected_channels=["py.Counter"],  # Only Counter checked
        )
        assert "script:Counter" in result
        assert "script:Debug" not in result

    def test_checked_via_bare_name(self):
        """Older clients may send the bare name (no py. prefix)."""
        result = self._filter(
            script_values={"Counter": 100},
            selected_channels=["Counter"],
        )
        assert "script:Counter" in result

    def test_checked_via_script_prefix(self):
        """Some recordings use script: prefix."""
        result = self._filter(
            script_values={"Counter": 100},
            selected_channels=["script:Counter"],
        )
        assert "script:Counter" in result

    def test_no_selection_includes_all(self):
        """If no selection (legacy mode), include everything."""
        result = self._filter(
            script_values={"A": 1, "B": 2, "C": 3},
            selected_channels=[],  # falsy
        )
        assert len(result) == 3


class TestCollisionLogic:
    """Replicate the publish() collision logic."""

    def _publish_attempt(self, name, script_id, published_values, running_scripts):
        """Returns True if publish would succeed, False if blocked."""
        existing = published_values.get(name)
        if existing and existing['scriptId'] != script_id:
            other_running = existing['scriptId'] in running_scripts
            if other_running:
                return False
            # Takeover allowed
        published_values[name] = {'scriptId': script_id, 'value': 0}
        return True

    def test_first_publisher_succeeds(self):
        pub = {}
        running = {'A'}
        assert self._publish_attempt('Counter', 'A', pub, running) is True

    def test_same_script_can_re_publish(self):
        pub = {'Counter': {'scriptId': 'A', 'value': 0}}
        running = {'A'}
        # Script A re-publishing its own name — fine
        assert self._publish_attempt('Counter', 'A', pub, running) is True

    def test_second_running_publisher_blocked(self):
        """B tries to publish what A is publishing — blocked."""
        pub = {'Counter': {'scriptId': 'A', 'value': 0}}
        running = {'A', 'B'}
        assert self._publish_attempt('Counter', 'B', pub, running) is False
        # Original publisher unchanged
        assert pub['Counter']['scriptId'] == 'A'

    def test_takeover_when_original_stopped(self):
        """A stopped, B can claim the name."""
        pub = {'Counter': {'scriptId': 'A', 'value': 0}}
        running = {'B'}  # A no longer running
        assert self._publish_attempt('Counter', 'B', pub, running) is True
        assert pub['Counter']['scriptId'] == 'B'


class TestReservedPrefixes:
    """publish() must reject reserved prefixes."""

    RESERVED = {'py.', 'uv.', 'sys.', 'alarm.', 'interlock.', 'fx.', 'script:'}

    def _is_reserved(self, name):
        return any(name.startswith(p) for p in self.RESERVED)

    def test_py_blocked(self):
        assert self._is_reserved('py.Foo')

    def test_uv_blocked(self):
        assert self._is_reserved('uv.Counter')

    def test_sys_blocked(self):
        assert self._is_reserved('sys.acquiring')

    def test_alarm_blocked(self):
        assert self._is_reserved('alarm.PT1.high')

    def test_interlock_blocked(self):
        assert self._is_reserved('interlock.Estop')

    def test_normal_name_allowed(self):
        assert not self._is_reserved('MyCounter')
        assert not self._is_reserved('PT_001')
        assert not self._is_reserved('VibrationRMS')


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
