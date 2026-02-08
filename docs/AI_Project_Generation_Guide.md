# ICCSFlux Project JSON Generation Guide

**Purpose**: This guide provides all information needed for an AI to generate valid ICCSFlux project JSON files for industrial data acquisition and control systems.

---

## Overview

ICCSFlux is a data acquisition (DAQ) and control system that:
- Reads sensor data from NI cDAQ hardware, cRIO controllers, and Opto22 devices
- Controls digital and analog outputs
- Provides real-time visualization via a web dashboard
- Records data to CSV files
- Implements safety interlocks and alarms
- Runs Python automation scripts

A project JSON file defines the complete system configuration including channels, safety rules, and dashboard layout.

---

## File Structure

```json
{
  "type": "nisystem-project",
  "version": "2.0",
  "name": "Project Name",
  "description": "Detailed project description",
  "created": "2026-01-20T00:00:00.000Z",
  "modified": "2026-01-20T00:00:00.000Z",
  "system": { },
  "service": { },
  "channels": { },
  "safety": { },
  "scripts": { },
  "layout": { }
}
```

---

## Section 1: Metadata

### Required Top-Level Fields

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `type` | string | **Always** `"nisystem-project"` | `"nisystem-project"` |
| `version` | string | Schema version, **always** `"2.0"` | `"2.0"` |
| `name` | string | Human-readable project name | `"Boiler Test System"` |
| `description` | string | Detailed description | `"500kW industrial boiler combustion research platform"` |
| `created` | string | ISO 8601 creation timestamp | `"2026-01-20T00:00:00.000Z"` |
| `modified` | string | ISO 8601 last modified timestamp | `"2026-01-20T00:00:00.000Z"` |

---

## Section 2: System Configuration

The `system` object configures the DAQ backend service.

```json
"system": {
  "mqtt_broker": "localhost",
  "mqtt_port": 1883,
  "mqtt_base_topic": "nisystem",
  "scan_rate_hz": 10,
  "publish_rate_hz": 4,
  "simulation_mode": true,
  "log_directory": "./logs",
  "system_name": "My Test Facility",
  "system_id": "FACILITY-001",
  "datalog_rate_ms": 1000,
  "datalog_rearm": true,
  "datalog_rearm_rate_sec": 3600
}
```

### System Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `mqtt_broker` | string | No | `"localhost"` | MQTT broker hostname or IP |
| `mqtt_port` | number | No | `1883` | MQTT broker port |
| `mqtt_base_topic` | string | No | `"nisystem"` | Base topic prefix for all MQTT messages |
| `scan_rate_hz` | number | No | `50` | Hardware scan rate in Hz (1-1000) |
| `publish_rate_hz` | number | No | `4` | Rate to publish data to MQTT (1-4 Hz max) |
| `simulation_mode` | boolean | No | `false` | If true, generates simulated data instead of reading hardware |
| `log_directory` | string | No | `"./logs"` | Directory for log files |
| `system_name` | string | **Yes** | - | Human-readable name shown in UI |
| `system_id` | string | **Yes** | - | Unique identifier (use uppercase, alphanumeric, dashes) |
| `datalog_rate_ms` | number | No | `1000` | Data recording interval in milliseconds |
| `datalog_rearm` | boolean | No | `true` | Automatically restart recording after file rotation |
| `datalog_rearm_rate_sec` | number | No | `3600` | Time between auto-rearm in seconds |

### Recommended Scan Rates by Application

| Application | Scan Rate | Publish Rate |
|-------------|-----------|--------------|
| Slow thermal processes | 1-10 Hz | 1-2 Hz |
| General industrial | 10-50 Hz | 2-4 Hz |
| Fast control loops | 50-100 Hz | 4 Hz |

**Note:** The maximum publish rate is 4 Hz. Higher internal scan rates are allowed for PID loops and script calculations, but MQTT publishing is capped at 4 Hz.

---

## Section 3: Service Configuration

The `service` object configures timeouts and health monitoring.

```json
"service": {
  "heartbeat_interval_sec": 2,
  "health_timeout_sec": 10,
  "shutdown_timeout_sec": 10,
  "command_ack_timeout_sec": 5
}
```

### Service Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `heartbeat_interval_sec` | number | `2` | Interval between heartbeat messages |
| `health_timeout_sec` | number | `10` | Time before declaring service unhealthy |
| `shutdown_timeout_sec` | number | `10` | Max time to wait during shutdown |
| `command_ack_timeout_sec` | number | `5` | Timeout waiting for command acknowledgment |

---

## Section 4: Channel Configuration

The `channels` object is a dictionary where **keys are TAG names** (unique identifiers) and values are channel configuration objects.

```json
"channels": {
  "TC001": { ... },
  "PT_Supply": { ... },
  "Valve_Main": { ... }
}
```

### Channel Naming Rules

1. **Use alphanumeric characters and underscores only**: `A-Z`, `a-z`, `0-9`, `_`
2. **Start with a letter**: `TC001` (valid), `001TC` (invalid)
3. **No spaces or special characters**: `TC_001` (valid), `TC-001` (invalid in TAG, ok in display_name)
4. **Keep concise but descriptive**:
   - Temperatures: `TC001`, `RTD_Inlet`, `T_Ambient`
   - Pressures: `PT001`, `PT_Supply`, `P_Tank`
   - Flows: `FT001`, `FT_Water`, `Flow_Main`
   - Digital: `Valve_1`, `Pump_Start`, `Alarm_Horn`

