# NISystem - NI cDAQ/cRIO Configuration-Driven Data Acquisition

A dynamic, configuration-driven alternative to LabVIEW for National Instruments cDAQ and cRIO hardware. Uses Python for hardware I/O, MQTT for messaging, and a Vue 3 dashboard for visualization and control.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Vue 3 Dashboard                          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────────┐ │
│  │Live Data │ │Recording │ │Safety    │ │Configuration   │ │
│  │& Trends  │ │Manager   │ │Monitor   │ │Editor          │ │
│  └──────────┘ └──────────┘ └──────────┘ └────────────────┘ │
└─────────────────────┬───────────────────────────────────────┘
                      │ MQTT (WebSocket)
┌─────────────────────┴───────────────────────────────────────┐
│                     MQTT Broker                             │
│                    (Mosquitto)                              │
└─────────────────────┬───────────────────────────────────────┘
                      │
       ┌──────────────┴──────────────┐
       │                             │
┌──────┴──────┐              ┌───────┴──────┐
│ DAQ Service │              │ cRIO Service │
│  (Python)   │              │ (LabVIEW RT) │
│   nidaqmx   │              │    MQTT      │
└──────┬──────┘              └───────┬──────┘
       │                             │
   ┌───┴───┐                    ┌────┴────┐
   │ cDAQ  │                    │  cRIO   │
   └───────┘                    └─────────┘
```

## Features

- **Configuration-Driven**: All channels, scaling, limits, and safety defined in INI files
- **Dynamic**: Add/remove channels by editing config, no code changes needed
- **Simulation Mode**: Full simulation when no hardware present
- **Safety System**: Configurable interlocks and safety actions with dependency tracking
- **Data Recording**: CSV logging with configurable rotation, triggers, and scheduling
- **Vue 3 Dashboard**: Modern, responsive UI with real-time data visualization
- **Scripting Engine**: Custom formulas and computed parameters
- **MQTT Messaging**: Standard protocol, easy to extend

## Supported Platforms

- **Linux** (primary development platform)
- **Windows 10/11** (production deployment)

## Quick Start

### 1. Install Dependencies

**Linux:**
```bash
./scripts/install_dependencies.sh
```

**Windows:**
```powershell
.\scripts\install_dependencies.ps1
```

This installs:
- Python 3.10+ with virtual environment
- Node.js and npm
- Mosquitto MQTT broker
- Python packages (paho-mqtt, python-dateutil)

### 2. Start All Services

**Linux:**
```bash
./scripts/start_all.sh
```

**Windows:**
```powershell
.\scripts\start_all.ps1
```

### 3. Start the Dashboard

```bash
cd dashboard
npm install
npm run dev
```

Then open: http://localhost:5173

### 4. Monitor MQTT Traffic

```bash
mosquitto_sub -h localhost -t 'nisystem/#' -v
```

## Project Structure

```
NISystem/
├── config/
│   └── system.ini              # Main configuration file
├── services/
│   └── daq_service/
│       ├── daq_service.py      # Main DAQ service
│       ├── config_parser.py    # INI file parser
│       ├── simulator.py        # Hardware simulator
│       ├── recording_manager.py # Data recording
│       ├── dependency_tracker.py # Config validation
│       ├── scaling.py          # Value scaling
│       ├── scheduler.py        # Automated scheduling
│       └── requirements.txt
├── dashboard/
│   ├── src/
│   │   ├── components/         # Vue components
│   │   ├── composables/        # Reusable logic (MQTT, scripts, safety)
│   │   ├── stores/             # Pinia state management
│   │   ├── widgets/            # Dashboard widgets
│   │   └── types/              # TypeScript definitions
│   └── package.json
├── scripts/
│   ├── install_dependencies.sh  # Linux installer
│   ├── install_dependencies.ps1 # Windows installer
│   ├── start_all.sh            # Linux startup
│   ├── start_all.ps1           # Windows startup
│   └── stop_all.sh             # Linux shutdown
├── tests/
│   ├── test_e2e_mqtt.py        # End-to-end tests
│   ├── test_all_commands.py    # Command tests
│   └── test_topic_alignment.py # MQTT topic tests
├── data/                       # Recorded data files
└── logs/                       # Runtime logs
```

## Configuration (system.ini)

The configuration file defines everything about your system:

### System Settings
```ini
[system]
mqtt_broker = localhost
mqtt_port = 1883
scan_rate_hz = 100
simulation_mode = true
```

### Chassis & Modules
```ini
[chassis:cDAQ-9178-1]
type = cDAQ-9178
connection = USB

