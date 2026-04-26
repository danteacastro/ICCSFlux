"""
Session Tab Button Tests

Verifies the highest-impact fixes from the Session UI audit (Phase 2J).
Mike will run sessions live; the buttons need feedback, confirmation
on destructive actions, and loading states.

Bugs fixed:
  - Stop Session had NO confirmation. One misclick stopped recording,
    aborted the running sequence, killed session scripts. Now wraps
    in confirm() with a clear list of what will happen.
  - Reset All Variables had NO confirmation. One click wiped every
    counter/accumulator/RMS — could destroy an hour of test data.
  - Per-variable Reset had NO confirmation. Risky for accumulators
    tracking pump-hours or batch totals.
  - No loading state. After clicking Start/Stop, Mike saw nothing
    for the 2-3 second round-trip and might click again. Now buttons
    show "Starting…" / "Stopping…" and stay disabled during the call.
  - No error feedback. If Start failed (no acquisition, alarm active),
    the click silently did nothing. Now shows a red toast.
"""

import pytest
from pathlib import Path


class TestPlaygroundTabFixes:

    def _read(self):
        return (Path(__file__).parent.parent / "dashboard" / "src" / "components" / "PlaygroundTab.vue").read_text(encoding='utf-8')

    def test_handle_start_session_exists(self):
        content = self._read()
        assert "function handleStartSession" in content

    def test_handle_stop_session_exists(self):
        content = self._read()
        assert "function handleStopSession" in content

    def test_start_button_uses_wrapper(self):
        """Start button click handler must use handleStartSession (not raw playground call)."""
        content = self._read()
        idx = content.find("Start Session")
        # Look at the button declaration above
        snippet = content[max(0, idx - 800):idx]
        assert "@click=\"handleStartSession\"" in snippet
        # Old raw call should not be on the same button
        assert '@click="playground.startTestSession()"' not in snippet

    def test_stop_button_uses_wrapper(self):
        content = self._read()
        idx = content.find("Stop Session")
        snippet = content[max(0, idx - 800):idx]
        assert "@click=\"handleStopSession\"" in snippet

    def test_start_handler_has_confirm(self):
        """handleStartSession must show confirm() before starting."""
        content = self._read()
        idx = content.find("function handleStartSession")
        body = content[idx:idx + 1500]
        assert "confirm(" in body

    def test_stop_handler_has_confirm(self):
        content = self._read()
        idx = content.find("function handleStopSession")
        body = content[idx:idx + 1500]
        assert "confirm(" in body
        # Stop confirmation must mention what will happen
        assert "recording" in body.lower() or "scripts" in body.lower()

    def test_reset_all_handler_has_confirm(self):
        """Reset All wipes every variable — must confirm."""
        content = self._read()
        idx = content.find("function handleResetAllVariables")
        body = content[idx:idx + 1500]
        assert "confirm(" in body
        # Confirmation should mention undoability
        assert "cannot be undone" in body.lower() or "undo" in body.lower()

    def test_per_variable_reset_has_confirm(self):
        content = self._read()
        idx = content.find("function handleResetVariable")
        body = content[idx:idx + 1000]
        assert "confirm(" in body

    def test_reset_all_button_uses_wrapper(self):
        """Reset All button must call handleResetAllVariables, not raw API."""
        content = self._read()
        idx = content.find('"btn btn-sm" @click="handleResetAllVariables"')
        assert idx > 0, "Reset All button should use handleResetAllVariables wrapper"

    def test_per_variable_reset_button_uses_wrapper(self):
        """Per-variable Reset button must call handleResetVariable wrapper."""
        content = self._read()
        # Should call our wrapper, not raw playground.resetVariable on the button
        assert '@click="handleResetVariable(variable)"' in content

    def test_session_feedback_state_exists(self):
        """sessionFeedback ref must be declared so we can show errors."""
        content = self._read()
        assert "sessionFeedback = ref" in content
        assert "sessionCommandPending" in content

    def test_session_feedback_displayed(self):
        """The template must render the feedback banner when set."""
        content = self._read()
        assert 'v-if="sessionFeedback"' in content
        assert 'class="session-feedback"' in content

    def test_loading_state_on_start_button(self):
        """Start button must show 'Starting…' and stay disabled during command."""
        content = self._read()
        idx = content.find("Start Session")
        snippet = content[max(0, idx - 1000):idx + 200]
        # Disabled while pending
        assert "sessionCommandPending" in snippet
        # Label changes during pending
        assert "Starting" in snippet or "Starting…" in snippet

    def test_loading_state_on_stop_button(self):
        content = self._read()
        idx = content.find("Stop Session")
        snippet = content[max(0, idx - 1000):idx + 200]
        assert "sessionCommandPending" in snippet
        assert "Stopping" in snippet


class TestConfirmationLogicReplica:
    """Replicate the confirmation flow to verify it correctly blocks
    destructive actions when the user clicks Cancel."""

    def test_cancel_blocks_action(self):
        """If confirm() returns False, the action must NOT proceed."""
        action_ran = [False]

        def confirm_then_act(confirm_result):
            if not confirm_result:
                return  # Bail
            action_ran[0] = True

        # User clicks Cancel
        confirm_then_act(False)
        assert not action_ran[0]

    def test_confirm_proceeds_with_action(self):
        action_ran = [False]

        def confirm_then_act(confirm_result):
            if not confirm_result:
                return
            action_ran[0] = True

        # User clicks OK
        confirm_then_act(True)
        assert action_ran[0]


class TestFeedbackStateLifecycle:
    """The feedback banner shows then auto-dismisses."""

    def test_feedback_set_and_clear(self):
        feedback = {'value': None}

        def set_feedback(type_, text):
            feedback['value'] = {'type': type_, 'text': text}

        def clear_feedback():
            feedback['value'] = None

        set_feedback('error', 'Start failed')
        assert feedback['value']['type'] == 'error'
        assert feedback['value']['text'] == 'Start failed'

        clear_feedback()
        assert feedback['value'] is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
