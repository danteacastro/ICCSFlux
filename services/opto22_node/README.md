# Opto22 Node Service v2.0.0

Hybrid-architecture edge service for Opto22 groov EPIC/RIO integration with NISystem. groov Manage's built-in MQTT broker handles native I/O scanning at full speed (zero Python in the data path), while the Python node subscribes to that data and adds intelligence: scripts, safety, alarms, PID control, sequences, triggers, watchdogs, and MQTT integration with the NISystem dashboard.

## Quick Start

### 1. Copy files to groov EPIC

```bash
scp -r services/opto22_node dev@<epic-ip>:/home/dev/
```

### 2. Run installer on groov EPIC

```bash
ssh dev@<epic-ip>
cd /home/dev/opto22_node
chmod +x install.sh
./install.sh <PC_IP> [NODE_ID] [API_KEY]
```

Example:
```bash
./install.sh 192.168.1.100 opto22-001 your-api-key-here
```

The service will auto-start on boot, subscribe to groov Manage MQTT for I/O data, publish values to NISystem, and reconnect automatically on network drops.

## Architecture

```
NISystem PC                           groov EPIC/RIO
+-----------------+                   +-------------------------------+
|  DAQ Service    |  System MQTT      |  Opto22 Node (Python)        |
|  Dashboard      |<-- (1883) ------->|  - Script engine             |
|  Project Mgmt   |  config/data/cmds |  - Safety / ISA-18.2 alarms  |
+-----------------+                   |  - PID control loops          |
                                      |  - Sequences & triggers       |
                                      |  - Watchdog engine            |
                                      |  - Audit trail                |
                                      +------+------------------------+
                                             |  groov MQTT (localhost)
                                             |  subscribes to I/O topics
                                      +------v------------------------+
                                      |  groov Manage MQTT Broker     |
                                      |  publishes: groov/io/#        |
                                      +------+------------------------+
                                             |
                                      +------v--------+
                                      |  I/O Modules  |
                                      |  (AI,AO,DI,DO)|
                                      +---------------+

Fallback: If groov Manage MQTT is unavailable, the node
polls I/O via groov Manage REST API instead.
```

**Dual MQTT connections:**

| Connection | Broker | Direction | Purpose |
|------------|--------|-----------|---------|
| SystemMQTT | NISystem Mosquitto (PC) | Bidirectional | Publish data, receive config/commands |
| GroovMQTT | groov Manage (localhost) | Subscribe only | Receive native I/O values |

## Module Structure

### Core

| File | LOC | Purpose |
|------|-----|---------|
| `opto22_node.py` | 1,139 | Main service orchestrator, imports all modules, scan loop, MQTT dispatch |
| `state_machine.py` | ~200 | States: IDLE, CONNECTING_MQTT, ACQUIRING, SESSION. Validated transitions |
| `mqtt_interface.py` | ~350 | Dual MQTT: SystemMQTT (NISystem) + GroovMQTT (groov Manage). Auto-reconnect |
| `hardware.py` | ~400 | GroovIOSubscriber (MQTT-based) + GroovRestFallback (polling). Unified HardwareInterface |
| `config.py` | ~500 | NodeConfig, ChannelConfig, load/save, groov MQTT + REST settings |
| `channel_types.py` | ~300 | ChannelType enum + OPTO22_MODULES database (GRV-ITMI-8, GRV-IMA-8, etc.) |

### Intelligence

| File | LOC | Purpose |
|------|-----|---------|
| `script_engine.py` | ~1,800 | Sandboxed user scripts with helpers (RateCalculator, Accumulator, EdgeDetector, RollingStats). 4 Hz rate-limited publishing via TokenBucketRateLimiter |
| `safety.py` | ~400 | ISA-18.2 alarms: NORMAL/ACTIVE/ACKNOWLEDGED/RETURNED/SHELVED/OUT_OF_SERVICE. On/off delay, deadband, rate-of-change, interlock trip actions |
| `audit_trail.py` | ~150 | SHA-256 hash chain, append-only JSONL, 10 MB rotation with gzip archival |

### Autonomous Engines (Opto22-unique)

