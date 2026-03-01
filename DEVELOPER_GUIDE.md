# ICCSFlux Developer Guide

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Dashboard (Vue 3 + TypeScript)                │
│                      http://localhost:5173                       │
│    30+ widgets · P&ID editor · ISA-101 HMI · Script editor      │
└──────────────────────────┬──────────────────────────────────────┘
                           │ WebSocket :9002
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Mosquitto MQTT Broker                          │
│        TCP :1883 (local, auth) │ TLS :8883 (remote, auth)       │
│        WS :9002 (local, anon)  │ WS :9003 (remote, auth)        │
└──────────────────────────┬──────────────────────────────────────┘
           ┌───────────────┼───────────────┐
           ▼               ▼               ▼
┌─────────────────┐ ┌────────────┐ ┌──────────────┐
│   DAQ Service    │ │ cRIO Node  │ │ Opto22 Node  │
│   (Python)       │ │ (Python)   │ │ (Python)     │
│                  │ │            │ │              │
│ · NI-DAQmx      │ │ · NI-DAQmx │ │ · groov MQTT │
│ · Modbus TCP/RTU │ │ · Safety   │ │ · REST API   │
│ · OPC-UA         │ │ · Scripts  │ │ · Safety     │
│ · EtherNet/IP    │ │ · Alarms   │ │ · Scripts    │
│ · REST API       │ │            │ │              │
│ · Safety         │ └────────────┘ └──────────────┘
│ · Alarms         │        │               │
│ · Scripts        │    NI cRIO         Opto22 groov
│ · Recording      │  (real-time)       EPIC / RIO
│ · PID            │
│ · Notifications  │   Also: CFP Node (Modbus → NI Compact FieldPoint)
└─────────────────┘
```

## Directory Structure

```
NISystem/
├── services/
│   ├── daq_service/          # Main backend (~13k lines)
│   │   ├── daq_service.py    # Core: MQTT, scan loop, orchestration
│   │   ├── safety_manager.py # IEC 61511 interlocks
│   │   ├── alarm_manager.py  # ISA-18.2 alarms
│   │   ├── script_manager.py # Script sandbox + 17 helpers
│   │   ├── recording_manager.py  # CSV/TDMS with ALCOA+
│   │   ├── pid_engine.py     # PID control loops
│   │   ├── notification_manager.py  # SMS + Email
│   │   ├── hardware_reader.py  # NI-DAQmx continuous acquisition
│   │   ├── modbus_reader.py  # Modbus TCP/RTU
│   │   ├── opcua_source.py   # OPC-UA subscriptions
│   │   ├── rest_reader.py    # REST API polling
│   │   ├── ethernet_ip_source.py  # Allen-Bradley EtherNet/IP
│   │   ├── config_parser.py  # Project JSON parsing
│   │   ├── data_source_manager.py  # Unified multi-source reader
│   │   ├── user_variables.py # User variables + session management
│   │   ├── device_discovery.py  # NI hardware enumeration
│   │   └── ...
│   ├── crio_node_v2/         # NI cRIO edge node
│   ├── opto22_node/          # Opto22 groov edge node
│   └── cfp_node/             # NI Compact FieldPoint edge node
├── dashboard/                # Vue 3 frontend
│   └── src/
│       ├── components/       # 40+ components (tabs, modals, P&ID, HMI)
│       ├── composables/      # 26 composables (MQTT, safety, auth, scripts)
│       ├── widgets/          # 30+ widget types (chart, gauge, setpoint, etc.)
│       ├── stores/           # Pinia central store (~3400 lines)
│       ├── types/            # TypeScript definitions
│       ├── assets/symbols/   # 50+ SVG P&ID symbols
│       └── constants/        # P&ID symbol + HMI control catalogs
├── tests/                    # 558 unit + HIL + system validation tests
├── scripts/                  # Build, deploy, TLS, credentials
├── config/                   # Project JSON files, TLS certs, MQTT config
├── docs/                     # User-facing documentation
│   ├── ai/                   # AI scripting reference docs
│   └── internal/             # Internal-only docs (audits, analysis)
├── vendor/                   # Offline dependencies (air-gapped builds)
└── dist/                     # Build output
```

## Development Setup

### Prerequisites

- Python 3.11+
- Node.js 18+ with npm
- Git
- NI-DAQmx drivers (optional — simulation mode works without them)

### Initial Setup

```bash
# Clone
git clone <repository-url>
cd NISystem

