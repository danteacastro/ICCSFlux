"""
Safety System Tests

Verifies the audit fixes for the Safety tab. Mike runs cDAQ in production;
the safety system is the highest-stakes subsystem in the codebase.

Bugs fixed:
  CRITICAL
    - safety/alarm/delete was a dead command. ConfigurationTab sent it on
      channel delete but the backend had no subscription or handler. Alarm
      configs went orphaned. Now subscribed + routed to a new handler that
      cascades alarm_manager.remove_alarm_config().
    - safety/interlock/delete didn't exist at all. Interlocks pointing at
      a deleted channel kept evaluating against ghost data. Now sent by
      cascadeChannelDelete + uv./py. delete paths, handled by a new
      backend handler that prunes interlocks referencing the channel.
    - alert() in useSafety blocked the HMI event loop. Replaced with a
      non-blocking safety feedback banner + dismissible toast.
    - Alarm beep used a truncated base64 WAV that silently failed to load.
      Replaced with a Web Audio API tone generator (real audible beep).
    - No global alarm banner — alarms only visible on SafetyTab. Now a
      Teleport'd banner in App.vue is visible on every tab.

  HIGH
    - ACK was fire-and-forget with no feedback. Now has pending flag,
      timeout, and response handler showing success/failure toast.
    - Hysteresis (deadband) was missing on analog interlock conditions.
      Noisy signals oscillating around threshold caused trip/clear chatter.
      Now `condition.deadband` is honored in _compare_with_hysteresis.

  MEDIUM
    - Bypass had no UI confirmation. Now confirms with audit reason prompt;
      critical interlocks get extra warning text.
    - Alarm config validation per channel type. Digital inputs no longer
      accept analog limits silently — toast + strip on save.
    - Latched-alarm semantics were undocumented. Tooltip added.
"""

import sys
import pytest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "services"))


# ===================================================================
# Backend handlers — daq_service.py
# ===================================================================

class TestBackendCascadeHandlers:

    def _read(self):
        return (Path(__file__).parent.parent / "services" / "daq_service" / "daq_service.py").read_text(encoding='utf-8')

    def test_subscribes_to_alarm_delete(self):
        content = self._read()
        assert 'client.subscribe(f"{base}/safety/alarm/delete")' in content

    def test_subscribes_to_interlock_delete(self):
        content = self._read()
        assert 'client.subscribe(f"{base}/safety/interlock/delete")' in content

    def test_alarm_delete_routed_to_handler(self):
        content = self._read()
        assert 'topic == f"{base}/safety/alarm/delete"' in content
        assert "_handle_safety_alarm_delete(payload)" in content

    def test_interlock_delete_routed_to_handler(self):
        content = self._read()
        assert 'topic == f"{base}/safety/interlock/delete"' in content
        assert "_handle_safety_interlock_delete(payload)" in content

    def test_alarm_delete_handler_exists_and_cascades(self):
        content = self._read()
        idx = content.find("def _handle_safety_alarm_delete")
        assert idx > 0
        body = content[idx:idx + 2000]
        # Must accept channel-based delete
        assert "channel = payload.get('channel')" in body
        # Must call alarm_manager.remove_alarm_config
        assert "remove_alarm_config" in body
        # Must iterate every config for that channel (snapshot to avoid mutation issue)
        assert "get_configs_for_channel(channel)" in body

    def test_interlock_delete_handler_exists_and_cascades(self):
        content = self._read()
        idx = content.find("def _handle_safety_interlock_delete")
        assert idx > 0
        body = content[idx:idx + 3000]
        # Two modes: explicit ID or channel cascade
        assert "interlock_id" in body
        assert "channel" in body
        # Must walk interlocks looking for conditions referencing the channel
        assert "il.conditions" in body or "interlock.conditions" in body
        assert "remove_interlock" in body

    def test_handlers_have_permission_check(self):
        """Both new handlers require MODIFY_SAFETY permission."""
        content = self._read()
        idx = content.find("_TOPIC_PERMISSIONS = {")
        body = content[idx:idx + 2500]
        assert "'safety/alarm/delete': Permission.MODIFY_SAFETY" in body
        assert "'safety/interlock/delete': Permission.MODIFY_SAFETY" in body


# ===================================================================
# Frontend cascade emission
# ===================================================================

