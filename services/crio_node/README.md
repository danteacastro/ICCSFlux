# cRIO Node Service

Standalone service that runs on NI cRIO-9056 for NISystem integration.

## Quick Start (One-Time Setup)

### 1. Copy files to cRIO

```bash
scp -r services/crio_node admin@<crio-ip>:/home/admin/
```

### 2. Run installer on cRIO

```bash
ssh admin@<crio-ip>
cd /home/admin/crio_node
chmod +x install.sh
./install.sh <YOUR_PC_IP>
```

Example:
```bash
./install.sh 192.168.1.100
```

That's it! The cRIO will now:
- Auto-start on boot
- Auto-detect all 96 channels
- Auto-read and publish values to MQTT
- Reconnect automatically if network drops

## What Happens Automatically

1. **Boot** → cRIO node service starts via systemd
2. **Hardware Detection** → Finds all 6 modules and 96 channels
3. **Auto-Read** → Starts reading ALL channels immediately (no config needed)
4. **MQTT Connect** → Connects to NISystem PC's MQTT broker
5. **Publish Values** → Sends channel values every 100ms

## Architecture

```
NISystem PC                              cRIO-9056
┌─────────────────┐      MQTT      ┌─────────────────────┐
│  Dashboard      │◄──────────────►│  cRIO Node Service  │
│  Backend        │   Config/Data   │  - Auto-detect HW   │
│  Project Mgmt   │                 │  - Auto-read all    │
└─────────────────┘                 │  - DAQmx watchdog   │
                                    └─────────────────────┘
                                           │
                                    ┌──────┴──────┐
                                    │ C-Series    │
                                    │ Modules     │
                                    │ (TC,DI,DO)  │
                                    └─────────────┘
```

## Files

| File | Purpose |
|------|---------|
| `crio_node.py` | Main service script |
| `crio_node.service` | Systemd service unit |
| `crio_node.env` | Configuration (MQTT broker, node ID) |
| `install.sh` | One-click installer |
| `requirements.txt` | Python dependencies |

## Configuration

After installation, config is at `/home/admin/nisystem/crio_node.env`:

```bash
# MQTT Broker - NISystem PC
MQTT_BROKER=192.168.1.100

# MQTT Port
MQTT_PORT=1883

# Node ID (change if you have multiple cRIOs)
NODE_ID=crio-001
```

To change settings:
```bash
sudo nano /home/admin/nisystem/crio_node.env
sudo systemctl restart crio_node.service
```

## Useful Commands

```bash
# Check status
systemctl status crio_node.service

# View live logs
journalctl -u crio_node.service -f

# Restart service
sudo systemctl restart crio_node.service

# Stop service
sudo systemctl stop crio_node.service

# Disable auto-start
sudo systemctl disable crio_node.service
```

## Multiple cRIOs

If you have multiple cRIOs, give each a unique node ID:

```bash
# On cRIO #1
./install.sh 192.168.1.100 crio-001

# On cRIO #2
./install.sh 192.168.1.100 crio-002
```

## Safe State (Hardware Watchdog)

The service configures an NI-DAQmx hardware watchdog:
- Monitors the RT task health
- If Python crashes/hangs, hardware automatically sets outputs to LOW
- Independent of PC connection - purely local hardware safety

## MQTT Topics

| Topic | Direction | Description |
|-------|-----------|-------------|
| `nisystem/nodes/{node-id}/channels/{name}` | Publish | Channel values |
| `nisystem/nodes/{node-id}/status/system` | Publish | Status + hardware info |
| `nisystem/nodes/{node-id}/heartbeat` | Publish | Heartbeat (every 2s) |
| `nisystem/discovery/ping` | Subscribe | Trigger status publish |

## Troubleshooting

### Service won't start
```bash
journalctl -u crio_node.service -n 50
```

### Can't connect to MQTT
Check the broker IP in `/home/admin/nisystem/crio_node.env`

### No channels detected
```bash
# Check if nidaqmx sees hardware
python3 -c "import nidaqmx.system; print(list(nidaqmx.system.System.local().devices))"
```

### Network issues after reboot
The service waits for network and auto-reconnects. Check:
```bash
ping <nisystem-pc-ip>
```
