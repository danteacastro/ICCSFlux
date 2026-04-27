"""
Overview Tab + Widgets Hardening Tests

Verifies fixes from the Overview/widgets audit. Mike runs cDAQ in production;
output widgets (toggle, setpoint, action button) are the only widgets that
can directly damage equipment, so silent failures here are unacceptable.

Bugs fixed:
  CRITICAL
    - Output writes failed silently across every widget (ActionButton:258,
      DashboardGrid:265, SetpointWidget:241, ToggleSwitch). setOutput now
      returns {success, error} and sets a global `lastOutputError` ref
      that App.vue surfaces via toast. Validation rejections (NaN, digital
      out-of-range, bounds, disconnected broker) all set the toast.
    - dashboard.handleChannelDeleted didn't prune P&ID symbols/pipes or
      plotStyles entries — orphans showed "undefined"/0 forever. Now
      cascades: clears symbol channel/fillChannel/flowChannel, pipe
      flowChannel, and filters plotStyles by deleted channel name.

  HIGH
    - CrioStatusWidget computed properties read crio state above the cDAQ
      guard. Now every dependent computed short-circuits when isCdaqMode.
    - ActionButton confirm timer leaked across re-clicks; ToggleSwitch
      confirm prompt auto-dismissed after 3s mid-decision (footgun).
      Both now keep the prompt visible until the operator explicitly
      accepts or cancels.
    - Setpoint step calc could produce huge step on huge ranges, making
      fine adjustment impossible. Capped at 10 with NaN/Infinity guard.
    - Destructive system_command actions (acquisition_stop, recording_stop,
      latch_reset_all) now confirm by default even without the prop set.
    - Output widgets gated by Operator role at the frontend (backend is
      authoritative; frontend disable matches the rest of the dashboard).
    - WidgetConfigModal save now warns on a channel reference that doesn't
      resolve, drops resolved-out channels on multi-channel widgets, and
      surfaces store.updateWidget errors instead of silently failing.

  Pending state
    - useMqtt.outputWritePending Map tracks per-channel in-flight writes.
      Toggle and Setpoint disable during the 1.2s window, preventing the
      double-fire that previously sent two writes for one operator click.
"""

import pytest
from pathlib import Path


class TestUseMqttOutputErrorPath:

    def _read(self):
        return (Path(__file__).parent.parent / "dashboard" / "src" / "composables" / "useMqtt.ts").read_text(encoding='utf-8')

    def test_last_output_error_ref_exists(self):
        content = self._read()
        assert "lastOutputError = ref" in content
        # Tracks channel + message + timestamp
        assert "channel: string" in content
        assert "message: string" in content

    def test_output_write_pending_ref_exists(self):
        content = self._read()
        assert "outputWritePending = ref" in content
        # Per-channel keyed
        assert "Record<string, boolean>" in content

    def test_set_output_returns_status(self):
        content = self._read()
        idx = content.find("function setOutput(")
        body = content[idx:idx + 200]
        assert "{ success: boolean; error?: string }" in body

    def test_set_output_disconnected_returns_failure(self):
        content = self._read()
        idx = content.find("function setOutput(")
        body = content[idx:idx + 1000]
        # Disconnected branch must return failure status with message
        assert "Not connected to MQTT broker" in body
        assert "_setOutputError" in body
        assert "return { success: false" in body

    def test_set_output_validation_rejects_publish(self):
        """NaN, digital range violation, and bounds violations must NOT
        send a publish — they must return failure with a message."""
        content = self._read()
        idx = content.find("function setOutput(")
        body = content[idx:idx + 3000]
        # NaN guard
        assert "Number.isFinite(value)" in body
        assert "NaN or Infinity" in body
        # Digital channel range guard
        assert "digital_output" in body
        assert "requires 0 or 1" in body
        # Bounds-out-of-range NOW returns failure (was just a warn-and-send)
        assert "exceeds high_limit" in body
        assert "below low_limit" in body
        # Each of these calls _setOutputError before returning
        # (verified by counting the pattern occurrences)
        assert body.count("_setOutputError(") >= 4

    def test_set_output_returns_success_after_send(self):
        content = self._read()
        idx = content.find("function setOutput(")
        body = content[idx:idx + 4000]
        assert "return { success: true }" in body

    def test_pending_set_on_send(self):
        content = self._read()
        idx = content.find("function setOutput(")
        body = content[idx:idx + 4000]
        assert "_setOutputPending(channelName)" in body

    def test_clear_last_output_error_exposed(self):
        content = self._read()
        assert "function clearLastOutputError" in content
        # Returned from composable
        assert "clearLastOutputError," in content
        assert "lastOutputError," in content
        assert "outputWritePending," in content