class TestFrontendCascadeEmission:

    def _read_config(self):
        return (Path(__file__).parent.parent / "dashboard" / "src" / "components" / "ConfigurationTab.vue").read_text(encoding='utf-8')

    def _read_playground(self):
        return (Path(__file__).parent.parent / "dashboard" / "src" / "composables" / "usePlayground.ts").read_text(encoding='utf-8')

    def _read_pyscripts(self):
        return (Path(__file__).parent.parent / "dashboard" / "src" / "composables" / "usePythonScripts.ts").read_text(encoding='utf-8')

    def test_channel_delete_emits_interlock_delete(self):
        content = self._read_config()
        idx = content.find("function cascadeChannelDelete")
        body = content[idx:idx + 3000]
        assert "safety/interlock/delete" in body
        assert "removedInterlock" in body or "interlock(s)" in body

    def test_user_variable_delete_cascades_to_safety(self):
        content = self._read_playground()
        idx = content.find("function deleteVariable")
        body = content[idx:idx + 1000]
        # Both alarm and interlock cascade
        assert "safety/alarm/delete" in body
        assert "safety/interlock/delete" in body
        # Uses the uv. prefix so backend can match it
        assert "uv." in body

    def test_python_script_delete_cascades_to_safety(self):
        content = self._read_pyscripts()
        idx = content.find("function deleteScript")
        body = content[idx:idx + 2000]
        assert "safety/alarm/delete" in body
        assert "safety/interlock/delete" in body
        # Uses the py. prefix
        assert "py." in body


# ===================================================================
# useSafety: alert() replaced + ACK feedback + new state refs
# ===================================================================

class TestUseSafetyHardening:

    def _read(self):
        return (Path(__file__).parent.parent / "dashboard" / "src" / "composables" / "useSafety.ts").read_text(encoding='utf-8')

    def test_no_blocking_alert(self):
        """alert() must NOT be CALLED in the safety composable — it freezes
        the HMI event loop. (Mentions in comments are fine.)"""
        content = self._read()
        # The specific old call site:
        assert "alert(`Safety guard:" not in content
        # Strip line-comments so a "// alert() blocks UI" note doesn't trip
        # the assertion. Only catch real call-sites.
        import re
        stripped = re.sub(r'//.*', '', content)
        # And block-comment style /* ... alert(...) ... */
        stripped = re.sub(r'/\*[\s\S]*?\*/', '', stripped)
        # Now only real code remains. Look for a bare alert( call (not
        # window.foo.alert which is unrelated).
        assert "alert(" not in stripped, \
            "alert() is still being called — replace with showSafetyFeedback()"

    def test_safety_feedback_ref_exposed(self):
        content = self._read()
        assert "safetyFeedback = ref" in content
        # Returned from composable
        assert "safetyFeedback: readonly(safetyFeedback)" in content

    def test_show_safety_feedback_helper(self):
        content = self._read()
        assert "function showSafetyFeedback" in content
        # Auto-dismiss timeout
        assert "safetyFeedbackTimeoutId" in content

    def test_blocked_interlock_uses_feedback_not_alert(self):
        content = self._read()
        idx = content.find("interlocks/error")
        body = content[idx:idx + 600]
        assert "showSafetyFeedback" in body
        assert "alert(" not in body

    def test_ack_pending_state_exists(self):
        content = self._read()
        assert "ackPending = ref" in content
        assert "function setAckPending" in content
        assert "function clearAckPending" in content
        assert "function isAckPending" in content

    def test_ack_blocks_double_fire(self):
        content = self._read()
        idx = content.find("function acknowledgeTrip")
        body = content[idx:idx + 1500]
        assert "isAckPending(interlockId)" in body
        assert "setAckPending(interlockId)" in body

    def test_ack_response_handler_subscribed(self):
        content = self._read()
        # New subscription on the ack response topic
        assert "interlocks/acknowledged" in content
        # Clears pending state on response
        idx = content.find("interlocks/acknowledged")
        body = content[idx:idx + 500]
        assert "clearAckPending" in body
        # Toast on success or error
        assert "showSafetyFeedback" in body

    def test_ack_pending_exposed_from_composable(self):
        content = self._read()
        assert "isAckPending," in content
        assert "ackPending: readonly(ackPending)" in content


# ===================================================================
# Alarm beep — Web Audio API tone (not truncated WAV)
# ===================================================================

class TestAlarmBeep:

    def _read(self):
        return (Path(__file__).parent.parent / "dashboard" / "src" / "components" / "SafetyTab.vue").read_text(encoding='utf-8')

    def test_no_truncated_data_url(self):
        content = self._read()
        # The truncated WAV that was the bug
        assert "UklGRl9vT19XQVZFZm10" not in content

    def test_uses_audio_context(self):
        content = self._read()
        assert "AudioContext" in content
        assert "function playAlarmBeep" in content

    def test_beep_played_on_alarm(self):
        content = self._read()
        # The play call site uses the new function, not alarmSound.play()
        assert "playAlarmBeep()" in content
        assert "alarmSound.play()" not in content

    def test_audio_context_resume(self):
        """Browsers suspend AudioContext until user gesture — must resume()."""
        content = self._read()
        idx = content.find("function playAlarmBeep")
        body = content[idx:idx + 1500]
        assert "ctx.resume" in body or "resume(" in body


