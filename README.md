# ICCSFlux — Configuration-Driven Industrial Data Acquisition & Control

A Python-based, open-architecture alternative to LabVIEW for National Instruments hardware and multi-vendor industrial I/O. Configuration-driven (JSON, not code), browser-based dashboard, distributed safety on real-time controllers, and portable single-exe deployment.

**~239k LOC** across 250+ files — Python backend, Vue 3 + TypeScript frontend, MQTT messaging.

## Architecture

```
                          Vue 3 Dashboard
             (TypeScript, Tailwind, WebSocket MQTT)
                              |
                      WebSocket :9002
                              |
                     Mosquitto MQTT Broker
              TCP :1883 (local)  |  TLS :8883 (remote)
                   /             |             \
           DAQ Service      cRIO Node       Opto22 Node
            (Python)         (Python)         (Python)
           nidaqmx /        NI-DAQmx        groov MQTT
          simulation                        + REST API
              |                |                |
          NI cDAQ           NI cRIO         Opto22 groov
        (USB/Ethernet)   (USB Ethernet)     EPIC / RIO
                                \              /
                          Modbus / OPC-UA / EtherNet-IP / REST
                            (additional data sources)
```
<img width="1911" height="1016" alt="image" src="https://github.com/user-attachments/assets/e94bb34f-312d-49e3-8421-085e737c4c4d" />
<img width="1911" height="1037" alt="image" src="https://github.com/user-attachments/assets/bab4d1c8-c227-40fb-83c3-f52af6bcc4b5" />

**DAQ Service** (`services/daq_service/`, ~13k lines) — Reads NI hardware (or simulation), manages alarms (ISA-18.2), interlocks (IEC 61511), recording, scripting, PID loops, notifications, user variables, and publishes over MQTT.

**Edge Nodes** — Lightweight Python agents deployed to remote controllers. Each runs safety logic independently (survives PC disconnect):
- **cRIO Node** (`services/crio_node_v2/`) — NI cRIO real-time controllers via SSH/SCP
- **Opto22 Node** (`services/opto22_node/`) — groov EPIC/RIO via groov Manage MQTT + REST
- **CFP Node** (`services/cfp_node/`) — NI Compact FieldPoint via Modbus

### Platform Maturity

| Platform | Status | Notes |
|----------|--------|-------|
| **NI cDAQ** (USB/Ethernet) | **Production** | Most mature. Continuous buffered acquisition, full channel type coverage, 72-hour soak tested. |
| **NI cRIO** (Real-Time) | **Production** | Most mature remote platform. 81-test HIL suite, loopback-verified I/O, safety interlocks, hot-unplug resilient. |
| **Opto22 groov EPIC/RIO** | Beta | CODESYS hybrid architecture works, Python fallback tested. Fewer field hours than cDAQ/cRIO. |
| **NI Compact FieldPoint** | Beta | Modbus bridge functional, safety synced from cRIO. Legacy hardware support. |
| **Modbus / OPC-UA / EtherNet-IP / REST** | Stable | Protocol readers tested, used as supplementary data sources alongside NI hardware. |

**Dashboard** (`dashboard/`) — Vue 3 + TypeScript SPA: live data, 30+ widget types, trend charts, P&ID editor (50+ SCADA symbols), ISA-101 HMI controls, script editor, safety monitor, recording, and admin panel.

**Portable Build** — PyInstaller compiles everything into `dist/ICCSFlux-Portable/` (~80 MB). Runs on any Windows PC without Python or Node.js.

## Features

- **Configuration-Driven** — Channels, scaling, alarms, interlocks, recording, PID, scripts, and dashboard layout defined in a single JSON project file. No application code changes needed.
- **Simulation Mode** — Full hardware simulation when no NI hardware is present. Develop and test anywhere.
- **Multi-Vendor Hardware** — NI cDAQ/cRIO, Opto22 groov EPIC/RIO, Modbus TCP/RTU, OPC-UA, EtherNet/IP (Allen-Bradley), REST APIs.
- **Python Scripting** — Sandboxed (AST-validated) engine with 17 built-in helper classes: SignalFilter, LookupTable, RampSoak, TrendLine, RingBuffer, PeakDetector, SpectralAnalysis, SPCChart, BiquadFilter, and more. Same API on DAQ service and edge nodes.
- **Safety System** — ISA-18.2 alarms (deadband, delays, rate-of-change, shelving, latch) + IEC 61511 interlocks (latch state machine, bypass tracking, demand counting, proof test). Runs on DAQ service and edge nodes independently.
- **PID Control** — Auto/manual/cascade modes, anti-windup, derivative-on-PV, bumpless transfer.
- **Data Recording** — CSV/TDMS with rotation (size/time/samples), circular mode, ALCOA+ integrity (SHA-256 hash chain, read-only, tamper detection).
- **Test Sessions** — Session lifecycle with variable resets, scheduler/recording/sequence automation, timeout management.
- **Notifications** — Twilio SMS + SMTP email with 7-layer filtering (event type, severity, group, alarm selection, cooldown, daily limit, quiet hours).
- **P&ID Editor** — Draw process diagrams with 50+ SCADA symbols, pipe routing (A* pathfinding), channel binding, runtime faceplates, multi-page support.
- **User Authentication** — Role-based access (Viewer, Operator, Supervisor, Admin) with session management, idle timeout, and audit trail.
- **Azure IoT Hub** — Optional uploader for cloud analytics (isolated process, separate paho-mqtt version).
- **AI-Assisted Scripting** — "Copy AI Context" button exports project context (channels, alarms, interlocks, variables) for use with any AI to generate scripts. See [docs/ai/](docs/ai/).