### Channel Types Overview

**Valid channel types** (ONLY these are allowed in `channel_type` field):

| Type | Description | Typical Use |
|------|-------------|-------------|
| `thermocouple` | Temperature sensor (TC) | Process temperatures |
| `rtd` | Resistance temperature detector | Precision temperature |
| `voltage_input` | 0-10V analog input | Pressure, level, position sensors |
| `current_input` | 4-20mA analog input | Industrial transmitters |
| `voltage_output` | 0-10V analog output | Setpoints, valve positions |
| `current_output` | 4-20mA analog output | Control signals |
| `digital_input` | On/Off input | Switches, status signals |
| `digital_output` | On/Off output | Valves, relays, indicators |
| `counter` | Counter/pulse input | Flow totalizers, encoder counts |
| `strain_input` | Strain gauge input | Load cells, force sensors |
| `iepe_input` | IEPE accelerometer | Vibration sensors |
| `resistance_input` | Resistance measurement | Resistance sensors |

**IMPORTANT:** Do NOT use `script`, `calculated`, `virtual`, or any other type not listed above. These are NOT valid channel types and will cause the project to fail to load.

### Calculated/Derived Values

Calculated values (PUE, COP, delta-T, etc.) should NOT be defined as channels. Instead:
1. Use Python scripts in the `pythonScripts` section
2. Use the `publish()` function to output calculated values
3. Published script values appear on MQTT but are not displayed in dashboard widgets

Example script for calculated value:
```python
# In pythonScripts section
{
  "id": "calc-pue",
  "name": "Power Usage Effectiveness",
  "enabled": true,
  "runOnStartup": true,
  "code": "it_power = tags['WT_IT_Load']\ncooling = tags['WT_Cooling']\npue = (it_power + cooling) / it_power if it_power > 100 else 1.0\npublish('CALC-PUE', pue, units='')"
}
```

---

### Channel Type: Thermocouple

For temperature measurement using thermocouple sensors.

```json
"TC_Flue_1": {
  "physical_channel": "cDAQ9189-1A2B3C4Mod1/ai0",
  "channel_type": "thermocouple",
  "thermocouple_type": "K",
  "units": "degF",
  "display_name": "Flue Gas Temperature 1",
  "description": "Primary flue gas temperature at stack exit",
  "alarm_enabled": true,
  "lo_limit": 200,
  "lolo_limit": 150,
  "hi_limit": 450,
  "hihi_limit": 500,
  "alarm_priority": "high",
  "alarm_deadband": 5,
  "safety_action": "high-temp-shutdown",
  "log": true,
  "log_interval_ms": 1000,
  "precision": 1,
  "group": "Flue Gas",
  "visible": true,
  "chartable": true
}
```

#### Thermocouple-Specific Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `thermocouple_type` | string | **Yes** | TC type: `"J"`, `"K"`, `"T"`, `"E"`, `"N"`, `"R"`, `"S"`, `"B"` |
| `cjc_source` | string | No | Cold junction compensation: `"internal"`, `"constant"`, `"channel"` |
| `cjc_value` | number | No | CJC temperature if `cjc_source` is `"constant"` |

#### Thermocouple Type Selection Guide

| Type | Range | Best For |
|------|-------|----------|
| `"J"` | -40 to 750°C | General purpose, reducing atmospheres |
| `"K"` | -200 to 1350°C | **Most common**, general purpose |
| `"T"` | -200 to 350°C | Low temp, food, cryogenics |
| `"E"` | -200 to 900°C | High sensitivity |
| `"N"` | -200 to 1300°C | High temp, stable |
| `"R"` | 0 to 1450°C | Very high temp, platinum |
| `"S"` | 0 to 1450°C | Very high temp, platinum |
| `"B"` | 0 to 1820°C | Extreme high temp |

---

### Channel Type: RTD

For precision temperature measurement using RTD sensors.

```json
"RTD_Water_Supply": {
  "physical_channel": "cDAQ9189-1A2B3C4Mod2/ai0",
  "channel_type": "rtd",
  "rtd_type": "Pt3851",
  "resistance_config": "3Wire",
  "excitation_current": 0.001,
  "r0": 100,
  "units": "degF",
  "display_name": "Water Supply Temperature",
  "description": "Feedwater supply temperature to boiler",
  "alarm_enabled": false,
  "log": true,
  "precision": 2,
  "group": "Water Loop"
}
```

#### RTD-Specific Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `rtd_type` | string | **Yes** | - | RTD type (see table below) |
| `resistance_config` | string | **Yes** | - | Wiring: `"2Wire"`, `"3Wire"`, `"4Wire"` |
| `excitation_current` | number | No | `0.001` | Excitation current in Amps |
| `r0` | number | No | `100` | Resistance at 0°C in Ohms |

#### RTD Type Selection

| Type | Description |
|------|-------------|
| `"Pt3851"` | Platinum, alpha=0.00385 (IEC 60751, most common) |
| `"Pt3750"` | Platinum, alpha=0.00375 (US industrial) |
| `"Pt3916"` | Platinum, alpha=0.003916 (US industrial) |
| `"Pt3920"` | Platinum, alpha=0.00392 (US industrial) |