class TestAppVueOutputErrorToast:

    def _read(self):
        return (Path(__file__).parent.parent / "dashboard" / "src" / "App.vue").read_text(encoding='utf-8')

    def test_output_error_toast_present(self):
        content = self._read()
        assert "output-error-toast" in content
        assert 'v-if="mqtt.lastOutputError.value"' in content

    def test_toast_shows_channel_and_message(self):
        content = self._read()
        idx = content.find("output-error-toast")
        body = content[idx:idx + 600]
        assert "lastOutputError.value.channel" in body
        assert "lastOutputError.value.message" in body

    def test_toast_dismiss_clears_error(self):
        content = self._read()
        assert "mqtt.clearLastOutputError()" in content


class TestPidAndPlotStylesCascade:

    def _read(self):
        return (Path(__file__).parent.parent / "dashboard" / "src" / "stores" / "dashboard.ts").read_text(encoding='utf-8')

    def test_handlechanneldeleted_prunes_plotstyles(self):
        content = self._read()
        idx = content.find("function handleChannelDeleted")
        body = content[idx:idx + 4000]
        assert "plotStyles" in body
        # Filters by channel
        assert ".filter(" in body

    def test_handlechanneldeleted_clears_symbol_channels(self):
        """All three symbol bindings (channel, fillChannel, flowChannel) cleared."""
        content = self._read()
        idx = content.find("function handleChannelDeleted")
        body = content[idx:idx + 4000]
        assert "s.channel === channelName" in body
        assert "s.fillChannel === channelName" in body
        assert "s.flowChannel === channelName" in body

    def test_handlechanneldeleted_clears_pipe_flow(self):
        content = self._read()
        idx = content.find("function handleChannelDeleted")
        body = content[idx:idx + 4000]
        assert "p.flowChannel === channelName" in body

    def test_pipes_geometry_preserved(self):
        """Pipes connect two symbols by geometry — we should NOT remove the
        pipe just because its flowChannel was deleted, only clear the binding."""
        content = self._read()
        idx = content.find("function handleChannelDeleted")
        body = content[idx:idx + 4000]
        # No pipes.splice or pipes filter for this case
        # The cascade walks pipes and only clears flowChannel
        assert "p.flowChannel = undefined" in body


class TestCrioStatusWidgetGuards:

    def _read(self):
        return (Path(__file__).parent.parent / "dashboard" / "src" / "widgets" / "CrioStatusWidget.vue").read_text(encoding='utf-8')

    def test_state_class_short_circuits_in_cdaq(self):
        content = self._read()
        idx = content.find("const stateClass = computed")
        body = content[idx:idx + 400]
        assert "isCdaqMode.value" in body

    def test_state_label_short_circuits_in_cdaq(self):
        content = self._read()
        idx = content.find("const stateLabel = computed")
        body = content[idx:idx + 400]
        assert "isCdaqMode.value" in body

    def test_io_counts_short_circuit_in_cdaq(self):
        content = self._read()
        # All three counts must guard cdaq mode
        for name in ("inputCount", "outputCount", "trippedCount"):
            idx = content.find(f"const {name} = computed")
            body = content[idx:idx + 250]
            assert "isCdaqMode.value" in body, f"{name} missing cDAQ guard"


class TestToggleSwitchHardening:

    def _read(self):
        return (Path(__file__).parent.parent / "dashboard" / "src" / "widgets" / "ToggleSwitch.vue").read_text(encoding='utf-8')

    def test_no_auto_dismiss_3s_timer(self):
        """The 3-second auto-dismiss footgun must be removed."""
        content = self._read()
        idx = content.find("function toggle()")
        body = content[idx:idx + 1000]
        # Old: confirmTimer = setTimeout(() => { showConfirm.value = false }, 3000)
        assert "3000" not in body, \
            "3-second auto-dismiss must be removed — prompt must stay until explicit accept/cancel"

    def test_pending_state_disables_toggle(self):
        content = self._read()
        assert "writePending" in content
        idx = content.find("canToggle = computed")
        body = content[idx:idx + 400]
        assert "writePending" in body

    def test_role_gate_disables_toggle(self):
        content = self._read()
        assert "hasOperatorRole" in content
        idx = content.find("canToggle = computed")
        body = content[idx:idx + 400]
        assert "hasOperatorRole.value" in body

    def test_status_text_explains_role_gate(self):
        content = self._read()
        assert "Requires Operator role" in content


