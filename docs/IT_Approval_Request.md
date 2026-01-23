# NISystem (ICCSFlux) - IT Approval Request

**For:** SentinelOne Whitelist & Software Approval

---

## System Overview

NISystem (ICCSFlux) is an industrial data acquisition (DAQ) platform that:

- Reads sensor data from National Instruments hardware (thermocouples, RTDs, analog I/O)
- Communicates with CompactRIO (cRIO) controllers on the local network
- Displays real-time data on a web dashboard (Vue.js frontend)
- Provides alarm management, data recording, and safety interlocks

---

## Components Requiring Approval

| Component | Source | Purpose |
|-----------|--------|---------|
| **Mosquitto** | Eclipse Foundation (mosquitto.org) | MQTT message broker for device communication |
| **Python 3.11** | python.org (embedded) | Backend DAQ service |
| **Node.js/npm** | nodejs.org | Dashboard build tooling (dev only) |

---

## About Mosquitto MQTT

Mosquitto is the industry-standard open-source MQTT broker maintained by the Eclipse Foundation. It's used globally in IoT, industrial automation, and SCADA systems.

**Our configuration:**
- Port `1883` (MQTT) bound to `0.0.0.0` for cRIO device connections on local network
- Port `9002` (WebSocket) bound to `127.0.0.1` for local dashboard only
- Authentication can be enabled via `mosquitto_secure.conf` for production
- Logs errors only to stdout (no disk accumulation)

---

## Network Configuration

| Port | Protocol | Binding | Purpose |
|------|----------|---------|---------|
| 1883 | MQTT | `0.0.0.0` | Hardware communication (cRIO, Opto22, Modbus devices) |
| 9002 | WebSocket | `127.0.0.1` | Dashboard browser connection (localhost only) |
| 8080 | HTTP | `127.0.0.1` | Dashboard web server (localhost only) |

**Why port 1883 uses 0.0.0.0 binding:**
- The system communicates with National Instruments CompactRIO (cRIO) controllers on the local network
- cRIO devices publish sensor data and receive commands via MQTT
- This is standard for industrial SCADA/DCS architectures

**Dashboard ports (9002, 8080) are localhost only** - the dashboard can only be accessed from the machine running the system.

**Security notes:**
- Traffic stays on local/plant network (no internet routing required)
- Mosquitto supports authentication (password file + ACL) for production
- Firewall rules can restrict to specific device IPs if needed

---

## SOC2 / Compliance Features

The system includes controls aligned with SOC2:

| Control | Implementation |
|---------|----------------|
| **Audit Trail** | Append-only logs with SHA-256 hash chain, 365-day retention |
| **User Authentication** | Session-based auth with configurable timeout |
| **Role-Based Access** | Operator, Engineer, Admin roles with granular permissions |
| **Data Integrity** | Cryptographic verification prevents tampering |
| **Log Management** | Automatic rotation (50MB max per file), compression after 7 days |
| **Alarm History** | Capped at 1,000 entries to prevent unbounded growth |

---

## Files/Processes to Whitelist

### Portable Installation
```
dist\ICCSFlux-Portable\
├── ICCSFlux.bat              (launcher)
├── ICCSFlux.py               (Python launcher script)
├── mosquitto\mosquitto.exe   (MQTT broker)
├── python\python.exe         (embedded Python 3.11)
└── services\                 (Python backend scripts)
```

### Development Installation
```
NISystem\
├── start.bat                 (dev launcher)
├── service.bat               (Windows service manager)
├── venv\Scripts\python.exe   (Python virtual environment)
└── services\                 (Python backend scripts)
```

### System Mosquitto (if installed separately)
```
C:\Program Files\mosquitto\mosquitto.exe
```

---

## Security Summary

- **No internet connectivity required** - all communication is local/plant network
- **No telemetry or external data transmission**
- **All source code is internal/proprietary**
- **Standard industrial protocols** (MQTT, HTTP, Modbus)
- **Optional authentication** via password file and ACL

---

## Contact

For questions please contact me.