# Python virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # Linux/Mac

# Install Python dependencies
pip install -r requirements.txt

# Dashboard
cd dashboard
npm install
cd ..
```

### Running in Development

The easiest way — starts MQTT broker, DAQ service, watchdog, Azure uploader, and dashboard dev server:

```bash
start.bat
```

On first run, this auto-generates:
- MQTT credentials (`config/mqtt_credentials.json`, `config/mosquitto_passwd`)
- TLS certificates (`config/tls/ca.crt`, `server.crt`, `server.key`)
- Dashboard `.env.local` with MQTT WebSocket credentials
- Admin password (`data/initial_admin_password.txt`)

Dashboard: http://localhost:5173

#### Manual startup (if needed)

**Terminal 1 — MQTT Broker:**
```bash
vendor\mosquitto\mosquitto.exe -c config\mosquitto.conf -v
```

**Terminal 2 — DAQ Service:**
```bash
python services/daq_service/daq_service.py
```

**Terminal 3 — Dashboard (hot reload):**
```bash
cd dashboard && npm run dev
```

## Configuration

ICCSFlux uses **JSON project files** (not INI). Projects live in `config/projects/`:

```json
{
  "name": "My Test Stand",
  "projectMode": "local",
  "channels": { ... },
  "safety": { "alarms": [...], "interlocks": [...] },
  "recording": { ... },
  "pythonScripts": { ... },
  "layout": { "pages": [...], "widgets": [...] }
}
```

Projects are managed through the dashboard Configuration tab or via MQTT commands.

## Building for Distribution

### Portable Build

```bash
build.bat
# Or directly:
python scripts/build_exe.py
```

Output: `dist/ICCSFlux-Portable/` (~80 MB) — native Windows executables via PyInstaller.

### Build Prerequisites

- PyInstaller 6.18.0+ (`pip install pyinstaller`)
- `vendor/mosquitto/mosquitto.exe` must exist
- npm installed for dashboard build

### Offline Dependencies

```bash
python scripts/download_dependencies.py
```

Populates `vendor/` for air-gapped builds.

## Testing

### Unit Tests (no external deps)

```bash
python -m pytest tests/test_daq_orchestration.py tests/test_longevity.py \
  tests/test_security_and_resilience.py tests/test_crio_script_engine_unit.py \
  tests/test_recording_manager.py tests/test_session_and_recording.py \
  tests/test_script_helpers.py tests/test_safety_manager.py \
  tests/test_hot_unplug_resilience.py -v
