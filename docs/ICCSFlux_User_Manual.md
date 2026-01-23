# ICCSFlux User Manual

**Version 1.0**
**Industrial Data Acquisition & Control System**

---

## Table of Contents

1. [Introduction](#1-introduction)
2. [Getting Started](#2-getting-started)
3. [Dashboard Overview](#3-dashboard-overview)
4. [Widgets Reference](#4-widgets-reference)
5. [Configuration Tab](#5-configuration-tab)
6. [Remote Nodes](#6-remote-nodes)
7. [Scripts & Automation Tab](#7-scripts--automation-tab)
8. [Safety System Tab](#8-safety-system-tab)
9. [Data Recording Tab](#9-data-recording-tab)
10. [Admin Tab](#10-admin-tab)
11. [Notes Tab](#11-notes-tab)
12. [User Roles & Permissions](#12-user-roles--permissions)
13. [Keyboard Shortcuts](#13-keyboard-shortcuts)
14. [Troubleshooting](#14-troubleshooting)
15. [Glossary](#15-glossary)

---

## 1. Introduction

### 1.1 What is ICCSFlux?

ICCSFlux is an industrial-grade data acquisition and control system designed for laboratory testing, manufacturing, and process monitoring. It provides:

- **Real-time data visualization** with customizable dashboards
- **Multi-channel data acquisition** supporting thermocouples, RTDs, voltage/current inputs, digital I/O, and more
- **Automated test sequences** with conditional logic and loops
- **Safety interlocks** compliant with ISA-18.2 alarm management standards
- **Data recording** with 21 CFR Part 11 compliance for regulated industries
- **Python scripting** for advanced calculations and custom logic

### 1.2 System Architecture

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

### 1.3 Key Features

| Feature | Description |
|---------|-------------|
| Multi-Channel DAQ | Up to 100+ channels at 100 Hz scan rate |
| Real-Time Display | Live updates at configurable publish rates |
| Test Automation | 50+ step types for complex test sequences |
| Safety Interlocks | Condition-based output gating with bypass audit |
| Alarm Management | ISA-18.2 compliant with first-out detection |
| Data Recording | CSV/TDMS with trigger-based capture |
| Python Scripting | Server-side Python scripts with full ecosystem |
| Compliance | 21 CFR Part 11 audit trail support |

---

## 2. Getting Started

### 2.1 Launching ICCSFlux

1. **Start the backend service:**
   ```
   Double-click: start.bat
   ```

2. **Open the dashboard:**
   - The browser opens automatically to `http://localhost:5173`
   - Or navigate manually to the URL

3. **Login (if required):**
   - Contact your administrator for login credentials

### 2.2 First-Time Setup

1. **Create channels** in the Configuration tab
2. **Set alarm thresholds** for critical measurements
3. **Define safety interlocks** for output protection
4. **Build your dashboard** with widgets
5. **Save your project** for backup

### 2.3 Quick Start: Running a Test

1. Click **START** in the control bar to begin data acquisition
2. Click **RECORD** to save data to file
3. Toggle **SESSION** to enable automated sequences
4. Monitor values on your dashboard widgets
5. Click **STOP** when finished

---

## 3. Dashboard Overview

### 3.1 Header Bar

```
┌────────────────────────────────────────────────────────────────────┐
│ [Logo] ICCSFlux │ Overview │ Config │ Scripts │ Data │ Safety │ ... │
├────────────────────────────────────────────────────────────────────┤
│              [START] [RECORD] [SESSION] │ [+Widget] [Edit] │ User │
└────────────────────────────────────────────────────────────────────┘
```

#### Navigation Tabs

| Tab | Purpose | Access Level |
|-----|---------|--------------|
| **Overview** | Main dashboard with widgets | All users |
| **Config** | Channel and system configuration | Operator+ to edit |
| **Scripts** | Automation, sequences, formulas | Supervisor+ to edit |
| **Data** | Recording management and export | Operator+ to edit |
| **Safety** | Alarms and interlocks | Supervisor+ to edit |
| **Notes** | Documentation and notes | All users |
| **Admin** | User management and audit trail | Supervisor+ (Users: Admin only) |

#### Control Buttons

| Button | Function | Shortcut |
|--------|----------|----------|
| **START/STOP** | Begin/end data acquisition | - |
| **RECORD** | Start/stop data recording | - |
| **SESSION** | Enable/disable automation engine | - |
| **+ Widget** | Add new widget (edit mode) | - |
| **Edit** | Toggle dashboard edit mode | - |

### 3.2 Page Selector

ICCSFlux supports multiple dashboard pages for organizing different views:

- Click the page dropdown next to "Overview"
- Select a page or create a new one
- Each page has independent widget layouts

### 3.3 Edit Mode

When Edit Mode is enabled:
- Drag widgets to reposition
- Resize widgets using corner handles
- Click widget menu (⋮) for options
- Draw pipe connections between widgets

---

## 4. Widgets Reference

### 4.1 Display Widgets

#### Numeric Display
Shows a channel value with configurable formatting.

| Setting | Description |
|---------|-------------|
| Channel | Data source to display |
| Precision | Decimal places (0-6) |
| Show Unit | Display engineering unit |
| Show Tag | Display channel identifier |
| Min/Max | Value range for bar indicator |

#### Gauge
Circular analog-style gauge for visual monitoring.

| Setting | Description |
|---------|-------------|
| Channel | Data source |
| Min/Max | Gauge scale range |
| Warning/Alarm | Color threshold zones |
| Show Value | Display numeric value |

#### LED Indicator
Boolean status display (ON/OFF).

| Setting | Description |
|---------|-------------|
| Channel | Digital input source |
| On Color | Color when TRUE (default: green) |
| Off Color | Color when FALSE (default: gray) |
| Invert | Swap ON/OFF logic |

#### Sparkline
Compact trend chart with current value.

| Setting | Description |
|---------|-------------|
| Channel | Data source |
| History | Number of points to display |
| Show Value | Display current value |
| Color | Line color |

#### Bar Graph
Horizontal or vertical bar visualization.

| Setting | Description |
|---------|-------------|
| Channel | Data source |
| Min/Max | Bar scale range |
| Orientation | Horizontal or Vertical |
| Show Value | Display numeric value |

#### Value Table
Industrial-style compact multi-value display.

| Setting | Description |
|---------|-------------|
| Channels | List of channels to display |
| Compact | Reduce spacing |
| Show Limits | Display alarm thresholds |

#### Clock
Time display with optional elapsed timer.

| Setting | Description |
|---------|-------------|
| Show Date | Display current date |
| Show Elapsed | Session elapsed time |
| Format | 12-hour or 24-hour |

### 4.2 Control Widgets

#### Toggle Switch
Control digital outputs.

| Setting | Description |
|---------|-------------|
| Channel | Digital output to control |
| Mode | Toggle (latching) or Pulse (momentary) |
| Pulse Duration | Duration for pulse mode (ms) |
| Confirm | Require confirmation before switching |

#### Setpoint
Adjust analog output values.

| Setting | Description |
|---------|-------------|
| Channel | Analog output to control |
| Min/Max | Allowed setpoint range |
| Step | Increment/decrement amount |
| Show Slider | Display slider control |

#### Action Button
Execute scripts or sequences on click.

| Setting | Description |
|---------|-------------|
| Action | Sequence ID or script to run |
| Label | Button text |
| Color | Button color |
| Confirm | Require confirmation |

#### Latch Switch
Safety-critical latching control.

| Setting | Description |
|---------|-------------|
| Output | Digital output to control |
| Arm Required | Must arm before enabling |
| Interlock | Associated safety interlock |

### 4.3 Status Widgets

#### Alarm Summary
Shows active alarms with severity levels.

| Display | Description |
|---------|-------------|
| Active Count | Number of unacknowledged alarms |
| Severity | Critical/High/Medium/Low breakdown |
| First Out | First alarm in cascade |
| Click | Opens Safety tab |

#### System Status
Overall system health indicator.

| Display | Description |
|---------|-------------|
| Connection | MQTT broker status |
| Acquisition | DAQ running/stopped |
| Recording | Recording active/stopped |
| Scheduler | Automation enabled/disabled |

#### Interlock Status
Safety interlock satisfaction display.

| Display | Description |
|---------|-------------|
| Status | SATISFIED or BLOCKED |
| Failed | List of unsatisfied conditions |
| Bypassed | Bypass status and timeout |

#### Script Monitor
Real-time Python script output display.

| Setting | Description |
|---------|-------------|
| Values | List of py.* values to display |
| Format | Number, percentage, status |
| Thresholds | Color-code based on value |

### 4.4 Chart Widgets

#### Trend Chart
Multi-channel time-series visualization.

| Setting | Description |
|---------|-------------|
| Channels | Data sources to plot |
| Time Range | History duration (seconds) |
| Update Mode | Strip, Scope, or Sweep |
| Y-Axis | Auto-scale or fixed range |
| Dual Axis | Enable second Y-axis |

**Chart Controls:**
- **Zoom**: Scroll wheel or pinch
- **Pan**: Click and drag
- **Cursor**: Click to place measurement cursor
- **Pause**: Freeze display (data continues recording)

### 4.5 Structural Widgets

#### Title
Text header for organizing dashboard.

| Setting | Description |
|---------|-------------|
| Text | Title content |
| Size | Small, Medium, Large |
| Alignment | Left, Center, Right |

#### Divider
Visual separator line.

| Setting | Description |
|---------|-------------|
| Style | Solid, Dashed, Dotted |
| Color | Line color |

#### P&ID Symbol
SCADA-style equipment symbols with animation.

| Symbol Types | Description |
|--------------|-------------|
| Valve | Gate, ball, butterfly, check |
| Pump | Centrifugal, positive displacement |
| Tank | Vertical, horizontal |
| Sensor | Temperature, pressure, flow |
| Motor | Electric motor symbol |

| Setting | Description |
|---------|-------------|
| Symbol | Equipment type |
| State Channel | Input for animation |
| Rotation | 0°, 90°, 180°, 270° |

---

## 5. Configuration Tab

### 5.1 Channel Management

#### Adding a Channel

1. Click **+ Add Channel**
2. Select channel type:
   - **Thermocouple** (J, K, T, E, N, R, S, B)
   - **RTD** (Pt100, Pt500, Pt1000)
   - **Voltage** (±10V, ±5V, ±1V, 0-10V)
   - **Current** (4-20mA, 0-20mA)
   - **Digital Input** (5V or 24V logic)
   - **Digital Output** (5V or 24V logic)
   - **Counter** (edge, frequency, pulse width)
   - **Modbus** (register or coil)

3. Configure channel settings:
   - **Tag**: Unique identifier (e.g., TC001, TEMP_INLET)
   - **Description**: Human-readable name
   - **Unit**: Engineering unit (°F, PSI, GPM)
   - **Device/Terminal**: Physical connection

4. Set scaling (optional):
   - **Linear**: y = mx + b
   - **4-20mA**: Map current to engineering range
   - **Polynomial**: Multi-coefficient curve
   - **Map**: Point-to-point lookup

5. Configure alarms:
   - **HiHi**: Critical high threshold
   - **Hi**: Warning high threshold
   - **Lo**: Warning low threshold
   - **LoLo**: Critical low threshold

#### Channel Types Reference

| Type | Use Case | Configuration |
|------|----------|---------------|
| Thermocouple | Temperature measurement | Type, CJC source |
| RTD | Precision temperature | Type, wire config (2/3/4) |
| Voltage | Analog signals | Range, terminal config |
| Current | Loop transmitters | Range (4-20mA typical) |
| Strain | Load cells, pressure | Bridge config, excitation |
| IEPE | Accelerometers | Sensitivity, coupling |
| Counter | Flow, speed, events | Edge type, gate time |
| Digital In | Switches, sensors | Logic level, invert |
| Digital Out | Relays, indicators | Logic level, safe state |
| Modbus | Remote devices | Address, register, function |

### 5.2 Safety Actions

Define actions that can be triggered by alarms or interlocks:

| Action Type | Description |
|-------------|-------------|
| **Trip System** | Set all outputs to safe state |
| **Stop Session** | Disable automation engine |
| **Stop Recording** | End current recording |
| **Set Output** | Set specific output to value |
| **Run Sequence** | Execute emergency sequence |

### 5.3 System Settings

| Setting | Description | Default |
|---------|-------------|---------|
| Scan Rate | Hardware sample rate (Hz) | 10 |
| Publish Rate | Dashboard update rate (Hz) | 2 |
| Simulation Mode | Generate simulated data | OFF |
| Node ID | Multi-node identifier | node-001 |

### 5.4 Project Management

- **Export Project**: Download complete configuration as JSON
- **Import Project**: Load configuration from file
- **Save**: Save current configuration to backend
- **Reload**: Discard changes and reload from backend

---

## 6. Remote Nodes

ICCSFlux supports three hardware platforms for data acquisition. This chapter explains how to configure and use remote nodes for distributed I/O.

### 6.1 Hardware Platform Overview

| Platform | Connection | Use Case |
|----------|------------|----------|
| **cDAQ** | USB/PCIe (Local) | Desktop testing, high-speed acquisition |
| **cRIO** | MQTT (Remote) | Rugged environments, autonomous operation |
| **Opto22** | MQTT (Remote) | groov EPIC/RIO systems |

### 6.2 Project Modes

The project mode setting determines the default hardware source for new channels:

| Mode | Hardware | Physical Channel Format | Example |
|------|----------|------------------------|---------|
| cDAQ | Local NI chassis | `cDAQ{chassis}Mod{slot}/{type}{#}` | `cDAQ1Mod1/ai0` |
| cRIO | Remote NI CompactRIO | `Mod{slot}/{type}{#}` | `Mod1/ai0` |
| Opto22 | Remote groov EPIC/RIO | `{ioType}/{module}/ch{#}` | `analogInputs/0/ch0` |

To set the project mode:
1. Go to **Config** tab
2. Select **Project Mode** dropdown
3. Choose your primary hardware platform

### 6.3 cRIO Node Setup

#### Requirements
- NI CompactRIO with Linux Real-Time
- Network connection to PC
- SSH access enabled

#### One-Click Installation

1. **Copy files to cRIO:**
   ```bash
   scp -r services/crio_node admin@<crio-ip>:/home/admin/
   ```

2. **Run installer on cRIO:**
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

3. **Verify installation:**
   ```bash
   systemctl status crio_node.service
   ```

The cRIO will now:
- Auto-start on boot
- Read I/O via NI-DAQmx
- Publish values to ICCSFlux PC via MQTT
- Execute safety logic locally

#### cRIO Configuration

After installation, edit `/home/admin/nisystem/crio_node.env`:

```bash
# MQTT Broker - ICCSFlux PC
MQTT_BROKER=192.168.1.100

# MQTT Port
MQTT_PORT=1883

# Node ID (unique per cRIO)
NODE_ID=crio-001
```

#### cRIO Commands

| Command | Description |
|---------|-------------|
| `systemctl status crio_node` | Check service status |
| `journalctl -u crio_node -f` | View live logs |
| `systemctl restart crio_node` | Restart service |
| `systemctl stop crio_node` | Stop service |

### 6.4 Opto22 Node Setup

#### Requirements
- Opto22 groov EPIC or groov RIO
- Network connection to PC
- SSH access as `dev` user

#### One-Click Installation

1. **Copy files to groov EPIC:**
   ```bash
   scp -r services/opto22_node dev@<epic-ip>:/home/dev/
   ```

2. **Run installer on groov EPIC:**
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

3. **Verify installation:**
   ```bash
   systemctl status opto22_node.service
   ```

The groov EPIC will now:
- Auto-start on boot
- Read I/O via local REST API
- Publish values to ICCSFlux PC via MQTT
- Reconnect automatically if network drops

#### Opto22 API Key (Optional)

If your groov EPIC requires authentication:

1. Log into groov Manage (`https://<epic-ip>`)
2. Go to **Accounts** → **API Keys**
3. Create a new API key
4. Add to install command:
   ```bash
   ./install.sh 192.168.1.100 opto22-001 your-api-key-here
   ```

#### Opto22 Commands

| Command | Description |
|---------|-------------|
| `systemctl status opto22_node` | Check service status |
| `journalctl -u opto22_node -f` | View live logs |
| `systemctl restart opto22_node` | Restart service |
| `systemctl stop opto22_node` | Stop service |

### 6.5 Node Discovery

Remote nodes appear automatically in the **Config** tab discovery tree:

```
Hardware Discovery
├── cDAQ Devices (Local)
│   └── cDAQ1 [Online]
│       └── Mod1: NI 9211 (4ch Thermocouple)
├── cRIO Nodes (Remote)
│   └── crio-001 [Online] ●
│       └── Mod1: NI 9211 (4ch Thermocouple)
└── Opto22 Nodes (Remote)
    └── opto22-001 [Online] ●
        └── Module 0: GRV-IAC-24 (8ch AI)
```

**Status Indicators:**
- **Green** ● = Online, heartbeat received within 10s
- **Yellow** ● = Warning, data may be stale
- **Red** ● = Offline, no heartbeat

### 6.6 Adding Channels from Remote Nodes

When adding a channel, select the source type and node:

1. Click **+ Add Channel**
2. Select **Source Type**: cDAQ, cRIO, or Opto22
3. If remote source, select **Node**: e.g., `crio-001`
4. Enter **Physical Channel** using the correct format:

| Source | Example Physical Channel |
|--------|-------------------------|
| cDAQ | `cDAQ1Mod1/ai0` |
| cRIO | `Mod1/ai0` |
| Opto22 | `analogInputs/0/ch0` |

### 6.7 Multi-Node Systems

ICCSFlux supports multiple remote nodes simultaneously:

```
                           ┌──────────────┐
                           │   ICCSFlux PC  │
                           │ MQTT Broker  │
                           └──────┬───────┘
                                  │
          ┌───────────────────────┼───────────────────────┐
          │                       │                       │
    ┌─────▼─────┐          ┌─────▼─────┐          ┌─────▼─────┐
    │ cRIO-001  │          │ cRIO-002  │          │opto22-001 │
    │  Lab A    │          │  Lab B    │          │  Field    │
    └───────────┘          └───────────┘          └───────────┘
```

Each node needs a unique Node ID set during installation:

```bash
# On cRIO #1
./install.sh 192.168.1.100 crio-001

# On cRIO #2
./install.sh 192.168.1.100 crio-002

# On Opto22
./install.sh 192.168.1.100 opto22-001
```

### 6.8 Autonomy & Failover

Remote nodes can operate autonomously if the PC disconnects:

| Feature | cRIO | Opto22 |
|---------|------|--------|
| Continue reading inputs | ✓ | ✓ |
| Maintain output states | ✓ | ✓ |
| Execute safety limits | ✓ | ✓ |
| Run local scripts | ✓ | ✓ |
| Auto-reconnect | ✓ | ✓ |

**What happens when PC disconnects:**
1. Node detects loss of PC heartbeat (30s timeout)
2. Node continues with last known configuration
3. Safety limits remain active
4. Scripts marked "ALWAYS" continue running
5. When PC reconnects, node syncs state

> **Note:** Data recording requires PC connection. For critical applications, ensure network redundancy.

---

## 7. Scripts & Automation Tab

### 7.1 Sub-Tab Navigation

| Sub-Tab | Purpose |
|---------|---------|
| Session | Test session control |
| Variables | User-defined variables |
| Python | Python script editor |
| Formulas | Calculated parameters |
| Blocks | Function block editor |
| Sequences | Test sequence builder |
| Draw Patterns | Valve dosing patterns |
| Schedule | Time-based automation |
| Alarms | Conditional alarms |
| Transforms | Data conditioning |
| Triggers | Event-based automation |
| Watchdogs | System health monitoring |
| Templates | Pre-built recipes |

### 7.2 Formulas (Calculated Parameters)

Create derived channels using JavaScript expressions.

**Example Formulas:**

```javascript
// Temperature average
(ch.TC001 + ch.TC002 + ch.TC003) / 3

// Pressure differential
ch.P_INLET - ch.P_OUTLET

// Flow rate from differential pressure
Math.sqrt(ch.DP_FLOW) * 10.5

// Boolean condition
ch.TEMP > 150 ? 1 : 0
```

**Available Functions:**
- Math: `abs()`, `sqrt()`, `pow()`, `log()`, `exp()`
- Trig: `sin()`, `cos()`, `tan()`, `atan2()`
- Stats: `min()`, `max()`
- Conditional: ternary operator `? :`

### 7.3 Sequences (Test Recipes)

Build automated test procedures with step-by-step execution.

#### Step Types

| Category | Steps |
|----------|-------|
| **Setpoint Control** | Set Output, Ramp, Soak |
| **Waiting** | Wait Time, Wait Condition, Wait Stable |
| **Flow Control** | If/Else, Loop, Call Sequence |
| **Recording** | Start Recording, Stop Recording, Mark Event |
| **Variables** | Set Variable, Increment, Calculate |
| **Safety** | Check Interlock, Verify Condition |
| **Notification** | Log Message, Show Alert, Play Sound |

#### Example Sequence: Thermal Warmup

```
1. [Set Output] Heater → ON
2. [Wait Condition] TC001 >= 150°F, timeout: 30 min
3. [Soak] Hold for 15 minutes
4. [Log] "Warmup complete"
5. [Start Recording] filename: "thermal_test"
6. [Ramp] Setpoint → 200°F at 2°F/min
7. [Wait Stable] TC001 within ±2°F for 5 min
8. [Stop Recording]
9. [Set Output] Heater → OFF
```

#### Sequence States

| State | Description |
|-------|-------------|
| Idle | Not running |
| Running | Executing steps |
| Paused | Temporarily halted |
| Completed | Finished successfully |
| Aborted | Stopped by user |
| Error | Failed with error |

### 7.4 Python Scripts

Write custom logic using server-side Python with full ecosystem access.

#### Script Template

```python
# ICCSFlux Python Script
# Runs while session is active

while session.active:
    # Read channel values (from any hardware: cDAQ, cRIO, Opto22)
    temp = tags.TC001        # Attribute style
    pressure = tags['PT001'] # Dictionary style

    # Calculate derived value
    efficiency = (temp - 70) / (pressure * 0.1)

    # Publish result (appears as py.Efficiency)
    publish('Efficiency', efficiency, units='%')

    # Control output based on condition
    if temp > 180:
        outputs.set('ALARM_LIGHT', True)
    else:
        outputs.set('ALARM_LIGHT', False)

    # Wait for next scan cycle
    next_scan()
```

#### Python API Reference

| Function | Description |
|----------|-------------|
| `tags.TC001` or `tags['TC001']` | Read channel value |
| `tags.timestamp('TC001')` | Get last update timestamp |
| `outputs.set(tag, value)` | Set digital/analog output |
| `publish(name, value, units)` | Create py.* computed tag |
| `session.active` | Check if session running |
| `session.elapsed` | Get elapsed time (seconds) |
| `session.start_recording(filename)` | Begin data capture |
| `session.stop_recording()` | End data capture |
| `next_scan()` | Wait for next scan cycle |
| `persist(key, value)` | Save value across restarts |
| `restore(key, default)` | Restore persisted value |

> **Note:** For comprehensive scripting documentation, see `docs/ICCSFlux_Python_Scripting_Guide.md`

### 7.5 User Variables

Create persistent values for calculations and tracking.

| Variable Type | Description |
|---------------|-------------|
| **Constant** | Fixed value |
| **Manual** | User-entered value |
| **Accumulator** | Running sum |
| **Counter** | Event counter |
| **Timer** | Elapsed time tracker |
| **Rolling Average** | Window-based average |
| **Min/Max Tracker** | Track extremes |

### 7.6 Triggers

Automate actions based on events or conditions.

| Trigger Type | Description |
|--------------|-------------|
| **Value Threshold** | Channel crosses value |
| **Time Elapsed** | After duration |
| **Schedule** | At specific time |
| **State Change** | Acquisition/recording starts/stops |
| **Sequence Event** | Sequence completes/errors |

| Action | Description |
|--------|-------------|
| Start Sequence | Run automation |
| Set Output | Control output |
| Start Recording | Begin capture |
| Send Notification | Alert user |
| Run Formula | Execute calculation |

### 7.7 Draw Patterns (Valve Dosing)

Configure sequential valve operations for flow testing:

1. **Define valves**: List of digital outputs
2. **Set target volume**: Gallons per draw
3. **Configure timing**: Delay between draws
4. **Set flow meter**: Channel for volume measurement
5. **Run pattern**: Execute automatically or via sequence

---

## 8. Safety System Tab

### Safety Architecture

ICCSFlux uses a **defense-in-depth** safety architecture where safety-critical logic is evaluated at multiple levels:

```
┌─────────────────────────────────────────────────────────────────┐
│ Level 1: Edge Nodes (cRIO/Opto22) - FIRST LINE OF DEFENSE      │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ • Hardware watchdog (cRIO)                                  │ │
│ │ • Local interlock checks before every output write          │ │
│ │ • Safe state activation on PC disconnect                    │ │
│ │ • Operates independently - no PC required                   │ │
│ └─────────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────────┤
│ Level 2: Backend (daq_service) - SUPERVISORY SAFETY            │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ • ISA-18.2 alarm management                                 │ │
│ │ • Interlock coordination across nodes                       │ │
│ │ • Audit trail and alarm history                             │ │
│ │ • Backend-authoritative latch state                         │ │
│ └─────────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────────┤
│ Level 3: Dashboard (Browser) - DISPLAY & COMMANDS ONLY         │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ • Displays safety status from backend                       │ │
│ │ • Sends commands to backend (backend validates)             │ │
│ │ • Never makes safety decisions                              │ │
│ └─────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

> **Key Principle**: The browser dashboard is for visualization and commands only. All safety decisions are made by the backend and edge nodes. If you close the browser, safety continues to operate.

### 8.1 Alarm Configuration

Configure monitoring thresholds for each channel.

#### Alarm Levels (ISA-18.2)

| Level | Priority | Response |
|-------|----------|----------|
| **HiHi** | Critical | Immediate action required |
| **Hi** | High | Attention needed |
| **Lo** | High | Attention needed |
| **LoLo** | Critical | Immediate action required |

#### Alarm Settings

| Setting | Description |
|---------|-------------|
| Enabled | Activate alarm monitoring |
| Setpoint | Threshold value |
| Deadband | Hysteresis to prevent chatter |
| On-Delay | Time above threshold before alarm |
| Off-Delay | Time below threshold before clear |
| Severity | Critical, High, Medium, Low |
| Behavior | Auto-clear, Latched, Timed-latch |
| Actions | Safety actions on trigger |

### 8.2 Active Alarms

View and manage current alarm states.

| Column | Description |
|--------|-------------|
| TAG | Channel identifier |
| State | Active, Acknowledged, Returned |
| Severity | Alarm priority level |
| Value | Current reading |
| Threshold | Alarm setpoint |
| Duration | Time since trigger |
| First Out | First alarm indicator |

#### Alarm Actions

| Action | Description |
|--------|-------------|
| **Acknowledge** | Confirm operator awareness |
| **Shelve** | Temporarily suppress (with reason) |
| **Reset** | Clear latched alarm |

### 8.3 Interlocks

Define conditions that must be met before allowing operations.

#### Condition Types

| Type | Description |
|------|-------------|
| Channel Value | Numeric comparison |
| Digital State | Input ON/OFF |
| No Alarms | No active alarms of severity |
| System Connected | MQTT broker online |
| DAQ Active | Acquisition running |

#### Interlock Controls

| Gate | Description |
|------|-------------|
| Block Outputs | Prevent output changes |
| Block Scheduler | Disable automation |
| Block Recording | Prevent recording |
| Block Buttons | Disable UI controls |

#### Bypass

Interlocks can be bypassed with proper authorization:
1. Click **Bypass** on interlock
2. Enter reason for bypass
3. Set timeout duration
4. Bypass logged to audit trail
5. Auto-reverts after timeout

### 8.4 Alarm History

Review past alarm events with full audit trail:

- Trigger time and clear time
- User who acknowledged
- Duration of alarm condition
- Associated safety actions executed

---

## 9. Data Recording Tab

### 9.1 Recording Modes

| Mode | Description |
|------|-------------|
| **Manual** | Start/stop with button |
| **Triggered** | Auto-start on condition |
| **Scheduled** | Time-based recording |

### 9.2 Recording Configuration

| Setting | Description |
|---------|-------------|
| File Format | CSV or TDMS |
| File Prefix | Filename prefix |
| Channels | All or selected subset |
| Decimation | Reduce sample rate |
| Split Size | Max file size before split |
| Split Duration | Max duration before split |

### 9.3 Trigger Recording

Configure automatic recording on events:

| Setting | Description |
|---------|-------------|
| Trigger Channel | Value to monitor |
| Condition | Above, Below, Change |
| Threshold | Trigger value |
| Hysteresis | Prevent false triggers |
| Pre-trigger | Samples before trigger |
| Post-trigger | Samples after condition clears |

### 9.4 Recorded Files

Browse and manage saved recordings:

| Action | Description |
|--------|-------------|
| **Download** | Export file to local drive |
| **View Metadata** | See channels, duration, size |
| **Delete** | Remove file (with confirmation) |
| **Export CSV** | Convert to spreadsheet format |
| **Export Excel** | Generate XLSX file |

---

## 10. Admin Tab

> **Note:** Admin tab requires Administrator role.

### 10.1 User Management

#### Creating a User

1. Click **+ Add User**
2. Enter username (unique)
3. Set initial password
4. Assign role:
   - **Guest**: Read-only access (monitoring only)
   - **Operator**: Run tests, acknowledge alarms, control outputs
   - **Supervisor**: Configure channels, alarms, safety settings, projects
   - **Admin**: Full system access including user management
5. Optional: Set display name
6. Click **Create**

#### User Actions

| Action | Description |
|--------|-------------|
| Edit | Modify user settings |
| Reset Password | Generate new password |
| Disable | Prevent login (preserve audit) |
| Delete | Remove user (if no audit records) |

### 10.2 Audit Trail

Complete record of system events for compliance.

#### Event Types

| Category | Events |
|----------|--------|
| Authentication | Login, logout, failed attempts |
| Configuration | Channel, alarm, interlock changes |
| Recording | Start, stop, file operations |
| Safety | Alarm triggers, acknowledges, bypasses |
| Sequences | Start, stop, step transitions |

#### Audit Filters

| Filter | Description |
|--------|-------------|
| Date Range | Start and end time |
| Event Type | Category of event |
| Username | Specific user |
| Search | Text in event details |

#### Export

Download audit trail as:
- CSV for spreadsheet analysis
- PDF for compliance documentation

### 10.3 Archive Management

Long-term data retention for regulatory compliance.

| Feature | Description |
|---------|-------------|
| Archive Data | Move recordings to archive storage |
| Verify Integrity | Check data checksums |
| Retrieve | Restore archived files |
| Export | Copy to external storage |

---

## 11. Notes Tab

### 11.1 Overview

The Notes tab provides an interactive notebook for:
- Test documentation
- Procedure notes
- Analysis and calculations
- Report generation

### 11.2 Features

| Feature | Description |
|---------|-------------|
| Markdown | Rich text formatting |
| Code Cells | Python execution |
| Data Access | Query channel values |
| Charts | Generate visualizations |
| Export | Save as PDF or HTML |

---

## 12. User Roles & Permissions

### 12.1 Role Hierarchy

```
Admin ────────────────────────────────── Full Access (User Management)
   │
Supervisor ───────────────────────────── Configure Channels, Alarms, Safety
   │
Operator ─────────────────────────────── Run Tests & Acknowledge Alarms
   │
Guest ────────────────────────────────── Read Only (Monitoring)
```

### 12.2 Permission Matrix

| Capability | Guest | Operator | Supervisor | Admin |
|------------|-------|----------|------------|-------|
| View dashboards | ✓ | ✓ | ✓ | ✓ |
| View all tabs | ✓ | ✓ | ✓ | ✓ |
| Start/Stop acquisition | - | ✓ | ✓ | ✓ |
| Start/Stop recording | - | ✓ | ✓ | ✓ |
| Control outputs | - | ✓ | ✓ | ✓ |
| Run sequences | - | ✓ | ✓ | ✓ |
| Acknowledge alarms | - | ✓ | ✓ | ✓ |
| Edit dashboard layout | - | ✓ | ✓ | ✓ |
| Edit channels | - | ✓ | ✓ | ✓ |
| Edit sequences | - | - | ✓ | ✓ |
| Edit safety config | - | - | ✓ | ✓ |
| Bypass interlocks | - | - | ✓ | ✓ |
| Manage users | - | - | - | ✓ |
| View audit trail | - | - | ✓ | ✓ |
| System configuration | - | - | - | ✓ |

### 12.3 View-Only Mode

When viewing a tab without edit permission:
- A banner displays "View Only - [Role] access required to edit"
- Data is visible and updates in real-time
- Edit controls are disabled or hidden
- Click "Login" to authenticate with higher privileges

---

## 13. Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl + S` | Save project |
| `Ctrl + E` | Toggle edit mode |
| `Ctrl + N` | New widget (edit mode) |
| `Escape` | Close dialog/modal |
| `F5` | Refresh dashboard |
| `F11` | Toggle fullscreen |

---

## 14. Troubleshooting

### 14.1 Connection Issues

**Problem:** Dashboard shows "Disconnected"

**Solutions:**
1. Check that backend service is running
2. Verify MQTT broker is accessible
3. Check firewall settings for ports 1883/9002
4. Restart the ICCSFlux service

### 14.2 No Data Updating

**Problem:** Values show "--" or don't update

**Solutions:**
1. Click START to begin acquisition
2. Check channel configuration
3. Verify hardware connections
4. Check for stale data warnings
5. Review error logs in Admin tab

### 14.3 Recording Not Starting

**Problem:** RECORD button doesn't work

**Solutions:**
1. Ensure acquisition is running first
2. Check available disk space
3. Verify recording permissions
4. Check interlock status (may be blocked)

### 14.4 Alarm Not Triggering

**Problem:** Value exceeds threshold but no alarm

**Solutions:**
1. Verify alarm is enabled
2. Check on-delay setting
3. Confirm threshold value is correct
4. Review deadband settings
5. Check if alarm is shelved

### 14.5 Sequence Not Running

**Problem:** Sequence stays in Idle state

**Solutions:**
1. Enable SESSION toggle
2. Check interlock requirements
3. Verify sequence has valid steps
4. Review error messages in sequence log

### 14.6 Python Script Errors

**Problem:** Script shows error or doesn't run

**Solutions:**
1. Check Pyodide load status (may take time)
2. Review syntax errors in output
3. Verify channel names are correct
4. Check for infinite loops without sleep()

---

## 15. Glossary

| Term | Definition |
|------|------------|
| **Acquisition** | Active data collection from hardware |
| **Alarm** | Condition-triggered notification |
| **Audit Trail** | Chronological record of system events |
| **Bypass** | Temporary override of safety interlock |
| **Channel** | Single measurement point or control output |
| **CJC** | Cold Junction Compensation (thermocouples) |
| **Deadband** | Hysteresis zone to prevent alarm chatter |
| **First Out** | First alarm in a cascade sequence |
| **Interlock** | Safety condition preventing operation |
| **ISA-18.2** | Alarm management standard |
| **Latched Alarm** | Alarm requiring manual reset |
| **MQTT** | Message protocol for real-time data |
| **Node** | Single DAQ service instance |
| **On-Delay** | Time condition must persist before alarm |
| **Publish Rate** | Frequency of dashboard updates |
| **RTD** | Resistance Temperature Detector |
| **Scan Rate** | Hardware sampling frequency |
| **Sequence** | Automated test procedure |
| **Session** | Active test period with automation |
| **Setpoint** | Target value for control output |
| **Shelve** | Temporarily suppress an alarm |
| **Tag** | Unique channel identifier |
| **TDMS** | NI Technical Data Management format |
| **Trigger** | Condition-based automation start |
| **21 CFR Part 11** | FDA regulation for electronic records |
| **Watchdog** | System health monitor |

---

## Support

For technical support:
- Contact your system administrator
- Full documentation: `docs/` folder
- Remote nodes guide: `docs/ICCSFlux_Remote_Nodes_Guide.md`
- Python scripting: `docs/ICCSFlux_Python_Scripting_Guide.md`

---

**ICCSFlux User Manual v1.0**
*Last Updated: January 2026*
