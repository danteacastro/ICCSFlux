# cRIO Node V2

Edge node service for NI CompactRIO hardware running NI Linux RT. Reads I/O modules, evaluates safety alarms, runs user scripts, and communicates with the PC-based DAQ service over MQTT.

**Version:** 2.2.0
**Replaces:** `services/crio_node/` (deprecated v1 monolith, 7,715 LOC)

---

## Quick Start

Deploy from the Windows PC using the deploy script. Do **not** manually `scp` individual files.

```cmd
deploy_crio_v2.bat [crio_host] [broker_host]
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `crio_host` | 192.168.1.20 | cRIO IP address (SSH target) |
| `broker_host` | 192.168.1.1 | PC running Mosquitto MQTT broker |

The script handles:
1. SSH connectivity check
2. Dependency installation (paho-mqtt, numpy, scipy from `vendor/crio-packages/`)
3. Stop existing service
4. Deploy all module files + runner script
5. Write MQTT credentials to cRIO (`mqtt_creds.json`, chmod 600)
6. Deploy TLS CA certificate (if available)
7. Start the service in daemon mode
8. Clear retained MQTT messages from previous deployment

---

## Architecture

```
                          MQTT (TCP 1883)
  ┌──────────────┐       authenticated        ┌──────────────┐
  │  DAQ Service  │◄────────────────────────►  │  cRIO Node   │
  │  (Windows PC) │    commands / telemetry    │  (Linux RT)  │
  └──────────────┘                             └──────┬───────┘
                                                      │
                                               NI-DAQmx RT
                                                      │
                                               ┌──────┴───────┐
                                               │  I/O Modules  │
                                               │  (TC, AI, AO, │
                                               │   DI, DO, CTR) │
                                               └──────────────┘
