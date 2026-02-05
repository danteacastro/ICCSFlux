# ICCSFlux - Configuration-Driven Data Acquisition for NI Hardware

A dynamic, configuration-driven alternative to LabVIEW for National Instruments cDAQ and cRIO hardware. Python backend with MQTT messaging, Vue 3 dashboard, and portable Windows deployment.

## Architecture

```
                        Vue 3 Dashboard
           (TypeScript, Tailwind, WebSocket MQTT)
                            |
                    WebSocket :9002
                            |
                   Mosquitto MQTT Broker
                   TCP :1883 (authenticated)
                    /                \
            DAQ Service           cRIO Node v2
             (Python)              (Python)
            nidaqmx /             Deployed via
           simulation              SSH/SCP
               |                      |
           NI cDAQ               NI cRIO-9035
         (USB/Ethernet)         (USB Ethernet)
```

**DAQ Service** (`services/daq_service/`) -- Python process that reads NI hardware (or runs in simulation mode), applies scaling/formulas, manages alarms, recording, scripting, PID loops, notifications, and publishes everything over MQTT.

**cRIO Node v2** (`services/crio_node_v2/`) -- Lightweight Python agent deployed to NI cRIO real-time hardware. Runs user scripts, reads/writes channels, and communicates back to DAQ via MQTT.

**Dashboard** (`dashboard/`) -- Vue 3 + TypeScript SPA with live data, trend charts, recording controls, script editor, safety monitor, configuration editor, and admin panel. Connects to MQTT over WebSocket.

**Portable Build** -- PyInstaller compiles the DAQ service, dashboard, and Mosquitto broker into a single `dist/ICCSFlux-Portable/` directory that runs on any Windows PC without Python or Node.js installed.

## Features

- **Configuration-Driven** -- All channels, scaling, limits, and safety defined in INI config files. Add/remove channels without code changes.
- **Simulation Mode** -- Full hardware simulation when no NI hardware is present. Develop and test anywhere.
- **Python Scripting Engine** -- Sandboxed `exec()` environment with 17 built-in helper classes:
  - Core: Counter, RateCalculator, Accumulator, EdgeDetector, RollingStats, Scheduler, StateMachine
  - Signal Processing: SignalFilter (EMA), LookupTable, RampSoak, TrendLine, RingBuffer, PeakDetector
  - Advanced (DAQ-only): SpectralAnalysis (FFT), SPCChart, BiquadFilter, DataLog
- **PID Control** -- Built-in PID engine with auto-tune, anti-windup, and output limiting.
- **Safety System** -- Configurable alarms, interlocks, and safety actions with dependency tracking.
- **Data Recording** -- CSV recording with rotation (size/time/samples), circular mode, ALCOA+ integrity (SHA-256 checksums, read-only files).
- **Test Sessions** -- Session lifecycle with variable resets, scheduler/recording/sequence automation, and timeout management.
- **Notifications** -- Twilio SMS and SMTP email alerts with 7-layer filtering (event type, severity, group, alarm selection, cooldown, daily limit, quiet hours).
- **Azure IoT Hub** -- Optional uploader pushes data to Azure for cloud analytics.
- **User Authentication** -- Role-based access control (Viewer, Operator, Supervisor, Admin) with session management.
- **cRIO Support** -- Deploy scripts to NI cRIO hardware over SSH. Group A helper classes available on both platforms; Group B raises clear errors on cRIO.

## Supported Hardware

| Type | Module Examples | Description |
|------|-----------------|-------------|
| Thermocouple | NI 9213 | Temperature measurement (J, K, T, E, N, S, R, B types) |
| Voltage | NI 9239, NI 9201 | Analog voltage input |
| Current | NI 9203 | 4-20 mA current loop |
| Digital Input | NI 9423 | Discrete input |
| Digital Output | NI 9472 | Discrete output |
| Analog Output | NI 9263 | Analog voltage output |
| Counter | NI 9361 | Counter/pulse input with rollover detection |

