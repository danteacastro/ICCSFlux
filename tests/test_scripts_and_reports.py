"""
Scripts Tab + Reports Hub Hardening Tests

Cleanup pass — the Python script subsystem was already heavily hardened in
earlier sessions; this audit found mostly silent-failure / UX gaps.

Bugs fixed:
  Scripts (CRITICAL)
    - Backend script command failures only logged to console; useBackendScripts
      now also surfaces them via the existing addNotification toast bus.
    - localStorage save failures in usePythonScripts were console-only — added
      lastScriptsSaveError ref + auto-clear timer for UI banner.
    - File import errors were caught but only console.error — now toast via
      scripts.addNotification('error', ...).

  Scripts (HIGH)
    - Delete script while it's running OR while editor is dirty: the confirm
      now lists what will be lost (running stop, unsaved edits) so a misclick
      mid-test doesn't kill an in-flight test silently.
    - OPTIMISTIC_UPDATE_TTL was 2s — too tight on slow links, causing the
      backend's stale status to overwrite the user's just-pressed change.
      Bumped to 8s.
    - saveScript() before validate() was fire-and-forget; validation could
      run against in-memory code while the backend still had the previous
      version. Now awaited.

  Scripts (LOW)
    - clearConsole() didn't go through requireEditPermission like all other
      mutations — fixed for consistency.

  Reports
    - refresh() used a blind 1500ms setTimeout to clear the loading flag,
      regardless of whether the response actually arrived. Now binds to
      auth.isLoadingAudit so the spinner clears on the actual response.
    - Custom date range had no validation. Now blocks queries with
      end-before-start, invalid format, or > 5 year range; surfaces
      inline near the inputs.
"""

import pytest
from pathlib import Path


class TestScriptsErrorSurface:

    def _read_backend(self):
        return (Path(__file__).parent.parent / "dashboard" / "src" / "composables" / "useBackendScripts.ts").read_text(encoding='utf-8')

    def _read_python(self):
        return (Path(__file__).parent.parent / "dashboard" / "src" / "composables" / "usePythonScripts.ts").read_text(encoding='utf-8')

    def _read_tab(self):
        return (Path(__file__).parent.parent / "dashboard" / "src" / "components" / "PythonScriptsTab.vue").read_text(encoding='utf-8')

    def test_backend_script_failure_surfaces_toast(self):
        content = self._read_backend()
        idx = content.find("function handleScriptResponse")
        body = content[idx:idx + 1500]
        # Was: console.error + lastError.value only
        # Now: also addNotification
        assert "addNotification" in body
        assert "Script" in body and "failed" in body.lower()

    def test_python_save_error_ref_exists(self):
        content = self._read_python()
        assert "lastScriptsSaveError = ref" in content
        assert "function clearScriptsSaveError" in content
        # Auto-clear timer
        assert "_lastScriptsSaveErrorTimer" in content

    def test_python_save_error_set_on_localstorage_failure(self):
        content = self._read_python()
        idx = content.find("function saveToLocalStorage")
        body = content[idx:idx + 600]
        assert "_setScriptsSaveError" in body

    def test_python_load_error_set_on_localstorage_failure(self):
        content = self._read_python()
        idx = content.find("function loadFromLocalStorage")
        body = content[idx:idx + 600]
        assert "_setScriptsSaveError" in body

    def test_python_save_error_exposed(self):
        content = self._read_python()
        # Returned for UI consumption
        assert "lastScriptsSaveError," in content
        assert "clearScriptsSaveError," in content

    def test_file_import_error_toasts(self):
        content = self._read_tab()
        idx = content.find("async function handleFileSelect")
        body = content[idx:idx + 1500]
        assert "scripts.addNotification" in body
        assert "File import failed" in body


class TestScriptsDeleteConfirm:

    def _read(self):
        return (Path(__file__).parent.parent / "dashboard" / "src" / "components" / "PythonScriptsTab.vue").read_text(encoding='utf-8')

    def test_delete_warns_when_running(self):
        content = self._read()
        idx = content.find("async function deleteScript")
        body = content[idx:idx + 1500]
        assert "isScriptRunning.value" in body
        assert "RUNNING" in body

    def test_delete_warns_when_dirty(self):
        content = self._read()
        idx = content.find("async function deleteScript")
        body = content[idx:idx + 1500]
        assert "isDirty.value" in body
        assert "unsaved" in body.lower()

    def test_delete_uses_confirm(self):
        content = self._read()
        idx = content.find("async function deleteScript")
        body = content[idx:idx + 1500]
        assert "confirm(" in body


class TestScriptsSaveBeforeRunAwait:

    def _read(self):
        return (Path(__file__).parent.parent / "dashboard" / "src" / "components" / "PythonScriptsTab.vue").read_text(encoding='utf-8')

    def test_save_awaited_before_validate(self):
        content = self._read()
        idx = content.find("async function toggleScript")
        body = content[idx:idx + 2500]
        # Old: saveScript()  — no await
        # New: await saveScript()
        assert "await saveScript()" in body


class TestScriptsClearConsolePermission:

    def _read(self):
        return (Path(__file__).parent.parent / "dashboard" / "src" / "components" / "PythonScriptsTab.vue").read_text(encoding='utf-8')

    def test_clear_console_gates_on_permission(self):
        content = self._read()
        idx = content.find("function clearConsole")
        body = content[idx:idx + 400]
        assert "requireEditPermission()" in body