```

### Main Loop Pattern

The main loop runs at the configured scan rate (default 10 Hz):

```
1. Process pending commands      (from MQTT command queue)
2. Read channels                 (if acquiring)
3. Check safety / alarms         (single pass, if acquiring)
4. Check communication watchdog  (if configured, if acquiring)
5. Toggle watchdog output        (if configured, if acquiring)
6. Publish values                (rate-limited to publish interval)
```

Commands from MQTT are queued (never block the paho thread). Safety-critical commands (stop, safe-state, alarm) are never dropped -- they preempt non-critical commands if the queue is full.

After 10 consecutive loop errors, acquisition stops permanently and requires manual restart.

---

## Module Structure

| File | LOC | Purpose |
|------|-----|---------|
| `crio_node.py` | 1,730 | Main service: event loop, MQTT commands, hardware read, script exec, safety checks, publish |
| `script_engine.py` | 1,777 | Script sandbox (same API as DAQ service), `TokenBucketRateLimiter` (4 Hz cap) |
| `hardware.py` | 1,178 | NI-DAQmx abstraction for cRIO modules. Falls back to `MockHardware` if `nidaqmx` unavailable |
| `config.py` | 520 | Config loading, channel scaling (linear, 4-20 mA, map), project JSON parsing |
| `safety.py` | 378+ | ISA-18.2 alarms: HIHI/HI/LO/LOLO, ROC, deadband, on/off delay, shelving, interlock actions |
| `channel_types.py` | 299 | Channel type enum + NI module mappings (voltage, current, TC, RTD, strain, DI/DO, counter) |
| `mqtt_interface.py` | 337 | paho-mqtt wrapper with auto-reconnect, TLS support, topic helpers |
| `state_machine.py` | 215 | States: IDLE -> ACQUIRING -> SESSION. Validated transitions only |
| `audit_trail.py` | ~150 | SHA-256 hash chain, append-only JSONL, auto-rotation at 10 MB |
| `__main__.py` | 11 | Module entry point (`python -m crio_node_v2`) |
| `__init__.py` | — | Package marker |

---

## Features

### Safety and Alarms

ISA-18.2 compliant alarm evaluation with six states:

| State | Description |
|-------|-------------|
| `NORMAL` | No alarm condition |
| `ACTIVE` | Alarm condition present, unacknowledged |
| `ACKNOWLEDGED` | Operator acknowledged, condition still present |
| `RETURNED` | Condition cleared, not yet acknowledged |
| `SHELVED` | Temporarily suppressed by operator (timed) |
| `OUT_OF_SERVICE` | Disabled for maintenance |

**Alarm configuration per channel:**

| Parameter | Description |
|-----------|-------------|
| `hihi_limit` / `hi_limit` / `lo_limit` / `lolo_limit` | Threshold limits |
| `deadband` | Hysteresis to prevent alarm chatter |
| `delay_seconds` | On-delay: condition must persist before alarm activates |
| `off_delay_seconds` | Off-delay: condition must clear before alarm deactivates |
| `rate_of_change_limit` | ROC alarm threshold (units per period) |
| `rate_of_change_period_s` | ROC evaluation period (default 60s) |
| `safety_action` | Action on trip (see below) |

**Safety actions** support two formats:

```
Legacy string:   "set:DigitalOut1:0"
Dict (preferred): {"type": "set_digital_output", "channel": "DigitalOut1", "value": 0}
```

Action types: `set_digital_output`, `set_analog_output`, `stop_session`

### Script Engine

User Python scripts run in sandboxed threads with AST validation. Same API as the DAQ service `script_manager.py` -- blocked lists **must** be kept in sync.

**Available APIs in scripts:**

| API | Purpose |
|-----|---------|
| `tags.get(name)` | Read channel value |
| `outputs.set(name, value)` | Write output |
| `vars.get(name)` / `vars.set(name, value)` | Shared variables (inter-script) |
| `publish(name, value, units='')` | Publish computed value (4 Hz cap) |
| `session.active` / `session.name` | Read session state |
| `wait_for(seconds)` | Sleep respecting stop requests |
| `wait_until(condition)` | Wait for condition |
| `should_stop()` | Check if script should exit |
| `persist(key, value)` / `restore(key)` | State persistence across restarts |

**Helper classes available in scripts:**

`Counter`, `RateCalculator`, `Accumulator`, `EdgeDetector`, `RollingStats`, `SignalFilter`, `LookupTable`, `RampSoak`, `TrendLine`, `RingBuffer`, `PeakDetector`

Publish rate is capped at 4 Hz per value via `TokenBucketRateLimiter`.

### Audit Trail

Lightweight, tamper-evident event log for safety-critical operations.

- **Format:** Append-only JSONL with SHA-256 hash chain (each entry chains to previous)
- **Storage:** `/var/log/nisystem/` on the cRIO
- **Rotation:** Auto-rotates at 10 MB
- **Events logged:**

| Event | Trigger |
|-------|---------|
| `alarm_trip` | Alarm condition activates |
| `alarm_ack` | Operator acknowledges alarm |
| `alarm_shelve` | Operator shelves alarm |
| `safety_trip` | Safety action executes (output forced) |
| `safety_reset` | Safety reset performed |
| `config_change` | Configuration updated |
| `session_start` | Test session begins |
| `session_stop` | Test session ends |

### Communication Watchdog

Detects loss of contact with the PC/DAQ service.

- Monitors time since last MQTT command received
- If no command within `comm_watchdog_timeout_s`, triggers safe state:
  1. Stops watchdog output (external relay detects loss of pulse)
  2. Forces all outputs to safe state
  3. Transitions to IDLE
  4. Publishes `safety/comm_watchdog` event
- Automatically clears when communication is restored

### Hardware Watchdog Output

Toggles a configured digital output at a steady rate for external safety relay monitoring. If the cRIO stops (crash, hang, power loss), the relay detects loss of pulse and trips.

---

## MQTT Topics

Base topic: `nisystem/nodes/{node-id}/`

### Subscriptions (from DAQ service)

| Topic Pattern | Purpose |
|---------------|---------|
| `{base}/config/#` | Configuration updates |
| `{base}/commands/#` | Output write commands |
| `{base}/system/#` | Acquire start/stop |
| `{base}/session/#` | Session start/stop |
| `{base}/script/#` | Script commands |
| `{base}/safety/#` | Safe-state commands |
| `{base}/alarm/#` | Alarm ack/shelve/unshelve |
| `nisystem/discovery/ping` | Discovery ping (global) |

### Publications (to DAQ service / dashboard)