Also supports Modbus TCP/RTU, EtherNet/IP, OPC UA, and REST data sources.

## Quick Start

### Prerequisites

- Python 3.10+ with venv
- Node.js 18+ with npm
- Mosquitto MQTT broker

### Development

```bash
# Backend
python -m venv venv
venv\Scripts\activate
pip install -r services/daq_service/requirements.txt

# Dashboard
cd dashboard
npm install
npm run dev

# Start services
start.bat          # Starts MQTT broker + DAQ service
```

Dashboard opens at http://localhost:5173

### Portable Build

```bash
build.bat          # Builds portable exe (PyInstaller + npm build)
```

Output: `dist/ICCSFlux-Portable/` -- run `ICCSFlux.exe` on any Windows PC.

### cRIO Deployment

```bash
deploy_crio_v2.bat [crio_host] [broker_host]
```

Defaults: cRIO at 192.168.1.20, broker at 192.168.1.1.

## Project Structure

```
NISystem/
  config/                     # INI configuration files
  services/
    daq_service/              # Main DAQ service (~13k lines)
      daq_service.py          # Core service
      script_manager.py       # Script engine + 17 helper classes
      recording_manager.py    # CSV recording with ALCOA+ integrity
      alarm_manager.py        # Alarm management
      pid_engine.py           # PID control loops
      notification_manager.py # SMS + Email notifications
      safety_manager.py       # Interlocks and safety actions
      user_variables.py       # Session management + user variables
      ...
    crio_node_v2/             # cRIO agent (deployed to hardware)
      script_engine.py        # Script engine (11 helper classes + 4 stubs)
      crio_node.py            # Main node process
      ...
  dashboard/                  # Vue 3 + TypeScript SPA
    src/
      components/             # Vue components (tabs, modals, widgets)
      composables/            # Reusable logic (MQTT, auth, scripts)
      stores/                 # Pinia state management
      types/                  # TypeScript type definitions
  tests/                      # 477 tests across 7 unit test files
  scripts/                    # Build, deploy, and utility scripts
  docs/                       # User manual, scripting guide, admin guide
  vendor/                     # Offline dependencies for air-gapped builds
  dist/                       # Build output (portable exe)
```

## Testing

```bash
python -m pytest tests/test_daq_orchestration.py tests/test_longevity.py \
  tests/test_security_and_resilience.py tests/test_crio_script_engine_unit.py \
  tests/test_recording_manager.py tests/test_session_and_recording.py \
  tests/test_script_helpers.py -v
```

**477 tests** across 7 files -- no external dependencies required:

| File | Tests | Coverage |
|------|-------|---------|
| test_daq_orchestration.py | 68 | State machine, alarm manager, script sandbox, channel config |
| test_longevity.py | 32 | Counter rollover, cumulative mode, notification overflow, cleanup |
| test_security_and_resilience.py | 98 | Sandbox security, notification manager, state persistence |
| test_crio_script_engine_unit.py | 75 | cRIO helper classes, shared variables, APIs |
| test_recording_manager.py | 37 | Recording config, rotation, triggers, thread safety |
| test_session_and_recording.py | 63 | Session lifecycle, ALCOA+ integrity, acquisition cascade |
| test_script_helpers.py | 104 | All 10 new helper classes, cRIO stubs |

## Documentation

- [User Manual](docs/ICCSFlux_User_Manual.md) -- Complete operation guide
- [Python Scripting Guide](docs/ICCSFlux_Python_Scripting_Guide.md) -- Script API reference
- [Administrator Guide](docs/ICCSFlux_Administrator_Guide.md) -- Deployment and security
- [Remote Nodes Guide](docs/ICCSFlux_Remote_Nodes_Guide.md) -- cRIO deployment
- [Quick Reference](docs/ICCSFlux_Quick_Reference.md) -- One-page cheat sheet

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
| `nisystem/scripts/{id}/...` | Script management (create, start, stop, status) |
| `nisystem/pid/{loop}/...` | PID loop control and tuning |

## License

MIT License