#### Wiring Configuration

| Config | Description | Accuracy |
|--------|-------------|----------|
| `"2Wire"` | Simple, lead resistance affects reading | Low |
| `"3Wire"` | Compensates for lead resistance | Medium |
| `"4Wire"` | Full compensation, highest accuracy | High |

---

### Channel Type: Voltage Input

For analog sensors with 0-10V or similar voltage output.

```json
"PT_Supply": {
  "physical_channel": "cDAQ9189-1A2B3C4Mod3/ai0",
  "channel_type": "voltage_input",
  "voltage_range": 10,
  "terminal_config": "Diff",
  "units": "psig",
  "scale_min": 0,
  "scale_max": 100,
  "display_name": "Supply Pressure",
  "description": "Main supply header pressure",
  "alarm_enabled": true,
  "lo_limit": 20,
  "lolo_limit": 10,
  "hi_limit": 80,
  "hihi_limit": 90,
  "alarm_priority": "high",
  "alarm_deadband": 2,
  "log": true,
  "precision": 1,
  "group": "Pressures"
}
```

#### Voltage Input Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `voltage_range` | number | **Yes** | - | Max voltage: `1`, `5`, `10` |
| `terminal_config` | string | No | `"Diff"` | `"Diff"`, `"RSE"`, `"NRSE"` |
| `scale_min` | number | **Yes** | - | Engineering units at 0V |
| `scale_max` | number | **Yes** | - | Engineering units at max voltage |

#### Terminal Configuration

| Config | Description | Use When |
|--------|-------------|----------|
| `"Diff"` | Differential (2 wires per channel) | Best noise rejection, default choice |
| `"RSE"` | Referenced Single-Ended | More channels, shared ground |
| `"NRSE"` | Non-Referenced Single-Ended | Floating signal sources |

---

### Channel Type: Current Input

For 4-20mA industrial transmitters.

```json
"FT_Water": {
  "physical_channel": "cDAQ9189-1A2B3C4Mod3/ai4",
  "channel_type": "current_input",
  "current_range_ma": 20,
  "four_twenty_scaling": true,
  "terminal_config": "Diff",
  "units": "GPM",
  "eng_units_min": 0,
  "eng_units_max": 100,
  "display_name": "Water Flow Rate",
  "description": "Circulating water flow through heat exchanger",
  "alarm_enabled": true,
  "lo_limit": 10,
  "lolo_limit": 5,
  "alarm_priority": "high",
  "alarm_deadband": 1,
  "safety_action": "low-flow-shutdown",
  "log": true,
  "precision": 1,
  "group": "Flow"
}
```

#### Current Input Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `current_range_ma` | number | No | `20` | Max current in mA (typically 20) |
| `four_twenty_scaling` | boolean | No | `true` | If true, 4mA=min, 20mA=max |
| `eng_units_min` | number | **Yes** | - | Engineering units at 4mA (or 0mA) |
| `eng_units_max` | number | **Yes** | - | Engineering units at 20mA |

---

### Channel Type: Voltage Output

For analog control outputs (0-10V setpoints).

```json
"Firing_Rate_SP": {
  "physical_channel": "cDAQ9189-1A2B3C4Mod5/ao0",
  "channel_type": "voltage_output",
  "voltage_range": 10,
  "units": "%",
  "scale_min": 0,
  "scale_max": 100,
  "display_name": "Firing Rate Setpoint",
  "description": "Burner firing rate command (0-100%)",
  "log": true,
  "precision": 0,
  "group": "Control"
}
```

#### Voltage Output Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `voltage_range` | number | **Yes** | Output range: `5` or `10` |
| `scale_min` | number | **Yes** | Engineering units at 0V |
| `scale_max` | number | **Yes** | Engineering units at max voltage |

---

### Channel Type: Current Output

For 4-20mA control outputs.

```json
"Valve_Position_SP": {
  "physical_channel": "cDAQ9189-1A2B3C4Mod5/ao2",
  "channel_type": "current_output",
  "current_range_ma": 20,
  "four_twenty_output": true,
  "units": "%",
  "eng_units_min": 0,
  "eng_units_max": 100,
  "display_name": "Valve Position Setpoint",
  "description": "Control valve position command",
  "log": true,
  "precision": 0,
  "group": "Control"
}
```

---

### Channel Type: Digital Input

For discrete on/off signals (switches, status).

```json
"Flame_Detected": {
  "physical_channel": "cDAQ9189-1A2B3C4Mod7/port0/line0",
  "channel_type": "digital_input",
  "display_name": "Flame Detected",
  "description": "UV flame detector - TRUE when flame present",
  "invert": false,
  "log": true,
  "group": "Safety"
}
```

#### Digital Input Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `invert` | boolean | No | `false` | Invert the logic (true becomes false) |

---

### Channel Type: Digital Output

For discrete on/off control (valves, relays).

```json
"Burner_Enable": {
  "physical_channel": "cDAQ9189-1A2B3C4Mod6/port0/line0",
  "channel_type": "digital_output",
  "display_name": "Burner Enable",
  "description": "Master burner enable relay - energized to run",
  "invert": false,
  "initial_value": false,
  "log": true,
  "group": "Control"
}
```

#### Digital Output Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `invert` | boolean | No | `false` | Invert the logic |
| `initial_value` | boolean | No | `false` | Value on system startup |

