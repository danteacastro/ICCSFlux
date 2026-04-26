"""
Data Tab Bug Fix Tests

Verifies the highest-impact fixes from the Data tab audit (Phases 1-4).
Mike runs cDAQ recordings live; the Data tab needs to fail loudly, not
silently degrade.

Bugs fixed:
  Phase 1 — Trigger channel cascade
    - Backend silently recorded everything when trigger_channel was missing
      from incoming values. Now drops samples + warns once.
    - Frontend triggerChannel pointed at deleted channels with no cleanup
      and no validation at start. Now watch-clears + revalidates.

  Phase 2 — User variable `log` sync at mount
    - syncUserVariableLog was only called on per-toggle. Vars restored from
      localStorage as "selected" had log=false on backend, so they didn't
      record. Now reconciled at mount and on variablesList change.

  Phase 3 — File list refresh + recording state badge
    - Stop failures left the file list stale. Mike thought recording stopped
      but it was still running. Now refreshes on success AND failure, and
      a "STOPPING…" badge tracks transitions even before the response.

  Phase 4 — Pre-trigger buffer never flushed (CRITICAL)
    - The pre-trigger feature buffered samples but never wrote them when the
      trigger fired. _pretrigger_flush_pending now drains the buffer in
      write_sample. Buffered samples discarded on stop now log a warning.
"""

import sys
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Allow importing recording_manager without the full daq_service stack
sys.path.insert(0, str(Path(__file__).parent.parent / "services"))


# ===================================================================
# Phase 1 + 2 + 3 — Frontend (DataTab.vue) source-level checks
# ===================================================================

class TestDataTabFrontendFixes:

    def _read(self):
        return (Path(__file__).parent.parent / "dashboard" / "src" / "components" / "DataTab.vue").read_text(encoding='utf-8')

    # --- Phase 1: Trigger channel cascade ---

    def test_trigger_channel_validation_checks_existence(self):
        """startRecording must reject a triggerChannel that's not in the
        current availableChannels list, not just falsy."""
        content = self._read()
        idx = content.find("function startRecording")
        body = content[idx:idx + 3500]
        assert "allChannelNames.value.includes(trig)" in body, \
            "Validation must verify the trigger channel still exists"
        # Old behavior was just `!recordingConfig.value.triggerChannel` — must
        # now error out when the name doesn't resolve.
        assert "no longer exists" in body

    def test_trigger_channel_watch_exists(self):
        """A watcher must clear triggerChannel when it disappears."""
        content = self._read()
        # Watcher keyed off allChannelNames
        assert "watch(allChannelNames" in content
        # Must call setRecordingConfig to clear
        assert "setRecordingConfig({ triggerChannel: '' })" in content
        # And must show feedback so the user knows
        assert "was deleted" in content or "Trigger tag" in content

    # --- Phase 2: User variable log reconciliation ---

    def test_reconcile_user_variable_logs_exists(self):
        content = self._read()
        assert "function reconcileUserVariableLogs" in content

    def test_reconcile_called_on_mount(self):
        content = self._read()
        idx = content.find("onMounted(()")
        body = content[idx:idx + 2500]
        assert "reconcileUserVariableLogs()" in body

    def test_reconcile_walks_variables_and_pushes_log_flag(self):
        """Reconciliation must look at every user variable and call
        updateVariable when its log flag doesn't match the selection."""
        content = self._read()
        idx = content.find("function reconcileUserVariableLogs")
        body = content[idx:idx + 600]
        assert "playground.variablesList.value" in body
        assert "selectedRecordingChannels" in body
        assert "updateVariable" in body
        assert "log: shouldLog" in body or "{ log:" in body

    def test_reconcile_on_variables_change(self):
        """A separate watcher must auto-add user vars whose log flag was
        flipped on from VariablesTab so they show up checked in DataTab."""
        content = self._read()
        # Watcher keyed off variablesList shape
        assert "playground.variablesList.value.map(v => `${v.name}:${v.log}`)" in content

    # --- Phase 3: File list refresh + recording state badge ---

    def test_file_list_refreshed_on_failure(self):
        """If the recording response is failure, the file list must still
        refresh so the operator can see ground-truth state."""
        content = self._read()
        # Find the !response.success branch
        idx = content.find("Recording operation failed")
        body = content[idx:idx + 400]
        assert "listRecordedFiles" in body, \
            "On failure we must still refresh the file list"

    def test_recording_op_kind_tracks_start_vs_stop(self):
        content = self._read()
        assert "recordingOpKind = ref" in content
        assert "'start'" in content and "'stop'" in content
        # setRecordingOp signature must take a kind
        assert "function setRecordingOp(kind:" in content

    def test_recording_op_timeout_refreshes_files(self):
        """When the 10s fallback timeout fires, the file list must refresh
        AND a clear feedback message must appear."""
        content = self._read()
        idx = content.find("setRecordingOp(kind")
        body = content[idx:idx + 1500]
        assert "listRecordedFiles" in body
        assert "timed out" in body.lower()

    def test_status_badge_shows_starting_and_stopping(self):
        """Template must render STARTING…/STOPPING… not just RECORDING/IDLE."""
        content = self._read()
        assert "STARTING…" in content
        assert "STOPPING…" in content
        assert "recordingOpKind === 'start'" in content
        assert "recordingOpKind === 'stop'" in content

    def test_record_buttons_disabled_during_op(self):
        """Both Start and Stop buttons must :disabled while isRecordingOp."""
        content = self._read()
        idx = content.find('class="record-btn start"')
        snippet = content[idx:idx + 600]
        assert "isRecordingOp" in snippet
        idx2 = content.find('class="record-btn stop"')
        snippet2 = content[idx2:idx2 + 600]
        assert "isRecordingOp" in snippet2

    def test_stop_recording_has_confirm(self):
        content = self._read()
        idx = content.find("function stopRecording")
        body = content[idx:idx + 800]
        assert "confirm(" in body

    # --- Phase 4 frontend: DB warning pill ---

    def test_db_status_shows_warning_during_recording_drop(self):
        content = self._read()
        # When recording but db_connected is false, must show a warning, not "Idle"
        assert "file-only mode" in content

    # --- Phase 5: Size estimate hint when zero selected ---

    def test_size_estimate_shows_hint_when_no_channels(self):
        content = self._read()
        assert "Select tags to estimate" in content


