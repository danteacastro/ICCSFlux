# ICCSFlux Administrator Guide

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
8. [Remote Node Administration](#8-remote-node-administration)
9. [Security Hardening](#9-security-hardening)
10. [Compliance (21 CFR Part 11)](#10-compliance-21-cfr-part-11)
11. [Performance Tuning](#11-performance-tuning)
12. [Log Files & Diagnostics](#12-log-files--diagnostics)

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
# 1. Extract ICCSFlux package
unzip iccsflux-v1.0.zip -d C:\ICCSFlux

# 2. Install Python dependencies
cd C:\ICCSFlux
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
C:\ICCSFlux\
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
   - Default credentials are set during installation
   - **Change password immediately after first login**

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
client_id = iccsflux-daq

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

To run ICCSFlux as a Windows service:

```batch
# Install as service (run as Administrator)
nssm install ICCSFlux-DAQ "C:\Python312\python.exe" "C:\ICCSFlux\services\daq_service\daq_service.py"
nssm set ICCSFlux-DAQ AppDirectory "C:\ICCSFlux\services\daq_service"
nssm set ICCSFlux-DAQ AppStdout "C:\ICCSFlux\data\logs\daq_stdout.log"
nssm set ICCSFlux-DAQ AppStderr "C:\ICCSFlux\data\logs\daq_stderr.log"

# Start service
net start ICCSFlux-DAQ

# Stop service
net stop ICCSFlux-DAQ
```

### 4.5 Scheduled Restart

For long-term stability, schedule weekly restarts:

```batch
# Create scheduled task (run as Administrator)
schtasks /create /tn "ICCSFlux Weekly Restart" /tr "C:\ICCSFlux\restart_daq.ps1" /sc weekly /d SUN /st 03:00 /ru SYSTEM
```

---

## 5. User Administration

### 5.1 Default Users

| Username | Role |
|----------|------|
| admin | Admin |

**Important:** Default credentials are provided during installation. Change the admin password immediately.

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
set BACKUP_DIR=D:\Backups\ICCSFlux\%date:~-4,4%%date:~-10,2%%date:~-7,2%

mkdir %BACKUP_DIR%
xcopy /E /Y config %BACKUP_DIR%\config\
xcopy /E /Y data\audit %BACKUP_DIR%\audit\
copy data\users.db %BACKUP_DIR%\
echo Backup completed to %BACKUP_DIR%
```

### 6.3 Recovery Targets

| Metric | Target | Notes |
|--------|--------|-------|
| **RTO** (Recovery Time Objective) | 30 minutes | Time to restore from backup and resume operation |
| **RPO** (Recovery Point Objective) | 24 hours | Maximum acceptable data loss (daily backups) |
| **RPO (recordings)** | 0 (per-test) | Recording data backed up after each test session |
| **Backup verification** | Weekly | Verify backup integrity by restoring to test environment |

For tighter RPO, increase backup frequency or enable continuous replication
of the `config/` and `data/audit/` directories.

### 6.4 Recovery Procedure

**Full system recovery (PC failure or corruption):**

1. Install ICCSFlux on replacement PC (or reinstall on existing)
2. Stop all ICCSFlux services
3. Restore configuration and data from backup:
```batch
xcopy /E /Y D:\Backups\ICCSFlux\20260104\config C:\ICCSFlux\config\
xcopy /E /Y D:\Backups\ICCSFlux\20260104\audit C:\ICCSFlux\data\audit\
copy D:\Backups\ICCSFlux\20260104\users.db C:\ICCSFlux\data\
```
4. Restart services and verify MQTT connectivity
5. Open dashboard — verify channels, interlocks, and alarm configurations loaded
6. Run a short test acquisition to confirm hardware communication

**cRIO node recovery (cRIO failure or reimage):**

1. Redeploy using `deploy_crio_v2.bat [crio_host] [broker_host]`
2. The cRIO node will receive its channel configuration from the DAQ service
   on first connection — no manual config restoration needed
3. Verify channels appear in the dashboard

**Project-only recovery (project file corruption):**

1. Restore project file: `copy D:\Backups\...\projects\*.json config\projects\`
2. Reload project in dashboard (Config tab → Load Project)

**Post-recovery verification checklist:**

- [ ] All expected channels visible in dashboard
- [ ] Alarm limits match expected values
- [ ] Interlocks active and evaluating correctly
- [ ] Safety actions configured (trip, safe-state)
- [ ] Audit trail entries present and readable
- [ ] User accounts and roles correct
- [ ] Recording can be started and data saved

### 6.5 Project Export/Import

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

## 8. Remote Node Administration

This chapter covers the deployment and maintenance of remote ICCSFlux nodes (cRIO and Opto22).

### 8.1 cRIO Node Deployment

#### Hardware Requirements

| Component | Requirement |
|-----------|-------------|
| Controller | NI cRIO with Linux Real-Time |
| Python | 3.8+ (included in NI Linux RT) |
| Network | Ethernet connection to PC |
| Storage | 256 MB free space |

#### Installation Files

The cRIO node service consists of:

| File | Purpose |
|------|---------|
| `crio_node.py` | Main service script |
| `crio_node.service` | Systemd service unit |
| `crio_node.env` | Environment configuration |
| `install.sh` | One-click installer |
| `requirements.txt` | Python dependencies |

#### Installation Procedure

1. **Copy files to cRIO:**
   ```bash
   scp -r services/crio_node admin@<crio-ip>:/home/admin/
   ```

2. **SSH to cRIO and run installer:**
   ```bash
   ssh admin@<crio-ip>
   cd /home/admin/crio_node
   chmod +x install.sh
   ./install.sh <ICCSFLUX_PC_IP> [NODE_ID]
   ```

   Example:
   ```bash
   ./install.sh 192.168.1.100 crio-001
   ```

3. **Verify installation:**
   ```bash
   systemctl status crio_node.service
   journalctl -u crio_node.service -f
   ```

#### Configuration File

Location: `/home/admin/nisystem/crio_node.env`

```bash
# MQTT Broker - ICCSFlux PC
MQTT_BROKER=192.168.1.100

# MQTT Port
MQTT_PORT=1883

# Node ID (unique per cRIO)
NODE_ID=crio-001
```

#### Service Management

| Command | Description |
|---------|-------------|
| `systemctl status crio_node` | Check status |
| `systemctl start crio_node` | Start service |
| `systemctl stop crio_node` | Stop service |
| `systemctl restart crio_node` | Restart service |
| `systemctl enable crio_node` | Enable auto-start |
| `systemctl disable crio_node` | Disable auto-start |
| `journalctl -u crio_node -f` | View live logs |
| `journalctl -u crio_node -n 100` | View last 100 log lines |

#### Log Management

Logs are stored in journald. To prevent flash wear:

```bash
# Configure log rotation (already done by installer)
cat /etc/systemd/journald.conf.d/nisystem.conf
```

Default settings:
- Maximum 50 MB total log storage
- Maximum 10 MB per file
- 7 day retention
- Compression enabled

### 8.2 Opto22 Node Deployment

#### Hardware Requirements

| Component | Requirement |
|-----------|-------------|
| Controller | Opto22 groov EPIC or groov RIO |
| Network | Ethernet connection to PC |
| User | `dev` account (default) |

#### Installation Files

| File | Purpose |
|------|---------|
| `opto22_node.py` | Main service script |
| `opto22_node.service` | Systemd service unit |
| `opto22_node.env` | Environment configuration |
| `install.sh` | One-click installer |
| `journald-nisystem.conf` | Log rotation config |
| `requirements.txt` | Python dependencies |

#### Installation Procedure

1. **Copy files to groov EPIC:**
   ```bash
   scp -r services/opto22_node dev@<epic-ip>:/home/dev/
   ```

2. **SSH to groov EPIC and run installer:**
   ```bash
   ssh dev@<epic-ip>
   cd /home/dev/opto22_node
   chmod +x install.sh
   ./install.sh <ICCSFLUX_PC_IP> [NODE_ID] [API_KEY]
   ```

   Example:
   ```bash
   ./install.sh 192.168.1.100 opto22-001
   ```

3. **Verify installation:**
   ```bash
   systemctl status opto22_node.service
   journalctl -u opto22_node.service -f
   ```

#### groov API Key Setup

If your groov EPIC requires authentication:

1. Log into groov Manage (`https://<epic-ip>`)
2. Navigate to **Accounts** → **API Keys**
3. Create a new API key with I/O access
4. Add to environment file:
   ```bash
   nano /home/dev/nisystem/opto22_node.env
   # Add: API_KEY=your-api-key-here
   systemctl restart opto22_node.service
   ```

#### Configuration File

Location: `/home/dev/nisystem/opto22_node.env`

```bash
# MQTT Broker - ICCSFlux PC
MQTT_BROKER=192.168.1.100

# MQTT Port
MQTT_PORT=1883

# Node ID (unique per Opto22)
NODE_ID=opto22-001

# groov API Key (optional)
API_KEY=
```

### 8.3 Network Architecture

#### Single Node Setup

```
┌─────────────────┐         ┌─────────────────┐
│   ICCSFlux PC     │◄───────►│  Remote Node    │
│  MQTT Broker    │  MQTT   │  (cRIO/Opto22)  │
│  Port 1883      │         │                 │
└─────────────────┘         └─────────────────┘
```

#### Multi-Node Setup

```
                       ┌─────────────────┐
                       │   ICCSFlux PC     │
                       │  MQTT Broker    │
                       │  192.168.1.100  │
                       └────────┬────────┘
                                │
          ┌─────────────────────┼─────────────────────┐
          │                     │                     │
    ┌─────▼─────┐         ┌─────▼─────┐         ┌─────▼─────┐
    │ cRIO-001  │         │ cRIO-002  │         │opto22-001 │
    │ Lab A     │         │ Lab B     │         │ Field     │
    │.101       │         │.102       │         │.103       │
    └───────────┘         └───────────┘         └───────────┘
```

#### Firewall Rules

| Port | Protocol | Direction | Purpose |
|------|----------|-----------|---------|
| 1883 | TCP | Inbound | MQTT (nodes → PC) |
| 22 | TCP | Outbound | SSH (PC → nodes) |

```batch
# Windows Firewall - allow MQTT inbound
netsh advfirewall firewall add rule name="ICCSFlux MQTT" dir=in action=allow protocol=TCP localport=1883
```

### 8.4 Node Health Monitoring

#### Heartbeat System

Remote nodes send heartbeat messages every 2 seconds:
- Topic: `nisystem/nodes/{node-id}/heartbeat`
- Payload: `{ "timestamp": ..., "node_id": "...", "status": "online" }`

The PC monitors heartbeats and marks nodes:
- **Online**: Heartbeat within 10 seconds
- **Warning**: Heartbeat 10-30 seconds old
- **Offline**: No heartbeat for 30+ seconds

#### Dashboard Indicators

In the Configuration tab discovery tree:
- **Green** ● = Online
- **Yellow** ● = Warning
- **Red** ● = Offline

#### Command Line Health Check

On cRIO:
```bash
# Check service status
systemctl status crio_node.service

# Check MQTT connectivity
mosquitto_pub -h <pc-ip> -t "test" -m "ping"

# Check network
ping <pc-ip>
```

On Opto22:
```bash
# Check service status
systemctl status opto22_node.service

# Check REST API
curl -k https://localhost/api/v1/device/info

# Check network
ping <pc-ip>
```

### 8.5 Troubleshooting Remote Nodes

#### Service Won't Start

```bash
# Check detailed error logs
journalctl -u crio_node.service -n 50 --no-pager

# Common issues:
# - Python dependencies missing → pip install -r requirements.txt
# - Wrong MQTT broker IP → edit .env file
# - Port 1883 blocked → check firewall
```

#### Can't Connect to MQTT

```bash
# Test MQTT connectivity
mosquitto_sub -h <pc-ip> -p 1883 -t "test" -v

# Check if broker is running on PC
netstat -ano | findstr :1883
```

#### No I/O Values (cRIO)

1. Verify NI-DAQmx is installed
2. Check module is detected: `nilsdev`
3. Verify channel configuration

#### No I/O Values (Opto22)

1. Check REST API is accessible:
   ```bash
   curl -k https://localhost/api/v1/device/info
   ```
2. Verify API key if authentication is enabled
3. Check PAC Control strategy is running

#### Network Issues After Reboot

Both services are configured to:
- Wait for network before starting
- Auto-reconnect on network loss
- Retry MQTT connection indefinitely

If issues persist:
```bash
# Check network status
ip addr
ping <pc-ip>

# Restart service
systemctl restart crio_node.service
```

---

## 8.5 Notification System Administration

### Twilio SMS Setup

1. Create a Twilio account at [twilio.com](https://www.twilio.com)
2. From the Twilio Console, note your:
   - **Account SID** (starts with `AC`)
   - **Auth Token**
   - **Phone Number** (Twilio-assigned, e.g., `+15551234567`)
3. In ICCSFlux, open **Configuration → System Settings → SMS Notifications**
4. Enter Account SID, Auth Token, From Number, and recipient To Numbers
5. Click **Test** to send a test message

**How it works**: ICCSFlux calls the Twilio REST API directly via HTTPS (`requests.post`). No Twilio SDK is installed. The only outbound connection is `https://api.twilio.com`. No inbound webhooks are required.

**Cost**: Twilio charges per message (~$0.0079/SMS in the US). With the default daily limit of 100, maximum cost is under $1/day.

### SMTP Email Setup

1. Obtain SMTP credentials from your email provider:

   | Provider | Server | Port | Notes |
   |----------|--------|------|-------|
   | Office 365 | `smtp.office365.com` | 587 | Use TLS, requires app password if MFA enabled |
   | Gmail | `smtp.gmail.com` | 587 | Requires App Password (not regular password) |
   | Corporate | Ask IT | 25 or 587 | May require internal relay configuration |

2. In ICCSFlux, open **Configuration → System Settings → Email Notifications**
3. Enter SMTP server, port, username, password, From address, and To addresses
4. Enable TLS (recommended for port 587)
5. Click **Test** to send a test email

**Security**: SMTP credentials are stored in the project JSON file alongside other configuration. The project file should be protected via OS-level file permissions. Credentials are never logged.

### Notification Filtering

Each channel (SMS, Email) has independent 7-layer filtering:

```
Alarm Event
  │
  ├─ 1. Event Type filter (triggered / cleared / acknowledged / flood)
  ├─ 2. Severity filter (CRITICAL / HIGH / MEDIUM / LOW)
  ├─ 3. Group filter (Boiler / Cooling / etc.)
  ├─ 4. Alarm selection (all / include_only / exclude)
  ├─ 5. Per-alarm cooldown (default 300s — same alarm won't repeat)
  ├─ 6. Daily limit (default 100 — resets at midnight)
  └─ 7. Quiet hours (suppress non-CRITICAL during off-hours)
        │
        ▼
    Notification Delivered (SMS or Email)
```

### Configuration Storage

Notification configuration is persisted to the project JSON file and sent to the DAQ service via MQTT (`notifications/config/update`). The DAQ service stores an in-memory copy and applies filtering in real time.

### Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Test SMS fails | Invalid Account SID or Auth Token | Verify credentials in Twilio Console |
| Test email fails | Wrong SMTP server/port | Check provider settings; ensure TLS matches port |
| No notifications during alarm | Filtering too restrictive | Check severity, event type, and group filters |
| Duplicate notifications | Cooldown too short | Increase per-alarm cooldown period |
| Notifications stop after N per day | Daily limit reached | Increase daily limit or review alarm config |
| No notifications during quiet hours | Quiet hours active | Only CRITICAL alarms bypass quiet hours |

---

## 9. Security Hardening

### 9.1 MQTT Security Model (Zero-Config)

ICCSFlux uses automatic MQTT credential generation. No manual setup is required.

**Architecture per portable unit:**
```
[PC] ─── localhost ─── [MQTT Broker + DAQ Service + Dashboard]
  │
  └── USB Ethernet ─── dedicated physical link ─── [cRIO]
```

**How it works:**
1. On first `start.bat` run, `scripts/mqtt_credentials.py` generates random credentials
2. Two MQTT users are created: `backend` (full access) and `dashboard` (controlled access)
3. Credentials are stored in `config/mqtt_credentials.json` (auto-generated, gitignored)
4. Password file `config/mosquitto_passwd` uses PBKDF2-SHA512 hashing
5. Dashboard credentials are written to `dashboard/.env.local` (auto-generated, gitignored)
6. `deploy_crio_v2.bat` reads credentials and passes them to the cRIO runner

**MQTT Users and Permissions (ACL):**

| User | Access | Purpose |
|------|--------|---------|
| `backend` | `readwrite #` | DAQ service + cRIO nodes — full access |
| `dashboard` | Read all, write control topics only | Browser dashboard — can monitor and send commands |

**To regenerate credentials:**
```batch
REM Delete the credential store and restart
del config\mqtt_credentials.json
start.bat
```

**TLS is intentionally omitted** because:
- The MQTT broker runs on `localhost` (same PC as all services)
- cRIO is on a dedicated physical Ethernet link (USB adapter), not a shared network
- The credential system prevents cross-talk between portable ICCSFlux instances
- Adding TLS would require certificate management that conflicts with the zero-config goal

### 9.2 Firewall Configuration

| Port | Protocol | Purpose |
|------|----------|---------|
| 1883 | TCP | MQTT (cRIO → PC, over dedicated USB Ethernet) |
| 9002 | TCP | MQTT WebSocket (localhost only, for dashboard) |
| 5173 | TCP | Dashboard (dev) |
| 80/443 | TCP | Dashboard (prod) |

```batch
# Windows Firewall rules (only needed if cRIO is on a routed network)
netsh advfirewall firewall add rule name="ICCSFlux MQTT" dir=in action=allow protocol=TCP localport=1883
netsh advfirewall firewall add rule name="ICCSFlux Dashboard" dir=in action=allow protocol=TCP localport=5173
```

### 9.3 Network Isolation

Each portable ICCSFlux unit uses physical isolation:
- cRIO connects via dedicated USB-C/USB-A Ethernet adapter (not shared LAN)
- MQTT WebSocket listener binds to `127.0.0.1` only (dashboard access)
- MQTT TCP listener on `0.0.0.0:1883` is accessible only from the dedicated cRIO link
- No internet or corporate network connectivity required for operation

---

## 10. Compliance (21 CFR Part 11)

### 10.1 Requirements Checklist

| Requirement | ICCSFlux Implementation |
|-------------|----------------------|
| Electronic signatures | User authentication required |
| Audit trail | Immutable event log |
| Authority checks | Role-based access control |
| Device checks | System status monitoring |
| Training | User role assignments |
| Access controls | Login with password |
| Operational checks | Sequence validation |
| Record retention | Archive management |

### 10.2 Audit Trail Configuration

```ini
# config/system.ini
[audit]
enabled = true
retention_days = 2190      # 6 years
checksum_algorithm = sha256
include_raw_data = true
```

### 10.3 Electronic Records

All configuration changes are logged:
- Who made the change
- When the change was made
- What was changed (before/after)
- Why (comment required for some changes)

### 10.4 Data Integrity

Recording files include:
- SHA-256 checksum
- Digital signature (optional)
- Metadata header with timestamps
- Operator identification

### 10.5 Validation

For validated systems:
1. Document IQ (Installation Qualification)
2. Document OQ (Operational Qualification)
3. Document PQ (Performance Qualification)
4. Maintain validation records

---

## 11. Performance Tuning

### 11.1 Scan Rate Optimization

| Channel Count | Recommended Scan Rate |
|---------------|----------------------|
| 1-32 | 100 Hz |
| 33-64 | 50 Hz |
| 65-128 | 25 Hz |
| 129-256 | 10 Hz |

### 11.2 Publish Rate

Lower publish rate reduces network/browser load:

| Use Case | Recommended Rate |
|----------|-----------------|
| Real-time display | 5-10 Hz |
| Trend monitoring | 2 Hz |
| Slow processes | 1 Hz |
| Data logging only | 0.5 Hz |

### 11.3 Memory Management

```ini
# config/system.ini
[performance]
max_buffer_size = 10000    # samples
chart_history = 3600       # seconds
gc_interval = 300          # garbage collection
```

### 11.4 Dashboard Optimization

- Limit widgets per page to 20-30
- Use decimation for trend charts
- Close unused browser tabs
- Reduce chart history for slow networks

---

## 12. Log Files & Diagnostics

### 12.1 Log Locations

| Log | Location |
|-----|----------|
| DAQ Service | data/logs/daq_service.log |
| MQTT Broker | data/logs/mosquitto.log |
| Audit Trail | data/audit/audit.db |
| Recording Status | data/logs/recording.log |

### 12.2 Log Levels

```ini
# config/system.ini
[logging]
level = INFO    # DEBUG, INFO, WARNING, ERROR, CRITICAL
```

### 12.3 Diagnostic Commands

```batch
# Check DAQ service status
curl http://localhost:8000/api/status

# Check MQTT connectivity
mosquitto_sub -h localhost -t "nisystem/#" -v

# View recent logs
type data\logs\daq_service.log | more
```

### 12.4 Common Issues

| Symptom | Cause | Solution |
|---------|-------|----------|
| No data updating | Acquisition stopped | Click START |
| Dashboard offline | MQTT disconnected | Check broker |
| Recording fails | Disk full | Free space |
| Slow performance | Too many channels | Reduce scan rate |
| Login fails | Account locked | Wait or reset |

### 12.5 Health Check Script

```batch
@echo off
echo === ICCSFlux Health Check ===
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

**ICCSFlux Administrator Guide v1.0**
*Last Updated: January 2026*
