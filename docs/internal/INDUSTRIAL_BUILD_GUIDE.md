# ICCSFlux Industrial-Grade Portable Build

## Overview

The ICCSFlux portable system is now built as **native Windows executables** with **industrial-grade reliability** features including automatic service restart, dependency management, and proper error handling.

---

## Build System

### Quick Start

```cmd
build.bat
```

This runs the complete build process:
1. Compiles all services to executables using PyInstaller
2. Builds the Vue dashboard to static files
3. Packages everything into `dist/ICCSFlux-Portable/`

### Prerequisites

- Python 3.8+ with PyInstaller installed (`pip install pyinstaller`)
- Node.js + npm (for building the dashboard)
- Vendor folder populated (run `python scripts\download_dependencies.py`)

---

## Architecture

### Executables (Native .exe files)

| Executable | Size | Purpose |
|-----------|------|---------|
| **ICCSFlux.exe** | ~8 MB | Main launcher + HTTP server for dashboard |
| **DAQService.exe** | ~49 MB | Data acquisition backend |
| **AzureUploader.exe** | ~15 MB | Azure IoT Hub integration (optional) |
| **mosquitto.exe** | ~6 MB | MQTT broker (third-party) |
| **nssm.exe** | ~324 KB | Windows service manager (third-party) |

### Dashboard (Browser-based UI)

The dashboard is **NOT an executable** - it's a browser-based Vue.js application served as static files:

```
ICCSFlux.exe → Embedded HTTP server → Serves www/ static files
                                           ↓
User's Browser ← http://localhost:5173 ← Vue dashboard
                                           ↓
Dashboard ← WebSocket (MQTT) → Backend services
```

**Why browser-based?**
- Smaller size (16 MB vs 100+ MB for Electron)
- Access from any device with a browser (PC, tablet, phone)
- Easy updates (just replace static files)
- True separation of concerns (UI in browser, logic in services)
- **This is the CORRECT architecture for industrial systems**

---

## Portable Distribution Structure

```
ICCSFlux-Portable/             Total: ~75-80 MB
├── ICCSFlux.exe               # 8 MB - Launcher
├── DAQService.exe             # 49 MB - DAQ backend
├── AzureUploader.exe          # 15 MB - Azure uploader (optional)
├── ICCSFlux.bat               # Simple batch launcher
├── Install-Service.bat        # Install as Windows services
├── Uninstall-Service.bat      # Remove services
├── README.txt
│
├── mosquitto/                 # 6.3 MB - MQTT broker
│   ├── mosquitto.exe
│   ├── *.dll
│   └── mosquitto.conf
│
├── nssm/                      # 324 KB - Service manager
│   └── nssm.exe
│
├── www/                       # 16 MB - Dashboard (Vue.js static files)
│   ├── index.html
│   ├── assets/
│   └── ...
│
├── config/                    # 1.5 MB - Configuration files
│   ├── system.ini
│   ├── channels.json
│   └── ...
│
├── azure/                     # Config for Azure (if used)
│   └── azure_uploader.ini.example
│
├── data/                      # Runtime data (empty initially)
│   ├── recordings/
│   ├── logs/
│   └── audit/
│
└── docs/                      # 164 KB - User documentation
    ├── 01_Getting_Started.md
    ├── 02_Quick_Reference.md
    └── ...
```

---

## Industrial-Grade Reliability Features

### 1. Automatic Service Restart

All services are configured to **automatically restart on failure**:

```batch
# NSSM configuration applied to all services:
nssm set <service> AppExit Default Restart      # Restart on any exit
nssm set <service> AppRestartDelay 5000         # Wait 5 seconds before restart
nssm set <service> AppThrottle 10000            # Throttle rapid restarts
```

**What this means:**
- If a service crashes, it automatically restarts after 5 seconds
- Prevents rapid restart loops (throttling)
- Industrial-grade uptime and reliability

### 2. Service Dependencies

Services start in the correct order:

```
ICCSFlux-MQTT (Mosquitto)
    ↓
ICCSFlux-DAQ (depends on MQTT)
    ↓
ICCSFlux-Azure (depends on MQTT)
    ↓
ICCSFlux-Web (depends on DAQ)
```

If MQTT fails, dependent services wait for it to restart.

### 3. Log Rotation

All services have automatic log rotation to prevent disk space issues:

```batch
nssm set <service> AppRotateFiles 1             # Enable rotation
nssm set <service> AppRotateBytes 10485760      # Rotate at 10 MB
```

**What this means:**
- Logs automatically rotate when they reach 10 MB
- Prevents disk space exhaustion
- Industrial best practice

### 4. Single Instance Lock

ICCSFlux.exe uses a lockfile to prevent multiple instances:

```
data/.iccsflux.lock
```

- Only one instance can run at a time
- Prevents port conflicts and data corruption
- Automatic cleanup on exit

---

## Running ICCSFlux

### Interactive Mode (with console)

```cmd
ICCSFlux.bat
```

or

```cmd
ICCSFlux.exe
```

