# ICCSFlux Remote Nodes Guide

**Complete Guide to cRIO and Opto22 Remote Data Acquisition**

---

## Table of Contents

1. [Introduction](#1-introduction)
2. [Hardware Comparison](#2-hardware-comparison)
3. [cRIO Node v2](#3-crio-node-v2)
4. [Opto22 Node](#4-opto22-node)
5. [Multi-Node Architectures](#5-multi-node-architectures)
6. [Autonomy & Failover](#6-autonomy--failover)
7. [MQTT Topic Reference](#7-mqtt-topic-reference)
8. [Troubleshooting](#8-troubleshooting)

---

## 1. Introduction

### 1.1 What are Remote Nodes?

ICCSFlux remote nodes are standalone data acquisition services that run on embedded hardware (NI cRIO or Opto22 groov EPIC/RIO). They communicate with the central ICCSFlux PC via MQTT, enabling:

- **Distributed I/O** - Place hardware where sensors are located
- **Autonomous Operation** - Continue running if PC disconnects
- **Scalability** - Add more nodes as your system grows
- **Reliability** - Hardware-level safety independent of PC
- **Edge Intelligence** - Full script sandbox, ISA-18.2 alarms, and audit trail on every node

### 1.2 Architecture Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                    ICCSFlux Dashboard (Browser)                   │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐                │
│  │   Widgets   │ │   Charts    │ │  Controls   │                │
│  └─────────────┘ └─────────────┘ └─────────────┘                │
└──────────────────────────┬───────────────────────────────────────┘
                           │ WebSocket/MQTT
┌──────────────────────────▼───────────────────────────────────────┐
│                    ICCSFlux Backend (PC)                          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐            │
│  │   DAQ    │ │  Alarms  │ │ Scripts  │ │ Recording│            │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘            │
└─────────┬──────────────────────┬──────────────────┬──────────────┘
          │ MQTT                 │ MQTT              │ MQTT
    ┌─────▼─────┐         ┌─────▼──────┐     ┌─────▼──────────┐
    │   cDAQ    │         │ cRIO Node  │     │  Opto22 Node   │
    │  (Local)  │         │   v2       │     │  (Hybrid)      │
    │ USB/PCIe  │         │ NI-DAQmx   │     │ groov MQTT +   │
    └───────────┘         └────────────┘     │ Python Intel.  │
                                             └───────┬────────┘
                                                     │ groov Manage MQTT
                                             ┌───────▼────────┐
                                             │ groov EPIC I/O  │
                                             └────────────────┘
```

### 1.3 When to Use Remote Nodes

| Scenario | Recommended Hardware |
|----------|---------------------|
| Desktop testing | cDAQ (local) |
| Remote lab | cRIO or Opto22 |
| Harsh environment | cRIO (industrial rated) |
| Existing Opto22 system | Opto22 node |
| Multiple locations | Multiple remote nodes |
| Safety-critical | cRIO (hardware watchdog) |
| Deterministic PID control | Opto22 + CODESYS on groov EPIC |
| Step-based sequences | Opto22 (built-in sequence manager) |

---

## 2. Hardware Comparison

### 2.1 Platform Overview

| Feature | cDAQ | cRIO v2 | Opto22 |
|---------|------|---------|--------|
| Connection | USB/PCIe | Ethernet (MQTT) | Ethernet (MQTT) |
| Location | Same PC | Remote | Remote |
| Autonomy | No | Yes | Yes |
| I/O Access | NI-DAQmx | NI-DAQmx | groov Manage MQTT (REST fallback) |
| Watchdog | Software | Hardware (DAQmx) | Software |
| OS | Windows | NI Linux RT | groov OS |
| User | N/A | admin | dev |
| Script Sandbox | N/A (runs on PC) | Full (same as PC) | Full (same as PC) |
| ISA-18.2 Alarms | N/A (runs on PC) | Full (shelving, ROC, off-delay) | Full (shelving, ROC, off-delay) |
| Audit Trail | N/A (runs on PC) | SHA-256 hash chain | SHA-256 hash chain |
| PID Control | N/A (runs on PC) | N/A | Built-in + CODESYS bridge |
| Sequences | N/A (runs on PC) | N/A | Built-in sequence manager |
| Architecture | Monolithic reader | 9 modular files | 15 modular files |

### 2.2 Physical Channel Naming

Each hardware platform has a different naming convention:

```
┌────────────────────────────────────────────────────────────────┐
│ Physical Channel Naming by Hardware Type                       │
├────────────────────────────────────────────────────────────────┤
│                                                                │
│ cDAQ (Local):     cDAQ{chassis}Mod{slot}/{type}{channel}      │
│                   Example: cDAQ1Mod1/ai0                       │
│                                                                │
│ cRIO (Remote):    Mod{slot}/{type}{channel}                   │
│                   Example: Mod1/ai0                            │
│                                                                │
│ Opto22 (Remote):  {ioType}/{moduleIndex}/ch{channelIndex}     │
│                   Example: analogInputs/0/ch0                  │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

### 2.3 Channel Type Mapping

| Type | cDAQ | cRIO | Opto22 |
|------|------|------|--------|
| Analog Input | `/ai0` | `/ai0` | `analogInputs/0/ch0` |
| Analog Output | `/ao0` | `/ao0` | `analogOutputs/0/ch0` |
| Digital Input | `/di0` or `/port0/line0` | `/di0` | `digitalInputs/0/ch0` |
| Digital Output | `/do0` or `/port0/line0` | `/do0` | `digitalOutputs/0/ch0` |
| Counter | `/ctr0` | `/ctr0` | N/A |

---

## 3. cRIO Node v2

> **Note**: cRIO Node v2 (`services/crio_node_v2/`) replaces the deprecated v1 (`services/crio_node/`). The v1 monolith (7,715 lines) is no longer maintained. All new deployments should use v2.

### 3.1 Hardware Requirements

| Component | Requirement |
|-----------|-------------|
| Controller | NI CompactRIO with Linux Real-Time |
| Modules | Any NI C-Series I/O module |
| Network | Ethernet (100 Mbps minimum) |
| Storage | 256 MB free space |
| Python | 3.8+ (included in NI Linux RT) |

**Tested Controllers:** cRIO-9035, cRIO-9038, cRIO-9040, cRIO-9045, cRIO-9056

### 3.2 Deployment

**Always use `deploy_crio_v2.bat`** — do not manually scp files:

```cmd
deploy_crio_v2.bat [crio_host] [broker_host]
```

Defaults:
- `crio_host`: 192.168.1.20
- `broker_host`: 192.168.1.1

The deploy script copies all files, installs dependencies, and restarts the service.

#### Verify Deployment

```bash
ssh admin@<crio-ip>
systemctl status crio_node.service
journalctl -u crio_node -f
```

### 3.3 Modular Architecture

The v2 node is split into 9 focused modules (total ~8,200 LOC):

| File | LOC | Purpose |
|------|-----|---------|
| `crio_node.py` | 1,730 | Main service: event loop, MQTT commands, hardware read, script exec, safety checks |
| `script_engine.py` | 1,777 | Sandboxed user scripts with rate limiting (4 Hz cap) |
| `hardware.py` | 1,178 | NI-DAQmx abstraction, module auto-detect, MockHardware fallback |
| `config.py` | 520 | Config loading, channel scaling, project JSON parsing |
| `safety.py` | 378+ | ISA-18.2 alarms: shelving, off-delay, ROC, interlock trip actions |
| `channel_types.py` | 299 | Channel type definitions, NI module mappings |
| `state_machine.py` | 215 | Acquisition lifecycle: IDLE → ACQUIRING → SESSION |
| `mqtt_interface.py` | 337 | paho-mqtt wrapper with auto-reconnect and TLS support |
| `audit_trail.py` | ~150 | SHA-256 hash chain, append-only JSONL, 10 MB rotation |

**Main loop pattern:**
1. Process all pending MQTT commands (non-blocking queue)
2. Read channels (if acquiring) via NI-DAQmx
3. Check safety (single pass — alarms + interlocks)
4. Toggle watchdog output (if configured)
5. Publish values (rate-limited)

### 3.4 Safety & Alarms (ISA-18.2)

The cRIO node evaluates alarms locally, independent of the PC:

**Alarm States:**

```
NORMAL → ACTIVE → ACKNOWLEDGED → NORMAL
              ↘ RETURNED → ACKNOWLEDGED → NORMAL
SHELVED (operator suppressed, auto-expires)
OUT_OF_SERVICE (disabled for maintenance)
```

**Alarm Features:**

| Feature | Description |
|---------|-------------|
| Threshold Alarms | HIHI, HI, LO, LOLO with configurable deadband |
| Rate-of-Change | Detects fast-changing values over configurable period (default 60s), 20% hysteresis |
| On-Delay | Alarm must persist for N seconds before activating (prevents transient triggers) |
| Off-Delay | Alarm must clear for N seconds before returning to normal (prevents flicker) |
| Shelving | Operator can suppress an alarm for a set duration (auto-unshelves when timer expires) |
| Out-of-Service | Alarm disabled for maintenance (manual return-to-service required) |
| Safety Actions | On trip: set outputs, stop session. Supports legacy `set:ch:val` and dict format |

**Safety action formats:**
```python
# Legacy string format
"set:DO_Pump:0"

# New dict format
{"type": "set_digital_output", "channel": "DO_Pump", "value": 0}
{"type": "set_analog_output", "channel": "AO_Valve", "value": 0.0}
{"type": "stop_session"}
```

### 3.5 Script Engine

Full sandbox with the same API as the DAQ service PC:

- **Publish rate limiting**: TokenBucketRateLimiter caps at 4 Hz per channel
- **APIs**: `tags` (read values), `outputs` (write outputs), `session` (session info), `vars` (shared variables)
- **Helpers**: Counter, RateCalculator, Accumulator, EdgeDetector, RollingStats, SignalFilter, LookupTable, RampSoak, TrendLine, RingBuffer, PeakDetector, SpectralAnalysis, SPCChart, BiquadFilter, DataLog
- **Safety**: AST-based sandbox blocks all imports, dangerous builtins, and module access
- **Blocked list sync**: Script engine blocked lists MUST match `services/daq_service/script_manager.py`

### 3.6 Audit Trail

Lightweight 21 CFR Part 11-compatible audit trail:

- **Format**: Append-only JSONL at `/var/log/nisystem/audit.jsonl`
- **Integrity**: SHA-256 hash chain — each entry hashes the previous entry's hash + current payload
- **Events**: `alarm_trip`, `alarm_ack`, `alarm_shelve`, `safety_trip`, `safety_reset`, `config_change`, `session_start`, `session_stop`
- **Rotation**: Auto-rotates at 10 MB (gzip old file)
- **Tamper detection**: Verify chain integrity by recalculating hashes

### 3.7 Configuration

Environment file: `/home/admin/nisystem/crio_node.env`

```bash
MQTT_BROKER=192.168.1.100
MQTT_PORT=1883
NODE_ID=crio-001
```

To modify:
```bash
nano /home/admin/nisystem/crio_node.env
sudo systemctl restart crio_node.service
```

### 3.8 Service Commands

| Command | Description |
|---------|-------------|
| `systemctl status crio_node` | Check status |
| `systemctl start crio_node` | Start service |
| `systemctl stop crio_node` | Stop service |
| `systemctl restart crio_node` | Restart service |
| `systemctl enable crio_node` | Enable auto-start |
| `systemctl disable crio_node` | Disable auto-start |
| `journalctl -u crio_node -f` | View live logs |
| `journalctl -u crio_node -n 100` | View last 100 lines |

### 3.9 cRIO-Specific Troubleshooting

| Issue | Solution |
|-------|----------|
| Service won't start | Check `journalctl -u crio_node -n 50` |
| No I/O detected | Run `nilsdev` to list devices |
| MQTT connection fails | Verify PC IP and port 1883 accessible |
| Python errors | Ensure NI Linux RT has Python 3.8+ |
| Module not found | Check module is seated properly |
| Script errors | Check `journalctl` for sandbox violations |
| Audit file missing | Check `/var/log/nisystem/` permissions |

---

## 4. Opto22 Node

### 4.1 Hybrid Architecture

The Opto22 node uses a **hybrid architecture**: groov Manage's built-in MQTT broker publishes raw I/O data natively (zero Python for scanning), while the Python node subscribes and adds intelligence:

```
                                groov EPIC/RIO
┌──────────────────────────────────────────────────────────┐
│                                                          │
│  ┌──────────────┐    groov Manage MQTT   ┌────────────┐ │
│  │ I/O Modules  │ ──────────────────────►│ Python Node│ │
│  │ (AI,AO,DI,DO)│    (native speed)      │            │ │
│  └──────────────┘                        │ - Scripts   │ │
│                                          │ - Safety    │ │
│  ┌──────────────┐    REST API (fallback) │ - PID       │ │
│  │ groov Manage │ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ►│ - Sequences │ │
│  │   Web UI     │                        │ - Triggers  │ │
│  └──────────────┘                        │ - Audit     │ │
│                                          └──────┬─────┘ │
│  ┌──────────────┐    Modbus TCP (opt)           │       │
│  │   CODESYS    │ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─┘       │
│  │  (det. PID)  │                                       │
│  └──────────────┘                                       │
└──────────────────────────────┬───────────────────────────┘
                               │ ICCSFlux MQTT
                        ┌──────▼──────┐
                        │ ICCSFlux PC │
                        │ Mosquitto   │
                        └─────────────┘
```

**Dual MQTT connections:**
- **SystemMQTT**: Connects to ICCSFlux Mosquitto broker on the PC (publishes data, receives commands)
- **GroovMQTT**: Connects to groov Manage's built-in broker on the EPIC (subscribes to I/O topics)
- **REST fallback**: If groov MQTT is unavailable, falls back to groov Manage REST API

### 4.2 Hardware Requirements

| Component | Requirement |
|-----------|-------------|
| Controller | Opto22 groov EPIC or groov RIO |
| I/O | Any groov I/O module |
| Network | Ethernet (100 Mbps minimum) |
| User | `dev` account access |

**Tested Controllers:** groov EPIC PR1, groov EPIC PR2, groov RIO

### 4.3 Installation

#### Step 1: Copy Files to groov EPIC

```bash
scp -r services/opto22_node dev@<epic-ip>:/home/dev/
```

#### Step 2: SSH and Run Installer

```bash
ssh dev@<epic-ip>
cd /home/dev/opto22_node
chmod +x install.sh
./install.sh <ICCSFLUX_PC_IP> [NODE_ID] [API_KEY]
```

**Parameters:**
- `ICCSFLUX_PC_IP` - IP address of the ICCSFlux PC (required)
- `NODE_ID` - Unique identifier for this node (default: `opto22-001`)
- `API_KEY` - groov API key if authentication required (optional)

**Example:**
```bash
./install.sh 192.168.1.100 opto22-field
```

#### Step 3: Verify Installation

```bash
systemctl status opto22_node.service
journalctl -u opto22_node -f
```

### 4.4 Modular Architecture

15 modular files (total ~5,800 LOC), grouped by function:

**Core Infrastructure:**

| File | LOC | Purpose |
|------|-----|---------|
| `opto22_node.py` | 1,139 | Main service orchestrator, imports all modules |
| `state_machine.py` | ~200 | States: IDLE → CONNECTING_MQTT → ACQUIRING → SESSION |
| `mqtt_interface.py` | ~350 | Dual MQTT: SystemMQTT + GroovMQTT connections |
| `hardware.py` | ~400 | groov MQTT subscriber + REST API fallback |
| `config.py` | ~500 | NodeConfig, ChannelConfig, groov MQTT settings |
| `channel_types.py` | ~300 | ChannelType enum, Opto22 module database |

**Intelligence Layer (shared with cRIO v2):**

| File | LOC | Purpose |
|------|-----|---------|
| `script_engine.py` | ~1,800 | Sandboxed user scripts with 4 Hz rate limiting |
| `safety.py` | ~400 | ISA-18.2 alarms: shelving, off-delay, ROC, interlocks |
| `audit_trail.py` | ~150 | SHA-256 hash chain, append-only JSONL |

**Autonomous Features (Opto22-unique):**

| File | LOC | Purpose |
|------|-----|---------|
| `pid_engine.py` | ~120 | PID loops: auto/manual/cascade, anti-windup, derivative-on-PV |
| `sequence_manager.py` | ~130 | Step-based sequences: setOutput, wait, condition, loops |
| `trigger_engine.py` | ~50 | Rising-edge threshold detection → actions |
| `watchdog_engine.py` | ~60 | Stale data + out-of-range monitoring with recovery |

**Optional Integration:**

| File | LOC | Purpose |
|------|-----|---------|
| `codesys_bridge.py` | ~240 | Modbus TCP bridge to CODESYS runtime (deterministic PID) |

### 4.5 Opto22-Unique Features

These features run on Opto22 but not on cRIO:

#### PID Engine
- Auto/Manual/Cascade modes with bumpless transfer
- Anti-windup: clamp or back-calculation
- Derivative on PV (avoids setpoint kick) or error
- Configurable output limits

#### Sequence Manager
- Server-side sequences that survive browser disconnect
- Step types: `setOutput`, `waitDuration`, `waitCondition`, `logMessage`, `loopStart`, `loopEnd`
- Thread-based execution with pause/resume/abort

#### Trigger Engine
- Rising-edge detection on threshold crossings
- Operators: `>`, `<`, `>=`, `<=`, `==`
- Actions: setOutput, runSequence, notification

#### Watchdog Engine
- Stale data detection (no update within configurable timeout)
- Out-of-range detection (value outside min/max bounds)
- Trigger actions + recovery actions when condition clears

#### CODESYS Bridge (Optional)
For deterministic PID control on groov EPIC:

- Reads CODESYS variables via Modbus TCP
- Supports: float32, int16, uint16, int32, bool
- Tag mapping with scale/offset
- Configurable poll rate
- Read and write support (writable flag per tag)

```python
# Example CODESYS tag mapping
tag_map = {
    'PID1_PV': {'register': 40001, 'type': 'float32'},
    'PID1_CV': {'register': 40003, 'type': 'float32', 'writable': True},
    'PID1_SP': {'register': 40005, 'type': 'float32', 'writable': True}
}
```

### 4.6 groov Manage MQTT Setup

To use the hybrid MQTT architecture:

1. Log into groov Manage (`https://<epic-ip>`)
2. Navigate to **I/O** → **MQTT**
3. Enable the built-in MQTT broker
4. Configure I/O publishing topics (default: `groov/io/{module}/{channel}`)
5. Set the publish rate to match your scan requirements

The Python node subscribes to these topics and maps them to ICCSFlux channel names via config:

```bash
# In opto22_node.env
GROOV_MQTT_HOST=localhost
GROOV_MQTT_PORT=1883
```

If groov MQTT is not available (older firmware), the node automatically falls back to the REST API.

### 4.7 groov API Key Setup

If your groov EPIC requires authentication:

1. Open groov Manage in browser: `https://<epic-ip>`
2. Navigate to **Accounts** → **API Keys**
3. Click **Create API Key**
4. Give it a name (e.g., "ICCSFlux Node")
5. Ensure **I/O Access** permission is enabled
6. Copy the generated key
7. Add to environment file:
   ```bash
   nano /home/dev/nisystem/opto22_node.env
   # Add: API_KEY=your-api-key-here
   systemctl restart opto22_node.service
   ```

### 4.8 Configuration

Environment file: `/home/dev/nisystem/opto22_node.env`

```bash
# ICCSFlux MQTT Broker (PC)
MQTT_BROKER=192.168.1.100
MQTT_PORT=1883

# Node ID (unique per Opto22)
NODE_ID=opto22-001

# groov API Key (optional, for REST fallback)
API_KEY=

# groov Manage MQTT (local broker on EPIC)
GROOV_MQTT_HOST=localhost
GROOV_MQTT_PORT=1883
```

### 4.9 Service Commands

| Command | Description |
|---------|-------------|
| `systemctl status opto22_node` | Check status |
| `systemctl start opto22_node` | Start service |
| `systemctl stop opto22_node` | Stop service |
| `systemctl restart opto22_node` | Restart service |
| `systemctl enable opto22_node` | Enable auto-start |
| `systemctl disable opto22_node` | Disable auto-start |
| `journalctl -u opto22_node -f` | View live logs |

### 4.10 Opto22-Specific Troubleshooting

| Issue | Solution |
|-------|----------|
| Service won't start | Check `journalctl -u opto22_node -n 50` |
| REST API 401 error | API key required — see Section 4.7 |
| REST API 404 error | Check groov Manage is running |
| No I/O values via MQTT | Verify groov Manage MQTT is enabled |
| No I/O values via REST | Check groov Manage REST API: `curl -k https://localhost/api/v1/device/info` |
| CODESYS bridge errors | Verify Modbus TCP enabled in CODESYS, check port 502 |
| Script errors | Check `journalctl` for sandbox violations |
| Dual MQTT issues | Check both SystemMQTT (PC) and GroovMQTT (local) connections in logs |
| PID not responding | Verify PID is in AUTO mode and channels are acquiring |

---

## 5. Multi-Node Architectures

### 5.1 Single PC, Multiple Nodes

```
                       ┌─────────────────┐
                       │   ICCSFlux PC    │
                       │  MQTT Broker     │
                       │  192.168.1.100   │
                       └────────┬─────────┘
                                │
          ┌─────────────────────┼─────────────────────┐
          │                     │                     │
    ┌─────▼─────┐         ┌─────▼─────┐         ┌─────▼─────┐
    │ cRIO-001  │         │ cRIO-002  │         │opto22-001 │
    │  Lab A    │         │  Lab B    │         │  Field    │
    │ .101      │         │ .102      │         │ .103      │
    └───────────┘         └───────────┘         └───────────┘
```

Each node needs a unique NODE_ID. For cRIO, use the deploy script:
```cmd
deploy_crio_v2.bat 192.168.1.101 192.168.1.100
deploy_crio_v2.bat 192.168.1.102 192.168.1.100
```

For Opto22, use the install script on each EPIC:
```bash
./install.sh 192.168.1.100 opto22-001
```

### 5.2 Node Identification in Dashboard

Remote nodes appear in the Configuration tab discovery tree:

```
Hardware Discovery
├── cDAQ Devices (Local)
│   └── cDAQ1 [Online]
├── cRIO Nodes (Remote) [Blue]
│   ├── crio-001 [Online] ●
│   └── crio-002 [Online] ●
└── Opto22 Nodes (Remote) [Amber]
    └── opto22-001 [Online] ●
```

### 5.3 Channel Tag Naming Convention

For multi-node systems, include the node ID in tag names:

| Node | Channel | Suggested Tag |
|------|---------|---------------|
| crio-001 | Mod1/ai0 | `CRIO1_TC001` |
| crio-002 | Mod1/ai0 | `CRIO2_TC001` |
| opto22-001 | analogInputs/0/ch0 | `OPTO_AI001` |

---

## 6. Autonomy & Failover

### Why Edge Nodes Are the First Line of Defense

For safety-critical applications, remote nodes (cRIO, Opto22) provide autonomous protection that operates independently of the PC:

| Layer | Location | Role |
|-------|----------|------|
| **Primary** | Edge Node | Hardware watchdog, local interlock checks, safe state, alarms, audit trail |
| **Supervisory** | PC Backend | Enhanced ISA-18.2 alarms, coordination, recording, archival |
| **Display** | Browser | Visualization only — no safety decisions |

> **SIL Consideration**: ICCSFlux implements SIL 1 redundant validation — both the edge node AND the PC backend check interlocks before allowing output writes. This provides defense-in-depth: if either layer detects a safety condition, the output is blocked.

### 6.1 What Runs Locally on Remote Nodes

| Feature | cRIO v2 | Opto22 | PC |
|---------|---------|--------|----|
| I/O Read | Yes | Yes | |
| I/O Write | Yes | Yes | |
| ISA-18.2 Alarms | Yes (full) | Yes (full) | Yes (enhanced) |
| Alarm Shelving | Yes | Yes | Yes |
| Rate-of-Change Alarms | Yes | Yes | Yes |
| Safety Interlocks | Yes | Yes | Yes |
| Safe State | Yes | Yes | |
| Hardware Watchdog | Yes (DAQmx) | No | |
| Script Sandbox | Yes (full) | Yes (full) | Yes (full) |
| Audit Trail | Yes | Yes | Yes |
| PID Control | No | Yes | Yes |
| Sequences | No | Yes | Yes |
| Triggers | No | Yes | Yes |
| Watchdog Monitoring | No | Yes | Yes |
| Recording | No | No | Yes |
| Dashboard | No | No | Yes |

### 6.2 PC Disconnect Behavior

When the ICCSFlux PC goes offline:

1. **Detection** (configurable, default 30 seconds)
   - Node monitors PC heartbeat via communication watchdog
   - After timeout, node enters standalone mode

2. **Standalone Mode**
   - I/O continues reading at configured scan rate
   - Outputs maintain last commanded state
   - Safety limits continue to be evaluated (ISA-18.2 alarms stay active)
   - Scripts continue running
   - Audit trail continues logging events
   - Data is NOT recorded (requires PC)

3. **Reconnection**
   - Node automatically reconnects when PC comes back
   - Configuration is re-synced from PC
   - State is published to PC

### 6.3 Safety During PC Disconnect

Remote nodes maintain these safety features independently:

| Safety Feature | cRIO v2 | Opto22 |
|----------------|---------|--------|
| HIHI/HI/LO/LOLO Limits | Every scan | Every scan |
| Rate-of-Change Detection | Every scan | Every scan |
| Safety Trip Actions | Execute locally | Execute locally |
| Alarm Shelving | Active (auto-unshelve timers run locally) | Active |
| Hardware Watchdog | Active (DAQmx) | N/A |
| Software Watchdog | Active | Active |
| Audit Trail | Logging continues | Logging continues |
| PID Control | N/A | Continues running |
| Sequences | N/A | Active sequences continue |

### 6.4 Configuring Autonomous Safety

In your project configuration, channels have alarm settings that run on the remote node:

```json
{
  "alarms": [
    {
      "channel": "TC001",
      "enabled": true,
      "hihi_limit": 250,
      "hi_limit": 200,
      "lo_limit": 32,
      "lolo_limit": 0,
      "deadband": 2.0,
      "delay_seconds": 3.0,
      "off_delay_s": 5.0,
      "rate_of_change_limit": 10.0,
      "rate_of_change_period_s": 60.0,
      "actions": [
        {"type": "set_digital_output", "channel": "DO_Heater", "value": 0}
      ]
    }
  ]
}
```

---

## 7. MQTT Topic Reference

### 7.1 Topics Published by Nodes

All topics are prefixed with `nisystem/nodes/{node-id}/`.

| Topic | Description |
|-------|-------------|
| `channels/batch` | All channel values (JSON batch) |
| `channels/{name}` | Single channel value |
| `status/system` | Node status, version, uptime (retained) |
| `heartbeat` | Heartbeat every 2s |
| `session/status` | Session state |
| `alarms/event` | Alarm triggered/cleared event |
| `alarms/status` | Current alarm states |
| `alarms/ack/response` | Alarm acknowledge response |
| `safety/action` | Safety trip action executed |
| `safety/safe-state/ack` | Safe-state command acknowledgement |
| `safety/comm_watchdog` | Communication watchdog status |
| `command/ack` | Command acknowledgement |
| `config/response` | Config request response |

### 7.2 Topics Subscribed by Nodes

| Topic | Description |
|-------|-------------|
| `{base}/nodes/{node-id}/config/#` | Configuration updates |
| `{base}/nodes/{node-id}/commands/#` | Output write commands |
| `{base}/nodes/{node-id}/system/#` | Acquire start/stop |
| `{base}/nodes/{node-id}/session/#` | Session start/stop |
| `{base}/nodes/{node-id}/script/#` | Script management |
| `{base}/nodes/{node-id}/safety/#` | Safety commands (safe-state) |
| `{base}/nodes/{node-id}/alarm/#` | Alarm ack/shelve/unshelve |
| `{base}/nodes/{node-id}/console/#` | Interactive console (Opto22 only) |
| `{base}/discovery/ping` | Trigger status publish |

### 7.3 Alarm Command Topics

| Topic Suffix | Payload | Description |
|--------------|---------|-------------|
| `alarm/ack` | `{"channel": "TC001"}` | Acknowledge alarm |
| `alarm/shelve` | `{"channel": "TC001", "duration_s": 3600, "operator": "admin"}` | Shelve alarm |
| `alarm/unshelve` | `{"channel": "TC001"}` | Unshelve alarm |
| `alarm/out-of-service` | `{"channel": "TC001", "operator": "admin"}` | Set out of service |
| `alarm/return-to-service` | `{"channel": "TC001"}` | Return to service |

### 7.4 Message Formats

**Channel Value (batch):**
```json
{
  "TC001": {"value": 72.5, "timestamp": 1707000000.123, "quality": "good", "type": "input"},
  "DO_Pump": {"value": 1.0, "timestamp": 1707000000.123, "quality": "good", "type": "output"}
}
```

**Heartbeat:**
```json
{
  "node_id": "crio-001",
  "timestamp": 1707000000.123,
  "status": "online",
  "scan_count": 12345
}
```

**Status (retained):**
```json
{
  "node_id": "crio-001",
  "node_type": "crio",
  "version": "2.1.0",
  "python_version": "3.9.7",
  "uptime_s": 86400.5,
  "ip_address": "192.168.1.101",
  "status": "online",
  "acquiring": true,
  "session_active": true,
  "channels": 16,
  "modules": [
    {"slot": 1, "type": "NI 9211", "channels": 4}
  ]
}
```

**Alarm Event:**
```json
{
  "channel": "TC001",
  "state": "active",
  "severity": "critical",
  "value": 255.3,
  "limit": 250.0,
  "timestamp": 1707000000.123
}
```

---

## 8. Troubleshooting

### 8.1 Common Issues

| Symptom | Possible Cause | Solution |
|---------|---------------|----------|
| Node not in discovery | Network issue | Check ping to PC |
| Node shows offline | No heartbeat | Check service is running |
| No data from node | MQTT not connected | Verify broker IP |
| Writes not working | Interlock blocked | Check interlock status in dashboard |
| Safety not triggering | Limits not configured | Check alarm config in project JSON |
| Alarms stuck in SHELVED | Shelve timer expired but node restarted | Unshelve manually via MQTT |
| Script not executing | Sandbox violation | Check logs for blocked operation |
| Audit trail gap | Log file rotation | Check gzipped archives in `/var/log/nisystem/` |

### 8.2 Diagnostic Commands

**On cRIO:**
```bash
# Check service
systemctl status crio_node

# Check logs
journalctl -u crio_node -f

# List NI hardware
nilsdev

# Test MQTT connectivity to PC
mosquitto_pub -h <pc-ip> -t "test" -m "ping"

# Check network
ping <pc-ip>
ip addr

# Check audit trail
ls -la /var/log/nisystem/
```

**On Opto22:**
```bash
# Check service
systemctl status opto22_node

# Check logs
journalctl -u opto22_node -f

# Test groov REST API
curl -k https://localhost/api/v1/device/info

# Test groov MQTT (if mosquitto_sub available)
mosquitto_sub -h localhost -t "groov/io/#" -v

# Test ICCSFlux MQTT connectivity to PC
mosquitto_pub -h <pc-ip> -t "test" -m "ping"

# Check CODESYS Modbus (if configured)
# Port 502 should be open on CODESYS runtime
nc -zv localhost 502

# Check network
ping <pc-ip>
```

### 8.3 Log File Locations

| Platform | Log Method | Command |
|----------|------------|---------|
| cRIO | journald | `journalctl -u crio_node` |
| Opto22 | journald | `journalctl -u opto22_node` |
| PC | File | `data/logs/daq_service.log` |
| Audit (cRIO) | JSONL | `/var/log/nisystem/audit.jsonl` |
| Audit (Opto22) | JSONL | `/var/log/nisystem/audit.jsonl` |

### 8.4 Network Debugging

```bash
# Check if MQTT port is open on PC (from remote node)
nc -zv <pc-ip> 1883

# Check firewall (on PC)
netstat -ano | findstr :1883

# Monitor all MQTT traffic (on PC)
mosquitto_sub -h localhost -t "nisystem/#" -v

# Monitor specific node traffic
mosquitto_sub -h localhost -t "nisystem/nodes/crio-001/#" -v
```

### 8.5 Reinstallation

**cRIO:**
Use the deploy script from the PC — it handles everything:
```cmd
deploy_crio_v2.bat 192.168.1.20 192.168.1.100
```

**Opto22:**
```bash
ssh dev@<epic-ip>
systemctl stop opto22_node
rm -rf /home/dev/nisystem
cd /home/dev/opto22_node
./install.sh <pc-ip> <node-id>
```

---

## Support

For technical support:
- Detailed cRIO v2 docs: `services/crio_node_v2/README.md`
- Detailed Opto22 docs: `services/opto22_node/README.md`
- User Manual: `docs/ICCSFlux_User_Manual.md`
- Administrator Guide: `docs/ICCSFlux_Administrator_Guide.md`
- Contact your system administrator

---

**ICCSFlux Remote Nodes Guide v2.0**
*Last Updated: February 2026*
