# Opto22 Node Service

Standalone service that runs on Opto22 groov EPIC/RIO for NISystem integration.

## Quick Start (One-Time Setup)

### 1. Copy files to groov EPIC

```bash
scp -r services/opto22_node dev@<epic-ip>:/home/dev/
```

### 2. Run installer on groov EPIC

```bash
ssh dev@<epic-ip>
cd /home/dev/opto22_node
chmod +x install.sh
./install.sh <YOUR_PC_IP>
```

Example:
```bash
./install.sh 192.168.1.100
```

That's it! The groov EPIC will now:
- Auto-start on boot
- Read I/O via local REST API
- Publish values to NISystem MQTT
- Reconnect automatically if network drops

## What Happens Automatically

1. **Boot** → Opto22 node service starts via systemd
2. **Hardware Detection** → Discovers I/O modules via REST API
3. **MQTT Connect** → Connects to NISystem PC's MQTT broker
4. **Publish Values** → Sends channel values at configured rate
5. **Safety Checks** → Evaluates limits and triggers actions locally

## Architecture

```
NISystem PC                              groov EPIC/RIO
┌─────────────────┐      MQTT      ┌─────────────────────┐
│  Dashboard      │◄──────────────►│  Opto22 Node Service│
│  Backend        │   Config/Data   │  - REST API I/O     │
│  Project Mgmt   │                 │  - Safety logic     │
└─────────────────┘                 │  - Python scripts   │
                                    └─────────────────────┘
                                           │
                                    ┌──────┴──────┐
                                    │ I/O Modules │
                                    │ (AI,AO,DI,DO)│
                                    └─────────────┘
```

## Files

| File | Purpose |
|------|---------|
| `opto22_node.py` | Main service script |
| `opto22_node.service` | Systemd service unit |
| `opto22_node.env` | Configuration (MQTT broker, node ID) |
| `install.sh` | One-click installer |
| `requirements.txt` | Python dependencies |
| `journald-nisystem.conf` | Log rotation config |

## Configuration

After installation, config is at `/home/dev/nisystem/opto22_node.env`:

```bash
# MQTT Broker - NISystem PC
MQTT_BROKER=192.168.1.100

# MQTT Port
MQTT_PORT=1883

# Node ID (change if you have multiple EPICs)
NODE_ID=opto22-001

# groov API Key (optional)
API_KEY=
```

To change settings:
```bash
nano /home/dev/nisystem/opto22_node.env
sudo systemctl restart opto22_node.service
```

## groov API Key (Optional)

If your groov EPIC requires authentication:

1. Log into groov Manage (`https://<epic-ip>`)
2. Go to **Accounts** → **API Keys**
3. Create a new API key
4. Add it to the install command:
   ```bash
   ./install.sh 192.168.1.100 opto22-001 your-api-key-here
   ```

Or edit the env file directly after installation.

## Useful Commands

```bash
# Check status
systemctl status opto22_node.service

# View live logs
journalctl -u opto22_node.service -f

# Restart service
sudo systemctl restart opto22_node.service

# Stop service
sudo systemctl stop opto22_node.service

# Disable auto-start
sudo systemctl disable opto22_node.service
```

## Multiple groov EPICs

If you have multiple EPICs, give each a unique node ID:

```bash
# On EPIC #1
./install.sh 192.168.1.100 opto22-001

# On EPIC #2
./install.sh 192.168.1.100 opto22-002
```

## Safety Features

The service runs safety logic locally on the groov EPIC:

- **Limit Checking**: Evaluates HIHI/HI/LO/LOLO limits on each scan
- **Safety Actions**: Triggers output safe states when limits exceeded
- **Interlocks**: Blocks output writes when conditions not met
- **One-Shot**: Safety actions fire once per event (not continuously)

For hardware-level safe state, configure PAC Control on the groov EPIC separately.

## MQTT Topics

| Topic | Direction | Description |
|-------|-----------|-------------|
| `nisystem/nodes/{node-id}/channels/{name}` | Publish | Channel values |
| `nisystem/nodes/{node-id}/status/system` | Publish | Status + hardware info |
| `nisystem/nodes/{node-id}/heartbeat` | Publish | Heartbeat (every 2s) |
| `nisystem/nodes/{node-id}/config/full` | Subscribe | Full config from PC |
| `nisystem/nodes/{node-id}/command/output` | Subscribe | Output write commands |
| `nisystem/discovery/ping` | Subscribe | Trigger status publish |

## Troubleshooting

### Service won't start
```bash
journalctl -u opto22_node.service -n 50
```

### Can't connect to MQTT
Check the broker IP in `/home/dev/nisystem/opto22_node.env`

### REST API errors
1. Check if groov API is accessible: `curl -k https://localhost/api/v1/device/info`
2. Verify API key if authentication is enabled

### No I/O values
1. Ensure PAC Control strategy is running
2. Check I/O module configuration in groov Manage

### Network issues after reboot
The service waits for network and auto-reconnects. Check:
```bash
ping <nisystem-pc-ip>
```

## Differences from cRIO Node

| Feature | cRIO Node | Opto22 Node |
|---------|-----------|-------------|
| I/O Access | NI-DAQmx | REST API |
| Hardware Watchdog | NI-DAQmx task | PAC Control (separate) |
| Safe State | DAQmx watchdog | Manual via REST |
| User | admin | dev |
| Install Path | /home/admin/nisystem | /home/dev/nisystem |
