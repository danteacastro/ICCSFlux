# NISystem Industrial Standards Audit Report

**Date:** 2026-02-01
**Project:** NISystem - Industrial Control System (DAQ, cRIO, Opto22, Modbus, EtherNet/IP, OPC UA)
**Classification:** Safety-Critical Industrial Control System
**Scope:** Full codebase - Python backend, TypeScript/Vue frontend, configuration, deployment

---

## Executive Summary

| Area | CRITICAL | HIGH | MEDIUM | LOW | Total |
|------|----------|------|--------|-----|-------|
| Python Backend | 6 | 16 | 8 | 3 | 33 |
| Frontend (TS/Vue) | 15 | 27 | 65 | 7 | 114 |
| Config / Deploy / Infra | 7 | 9 | 26 | 0 | 42 |
| **TOTAL** | **28** | **52** | **99** | **10** | **189** |

**Overall Risk Rating: HIGH** - System requires significant hardening before production deployment in regulated environments.

---

## Changes Already Completed (Sessions 1-3)

The following categories were already addressed in prior sessions:

1. **Error Handling** - Fixed 27 bare `except: pass` blocks across Python backend
2. **Hardware Safety** - Fixed terminal configuration defaults, added safety checks
3. **Security** - Identified and documented MQTT security gaps
4. **Type Safety** - Eliminated all 412 `as any` type assertions across 48 TypeScript/Vue files (now zero)
5. **MQTT Security Audit** - Comprehensive findings documented below

### Session 4 Fixes Applied (2026-02-01)

**Python Backend - CRITICAL fixes:**

| ID | Fix | File |
|----|-----|------|
| PY-C1 | Replaced pattern-matching sandbox with AST-based validation (`ast.parse`, node walker blocks imports/dunder/dangerous calls) | `script_engine.py` |
| PY-C3 | Added `_output_channels` set + `set_output_channels()`. Safety actions now validate target channel exists before write | `safety.py` |
| PY-C4 | **Not a bug** - User confirmed cRIO continuing to run IS the desired safety behavior | N/A |
| PY-C5 | **Not a bug** - `TerminalConfiguration.DEFAULT` is correct for cRIO C-Series (per CLAUDE.md) | N/A |

**Python Backend - HIGH fixes:**

| ID | Fix | File |
|----|-----|------|
| PY-H3 | Added `VALID_TC_TYPES` set validation, logs WARNING for invalid thermocouple types | `hardware.py` |
| PY-H4 | Added `_failed_channels` set to track task creation failures | `hardware.py` |
| PY-H5 | Fixed socket resource leak with `with` context manager | `crio_node.py` |
| PY-H6 | Added `math.isinf(value)` check in `_validate_output_value` | `hardware.py` |
| PY-H7 | Added `[AUDIT]` prefix logging for output writes and alarm acknowledgments | `crio_node.py` |
| PY-H8 | Added `publish_critical()` method with QoS=1 for guaranteed delivery | `mqtt_interface.py` |
| PY-H11 | Added SIGTERM/SIGINT signal handlers for graceful shutdown | `crio_node.py` |
| PY-H12 | Added validation for `momentary_pulse_ms` (0-3600000) and `pulse_duty_cycle` (0-100) | `config.py` |
| PY-H13 | Added `exc_info=True` to error logging for full tracebacks | `safety.py` |
| PY-H14 | Added `threading.Lock` (`_output_lock`) for thread-safe `_output_values` access | `hardware.py` |
| PY-H15 | Changed OPC UA subscription cleanup from `pass` to logging warning | `opcua_source.py` |

**Python - False positives identified (no fix needed):**

| ID | Reason |
|----|--------|
| PY-H1 | `_validate_output_value()` IS called at line 840 before all writes including pulse |
| PY-H2 | No division-by-zero - formula is `eng_min + (normalized * span)`, returns constant when span=0 |
| PY-H10 | Python `for/else` correctly SKIPS alarm config when `break` triggered by invalid ordering |

**Frontend fixes:**

| ID | Fix | File |
|----|-----|------|
| FE-C1 | Added defense-in-depth validation in `setOutput()`: NaN/Infinity rejection, digital 0/1 enforcement, limit warnings | `useMqtt.ts` |
| FE-C3 | Added per-channel trailing-edge throttle (50ms) to coalesce rapid slider changes | `useMqtt.ts` |
| FE-C12 | Added supervisor role check to `addSafetyAction()` | `useSafety.ts` |
| FE-C14 | Sanitized `fillColor` with regex validation before SVG insertion | `PidCanvas.vue` |
| FE-C15 | Added supervisor role check to `bypassInterlock()` | `useSafety.ts` |
| FE-H8 | Added supervisor role check + audit event logging to `removeInterlock()` | `useSafety.ts` |

**Frontend - False positives / design choices (no fix needed):**

| ID | Reason |
|----|--------|
| FE-C2, C4, C5 | `tripSystem`/`executeSafetyAction` are programmatic - confirmations would BREAK automated safety responses |
| FE-C6 | Line 556 already has `if (preRange !== 0)` guard |
| FE-C7 | `DEFAULT_GUEST` is development mode feature with view-only permissions |
| FE-C8 | Expression regex blocks alphabetic chars; channel names already replaced with numeric values |
| FE-C9, C13 | `JSON.parse` schema validation on every MQTT message is overengineering; backend is authority |
| FE-C10, C11 | Permission guards in useMqtt would create circular dependency with useAuth; enforced at component level + backend |
| FE-H9 | Single-click digital output is standard industrial HMI pattern (FactoryTalk, Wonderware, Ignition). Protection via role/session/interlocks, not click friction. |

**MQTT Security — Zero-Config Implementation (previously deferred):**

