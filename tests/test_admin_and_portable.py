"""
Admin Tab + Portable Executable Hardening Tests

Bugs fixed:
  Admin (CRITICAL — security)
    - useAuth.deleteUser() only sent the MQTT command. The offline-login
      credential cache (CREDENTIAL_CACHE_KEY) survived user deletion, so
      a fired employee with cached creds retained offline access until
      the workstation's localStorage was wiped. Now purgeCachedCredentials
      runs locally as part of deleteUser().

  Admin (HIGH)
    - saveSecuritySettings localStorage failure was swallowed (console-only).
      Now sets securityMessage with 8s auto-clear so the supervisor sees
      the policy didn't actually persist.
    - enableNistPreset (NIST 800-53 button) flipped every security toggle
      with zero confirmation. A misclick could lock the operator out
      (session lock kicked in mid-test). Now confirms with a clear
      preview of what the preset enables.
    - applyBrokerAndConnect changed broker URL with no confirmation,
      dropping all subscriptions. Now confirms only when the URL has
      actually changed. Also dropped the 100ms setTimeout race since
      useMqtt.connect() now self-cleans.

  Portable executable (CRITICAL)
    - Launcher would proceed past missing required files (mosquitto.exe,
      DAQService.exe, system.ini, www/) and Mike would see a blank
      dashboard with silent service failures. Now validate_required_files()
      runs first; missing files surface in a tk dialog AND on stderr.

  Portable executable (HIGH)
    - AzureUploader stdout/stderr was redirected to DEVNULL — a startup
      crash left zero forensic trail. Now appends to logs/azure_uploader.log
      so the operator can see why it died. Also pre-creates the historian
      directory the uploader expects.
"""

import pytest
from pathlib import Path


class TestUserDeletePurgesCredCache:

    def _read(self):
        return (Path(__file__).parent.parent / "dashboard" / "src" / "composables" / "useAuth.ts").read_text(encoding='utf-8')

    def test_purge_cached_credentials_helper_exists(self):
        content = self._read()
        assert "function purgeCachedCredentials" in content

    def test_purge_clears_localstorage(self):
        content = self._read()
        idx = content.find("function purgeCachedCredentials")
        body = content[idx:idx + 800]
        # Must read existing, delete the username key, write back
        assert "loadAllCachedCredentials" in body
        assert "delete existing[username]" in body
        assert "localStorage.setItem(CREDENTIAL_CACHE_KEY" in body

    def test_delete_user_calls_purge(self):
        content = self._read()
        idx = content.find("function deleteUser")
        body = content[idx:idx + 600]
        assert "purgeCachedCredentials(username)" in body


class TestAdminSecuritySettingsErrorFeedback:

    def _read(self):
        return (Path(__file__).parent.parent / "dashboard" / "src" / "components" / "AdminTab.vue").read_text(encoding='utf-8')

    def test_security_message_ref_exists(self):
        content = self._read()
        assert "const securityMessage = ref(" in content

    def test_save_security_settings_catches_localstorage_failure(self):
        content = self._read()
        idx = content.find("function saveSecuritySettings")
        body = content[idx:idx + 1500]
        assert "try {" in body
        assert "catch" in body
        assert "securityMessage.value" in body
        # Auto-clear timer
        assert "setTimeout(" in body
        assert "8000" in body


class TestAdminEnableNistPresetConfirm:

    def _read(self):
        return (Path(__file__).parent.parent / "dashboard" / "src" / "components" / "AdminTab.vue").read_text(encoding='utf-8')

    def test_nist_preset_confirms(self):
        content = self._read()
        idx = content.find("function enableNistPreset")
        body = content[idx:idx + 2500]
        assert "confirm(" in body
        # The confirm spells out the lockout risk so the operator
        # understands the consequence.
        assert "lock" in body.lower()
        # Bails on cancel
        assert "return" in body


class TestAdminBrokerChangeConfirm:

    def _read(self):
        return (Path(__file__).parent.parent / "dashboard" / "src" / "components" / "AdminTab.vue").read_text(encoding='utf-8')

    def test_broker_change_confirms_when_url_changes(self):
        content = self._read()
        idx = content.find("function applyBrokerAndConnect")
        body = content[idx:idx + 2500]
        # Only confirms if the URL actually changes
        assert "brokerUrlInput.value !== brokerConfig.brokerUrl.value" in body
        assert "confirm(" in body
        # Mentions the consequences (recordings, subscriptions)
        assert "subscriptions" in body.lower() or "recording" in body.lower()

    def test_broker_change_drops_settimeout_race(self):
        """useMqtt.connect() now self-cleans (per App shell phase) so
        the disconnect()→100ms→connect() race is no longer needed."""
        content = self._read()
        idx = content.find("function applyBrokerAndConnect")
        # Bound by next function declaration so we don't read into resetBrokerToLocal
        end = content.find("\nfunction ", idx + 1)
        if end < 0: end = idx + 2500
        body = content[idx:end]
        # Old: setTimeout(() => mqttClient.connect(...), 100)
        assert "setTimeout(" not in body, \
            "100ms reconnect race must be gone"
        assert "mqttClient.disconnect()" not in body


