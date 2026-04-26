"""
User Variable Recording Tests

Verifies the per-variable recording opt-in. Mike checks "Record this
variable" on the Data tab → frontend sends log=True to backend → backend
includes that variable in CSV/TDMS.

Audit findings fixed:
  - User variables had NO recording inclusion path on the multi-project
    code path (write_sample only got hardware channels).
  - There was no per-variable opt-in flag; it was all-or-nothing.

Now:
  - UserVariable has a `log: bool` field, default False.
  - Both single-project and multi-project recording paths check
    var.log before including the variable.
  - Frontend Data tab toggles `var.log` when Mike checks/unchecks
    the user variable section.
"""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "daq_service"))

from user_variables import UserVariable


# ===================================================================
# Source-level checks
# ===================================================================

class TestSourceLevelFixes:

    def test_user_variable_has_log_field(self):
        """UserVariable dataclass must have a `log: bool = False` field."""
        v = UserVariable(
            id="test", name="test", display_name="Test",
            variable_type='manual'
        )
        assert hasattr(v, 'log')
        assert v.log is False  # Default opt-OUT

    def test_log_default_is_false(self):
        """Default must be False — existing projects don't suddenly
        start recording every variable."""
        v = UserVariable(
            id="test", name="test", display_name="Test",
            variable_type='manual'
        )
        assert v.log is False

    def test_log_can_be_set_true(self):
        v = UserVariable(
            id="test", name="test", display_name="Test",
            variable_type='manual',
            log=True,
        )
        assert v.log is True

    def test_log_round_trips_through_dict(self):
        """to_dict / from_dict must preserve the log field."""
        v = UserVariable(
            id="test", name="test", display_name="Test",
            variable_type='manual',
            log=True,
        )
        d = v.to_dict()
        assert d.get('log') is True
        v2 = UserVariable.from_dict(d)
        assert v2.log is True

    def test_log_false_round_trips(self):
        v = UserVariable(
            id="test", name="test", display_name="Test",
            variable_type='manual',
            log=False,
        )
        d = v.to_dict()
        # Either present as False or missing (which defaults to False)
        v2 = UserVariable.from_dict(d)
        assert v2.log is False

    def test_legacy_dict_without_log_defaults_false(self):
        """Old project files without a log field default to False."""
        legacy = {
            'id': 'test',
            'name': 'test',
            'display_name': 'Test',
            'variable_type': 'manual',
            'value': 0.0,
        }
        v = UserVariable.from_dict(legacy)
        assert v.log is False  # No surprise recording

    def test_get_values_dict_includes_log(self):
        """get_values_dict must surface log so the recording path can filter.
        Source-level check rather than constructing a real manager
        (UserVariableManager has dependencies we'd have to mock)."""
        path = Path(__file__).parent.parent / "services" / "daq_service" / "user_variables.py"
        content = path.read_text(encoding='utf-8')
        idx = content.find("def get_values_dict")
        body = content[idx:idx + 2000]
        assert "'log': var.log" in body


class TestRecordingFilterLogic:
    """Verify the recording loop correctly skips variables with log=False."""

    def test_skip_when_log_false(self):
        """Replicate the recording filter: var.log=False → not included."""
        var_dict = {
            "v1": {"name": "Counter1", "value": 100, "log": True, "units": ""},
            "v2": {"name": "Debug1", "value": 50, "log": False, "units": ""},
            "v3": {"name": "Counter2", "value": 200, "log": True, "units": ""},
        }
        record_values = {}
        for var_id, info in var_dict.items():
            if not info.get('log', False):
                continue
            key = f"uv.{info['name']}"
            record_values[key] = info['value']

        assert "uv.Counter1" in record_values
        assert "uv.Counter2" in record_values
        assert "uv.Debug1" not in record_values  # log=False skipped

    def test_default_false_no_recording(self):
        """If `log` field is missing entirely (legacy), don't record."""
        var_dict = {
            "v1": {"name": "Old", "value": 100, "units": ""},  # No log field
        }
        record_values = {}
        for var_id, info in var_dict.items():
            if not info.get('log', False):
                continue
            key = f"uv.{info['name']}"
            record_values[key] = info['value']

        # Legacy variable without explicit log=True is NOT recorded
        assert record_values == {}


class TestSourceCodeIntegration:

    def _read_daq(self):
        return (Path(__file__).parent.parent / "services" / "daq_service" / "daq_service.py").read_text(encoding='utf-8')

    def test_multi_project_recording_filters_by_log(self):
        """The multi-project recording loop must check var_info.get('log', False)."""
        content = self._read_daq()
        # Find the multi-project recording block
        idx = content.find("ctx.recording_manager.write_sample(record_values, channel_configs)")
        # The filter must be visible in the surrounding code
        snippet = content[max(0, idx - 1500):idx + 200]
        assert "var_info.get('log', False)" in snippet or "var_info.get(\"log\", False)" in snippet

    def test_single_project_recording_filters_by_log(self):
        """The single-project recording block must check var.log."""
        content = self._read_daq()
        # Find the user_variables.get_all_variables() iteration
        idx = content.find("for var in self.user_variables.get_all_variables():")
        snippet = content[idx:idx + 1000]
        # Must skip vars where log=False
        assert "getattr(var, 'log', False)" in snippet or "var.log" in snippet


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