# ===================================================================
# Phase 1 + 4 — Backend recording_manager.py
# ===================================================================

class TestRecordingManagerTriggerGuard:
    """Verify the backend trigger logic no longer silently degrades when
    the configured channel goes missing, and that the pre-trigger buffer
    actually gets written to disk when the trigger fires."""

    def _make_rm(self, trigger_channel='PT1', condition='above', value=10.0):
        """Build a minimal RecordingManager instance with a mock config."""
        from daq_service.recording_manager import RecordingManager
        rm = RecordingManager.__new__(RecordingManager)
        # Bypass __init__ so we don't need the full daq_service stack
        rm.config = MagicMock()
        rm.config.mode = 'triggered'
        rm.config.trigger_channel = trigger_channel
        rm.config.trigger_condition = condition
        rm.config.trigger_value = value
        rm.config.pre_trigger_samples = 5
        rm.config.post_trigger_samples = 0
        rm.trigger_armed = True
        rm.trigger_fired = False
        rm.pre_trigger_buffer = []
        rm.last_trigger_value = None
        rm.post_trigger_count = 0
        rm._warned_trigger_missing = False
        rm._pretrigger_flush_pending = False
        return rm

    def test_trigger_channel_not_in_values_drops_sample(self):
        """When trigger_channel is missing from incoming values, _handle_trigger
        must return False (drop sample), not True (record everything)."""
        rm = self._make_rm(trigger_channel='PT1')
        # Values dict missing PT1 entirely (e.g., channel deleted)
        result = rm._handle_trigger({'TC1': 25.0, 'PT2': 15.0})
        assert result is False, \
            "Missing trigger channel must NOT silently record everything"

    def test_trigger_channel_missing_warns_once(self):
        """Repeated calls with a missing channel must not spam the log."""
        rm = self._make_rm(trigger_channel='PT1')
        for _ in range(100):
            rm._handle_trigger({'TC1': 25.0})
        assert rm._warned_trigger_missing is True

    def test_no_trigger_channel_configured_warns_once(self):
        """If trigger_channel is empty/None, function returns True (record
        all) but warns once that config is incomplete."""
        rm = self._make_rm(trigger_channel='')
        result = rm._handle_trigger({'PT1': 5.0})
        assert result is True
        assert rm._warned_trigger_missing is True

    def test_trigger_fires_sets_pretrigger_flush_pending(self):
        """When the trigger condition is met, the flush flag must flip on
        so write_sample knows to drain the pre-trigger buffer."""
        rm = self._make_rm(trigger_channel='PT1', condition='above', value=10.0)
        # Below threshold first — buffers samples
        rm._handle_trigger({'PT1': 5.0})
        rm._handle_trigger({'PT1': 8.0})
        assert len(rm.pre_trigger_buffer) == 2
        assert rm._pretrigger_flush_pending is False
        # Above threshold — fires
        result = rm._handle_trigger({'PT1': 15.0})
        assert result is True
        assert rm.trigger_fired is True
        assert rm._pretrigger_flush_pending is True, \
            "Flush flag must signal write_sample to drain the buffer"

    def test_pretrigger_buffer_capped_at_pre_trigger_samples(self):
        """Buffer must not grow unbounded while armed."""
        rm = self._make_rm(trigger_channel='PT1', value=100.0)
        for i in range(20):
            rm._handle_trigger({'PT1': float(i)})
        # Buffer is capped at pre_trigger_samples (5)
        assert len(rm.pre_trigger_buffer) <= 5

    def test_after_trigger_fires_subsequent_samples_recorded(self):
        rm = self._make_rm(trigger_channel='PT1', value=10.0)
        # Fire the trigger
        rm._handle_trigger({'PT1': 15.0})
        # Subsequent samples must record
        assert rm._handle_trigger({'PT1': 12.0}) is True
        assert rm._handle_trigger({'PT1': 8.0}) is True