## Supported Hardware

| Type | NI Module Examples | Description |
|------|-------------------|-------------|
| Thermocouple | NI 9213 | Temperature (J, K, T, E, N, S, R, B types) |
| RTD | NI 9217 | Resistance temperature detector |
| Voltage Input | NI 9239, NI 9201, NI 9202 | Analog voltage |
| Current Input | NI 9203 | 4-20 mA current loop |
| Voltage Output | NI 9263, NI 9264 | Analog voltage output |
| Current Output | NI 9265, NI 9266 | Analog current output |
| Digital Input | NI 9423, NI 9425 | Discrete input |
| Digital Output | NI 9472, NI 9474 | Discrete output |
| Counter | NI 9361 | Counter/pulse with rollover detection |
| Strain / Bridge | NI 9237 | Strain gauge / Wheatstone bridge |
| IEPE | NI 9234 | Accelerometer / microphone |

**Additional protocols:** Modbus TCP/RTU (holding/input registers, coils), OPC-UA, EtherNet/IP (Allen-Bradley), REST API polling (BASIC, BEARER, API_KEY, OAUTH2 auth).

## Quick Start

### Prerequisites

- Python 3.11+ with venv
- Node.js 18+ with npm
- **NI-DAQmx drivers** (required for real hardware — download from [ni.com/downloads](https://www.ni.com/en/support/downloads/drivers/download.ni-daq-mx.html))

> **Important:** If NI-DAQmx is not installed, the system will automatically fall back to simulation mode and display a **SIM MODE** banner in the dashboard. All channel values will be simulated, not real hardware readings. If you see SIM MODE unexpectedly, verify that NI-DAQmx drivers are installed and your cDAQ hardware is connected.

### Development

```bash
# Backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

# Dashboard
cd dashboard && npm install

# Start everything (auto-generates MQTT credentials + TLS certs on first run)
start.bat
```

Dashboard opens at http://localhost:5173

### Portable Build

```bash
build.bat          # PyInstaller + npm build → dist/ICCSFlux-Portable/
```

Run `ICCSFlux.exe` on any Windows PC — no dependencies required. Auto-generates credentials, starts MQTT broker, DAQ service, and web dashboard.

### cRIO Deployment

```bash
deploy_crio_v2.bat [crio_host] [broker_host]
```

Defaults: cRIO at 192.168.1.20, broker at 192.168.1.1.

## Project Structure

```
ICCSFlux/
├── services/
│   ├── daq_service/              # Main DAQ service (~13k lines)
│   │   ├── daq_service.py        # Core: MQTT, scan loop, orchestration
│   │   ├── safety_manager.py     # IEC 61511 interlocks + latch state machine
│   │   ├── alarm_manager.py      # ISA-18.2 alarms
│   │   ├── script_manager.py     # Script sandbox + 17 helper classes
│   │   ├── recording_manager.py  # CSV/TDMS recording with ALCOA+
│   │   ├── pid_engine.py         # PID control loops
│   │   ├── notification_manager.py  # SMS + Email
│   │   └── ...                   # 20+ modules
│   ├── crio_node_v2/             # NI cRIO edge node
│   ├── opto22_node/              # Opto22 groov edge node
│   └── cfp_node/                 # NI Compact FieldPoint edge node
├── dashboard/                    # Vue 3 + TypeScript SPA
│   └── src/
│       ├── components/           # 40+ components (tabs, modals, P&ID)
│       ├── composables/          # 26 composables (MQTT, safety, auth, scripts)
│       ├── widgets/              # 30+ dashboard widget types
│       ├── stores/               # Pinia state management
│       └── types/                # TypeScript definitions
├── tests/                        # 558 unit tests + HIL + system validation
├── scripts/                      # Build, deploy, and utility scripts
├── config/                       # Project JSON files + TLS certs
├── docs/                         # User manual, admin guide, AI scripting docs
├── vendor/                       # Offline dependencies for air-gapped builds
└── dist/                         # Build output
```

## Testing

### Unit Tests (no external deps required)

```bash
python -m pytest tests/test_daq_orchestration.py tests/test_longevity.py \
  tests/test_security_and_resilience.py tests/test_crio_script_engine_unit.py \
  tests/test_recording_manager.py tests/test_session_and_recording.py \
  tests/test_script_helpers.py tests/test_safety_manager.py \
  tests/test_hot_unplug_resilience.py -v
```

**558 tests** across 9 files:

| File | Tests | Coverage |
|------|-------|---------|
| test_daq_orchestration.py | 68 | State machine, alarm manager, script sandbox, channel config |
| test_longevity.py | 32 | Counter rollover, cumulative mode, notification overflow, cleanup |
| test_security_and_resilience.py | 98 | Sandbox security (AST validation), notification manager, persistence |
| test_crio_script_engine_unit.py | 75 | cRIO helper classes, shared variables, APIs |
| test_recording_manager.py | 37 | Recording config, rotation, triggers, thread safety |
| test_session_and_recording.py | 63 | Session lifecycle, ALCOA+ integrity, acquisition cascade |
| test_script_helpers.py | 104 | SignalFilter, LookupTable, RampSoak, TrendLine, PeakDetector, etc. |
| test_safety_manager.py | 47 | Interlock latch (SAFE/ARMED/TRIPPED), conditions, bypass, persistence |
| test_hot_unplug_resilience.py | 34 | COMM_FAIL alarms, channel_offline, discovery staleness, Opto22 I/O |

### Dashboard Tests

```bash
cd dashboard && npx vitest run     # 2200+ tests
cd dashboard && npm run build      # Type check + production build
```

### System Validation (auto-starts services)

```bash
python -m pytest tests/test_system_validation.py -v   # 9-layer, 34 tests
python -m pytest tests/test_hardware_hil.py -v         # Hardware-in-the-loop, 4 tiers
```

### Hardware probe (real-hardware regression check)

`tools/hwreader_probe.py` is a standalone exerciser that drives `HardwareReader` directly against a real cDAQ chassis with no MQTT, no project loader, no dashboard — just the reader plus a watchdog. Useful for:

- Verifying NI-DAQmx / module configuration (per-module `terminal_config`, ADC timing, buffer mode) is producing valid task creation.
- Confirming reads/writes work end-to-end on every channel of every module before bringing up the full service.
- Catching driver hangs (Ctrl-Break dumps live thread stacks even if the process is wedged inside DAQmx).
- Smoke-testing changes to `services/daq_service/hardware_reader.py` without standing up the rest of the stack.

```bash
# Edit the CHANNELS / MODULES block at the top of tools/hwreader_probe.py
# to match your chassis device name (NI MAX) and slot layout.
python tools/hwreader_probe.py
```

Reports per-task health (reads, errors, recoveries, dropped samples, max lag), per-channel staleness, real readings on every AI/AO, and a final pass/fail summary including output write-and-readback verification. Auto-exits after the configured `MAX_DURATION_S` (default 12 s).

## MQTT Topics

| Topic Pattern | Description |
|--------------|-------------|
| `nisystem/channels/{name}` | Channel values (JSON: value, units, status) |
| `nisystem/commands/{name}` | Write commands to outputs |
| `nisystem/alarms/{source}` | Active alarms |
| `nisystem/status/system` | System status (state, scan rate, channels) |
| `nisystem/system/acquire/start\|stop` | Acquisition control |
| `nisystem/system/recording/start\|stop` | Recording control |
| `nisystem/system/session/start\|stop` | Session control |
| `nisystem/scripts/{id}/...` | Script management |
| `nisystem/pid/{loop}/...` | PID loop control |
| `nisystem/safety/interlocks` | Interlock status |

### MQTT Listeners

| Port | Transport | Auth | Purpose |
|------|-----------|------|---------|
| 1883 | TCP | Authenticated | Local services (DAQ, watchdog) |
| 8883 | TCP + TLS | Authenticated | Remote edge nodes (cRIO, Opto22, CFP) |
| 9002 | WebSocket | Anonymous | Dashboard (localhost only) |
| 9003 | WebSocket | Authenticated | Remote dashboards (LAN) |

## Documentation

- [User Manual](docs/ICCSFlux_User_Manual.md) — Complete operation guide
- [Python Scripting Guide](docs/ICCSFlux_Python_Scripting_Guide.md) — Script API reference
- [Administrator Guide](docs/ICCSFlux_Administrator_Guide.md) — Deployment and security
- [Remote Nodes Guide](docs/ICCSFlux_Remote_Nodes_Guide.md) — cRIO / Opto22 / CFP deployment
- [Quick Reference](docs/ICCSFlux_Quick_Reference.md) — One-page cheat sheet
- [AI Scripting Docs](docs/ai/) — Feed these to any AI to generate ICCSFlux scripts

## License

MIT License