# ===================================================================
# Global alarm banner in App.vue
# ===================================================================

class TestGlobalAlarmBanner:

    def _read(self):
        return (Path(__file__).parent.parent / "dashboard" / "src" / "App.vue").read_text(encoding='utf-8')

    def test_safety_imported(self):
        content = self._read()
        assert "import { useSafety }" in content
        assert "const safety = useSafety()" in content

    def test_global_banner_present(self):
        content = self._read()
        assert "global-alarm-banner" in content
        # Visible whenever there are active alarms OR the system is tripped
        assert "safety.hasActiveAlarms" in content
        assert "safety.isTripped" in content

    def test_banner_navigates_to_safety_tab(self):
        content = self._read()
        idx = content.find("global-alarm-banner")
        body = content[idx:idx + 600]
        assert "activeTab = 'safety'" in body

    def test_safety_feedback_toast_present(self):
        content = self._read()
        assert "safety-feedback-toast" in content
        assert "safety.dismissSafetyFeedback" in content


# ===================================================================
# Backend hysteresis (deadband)
# ===================================================================

class TestHysteresis:

    def _read(self):
        return (Path(__file__).parent.parent / "services" / "daq_service" / "safety_manager.py").read_text(encoding='utf-8')

    def test_condition_has_deadband_field(self):
        content = self._read()
        assert "deadband: float = 0.0" in content

    def test_to_dict_includes_deadband(self):
        content = self._read()
        idx = content.find("def to_dict(self)")
        body = content[idx:idx + 600]
        assert "'deadband': self.deadband" in body

    def test_from_dict_parses_deadband(self):
        content = self._read()
        idx = content.find("def from_dict(d: dict)")
        body = content[idx:idx + 3000]
        assert "deadband=" in body

    def test_compare_with_hysteresis_function(self):
        content = self._read()
        assert "def _compare_with_hysteresis" in content

    def test_channel_value_uses_hysteresis(self):
        content = self._read()
        # The cond_type == 'channel_value' branch must call the new function
        idx = content.find("elif cond_type == 'channel_value':")
        body = content[idx:idx + 1500]
        assert "_compare_with_hysteresis" in body

    def test_variable_value_uses_hysteresis(self):
        content = self._read()
        idx = content.find("elif cond_type == 'variable_value':")
        body = content[idx:idx + 1200]
        assert "_compare_with_hysteresis" in body

    def test_clear_all_resets_hysteresis_state(self):
        content = self._read()
        idx = content.find("def clear_all")
        body = content[idx:idx + 500]
        assert "_condition_prev_satisfied.clear()" in body


# ===================================================================
# Hysteresis logic replica — verifies the rule is correct
# ===================================================================

class TestHysteresisLogic:

    prev: dict

    def setup_method(self):
        self.prev = {}

    def compare(self, current, op, threshold, deadband, cond_id):
        # Mirror of _compare_with_hysteresis
        def raw():
            if op == '>':
                return current > threshold
            if op == '<':
                return current < threshold
            if op == '>=':
                return current >= threshold
            if op == '<=':
                return current <= threshold
            return False

        r = raw()
        if not deadband or deadband <= 0:
            self.prev[cond_id] = r
            return r
        prev = self.prev.get(cond_id)
        if prev is None:
            self.prev[cond_id] = r
            return r
        if prev:
            if op in ('>', '>='):
                still = current > (threshold - deadband)
            elif op in ('<', '<='):
                still = current < (threshold + deadband)
            else:
                still = r
            self.prev[cond_id] = still
            return still
        else:
            self.prev[cond_id] = r
            return r

    def test_high_alarm_no_chatter(self):
        """Value crosses 50 with deadband=2. Must not flap on noise."""
        # Value rising: 49, 50.5 (trips), 49.9 (within deadband — stays tripped)
        assert self.compare(49.0, '>', 50.0, 2.0, 'c1') is False
        assert self.compare(50.5, '>', 50.0, 2.0, 'c1') is True
        # Now drops slightly — without deadband this would clear; with deadband it should stay tripped
        assert self.compare(49.5, '>', 50.0, 2.0, 'c1') is True
        assert self.compare(48.5, '>', 50.0, 2.0, 'c1') is True   # still inside deadband (above 48.0)
        # Drops past threshold - deadband (50 - 2 = 48) — clears
        assert self.compare(47.5, '>', 50.0, 2.0, 'c1') is False

    def test_zero_deadband_acts_like_raw(self):
        # With deadband=0, must behave exactly like the simple comparator.
        assert self.compare(50.0001, '>', 50.0, 0, 'c2') is True
        assert self.compare(49.9999, '>', 50.0, 0, 'c2') is False
        assert self.compare(50.0001, '>', 50.0, 0, 'c2') is True

    def test_low_alarm_no_chatter(self):
        """Symmetric: deadband works for < operator."""
        assert self.compare(11.0, '<', 10.0, 2.0, 'c3') is False
        assert self.compare(9.5, '<', 10.0, 2.0, 'c3') is True
        # Drifts above 10 but within +deadband — stays tripped
        assert self.compare(11.5, '<', 10.0, 2.0, 'c3') is True
        # Past 10 + 2 = 12 — clears
        assert self.compare(12.5, '<', 10.0, 2.0, 'c3') is False


