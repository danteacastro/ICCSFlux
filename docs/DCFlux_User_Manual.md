# DCFlux User Manual

**Version 1.0**
**Industrial Data Acquisition & Control System**

---

## Table of Contents

1. [Introduction](#1-introduction)
2. [Getting Started](#2-getting-started)
3. [Dashboard Overview](#3-dashboard-overview)
4. [Widgets Reference](#4-widgets-reference)
5. [Configuration Tab](#5-configuration-tab)
6. [Scripts & Automation Tab](#6-scripts--automation-tab)
7. [Safety System Tab](#7-safety-system-tab)
8. [Data Recording Tab](#8-data-recording-tab)
9. [Admin Tab](#9-admin-tab)
10. [Notes Tab](#10-notes-tab)
11. [User Roles & Permissions](#11-user-roles--permissions)
12. [Keyboard Shortcuts](#12-keyboard-shortcuts)
13. [Troubleshooting](#13-troubleshooting)
14. [Glossary](#14-glossary)

---

## 1. Introduction

### 1.1 What is DCFlux?

DCFlux is an industrial-grade data acquisition and control system designed for laboratory testing, manufacturing, and process monitoring. It provides:

- **Real-time data visualization** with customizable dashboards
- **Multi-channel data acquisition** supporting thermocouples, RTDs, voltage/current inputs, digital I/O, and more
- **Automated test sequences** with conditional logic and loops
- **Safety interlocks** compliant with ISA-18.2 alarm management standards
- **Data recording** with 21 CFR Part 11 compliance for regulated industries
- **Python scripting** for advanced calculations and custom logic

### 1.2 System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    DCFlux Dashboard                          │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐            │
│  │   Widgets   │ │   Charts    │ │  Controls   │            │
│  └─────────────┘ └─────────────┘ └─────────────┘            │
│                         │                                    │
│                    WebSocket/MQTT                            │
└─────────────────────────────────────────────────────────────┘
                          │
┌─────────────────────────────────────────────────────────────┐
│                  DCFlux Backend Service                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │
│  │   DAQ    │ │  Alarms  │ │ Sequences│ │ Recording│       │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘       │
│                         │                                    │
│                    Hardware I/O                              │
└─────────────────────────────────────────────────────────────┘
                          │
              ┌───────────┴───────────┐
              │    NI-DAQmx / Modbus  │
              │    Sensors & Outputs  │
              └───────────────────────┘
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
| Python Scripting | Full Python 3.11+ in browser via Pyodide |
| Compliance | 21 CFR Part 11 audit trail support |

---

## 2. Getting Started

### 2.1 Launching DCFlux

1. **Start the backend service:**
   ```
   Double-click: start.bat
   ```

2. **Open the dashboard:**
   - The browser opens automatically to `http://localhost:5173`
   - Or navigate manually to the URL

3. **Login (if required):**
   - Default admin credentials: `admin` / `iccsadmin`
   - Contact your administrator for user credentials

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
│ [Logo] DCFlux │ Overview │ Config │ Scripts │ Data │ Safety │ ... │
├────────────────────────────────────────────────────────────────────┤
│              [START] [RECORD] [SESSION] │ [+Widget] [Edit] │ User │
└────────────────────────────────────────────────────────────────────┘
```

#### Navigation Tabs

| Tab | Purpose | Access Level |
|-----|---------|--------------|
| **Overview** | Main dashboard with widgets | All users |
| **Config** | Channel and system configuration | Operator+ to edit |
| **Scripts** | Automation, sequences, formulas | Engineer+ to edit |
| **Data** | Recording management and export | Operator+ to edit |
| **Safety** | Alarms and interlocks | Engineer+ to edit |
| **Notes** | Documentation and notes | All users |
| **Admin** | User management and audit trail | Admin only |

#### Control Buttons

| Button | Function | Shortcut |
|--------|----------|----------|
| **START/STOP** | Begin/end data acquisition | - |
| **RECORD** | Start/stop data recording | - |
| **SESSION** | Enable/disable automation engine | - |
| **+ Widget** | Add new widget (edit mode) | - |
| **Edit** | Toggle dashboard edit mode | - |

### 3.2 Page Selector

DCFlux supports multiple dashboard pages for organizing different views:

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

## 6. Scripts & Automation Tab

### 6.1 Sub-Tab Navigation

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

### 6.2 Formulas (Calculated Parameters)

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

### 6.3 Sequences (Test Recipes)

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

### 6.4 Python Scripts

Write custom logic using full Python 3.11+ syntax.

#### Script Template

```python
# DCFlux Python Script
# Runs while session is active

while session.active:
    # Read channel values
    temp = channels['TC001']
    pressure = channels['PT001']

    # Calculate derived value
    efficiency = (temp - 70) / (pressure * 0.1)

    # Publish result
    publish('Efficiency', efficiency, units='%')

    # Control output based on condition
    if temp > 180:
        set_output('ALARM_LIGHT', True)
    else:
        set_output('ALARM_LIGHT', False)

    # Wait for next scan
    sleep(1.0)
```

#### Python API Reference

| Function | Description |
|----------|-------------|
| `channels['TAG']` | Read channel value |
| `timestamps['TAG']` | Get last update time |
| `set_output(tag, value)` | Set digital/analog output |
| `publish(name, value, units)` | Create py.* output |
| `session.active` | Check if session running |
| `session.elapsed` | Get elapsed time (seconds) |
| `start_recording(filename)` | Begin data capture |
| `stop_recording()` | End data capture |
| `sleep(seconds)` | Wait between iterations |

### 6.5 User Variables

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

### 6.6 Triggers

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

### 6.7 Draw Patterns (Valve Dosing)

Configure sequential valve operations for flow testing:

1. **Define valves**: List of digital outputs
2. **Set target volume**: Gallons per draw
3. **Configure timing**: Delay between draws
4. **Set flow meter**: Channel for volume measurement
5. **Run pattern**: Execute automatically or via sequence

---

## 7. Safety System Tab

### 7.1 Alarm Configuration

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

### 7.2 Active Alarms

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

### 7.3 Interlocks

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

### 7.4 Alarm History

Review past alarm events with full audit trail:

- Trigger time and clear time
- User who acknowledged
- Duration of alarm condition
- Associated safety actions executed

---

## 8. Data Recording Tab

### 8.1 Recording Modes

| Mode | Description |
|------|-------------|
| **Manual** | Start/stop with button |
| **Triggered** | Auto-start on condition |
| **Scheduled** | Time-based recording |

### 8.2 Recording Configuration

| Setting | Description |
|---------|-------------|
| File Format | CSV or TDMS |
| File Prefix | Filename prefix |
| Channels | All or selected subset |
| Decimation | Reduce sample rate |
| Split Size | Max file size before split |
| Split Duration | Max duration before split |

### 8.3 Trigger Recording

Configure automatic recording on events:

| Setting | Description |
|---------|-------------|
| Trigger Channel | Value to monitor |
| Condition | Above, Below, Change |
| Threshold | Trigger value |
| Hysteresis | Prevent false triggers |
| Pre-trigger | Samples before trigger |
| Post-trigger | Samples after condition clears |

### 8.4 Recorded Files

Browse and manage saved recordings:

| Action | Description |
|--------|-------------|
| **Download** | Export file to local drive |
| **View Metadata** | See channels, duration, size |
| **Delete** | Remove file (with confirmation) |
| **Export CSV** | Convert to spreadsheet format |
| **Export Excel** | Generate XLSX file |

---

## 9. Admin Tab

> **Note:** Admin tab requires Administrator role.

### 9.1 User Management

#### Creating a User

1. Click **+ Add User**
2. Enter username (unique)
3. Set initial password
4. Assign role:
   - **Viewer**: Read-only access
   - **Operator**: Run tests, acknowledge alarms
   - **Engineer**: Configure channels, alarms, safety settings, projects
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

### 9.2 Audit Trail

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

### 9.3 Archive Management

Long-term data retention for regulatory compliance.

| Feature | Description |
|---------|-------------|
| Archive Data | Move recordings to archive storage |
| Verify Integrity | Check data checksums |
| Retrieve | Restore archived files |
| Export | Copy to external storage |

---

## 10. Notes Tab

### 10.1 Overview

The Notes tab provides an interactive notebook for:
- Test documentation
- Procedure notes
- Analysis and calculations
- Report generation

### 10.2 Features

| Feature | Description |
|---------|-------------|
| Markdown | Rich text formatting |
| Code Cells | Python execution |
| Data Access | Query channel values |
| Charts | Generate visualizations |
| Export | Save as PDF or HTML |

---

## 11. User Roles & Permissions

### 11.1 Role Hierarchy

```
Admin ────────────────────────────────── Full Access (User Management)
   │
Engineer ─────────────────────────────── Configure Channels, Alarms, Safety
   │
Operator ─────────────────────────────── Run Tests & Acknowledge Alarms
   │
Viewer ───────────────────────────────── Read Only (Monitoring)
```

### 11.2 Permission Matrix

| Capability | Viewer | Operator | Engineer | Admin |
|------------|--------|----------|------------|-------|
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
| View audit trail | - | - | - | ✓ |
| System configuration | - | - | - | ✓ |

### 11.3 View-Only Mode

When viewing a tab without edit permission:
- A banner displays "View Only - [Role] access required to edit"
- Data is visible and updates in real-time
- Edit controls are disabled or hidden
- Click "Login" to authenticate with higher privileges

---

## 12. Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl + S` | Save project |
| `Ctrl + E` | Toggle edit mode |
| `Ctrl + N` | New widget (edit mode) |
| `Escape` | Close dialog/modal |
| `F5` | Refresh dashboard |
| `F11` | Toggle fullscreen |

---

## 13. Troubleshooting

### 13.1 Connection Issues

**Problem:** Dashboard shows "Disconnected"

**Solutions:**
1. Check that backend service is running
2. Verify MQTT broker is accessible
3. Check firewall settings for ports 1883/9002
4. Restart the DCFlux service

### 13.2 No Data Updating

**Problem:** Values show "--" or don't update

**Solutions:**
1. Click START to begin acquisition
2. Check channel configuration
3. Verify hardware connections
4. Check for stale data warnings
5. Review error logs in Admin tab

### 13.3 Recording Not Starting

**Problem:** RECORD button doesn't work

**Solutions:**
1. Ensure acquisition is running first
2. Check available disk space
3. Verify recording permissions
4. Check interlock status (may be blocked)

### 13.4 Alarm Not Triggering

**Problem:** Value exceeds threshold but no alarm

**Solutions:**
1. Verify alarm is enabled
2. Check on-delay setting
3. Confirm threshold value is correct
4. Review deadband settings
5. Check if alarm is shelved

### 13.5 Sequence Not Running

**Problem:** Sequence stays in Idle state

**Solutions:**
1. Enable SESSION toggle
2. Check interlock requirements
3. Verify sequence has valid steps
4. Review error messages in sequence log

### 13.6 Python Script Errors

**Problem:** Script shows error or doesn't run

**Solutions:**
1. Check Pyodide load status (may take time)
2. Review syntax errors in output
3. Verify channel names are correct
4. Check for infinite loops without sleep()

---

## 14. Glossary

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
- Email: support@example.com
- Documentation: https://docs.example.com
- Issue Tracker: https://github.com/example/dcflux/issues

---

**DCFlux User Manual v1.0**
*Last Updated: January 2026*
