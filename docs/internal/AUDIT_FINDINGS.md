# NISystem Comprehensive Audit Report

**Date**: 2026-02-28
**Scope**: DAQ service, cRIO node, safety systems, recording, scripts, watchdog, PID, standards compliance

---

## Executive Summary

The NISystem codebase is **well-engineered for an industrial data acquisition system**. Safety architecture follows IEC 61511 latch state machine patterns, alarms follow ISA-18.2, and audit trails follow 21 CFR Part 11. However, the audit identified several issues ranging from minor robustness gaps to a few items that warrant attention before safety-critical deployment.

**Critical**: 0 findings
**High**: 3 findings
**Medium**: 8 findings
**Low**: 6 findings

---

## Part 1: Runtime & Timing

### 1.1 DAQ Service Scan Loop

**Location**: `services/daq_service/daq_service.py` (~line 5753+)

**Architecture**: The scan loop runs in a dedicated thread. Each cycle:
1. Reads hardware values (HardwareReader continuous buffer)
2. Reads auxiliary sources (Modbus, OPC-UA, REST, EtherNet/IP via DataSourceManager)
3. Runs user scripts (ScriptManager)
4. Evaluates alarms (AlarmManager)
5. Evaluates interlocks (SafetyManager)
6. Publishes to MQTT (rate-limited at 4 Hz via TokenBucketRateLimiter)
7. Records data (RecordingManager)

**Finding 1.1a — Scan overrun detection exists but is passive** (LOW)
- Scan timing stats are tracked (`ScanTimingStats`) and overruns are logged
- No automatic corrective action on sustained overruns (e.g., reducing scan rate, shedding load)
- For non-safety applications this is acceptable; for SIL-rated interlocks the scan overrun should trigger a diagnostic alarm

**Finding 1.1b — Script execution is synchronous in scan loop** (MEDIUM)
- User scripts execute within the scan cycle via `exec()` in-process
- A slow script directly delays alarm/interlock evaluation and recording
- Scripts have a timeout mechanism but it's cooperative (Python GIL), not preemptive
- Mitigation: The 4 Hz rate limiter on script-published values limits cascading effects

### 1.2 cRIO Node Main Loop

**Location**: `services/crio_node_v2/crio_node.py` (lines 455-654, 1401-1800)

**Architecture**: Single-threaded async-style loop with `time.sleep()`:
1. Read hardware channels (AI, DI, TC with IndexError guards for hot-unplug)
2. Run user scripts (4 Hz rate-limited)
3. Evaluate safety (alarms + interlocks)
4. Publish values to MQTT
5. Handle incoming MQTT commands

**Finding 1.2a — Error threshold of 3 before safe state** (LOW)
- After 3 consecutive hardware read errors, the node enters safe state and publishes `status/degraded`
- This is appropriate — fast enough to catch real failures, tolerant enough for transient glitches
- Recovery uses exponential backoff

**Finding 1.2b — Single-threaded design limits responsiveness** (LOW)
- MQTT command handling occurs in the same loop as hardware reads
- If a hardware read blocks (e.g., DAQmx timeout), command processing is delayed
- For the cRIO use case (local I/O, 10 Hz scan), this is acceptable

### 1.3 PID Engine Timing

**Location**: `services/daq_service/pid_engine.py` (lines 462-601)

**Architecture**: PID loops execute within the scan cycle. Each loop:
- Computes error, integral, derivative terms
- Uses derivative-on-PV (not derivative-on-error) to avoid setpoint kick
- Anti-windup via integral clamping
- Bumpless transfer on auto↔manual switch

**Finding 1.3a — dt calculated from wall clock** (MEDIUM)
- `dt` is computed from `time.monotonic()` delta between calls
- If the scan loop is delayed (script overrun, GC pause), the PID sees a large dt
- This causes an integral jump proportional to the delay
- **Recommendation**: Clamp `dt` to `[0.5 * expected_dt, 2.0 * expected_dt]` to limit integral windup from timing jitter

**Finding 1.3b — No output rate-of-change limiting** (MEDIUM)
- PID output is clamped to `[output_min, output_max]` but there's no slew rate limit
- A sudden setpoint change or mode switch can cause a step change in output
- For motor/valve applications, this can cause mechanical stress
- **Recommendation**: Add optional `max_output_rate` parameter (units/sec)

