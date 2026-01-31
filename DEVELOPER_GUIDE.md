# ICCSFlux Developer Guide

## Architecture Overview

ICCSFlux is an industrial data acquisition system with these main components:

```
┌─────────────────────────────────────────────────────────────┐
│                      Dashboard (Vue 3)                       │
│                    http://localhost:5173                     │
└─────────────────────────┬───────────────────────────────────┘
                          │ WebSocket (MQTT over WS)
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                  Mosquitto MQTT Broker                       │
│              localhost:1883 (TCP) / :9001 (WS)              │
└─────────────────────────┬───────────────────────────────────┘
                          │ MQTT
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    DAQ Service (Python)                      │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────────────┐   │
│  │ Hardware    │ │ Modbus      │ │ Data Source Manager │   │
│  │ Reader      │ │ Reader      │ │ (OPC-UA, EtherNet/IP│   │
│  │ (NI DAQmx)  │ │ (TCP/RTU)   │ │  REST, S7)          │   │
│  └─────────────┘ └─────────────┘ └─────────────────────┘   │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────────────┐   │
│  │ Alarm       │ │ Script      │ │ Recording Manager   │   │
│  │ Manager     │ │ Manager     │ │ (CSV, TDMS)         │   │
│  └─────────────┘ └─────────────┘ └─────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## Directory Structure

```
NISystem/
├── services/
│   └── daq_service/          # Python backend
│       ├── daq_service.py    # Main service (~12,000 lines)
│       ├── alarm_manager.py  # Alarm handling
│       ├── script_manager.py # Python script execution
│       ├── modbus_reader.py  # Modbus TCP/RTU
│       ├── data_source_manager.py  # Multi-protocol abstraction
│       └── ...
├── dashboard/                # Vue 3 frontend
│   ├── src/
│   │   ├── components/       # Reusable components
│   │   ├── widgets/          # Dashboard widgets
│   │   ├── stores/           # Pinia stores
│   │   └── composables/      # Vue composables
│   └── package.json
├── config/                   # Configuration files
├── scripts/                  # Build and utility scripts
├── tests/                    # Python tests
├── vendor/                   # Offline dependencies
└── dist/                     # Build output
```

## Development Setup

### Prerequisites

- Python 3.11+
- Node.js 18+ (for dashboard development)
- Git

### Initial Setup

```bash
# Clone the repository
git clone <repository-url>
cd NISystem

# Create Python virtual environment
python -m venv venv
venv\Scripts\activate  # Windows
source venv/bin/activate  # Linux/Mac

# Install Python dependencies
pip install -r services/daq_service/requirements.txt

# Install dashboard dependencies
cd dashboard
npm install
cd ..
```

### Running in Development Mode

**Terminal 1 - MQTT Broker:**
```bash
# If Mosquitto is installed system-wide:
mosquitto -v

# Or use the portable version:
dist\ICCSFlux-Portable\mosquitto\mosquitto.exe -c dist\ICCSFlux-Portable\mosquitto\mosquitto.conf
```

**Terminal 2 - DAQ Service:**
```bash
cd services/daq_service
python daq_service.py -c ../../config/system.ini
```

**Terminal 3 - Dashboard (with hot reload):**
```bash
cd dashboard
npm run dev
```

Dashboard will be available at http://localhost:5173

## Building for Distribution

### Download Dependencies (one time)

```bash
python scripts/download_dependencies.py
```

This downloads:
- Python 3.11 embedded
- Python packages (wheels)
- Mosquitto binaries
- NSSM service manager
- Pre-builds dashboard

### Build Portable Package

```bash
# Uses vendor/ folder (no internet needed)
build.bat

# Or directly:
python scripts/build_portable.py --offline
```

Output: `dist/ICCSFlux-Portable/` (~70 MB)

## Testing

### Python Tests

```bash
# Run all tests
pytest tests/

# Run specific test file
pytest tests/test_alarm_manager.py

# Run with coverage
pytest --cov=services/daq_service tests/
```

### Dashboard Tests

```bash
cd dashboard
npm run test
```

## Code Style

### Python
- Follow PEP 8
- Use type hints
- Docstrings for public functions

### TypeScript/Vue
- Use composition API with `<script setup>`
- Pinia for state management
- Follow Vue style guide

## Key Files

| File | Purpose |
|------|---------|
| `services/daq_service/daq_service.py` | Main service, MQTT handlers, scan loop |
| `services/daq_service/config_parser.py` | INI file parsing |
| `services/daq_service/hardware_reader.py` | NI DAQmx interface |
| `services/daq_service/modbus_reader.py` | Modbus TCP/RTU |
| `services/daq_service/alarm_manager.py` | Alarm logic |
| `services/daq_service/script_manager.py` | User Python scripts |
| `dashboard/src/stores/dashboard.ts` | Main Pinia store |
| `dashboard/src/composables/useMqtt.ts` | MQTT connection |

## MQTT Topics

All topics are prefixed with `nisystem/nodes/{node_id}/`

| Topic | Direction | Purpose |
|-------|-----------|---------|
| `channels/values` | Pub | Channel values (JSON) |
| `status/system` | Pub | System status |
| `alarms/active` | Pub | Active alarms |
| `command/acquire/start` | Sub | Start acquisition |
| `command/acquire/stop` | Sub | Stop acquisition |
| `command/channel/set` | Sub | Set output value |

## Adding a New Data Source

1. Create a new class in `services/daq_service/` that inherits from `DataSource`
2. Implement `connect()`, `disconnect()`, `read_all()`, `read_channel()`, `write_channel()`
3. Register with `DataSourceManager.register_source_type()`
4. Add configuration parsing in `config_parser.py`

## Adding a New Dashboard Widget

1. Create `dashboard/src/widgets/MyWidget.vue`
2. Register in `dashboard/src/widgets/index.ts`
3. Add to widget palette in dashboard editor

## Troubleshooting

### Service won't start
- Check if ports 1883 (MQTT) and 5173 (web) are available
- Check `data/logs/` for error logs
- Verify config/system.ini exists

### No hardware detected
- Install NI-DAQmx drivers
- Check NI MAX for device names
- System runs in simulation mode if no hardware

### Dashboard not connecting
- Ensure MQTT broker is running
- Check browser console for WebSocket errors
- Verify WebSocket port 9001 is open

## Release Checklist

- [ ] All tests passing
- [ ] Version updated in `daq_service.py`
- [ ] CHANGELOG updated
- [ ] Build portable package
- [ ] Test on clean Windows machine
- [ ] Tag release in git
