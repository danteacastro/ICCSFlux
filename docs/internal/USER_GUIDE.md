# ICCSFlux User Guide

## What is ICCSFlux?

ICCSFlux is an industrial data acquisition system that:
- Reads data from sensors, PLCs, and industrial devices
- Displays real-time values on a web dashboard
- Records data to files (CSV, TDMS)
- Manages alarms and notifications
- Runs automated sequences and scripts

## Quick Start

1. **Double-click `ICCSFlux.bat`**
2. Wait for the console to show "ICCSFlux is ready!"
3. Your browser opens to the dashboard automatically
4. Press Ctrl+C in the console to stop

## Running Modes

### Interactive Mode (Recommended for Testing)
```
Double-click: ICCSFlux.bat
```
- Shows console window with status messages
- Opens browser automatically
- Stop with Ctrl+C

### Background Mode (No Console Window)
```
Double-click: Start-Background.bat
Double-click: Stop-ICCSFlux.bat (to stop)
```
- Runs hidden in the background
- Open browser manually to http://localhost:5173

### Auto-Start on Login
```
Double-click: Install-AutoStart.bat (one time)
```
- ICCSFlux starts when you log in
- Stops when you log out
- Remove with: `Uninstall-AutoStart.bat`

### Windows Service (Runs 24/7)
```
Double-click: Install-Service.bat (run as Administrator)
```
- Starts at boot (before login)
- Runs even when logged out
- Auto-restarts on crash
- Manage via Services (services.msc)
- Remove with: `Uninstall-Service.bat`

## Dashboard Overview

### Main Areas

```
┌──────────────────────────────────────────────────────┐
│  [Logo]  Project Name           [Status] [Settings]  │  Header
├──────────────────────────────────────────────────────┤
│                                                      │
│   ┌─────────┐  ┌─────────┐  ┌─────────┐            │
│   │ Widget  │  │ Widget  │  │ Widget  │            │  Dashboard
│   │         │  │         │  │         │            │  Area
│   └─────────┘  └─────────┘  └─────────┘            │
│                                                      │
├──────────────────────────────────────────────────────┤
│  Acquiring: ON    Recording: OFF    Scan: 10ms      │  Status Bar
└──────────────────────────────────────────────────────┘
```

### Common Widgets

| Widget | Purpose |
|--------|---------|
| **Gauge** | Displays a single value with min/max range |
| **Trend Chart** | Shows value history over time |
| **Bar Graph** | Compares multiple values |
| **LED Indicator** | Shows on/off or alarm states |
| **Setpoint** | Adjustable value with slider |
| **Text Label** | Displays formatted text |

## Basic Operations

### Starting Data Acquisition

1. Click the **Play** button in the header, or
2. Press the **Start** button in the control panel

The status bar shows "Acquiring: ON" when running.

### Recording Data

1. Click the **Record** button (red circle)
2. Enter a filename (optional)
3. Click **Stop Recording** when done

Files are saved to `data/recordings/`

### Viewing Alarms

1. Click the **Alarms** icon in the header
2. Active alarms show in red
3. Click an alarm to acknowledge it
4. View alarm history in the Alarms panel

## Configuration

### System Configuration (config/system.ini)

Basic settings:
```ini
[system]
node_id = node-001
node_name = Lab System
simulation_mode = false
scan_rate_ms = 100

[mqtt]
broker_host = localhost
broker_port = 1883
```

### Adding Channels

In `system.ini`:
```ini
[channels]
Temp_1 = Dev1/ai0, thermocouple, K, 0, 1000, degC
Pressure = Dev1/ai1, voltage, 0-10V, 0, 100, PSI
Valve_Open = Dev1/port0/line0, digital_input
```

Format: `Name = Device/Channel, Type, Range, Min, Max, Unit`

### Modbus Devices

```ini
[modbus]
enabled = true
host = 192.168.1.100
port = 502
slave_id = 1

[modbus_channels]
Tank_Level = 40001, float32, 0, 100, %
Pump_Speed = 40003, uint16, 0, 1800, RPM
```

## Projects

Projects save your complete configuration including:
- Channel definitions
- Dashboard layout
- Alarm settings
- Scripts

### Creating a Project

1. Configure your system
2. Click **File > Save Project**
3. Enter a project name
4. Click **Save**

### Loading a Project

1. Click **File > Open Project**
2. Select the project
3. Click **Load**

Projects are saved in `config/projects/`

## Troubleshooting

### Dashboard won't load

**Check if services are running:**
- Open http://localhost:5173 manually
- Look for errors in the console window

**Port conflicts:**
- Port 1883 (MQTT) or 5173 (Web) may be in use
- Stop other applications using these ports

### No data showing

**Check acquisition is running:**
- Status bar should show "Acquiring: ON"
- Click Start if not running

**Check hardware:**
- NI MAX should show your device
- Run in simulation mode to test without hardware

### Connection lost

**MQTT broker stopped:**
- Restart ICCSFlux
- Check for Mosquitto errors

**Network issues:**
- Verify localhost is accessible
- Check firewall settings

### Service won't install

**Run as Administrator:**
- Right-click `Install-Service.bat`
- Select "Run as administrator"

**Check NSSM:**
- Verify `nssm/nssm.exe` exists
- Download from https://nssm.cc if missing

## File Locations

| Location | Contents |
|----------|----------|
| `config/` | Configuration files |
| `config/projects/` | Saved projects |
| `data/` | Runtime data |
| `data/recordings/` | Recorded data files |
| `data/logs/` | Service logs |
| `docs/` | Documentation |

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+S` | Save project |
| `Ctrl+O` | Open project |
| `Space` | Toggle acquisition |
| `R` | Toggle recording |
| `Escape` | Close dialogs |

## Getting Help

1. Check this guide and the README
2. Review logs in `data/logs/`
3. Contact your system administrator

## Specifications

- **Scan Rate:** 1ms - 10s configurable
- **Channels:** Up to 1000 per node
- **Data Sources:** NI DAQmx, Modbus TCP/RTU, OPC-UA, EtherNet/IP
- **Recording:** CSV, TDMS formats
- **Browser Support:** Chrome, Firefox, Edge (modern versions)