| Topic | QoS | Retained | Content |
|-------|-----|----------|---------|
| `channels/batch` | 0 | No | All channel values (dict of name -> {value, timestamp, quality}) |
| `channels/{name}` | 0 | No | Individual channel value |
| `status/system` | 0 | **Yes** | Node status: version, python_version, uptime_s, acquiring, modules, IP, serial, scan_timing |
| `heartbeat` | 0 | No | Periodic heartbeat for discovery |
| `session/status` | 0 | No | Session state |
| `alarms/event` | 0 | No | Alarm trip/clear event |
| `alarms/status` | 0 | **Yes** | Current alarm states for all channels |
| `alarms/ack/response` | 0 | No | Alarm acknowledge result |
| `safety/action` | 0 | No | Safety action executed |
| `safety/safe-state/ack` | 0 | No | Safe-state command result |
| `safety/comm_watchdog` | 0 | No | Communication watchdog trip/clear |
| `command/ack` | 1 | No | Command acknowledgment (output writes, system commands) |
| `config/response` | 1 | No | Configuration update result |

---

## Configuration

### Environment File

Location on cRIO: `/home/admin/nisystem/crio_node.env`

```
MQTT_BROKER=192.168.1.1
MQTT_PORT=1883
NODE_ID=crio-001
```

### Credentials File

Location on cRIO: `/home/admin/nisystem/mqtt_creds.json` (chmod 600, written by deploy script)

```json
{"mqtt_user": "...", "mqtt_pass": "...", "broker": "192.168.1.1", "node_id": "crio-001"}
```

### Project JSON

Channel configuration is pushed from the DAQ service via MQTT (`config/full` command). Channels are defined in the project JSON on the PC side with valid `ChannelType` values:

**Analog inputs:** `voltage_input`, `current_input`, `thermocouple`, `rtd`, `strain_input`, `bridge_input`, `iepe_input`, `resistance_input`
**Analog outputs:** `voltage_output`, `current_output`
**Digital:** `digital_input`, `digital_output`
**Counter/Timer:** `counter_input`, `counter_output`, `frequency_input`, `pulse_output`

cRIO modules require **DIFFERENTIAL** terminal configuration (not RSE). Use `TerminalConfiguration.DEFAULT` to let DAQmx auto-select.

---

## Service Commands

On the cRIO (SSH as `admin`):

```bash
# View logs (live)
ssh admin@192.168.1.20 "tail -f /home/admin/nisystem/logs/crio_node.log"

# Check if running
ssh admin@192.168.1.20 "pgrep -f run_crio_v2.py"

# Stop manually
ssh admin@192.168.1.20 "pkill -f run_crio_v2.py"

# Start manually (foreground, for debugging)
ssh admin@192.168.1.20 "cd /home/admin/nisystem && python3 run_crio_v2.py --broker 192.168.1.1"

# Start as daemon
ssh admin@192.168.1.20 "cd /home/admin/nisystem && python3 run_crio_v2.py --broker 192.168.1.1 --daemon"

# If systemd service is installed:
ssh admin@192.168.1.20 "systemctl status crio_node"
ssh admin@192.168.1.20 "systemctl restart crio_node"
ssh admin@192.168.1.20 "journalctl -u crio_node -f"
```

Or use the device CLI from the PC:

```cmd
device.bat logs crio --host 192.168.1.20 -f
```

---

## Differences from V1

| Aspect | V1 (`services/crio_node/`) | V2 (`services/crio_node_v2/`) |
|--------|---------------------------|-------------------------------|
| Architecture | Single 7,715-line monolith | 9 focused modules (~6,500 LOC total) |
| State machine | Implicit flags | Explicit states (IDLE/ACQUIRING/SESSION) with validated transitions |
| Safety | Basic threshold alarms | ISA-18.2: deadband, on/off delay, ROC, shelving, OUT_OF_SERVICE |
| Safety actions | String format only | String + structured dict format, `stop_session` action |
| Audit trail | None | SHA-256 hash chain, append-only JSONL, 10 MB rotation |
| Script engine | Limited helpers | Full helper library (Counter, RateCalculator, SignalFilter, etc.) |
| Publish rate | Uncontrolled | Token bucket rate limiter (4 Hz cap) |
| Comm watchdog | None | Configurable timeout, auto safe-state on PC disconnect |
| Hardware watchdog | None | Toggling digital output for external relay monitoring |
| Version reporting | None | Version, Python version, uptime in status/system message |
| Command queue | Blocking callbacks | Non-blocking queue, critical commands never dropped |
| MQTT library | paho-mqtt 1.x | paho-mqtt 2.x with auto-reconnect |
| Scan timing | Not tracked | Min/max/mean/jitter/overrun statistics |
| Error handling | Continues on error | 10 consecutive errors -> safe state + stop (requires manual restart) |