---

### Common Channel Properties (All Types)

| Property | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `physical_channel` | string | **Yes** | - | NI-DAQmx device path |
| `channel_type` | string | **Yes** | - | One of the types above |
| `units` | string | No | `""` | Engineering units for display |
| `display_name` | string | No | TAG name | Human-readable name |
| `description` | string | No | `""` | Detailed description |
| `group` | string | No | `"Ungrouped"` | Logical group for organization |
| `log` | boolean | No | `true` | Include in data recording |
| `log_interval_ms` | number | No | system default | Recording interval override |
| `precision` | number | No | `2` | Decimal places for display |
| `visible` | boolean | No | `true` | Show in channel lists |
| `chartable` | boolean | No | `true` | Allow in trend charts |

### Alarm Properties (Analog Channels)

| Property | Type | Description |
|----------|------|-------------|
| `alarm_enabled` | boolean | Enable alarming for this channel |
| `lo_limit` | number | Low alarm threshold |
| `lolo_limit` | number | Low-low (critical) alarm threshold |
| `hi_limit` | number | High alarm threshold |
| `hihi_limit` | number | High-high (critical) alarm threshold |
| `alarm_priority` | string | `"low"`, `"medium"`, `"high"`, `"critical"` |
| `alarm_deadband` | number | Deadband to prevent alarm chatter |
| `safety_action` | string | Reference to safety action to trigger |

### Physical Channel Path Format

Format: `{device_name}{module}/ai{n}` or `{device_name}{module}/port{p}/line{l}`

Examples:
- `cDAQ9189-1A2B3C4Mod1/ai0` - Analog input 0 on module 1
- `cDAQ9189-1A2B3C4Mod1/ai7` - Analog input 7 on module 1
- `cDAQ9189-1A2B3C4Mod5/ao0` - Analog output 0 on module 5
- `cDAQ9189-1A2B3C4Mod6/port0/line0` - Digital line 0, port 0, module 6
- `cDAQ9189-1A2B3C4Mod6/port0/line7` - Digital line 7, port 0, module 6

---

## Section 5: Safety Configuration

The `safety` object defines protective interlocks and emergency actions.

```json
"safety": {
  "enabled": true,
  "watchdog_timeout_sec": 5,
  "actions": { },
  "interlocks": [ ]
}
```

### Safety Actions

Actions define what outputs to set when a safety condition is triggered.

```json
"actions": {
  "burner-shutdown": {
    "name": "Burner Emergency Shutdown",
    "description": "Immediate burner shutdown on overtemperature or flame loss",
    "outputs": {
      "Burner_Enable": false,
      "Main_Gas_Valve": false,
      "Pilot_Valve": false,
      "Ignition_Spark": false,
      "Alarm_Horn": true
    },
    "latching": true,
    "priority": 1
  },
  "high-temp-warning": {
    "name": "High Temperature Warning",
    "description": "Audible alarm on elevated temperature",
    "outputs": {
      "Alarm_Horn": true
    },
    "latching": false,
    "priority": 3
  }
}
```

#### Action Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | **Yes** | Human-readable action name |
| `description` | string | No | What this action does |
| `outputs` | object | **Yes** | Map of output channel TAG → value |
| `latching` | boolean | No | If true, requires manual reset |
| `priority` | number | No | 0 = highest, higher numbers = lower priority |

#### Priority Guidelines

| Priority | Use For |
|----------|---------|
| 0 | Emergency stop, fire, explosion risk |
| 1 | Critical safety (flame loss, overpressure) |
| 2 | High priority (overtemperature, low flow) |
| 3 | Warnings and advisories |

---

### Safety Interlocks

Interlocks define conditions that trigger safety actions.

```json
"interlocks": [
  {
    "name": "Flame Loss Protection",
    "description": "Shut down fuel if flame is lost while burner is running",
    "condition": "Flame_Detected == false AND Burner_Enable == true",
    "action": "burner-shutdown",
    "delay_ms": 2000
  },
  {
    "name": "High Limit Trip",
    "description": "Emergency shutdown on temperature limit switch",
    "condition": "High_Limit_OK == false",
    "action": "burner-shutdown",
    "delay_ms": 0
  },
  {
    "name": "Combustion Overtemperature",
    "description": "Shutdown if combustion temperature exceeds limit",
    "condition": "TC_Combustion_1 > 1800",
    "action": "burner-shutdown",
    "delay_ms": 0
  },
  {
    "name": "Low Water Flow",
    "description": "Warning if water flow drops below minimum",
    "condition": "FT_Water < 10",
    "action": "low-flow-warning",
    "delay_ms": 5000
  }
]
```

#### Interlock Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | **Yes** | Human-readable interlock name |
| `description` | string | No | What this interlock protects against |
| `condition` | string | **Yes** | Boolean expression (see syntax below) |
| `action` | string | **Yes** | Reference to action key in `actions` |
| `delay_ms` | number | No | Delay before triggering (0 = immediate) |

#### Condition Syntax

**Comparisons:**
- `channel == value` - Equals
- `channel != value` - Not equals
- `channel > value` - Greater than
- `channel >= value` - Greater than or equal
- `channel < value` - Less than
- `channel <= value` - Less than or equal

**Boolean:**
- `channel == true` - Digital input is ON
- `channel == false` - Digital input is OFF

