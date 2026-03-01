# Opto22 Hybrid Deployment Guide

Complete guide for deploying the CODESYS + Python hybrid system to a groov EPIC.

---

## Prerequisites

### Hardware
- Opto22 groov EPIC (or groov RIO with CODESYS support)
- Ethernet connection to PC (same subnet or routed)
- groov Manage configured with SSH enabled (user: `dev`)
- I/O modules installed and configured in groov Manage

### Software — PC Side
- NISystem project with Opto22 channels configured
- Python 3.10+ with `paramiko` (for SSH/SCP in deploy script)
- CODESYS Development System V3 (for importing generated ST code)
- MQTT credentials auto-generated (`config/mqtt_credentials.json`)
- TLS certificates auto-generated (`config/tls/ca.crt`)

### Software — groov EPIC Side
- Python 3 (pre-installed on groov EPIC)
- `paho-mqtt` pip package (required)
- `pymodbus` pip package (required for CODESYS bridge)
- groov Manage MQTT enabled (for native I/O scanning)
- CODESYS runtime installed (for deterministic PID/interlocks)

---

## Deployment Steps

### Step 1: Configure the Project

In the NISystem dashboard:
1. Add Opto22 device in Configuration tab
2. Map channels to groov I/O modules (GRV-series)
3. Configure PID loops via MQTT commands (PV channel, CV channel, tuning)
4. Configure interlocks (conditions, controls, safe states)
5. **Save the project** — this is critical because the backend injects PID loop state into the project JSON during save. Without saving, PID loops are not persisted.

**Important**: PID loops are configured at runtime via MQTT commands (`pid/loop/{id}/config`) and live in the backend's `pid_engine`. They are **only** written to the project JSON when you explicitly save. The backend injects `pidLoops` into the save data automatically.

### Step 2: Generate Structured Text Code

Generate the CODESYS ST files from the saved project:

```bash
python scripts/generate_codesys_st.py config/projects/MyProject.json
```

Options:
```bash
# Custom output directory (default: dist/codesys_st)
python scripts/generate_codesys_st.py config/projects/MyProject.json --output dist/codesys_st

# Custom project name
python scripts/generate_codesys_st.py config/projects/MyProject.json --name "My Plant"
```

The script reads PID loops, interlocks, and channels from the project JSON and generates 5 files:
- `FB_PID_Loop.st` — PID controller function block
- `FB_Interlock.st` — IEC 61511 interlock state machine
- `FB_SafeState.st` — Safe state output manager
- `GVL_Registers.st` — Global variable list with Modbus register AT declarations
- `Main.st` — Main program (project-specific, wires everything together)

**Note on I/O paths**: Channels in the project JSON may not have groov-specific I/O paths (`io_path`, `groov_module_index`). The script will warn about these — you need to add I/O path assignments to your channel config or manually edit the generated ST code to bind channels to groov module slots.

### Step 3: Deploy Python Node to groov EPIC

```cmd
deploy_opto22.bat [epic_host] [broker_host]
```

Defaults: `192.168.1.30` / `192.168.1.1`

The script performs a 10-step safety-verified deployment:

| Step | Action | Failure behavior |
|------|--------|------------------|
| 1 | SSH connectivity check | Aborts if unreachable |
| 2 | Stop all opto22_node processes | Force-kill, verify 0 processes |
| 3 | Verify Python 3 on EPIC | Aborts if missing |
| 4 | Check pip dependencies | Warns if paho-mqtt/pymodbus missing |
| 5 | SCP 15+ Python files + CODESYS package | All-or-nothing |
| 6 | Write MQTT credentials (chmod 600) | — |
| 7 | Import verification on EPIC | Aborts if imports fail |
| 8 | Deploy generated ST files to EPIC | Copies `dist/codesys_st/*.st` |
| 9 | Install + start systemd service | Enables on boot |
| 10 | Verify exactly 1 process running | Fails on 0 or >1 (split-brain) |

After this step, the **Python companion** is running on the EPIC and connecting to the NISystem MQTT broker over TLS.

### Step 4: Import ST Code into CODESYS IDE

This is the **manual step** — CODESYS requires its IDE for compilation and download.

1. **Open CODESYS Development System V3**

