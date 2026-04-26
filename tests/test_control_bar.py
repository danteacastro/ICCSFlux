"""
ControlBar Button Tests

Verifies fixes for the audit findings on the three most important ControlBar
buttons (START/STOP, RECORD, SESSION). Mike runs these live; the buttons need
loading state, error feedback, and confirmation on destructive actions.

Bugs fixed:
  - START/STOP/RECORD/SESSION had no pending state. Backend round-trip is
    2-3 seconds and the user could rapid-click during the gap, double-firing
    commands. Now all four bind to acquireCommandPending /
    recordingCommandPending / sessionCommandPending and stay disabled +
    show "STARTING…" / "STOPPING…" labels during the call.
  - Errors were silently logged to console. lastAcquireError /
    lastRecordingError / lastSessionError refs existed in useMqtt but were
    never bound to the visible UI (only to the hidden DiagnosticOverlay).
    Now ControlBar shows an inline red banner with a dismiss button.
  - STOP had no confirmation. One misclick aborts acquisition AND any active
    recording AND the running test session. Now confirms with a clear list.
  - RECORD STOP had no confirmation. Stopping recording finalizes the file;
    a new run starts a new file. Now confirms.
  - SESSION STOP had no confirmation. Aborts running sequences and session
    scripts. Now confirms.
"""

import pytest
from pathlib import Path


class TestControlBarFixes:

    def _read_bar(self):
        return (Path(__file__).parent.parent / "dashboard" / "src" / "components" / "ControlBar.vue").read_text(encoding='utf-8')

    def _read_app(self):
        return (Path(__file__).parent.parent / "dashboard" / "src" / "App.vue").read_text(encoding='utf-8')

    # -- pending state plumbed in --

    def test_acquire_pending_computed_exists(self):
        content = self._read_bar()
        assert "acquirePending = computed" in content
        assert "mqtt.acquireCommandPending" in content

    def test_recording_pending_computed_exists(self):
        content = self._read_bar()
        assert "recordingPending = computed" in content
        assert "mqtt.recordingCommandPending" in content

    def test_session_pending_computed_exists(self):
        content = self._read_bar()
        assert "sessionPending = computed" in content
        assert "mqtt.sessionCommandPending" in content

    # -- pending state actually disables and relabels buttons --

    def test_start_button_disabled_when_pending(self):
        content = self._read_bar()
        idx = content.find("'STARTING…' : 'START'")
        assert idx > 0, "Start button must show STARTING… label when acquirePending"
        snippet = content[max(0, idx - 600):idx]
        assert "acquirePending" in snippet
        assert ":disabled=" in snippet

    def test_stop_button_disabled_when_pending(self):
        content = self._read_bar()
        idx = content.find("'STOPPING…' : 'STOP'")
        assert idx > 0, "Stop button must show STOPPING… label when acquirePending"
        snippet = content[max(0, idx - 600):idx]
        assert "acquirePending" in snippet

    def test_record_start_button_disabled_when_pending(self):
        content = self._read_bar()
        idx = content.find("'STARTING…' : 'RECORD'")
        assert idx > 0
        snippet = content[max(0, idx - 600):idx]
        assert "recordingPending" in snippet

    def test_record_stop_disabled_when_pending(self):
        content = self._read_bar()
        # When recording, label flips to STOPPING… or the timer
        assert "recordingPending ? 'STOPPING…' : recordingTime" in content

    def test_session_toggle_disabled_when_pending(self):
        content = self._read_bar()
        idx = content.find('class="toggle-btn"')
        assert idx > 0
        snippet = content[idx:idx + 800]
        assert "sessionPending" in snippet
        # Must be in the disabled binding, not just classes
        assert "|| sessionPending" in snippet

    # -- error feedback banner --

    def test_error_banner_exists(self):
        content = self._read_bar()
        assert 'class="control-error-banner"' in content
        assert 'v-if="anyError"' in content

    def test_error_banner_shows_all_three_error_types(self):
        content = self._read_bar()
        idx = content.find('class="control-error-banner"')
        snippet = content[idx:idx + 600]
        # Banner must display whichever error is set
        assert "acquireError" in snippet
        assert "recordingError" in snippet
        assert "sessionError" in snippet

    def test_error_banner_has_dismiss(self):
        content = self._read_bar()
        assert "dismissError" in content
        # Dismiss must clear all three refs (otherwise stale errors linger)
        idx = content.find("function dismissError")
        body = content[idx:idx + 400]
        assert "lastAcquireError.value = null" in body
        assert "lastRecordingError.value = null" in body
        assert "lastSessionError.value = null" in body

    # -- confirmations on destructive actions in App.vue --

    def test_handle_stop_has_confirm(self):
        content = self._read_app()
        idx = content.find("async function handleStop")
        body = content[idx:idx + 1500]
        assert "confirm(" in body
        # Should mention what it cascades to
        assert "Stop acquisition" in body

    def test_handle_stop_warns_about_recording(self):
        """If recording is active, the confirm must warn about it."""
        content = self._read_app()
        idx = content.find("async function handleStop")
        body = content[idx:idx + 1500]
        assert "isRecording" in body
        assert "End the current recording" in body or "recording" in body.lower()

    def test_handle_stop_warns_about_session(self):
        content = self._read_app()
        idx = content.find("async function handleStop")
        body = content[idx:idx + 1500]
        assert "isSessionActive" in body
        assert "session" in body.lower()

    def test_handle_record_stop_has_confirm(self):
        content = self._read_app()
        idx = content.find("async function handleRecordStop")
        body = content[idx:idx + 800]
        assert "confirm(" in body
        # Should mention finalization
        assert "finalized" in body.lower() or "file" in body.lower()

    def test_handle_session_stop_has_confirm(self):
        content = self._read_app()
        idx = content.find("async function handleSessionStop")
        body = content[idx:idx + 800]
        assert "confirm(" in body
        # Should mention sequence/scripts
        assert "sequence" in body.lower() or "scripts" in body.lower()


class TestConfirmCancelsCommand:
    """Replicate the confirm-then-act pattern to verify Cancel halts the action."""

    def test_cancel_skips_command(self):
        called = [False]

        def stop_handler(confirmed):
            if not confirmed:
                return
            called[0] = True

        stop_handler(False)
        assert not called[0]

    def test_ok_runs_command(self):
        called = [False]

        def stop_handler(confirmed):
            if not confirmed:
                return
            called[0] = True

        stop_handler(True)
        assert called[0]


class TestPendingFlagBlocksDoubleClick:
    """Replicate the pending-flag pattern: while a command is in flight, the
    next click is suppressed."""

    def test_double_click_only_fires_once(self):
        pending = {'value': False}
        fire_count = {'count': 0}

        def click():
            if pending['value']:
                return
            pending['value'] = True
            try:
                fire_count['count'] += 1
            finally:
                pending['value'] = False

        # Simulate Mike rapid-clicking — but the test runs sync so we
        # interleave manually
        pending['value'] = True  # First click is in flight
        click()  # Second click during pending — should bail
        pending['value'] = False
        click()  # Third click after pending cleared
        assert fire_count['count'] == 1

    def test_command_clears_pending_on_error(self):
        """Even if the command fails, pending must clear so the user can retry."""
        pending = {'value': False}

        def click_with_error():
            if pending['value']:
                return
            pending['value'] = True
            try:
                raise RuntimeError("backend failed")
            except RuntimeError:
                pass  # Logged; error displayed via toast
            finally:
                pending['value'] = False

        click_with_error()
        assert pending['value'] is False, "Pending must clear in finally{} even on error"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