**Logical Operators:**
- `AND` - Both conditions must be true
- `OR` - Either condition must be true
- `NOT` - Negates the condition
- `( )` - Grouping for precedence

**Examples:**
```
Flame_Detected == false AND Burner_Enable == true
TC001 > 500 OR TC002 > 500
(PT001 < 10 OR PT001 > 100) AND Pump_Running == true
NOT (SafetySwitch == true)
```

---

## Section 6: Scripts Configuration

The `scripts` object defines Python automation scripts.

```json
"scripts": {
  "efficiency_calc": {
    "name": "Efficiency Calculator",
    "description": "Real-time thermal efficiency calculation",
    "enabled": true,
    "auto_start": true,
    "file": "efficiency_calc.py"
  },
  "data_logger": {
    "name": "Custom Data Logger",
    "description": "Logs data to external database",
    "enabled": true,
    "auto_start": false,
    "file": "data_logger.py"
  }
}
```

#### Script Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | **Yes** | Human-readable script name |
| `description` | string | No | What the script does |
| `enabled` | boolean | No | If false, script cannot be run |
| `auto_start` | boolean | No | Start automatically with acquisition |
| `file` | string | **Yes** | Python file name (in scripts directory) |

---

## Section 7: Dashboard Layout

The `layout` object defines the web dashboard configuration.

```json
"layout": {
  "gridColumns": 24,
  "rowHeight": 30,
  "currentPageId": "overview",
  "pages": [ ]
}
```

### Layout Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `gridColumns` | number | `24` | Number of grid columns (keep at 24) |
| `rowHeight` | number | `30` | Height of each grid row in pixels |
| `currentPageId` | string | `"default"` | ID of initially selected page |
| `pages` | array | `[]` | Array of page definitions |

---

### Pages

Each page contains a collection of widgets.

```json
"pages": [
  {
    "id": "overview",
    "name": "Overview",
    "order": 0,
    "widgets": [ ]
  },
  {
    "id": "combustion",
    "name": "Combustion",
    "order": 1,
    "widgets": [ ]
  },
  {
    "id": "safety",
    "name": "Safety",
    "order": 2,
    "widgets": [ ]
  }
]
```

#### Page Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | **Yes** | Unique page identifier (lowercase, no spaces) |
| `name` | string | **Yes** | Display name shown in tab |
| `order` | number | **Yes** | Sort order (0 = first) |
| `widgets` | array | **Yes** | Array of widget definitions |

---

### Widget Common Properties

All widgets share these base properties:

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `id` | string | **Yes** | Unique widget ID (e.g., `"w-temp-gauge-1"`) |
| `type` | string | **Yes** | Widget type (see below) |
| `x` | number | **Yes** | Grid column position (0-23) |
| `y` | number | **Yes** | Grid row position (0+) |
| `w` | number | **Yes** | Width in grid columns |
| `h` | number | **Yes** | Height in grid rows |
| `title` | string | No | Widget title/header |

### Grid System

- **24 columns** across the screen
- Each row is **30 pixels** tall
- Widgets snap to grid
- Position (0,0) is top-left

**Typical Sizes:**
| Widget Type | Minimum Size | Recommended Size |
|-------------|--------------|------------------|
| Title | 4×1 | 8-12×1 |
| Numeric | 2×1 | 3×1 |
| Gauge | 3×2 | 4×3 |
| LED | 2×1 | 2-3×1 |
| Toggle | 2×1 | 2-3×1 |
| Chart | 8×3 | 12×5 |
| Sparkline | 3×2 | 4×2 |

---

### Widget Type: title

Text labels and headers.

```json
{
  "id": "w-header",
  "type": "title",
  "title": "System Overview",
  "subtitle": "Real-time Monitoring Dashboard",
  "x": 0, "y": 0, "w": 12, "h": 1,
  "style": {
    "fontSize": "large",
    "textAlign": "left"
  }
}
```

| Property | Type | Values | Description |
|----------|------|--------|-------------|
| `title` | string | - | Main text |
| `subtitle` | string | - | Secondary text (smaller) |
| `style.fontSize` | string | `"small"`, `"medium"`, `"large"` | Text size |
| `style.textAlign` | string | `"left"`, `"center"`, `"right"` | Alignment |

---

### Widget Type: clock

Date and time display.

```json
{
  "id": "w-clock",
  "type": "clock",
  "x": 20, "y": 0, "w": 4, "h": 1,
  "showDate": true,
  "showSeconds": true,
  "format24h": false
}
```

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `showDate` | boolean | `true` | Display the date |
| `showSeconds` | boolean | `false` | Show seconds |
| `format24h` | boolean | `false` | Use 24-hour format |

---

### Widget Type: numeric

Single channel value display.

```json
{
  "id": "w-temp-display",
  "type": "numeric",
  "channel": "TC001",
  "x": 0, "y": 1, "w": 3, "h": 1,
  "showLabel": true,
  "showUnit": true,
  "precision": 1
}
```

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `channel` | string | **Required** | Channel TAG to display |
| `showLabel` | boolean | `true` | Show channel label |
| `showUnit` | boolean | `true` | Show engineering units |
| `precision` | number | from channel | Decimal places |

---

### Widget Type: gauge

Circular gauge visualization.