2. **Create or open project**
   - File → New Project → Standard Project
   - Device: Opto22 groov EPIC (select correct target)
   - Language: Structured Text

3. **Import function blocks**
   - Project → Import → select `FB_PID_Loop.st`
   - Repeat for `FB_Interlock.st`, `FB_SafeState.st`
   - These appear as POUs (Program Organization Units) under Application

4. **Import global variable list**
   - Project → Import → select `GVL_Registers.st`
   - Or: Add → Global Variable List, paste contents
   - Verify AT declarations match register map

5. **Replace Main program**
   - Open the default `PLC_PRG` or `Main` POU
   - Replace contents with generated `Main.st`
   - Or: delete default Main, import `Main.st`

6. **Add Modbus TCP Slave device**
   - In Device tree, right-click the controller → Add Device
   - Select Modbus TCP Slave (the EPIC acts as Modbus server, Python is the client)
   - Configure: IP = `127.0.0.1`, Port = `502`, Unit ID = `1`
   - Map I/O: connect GVL_Registers variables to the Modbus device

7. **Set task configuration**
   - Task → MainTask → Interval: `T#1ms` (1 ms cycle)
   - Priority: highest available
   - Watchdog: enabled, 100 ms

8. **Build and download**
   - Build → Build (check for errors)
   - Online → Login
   - Download → Start

### Step 5: Verify Hybrid Operation

After both Python and CODESYS are running:

1. **Check Python node status** on the EPIC:
   ```bash
   ssh dev@192.168.1.30
   systemctl status opto22_node
   journalctl -u opto22_node -f
   ```

   Look for:
   ```
   CODESYS bridge started: localhost:502 polling N tags at 10.0 Hz
   CODESYS mode activated — PID/interlocks running in PLC
   ```

2. **Check MQTT status** in the NISystem dashboard:
   - System Status widget should show Opto22 node online
   - CODESYS status: `available: true`, `mode_active: true`

3. **Verify PID control**:
   - Change a setpoint in the dashboard
   - Confirm PV tracks SP (via CODESYS, 1 ms control loop)
   - Check PID status widget shows CV output

4. **Test failover**:
   - Stop CODESYS runtime in CODESYS IDE (Online → Stop)
   - Python logs: `"CODESYS lost — falling back to Python PID/safety"`
   - PID control continues (at Python scan rate, ~10 Hz instead of 1 kHz)
   - Restart CODESYS → `"CODESYS mode activated"`

5. **Test safety**:
   - Arm an interlock, trigger the condition
   - Verify trip in both CODESYS (via Modbus status registers) and Python (via MQTT)
   - Verify safe state applied to outputs

---

## File Locations on groov EPIC

After deployment, files are at:

```
/home/dev/nisystem/
├── run_opto22.py              # Entry point (started by systemd)
├── mqtt_creds.json            # MQTT credentials (chmod 600)
├── ca.crt                     # TLS CA certificate
├── logs/
│   └── opto22_node.log        # Rotating log (5 MB x 3)
├── opto22_node/               # Python package
│   ├── __init__.py
│   ├── opto22_node.py         # Main service
│   ├── safety.py              # ISA-18.2 + IEC 61511
│   ├── script_engine.py       # Script sandbox
│   ├── codesys_bridge.py      # Modbus TCP bridge
│   ├── config.py              # Configuration
│   ├── hardware.py            # groov I/O interface
│   ├── mqtt_interface.py      # Dual MQTT
│   ├── state_machine.py       # State management
│   ├── pid_engine.py          # Python PID fallback
│   ├── sequence_manager.py    # Sequences
│   ├── trigger_engine.py      # Triggers
│   ├── watchdog_engine.py     # Watchdog
│   ├── channel_types.py       # Module database
│   ├── audit_trail.py         # SHA-256 audit
│   └── codesys/               # CODESYS integration
│       ├── __init__.py
│       ├── register_map.py    # Modbus register allocation
│       ├── st_codegen.py      # ST code generator
│       └── templates/         # Jinja2 ST templates
│           ├── fb_pid_loop.st.j2
│           ├── fb_interlock.st.j2
│           ├── fb_safe_state.st.j2
│           ├── gvl_registers.st.j2
│           └── main_program.st.j2
└── codesys_st/                # Generated ST files (for reference)
    ├── FB_PID_Loop.st
    ├── FB_Interlock.st
    ├── FB_SafeState.st
    ├── GVL_Registers.st
    └── Main.st
```

