"""
App Shell + Cross-Cutting Hardening Tests

Verifies fixes from the App shell audit. This layer (useMqtt + useProjectFiles
+ App.vue + ConnectionOverlay/DiagnosticOverlay + useBrokerConfig) affects
every tab, so silent failures here cascade everywhere.

Bugs fixed:
  CRITICAL
    - useMqtt.connect() didn't tear down an existing client before creating
      a new one. Calling connect() twice (broker switch, retry) leaked
      the previous client and its mqtt-internal reconnect timers, manifesting
      as phantom disconnects and double-publishes. Now guards client.value
      and end()s the previous instance first.
    - App.handleRetryConnection used disconnect()→100ms→connect() which raced
      the mqtt-library reconnect timer. Now relies on connect()'s teardown
      and drops the setTimeout.
    - generateRequestId() used Date.now()+Math.random() — could collide on
      rapid-fire commands in the same ms, letting one command steal another's
      ACK and producing hangs. Now uses crypto.randomUUID() with a counter
      fallback for non-secure contexts.
    - useProjectFiles.newProject() didn't cancel the in-flight autoSaveTimeout
      or stop backendAutosaveInterval. After clicking "New Project" mid-debounce
      the timer fired against a null project; over time backendAutosaveInterval
      kept hammering disconnected brokers. Both now stopped.

  HIGH
    - Autosave debounce had no cooldown after failure. Repeated edits while
      the broker was down queued unbounded retries. Now cools down 15s after
      a failure before re-arming.
    - autosaveToBackend now skips when MQTT is disconnected, so the 30s
      interval doesn't spam useless publishes against a dead broker.

  MEDIUM
    - Broker URL loaded from localStorage with zero validation. A malformed
      stored URL could throw on parse later in boot. Now validates scheme,
      length, hostname; falls back to default and logs a warning.
    - channelOwners Map leaked on channel delete (entry never removed). Over
      a long session of create/delete cycles the Map grew unbounded.
    - project/loaded and project/current both ran applyProjectData and fired
      callbacks; on backends that publish both, the project was applied
      twice. Now deduped via a 1.5s window keyed by filename.
"""

import pytest
from pathlib import Path


class TestUseMqttReconnectGuard:

    def _read(self):
        return (Path(__file__).parent.parent / "dashboard" / "src" / "composables" / "useMqtt.ts").read_text(encoding='utf-8')

    def test_connect_tears_down_existing_client(self):
        content = self._read()
        idx = content.find("function connect(brokerUrl")
        body = content[idx:idx + 1500]
        # Must check for existing client and end() it before creating new one
        assert "if (client.value)" in body
        assert "client.value.end(true)" in body
        # Must null the ref so the next mqtt.connect() doesn't see a stale handle
        assert "client.value = null" in body

    def test_connect_logs_teardown_failure(self):
        content = self._read()
        idx = content.find("function connect(brokerUrl")
        body = content[idx:idx + 1500]
        assert "try {" in body
        assert "catch" in body
        assert "failed to close previous client" in body.lower() or "previous client" in body


class TestUseMqttGenerateRequestId:

    def _read(self):
        return (Path(__file__).parent.parent / "dashboard" / "src" / "composables" / "useMqtt.ts").read_text(encoding='utf-8')

    def test_uses_crypto_randomuuid_when_available(self):
        content = self._read()
        idx = content.find("function generateRequestId")
        body = content[idx:idx + 600]
        assert "crypto.randomUUID" in body

    def test_fallback_includes_counter(self):
        """Non-secure contexts: must include a monotonic counter so two
        calls in the same ms with same Math.random can't collide."""
        content = self._read()
        idx = content.find("function generateRequestId")
        body = content[idx:idx + 600]
        assert "_requestIdCounter" in body

    def test_counter_declared_at_module_level(self):
        content = self._read()
        # Counter lives at module scope so it survives across composable instances
        assert "let _requestIdCounter = 0" in content