```json
{
  "id": "w-pressure-gauge",
  "type": "gauge",
  "channel": "PT001",
  "x": 0, "y": 1, "w": 4, "h": 3,
  "minValue": 0,
  "maxValue": 100,
  "showLimits": true,
  "showValue": true,
  "colorZones": [
    { "min": 0, "max": 20, "color": "#ef4444" },
    { "min": 20, "max": 80, "color": "#22c55e" },
    { "min": 80, "max": 100, "color": "#ef4444" }
  ]
}
```

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `channel` | string | **Required** | Channel TAG |
| `minValue` | number | `0` | Gauge minimum |
| `maxValue` | number | `100` | Gauge maximum |
| `showLimits` | boolean | `true` | Show alarm limits on gauge |
| `showValue` | boolean | `true` | Show numeric value |
| `colorZones` | array | - | Custom color ranges |

---

### Widget Type: bar_graph

Horizontal bar graph.

```json
{
  "id": "w-level-bar",
  "type": "bar_graph",
  "channel": "Level",
  "x": 0, "y": 1, "w": 6, "h": 1,
  "minValue": 0,
  "maxValue": 100,
  "showLimits": true,
  "showValue": true,
  "colorZones": [
    { "max": 20, "color": "#ef4444" },
    { "max": 80, "color": "#22c55e" },
    { "max": 100, "color": "#eab308" }
  ]
}
```

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `channel` | string | **Required** | Channel TAG |
| `minValue` | number | `0` | Bar minimum |
| `maxValue` | number | `100` | Bar maximum |
| `showLimits` | boolean | `true` | Show limit markers |
| `showValue` | boolean | `true` | Show numeric value |
| `colorZones` | array | - | Color by value range |

**Note:** For `colorZones` in bar_graph, only `max` is needed (each zone goes from previous max to this max).

---

### Widget Type: led

LED indicator for digital or threshold-based status.

```json
{
  "id": "w-flame-led",
  "type": "led",
  "channel": "Flame_Detected",
  "x": 0, "y": 1, "w": 2, "h": 1,
  "label": "Flame",
  "onColor": "#22c55e",
  "offColor": "#ef4444",
  "threshold": null,
  "invertThreshold": false
}
```

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `channel` | string | **Required** | Channel TAG |
| `label` | string | channel name | Display label |
| `onColor` | string | `"#22c55e"` | Color when ON (CSS color) |
| `offColor` | string | `"#64748b"` | Color when OFF |
| `threshold` | number | `null` | For analog: ON if value > threshold |
| `invertThreshold` | boolean | `false` | Invert threshold logic |

**Common Colors:**
- Green (OK): `"#22c55e"`
- Red (Alarm): `"#ef4444"`
- Yellow (Warning): `"#eab308"`
- Blue (Active): `"#3b82f6"`
- Gray (Off): `"#64748b"`

---

### Widget Type: toggle

ON/OFF switch for digital outputs.

```json
{
  "id": "w-pump-toggle",
  "type": "toggle",
  "channel": "Pump_Enable",
  "x": 0, "y": 1, "w": 2, "h": 1,
  "onLabel": "PUMP ON",
  "offLabel": "PUMP OFF",
  "confirmOn": true,
  "confirmOff": false,
  "style": {
    "onColor": "#22c55e",
    "offColor": "#64748b"
  }
}
```

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `channel` | string | **Required** | Digital output channel TAG |
| `onLabel` | string | `"ON"` | Label when ON |
| `offLabel` | string | `"OFF"` | Label when OFF |
| `confirmOn` | boolean | `false` | Require confirmation to turn ON |
| `confirmOff` | boolean | `false` | Require confirmation to turn OFF |
| `style.onColor` | string | `"#22c55e"` | Color when ON |
| `style.offColor` | string | `"#64748b"` | Color when OFF |

---

### Widget Type: setpoint

Numeric input for analog outputs.

```json
{
  "id": "w-temp-setpoint",
  "type": "setpoint",
  "channel": "Temp_Setpoint",
  "x": 0, "y": 1, "w": 3, "h": 2,
  "minValue": 0,
  "maxValue": 200,
  "step": 1,
  "showSlider": true
}
```

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `channel` | string | **Required** | Output channel TAG |
| `minValue` | number | `0` | Minimum allowed value |
| `maxValue` | number | `100` | Maximum allowed value |
| `step` | number | `1` | Increment step size |
| `showSlider` | boolean | `true` | Show slider control |

---

### Widget Type: chart

Multi-channel trend chart.

```json
{
  "id": "w-temp-chart",
  "type": "chart",
  "channels": ["TC001", "TC002", "TC003", "TC004"],
  "x": 0, "y": 1, "w": 12, "h": 5,
  "timeRange": 300,
  "showGrid": true,
  "showLegend": true,
  "showDigitalDisplay": true,
  "yAxisAuto": true,
  "yAxisMin": 0,
  "yAxisMax": 500,
  "showScrollbar": false,
  "title": "Temperature Trends"
}
```

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `channels` | array | **Required** | Array of channel TAGs (max 8) |
| `timeRange` | number | `300` | Time window in seconds |
| `showGrid` | boolean | `true` | Show grid lines |
| `showLegend` | boolean | `true` | Show channel legend |
| `showDigitalDisplay` | boolean | `false` | Show numeric values |
| `yAxisAuto` | boolean | `true` | Auto-scale Y axis |
| `yAxisMin` | number | - | Fixed Y axis minimum |
| `yAxisMax` | number | - | Fixed Y axis maximum |
| `showScrollbar` | boolean | `false` | Allow scrolling history |