Systemd unit: `/etc/systemd/system/opto22_node.service`

---

## Register Map Reference

Python ↔ CODESYS communication via Modbus TCP (localhost:502):

### Holding Registers (Python → CODESYS)

| Address Range | Content | Type | Capacity |
|---------------|---------|------|----------|
| 40001–40100 | PID setpoints | float32 (2 regs each) | 50 loops |
| 40101–40250 | PID tuning (Kp, Ki, Kd) | float32 triplets | 50 loops |
| 40401–40500 | Interlock commands | uint16 pairs | 50 interlocks |
| 40501–40600 | Output override values | float32 | 50 outputs |
| 40601–40610 | System commands | uint16 | E-stop, mode, heartbeat, acquire, config version |

### Input Registers (CODESYS → Python)

| Address Range | Content | Type | Capacity |
|---------------|---------|------|----------|
| 30001–30100 | PID CV outputs | float32 | 50 loops |
| 30101–30300 | Process values | float32 | 100 channels |
| 30301–30400 | Interlock status + trip counts | uint16 pairs | 50 interlocks |
| 30401–30410 | System status | uint16 | Scan time, error count, watchdog |

### Coils (Python → CODESYS)

| Address Range | Content | Capacity |
|---------------|---------|----------|
| 00001–00050 | PID enable flags | 50 loops |
| 00051–00100 | PID manual mode flags | 50 loops |
| 00101–00150 | Interlock arm commands | 50 interlocks |
| 00151–00200 | Interlock bypass flags | 50 interlocks |

### Discrete Inputs (CODESYS → Python)

| Address Range | Content | Capacity |
|---------------|---------|----------|
| 10001–10050 | Interlock tripped flags | 50 interlocks |
| 10051–10100 | PID active flags | 50 loops |
| 10101–10110 | System health flags | System |

---

## Watchdog Behavior

### Python → CODESYS Heartbeat
- Python increments `SYS_HEARTBEAT` register (40607) every scan cycle
- CODESYS watches this counter; if it stops incrementing for 5 seconds:
  - PLC assumes Python companion is dead
  - PLC applies safe state to ALL outputs autonomously
  - PLC continues running PID in last-known-good configuration

### CODESYS → Python Health
- Python reads `codesys_available` property every scan:
  - `_connected` = Modbus TCP socket open
  - `_last_read_time` < 5 seconds ago
  - `_consecutive_errors` < 3
- If any check fails → Python fallback mode activates

---

## Redeployment After Config Changes

When the project configuration changes (channels, PID loops, interlocks):

1. **Regenerate ST code** (Step 2)
2. **Redeploy Python node** (Step 3) — `deploy_opto22.bat`
3. **Re-import ST into CODESYS** (Step 4) — only `GVL_Registers.st` and `Main.st` typically change
4. **Download to PLC** — Build → Download → Start

The Python deploy script handles the Python side atomically. The CODESYS side requires IDE access.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `"CODESYS bridge error"` in logs | Modbus TCP not responding | Check CODESYS runtime is running; check port 502 |
| `"CODESYS lost — falling back"` | CODESYS stopped or 3+ Modbus errors | Restart CODESYS runtime; check for PLC crash |
| Python node not starting | Import errors, missing deps | Run step 7 manually: `ssh dev@epic python3 -c "from opto22_node.config import NodeConfig"` |
| Split-brain (>1 process) | Failed deploy or manual start | `ssh dev@epic "pkill -9 -f run_opto22.py"` then re-deploy |
| No I/O values | groov MQTT not running | Check groov Manage → MQTT → Enabled |
| Stale channel warnings | groov MQTT topic mismatch | Verify channel config topic paths match groov Manage topics |
| PID not tracking | Wrong register mapping | Compare `GVL_Registers.st` addresses with `register_map.py` |
| Interlock won't trip | Condition direction wrong | `satisfied=True` means safe; check condition semantics |
| TLS connection refused | CA cert not deployed | Re-run deploy (step copies `ca.crt`) |