---

## Part 2: Safety & Interlocks

### 2.1 IEC 61511 Compliance — Safety Instrumented Systems

**Location**: `services/daq_service/safety_manager.py`, `services/crio_node_v2/safety.py`

**Architecture**: Three-tier safety (DAQ authoritative + cRIO local + Opto22 local). Latch state machine: SAFE → ARMED → TRIPPED. Config pushed from DAQ to edge nodes.

**Finding 2.1a — No SIL verification calculation** (MEDIUM)
- Interlocks carry a `sil_rating` field but there's no PFD (Probability of Failure on Demand) calculation
- Proof test intervals are tracked but not validated against required test frequency for the claimed SIL
- The field is informational only — no enforcement
- **Recommendation**: Add a warning if proof test is overdue relative to SIL requirements

**Finding 2.1b — NaN handling in interlock conditions** (HIGH)
- When a channel value is `NaN` (open thermocouple, disconnected sensor), the condition evaluation at `safety.py:646-675` checks for `None` values and sets `channel_offline=True`
- However, `NaN` is not `None` — a NaN float passes the None check and enters comparison operators
- `NaN < 100` evaluates to `False` in Python, which means a `channel_value < threshold` condition would appear "not satisfied"
- Whether this trips or not depends on the condition's `satisfied=True/False` semantics
- In the **worst case**: an open thermocouple reading NaN on a "temperature must be below limit" interlock could **fail to trip** because `NaN < limit` = False = "condition not met" = potentially interpreted as "safe" depending on logic
- **Recommendation**: Add explicit `math.isnan()` check before comparison; treat NaN as channel_offline

**Finding 2.1c — Interlock evaluation order is correct** (POSITIVE)
- Alarms evaluate first, then interlocks — so `alarm_active` conditions see current alarm state
- COMM_FAIL detection runs before interlock evaluation
- This ordering is critical and is correctly implemented

### 2.2 ISA-18.2 Compliance — Alarm Management

**Location**: `services/daq_service/alarm_manager.py`

**Finding 2.2a — Alarm flood detection exists on edge nodes** (POSITIVE)
- `crio_node_v2/safety.py` has `_check_flood()` / `_should_suppress()`
- Alarm flood detection with configurable thresholds

**Finding 2.2b — NaN values not explicitly handled in alarm evaluation** (HIGH)
- `alarm_manager.py:561-680` — the `_evaluate_alarm()` method compares channel values against thresholds
- No `math.isnan()` guard before comparisons
- NaN comparisons return False for all operators, meaning:
  - High-high alarm: `NaN > threshold` = False → alarm does NOT fire
  - Low-low alarm: `NaN < threshold` = False → alarm does NOT fire
- An open thermocouple reading NaN would **not trigger any threshold alarm**
- COMM_FAIL catches missing channels but not NaN-valued channels
- **Recommendation**: Treat NaN as an alarm condition (either force-fire or generate a dedicated BAD_QUALITY alarm)

### 2.3 Output Blocking

**Finding 2.3a — Output blocking correctly prevents script/MQTT override** (POSITIVE)
- Safety-held outputs cannot be overridden by scripts or MQTT `set_output` commands
- `is_safety_held()` and `is_interlock_held()` checks are present in script engine
- The blocking check happens at the output write point, not at evaluation

---

## Part 3: Data Integrity & Recording

### 3.1 21 CFR Part 11 / ALCOA+ — Audit Trail

**Location**: `services/daq_service/audit_trail.py`

**Finding 3.1a — SHA-256 hash chain is well-implemented** (POSITIVE)
- Each audit entry includes the hash of the previous entry
- Append-only JSONL format
- Tamper detection via hash chain verification
- `fsync` after each write

**Finding 3.1b — Electronic signatures not implemented** (MEDIUM)
- Only one reference to `electronic_signature` in the entire DAQ service
- 21 CFR Part 11 requires electronic signatures for record approval/rejection
- The audit trail logs actions with usernames but doesn't require signature verification
- **Impact**: Acceptable for non-regulated environments; would need enhancement for pharma/FDA-regulated use