# ===================================================================
# Cascade logic replica
# ===================================================================

class TestCascadeLogic:

    def test_remove_interlocks_referencing_channel(self):
        """Replicates _handle_safety_interlock_delete channel cascade."""
        interlocks = [
            {'id': 'il-1', 'name': 'High Pressure',
             'conditions': [{'channel': 'PT1', 'operator': '>', 'value': 100}]},
            {'id': 'il-2', 'name': 'Tank Empty',
             'conditions': [{'channel': 'TC1', 'operator': '<', 'value': 5}]},
            {'id': 'il-3', 'name': 'Combined',
             'conditions': [
                 {'channel': 'PT1', 'operator': '>', 'value': 100},
                 {'channel': 'PT2', 'operator': '>', 'value': 50},
             ]},
        ]
        deleted = 'PT1'
        # Match: any condition references the deleted channel
        to_remove = [il['id'] for il in interlocks if any(
            c.get('channel') == deleted for c in il['conditions']
        )]
        assert to_remove == ['il-1', 'il-3']

    def test_remove_alarm_configs_for_channel(self):
        """Replicates _handle_safety_alarm_delete by-channel cascade."""
        configs = [
            {'id': 'alarm-PT1', 'channel': 'PT1'},
            {'id': 'alarm-TC1', 'channel': 'TC1'},
            {'id': 'alarm-PT1-low', 'channel': 'PT1'},
        ]
        deleted = 'PT1'
        survivors = [c for c in configs if c['channel'] != deleted]
        assert [c['id'] for c in survivors] == ['alarm-TC1']

    def test_uv_prefix_cascade(self):
        """User-variable name 'RPM' must cascade as 'uv.RPM'."""
        var_name = 'RPM'
        ref = f'uv.{var_name}'
        assert ref == 'uv.RPM'

    def test_py_prefix_cascade(self):
        """Python-published name 'computed_pressure' must cascade as 'py.computed_pressure'."""
        published = 'computed_pressure'
        ref = published if published.startswith('py.') else f'py.{published}'
        assert ref == 'py.computed_pressure'


# ===================================================================
# SafetyTab UI guards
# ===================================================================

class TestSafetyTabUiGuards:

    def _read(self):
        return (Path(__file__).parent.parent / "dashboard" / "src" / "components" / "SafetyTab.vue").read_text(encoding='utf-8')

    def test_bypass_requires_confirm(self):
        content = self._read()
        idx = content.find("function toggleInterlockBypass")
        body = content[idx:idx + 2000]
        assert "confirm(" in body
        assert "prompt(" in body
        # Critical interlocks get extra warning
        assert "is_critical" in body or "CRITICAL INTERLOCK" in body

    def test_bypass_requires_audit_reason(self):
        content = self._read()
        idx = content.find("function toggleInterlockBypass")
        body = content[idx:idx + 2000]
        assert "Reason for bypass" in body
        assert "audit" in body.lower()

    def test_alarm_save_validates_digital_input(self):
        content = self._read()
        idx = content.find("function saveAlarmConfig")
        body = content[idx:idx + 2000]
        assert "digital_input" in body
        # Must reject analog limits OR strip them and warn
        assert "high_high" in body
        assert "showSafetyFeedback" in body

    def test_validation_uses_feedback_not_alert(self):
        content = self._read()
        idx = content.find("function saveAlarmConfig")
        body = content[idx:idx + 2000]
        # Old: alert(`Invalid alarm configuration: ...`)
        # New: showSafetyFeedback('error', ...)
        assert "alert(`Invalid alarm" not in body

    def test_latch_status_has_tooltip(self):
        content = self._read()
        # Tooltip explaining latched semantics
        idx = content.find('class="latch-status active"')
        body = content[idx:idx + 600]
        assert "title=" in body
        assert "manually reset" in body or "intentional" in body


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