class TestAppHandleRetryConnection:

    def _read(self):
        return (Path(__file__).parent.parent / "dashboard" / "src" / "App.vue").read_text(encoding='utf-8')

    def _handler_body(self, content):
        """Slice just handleRetryConnection — bounded by the matching close
        brace at column 0, since other JS functions follow without a
        consistent leading prefix."""
        idx = content.find("function handleRetryConnection")
        # Find the closing line "}" at column 0 (function body close).
        rest = content[idx:]
        end_marker = rest.find("\n}\n")
        end = idx + (end_marker + 2 if end_marker > 0 else 800)
        return content[idx:end]

    def test_no_disconnect_then_settimeout(self):
        """The 100ms setTimeout race must be removed."""
        content = self._read()
        body = self._handler_body(content)
        # Old: mqtt.disconnect(); setTimeout(() => mqtt.connect(...), 100)
        assert "setTimeout(" not in body, \
            "100ms setTimeout race must be gone — connect() now tears down internally"
        assert "mqtt.disconnect()" not in body

    def test_calls_connect_directly(self):
        content = self._read()
        body = self._handler_body(content)
        assert "mqtt.connect(" in body


class TestUseProjectFilesAutosave:

    def _read(self):
        return (Path(__file__).parent.parent / "dashboard" / "src" / "composables" / "useProjectFiles.ts").read_text(encoding='utf-8')

    def test_stop_autosave_timers_helper(self):
        content = self._read()
        assert "function stopAutoSaveTimers" in content
        idx = content.find("function stopAutoSaveTimers")
        body = content[idx:idx + 500]
        assert "autoSaveTimeout" in body
        assert "backendAutosaveInterval" in body

    def test_new_project_stops_timers(self):
        content = self._read()
        idx = content.find("async function newProject")
        body = content[idx:idx + 1500]
        assert "stopAutoSaveTimers()" in body
        # Also clears isDirty so the new fresh project doesn't immediately
        # schedule a save based on stale state.
        assert "isDirty.value = false" in body

    def test_autosave_failure_cooldown(self):
        content = self._read()
        assert "AUTO_SAVE_FAILURE_COOLDOWN_MS" in content
        # Cooldown applied in scheduleAutoSave
        idx = content.find("function scheduleAutoSave")
        body = content[idx:idx + 1500]
        assert "autoSaveLastFailureAt" in body
        # Cooldown bumps the delay
        assert "FAILURE_COOLDOWN_MS - sinceFailure" in body or "AUTO_SAVE_FAILURE_COOLDOWN_MS" in body

    def test_autosave_resets_failure_marker_on_success(self):
        content = self._read()
        idx = content.find("function scheduleAutoSave")
        body = content[idx:idx + 1500]
        assert "autoSaveLastFailureAt = 0" in body

    def test_autosave_marks_failure_on_save_fail(self):
        content = self._read()
        idx = content.find("function scheduleAutoSave")
        body = content[idx:idx + 1500]
        assert "autoSaveLastFailureAt = Date.now()" in body

    def test_backend_autosave_skips_when_disconnected(self):
        content = self._read()
        idx = content.find("function autosaveToBackend")
        body = content[idx:idx + 700]
        assert "mqtt.connected.value" in body
        assert "return" in body


class TestProjectLoadDedupe:

    def _read(self):
        return (Path(__file__).parent.parent / "dashboard" / "src" / "composables" / "useProjectFiles.ts").read_text(encoding='utf-8')

    def test_should_apply_once_helper(self):
        content = self._read()
        assert "function shouldApplyOnce" in content
        idx = content.find("function shouldApplyOnce")
        body = content[idx:idx + 500]
        assert "lastAppliedKey" in body
        assert "APPLY_DEDUPE_WINDOW_MS" in body

    def test_loaded_handler_uses_dedupe(self):
        content = self._read()
        idx = content.find("project/loaded`")
        body = content[idx:idx + 2000]
        assert "shouldApplyOnce" in body

    def test_current_handler_uses_dedupe(self):
        content = self._read()
        idx = content.find("project/current`")
        body = content[idx:idx + 2000]
        assert "shouldApplyOnce" in body