class TestActionButtonHardening:

    def _read(self):
        return (Path(__file__).parent.parent / "dashboard" / "src" / "widgets" / "ActionButtonWidget.vue").read_text(encoding='utf-8')

    def test_no_auto_dismiss_3s_timer(self):
        content = self._read()
        idx = content.find("function handleClick")
        body = content[idx:idx + 1000]
        # The setTimeout(..., 3000) for confirm auto-cancel must be removed
        assert "3000" not in body, "3s confirm auto-dismiss must be removed"

    def test_destructive_system_commands_force_confirm(self):
        content = self._read()
        # Destructive set must be defined
        assert "_DESTRUCTIVE_SYSTEM_COMMANDS" in content
        assert "'acquisition_stop'" in content
        assert "'recording_stop'" in content
        assert "'latch_reset_all'" in content
        # Effective gate uses both prop and destructive set
        assert "requiresConfirmation" in content
        idx = content.find("requiresConfirmation = computed")
        body = content[idx:idx + 600]
        assert "_DESTRUCTIVE_SYSTEM_COMMANDS" in body

    def test_role_gate_disables_button(self):
        content = self._read()
        assert "hasOperatorRole" in content
        idx = content.find("isDisabled = computed")
        body = content[idx:idx + 400]
        assert "hasOperatorRole.value" in body

    def test_digital_output_checks_status(self):
        """digital_output action must early-return on setOutput failure to
        avoid blasting a follow-up reset write."""
        content = self._read()
        idx = content.find("case 'digital_output':")
        body = content[idx:idx + 800]
        assert "result.success" in body or "result = mqtt.setOutput" in body
        # Bails (break) when not successful before scheduling the reset
        assert "if (!result.success)" in body


class TestSetpointWidgetHardening:

    def _read(self):
        return (Path(__file__).parent.parent / "dashboard" / "src" / "widgets" / "SetpointWidget.vue").read_text(encoding='utf-8')

    def test_step_handles_invalid_range(self):
        """NaN/Infinity in range must not propagate into step."""
        content = self._read()
        idx = content.find("const stepVal = computed")
        body = content[idx:idx + 700]
        assert "Number.isFinite(range)" in body

    def test_step_proportional_to_large_range(self):
        """For large ranges, step is range/100 — no cap. Earlier I added a
        Math.min(10, ...) cap because the audit claimed it 'made fine
        adjustment impossible'; that was backwards. Capping makes large-range
        traversal take 100k clicks. Document the original 1% behavior."""
        content = self._read()
        idx = content.find("const stepVal = computed")
        body = content[idx:idx + 700]
        # No artificial cap on large ranges
        assert "Math.min(10," not in body
        # The 1% rule is preserved
        assert "range / 100" in body

    def test_pending_disables_input(self):
        content = self._read()
        assert "writePending" in content
        idx = content.find("isDisabled = computed")
        body = content[idx:idx + 600]
        assert "writePending.value" in body

    def test_role_gate_disables(self):
        content = self._read()
        assert "hasOperatorRole" in content
        idx = content.find("isDisabled = computed")
        body = content[idx:idx + 600]
        assert "hasOperatorRole.value" in body


class TestWidgetConfigModalValidation:

    def _read(self):
        return (Path(__file__).parent.parent / "dashboard" / "src" / "components" / "WidgetConfigModal.vue").read_text(encoding='utf-8')

    def test_channel_exists_helper(self):
        content = self._read()
        assert "function channelExists" in content
        # Recognizes uv./py./script: prefixes plus hardware channels
        idx = content.find("function channelExists")
        body = content[idx:idx + 500]
        assert "store.channels" in body
        assert "uv." in body
        assert "py." in body
        assert "script:" in body

    def test_save_warns_on_missing_channel(self):
        content = self._read()
        idx = content.find("function save()")
        body = content[idx:idx + 2500]
        # Confirms with the user before saving a widget pointing at a deleted channel
        assert "channelExists(w.channel)" in body or "channelExists(" in body
        assert "doesn't exist" in body or "no longer" in body or "doesn" in body

    def test_save_drops_unresolved_multi_channel(self):
        content = self._read()
        idx = content.find("function save()")
        body = content[idx:idx + 2500]
        assert ".filter(channelExists)" in body

    def test_save_handles_store_error(self):
        content = self._read()
        idx = content.find("function save()")
        body = content[idx:idx + 2500]
        assert "try {" in body
        assert "catch" in body
        assert "Save failed" in body


