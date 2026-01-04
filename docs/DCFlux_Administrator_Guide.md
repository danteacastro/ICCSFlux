# DCFlux Administrator Guide

**System Installation, Configuration & Maintenance**

---

## Table of Contents

1. [System Requirements](#1-system-requirements)
2. [Installation](#2-installation)
3. [Configuration Files](#3-configuration-files)
4. [Service Management](#4-service-management)
5. [User Administration](#5-user-administration)
6. [Backup & Recovery](#6-backup--recovery)
7. [Multi-Node Deployment](#7-multi-node-deployment)
8. [Security Hardening](#8-security-hardening)
9. [Compliance (21 CFR Part 11)](#9-compliance-21-cfr-part-11)
10. [Performance Tuning](#10-performance-tuning)
11. [Log Files & Diagnostics](#11-log-files--diagnostics)

---

## 1. System Requirements

### Minimum Hardware
| Component | Requirement |
|-----------|-------------|
| CPU | Intel Core i5 or equivalent |
| RAM | 8 GB |
| Storage | 100 GB SSD |
| Network | Ethernet (1 Gbps) |

### Recommended Hardware
| Component | Requirement |
|-----------|-------------|
| CPU | Intel Core i7 or Xeon |
| RAM | 16 GB |
| Storage | 500 GB NVMe SSD |
| Network | Ethernet (1 Gbps) |

### Software Requirements
| Component | Version |
|-----------|---------|
| Operating System | Windows 10/11 Pro (64-bit) |
| Python | 3.10 or later |
| Node.js | 18.x or later |
| MQTT Broker | Mosquitto 2.x |
| Browser | Chrome/Edge (latest) |

### Optional Hardware
| Component | Purpose |
|-----------|---------|
| NI-DAQmx | National Instruments hardware |
| Modbus Device | Remote I/O modules |
| UPS | Power protection |

---

## 2. Installation

### 2.1 Quick Install

```batch
# 1. Extract DCFlux package
unzip dcflux-v1.0.zip -d C:\DCFlux

# 2. Install Python dependencies
cd C:\DCFlux
pip install -r requirements.txt

# 3. Install Node dependencies
cd dashboard
npm install

# 4. Install Mosquitto MQTT broker
winget install Eclipse.Mosquitto

# 5. Configure and start
copy config\system.ini.example config\system.ini
start.bat
```

### 2.2 Directory Structure

```
C:\DCFlux\
├── dashboard\           # Vue.js frontend
│   ├── src\
│   ├── dist\           # Production build
│   └── package.json
├── services\           # Python backend
│   ├── daq_service\
│   │   ├── daq_service.py
│   │   ├── alarm_manager.py
│   │   ├── recording_manager.py
│   │   └── ...
│   └── requirements.txt
├── config\
│   ├── system.ini      # Main configuration
│   ├── projects\       # Saved projects
│   └── mosquitto.conf  # MQTT broker config
├── data\
│   ├── recordings\     # Data files
│   ├── archives\       # Long-term storage
│   └── logs\           # Application logs
├── docs\               # Documentation
├── start.bat           # Startup script
└── stop.bat            # Shutdown script
```

### 2.3 First-Time Setup

1. **Configure MQTT Broker:**
   ```
   # Edit config/mosquitto.conf
   listener 1883
   listener 9002
   protocol websockets
   allow_anonymous true
   ```

2. **Configure System:**
   ```ini
   # config/system.ini
   [mqtt]
   broker = localhost
   port = 1883
   ws_port = 9002

   [acquisition]
   scan_rate = 10
   publish_rate = 2

   [node]
   id = node-001
   name = Main DAQ System
   ```

3. **Create Admin User:**
   - Default: `admin` / `iccsadmin`
   - Change password after first login

---

## 3. Configuration Files

### 3.1 system.ini

Main configuration file for the DAQ service.

```ini
[mqtt]
broker = localhost
port = 1883
ws_port = 9002
username =
password =
client_id = dcflux-daq

[acquisition]
scan_rate = 10          # Hz
publish_rate = 2        # Hz
simulation = false

[recording]
directory = data/recordings
format = csv            # csv or tdms
max_file_size = 100     # MB
auto_split = true

[logging]
level = INFO
max_file_size = 50      # MB
backup_count = 5

[watchdog]
enabled = true
heartbeat_timeout = 10  # seconds
auto_restart = true

[node]
id = node-001
name = Primary Node
location = Lab A
```

### 3.2 mosquitto.conf

MQTT broker configuration.

```conf
# Network listeners
listener 1883
listener 9002
protocol websockets

# Authentication
allow_anonymous true
# For production, enable authentication:
# allow_anonymous false
# password_file /path/to/passwd

# Persistence
persistence true
persistence_location data/mqtt/

# Logging
log_dest file data/logs/mosquitto.log
log_type warning
log_type error
```

### 3.3 Project Files (JSON)

Projects store complete system configuration:

```json
{
  "name": "Test System",
  "version": "1.0",
  "created": "2026-01-04T12:00:00Z",
  "channels": { ... },
  "alarms": { ... },
  "interlocks": { ... },
  "sequences": { ... },
  "layout": { ... }
}
```

---

## 4. Service Management

### 4.1 Starting Services

```batch
# Start all services
start.bat

# Or individually:
# Start MQTT broker
net start mosquitto

# Start DAQ service
cd services\daq_service
python daq_service.py -c ..\..\config\system.ini

# Start web dashboard
cd dashboard
npm run dev
```

### 4.2 Stopping Services

```batch
# Stop all services
stop.bat

# Or individually:
taskkill /IM python.exe /F
net stop mosquitto
```

### 4.3 Service Status

```batch
# Check if services are running
tasklist | findstr python
tasklist | findstr mosquitto
netstat -ano | findstr :1883
netstat -ano | findstr :5173
```

### 4.4 Windows Service Installation

To run DCFlux as a Windows service:

```batch
# Install as service (run as Administrator)
nssm install DCFlux-DAQ "C:\Python312\python.exe" "C:\DCFlux\services\daq_service\daq_service.py"
nssm set DCFlux-DAQ AppDirectory "C:\DCFlux\services\daq_service"
nssm set DCFlux-DAQ AppStdout "C:\DCFlux\data\logs\daq_stdout.log"
nssm set DCFlux-DAQ AppStderr "C:\DCFlux\data\logs\daq_stderr.log"

# Start service
net start DCFlux-DAQ

# Stop service
net stop DCFlux-DAQ
```

### 4.5 Scheduled Restart

For long-term stability, schedule weekly restarts:

```batch
# Create scheduled task (run as Administrator)
schtasks /create /tn "DCFlux Weekly Restart" /tr "C:\DCFlux\restart_daq.ps1" /sc weekly /d SUN /st 03:00 /ru SYSTEM
```

---

## 5. User Administration

### 5.1 Default Users

| Username | Password | Role |
|----------|----------|------|
| admin | iccsadmin | Admin |

**Important:** Change the admin password after installation.

### 5.2 Creating Users

Via Dashboard:
1. Login as admin
2. Go to Admin tab → User Management
3. Click "+ Add User"
4. Enter username, password, role
5. Click Create

Via Command Line:
```python
# Python script to create user
from user_session import UserSessionManager

usm = UserSessionManager()
usm.create_user(
    username="operator1",
    password="secure_password",
    role="operator",
    display_name="Operator One"
)
```

### 5.3 Password Policy

Recommended password requirements:
- Minimum 8 characters
- Mix of uppercase and lowercase
- At least one number
- At least one special character

### 5.4 Session Management

```ini
# config/system.ini
[auth]
session_timeout = 3600      # seconds (1 hour)
max_sessions = 5            # per user
lockout_attempts = 3        # failed logins before lockout
lockout_duration = 300      # seconds (5 minutes)
```

---

## 6. Backup & Recovery

### 6.1 What to Backup

| Item | Location | Frequency |
|------|----------|-----------|
| Projects | config/projects/ | Daily |
| Recordings | data/recordings/ | After each test |
| Audit Trail | data/audit/ | Daily |
| Configuration | config/ | After changes |
| User Database | data/users.db | Daily |

### 6.2 Backup Script

```batch
@echo off
set BACKUP_DIR=D:\Backups\DCFlux\%date:~-4,4%%date:~-10,2%%date:~-7,2%

mkdir %BACKUP_DIR%
xcopy /E /Y config %BACKUP_DIR%\config\
xcopy /E /Y data\audit %BACKUP_DIR%\audit\
copy data\users.db %BACKUP_DIR%\
echo Backup completed to %BACKUP_DIR%
```

### 6.3 Recovery Procedure

1. Stop all DCFlux services
2. Restore configuration files
3. Restore user database
4. Restart services
5. Verify data integrity

```batch
# Restore from backup
xcopy /E /Y D:\Backups\DCFlux\20260104\config C:\DCFlux\config\
copy D:\Backups\DCFlux\20260104\users.db C:\DCFlux\data\
```

### 6.4 Project Export/Import

Dashboard method:
1. Config tab → Export Project
2. Save .json file
3. On new system: Import Project

Command line:
```batch
# Export
copy config\projects\current.json backup_project.json

# Import
copy backup_project.json config\projects\current.json
```

---

## 7. Multi-Node Deployment

### 7.1 Architecture

```
┌─────────────────┐     ┌─────────────────┐
│   Node 001      │     │   Node 002      │
│   (Lab A DAQ)   │     │   (Lab B DAQ)   │
└────────┬────────┘     └────────┬────────┘
         │                       │
         └──────────┬────────────┘
                    │
         ┌──────────▼──────────┐
         │   MQTT Broker       │
         │   (Central Server)  │
         └──────────┬──────────┘
                    │
         ┌──────────▼──────────┐
         │   Dashboard         │
         │   (Any Browser)     │
         └─────────────────────┘
```

### 7.2 Node Configuration

Each node needs unique configuration:

```ini
# Node 001 - config/system.ini
[mqtt]
broker = central-server.local
port = 1883

[node]
id = node-001
name = Lab A System
location = Building 1, Lab A
```

```ini
# Node 002 - config/system.ini
[mqtt]
broker = central-server.local
port = 1883

[node]
id = node-002
name = Lab B System
location = Building 1, Lab B
```

### 7.3 Central Broker Setup

Configure Mosquitto for multi-node:

```conf
# mosquitto.conf on central server
listener 1883 0.0.0.0
listener 9002 0.0.0.0
protocol websockets

max_connections 100
persistent_client_expiration 1d
```

### 7.4 Dashboard Node Selection

The dashboard can view any node:
- Default shows all nodes
- Use node selector to filter
- Each widget can target specific node

---

## 8. Security Hardening

### 8.1 MQTT Authentication

```conf
# mosquitto.conf
allow_anonymous false
password_file C:\DCFlux\config\mqtt_passwd

# Generate password file
mosquitto_passwd -c C:\DCFlux\config\mqtt_passwd dcflux
```

### 8.2 TLS/SSL Encryption

```conf
# mosquitto.conf
listener 8883
cafile C:\DCFlux\certs\ca.crt
certfile C:\DCFlux\certs\server.crt
keyfile C:\DCFlux\certs\server.key
require_certificate false
```

### 8.3 Firewall Configuration

| Port | Protocol | Purpose |
|------|----------|---------|
| 1883 | TCP | MQTT (internal only) |
| 8883 | TCP | MQTT over TLS |
| 9002 | TCP | MQTT WebSocket |
| 5173 | TCP | Dashboard (dev) |
| 80/443 | TCP | Dashboard (prod) |

```batch
# Windows Firewall rules
netsh advfirewall firewall add rule name="DCFlux MQTT" dir=in action=allow protocol=TCP localport=1883
netsh advfirewall firewall add rule name="DCFlux Dashboard" dir=in action=allow protocol=TCP localport=5173
```

### 8.4 Network Isolation

For production systems:
- Place DAQ nodes on dedicated VLAN
- Restrict MQTT broker access
- Use VPN for remote access
- Disable unused network services

---

## 9. Compliance (21 CFR Part 11)

### 9.1 Requirements Checklist

| Requirement | DCFlux Implementation |
|-------------|----------------------|
| Electronic signatures | User authentication required |
| Audit trail | Immutable event log |
| Authority checks | Role-based access control |
| Device checks | System status monitoring |
| Training | User role assignments |
| Access controls | Login with password |
| Operational checks | Sequence validation |
| Record retention | Archive management |

### 9.2 Audit Trail Configuration

```ini
# config/system.ini
[audit]
enabled = true
retention_days = 2190      # 6 years
checksum_algorithm = sha256
include_raw_data = true
```

### 9.3 Electronic Records

All configuration changes are logged:
- Who made the change
- When the change was made
- What was changed (before/after)
- Why (comment required for some changes)

### 9.4 Data Integrity

Recording files include:
- SHA-256 checksum
- Digital signature (optional)
- Metadata header with timestamps
- Operator identification

### 9.5 Validation

For validated systems:
1. Document IQ (Installation Qualification)
2. Document OQ (Operational Qualification)
3. Document PQ (Performance Qualification)
4. Maintain validation records

---

## 10. Performance Tuning

### 10.1 Scan Rate Optimization

| Channel Count | Recommended Scan Rate |
|---------------|----------------------|
| 1-32 | 100 Hz |
| 33-64 | 50 Hz |
| 65-128 | 25 Hz |
| 129-256 | 10 Hz |

### 10.2 Publish Rate

Lower publish rate reduces network/browser load:

| Use Case | Recommended Rate |
|----------|-----------------|
| Real-time display | 5-10 Hz |
| Trend monitoring | 2 Hz |
| Slow processes | 1 Hz |
| Data logging only | 0.5 Hz |

### 10.3 Memory Management

```ini
# config/system.ini
[performance]
max_buffer_size = 10000    # samples
chart_history = 3600       # seconds
gc_interval = 300          # garbage collection
```

### 10.4 Dashboard Optimization

- Limit widgets per page to 20-30
- Use decimation for trend charts
- Close unused browser tabs
- Reduce chart history for slow networks

---

## 11. Log Files & Diagnostics

### 11.1 Log Locations

| Log | Location |
|-----|----------|
| DAQ Service | data/logs/daq_service.log |
| MQTT Broker | data/logs/mosquitto.log |
| Audit Trail | data/audit/audit.db |
| Recording Status | data/logs/recording.log |

### 11.2 Log Levels

```ini
# config/system.ini
[logging]
level = INFO    # DEBUG, INFO, WARNING, ERROR, CRITICAL
```

### 11.3 Diagnostic Commands

```batch
# Check DAQ service status
curl http://localhost:8000/api/status

# Check MQTT connectivity
mosquitto_sub -h localhost -t "nisystem/#" -v

# View recent logs
type data\logs\daq_service.log | more
```

### 11.4 Common Issues

| Symptom | Cause | Solution |
|---------|-------|----------|
| No data updating | Acquisition stopped | Click START |
| Dashboard offline | MQTT disconnected | Check broker |
| Recording fails | Disk full | Free space |
| Slow performance | Too many channels | Reduce scan rate |
| Login fails | Account locked | Wait or reset |

### 11.5 Health Check Script

```batch
@echo off
echo === DCFlux Health Check ===
echo.
echo Checking services...
tasklist | findstr python && echo [OK] Python running || echo [FAIL] Python not running
tasklist | findstr mosquitto && echo [OK] MQTT running || echo [FAIL] MQTT not running
echo.
echo Checking ports...
netstat -ano | findstr :1883 >nul && echo [OK] MQTT port 1883 || echo [FAIL] MQTT port
netstat -ano | findstr :5173 >nul && echo [OK] Dashboard port 5173 || echo [FAIL] Dashboard port
echo.
echo Checking disk space...
for /f "tokens=3" %%a in ('dir C:\ ^| find "bytes free"') do echo Free space: %%a bytes
echo.
echo === End Health Check ===
```

---

## Quick Reference

### Start System
```batch
start.bat
```

### Stop System
```batch
stop.bat
```

### View Logs
```batch
type data\logs\daq_service.log | more
```

### Create Backup
```batch
backup.bat
```

### Check Status
```batch
health_check.bat
```

---

**DCFlux Administrator Guide v1.0**
*Last Updated: January 2026*