| File | LOC | Purpose |
|------|-----|---------|
| `pid_engine.py` | ~120 | PID loops: auto/manual/cascade, anti-windup (clamp/back-calculation), derivative-on-PV, bumpless transfer |
| `sequence_manager.py` | ~130 | Server-side sequences: setOutput, waitDuration, waitCondition, logMessage, loops. Survives browser disconnect |
| `trigger_engine.py` | ~50 | Rising-edge threshold detection with actions: setOutput, runSequence, notification |
| `watchdog_engine.py` | ~60 | Stale data + out-of-range monitoring with trigger/recovery actions |

### Optional

| File | LOC | Purpose |
|------|-----|---------|
| `codesys_bridge.py` | ~240 | Modbus TCP bridge to CODESYS runtime on groov EPIC. Reads/writes float32, int16, uint16, int32, bool. Tag mapping with scale/offset |

## Features

### Shared with cRIO v2

These features use the same design and API as the cRIO Node v2:

- **Script sandbox** -- AST-validated `exec()` with blocked imports, dunders, and builtins. Same helper classes (RateCalculator, Accumulator, EdgeDetector, RollingStats, SharedVariableStore). Same TagsAPI, OutputsAPI, SessionAPI, VarsAPI interfaces. 4 Hz rate-limited publishing.
- **ISA-18.2 alarms** -- Six-state alarm model (NORMAL, ACTIVE, ACKNOWLEDGED, RETURNED, SHELVED, OUT_OF_SERVICE). Configurable HIHI/HI/LO/LOLO limits, deadband, on-delay, off-delay, rate-of-change.
- **Safety interlocks** -- Backend-authoritative trip actions (set output, stop session). Output safety holds prevent override until alarm clears and is acknowledged.
- **Audit trail** -- SHA-256 hash chain in append-only JSONL. Tamper-evident. 10 MB rotation with gzip archival.
- **Session management** -- Named test sessions with operator, locked outputs, and timeout.
- **Interactive console** -- Remote Python REPL via MQTT with `tags`, `outputs`, `math`, and `numpy` (if available).

### Opto22-Unique Features

These features run only on the Opto22 node (not on cRIO):

- **PID engine** -- Full PID control loops running on the groov EPIC. Auto/manual/cascade modes. Anti-windup via clamping or back-calculation. Derivative-on-PV (default) or derivative-on-error. Bumpless transfer between modes. Output rate limiting. Status published to `pid/{loop_id}/status`.
- **Sequence manager** -- Server-side step-based automation that survives browser disconnects. Step types: `setOutput`, `waitDuration`, `waitCondition`, `logMessage`, `loopStart`/`loopEnd`. Supports pause/resume/abort. Condition evaluation with timeout.
- **Trigger engine** -- Value threshold triggers with rising-edge detection (fires once on transition). Operators: `>`, `<`, `>=`, `<=`, `==`. Actions: `setOutput`, `runSequence`, `notification`.
- **Watchdog engine** -- Multi-channel monitoring for stale data (no update within timeout) and out-of-range values (below min or above max). Trigger actions and recovery actions when condition clears.

### CODESYS Integration (Optional)

The `codesys_bridge.py` module reads CODESYS variables from groov EPIC via Modbus TCP and maps them to NISystem channels. This enables deterministic real-time control in CODESYS while NISystem handles data integration, alarms, and audit trail.

| Feature | Details |
|---------|---------|
| Protocol | Modbus TCP (port 502, localhost) |
| Data types | float32, int16, uint16, int32, bool |
| Tag mapping | Register address + type + scale + offset |
| Writable tags | Supported (must be marked `writable: true`) |
| Poll rate | Configurable (default 10 Hz) |
| Reconnect | Automatic with exponential backoff (2s to 30s) |

Example tag map:
```json
{
  "PID1_PV": {"register": 40001, "type": "float32", "scale": 1.0},
  "PID1_CV": {"register": 40003, "type": "float32", "scale": 1.0, "writable": true}
}
```

## groov Manage MQTT Setup

1. Open groov Manage in a browser: `https://<epic-ip>`
2. Go to **I/O** and configure your I/O modules
3. Go to **System** > **MQTT Broker** and enable the built-in broker
4. Configure I/O publishing -- groov Manage publishes module data on topics like `groov/io/<module>/<channel>`
5. Note the MQTT port (default 1883) and any authentication settings