---

### Widget Type: sparkline

Mini trend line for single channel.

```json
{
  "id": "w-flow-spark",
  "type": "sparkline",
  "channel": "FT_Water",
  "x": 0, "y": 1, "w": 4, "h": 2,
  "historyLength": 60,
  "showValue": true,
  "title": "Flow Trend"
}
```

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `channel` | string | **Required** | Channel TAG |
| `historyLength` | number | `60` | Number of samples to show |
| `showValue` | boolean | `true` | Show current value |

---

### Widget Type: system_status

System overview panel.

```json
{
  "id": "w-status",
  "type": "system_status",
  "x": 0, "y": 1, "w": 4, "h": 4,
  "title": "System Status"
}
```

Shows: connection status, acquisition state, recording state, scan rate, uptime.

---

### Widget Type: alarm_summary

Active alarms list.

```json
{
  "id": "w-alarms",
  "type": "alarm_summary",
  "x": 0, "y": 1, "w": 5, "h": 4,
  "title": "Active Alarms",
  "maxItems": 10,
  "showAckButton": true,
  "filterPriority": ["critical", "high"]
}
```

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `maxItems` | number | `10` | Maximum alarms to show |
| `showAckButton` | boolean | `true` | Show acknowledge button |
| `filterPriority` | array | all | Filter by priority level |

---

### Widget Type: interlock_status

Safety interlock status panel.

```json
{
  "id": "w-interlocks",
  "type": "interlock_status",
  "x": 0, "y": 1, "w": 4, "h": 4,
  "title": "Safety Interlocks"
}
```

Shows all configured interlocks with their current state (OK/TRIPPED).

---

### Widget Type: value_table

Multi-channel value table.

```json
{
  "id": "w-table",
  "type": "value_table",
  "channels": ["TC001", "TC002", "PT001", "FT001"],
  "x": 0, "y": 1, "w": 6, "h": 4,
  "title": "Process Values",
  "showAlarmStatus": true,
  "showUnits": true
}
```

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `channels` | array | **Required** | Array of channel TAGs |
| `showAlarmStatus` | boolean | `true` | Show alarm indicators |
| `showUnits` | boolean | `true` | Show engineering units |

---

### Widget Type: divider

Visual separator line.

```json
{
  "id": "w-div-1",
  "type": "divider",
  "x": 0, "y": 5, "w": 24, "h": 1,
  "style": {
    "color": "#3b82f6",
    "thickness": 2
  }
}
```

---

## Complete Example Project