### 3.2 Recording Manager Crash Safety

**Location**: `services/daq_service/recording_manager.py`

**Finding 3.2a — OS-level file locking + fsync implemented** (POSITIVE)
- `msvcrt.locking()` on Windows, `fcntl.flock()` on Unix
- `fsync` after flush for crash safety
- Buffered mode accumulates samples before writing (configurable buffer size)

**Finding 3.2b — No crash recovery for in-flight buffers** (MEDIUM)
- If the process crashes between buffer accumulation and flush, buffered samples are lost
- The buffer lives in memory only
- `stop_recording()` flushes and closes properly on graceful shutdown
- Ungraceful crash (kill -9, power loss) loses the current buffer
- **Recommendation**: For critical recording, use `immediate` mode (writes every sample) or reduce buffer size

**Finding 3.2c — Graceful shutdown chain exists** (POSITIVE)
- `atexit` handler registered
- `SIGTERM`/`SIGINT` handlers call shutdown sequence
- Recording is stopped and flushed before exit

---

## Part 4: Hardware & Communication

### 4.1 NI-DAQmx API Usage

**Location**: `services/daq_service/hardware_reader.py`, `services/crio_node_v2/hardware.py`

**Finding 4.1a — Continuous buffered acquisition correctly used** (POSITIVE)
- HardwareReader uses DAQmx continuous buffered mode
- Buffer overrun handling present
- Hot-unplug resilience via IndexError guards on partial reads

**Finding 4.1b — cRIO hardware default values on startup** (LOW)
- Output channels initialize to `default_value` from config (typically 0.0)
- `set_safe_state()` writes configured safe values to all outputs
- No verification read-back after safe state write
- **Recommendation**: Add read-back verification for safety-critical outputs

### 4.2 MQTT Reconnection

**Location**: `services/daq_service/daq_service.py` (line 3391+), `services/crio_node_v2/mqtt_interface.py`

**Finding 4.2a — DAQ service MQTT reconnection** (LOW)
- `on_disconnect` callback handles reconnection
- paho-mqtt v2 automatic reconnection is relied upon
- No explicit backoff visible in DAQ service (paho handles it internally)

**Finding 4.2b — cRIO MQTT reconnection is robust** (POSITIVE)
- Exponential backoff: 5s → 60s max
- Node never exits on broker unavailability
- Keeps retrying until broker comes up or SIGTERM

### 4.3 Opto22 Stale I/O Detection

**Finding 4.3a — groov MQTT stale detection implemented** (POSITIVE)
- `GroovIOSubscriber.get_stale_channels(timeout_s)` detects channels that haven't updated
- Stale detection runs in the main loop
- Published to status for monitoring

---

## Part 5: Script Isolation

### 5.1 Script Sandbox

**Location**: `services/daq_service/script_manager.py`, `services/crio_node_v2/script_engine.py`

**Finding 5.1a — AST-based validation is thorough** (POSITIVE)
- Blocked imports, dangerous dunders, dangerous builtins
- `type()` removed from safe builtins (prevents metaclass escape)
- Blocked module access
- 256 KB code size limit

**Finding 5.1b — exec() in-process is inherently limited** (LOW)
- No process isolation — a determined attacker with code execution could potentially escape
- For the intended use case (trusted operators writing simple scripts), this is acceptable
- The blocked lists are comprehensive and synced across all three engines

### 5.2 Script Output Safety

**Finding 5.2a — Safety-held output check present** (POSITIVE)
- Scripts cannot override safety-held or interlock-held outputs
- TokenBucketRateLimiter prevents publish flooding (4 Hz)

---

## Part 6: Watchdog Monitoring

### 6.1 Software Watchdog

**Location**: `services/daq_service/watchdog.py`, `services/daq_service/watchdog_engine.py`

**Finding 6.1a — Heartbeat monitoring implemented** (POSITIVE)
- Watchdog monitors DAQ service heartbeat
- Hang detection with configurable timeout
- Auto-recovery attempt on detected hang