The Python node subscribes to `groov/io/#` by default (configurable via `groov_io_topic_patterns`). Topic-to-channel mapping is configured either:

- **Per-channel**: Set `groov_topic` on each channel in the project config
- **Explicit mapping**: Use the `topic_mapping` config section (`{"groov/io/mod0/ch0": "TC_Zone1"}`)
- **Auto-derived**: If no mapping is configured, `groov/io/mod0/ch0` becomes `mod0_ch0`

## MQTT Topics

Base topic: `nisystem/nodes/{node-id}/`

### Published by Opto22 Node (to NISystem broker)

| Topic Suffix | QoS | Retain | Description |
|-------------|-----|--------|-------------|
| `channels/batch` | 0 | No | All channel values (batched, at publish rate) |
| `status/system` | 1 | Yes | Node status, version, uptime, channel count |
| `heartbeat` | 0 | No | Heartbeat with sequence number (every 2s) |
| `alarms/event` | 0 | No | Alarm state change events |
| `safety/triggered` | 0 | No | Safety action execution |
| `pid/{loop_id}/status` | 0 | No | PID loop status (PV, SP, CV, mode) |
| `sequence/{id}/{event}` | 1 | No | Sequence lifecycle events |
| `notifications` | 0 | No | Watchdog/trigger notifications |
| `config/response` | 0 | No | Config load acknowledgement |
| `command/response` | 0 | No | Command responses (ping, info) |
| `session/status` | 0 | No | Session state |
| `session/blocked` | 0 | No | Output write blocked by session lock |
| `status/safe-state` | 0 | No | Safe-state activation |
| `console/result` | 0 | No | Interactive console output |

### Subscribed by Opto22 Node (from NISystem broker)

| Topic Suffix | Description |
|-------------|-------------|
| `config/#` | Full configuration updates |
| `commands/#` | Ping, info, output write |
| `script/#` | Add/start/stop/remove/reload scripts |
| `system/#` | Acquire start/stop, reset, safe-state |
| `safety/#` | Alarm ack/shelve/unshelve, out-of-service |
| `session/#` | Session start/stop/ping |
| `console/#` | Interactive console execute/reset |
| `discovery/ping` | Trigger status publish (broadcast topic) |

### Subscribed from groov Manage Broker

| Topic Pattern | Description |
|--------------|-------------|
| `groov/io/#` | Raw I/O data from groov Manage (default, configurable) |

## Configuration

### Environment File

Located at `/home/dev/nisystem/opto22_node.env`:

```bash
# NISystem MQTT broker (PC)
MQTT_BROKER=192.168.1.100
MQTT_PORT=1883

# Node identity
NODE_ID=opto22-001

# groov API key (for REST fallback)
API_KEY=

# groov Manage MQTT broker (on the EPIC itself)
GROOV_MQTT_HOST=localhost
GROOV_MQTT_PORT=1883
```

### groov MQTT Settings (in project config)

```json
{
  "groov": {
    "mqtt_host": "localhost",
    "mqtt_port": 1883,
    "mqtt_username": null,
    "mqtt_password": null,
    "mqtt_tls": false,
    "io_topic_patterns": ["groov/io/#"]
  }
}
```

### CODESYS Bridge Settings (in project config)

```json
{
  "codesys": {
    "host": "localhost",
    "port": 502,
    "unit_id": 1,
    "poll_rate_hz": 10.0,
    "tag_map": {
      "PID1_PV": {"register": 40001, "type": "float32"},
      "PID1_CV": {"register": 40003, "type": "float32", "scale": 1.0, "offset": 0.0, "writable": true},
      "Pump_Running": {"register": 1, "type": "bool"}
    }
  }
}
```

### Channel Configuration

Channels can specify their groov MQTT topic and REST fallback coordinates:

```json
{
  "channels": {
    "TC_Zone1": {
      "physical_channel": "mod0/ch0",
      "channel_type": "thermocouple",
      "thermocouple_type": "K",
      "groov_topic": "groov/io/mod0/ch0",
      "groov_module_index": 0,
      "groov_channel_index": 0,
      "alarm_enabled": true,
      "hihi_limit": 500.0,
      "hi_limit": 400.0,
      "lo_limit": 10.0,
      "lolo_limit": 0.0,
      "safety_action": "set:Heater_Enable:0"
    }
  }
}
```