[module:cDAQ1Mod1]
type = NI9213
chassis = cDAQ-9178-1
slot = 1
```

### Channels
```ini
[channel:furnace_zone1_temp]
module = cDAQ1Mod1
physical_channel = ai0
channel_type = thermocouple
thermocouple_type = K
units = degC
low_limit = 0
high_limit = 1200
safety_action = shutdown_heaters
log = true
```

### Safety Actions
```ini
[safety_action:shutdown_heaters]
description = Shutdown all heater zones
actions = heater_zone1:false, heater_zone2:false
trigger_alarm = true
alarm_message = High temperature - heaters disabled
```

## MQTT Topics

| Topic | Description |
|-------|-------------|
| `nisystem/channels/{name}` | Channel values (JSON with value, units, status) |
| `nisystem/commands/{name}` | Write commands to outputs |
| `nisystem/alarms/{source}` | Active alarms |
| `nisystem/status/system` | Comprehensive system status |
| `nisystem/config/channels` | Channel configuration |
| `nisystem/config/current` | Full config snapshot |
| `nisystem/system/acquire/start` | Start data acquisition |
| `nisystem/system/acquire/stop` | Stop acquisition |
| `nisystem/system/recording/start` | Start recording |
| `nisystem/system/recording/stop` | Stop recording |
| `nisystem/recording/config` | Recording configuration |
| `nisystem/dependencies/validate` | Validate config integrity |

## Channel Types Supported

| Type | Module Examples | Description |
|------|-----------------|-------------|
| `thermocouple` | NI9213 | Temperature measurement |
| `voltage` | NI9239, NI9201 | Analog voltage input |
| `current` | NI9203 | 4-20mA current loop |
| `digital_input` | NI9423 | Digital/discrete input |
| `digital_output` | NI9472 | Digital/discrete output |
| `analog_output` | NI9263 | Analog voltage output |
| `counter` | NI9361 | Counter/pulse input |

## Adding Real Hardware

1. Set `simulation_mode = false` in system.ini
2. Install NI-DAQmx drivers from ni.com
3. Install nidaqmx Python package:
   ```bash
   pip install nidaqmx
   ```
4. Update chassis serial numbers and module configurations

## Dashboard Features

- **Live Data Display**: Real-time channel values with configurable widgets
- **Trend Charts**: Time-series plotting with multiple channels
- **Recording Manager**: Configure and control data recording
- **Safety Monitor**: View and manage safety actions and alarms
- **Configuration Editor**: Edit channels, modules, and safety actions
- **Script Editor**: Create custom formulas and computed parameters
- **Customizable Layout**: Drag-and-drop widget arrangement

## Running Tests

```bash
cd tests
pytest -v
```

Tests require MQTT broker and DAQ service to be running.

## Troubleshooting

### MQTT Connection Failed
```bash
# Linux
sudo systemctl status mosquitto
sudo systemctl start mosquitto

# Windows
net start mosquitto
```

### No Data in Dashboard
```bash
# Check MQTT traffic
mosquitto_sub -h localhost -t 'nisystem/#' -v

# Check DAQ service logs
tail -f logs/daq_service.log
```

### Config Not Loading
```bash
# Test config parser directly
cd services/daq_service
python config_parser.py
```

## License

MIT License - Use freely for your projects.
