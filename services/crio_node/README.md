# cRIO Node Service

Standalone service that runs on NI cRIO-9056 for NISystem integration.

## Overview

This service runs **on the cRIO itself** (not the PC) and:
1. Connects to NISystem PC's MQTT broker
2. Receives configuration and saves it locally
3. Runs DAQ loop with hardware watchdog for safe state
4. Continues running even if PC disconnects
5. Executes Python scripts pushed from NISystem

## Architecture

```
NISystem PC                              cRIO-9056
┌─────────────────┐      MQTT      ┌─────────────────────┐
│  Dashboard      │◄──────────────►│  cRIO Node Service  │
│  Backend        │   Config/Data   │  - Local config     │
│  Project Mgmt   │                 │  - DAQmx watchdog   │
└─────────────────┘                 │  - Python scripts   │
                                    └─────────────────────┘
                                           │
                                    ┌──────┴──────┐
                                    │ C-Series    │
                                    │ Modules     │
                                    │ (TC,DI,DO)  │
                                    └─────────────┘
```

## Installation on cRIO

### 1. Enable SSH on cRIO

Use NI MAX or NI Web-Based Configuration to enable SSH access.

### 2. Copy service files

```bash
scp -r services/crio_node admin@<crio-ip>:/home/admin/nisystem/
```

### 3. Install dependencies

```bash
ssh admin@<crio-ip>
cd /home/admin/nisystem
pip install -r requirements.txt
```

### 4. Configure MQTT broker address

Edit `/home/admin/nisystem/crio_config.json` or use command-line:

```bash
python crio_node.py --broker 192.168.1.100 --port 1884 --node-id crio-001
```

### 5. Start as service (systemd)

Create `/etc/systemd/system/nisystem-crio.service`:

```ini
[Unit]
Description=NISystem cRIO Node Service
After=network.target

[Service]
Type=simple
User=admin
WorkingDirectory=/home/admin/nisystem
ExecStart=/usr/bin/python3 /home/admin/nisystem/crio_node.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable nisystem-crio
sudo systemctl start nisystem-crio
```

## Safe State (Hardware Watchdog)

The service configures an NI-DAQmx hardware watchdog that:
- Monitors the RT task health
- If Python stops "petting" the watchdog (crash, hang, etc.)
- Hardware **automatically** sets configured outputs to LOW

This is **independent of the PC** - purely local hardware mechanism.

### Configuration

In project config, specify which outputs go to safe state:
```json
{
  "safe_state_outputs": ["DO_Heater", "DO_Pump", "DO_Fan"]
}
```

If not specified, all DO channels default to LOW on watchdog expiry.

## MQTT Topics

The service uses node-prefixed topics for multi-node support:

| Topic | Direction | Description |
|-------|-----------|-------------|
| `nisystem/nodes/{node-id}/channels/{name}` | Publish | Channel values |
| `nisystem/nodes/{node-id}/status/system` | Publish | System status |
| `nisystem/nodes/{node-id}/heartbeat` | Publish | Heartbeat (2 Hz) |
| `nisystem/nodes/{node-id}/config/full` | Subscribe | Full config update |
| `nisystem/nodes/{node-id}/commands/{channel}` | Subscribe | Output commands |
| `nisystem/nodes/{node-id}/script/add` | Subscribe | Add script |
| `nisystem/nodes/{node-id}/script/start` | Subscribe | Start script |

## Command Line Options

```
usage: crio_node.py [-h] [-c CONFIG_DIR] [--broker BROKER] [--port PORT] [--node-id NODE_ID]

cRIO Node Service for NISystem

optional arguments:
  -h, --help            show this help message and exit
  -c CONFIG_DIR, --config-dir CONFIG_DIR
                        Configuration directory (default: /home/admin/nisystem)
  --broker BROKER       MQTT broker address (overrides config)
  --port PORT           MQTT broker port (overrides config)
  --node-id NODE_ID     Node ID (overrides config)
```

## Standalone Mode

If the PC disconnects:
1. Service logs "Lost contact with PC - continuing in standalone mode"
2. DAQ continues with last known configuration
3. Scripts continue executing
4. Data is buffered (if recording enabled)
5. When PC reconnects, service resumes normal operation

## Testing Without Hardware

The service falls back to simulation mode if NI-DAQmx is not available:
```
WARNING: nidaqmx not available - running in simulation mode
```