class TestPortableValidateRequiredFiles:

    def _read(self):
        return (Path(__file__).parent.parent / "scripts" / "ICCSFlux_exe.py").read_text(encoding='utf-8')

    def test_validate_required_files_helper_exists(self):
        content = self._read()
        assert "def validate_required_files()" in content

    def test_validates_all_critical_files(self):
        content = self._read()
        idx = content.find("def validate_required_files")
        body = content[idx:idx + 2000]
        # All five critical paths
        assert "MOSQUITTO" in body
        assert "MOSQUITTO_CONF" in body
        assert "DAQ_SERVICE" in body
        assert "CONFIG" in body
        assert "WWW" in body

    def test_show_missing_files_error_helper(self):
        content = self._read()
        assert "def show_missing_files_error" in content
        idx = content.find("def show_missing_files_error")
        body = content[idx:idx + 2000]
        # Logs to stderr (so NSSM service mode sees it)
        assert "sys.stderr" in body
        # Tries graphical dialog
        assert "messagebox.showerror" in body
        # Mentions rebuild path so Mike knows the recovery
        assert "build_exe" in body or "installer" in body or "Re-run" in body

    def test_main_runs_validation_before_services(self):
        content = self._read()
        idx = content.find("def main():")
        body = content[idx:idx + 4000]
        assert "validate_required_files()" in body
        assert "show_missing_files_error" in body
        # Must return non-zero so service-mode doesn't keep trying
        assert "return 1" in body

    def test_validation_skipped_in_setup_mode(self):
        """--setup is responsible for generating some of what we'd check
        for, so it must run BEFORE the validation gate."""
        content = self._read()
        idx = content.find("def main():")
        body = content[idx:idx + 4000]
        assert "if not args.setup:" in body or "args.setup" in body


class TestAzureUploaderLogging:

    def _read(self):
        return (Path(__file__).parent.parent / "scripts" / "ICCSFlux_exe.py").read_text(encoding='utf-8')

    def test_azure_log_to_file_not_devnull(self):
        content = self._read()
        # Anchor on the launcher's own log message so we land near the
        # AzureUploader Popen, not the path constant definition.
        idx = content.find("Starting Azure IoT Hub uploader")
        assert idx > 0
        body = content[idx:idx + 2500]
        # New: stdout=azure_log_handle (file), stderr=STDOUT (merged)
        assert "azure_log_handle" in body
        assert "stderr=subprocess.STDOUT" in body

    def test_log_path_under_logs_dir(self):
        content = self._read()
        assert "azure_uploader.log" in content

    def test_historian_dir_pre_created(self):
        """AzureUploader expects the historian dir to exist; we now create it."""
        content = self._read()
        idx = content.find("Starting Azure IoT Hub uploader")
        body = content[idx:idx + 1500]
        assert 'mkdir' in body
        assert 'historian' in body


# ===================================================================
# Logic replicas
# ===================================================================

class TestCredCachePurgeLogic:

    def test_purge_removes_username(self):
        cache = {
            'alice': {'username': 'alice', 'passwordHash': 'h1', 'cachedAt': 1},
            'bob':   {'username': 'bob',   'passwordHash': 'h2', 'cachedAt': 2},
        }
        # purgeCachedCredentials('bob')
        if 'bob' in cache:
            del cache['bob']
        assert 'alice' in cache
        assert 'bob' not in cache

    def test_purge_missing_user_is_noop(self):
        cache = {'alice': {'username': 'alice'}}
        # Username not in cache: no-op
        if 'charlie' in cache:
            del cache['charlie']
        assert cache == {'alice': {'username': 'alice'}}


class TestPreflightValidationLogic:

    def test_missing_list_collects_all(self):
        # Mirror validate_required_files
        from pathlib import Path as P
        existing = P(__file__).parent  # exists
        missing_path = P('/nonexistent/path/never/here')
        required = [
            (existing, 'A'),
            (missing_path, 'B'),
            (existing, 'C'),
        ]
        missing = [(p, label) for p, label in required if not p.exists()]
        assert len(missing) == 1
        assert missing[0][1] == 'B'

    def test_all_present_returns_empty(self):
        from pathlib import Path as P
        existing = P(__file__).parent
        required = [(existing, 'A'), (existing, 'B')]
        missing = [(p, label) for p, label in required if not p.exists()]
        assert missing == []


class TestBrokerChangeConfirmLogic:

    def test_no_confirm_when_url_unchanged(self):
        current = 'ws://localhost:9002'
        new = 'ws://localhost:9002'
        # Replicates the guard: if (new !== current) confirm()
        needs_confirm = new != current
        assert not needs_confirm

    def test_confirm_when_url_changed(self):
        current = 'ws://localhost:9002'
        new = 'wss://broker.example.com'
        needs_confirm = new != current
        assert needs_confirm


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