```json
{
  "type": "nisystem-project",
  "version": "2.0",
  "name": "Heat Exchanger Test Stand",
  "description": "Water-to-water heat exchanger performance testing system",
  "created": "2026-01-20T00:00:00.000Z",
  "modified": "2026-01-20T00:00:00.000Z",
  "system": {
    "mqtt_broker": "localhost",
    "mqtt_port": 1883,
    "mqtt_base_topic": "nisystem",
    "scan_rate_hz": 10,
    "publish_rate_hz": 4,
    "simulation_mode": true,
    "system_name": "HX Test Stand",
    "system_id": "HX-001"
  },
  "service": {
    "heartbeat_interval_sec": 2,
    "health_timeout_sec": 10
  },
  "channels": {
    "TC_Hot_In": {
      "physical_channel": "cDAQ9189-1234Mod1/ai0",
      "channel_type": "thermocouple",
      "thermocouple_type": "K",
      "units": "degF",
      "display_name": "Hot Side Inlet",
      "alarm_enabled": true,
      "hi_limit": 200,
      "hihi_limit": 212,
      "alarm_priority": "high",
      "log": true,
      "precision": 1,
      "group": "Temperatures"
    },
    "TC_Hot_Out": {
      "physical_channel": "cDAQ9189-1234Mod1/ai1",
      "channel_type": "thermocouple",
      "thermocouple_type": "K",
      "units": "degF",
      "display_name": "Hot Side Outlet",
      "log": true,
      "precision": 1,
      "group": "Temperatures"
    },
    "TC_Cold_In": {
      "physical_channel": "cDAQ9189-1234Mod1/ai2",
      "channel_type": "thermocouple",
      "thermocouple_type": "K",
      "units": "degF",
      "display_name": "Cold Side Inlet",
      "log": true,
      "precision": 1,
      "group": "Temperatures"
    },
    "TC_Cold_Out": {
      "physical_channel": "cDAQ9189-1234Mod1/ai3",
      "channel_type": "thermocouple",
      "thermocouple_type": "K",
      "units": "degF",
      "display_name": "Cold Side Outlet",
      "log": true,
      "precision": 1,
      "group": "Temperatures"
    },
    "FT_Hot": {
      "physical_channel": "cDAQ9189-1234Mod2/ai0",
      "channel_type": "current_input",
      "current_range_ma": 20,
      "four_twenty_scaling": true,
      "units": "GPM",
      "eng_units_min": 0,
      "eng_units_max": 50,
      "display_name": "Hot Side Flow",
      "alarm_enabled": true,
      "lo_limit": 5,
      "alarm_priority": "medium",
      "log": true,
      "precision": 1,
      "group": "Flow"
    },
    "FT_Cold": {
      "physical_channel": "cDAQ9189-1234Mod2/ai1",
      "channel_type": "current_input",
      "current_range_ma": 20,
      "four_twenty_scaling": true,
      "units": "GPM",
      "eng_units_min": 0,
      "eng_units_max": 50,
      "display_name": "Cold Side Flow",
      "alarm_enabled": true,
      "lo_limit": 5,
      "alarm_priority": "medium",
      "log": true,
      "precision": 1,
      "group": "Flow"
    },
    "Hot_Pump": {
      "physical_channel": "cDAQ9189-1234Mod3/port0/line0",
      "channel_type": "digital_output",
      "display_name": "Hot Pump",
      "description": "Hot side circulation pump",
      "log": true,
      "group": "Control"
    },
    "Cold_Pump": {
      "physical_channel": "cDAQ9189-1234Mod3/port0/line1",
      "channel_type": "digital_output",
      "display_name": "Cold Pump",
      "description": "Cold side circulation pump",
      "log": true,
      "group": "Control"
    }
  },
  "safety": {
    "enabled": true,
    "watchdog_timeout_sec": 5,
    "actions": {
      "high-temp-shutdown": {
        "name": "High Temperature Shutdown",
        "description": "Stop pumps on overtemperature",
        "outputs": {
          "Hot_Pump": false,
          "Cold_Pump": false
        },
        "latching": true,
        "priority": 1
      }
    },
    "interlocks": [
      {
        "name": "Hot Side Overtemp",
        "condition": "TC_Hot_In > 212",
        "action": "high-temp-shutdown",
        "delay_ms": 0
      }
    ]
  },
  "layout": {
    "gridColumns": 24,
    "rowHeight": 30,
    "currentPageId": "overview",
    "pages": [
      {
        "id": "overview",
        "name": "Overview",
        "order": 0,
        "widgets": [
          {
            "id": "w-title",
            "type": "title",
            "title": "Heat Exchanger Test Stand",
            "x": 0, "y": 0, "w": 12, "h": 1,
            "style": { "fontSize": "large" }
          },
          {
            "id": "w-clock",
            "type": "clock",
            "x": 20, "y": 0, "w": 4, "h": 1,
            "showDate": true
          },
          {
            "id": "w-status",
            "type": "system_status",
            "x": 0, "y": 1, "w": 4, "h": 3
          },
          {
            "id": "w-gauge-hot-in",
            "type": "gauge",
            "channel": "TC_Hot_In",
            "x": 4, "y": 1, "w": 4, "h": 3,
            "minValue": 50,
            "maxValue": 250,
            "showLimits": true
          },
          {
            "id": "w-gauge-hot-out",
            "type": "gauge",
            "channel": "TC_Hot_Out",
            "x": 8, "y": 1, "w": 4, "h": 3,
            "minValue": 50,
            "maxValue": 250
          },
          {
            "id": "w-gauge-cold-in",
            "type": "gauge",
            "channel": "TC_Cold_In",
            "x": 12, "y": 1, "w": 4, "h": 3,
            "minValue": 32,
            "maxValue": 150
          },
          {
            "id": "w-gauge-cold-out",
            "type": "gauge",
            "channel": "TC_Cold_Out",
            "x": 16, "y": 1, "w": 4, "h": 3,
            "minValue": 32,
            "maxValue": 150
          },
          {
            "id": "w-toggle-hot-pump",
            "type": "toggle",
            "channel": "Hot_Pump",
            "x": 0, "y": 4, "w": 3, "h": 1,
            "onLabel": "HOT PUMP ON",
            "offLabel": "HOT PUMP OFF"
          },
          {
            "id": "w-toggle-cold-pump",
            "type": "toggle",
            "channel": "Cold_Pump",
            "x": 3, "y": 4, "w": 3, "h": 1,
            "onLabel": "COLD PUMP ON",
            "offLabel": "COLD PUMP OFF"
          },
          {
            "id": "w-flow-hot",
            "type": "numeric",
            "channel": "FT_Hot",
            "x": 6, "y": 4, "w": 3, "h": 1
          },
          {
            "id": "w-flow-cold",
            "type": "numeric",
            "channel": "FT_Cold",
            "x": 9, "y": 4, "w": 3, "h": 1
          },
          {
            "id": "w-chart",
            "type": "chart",
            "channels": ["TC_Hot_In", "TC_Hot_Out", "TC_Cold_In", "TC_Cold_Out"],
            "x": 0, "y": 5, "w": 24, "h": 6,
            "timeRange": 300,
            "showGrid": true,
            "showLegend": true,
            "title": "Temperature Trends"
          }
        ]
      }
    ]
  }
}
```

---

## Generation Checklist

When generating a project, ensure:

- [ ] `type` is `"nisystem-project"`
- [ ] `version` is `"2.0"`
- [ ] All channel TAGs are unique
- [ ] Channel TAGs use only alphanumeric and underscore
- [ ] Physical channels are properly formatted
- [ ] All widget IDs are unique
- [ ] Widgets reference valid channel TAGs
- [ ] Safety actions reference valid output channels
- [ ] Interlocks reference valid actions
- [ ] Page IDs are unique lowercase identifiers
- [ ] Widget positions don't overlap excessively
- [ ] Chart channels arrays don't exceed 8 items