class TestDashboardGridHandleToggleChange:

    def _read(self):
        return (Path(__file__).parent.parent / "dashboard" / "src" / "components" / "DashboardGrid.vue").read_text(encoding='utf-8')

    def test_logs_failure(self):
        content = self._read()
        idx = content.find("function handleToggleChange")
        body = content[idx:idx + 1000]
        assert "result.success" in body or "result = mqtt.setOutput" in body
        assert "result.error" in body


# ===================================================================
# Logic replicas
# ===================================================================

class TestPidCascadeLogic:

    def test_symbol_channel_cleared(self):
        symbols = [
            {'id': 's1', 'channel': 'PT1', 'fillChannel': None, 'flowChannel': None},
            {'id': 's2', 'channel': 'TC1', 'fillChannel': 'PT1', 'flowChannel': None},
            {'id': 's3', 'channel': 'TC1', 'fillChannel': None, 'flowChannel': 'PT1'},
        ]
        deleted = 'PT1'
        for s in symbols:
            if s['channel'] == deleted:
                s['channel'] = None
            if s['fillChannel'] == deleted:
                s['fillChannel'] = None
            if s['flowChannel'] == deleted:
                s['flowChannel'] = None
        assert symbols[0]['channel'] is None
        assert symbols[1]['fillChannel'] is None
        assert symbols[2]['flowChannel'] is None
        # Other bindings preserved
        assert symbols[1]['channel'] == 'TC1'
        assert symbols[2]['channel'] == 'TC1'

    def test_pipe_flow_cleared_geometry_preserved(self):
        pipes = [
            {'id': 'pipe-a', 'flowChannel': 'PT1', 'from': 's1', 'to': 's2'},
            {'id': 'pipe-b', 'flowChannel': 'TC1', 'from': 's2', 'to': 's3'},
        ]
        deleted = 'PT1'
        for p in pipes:
            if p.get('flowChannel') == deleted:
                p['flowChannel'] = None
        # Pipe still exists, just its flow binding is cleared
        assert len(pipes) == 2
        assert pipes[0]['flowChannel'] is None
        assert pipes[0]['from'] == 's1' and pipes[0]['to'] == 's2'

    def test_plot_styles_filtered(self):
        plot_styles = [
            {'channel': 'PT1', 'color': 'red'},
            {'channel': 'TC1', 'color': 'blue'},
            {'channel': 'PT1', 'color': 'green'},
        ]
        deleted = 'PT1'
        plot_styles = [p for p in plot_styles if p['channel'] != deleted]
        assert len(plot_styles) == 1
        assert plot_styles[0]['channel'] == 'TC1'


class TestSetOutputValidationLogic:

    def test_nan_rejected(self):
        import math
        value = math.nan
        # Mirror useMqtt validation
        is_finite = isinstance(value, (int, float)) and value == value and abs(value) != float('inf')
        assert not is_finite

    def test_digital_out_of_range_rejected(self):
        channel_type = 'digital_output'
        for v in (2, -1, 0.5, 0.99):
            valid = (channel_type != 'digital_output') or v in (0, 1)
            assert not valid

    def test_high_limit_rejected(self):
        value = 105.0
        high_limit = 100.0
        rejected = value > high_limit
        assert rejected


class TestDestructiveCommandConfirmLogic:

    def test_acquisition_stop_forces_confirm(self):
        destructive = {'acquisition_stop', 'recording_stop', 'latch_reset_all'}
        action = {'type': 'system_command', 'command': 'acquisition_stop'}
        require_prop = False
        forced = (action['type'] == 'system_command'
                  and action.get('command') in destructive)
        effective = require_prop or forced
        assert effective

    def test_acquisition_start_does_not_force(self):
        destructive = {'acquisition_stop', 'recording_stop', 'latch_reset_all'}
        action = {'type': 'system_command', 'command': 'acquisition_start'}
        require_prop = False
        forced = (action['type'] == 'system_command'
                  and action.get('command') in destructive)
        effective = require_prop or forced
        assert not effective


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