**Finding 6.1b — No hardware watchdog integration on cRIO** (MEDIUM)
- 5 grep hits for "watchdog" in cRIO code but no `/dev/watchdog` or WDT ioctl
- The cRIO hardware likely has a watchdog timer but it's not utilized
- If the Python process hangs (deadlock, infinite loop), there's no hardware-level recovery
- The `init.d` service script handles crash restarts but not hangs
- **Recommendation**: Integrate cRIO hardware watchdog timer for hang recovery; or add a software watchdog thread that monitors the main loop

---

## Summary Table

| # | Finding | Severity | Location | Recommendation |
|---|---------|----------|----------|----------------|
| 2.1b | NaN not treated as channel_offline in interlocks | **HIGH** | safety_manager.py, crio safety.py | Add `math.isnan()` check; treat NaN as offline |
| 2.2b | NaN values don't trigger threshold alarms | **HIGH** | alarm_manager.py | Treat NaN as BAD_QUALITY alarm or force-fire |
| 1.3a | PID dt from wall clock — integral jump on delays | **HIGH** | pid_engine.py | Clamp dt to expected range |
| 1.1b | Script execution synchronous in scan loop | MEDIUM | daq_service.py, script_manager.py | Consider async/subprocess for heavy scripts |
| 1.3b | No PID output slew rate limiting | MEDIUM | pid_engine.py | Add optional max_output_rate |
| 2.1a | SIL rating informational only, no PFD calc | MEDIUM | safety_manager.py | Add proof test overdue warning |
| 3.1b | Electronic signatures not implemented | MEDIUM | audit_trail.py | Add for FDA-regulated deployments |
| 3.2b | In-flight recording buffer lost on crash | MEDIUM | recording_manager.py | Use immediate mode for critical data |
| 6.1b | No hardware watchdog on cRIO | MEDIUM | crio_node.py | Integrate /dev/watchdog WDT |
| 1.3b | PID derivative-on-PV correct | MEDIUM | pid_engine.py | Add optional slew rate limit |
| 1.1a | Scan overrun passive logging only | LOW | daq_service.py | Add diagnostic alarm on sustained overrun |
| 1.2a | cRIO error threshold of 3 appropriate | LOW | crio_node.py | No change needed |
| 1.2b | Single-threaded cRIO design | LOW | crio_node.py | Acceptable for 10 Hz scan rate |
| 4.1b | No read-back after safe state write | LOW | crio hardware.py | Add verification for safety outputs |
| 4.2a | DAQ MQTT reconnect relies on paho internals | LOW | daq_service.py | Monitor reconnection metrics |
| 5.1b | exec() in-process sandbox | LOW | script_manager.py | Acceptable for trusted operators |

---

## Positive Findings (No Action Required)

1. **IEC 61511 latch state machine** — SAFE/ARMED/TRIPPED correctly implemented with demand counting and proof test tracking
2. **ISA-18.2 alarm lifecycle** — deadband, on/off delays, rate-of-change, shelving, latching all present
3. **Three-tier safety** — DAQ authoritative + edge node local safety survives PC disconnect
4. **Output blocking** — safety-held outputs correctly prevent script/MQTT override
5. **COMM_FAIL alarm** — missing channels auto-detected and alarmed
6. **SHA-256 audit hash chain** — tamper-detectable, append-only, fsync'd
7. **OS-level file locking** — recording files protected against concurrent access
8. **Graceful shutdown** — atexit + signal handlers flush recordings and close cleanly
9. **Hot-unplug resilience** — IndexError guards, NaN for missing channels, stale detection
10. **Alarm evaluation before interlocks** — correct ordering for `alarm_active` conditions
11. **cRIO MQTT exponential backoff** — never exits, keeps retrying
12. **Script blocked lists synced** — all three engines share the same restrictions

---

## Priority Actions

### Immediate (before safety-critical deployment)
1. **Fix NaN handling in alarm evaluation and interlock conditions** — this is the most impactful finding; open thermocouples reading NaN will silently fail to alarm or trip
2. **Clamp PID dt** — prevents integral windup from scan timing jitter

### Short-term
3. Add hardware watchdog integration for cRIO
4. Add PID output slew rate limiting option
5. Add proof test overdue warning for SIL-rated interlocks

### When needed
6. Electronic signatures for FDA-regulated environments
7. Process isolation for script sandbox (if moving beyond trusted operators)