class TestOptimisticUpdateTtl:

    def _read(self):
        return (Path(__file__).parent.parent / "dashboard" / "src" / "composables" / "useBackendScripts.ts").read_text(encoding='utf-8')

    def test_ttl_increased_from_2s(self):
        content = self._read()
        # Was 2000, now 8000 (or higher)
        assert "OPTIMISTIC_UPDATE_TTL = 8000" in content
        # Old constant must be gone
        assert "OPTIMISTIC_UPDATE_TTL = 2000" not in content


class TestReportsResponseDrivenLoading:

    def _read(self):
        return (Path(__file__).parent.parent / "dashboard" / "src" / "components" / "OperationalReportTab.vue").read_text(encoding='utf-8')

    def test_no_blind_settimeout(self):
        content = self._read()
        idx = content.find("function refresh()")
        end = content.find("\nfunction ", idx + 1)
        if end < 0: end = idx + 2000
        body = content[idx:end]
        # The 1500ms blind timeout must be gone
        assert "setTimeout(" not in body, \
            "Loading must clear on actual audit response, not blind timer"

    def test_loading_mirrors_audit_response_state(self):
        content = self._read()
        # Watcher mirrors auth.isLoadingAudit into local isLoading
        assert "auth.isLoadingAudit.value" in content

    def test_non_supervisor_does_not_spin(self):
        """Non-supervisors don't query audit — loading must clear immediately."""
        content = self._read()
        idx = content.find("function refresh()")
        end = content.find("\nfunction ", idx + 1)
        if end < 0: end = idx + 2000
        body = content[idx:end]
        assert "isSupervisor" in body
        assert "isLoading.value = false" in body


class TestReportsDateValidation:

    def _read(self):
        return (Path(__file__).parent.parent / "dashboard" / "src" / "components" / "OperationalReportTab.vue").read_text(encoding='utf-8')

    def test_custom_range_error_helper(self):
        content = self._read()
        assert "function customRangeError" in content
        idx = content.find("function customRangeError")
        body = content[idx:idx + 1500]
        # End-before-start guard
        assert "End date is before start date" in body
        # Format guard
        assert "Number.isFinite" in body
        # Range cap
        assert "5 years" in body or "Range too large" in body

    def test_refresh_skips_when_invalid(self):
        content = self._read()
        idx = content.find("function refresh()")
        end = content.find("\nfunction ", idx + 1)
        if end < 0: end = idx + 2000
        body = content[idx:end]
        assert "customRangeError()" in body
        assert "return" in body

    def test_template_shows_inline_error(self):
        content = self._read()
        assert "dateRangeError" in content
        assert "range-error" in content
        # Date inputs get an .invalid class
        assert "class=\"datetime-input\" :class=\"{ invalid: dateRangeError }\"" in content


# ===================================================================
# Logic replicas
# ===================================================================

class TestDateRangeValidationLogic:

    def validate(self, start, end):
        from datetime import datetime, timedelta
        if not start or not end: return None
        try:
            s = datetime.fromisoformat(start)
            e = datetime.fromisoformat(end)
        except ValueError:
            return 'Invalid date format'
        if e < s: return 'End date is before start date'
        if (e - s) > timedelta(days=5 * 365):
            return 'Range too large (max 5 years)'
        return None

    def test_valid_range(self):
        assert self.validate('2026-01-01T00:00', '2026-01-02T00:00') is None

    def test_end_before_start(self):
        assert self.validate('2026-02-01T00:00', '2026-01-01T00:00') is not None

    def test_too_large(self):
        assert self.validate('2020-01-01T00:00', '2026-01-01T00:00') is not None

    def test_empty_returns_none(self):
        assert self.validate('', '') is None
        assert self.validate('2026-01-01T00:00', '') is None


class TestOptimisticTtlLogic:

    def test_2s_too_tight_for_slow_link(self):
        # Round-trip latency on a slow link: ~2.1s
        # Old TTL: 2000ms — backend status arrives AFTER protection expired
        # New TTL: 8000ms — well within window
        round_trip_ms = 2100
        assert round_trip_ms > 2000, "Documents the old failure mode"
        assert round_trip_ms < 8000, "New TTL covers it"


class TestRunningScriptDeletePromptLogic:

    def build_prompt(self, is_running, is_dirty):
        warnings = []
        if is_running: warnings.append('• The script is currently RUNNING — it will be stopped first.')
        if is_dirty: warnings.append('• You have unsaved edits — they will be lost.')
        if warnings:
            return f"Delete this script?\n\n{chr(10).join(warnings)}\n\nThis cannot be undone."
        return 'Delete this script? This cannot be undone.'

    def test_running_warning_present(self):
        out = self.build_prompt(True, False)
        assert 'RUNNING' in out

    def test_dirty_warning_present(self):
        out = self.build_prompt(False, True)
        assert 'unsaved' in out

    def test_both_warnings(self):
        out = self.build_prompt(True, True)
        assert 'RUNNING' in out and 'unsaved' in out

    def test_default_message(self):
        out = self.build_prompt(False, False)
        assert 'cannot be undone' in out
        assert 'RUNNING' not in out
        assert 'unsaved' not in out


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