To change settings after installation:
```bash
nano /home/dev/nisystem/opto22_node.env
sudo systemctl restart opto22_node.service
```

## Service Commands

```bash
# Check status
systemctl status opto22_node.service

# View live logs
journalctl -u opto22_node.service -f

# Restart service
sudo systemctl restart opto22_node.service

# Stop service
sudo systemctl stop opto22_node.service

# Disable auto-start
sudo systemctl disable opto22_node.service
```

## Multiple groov EPICs

Give each EPIC a unique node ID:

```bash
# On EPIC #1
./install.sh 192.168.1.100 opto22-001

# On EPIC #2
./install.sh 192.168.1.100 opto22-002
```

## Differences from cRIO Node

| Feature | cRIO Node v2 | Opto22 Node v2 |
|---------|--------------|----------------|
| I/O access | NI-DAQmx (direct) | groov Manage MQTT + REST fallback |
| MQTT connections | 1 (System) | 2 (System + groov Manage) |
| State machine | IDLE / ACQUIRING / SESSION | IDLE / CONNECTING_MQTT / ACQUIRING / SESSION |
| PID control | Not available | Auto/manual/cascade, anti-windup, derivative-on-PV |
| Sequences | Not available | Server-side step-based automation |
| Triggers | Not available | Value threshold with rising-edge detection |
| Watchdog engine | Not available | Stale data + out-of-range monitoring |
| CODESYS bridge | Not available | Modbus TCP bridge to CODESYS runtime |
| Hardware watchdog | NI-DAQmx watchdog task | Software watchdog (output safe-state on timeout) |
| User | admin | dev |
| Install path | /home/admin/nisystem | /home/dev/nisystem |
| Safe state | DAQmx watchdog | Manual via REST API or MQTT command |
| Terminal config | Differential (NI modules) | N/A (groov Manage handles it) |
| Module database | NI cDAQ/cRIO modules | Opto22 GRV-series modules |

## Troubleshooting

### Service won't start
```bash
journalctl -u opto22_node.service -n 50
```
Check for Python import errors or missing dependencies.

### Can't connect to NISystem MQTT
1. Verify broker IP in `/home/dev/nisystem/opto22_node.env`
2. Test connectivity: `ping <nisystem-pc-ip>`
3. Check Mosquitto is running on the PC and listening on port 1883

### groov Manage MQTT not connecting
1. Verify the MQTT broker is enabled in groov Manage settings
2. Check the host/port in config (default: `localhost:1883`)
3. Look for `groov MQTT connected` in logs
4. If authentication is required, verify username/password in groov MQTT config

### Stuck in CONNECTING_MQTT state
The node enters CONNECTING_MQTT when waiting for the groov Manage MQTT broker. Check:
1. groov Manage MQTT broker is enabled and running
2. I/O topics are being published (check in groov Manage MQTT settings)
3. The node will fall back to REST polling if MQTT remains unavailable

### No I/O values
1. Ensure I/O modules are configured in groov Manage
2. Check topic mapping -- run `journalctl -u opto22_node.service | grep "groov MQTT subscribed"` to confirm subscription
3. Verify groov Manage is publishing I/O data (use an MQTT client like `mosquitto_sub -t "groov/io/#"` on the EPIC)
4. If using REST fallback, test the API: `curl -k https://localhost/manage/api/v1/io/local/modules/`

### REST API errors
1. Check if groov Manage API is accessible: `curl -k https://localhost/manage/api/v1/io/local/modules/`
2. Verify API key if authentication is enabled
3. REST is only used as fallback when groov Manage MQTT is unavailable

### CODESYS bridge not reading values
1. Verify CODESYS runtime is running on the groov EPIC
2. Check Modbus TCP is enabled in CODESYS (port 502)
3. Verify register addresses match the CODESYS variable mapping
4. Test Modbus connectivity: the bridge logs connection attempts to journald
5. Check `poll_rate_hz` is not set too high for the number of tags

### Network issues after reboot
The service waits for network and auto-reconnects both MQTT connections. Check:
```bash
ping <nisystem-pc-ip>
systemctl status opto22_node.service
```