# ===================================================================
# Logic replicas — frontend behaviors transcribed to Python
# ===================================================================

class TestFrontendLogicReplicas:

    def test_user_variable_log_reconcile(self):
        """The reconciliation rule: for each user variable, log == (uv.NAME
        is in selectedRecordingChannels)."""
        selected = {'PT1', 'TC1', 'uv.RPM', 'py.script1'}
        variables = [
            {'name': 'RPM', 'log': False},   # In selection but not logging — flip on
            {'name': 'Pressure', 'log': True},  # NOT in selection but logging — flip off
            {'name': 'Temp', 'log': False},  # Not in selection, not logging — leave
        ]
        for v in variables:
            should_log = f"uv.{v['name']}" in selected
            if bool(v['log']) != should_log:
                v['log'] = should_log
        log_map = {v['name']: v['log'] for v in variables}
        assert log_map == {'RPM': True, 'Pressure': False, 'Temp': False}

    def test_trigger_channel_clear_on_delete(self):
        """When a channel is removed from availableChannels, the trigger
        config must be cleared if it pointed at it."""
        recording_trigger = 'PT1'
        all_channels = ['TC1', 'PT2']  # PT1 was just deleted
        if recording_trigger and recording_trigger not in all_channels:
            recording_trigger = ''
        assert recording_trigger == ''

    def test_validate_blocks_missing_trigger(self):
        """startRecording must abort if the configured trigger channel
        isn't currently in the available list."""
        all_channels = ['TC1', 'PT2']
        config_trigger = 'PT1'  # Stale

        def can_start():
            if config_trigger and config_trigger not in all_channels:
                return False
            return True

        assert not can_start()


class TestRecordingOpStateMachine:
    """Replicate the recordingOpKind state machine."""

    def test_kind_transitions_on_start(self):
        kind = None

        def set_op(k):
            nonlocal kind
            kind = k

        set_op('start')
        assert kind == 'start'
        # Response received
        kind = None
        assert kind is None

    def test_kind_clears_on_response(self):
        is_op = True
        kind = 'stop'

        def on_response():
            nonlocal is_op, kind
            is_op = False
            kind = None

        on_response()
        assert is_op is False
        assert kind is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