**Features:**
- Shows startup messages and status
- Opens browser automatically
- Press Ctrl+C to stop
- Ideal for development and testing

### As Windows Services (runs even when logged out)

```cmd
# Install (run as Administrator)
Install-Service.bat

# The installer creates 4 services:
#   ICCSFlux-MQTT   - MQTT broker
#   ICCSFlux-DAQ    - Data acquisition
#   ICCSFlux-Azure  - Azure uploader (if AzureUploader.exe exists)
#   ICCSFlux-Web    - Dashboard web server

# Services auto-start on boot and auto-restart on failure
```

**To uninstall:**

```cmd
Uninstall-Service.bat
```

**Service Features:**
- Auto-start on Windows boot
- Run even when logged out
- Auto-restart on failure
- Managed via Windows Services (services.msc)
- Industrial-grade reliability

---

## Building from Source

### Step-by-Step

1. **Populate vendor folder** (first time only):
   ```cmd
   python scripts\download_dependencies.py
   ```

2. **Build the portable package**:
   ```cmd
   build.bat
   ```

3. **Output location**:
   ```
   dist\ICCSFlux-Portable\
   ```

### Build Process Details

The build process (`build_exe.py`):

1. **Compiles executables** using PyInstaller:
   - DAQService.exe from `services/daq_service/`
   - ICCSFlux.exe from `scripts/ICCSFlux_exe.py`
   - AzureUploader.exe from `services/azure_uploader/`

2. **Builds dashboard** using npm:
   - Runs `npm run build` in `dashboard/`
   - Outputs to `dashboard/dist/`

3. **Copies dependencies**:
   - Mosquitto from `vendor/mosquitto/`
   - NSSM from `vendor/nssm/`
   - Configuration files from `config/`
   - Documentation from `docs/`

4. **Creates installers**:
   - Service installer batch files
   - Simple launchers
   - README

### Quick Mode (skip recompilation)

If you've already compiled the executables and only changed config/dashboard:

```cmd
python scripts\build_exe.py --quick
```

This skips PyInstaller compilation and just packages everything.

---

## Size Optimization

The portable distribution is optimized to be **75-80 MB total**:

| Component | Size | Notes |
|-----------|------|-------|
| DAQService.exe | 49 MB | Includes NumPy/SciPy for signal processing |
| ICCSFlux.exe | 8 MB | Lightweight launcher |
| AzureUploader.exe | 15 MB | Optional, only if using Azure |
| www/ | 16 MB | Vue dashboard static files |
| mosquitto/ | 6.3 MB | MQTT broker + DLLs |
| config/ | 1.5 MB | Configuration files |
| nssm/ | 324 KB | Service manager |
| docs/ | 164 KB | Documentation |

**What we DON'T include:**
- ❌ Embedded Python (249 MB)
- ❌ pip/setuptools (44 MB)
- ❌ Test directories (25 MB)
- ❌ Python bytecode cache (10 MB)

**Total savings: ~300+ MB compared to embedded Python approach!**

---

## Troubleshooting

### Build Fails: PyInstaller not found

```cmd
pip install pyinstaller
```

### Build Fails: npm not found

Install Node.js from https://nodejs.org/

### Services won't start

Check logs in `data/logs/`:
- `mosquitto.log` - MQTT broker
- `daq_service.log` - DAQ backend
- `azure_uploader.log` - Azure uploader
- `web_server.log` - Dashboard server

### Port conflicts

Default ports:
- 1883 - MQTT broker
- 9001 - MQTT WebSocket
- 5173 - Dashboard HTTP server

If ports are in use, ICCSFlux will attempt to find alternative ports.

### Dashboard not loading

1. Check if ICCSFlux.exe is running
2. Check `data/logs/web_server.log`
3. Verify `www/` folder exists and contains `index.html`
4. Try accessing http://localhost:5173 directly

---

## Comparison: build_exe.py vs build_portable.py

| Feature | build_exe.py | build_portable.py |
|---------|-------------|-------------------|
| **Output** | Native executables | Python scripts |
| **Size** | ~75-80 MB | ~327 MB |
| **Python needed?** | No (self-contained) | Yes (embedded) |
| **Startup speed** | Fast | Slower |
| **Updates** | Rebuild exe | Just update .py |
| **Industrial use** | ✅ Recommended | ❌ Development only |
| **Service restart** | ✅ Built-in | Limited |
| **Reliability** | ✅ High | Lower |

**Recommendation:** Use `build_exe.py` (via `build.bat`) for production/industrial deployments.

---

## Summary

The ICCSFlux portable system is now a **truly industrial-grade** solution:

✅ **Native executables** - No Python installation required
✅ **Small size** - ~75-80 MB total
✅ **Auto-restart** - Services recover from crashes automatically
✅ **Service dependencies** - Correct startup order guaranteed
✅ **Log rotation** - Prevents disk space issues
✅ **Single instance** - Prevents conflicts
✅ **Browser-based UI** - Access from any device
✅ **Windows Service support** - Runs even when logged out

**This is production-ready for industrial deployment.**
