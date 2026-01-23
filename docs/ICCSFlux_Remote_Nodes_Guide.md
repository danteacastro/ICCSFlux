# ICCSFlux Remote Nodes Guide

**Complete Guide to cRIO and Opto22 Remote Data Acquisition**

---

## Table of Contents

1. [Introduction](#1-introduction)
2. [Hardware Comparison](#2-hardware-comparison)
3. [cRIO Node](#3-crio-node)
4. [Opto22 Node](#4-opto22-node)
5. [Multi-Node Architectures](#5-multi-node-architectures)
6. [Autonomy & Failover](#6-autonomy--failover)
7. [MQTT Topic Reference](#7-mqtt-topic-reference)
8. [Troubleshooting](#8-troubleshooting)

---

## 1. Introduction

### 1.1 What are Remote Nodes?

ICCSFlux remote nodes are standalone data acquisition services that run on embedded hardware (NI cRIO or Opto22 groov EPIC/RIO). They communicate with the central ICCSFlux PC via MQTT, enabling:

- **Distributed I/O** - Place hardware where sensors are located
- **Autonomous Operation** - Continue running if PC disconnects
- **Scalability** - Add more nodes as your system grows
- **Reliability** - Hardware-level safety independent of PC

### 1.2 Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    ICCSFlux Dashboard (Browser)                    │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐                │
│  │   Widgets   │ │   Charts    │ │  Controls   │                │
│  └─────────────┘ └─────────────┘ └─────────────┘                │
└──────────────────────────┬──────────────────────────────────────┘
                           │ WebSocket/MQTT
┌──────────────────────────▼──────────────────────────────────────┐
│                    ICCSFlux Backend (PC)                           │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐           │
│  │   DAQ    │ │  Alarms  │ │ Scripts  │ │ Recording│           │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘           │
└─────────┬──────────────────────┬──────────────────┬─────────────┘
          │                      │                  │
    ┌─────▼─────┐         ┌──────▼──────┐    ┌─────▼─────┐
    │   cDAQ    │         │  cRIO Node  │    │Opto22 Node│
    │  (Local)  │         │  (Remote)   │    │ (Remote)  │
    │ USB/PCIe  │         │   MQTT      │    │   MQTT    │
    └───────────┘         └─────────────┘    └───────────┘
```

### 1.3 When to Use Remote Nodes

| Scenario | Recommended Hardware |
|----------|---------------------|
| Desktop testing | cDAQ (local) |
| Remote lab | cRIO or Opto22 |
| Harsh environment | cRIO (industrial rated) |
| Existing Opto22 system | Opto22 node |
| Multiple locations | Multiple remote nodes |
| Safety-critical | cRIO (hardware watchdog) |

---

## 2. Hardware Comparison

### 2.1 Platform Overview

| Feature | cDAQ | cRIO | Opto22 |
|---------|------|------|--------|
| Connection | USB/PCIe | Ethernet (MQTT) | Ethernet (MQTT) |
| Location | Same PC | Remote | Remote |
| Autonomy | No | Yes | Yes |
| I/O Access | NI-DAQmx | NI-DAQmx | REST API |
| Watchdog | Software | Hardware | Software |
| OS | Windows | NI Linux RT | groov OS |
| User | N/A | admin | dev |
| Price | $$ | $$$ | $$ |

### 2.2 Physical Channel Naming

Each hardware platform has a different naming convention:

```
┌────────────────────────────────────────────────────────────────┐
│ Physical Channel Naming by Hardware Type                        │
├────────────────────────────────────────────────────────────────┤
│                                                                 │
│ cDAQ (Local):     cDAQ{chassis}Mod{slot}/{type}{channel}       │
│                   Example: cDAQ1Mod1/ai0                        │
│                                                                 │
│ cRIO (Remote):    Mod{slot}/{type}{channel}                    │
│                   Example: Mod1/ai0                             │
│                                                                 │
│ Opto22 (Remote):  {ioType}/{moduleIndex}/ch{channelIndex}      │
│                   Example: analogInputs/0/ch0                   │
│                                                                 │
└────────────────────────────────────────────────────────────────┘
```

### 2.3 Channel Type Mapping

| Type | cDAQ | cRIO | Opto22 |
|------|------|------|--------|
| Analog Input | `/ai0` | `/ai0` | `analogInputs/0/ch0` |
| Analog Output | `/ao0` | `/ao0` | `analogOutputs/0/ch0` |
| Digital Input | `/di0` or `/port0/line0` | `/di0` | `digitalInputs/0/ch0` |
| Digital Output | `/do0` or `/port0/line0` | `/do0` | `digitalOutputs/0/ch0` |
| Counter | `/ctr0` | `/ctr0` | N/A |

---

## 3. cRIO Node

### 3.1 Hardware Requirements

| Component | Requirement |
|-----------|-------------|
| Controller | NI CompactRIO with Linux Real-Time |
| Modules | Any NI C-Series I/O module |
| Network | Ethernet (100 Mbps minimum) |
| Storage | 256 MB free space |
| Python | 3.8+ (included in NI Linux RT) |

**Tested Controllers:**
- cRIO-9035
- cRIO-9038
- cRIO-9040
- cRIO-9045

### 3.2 Installation

#### Step 1: Copy Files to cRIO

```bash
scp -r services/crio_node admin@<crio-ip>:/home/admin/
```

#### Step 2: SSH and Run Installer

```bash
ssh admin@<crio-ip>
cd /home/admin/crio_node
chmod +x install.sh
./install.sh <ICCSFLUX_PC_IP> [NODE_ID]
```

**Parameters:**
- `ICCSFLUX_PC_IP` - IP address of the ICCSFlux PC (required)
- `NODE_ID` - Unique identifier for this node (default: `crio-001`)

**Example:**
```bash
./install.sh 192.168.1.100 crio-lab-a
```

#### Step 3: Verify Installation

```bash
systemctl status crio_node.service
journalctl -u crio_node -f
```

### 3.3 Configuration

Configuration file: `/home/admin/nisystem/crio_node.env`

```bash
# MQTT Broker - ICCSFlux PC
MQTT_BROKER=192.168.1.100

# MQTT Port
MQTT_PORT=1883

# Node ID (unique per cRIO)
NODE_ID=crio-001
```

To modify:
```bash
nano /home/admin/nisystem/crio_node.env
sudo systemctl restart crio_node.service
```

### 3.4 Service Commands

| Command | Description |
|---------|-------------|
| `systemctl status crio_node` | Check status |
| `systemctl start crio_node` | Start service |
| `systemctl stop crio_node` | Stop service |
| `systemctl restart crio_node` | Restart service |
| `systemctl enable crio_node` | Enable auto-start |
| `systemctl disable crio_node` | Disable auto-start |
| `journalctl -u crio_node -f` | View live logs |
| `journalctl -u crio_node -n 100` | View last 100 lines |

### 3.5 Safety Features

The cRIO node includes autonomous safety features:

| Feature | Description |
|---------|-------------|
| **Hardware Watchdog** | DAQmx watchdog task monitors scan loop |
| **Safe State** | Outputs go to defined safe values on timeout |
| **Limit Checking** | High/low limits evaluated locally |
| **One-Shot Actions** | Safety actions fire once per event |

**How the Watchdog Works:**
1. Scan loop "pets" the watchdog each cycle
2. If the loop hangs, watchdog times out (default: 5 seconds)
3. All outputs go to configured safe state
4. Event logged and published via MQTT

### 3.6 cRIO-Specific Troubleshooting

| Issue | Solution |
|-------|----------|
| Service won't start | Check `journalctl -u crio_node -n 50` |
| No I/O detected | Run `nilsdev` to list devices |
| MQTT connection fails | Verify PC IP and port 1883 accessible |
| Python errors | Ensure NI Linux RT has Python 3.8+ |
| Module not found | Check module is seated properly |

---

## 4. Opto22 Node

### 4.1 Hardware Requirements

| Component | Requirement |
|-----------|-------------|
| Controller | Opto22 groov EPIC or groov RIO |
| I/O | Any groov I/O module |
| Network | Ethernet (100 Mbps minimum) |
| User | `dev` account access |

**Tested Controllers:**
- groov EPIC PR1
- groov EPIC PR2
- groov RIO

### 4.2 Installation

#### Step 1: Copy Files to groov EPIC

```bash
scp -r services/opto22_node dev@<epic-ip>:/home/dev/
```

#### Step 2: SSH and Run Installer

```bash
ssh dev@<epic-ip>
cd /home/dev/opto22_node
chmod +x install.sh
./install.sh <ICCSFLUX_PC_IP> [NODE_ID] [API_KEY]
```

**Parameters:**
- `ICCSFLUX_PC_IP` - IP address of the ICCSFlux PC (required)
- `NODE_ID` - Unique identifier for this node (default: `opto22-001`)
- `API_KEY` - groov API key if authentication required (optional)

**Example:**
```bash
./install.sh 192.168.1.100 opto22-field
```

#### Step 3: Verify Installation

```bash
systemctl status opto22_node.service
journalctl -u opto22_node -f
```

### 4.3 Configuration

Configuration file: `/home/dev/nisystem/opto22_node.env`

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

### 4.4 groov API Key Setup

If your groov EPIC requires authentication:

1. Open groov Manage in browser: `https://<epic-ip>`
2. Navigate to **Accounts** → **API Keys**
3. Click **Create API Key**
4. Give it a name (e.g., "ICCSFlux Node")
5. Ensure **I/O Access** permission is enabled
6. Copy the generated key
7. Add to environment file:
   ```bash
   nano /home/dev/nisystem/opto22_node.env
   # Add: API_KEY=your-api-key-here
   systemctl restart opto22_node.service
   ```

### 4.5 Service Commands

| Command | Description |
|---------|-------------|
| `systemctl status opto22_node` | Check status |
| `systemctl start opto22_node` | Start service |
| `systemctl stop opto22_node` | Stop service |
| `systemctl restart opto22_node` | Restart service |
| `systemctl enable opto22_node` | Enable auto-start |
| `systemctl disable opto22_node` | Disable auto-start |
| `journalctl -u opto22_node -f` | View live logs |

### 4.6 I/O Channel Discovery

The Opto22 node automatically discovers I/O via the groov REST API:

```bash
# Test REST API access
curl -k https://localhost/api/v1/device/info

# List analog inputs
curl -k https://localhost/api/v1/io/analogInputs
```

Channel naming follows this pattern:
- `analogInputs/0/ch0` - First channel of first analog input module
- `digitalOutputs/1/ch3` - Fourth channel of second digital output module

### 4.7 Opto22-Specific Troubleshooting

| Issue | Solution |
|-------|----------|
| Service won't start | Check `journalctl -u opto22_node -n 50` |
| REST API 401 error | API key required - see Section 4.4 |
| REST API 404 error | Check groov View is running |
| No I/O values | Ensure PAC Control strategy is running |
| SSL certificate error | Service uses `-k` flag for self-signed certs |

---

## 5. Multi-Node Architectures

### 5.1 Single PC, Multiple Nodes

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
    │  Lab A    │         │  Lab B    │         │  Field    │
    │ .101      │         │ .102      │         │ .103      │
    └───────────┘         └───────────┘         └───────────┘
```

Each node needs a unique NODE_ID:
```bash
# Node 1
./install.sh 192.168.1.100 crio-001

# Node 2
./install.sh 192.168.1.100 crio-002

# Node 3
./install.sh 192.168.1.100 opto22-001
```

### 5.2 Node Identification in Dashboard

Remote nodes appear in the Configuration tab discovery tree:

```
Hardware Discovery
├── cDAQ Devices (Local)
│   └── cDAQ1 [Online]
├── cRIO Nodes (Remote) [Blue]
│   ├── crio-001 [Online] ●
│   └── crio-002 [Online] ●
└── Opto22 Nodes (Remote) [Amber]
    └── opto22-001 [Online] ●
```

### 5.3 Channel Tag Naming Convention

For multi-node systems, include the node ID in tag names:

| Node | Channel | Suggested Tag |
|------|---------|---------------|
| crio-001 | Mod1/ai0 | `CRIO1_TC001` |
| crio-002 | Mod1/ai0 | `CRIO2_TC001` |
| opto22-001 | analogInputs/0/ch0 | `OPTO_AI001` |

---

## 6. Autonomy & Failover

### Why Edge Nodes Are the First Line of Defense

For safety-critical applications, remote nodes (cRIO, Opto22) provide autonomous protection that operates independently of the PC:

| Layer | Location | Role |
|-------|----------|------|
| **Primary** | Edge Node | Hardware watchdog, local interlock checks, safe state |
| **Supervisory** | PC Backend | ISA-18.2 alarms, coordination, audit trail |
| **Display** | Browser | Visualization only - no safety decisions |

> **SIL Consideration**: ICCSFlux implements SIL 1 redundant validation - both the edge node AND the PC backend check interlocks before allowing output writes. This provides defense-in-depth: if either layer detects a safety condition, the output is blocked.

### 6.1 What Runs Locally on Remote Nodes

| Feature | Runs on Node | Runs on PC |
|---------|--------------|------------|
| I/O Read | ✓ | |
| I/O Write | ✓ | |
| Safety Limits | ✓ | ✓ (enhanced) |
| Safe State | ✓ | |
| Watchdog | ✓ | |
| Scripts | ✓ (basic) | ✓ (full) |
| Recording | | ✓ |
| Alarms (ISA-18.2) | | ✓ |
| Dashboard | | ✓ |

### 6.2 PC Disconnect Behavior

When the ICCSFlux PC goes offline:

1. **Detection** (30 seconds)
   - Node monitors PC heartbeat
   - After 30 seconds without heartbeat, node enters standalone mode

2. **Standalone Mode**
   - I/O continues reading at configured scan rate
   - Outputs maintain last commanded state
   - Safety limits continue to be evaluated
   - Scripts marked "ALWAYS" keep running
   - Data is NOT recorded (requires PC)

3. **Reconnection**
   - Node automatically reconnects when PC comes back
   - Configuration is re-synced from PC
   - State is published to PC

### 6.3 Safety During PC Disconnect

Remote nodes maintain these safety features independently:

| Safety Feature | Behavior |
|----------------|----------|
| High/Low Limits | Checked every scan |
| Safety Actions | Execute locally |
| Hardware Watchdog | Active (cRIO only) |
| Safe State | Triggered on watchdog timeout |

### 6.4 Configuring Autonomous Safety

In your project configuration, channels can have safety settings that run on the remote node:

```json
{
  "name": "TC001",
  "physical_channel": "Mod1/ai0",
  "high_limit": 200,
  "low_limit": 32,
  "safety_action": "emergency_shutdown"
}
```

The `safety_action` executes on the node without PC involvement.

---

## 7. MQTT Topic Reference

### 7.1 Topics Published by Nodes

| Topic | Direction | Description |
|-------|-----------|-------------|
| `nisystem/nodes/{node-id}/channels/{name}` | Node → PC | Channel values |
| `nisystem/nodes/{node-id}/status/system` | Node → PC | Status + hardware info |
| `nisystem/nodes/{node-id}/heartbeat` | Node → PC | Heartbeat (every 2s) |
| `nisystem/nodes/{node-id}/safety/triggered` | Node → PC | Safety action fired |
| `nisystem/nodes/{node-id}/interlock/blocked` | Node → PC | Write blocked |

### 7.2 Topics Subscribed by Nodes

| Topic | Direction | Description |
|-------|-----------|-------------|
| `nisystem/nodes/{node-id}/config/full` | PC → Node | Full configuration |
| `nisystem/nodes/{node-id}/command/output` | PC → Node | Output write command |
| `nisystem/nodes/{node-id}/session/start` | PC → Node | Start session |
| `nisystem/nodes/{node-id}/session/stop` | PC → Node | Stop session |
| `nisystem/discovery/ping` | PC → All | Trigger status publish |

### 7.3 Message Formats

**Channel Value:**
```json
{
  "value": 72.5,
  "timestamp": 1704299400123,
  "unit": "°F",
  "quality": "good"
}
```

**Heartbeat:**
```json
{
  "node_id": "crio-001",
  "timestamp": 1704299400123,
  "status": "online",
  "scan_count": 12345
}
```

**Status:**
```json
{
  "node_id": "crio-001",
  "node_type": "crio",
  "ip_address": "192.168.1.101",
  "status": "online",
  "channels": 16,
  "modules": [
    {"slot": 1, "type": "NI 9211", "channels": 4}
  ]
}
```

---

## 8. Troubleshooting

### 8.1 Common Issues

| Symptom | Possible Cause | Solution |
|---------|---------------|----------|
| Node not in discovery | Network issue | Check ping to PC |
| Node shows offline | No heartbeat | Check service is running |
| No data from node | MQTT not connected | Verify broker IP |
| Writes not working | Interlock blocked | Check interlock status |
| Safety not triggering | Limits not configured | Check channel config |

### 8.2 Diagnostic Commands

**On cRIO:**
```bash
# Check service
systemctl status crio_node

# Check logs
journalctl -u crio_node -f

# List NI hardware
nilsdev

# Test MQTT
mosquitto_pub -h <pc-ip> -t "test" -m "ping"

# Check network
ping <pc-ip>
ip addr
```

**On Opto22:**
```bash
# Check service
systemctl status opto22_node

# Check logs
journalctl -u opto22_node -f

# Test REST API
curl -k https://localhost/api/v1/device/info

# Test MQTT
mosquitto_pub -h <pc-ip> -t "test" -m "ping"

# Check network
ping <pc-ip>
```

### 8.3 Log File Locations

| Platform | Log Method | Command |
|----------|------------|---------|
| cRIO | journald | `journalctl -u crio_node` |
| Opto22 | journald | `journalctl -u opto22_node` |
| PC | File | `data/logs/daq_service.log` |

### 8.4 Network Debugging

```bash
# Check if MQTT port is open on PC
# From remote node:
nc -zv <pc-ip> 1883

# Check firewall (on PC)
netstat -ano | findstr :1883

# Monitor MQTT traffic (on PC)
mosquitto_sub -h localhost -t "nisystem/#" -v
```

### 8.5 Reinstallation

If issues persist, try reinstalling:

**cRIO:**
```bash
ssh admin@<crio-ip>
systemctl stop crio_node
rm -rf /home/admin/nisystem
cd /home/admin/crio_node
./install.sh <pc-ip> <node-id>
```

**Opto22:**
```bash
ssh dev@<epic-ip>
systemctl stop opto22_node
rm -rf /home/dev/nisystem
cd /home/dev/opto22_node
./install.sh <pc-ip> <node-id>
```

---

## Support

For technical support:
- User Manual: `docs/ICCSFlux_User_Manual.md`
- Administrator Guide: `docs/ICCSFlux_Administrator_Guide.md`
- Contact your system administrator

---

**ICCSFlux Remote Nodes Guide v1.0**
*Last Updated: January 2026*