| ID | Resolution | File |
|----|-----------|------|
| CFG-C1 | `per_listener_settings true` — MQTT TCP (1883): `allow_anonymous false` + password_file + ACL. WebSocket (9002, localhost): `allow_anonymous true` (dashboard is pre-built, credentials can't be baked in; localhost binding is the security boundary). | `mosquitto.conf` |
| CFG-C2 | `0.0.0.0` binding kept intentionally — cRIO needs access over USB Ethernet. WebSocket restricted to `127.0.0.1`. Physical isolation is the security boundary. | `mosquitto.conf` |
| CFG-C3 | **TLS intentionally skipped** — MQTT broker runs on localhost, cRIO on dedicated physical link. TLS would require certificate management incompatible with zero-config. | N/A |
| CFG-C4 | Same as CFG-C2 — physically isolated network | N/A |
| CFG-C5 | ACL file enforces role-based topic access: `backend` (full), `dashboard` (read + control write) | `mosquitto_acl.conf` |
| CFG-C6 | Credentials auto-generated on first run by `scripts/mqtt_credentials.py` — PBKDF2-SHA512 hashed password file. Dashboard `.env.local` and cRIO args set automatically. | `mqtt_credentials.py`, `mosquitto_passwd` |
| CFG-C7 | Hardcoded paths replaced with relative paths in mosquitto.conf. `start.bat` uses `%~dp0` for portability. | `mosquitto.conf`, `start.bat` |
| CFG-H1–H3 | Covered by CFG-C1 through CFG-C7 above | — |
| CFG-H5 | cRIO broker host passed via `--broker` CLI arg from deploy script | `deploy_crio_v2.bat` |
| CFG-H6 | Auth prevents unauthorized access. Physical isolation prevents network exposure. | `mosquitto.conf` |
| CFG-H9 | Old `mosquitto_secure.conf` with hardcoded paths deleted. Production config now in `mosquitto.conf`. | Deleted `mosquitto_secure.conf` |
| PY-C2 | Credentials auto-generated (not hardcoded). JSON store is gitignored. Env vars pass credentials to services at runtime. | `mqtt_credentials.py`, `.gitignore` |

**Zero-config flow:** `start.bat` → `mqtt_credentials.py` (generates on first run) → sets env vars → launches mosquitto + DAQ service + dashboard. `deploy_crio_v2.bat` reads credentials and passes `--mqtt-user`/`--mqtt-pass` to cRIO runner.

**Portable build:** `ICCSFlux.exe` generates credentials at runtime, passes env vars to `DAQService.exe`. Dashboard connects anonymously via WebSocket (localhost, `per_listener_settings true`). `build_exe.py` temporarily removes `.env.local` during `npm run build` to prevent dev credentials from being baked into the portable distribution. DAQ service reads credential file directly as fallback (no env vars needed for NSSM Windows services).

### Session 4 Continued - Remaining CRITICAL + HIGH Fixes

**Python Backend - Additional CRITICAL:**

| ID | Fix | File |
|----|-----|------|
| PY-C6 | Added retry logic (max 3 retries with backoff) to MQTT publish queue thread. Failed messages re-queued instead of dropped. Queue-full protection for retries. | `daq_service.py` |

**Python Backend - Additional HIGH:**

| ID | Fix | File |
|----|-----|------|
| PY-H9 | Added `_validate_config()` function: validates required fields (mqtt_broker, node_id), optional field types, and channels dict structure. Logs errors/warnings but doesn't crash. | `crio_node.py` |
| PY-H16 | Added `exc_info=True` to discovery error logging. Added success flag checking at both scan callsites in daq_service.py. | `device_discovery.py`, `daq_service.py` |

**crio_node.py bonus improvements (defense-in-depth):**
- Communication watchdog implemented: `_check_comm_watchdog()` transitions to safe state if no commands received within `comm_watchdog_timeout_s`
- Critical commands (stop, safe_state, alarm) never dropped from full queue - non-critical commands evicted instead
- Main loop: 10 consecutive errors now triggers `set_safe_state()` + exits loop (requires manual restart)
- Script shutdown timeout (5s) prevents hanging during stop

**Frontend - Additional HIGH:**

| ID | Fix | File |
|----|-----|------|
| FE-H1 | Message handler split into per-category try-catch blocks (channels, status, config, discovery, alarms, recording, watchdog, variables, heartbeat/ack, SOE). One failure no longer kills all routing. | `useMqtt.ts` |
| FE-H2 | Added `console.warn` when physical-to-TAG mapping falls back to physical name | `useMqtt.ts` |
| FE-H3 | Added optional chaining / null coalescing for all `channelConfigs.value[key]` lookups | `useMqtt.ts` |
| FE-H4 | Added null/type guards in `evaluateConditionRaw()`: condition object check, channel existence check, numeric value validation, NaN guards | `useSafety.ts` |
| FE-H6 | Moved `connected.value = true` to AFTER subscriptions are issued | `useMqtt.ts` |
| FE-H10 | Added project file structure validation: type check, name check, channels/layout/safety/scripts field type validation | `useProjectManager.ts` |

**Frontend - FE-H12-H27 bundle:**

| Finding | Fix | File |
|---------|-----|------|
| Alarm processing error handlers | Wrapped `handleBackendAlarm` in try-catch, extracted to `_processBackendAlarm` | `useSafety.ts` |
| Stale data on disconnect | Clear `channelValues`, `systemStatus`, `channelOwners` on MQTT disconnect | `useMqtt.ts` |
| Channel ownership unbounded growth | `channelOwners.clear()` on disconnect | `useMqtt.ts` |
| Pending commands orphaned timers | Resolve all pending commands with error + clear map on disconnect | `useMqtt.ts` |
| cRIO status payload assertion | Added type guard: validate `parsed.online` is boolean before cast | `useCrio.ts` |
| Heartbeat payload assertion | Added type guard: validate `parsed.state` is string before cast | `useCrio.ts` |

### Final HIGH Fixes

| ID | Fix | File |
|----|-----|------|
| CFG-H7 | Created `requirements-lock.txt` with pinned dependency versions from venv (`pip freeze`). Frontend already has `package-lock.json`. | `requirements-lock.txt` |
| FE-H9 | **Design choice** - Single-click digital output is standard industrial HMI pattern (FactoryTalk, Wonderware, Ignition). Protection via role/session/interlocks. | N/A |
| FE-H11 | Replaced `any` callback payloads with typed interfaces: `DiscoveryCallbackPayload`, `ConfigUpdateCallbackPayload`, `RecordingCallbackPayload`, `AlarmCallbackPayload`, `SystemUpdateCallbackPayload`, `CrioCallbackPayload`. Generic `subscribe()` uses `unknown`. | `types/index.ts`, `useMqtt.ts` |

### MEDIUM Fixes Applied

**Python Backend - MEDIUM:**

| ID | Fix | File |
|----|-----|------|
| PY-M1 | Critical command payloads (`/output`, `/stop`, `/safety/`, `/alarm/`) now logged at INFO (not DEBUG). Routine commands stay at DEBUG. | `crio_node.py` |
| PY-M2 | Config file saved with `os.chmod(0o600)` on non-Windows (owner-only permissions) | `crio_node.py` |
| PY-M5 | Default script timeout changed from 300s to 30s (`DEFAULT_SCRIPT_TIMEOUT_S`). Timeout logged at script start. State machine bare `except:pass` blocks now log errors. | `script_manager.py` |
| PY-M6 | Audit trail files restricted to `os.chmod(0o600)` on non-Windows | `audit_trail.py` |
| PY-M7 | 12 magic numbers extracted to named constants: `SLOW_READ_INTERVAL_S`, `MIN_BUFFER_SAMPLES`, `BUFFER_DURATION_S`, `RESISTANCE_EXCITATION_A`, `DI_READ_TIMEOUT_S`, `AI_TIMED_READ_TIMEOUT_S`, `AI_ONDEMAND_READ_TIMEOUT_S`, `AI_SLOW_READ_TIMEOUT_S`, `CTR_READ_TIMEOUT_S`, `DEFAULT_MIN_PERIOD_S`, `DEFAULT_MAX_PERIOD_S` | `hardware.py` |
| PY-M8 | Thermocouple type default log level changed from DEBUG to WARNING with message about verification | `config.py` |

**Config / Infrastructure - MEDIUM:**

| ID | Fix | File |
|----|-----|------|
| CFG-H8 | Added `config/projects/backups/` directory exclusion to `.gitignore` | `.gitignore` |
| CFG-M (secrets) | Added `mosquitto_passwd`, `**/users.json`, `.env.production` to `.gitignore` credential exclusions | `.gitignore` |

**Frontend - MEDIUM:**

| ID | Fix | File |
|----|-----|------|
| FE-M (accessibility) | Added `aria-label` to START, STOP, RECORD, session toggle, add widget, edit mode, P&ID mode buttons. Added `aria-hidden="true"` to decorative SVGs. Added `role="switch"` + `aria-checked` to session toggle. Added `aria-live="polite"` to recording timer. Added `aria-pressed` to edit/P&ID toggles. | `ControlBar.vue` |
| FE-M (session expiry) | Added `SESSION_MAX_AGE_MS` (24h). Persisted sessions include `_persistedAt` timestamp and are discarded on reload if expired. | `useAuth.ts` |
| FE-M (XSS) | Added security documentation for `v-html` SVG rendering — content sourced only from trusted built-in symbol library, not user input. | `SvgSymbolWidget.vue` |

### Additional Fixes (Remaining MEDIUM + LOW)

**Python Backend:**

| ID | Fix | File |
|----|-----|------|
| PY-M3 | `InterlockCondition.from_dict()` now returns `None` (and logs error) for invalid operators, unknown condition types, or missing channels. Callers filter out `None` results. | `safety_manager.py` |
| PY-M4 | Console `exec()` namespace now sets `'__builtins__': {}` to prevent access to `__import__`, `open()`, `exec()` etc. Removed `getattr`, `setattr`, `hasattr`, `type`, `dir`, `help` (sandbox escape vectors). | `daq_service.py` |
| CFG-M (rates) | `scan_rate_hz` and `publish_rate_hz` validated in `NodeConfig.from_dict()` — values ≤ 0 rejected with warning, default to 4.0 Hz. | `crio_node.py` |
| PY-L1 | Mock hardware now supports fault injection: `_simulate_read_error` (one-shot RuntimeError), `_simulate_write_error` (returns False), `_simulate_nan_channels` (set of channels returning NaN), `_simulate_start_failure` (start returns False). | `hardware.py` |

**Frontend:**

| ID | Fix | File |
|----|-----|------|
| FE-M (idle timeout) | Added 30-minute idle timeout. Monitors `mousedown`, `keydown`, `touchstart`, `scroll` events. Auto-logout on expiry. Timer starts/stops with auth state changes. | `useAuth.ts` |
| FE-M (logging) | Converted 149 `console.log` → `console.debug` across 8 composable files. Kept `console.log` only for critical connection state transitions (MQTT connected/reconnecting) and auth events. `console.warn`/`console.error` unchanged. | Multiple composables |

### Final Code Fixes (Remaining HIGH + MEDIUM)

**Frontend:**

| ID | Fix | File |
|----|-----|------|
| FE-H5 | Expression evaluator: added checks blocking property access (`/\.\s*[a-zA-Z_]/`) and empty function calls (`/\(\s*\)/`) before `new Function()` eval | `useSafety.ts` |
| FE-H (login) | Login timeout now cleans up `onAuthChange` callback on expiry. `isLoggingIn` explicitly reset in both success and timeout paths. Improved error message. | `useAuth.ts` |
| FE-H (permissions) | Added `canDo(permission)` reactive computed wrapper for `hasPermission()`. Fixed misleading comment about reactivity. | `useAuth.ts` |
| FE-M (clear all) | "Clear All" alarms button now shows `confirm()` dialog with alarm count before clearing | `SafetyTab.vue` |

**Python Backend:**

| ID | Fix | File |
|----|-----|------|
| CFG-M (alarm ranges) | `ChannelConfig.__post_init__()` validates alarm limit ordering (lolo < lo < hi < hihi). Invalid ordering disables alarms with error log. Negative deadband/delay clamped to 0. | `config.py` |
| CFG-M (interlock xval) | `add_interlock()` cross-validates condition channels against current hardware config. Logs warning for channels not found. | `safety_manager.py` |

**Documentation:**

| ID | Fix | File |
|----|-----|------|
| CFG-M (recovery) | Expanded Backup & Recovery section: added RTO/RPO targets (30min/24h), full system recovery procedure, cRIO recovery, project recovery, post-recovery checklist | `ICCSFlux_Administrator_Guide.md` |
| CFG-M (NI-DAQmx) | Added NI-DAQmx driver install URL and instructions to requirements.txt | `requirements.txt` |
| CFG-M (systemd) | Already exists — all 3 `.service` files have `Restart=always`, `RestartSec=5`. `crio_service.service` also has `WatchdogSec=30` + `MemoryMax=256M`. | N/A |

**Skipped (not worth fixing):**

| ID | Reason |
|----|--------|
| PY-L2 | Script API docstrings — marginal value unless end-users write custom scripts |
| PY-L3 | Logging prefix inconsistency — no operational benefit from standardizing; log aggregation filters by module name |
| FE-L (all 7) | Vue reactivity non-issues (array mutation, computed sort, forEach patterns), premature optimization (O(n) topic matching), undefined batch order (channels are independent) |

---

## PART 1: PYTHON BACKEND FINDINGS

### CRITICAL (6)

#### PY-C1: Script Sandbox Escape via Pattern Matching
- **File:** `services/crio_node_v2/script_engine.py:656-671`
- **Also:** `services/daq_service/script_manager.py:916-917`, `services/opto22_node/opto22_node.py:2687-2692`
- Script execution uses string pattern matching to block dangerous functions (`__import__`, `exec(`, `open(`, etc.) but patterns are trivially bypassable via string concatenation (`'__im' + 'port__'`), whitespace insertion, or `getattr` indirection. After pattern check, code is executed with `exec(code, env, env)`. No AST-based validation, no execution timeout, no resource limits, no process-level sandbox.
- **Risk:** Arbitrary code execution on cRIO/DAQ host with full privileges.
- **Fix:** Implement AST-based validation; add execution timeout; add resource limits; consider process-level sandboxing.

#### PY-C2: MQTT Credentials in Plaintext Config File
- **File:** `services/crio_node_v2/crio_node.py:779-780`
- **Also:** `services/crio_node_v2/config.py:252`
- MQTT password stored unencrypted in `crio_config.json` (default permissions 0644, world-readable).
- **Risk:** Any user on cRIO can read credentials. If cRIO breached, MQTT broker compromised.
- **Compliance:** Violates 21 CFR Part 11 (secured credentials).

#### PY-C3: Safety Action Without Pre-Flight Validation
- **File:** `services/crio_node_v2/safety.py:243-265`
- Safety action parser does not validate target channel exists before executing write. Misspelled channel name in config causes safety action to silently fail.
- **Risk:** Safety interlock trips but output never actuates. System appears safe when unsafe.

#### PY-C4: Communication Watchdog Timer Not Implemented
- **File:** `services/crio_node_v2/crio_node.py:54-61, 64-65, 323-324`
- `comm_watchdog_timeout_s` configured in dataclass but `_check_comm_watchdog()` never implemented. cRIO continues running if DAQ service crashes.
- **Risk:** Hardware continues in last commanded state indefinitely with no safe-state transition.

#### PY-C5: Unvalidated Terminal Configuration for Current Inputs
- **File:** `services/crio_node_v2/hardware.py:443, 481`
- Current and voltage input channels hardcoded to `TerminalConfiguration.DEFAULT` without validation. Per CLAUDE.md, cRIO modules require DIFFERENTIAL configuration.
- **Risk:** Incorrect measurement readings if DEFAULT resolves to RSE. Control errors from bad data.

#### PY-C6: Exception Swallowing in MQTT Publish Queue Thread
- **File:** `services/daq_service/daq_service.py:11283-11284`
- Critical MQTT publish queue thread catches all exceptions with only logging. No retry, no queue persistence. Messages (including alarms) lost silently.
- **Risk:** Safety-critical alarms never reach operator dashboard.

### HIGH (16)

#### PY-H1: Missing Input Bounds Validation - Pulse Output Frequency
- **File:** `services/crio_node_v2/hardware.py:881-897`
- Pulse output frequency written to hardware without bounds validation. `_validate_output_value()` exists (line 799) but not called for pulse outputs.

#### PY-H2: 4-20mA Scaling Without Bounds Validation
- **File:** `services/crio_node_v2/config.py:109-124`
- No check that `eng_min < eng_max`, no division-by-zero guard, no bounds on input current or output result.

#### PY-H3: Thermocouple Type Defaulted Without Logging
- **File:** `services/crio_node_v2/hardware.py:423-433`
- Invalid thermocouple types silently default to K-type via `getattr()` default. Temperature readings could be wrong by 100+ degrees.

#### PY-H4: Counter/Pulse Task Creation Failures Not Propagated
- **File:** `services/crio_node_v2/hardware.py:631-632, 665-666`
- Task creation failures logged but not re-raised. Channels silently unavailable.

#### PY-H5: Socket Resource Leak in IP Detection
- **File:** `services/crio_node_v2/crio_node.py:1209-1212`
- Socket created but not closed in `finally` block. Repeated calls exhaust file descriptors.

#### PY-H6: Output Value Validation Missing Infinity Check
- **File:** `services/crio_node_v2/hardware.py:799-827`
- Checks for NaN but not `float('inf')`. Infinity passes through to hardware.

#### PY-H7: No Audit Logging on Critical Output Commands
- **File:** `services/crio_node_v2/crio_node.py` (write output handler)
- Hardware output writes have no audit trail (who, when, what, from where).
- **Compliance:** Violates 21 CFR Part 11.

#### PY-H8: MQTT Publish Failures Not Retried
- **File:** `services/crio_node_v2/mqtt_interface.py:177-210`
- Default QoS=0. Critical messages (alarms, safety status) not retried on failure. Return value ignored by many callers.

#### PY-H9: Config File Loaded Without Schema Validation
- **File:** `services/crio_node_v2/crio_node.py:1411-1414`
- JSON config loaded directly without validating required fields, types, or ranges.

#### PY-H10: Alarm Limit Ordering Not Enforced
- **File:** `services/crio_node_v2/crio_node.py:827-847`
- Invalid alarm limit ordering (hihi < hi) logged as error but config still applied. Alarms malfunction silently.

#### PY-H11: Missing Signal Handlers in cRIO Node Main Entry Point
- **File:** `services/crio_node_v2/crio_node.py:1392-1433`
- No SIGTERM/SIGINT handlers. systemd shutdown signals not caught. Hardware left running on termination.

#### PY-H12: Momentary Pulse Duration Not Validated
- **File:** `services/crio_node_v2/config.py:88`
- Accepts any integer including negative values and extreme durations (2^31 ms = 24+ days).

#### PY-H13: Exception Context Lost in Alarm Callbacks
- **File:** `services/crio_node_v2/safety.py:140-143, 259-263`
- `logger.error(f"Alarm callback error: {e}")` without `exc_info=True`. Tracebacks discarded.

#### PY-H14: Race Condition in Output State Access
- **File:** `services/crio_node_v2/hardware.py:200-202, 829-839, 942-944`
- `_output_values` dict accessed without locking. Main thread writes while another reads.

#### PY-H15: OPC UA Resource Leak on Subscription Delete
- **File:** `services/daq_service/opcua_source.py:174-179`
- Subscription delete exception swallowed with `pass`. Server resources leak over time.

#### PY-H16: Unvalidated Hardware Discovery Data
- **File:** `services/daq_service/device_discovery.py:535-541`
- `DiscoveryResult` with `success=False` returned but callers may not check flag.

### MEDIUM (8)

| ID | File | Description |
|----|------|-------------|
| PY-M1 | `crio_node.py:413-450` | Command payload logged at DEBUG only - can't troubleshoot in production |
| PY-M2 | `crio_node.py:788-789` | Config file saved with default permissions (0644), world-readable |
| PY-M3 | `safety_manager.py:79-82` | Invalid interlock condition type accepted with warning only |
| PY-M4 | `daq_service.py:1635-1720` | Console variables evaluated with `exec()` and restricted namespace but incomplete blocking |
| PY-M5 | `script_manager.py:914-917` | Script execution has no timeout - infinite loop blocks main thread |
| PY-M6 | `audit_trail.py:272-274` | Audit trail files written with default permissions, world-readable |
| PY-M7 | `hardware.py:515,693,717,743` | Magic numbers without explanation (timeouts, buffer sizes) |
| PY-M8 | `config.py:154-156` | Thermocouple type defaulted to K at DEBUG log level |

### LOW (3)

| ID | File | Description |
|----|------|-------------|
| PY-L1 | `hardware.py:127-147` | Mock hardware has no simulated errors/timeouts for testing |
| PY-L2 | `script_engine.py:200-300` | Script API has minimal docstrings |
| PY-L3 | Multiple files | Inconsistent logging format (mixed `[PREFIX]` tags) |

---

## PART 2: FRONTEND (TypeScript/Vue) FINDINGS

### CRITICAL (15)

#### FE-C1: Output Command - No Range Validation
- **File:** `dashboard/src/composables/useMqtt.ts:1367-1374`
- `setOutput()` sends values to hardware without range checking, channel validation, or interlock checks.

#### FE-C2: No Confirmation for System Trip
- **File:** `dashboard/src/composables/useSafety.ts:1499`
- `tripSystem()` executes immediately without UI confirmation dialog.

#### FE-C3: No Rate Limiting on Control Commands
- **File:** `dashboard/src/composables/useMqtt.ts:1367-1374`
- `setOutput()` can be called unlimited times per second (e.g., rapid slider). MQTT broker and backend flooded.

#### FE-C4: No Confirmation for Safety Action Execution
- **File:** `dashboard/src/composables/useSafety.ts:1595-1655`
- `executeSafetyAction()` with type `trip_system` executes without confirmation.

#### FE-C5: No Confirmation for Output State Changes
- **File:** `dashboard/src/composables/useSafety.ts:1624-1635`
- `set_output_safe` safety action changes output states without confirmation.

#### FE-C6: Division by Zero Risk in Scaling
- **File:** `dashboard/src/composables/useMqtt.ts:556`
- Map scaling divides by `(pre_scaled_max - pre_scaled_min)` which could be zero.

#### FE-C7: Default Guest User Always Available
- **File:** `dashboard/src/composables/useAuth.ts:59-64, 102`
- System falls back to `DEFAULT_GUEST` if not authenticated. Anyone sees data without login.

#### FE-C8: Expression Evaluator - Code Injection
- **File:** `dashboard/src/composables/useSafety.ts:937-939`
- Uses `new Function()` with incomplete validation regex that allows `.()` for property access.

#### FE-C9: Project File Loading - Arbitrary Code Execution
- **File:** `dashboard/src/composables/useProjectManager.ts:504`
- `JSON.parse(content)` used directly without schema validation. Malicious projects inject scripts.

#### FE-C10: Control Operations - No Permission Check Before MQTT Send
- **File:** `dashboard/src/composables/useMqtt.ts:1331-1383`
- `startAcquisition()`, `stopAcquisition()`, etc. don't check permissions before sending.

#### FE-C11: Channel Config Update - No Auth Check
- **File:** `dashboard/src/composables/useMqtt.ts:1476-1487`
- Any connected user can modify hardware configuration.

#### FE-C12: Safety Action Create - No Admin Check
- **File:** `dashboard/src/composables/useSafety.ts:1562-1571`
- Any user can create system trip actions.

#### FE-C13: Unsafe JSON Parsing - No Schema Validation
- **File:** `dashboard/src/composables/useMqtt.ts:244`
- `JSON.parse(message.toString())` without validating payload structure.

#### FE-C14: SVG Injection via v-html
- **File:** `dashboard/src/components/PidCanvas.vue:2020-2023`
- `v-html` renders user-created SVG without sanitization. Malicious SVG with script tags.

#### FE-C15: Interlock Bypass - No Permission Validation
- **File:** `dashboard/src/composables/useSafety.ts:665-690`
- `bypassInterlock()` checks `interlock.bypassAllowed` but not user's role.

### HIGH (27)

#### FE-H1: MQTT Message Handler - Insufficient Error Capture
- **File:** `dashboard/src/composables/useMqtt.ts:239-368`
- Single try-catch for 120+ lines of message routing. Failed messages silently discarded.

#### FE-H2: Batch Channel Processing - Missing Validation
- **File:** `dashboard/src/composables/useMqtt.ts:453-530`
- Physical-to-TAG name mapping without validation. Failed mappings silently use physical name.

#### FE-H3: Channel Value - Missing Null Checks
- **File:** `dashboard/src/composables/useMqtt.ts:400`
- `channelConfigs.value[channelName]` assumes channel exists. Undefined if non-existent.

#### FE-H4: Interlock Condition - No Type Validation
- **File:** `dashboard/src/composables/useSafety.ts:856-880`
- `evaluateConditionRaw()` accesses properties without null checks.

#### FE-H5: Expression Evaluation - Incomplete Input Validation
- **File:** `dashboard/src/composables/useSafety.ts:933`
- Regex allows `.()` which enables property access and function calls.

#### FE-H6: Connection State Race Condition
- **File:** `dashboard/src/composables/useMqtt.ts:192-227`
- `connected.value = true` set before subscriptions established. Commands during window lost.

#### FE-H7: No Confirmation for Interlock Bypass
- **File:** `dashboard/src/composables/useSafety.ts:665-690`
- Disables safety system without confirmation dialog.

#### FE-H8: No Confirmation for Interlock Removal
- **File:** `dashboard/src/composables/useSafety.ts:651-663`
- Deletes interlock without confirmation.

#### FE-H9: Output Widget - No Double-Click/Hold Pattern
- Digital output toggle allows single-click state change without safety confirmation.

#### FE-H10: Project File Upload - No Content Validation
- **File:** `dashboard/src/composables/useProjectManager.ts:504`
- Parsed JSON used directly for channels, scripts, etc.

#### FE-H11: MQTT Callback Payload - Untyped `any`
- **File:** `dashboard/src/composables/useMqtt.ts:42-44, 58, 109-116`
- 50+ instances of `any` type in callback declarations.

#### FE-H12-H27: Additional High Findings
- Missing error handlers in alarm processing (`useSafety.ts:709-754`)
- Login timeout silent failure (`useAuth.ts:279-292`)
- User management no error callback (`useAuth.ts:321-337`)
- cRIO status payload unsafe assertion (`useCrio.ts:137`)
- Heartbeat payload unsafe assertion (`useCrio.ts:151`)
- Command ack no payload structure check (`useMqtt.ts:1113-1140`)
- Stale data not cleared on disconnect (`useMqtt.ts:1733-1740`)
- Channel ownership tracking unbounded growth (`useMqtt.ts:39, 381-398`)
- knownNodes registry no timeout cleanup (`useMqtt.ts:256-281`)
- Safety state not atomic on clear (`useSafety.ts:340-394`)
- Scaling parameter type mismatch (`useMqtt.ts:543-548`)
- Pending commands orphaned timeout handlers (`useMqtt.ts:1172-1196`)
- `hasPermission` is not reactive (`useAuth.ts:126-145`)
- Session token no expiration (`useAuth.ts:86-97`)
- Watch cleanup missing (`useAuth.ts:167-171`)
- Multiple sendCommand variants with unclear semantics (`useMqtt.ts:1241-1304`)

### MEDIUM (65)

Key categories:
- **Error Handling (6):** Alarm processing, channel value handling, discovery timeouts, localStorage failures
- **Input Validation (9):** Variable access, safety action targets, config loads, alarm config updates
- **Safety UI (3):** Alarm acknowledgment, clear all alarms, alarm reset - all without confirmation
- **Auth/AuthZ (5):** Session in plain text, no idle timeout, self-service restrictions, archive verification
- **State Management (7):** dataIsStale unreliable, multiple concurrent connects, interlock status watch, active node selection
- **MQTT Handling (6):** Heartbeat no error state, command ack cleanup, discovery timeout, subscription cleanup, channel deduplication
- **XSS/Injection (2):** SVG symbol widget, dynamic binding template injection
- **Accessibility (10):** Missing ARIA labels on START/STOP/RECORD buttons, lock icon not described, alarm severity color-only, system trip not announced, interlock failure not accessible, output controls missing labels, warning dialogs not announced
- **Type Safety (10):** Handler parameters untyped, store values unsafe, config fields partially typed, payload destructuring, localStorage type safety
- **Code Quality (7):** Dead code, silent command failures, timeout callback patterns, console logging verbose (83 statements)

### LOW (7)

- Topic wildcard matching O(n) per message
- Batch channel processing order undefined
- Array mutation instead of immutable update
- Computed property sorts on every compute
- Reactive forEach mutation pattern
- Warning dialogs may not be announced

---

## PART 3: CONFIGURATION / DEPLOYMENT / INFRASTRUCTURE FINDINGS

### CRITICAL (7)

#### CFG-C1: Anonymous MQTT Access Enabled by Default
- **File:** `config/mosquitto.conf:7`
- `allow_anonymous true` - unauthenticated connections accepted.
- **CWE:** CWE-306

#### CFG-C2: MQTT Listener Binds to 0.0.0.0 (All Interfaces)
- **File:** `config/mosquitto.conf:1`
- `listener 1883 0.0.0.0` - unencrypted MQTT accessible on all network interfaces.
- **CWE:** CWE-200

#### CFG-C3: No TLS/SSL for Any MQTT Listener
- **Files:** `config/mosquitto.conf`, `config/mosquitto_secure.conf`
- No `cafile`, `certfile`, `keyfile`, or `tls_version` in either config. All messages transmitted plaintext.
- **CWE:** CWE-295

#### CFG-C4: MQTT Accessible from Entire Network
- **Files:** `config/mosquitto.conf:1`, `config/mosquitto_secure.conf:9,13`
- Even "secure" config exposes WebSocket on `0.0.0.0:9002`.

#### CFG-C5: WebSocket Uses Unencrypted Protocol
- **File:** `config/mosquitto.conf:4-5`
- Dashboard connects via `ws://` not `wss://`. All traffic in cleartext.

#### CFG-C6: MQTT Credentials File Not Auto-Generated
- **File:** `config/mosquitto_secure.conf:24`
- References `mosquitto_passwd` but no automated generation. `setup_mqtt_security.bat` referenced in docs doesn't exist.

#### CFG-C7: No Security Hardening Guide
- No `SECURITY.md` or `HARDENING.md` exists. No documented procedures for TLS, credentials, firewall, or network segmentation.

### HIGH (9)

#### CFG-H1: WebSocket Exposed to 0.0.0.0 in Secure Config
- **File:** `config/mosquitto_secure.conf:13`
- `listener 9002 0.0.0.0` even with auth. No TLS on WebSocket.

#### CFG-H2: Password File Path Hardcoded
- **File:** `config/mosquitto_secure.conf:24`
- Absolute Windows path with specific username. Fails at different deployment locations.

#### CFG-H3: Anonymous Users Have Read Access to Sensitive Topics
- **File:** `config/mosquitto_acl.conf:37-42`
- Anonymous can read `channels/#`, `status/#`, `heartbeat`. Information disclosure.

#### CFG-H4: Hardcoded Default Broker IP in Deployment Script
- **File:** `deploy_crio_v2.bat:11`
- Defaults to `192.168.1.1`. Error-prone for multi-site installations.

#### CFG-H5: MQTT Broker Hardcoded to localhost in cRIO Services
- **Files:** `services/crio_node_v2/crio_node.py:48`, `config.py:216`, `mqtt_interface.py:30`
- cRIO is remote device - localhost means wrong host.

#### CFG-H6: Remote cRIO Accessible via MQTT if Broker Exposed
- cRIO executes any command on control topics. No additional authorization layer on device.

#### CFG-H7: No Dependency Audit, SBOM, or Vulnerability Scanning
- No `requirements-lock.txt`, no SBOM files, no security scanning in CI/CD.

#### CFG-H8: Project Backups Committed to Git Repository
- **File:** `config/projects/backups/`
- Backup JSON files tracked in Git. Repository grows rapidly.

#### CFG-H9: Watchdog Uses WebSocket Without TLS
- **File:** `services/daq_service/watchdog.py:113-122`
- Connects via plain `ws://`. Attacker could send fake heartbeats.

### MEDIUM (26)

Key categories:

**MQTT (1):**
- No rate limiting or connection limits on broker

**Deployment (5):**
- SSH uses default `admin` username without verification
- No SSH host key verification during deployment
- Deployed files lack integrity verification (no checksums)
- Daemon start without proper cleanup of previous instance
- Daemon log output without error fallback

**Configuration (4):**
- Config file paths hardcoded to specific Windows user directory
- Numeric config parameters lack range validation (scan_rate_hz=0 disables scanning)
- Safety config parameters not cross-validated with hardware
- cRIO service config points to hardcoded IP

**Secrets (2):**
- Hardcoded `admin:admin` credentials in test code
- `.gitignore` credentials exclusion incomplete (doesn't cover `mosquitto_passwd`, `users.json`)

**Dependencies (3):**
- All dependencies use `>=` instead of pinned versions
- NI-DAQmx (critical driver) not in requirements.txt
- Azure SDK paho-mqtt version conflict

**Backup/Recovery (3):**
- No documented recovery procedure
- Archive integrity verification optional rather than mandatory
- No RTO/RPO targets defined

**Project Config (3):**
- Project JSON lacks comprehensive schema validation
- No range validation for alarm limits in config files
- Safety interlocks in config files not write-protected

**Service Management (3):**
- No adaptive health check timeout based on network conditions
- Services lack automatic restart on crash
- No resource limits (CPU, memory) for services

**Documentation (3):**
- CLAUDE.md references non-existent `setup_mqtt_security.bat`
- No regulatory compliance documentation
- CI/CD pipeline lacks security acceptance tests

---

## PART 4: COMPLIANCE MAPPING

| Standard | Status | Key Gaps |
|----------|--------|----------|
| **FDA 21 CFR Part 11** | Non-compliant | No audit evidence, plaintext credentials, world-readable files |
| **IEC 62443** (Industrial Cybersecurity) | Non-compliant | No auth, no encryption, 0.0.0.0 binding |
| **IEC 61511** (Safety Systems) | Partial | Interlocks exist but no cross-validation, watchdog unimplemented |
| **ISA-18.2** (Alarm Management) | Partial | Alarm framework exists but limit validation missing |
| **NIST SP 800-53** | Non-compliant | Gaps in AC, AU, CM, IA, SC, SI families |
| **NIST SP 800-52** (TLS) | Non-compliant | No TLS anywhere |
| **OWASP Top 10** | Non-compliant | Injection, broken auth, security misconfiguration |

---

## PART 5: REMEDIATION ROADMAP

### Phase 1: Critical - Before Any Production Deployment

1. ~~**MQTT Authentication:** Enable `allow_anonymous false`, generate credentials~~ **DONE** — Zero-config auto-generation via `scripts/mqtt_credentials.py`
2. ~~**MQTT TLS:**~~ **SKIPPED** — Intentionally omitted (localhost + dedicated physical link; TLS incompatible with zero-config)
3. ~~**MQTT Binding:**~~ **DONE** — WebSocket on `127.0.0.1`, TCP on `0.0.0.0` (needed for cRIO physical link)
4. **Script Sandbox:** Replace pattern-matching with AST-based validation, add execution timeout
5. **Safety Action Validation:** Validate target channel exists before executing safety write
6. **Communication Watchdog:** Implement `_check_comm_watchdog()` with safe-state transition
7. **Frontend Confirmations:** Add confirmation dialogs for system trip, safety actions, output changes
8. **Rate Limiting:** Add rate limiting on `setOutput()` and all control commands
9. **Output Validation:** Add range checking in frontend `setOutput()` before MQTT publish
10. **Security Hardening Guide:** Create `SECURITY.md` with production deployment procedures

### Phase 2: High Priority - Within First Sprint

11. **Permission Checks:** Add frontend auth checks before control operations
12. **Signal Handlers:** Add SIGTERM/SIGINT handlers to cRIO node main entry
13. **Schema Validation:** Validate config files and project JSON on load
14. **Alarm Limit Enforcement:** Reject invalid alarm ordering instead of logging
15. **MQTT QoS:** Use QoS=1 for safety-critical messages, add retry mechanism
16. **Audit Logging:** Add audit trail for all output commands (who, when, what, from where)
17. **Terminal Config:** Validate resolved terminal configuration matches module requirements
18. **Output Bounds:** Add infinity check, validate pulse frequency, validate momentary duration
19. **Resource Leaks:** Fix socket leak in IP detection, OPC UA subscription cleanup
20. **Dependency Lock:** Create `requirements-lock.txt` with pinned versions
21. **Race Conditions:** Add locking to `_output_values` dict, fix connection state race

### Phase 3: Medium Priority - Within 1-3 Months

22. **Frontend state management:** Clear stale data on disconnect, fix ownership tracking, cleanup knownNodes
23. **Accessibility:** Add ARIA labels to all safety-critical controls
24. **Expression evaluator:** Strengthen regex validation or replace `new Function()` with safe parser
25. **Project file validation:** Add schema validation for uploaded project files
26. **Config validation:** Cross-validate safety parameters, validate alarm ranges
27. **Deployment integrity:** Add SHA-256 checksums, SSH host key verification
28. **Backup/Recovery:** Document procedures, make archive verification mandatory
29. **Service management:** Add auto-restart, resource limits
30. **CI/CD security tests:** Add security acceptance tests to pipeline

### Phase 4: Ongoing

31. **Vulnerability management:** Monthly dependency audits, SBOM generation
32. **Quarterly security testing**
33. **Compliance documentation and certification**
34. **Backup verification drills**

---

## PART 6: QUICK REFERENCE - ALL FINDINGS BY FILE

### Python Backend

| File | Finding IDs |
|------|-------------|
| `services/crio_node_v2/script_engine.py` | PY-C1 |
| `services/crio_node_v2/crio_node.py` | PY-C2, PY-C4, PY-H5, PY-H7, PY-H9, PY-H10, PY-H11, PY-M1, PY-M2 |
| `services/crio_node_v2/safety.py` | PY-C3, PY-H13 |
| `services/crio_node_v2/hardware.py` | PY-C5, PY-H1, PY-H3, PY-H4, PY-H6, PY-H14, PY-M7, PY-L1 |
| `services/crio_node_v2/config.py` | PY-H2, PY-H12, PY-M8 |
| `services/crio_node_v2/mqtt_interface.py` | PY-H8 |
| `services/daq_service/daq_service.py` | PY-C6, PY-M4 |
| `services/daq_service/script_manager.py` | PY-M5 |
| `services/daq_service/opcua_source.py` | PY-H15 |
| `services/daq_service/device_discovery.py` | PY-H16 |
| `services/daq_service/safety_manager.py` | PY-M3 |
| `services/daq_service/audit_trail.py` | PY-M6 |

### Frontend

| File | Finding IDs |
|------|-------------|
| `dashboard/src/composables/useMqtt.ts` | FE-C1, FE-C3, FE-C10, FE-C11, FE-C13, FE-H1-H3, FE-H6, FE-H11 + 15 MEDIUM |
| `dashboard/src/composables/useSafety.ts` | FE-C2, FE-C4, FE-C5, FE-C8, FE-C12, FE-C15, FE-H4, FE-H5, FE-H7, FE-H8 + 10 MEDIUM |
| `dashboard/src/composables/useAuth.ts` | FE-C7, FE-H13-H16 + 5 MEDIUM |
| `dashboard/src/composables/useProjectManager.ts` | FE-C9, FE-H10 |
| `dashboard/src/composables/useCrio.ts` | FE-H12 |
| `dashboard/src/components/PidCanvas.vue` | FE-C14 |
| `dashboard/src/components/ControlBar.vue` | 5 MEDIUM (accessibility) |

### Configuration / Infrastructure

| File | Finding IDs |
|------|-------------|
| `config/mosquitto.conf` | CFG-C1, CFG-C2, CFG-C3, CFG-C4, CFG-C5, CFG-C7 |
| ~~`config/mosquitto_secure.conf`~~ | Deleted — superseded by production `mosquitto.conf` |
| `config/mosquitto_acl.conf` | CFG-H3, CFG-C5 |
| `scripts/mqtt_credentials.py` | CFG-C6, PY-C2 (new — auto-generates credentials) |
| `deploy_crio_v2.bat` | CFG-H4, CFG-H5 + 3 MEDIUM |
| `scripts/run_crio_v2.py` | CFG-H5 (--mqtt-user/--mqtt-pass args) |
| `start.bat` | CFG-C7 (portable paths, credential auto-setup) |
| `requirements.txt` | 3 MEDIUM |
| `.gitignore` | 1 MEDIUM |
| `.github/workflows/ci.yml` | 1 MEDIUM |

---

*This audit should be re-run after each remediation phase to track progress.*
*Last updated: 2026-02-01*