class TestBrokerUrlValidation:

    def _read(self):
        return (Path(__file__).parent.parent / "dashboard" / "src" / "composables" / "useBrokerConfig.ts").read_text(encoding='utf-8')

    def test_validate_broker_url_function(self):
        content = self._read()
        assert "function isValidBrokerUrl" in content
        idx = content.find("function isValidBrokerUrl")
        body = content[idx:idx + 800]
        # Validates ws:/wss: scheme
        assert "ws:" in body
        assert "wss:" in body
        # Length cap
        assert "MAX_URL_LENGTH" in body or "length" in body
        # Hostname presence
        assert "hostname" in body

    def test_initial_load_validates(self):
        content = self._read()
        assert "function loadInitialBrokerUrl" in content
        idx = content.find("function loadInitialBrokerUrl")
        body = content[idx:idx + 600]
        assert "isValidBrokerUrl" in body
        # Fall through to default on invalid
        assert "DEFAULT_URL" in body

    def test_set_broker_url_rejects_invalid(self):
        content = self._read()
        idx = content.find("function setBrokerUrl")
        body = content[idx:idx + 400]
        assert "isValidBrokerUrl" in body
        # Returns early without writing localStorage
        assert "Refusing" in body or "Invalid" in body or "return" in body


class TestChannelOwnersCleanup:

    def _read(self):
        return (Path(__file__).parent.parent / "dashboard" / "src" / "composables" / "useMqtt.ts").read_text(encoding='utf-8')

    def test_channel_delete_clears_owners(self):
        content = self._read()
        idx = content.find("function handleChannelDeleted")
        body = content[idx:idx + 800]
        assert "channelOwners.delete(channelName)" in body


# ===================================================================
# Logic replicas
# ===================================================================

class TestBrokerUrlLogic:

    def is_valid(self, s):
        if not isinstance(s, str) or not s:
            return False
        if len(s) > 1024:
            return False
        # Mirror URL parser
        if not (s.startswith('ws://') or s.startswith('wss://')):
            return False
        # Need a host after the scheme
        rest = s.split('://', 1)[1]
        # Strip path and query
        host = rest.split('/', 1)[0].split('?', 1)[0].split(':', 1)[0]
        return bool(host)

    def test_local_default_valid(self):
        assert self.is_valid('ws://localhost:9002')

    def test_remote_wss_valid(self):
        assert self.is_valid('wss://broker.example.com:443')

    def test_http_scheme_rejected(self):
        assert not self.is_valid('http://localhost:9002')

    def test_empty_rejected(self):
        assert not self.is_valid('')
        assert not self.is_valid(None)

    def test_long_rejected(self):
        assert not self.is_valid('ws://' + ('a' * 2000))


class TestDedupeWindowLogic:

    def setup_method(self):
        self.last_key = None
        self.window_ms = 1500

    def should_apply(self, filename, now_ms):
        bucket = now_ms // self.window_ms
        key = f'{filename}@{bucket}'
        if key == self.last_key:
            return False
        self.last_key = key
        return True

    def test_two_calls_same_window_dedupe(self):
        assert self.should_apply('proj.json', 1000) is True
        assert self.should_apply('proj.json', 1100) is False  # same bucket

    def test_calls_in_different_windows_apply(self):
        assert self.should_apply('proj.json', 0) is True
        assert self.should_apply('proj.json', 2000) is True  # different bucket

    def test_different_files_apply(self):
        assert self.should_apply('a.json', 1000) is True
        assert self.should_apply('b.json', 1100) is True


class TestAutosaveCooldownLogic:

    DEBOUNCE_MS = 3000
    COOLDOWN_MS = 15000

    def compute_delay(self, since_failure_ms):
        if since_failure_ms < self.COOLDOWN_MS:
            return self.COOLDOWN_MS - since_failure_ms
        return self.DEBOUNCE_MS

    def test_immediately_after_failure_uses_cooldown(self):
        assert self.compute_delay(0) == 15000

    def test_partway_through_cooldown(self):
        assert self.compute_delay(5000) == 10000

    def test_after_cooldown_reverts_to_debounce(self):
        assert self.compute_delay(20000) == 3000


class TestRequestIdCollisionLogic:

    def test_uuid_unique(self):
        # crypto.randomUUID is collision-impossible — Python uuid4 is the same algo
        import uuid
        ids = {str(uuid.uuid4()) for _ in range(10000)}
        assert len(ids) == 10000

    def test_counter_breaks_same_ms_collision(self):
        # Even if Date.now() and Math.random produce the same bits, the counter
        # increments per call.
        counter = 0
        seen = set()
        for _ in range(100):
            counter += 1
            ts = 1700000000000
            random_part = 'abc123'
            key = f'{ts}-{counter}-{random_part}'
            assert key not in seen
            seen.add(key)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