```

### Dashboard Tests

```bash
cd dashboard
npx vitest run          # 2200+ tests
npm run build           # Type check (vue-tsc) + production build
```

### System Validation (auto-starts MQTT + DAQ service)

```bash
python -m pytest tests/test_system_validation.py -v     # 9-layer, 34 tests
python -m pytest tests/test_hardware_hil.py -v           # Hardware-in-the-loop
```

## Key Files Reference

### Backend

| File | Purpose |
|------|---------|
| `services/daq_service/daq_service.py` | Main service: MQTT, scan loop, orchestration (~13k lines) |
| `services/daq_service/config_parser.py` | Project JSON parsing, ChannelType enum |
| `services/daq_service/safety_manager.py` | IEC 61511 interlocks, latch state machine |
| `services/daq_service/alarm_manager.py` | ISA-18.2 alarms |
| `services/daq_service/script_manager.py` | Script sandbox + 17 helper classes |
| `services/daq_service/recording_manager.py` | CSV/TDMS recording, ALCOA+ |
| `services/daq_service/hardware_reader.py` | NI-DAQmx continuous buffered acquisition |
| `services/daq_service/modbus_reader.py` | Modbus TCP/RTU client |
| `services/daq_service/data_source_manager.py` | Unified multi-source reader |
| `services/daq_service/notification_manager.py` | SMS + Email with rate limiting |

### Frontend

| File | Purpose |
|------|---------|
| `dashboard/src/stores/dashboard.ts` | Pinia central store (~3400 lines) |
| `dashboard/src/composables/useMqtt.ts` | MQTT WebSocket client |
| `dashboard/src/composables/useSafety.ts` | Alarm + interlock management |
| `dashboard/src/composables/useScripts.ts` | Script evaluation |
| `dashboard/src/composables/useAuth.ts` | Authentication + roles |
| `dashboard/src/types/index.ts` | Master TypeScript definitions |

## MQTT Topics

All topics prefixed with `nisystem/`:

| Topic | Direction | Purpose |
|-------|-----------|---------|
| `channels/{name}` | Pub | Channel values (JSON) |
| `commands/{name}` | Sub | Write to outputs |
| `status/system` | Pub | System state, scan rate |
| `alarms/{source}` | Pub | Active alarms |
| `safety/interlocks` | Pub | Interlock status |
| `system/acquire/start\|stop` | Sub | Acquisition control |
| `system/recording/start\|stop` | Sub | Recording control |
| `system/session/start\|stop` | Sub | Session control |
| `scripts/{id}/...` | Pub/Sub | Script management |
| `pid/{loop}/...` | Pub/Sub | PID loop control |

## Adding a New Data Source

1. Create a new class in `services/daq_service/` implementing `connect()`, `disconnect()`, `read_all()`, `read_channel()`, `write_channel()`
2. Register with `DataSourceManager.register_source_type()`
3. Add config parsing in `config_parser.py` (new `HardwareSource` enum value)
4. Add device config component in `dashboard/src/components/` (e.g., `MyDeviceConfig.vue`)
5. Wire into `ConfigurationTab.vue`

## Adding a New Dashboard Widget

1. Create `dashboard/src/widgets/MyWidget.vue` using `<script setup lang="ts">`
2. Register in `dashboard/src/widgets/index.ts` with type, label, default size, and config schema
3. Add config form in `WidgetConfigModal.vue`

## Safety System Architecture

Three-tier safety — edge nodes run interlocks independently of the PC:

| Layer | File | Independence |
|-------|------|-------------|
| DAQ Service | `safety_manager.py` | Backend-authoritative, full condition types |
| cRIO Node | `crio_node_v2/safety.py` | Survives PC disconnect |
| Opto22 Node | `opto22_node/safety.py` | Survives PC disconnect |
| CFP Node | `cfp_node/safety.py` | Survives PC disconnect |

Edge node safety files are synced copies — edit cRIO first, then copy to Opto22/CFP (changing only the logger name).

Interlocks are pushed from DAQ service to edge nodes during config sync. Edge nodes deserialize via `from_dict()` which accepts both camelCase and snake_case formats.

## Script Sandbox

User scripts run via `exec()` with AST-based validation (not process isolation). The sandbox blocks imports, dangerous dunders, dangerous builtins, and module access. All three script engines share the same blocked lists — keep them in sync:

- `services/daq_service/script_manager.py`
- `services/crio_node_v2/script_engine.py`
- `services/opto22_node/script_engine.py`

## cRIO Deployment

**Always use the deploy script:**

```bash
deploy_crio_v2.bat [crio_host] [broker_host]
```

Do NOT manually SCP files. The deploy script ensures all files are deployed atomically and verifies exactly one process is running (duplicate processes are a split-brain interlock hazard).

## Troubleshooting

### Service won't start
- Check if ports 1883, 8883, 9002, 5173 are available
- Check logs in `logs/` or console output
- Verify `config/mqtt_credentials.json` exists (auto-generated on first `start.bat`)

### No hardware detected
- Install NI-DAQmx drivers from [ni.com](https://www.ni.com/en/support/downloads/drivers/download.ni-daq-mx.html)
- Check NI MAX for device names
- System runs in simulation mode automatically if no hardware is present

### Dashboard not connecting
- Ensure MQTT broker is running on port 9002 (WebSocket)
- Check browser console for WebSocket errors
- Verify `config/mosquitto.conf` has the WebSocket listener configured
