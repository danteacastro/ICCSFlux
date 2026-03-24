# ICCSFlux Project JSON Generation Guide

**Purpose**: This guide provides all information needed for an AI to generate valid ICCSFlux project JSON files for industrial data acquisition and control systems.

---

## Overview

ICCSFlux is a data acquisition (DAQ) and control system that:
- Reads sensor data from NI cDAQ hardware, cRIO controllers, and Opto22 devices
- Controls digital and analog outputs
- Provides real-time visualization via a web dashboard
- Records data to CSV and TDMS files
- Implements safety interlocks and alarms
- Runs Python automation scripts

A project JSON file defines the complete system configuration including channels, safety rules, user variables, recording settings, and dashboard layout.

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
  "userVariables": [ ],
  "recording": { },
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

The `channels` object is a dictionary where **keys are TAG names** (unique identifiers) and values are channel configuration objects. The `name` field inside the channel object must match the dictionary key.

```json
"channels": {
  "TC-001": { "name": "TC-001", ... },
  "PT_Supply": { "name": "PT_Supply", ... },
  "Valve_Main": { "name": "Valve_Main", ... }
}
```

### Channel Naming Rules

1. **Use alphanumeric characters, underscores, and dashes**: `A-Z`, `a-z`, `0-9`, `_`, `-`
2. **Start with a letter**: `TC001` (valid), `001TC` (invalid)
3. **Dashes are valid** (ISA-5.1 tag names use dashes): `TT-101`, `PT-200`, `FT-301`
4. **Keep concise but descriptive**:
   - Temperatures: `TC-001`, `RTD_Inlet`, `TT-101`
   - Pressures: `PT-001`, `PT_Supply`, `PI-200`
   - Flows: `FT-001`, `FT_Water`, `FI-301`
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
| `counter` or `counter_input` | Counter/pulse input | Flow totalizers, encoder counts |
| `counter_output` | Counter/pulse output | Pulse train output |
| `frequency_input` | Frequency measurement input | Frequency sensors |
| `pulse_output` | Pulse train output | Stepper motor, PWM |
| `strain` or `strain_input` | Strain gauge input | Load cells, force sensors |
| `bridge_input` | Wheatstone bridge input | Universal bridge sensors |
| `iepe` or `iepe_input` | IEPE accelerometer | Vibration sensors |
| `resistance` or `resistance_input` | Resistance measurement | Resistance sensors |
| `modbus_register` | Modbus holding/input register | Modbus devices |
| `modbus_coil` | Modbus coil/discrete input | Modbus digital I/O |

Short forms (`strain`, `iepe`, `resistance`, `counter`) and explicit forms (`strain_input`, `iepe_input`, `resistance_input`, `counter_input`) are both valid and behave identically.

**IMPORTANT:** Do NOT use `script`, `calculated`, `virtual`, or any other type not listed above. These are NOT valid channel types and will cause `ValueError` when loading the project.

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
  "name": "TC_Flue_1",
  "physical_channel": "cDAQ9189-1A2B3C4Mod1/ai0",
  "channel_type": "thermocouple",
  "thermocouple_type": "K",
  "unit": "degF",
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
  "decimals": 1,
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
| `"J"` | -40 to 750C | General purpose, reducing atmospheres |
| `"K"` | -200 to 1350C | **Most common**, general purpose |
| `"T"` | -200 to 350C | Low temp, food, cryogenics |
| `"E"` | -200 to 900C | High sensitivity |
| `"N"` | -200 to 1300C | High temp, stable |
| `"R"` | 0 to 1450C | Very high temp, platinum |
| `"S"` | 0 to 1450C | Very high temp, platinum |
| `"B"` | 0 to 1820C | Extreme high temp |

---

### Channel Type: RTD

For precision temperature measurement using RTD sensors.

```json
"RTD_Water_Supply": {
  "name": "RTD_Water_Supply",
  "physical_channel": "cDAQ9189-1A2B3C4Mod2/ai0",
  "channel_type": "rtd",
  "rtd_type": "Pt100",
  "rtd_wiring": "3-wire",
  "rtd_current": 0.001,
  "rtd_resistance": 100,
  "unit": "degF",
  "description": "Feedwater supply temperature to boiler",
  "alarm_enabled": false,
  "log": true,
  "decimals": 2,
  "group": "Water Loop"
}
```

#### RTD-Specific Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `rtd_type` | string | **Yes** | - | RTD type: `"Pt100"`, `"Pt500"`, `"Pt1000"`, `"custom"` |
| `rtd_wiring` | string | **Yes** | - | Wiring: `"2-wire"`, `"3-wire"`, `"4-wire"` |
| `rtd_current` | number | No | `0.001` | Excitation current in Amps |
| `rtd_resistance` | number | No | `100` | Nominal resistance at 0C in Ohms |

#### RTD Type Selection

| Type | Description |
|------|-------------|
| `"Pt100"` | Platinum, 100 Ohm at 0C (IEC 60751, most common) |
| `"Pt500"` | Platinum, 500 Ohm at 0C |
| `"Pt1000"` | Platinum, 1000 Ohm at 0C |
| `"custom"` | Custom RTD type (set `rtd_resistance` to nominal value) |

#### Wiring Configuration

| Config | Description | Accuracy |
|--------|-------------|----------|
| `"2-wire"` | Simple, lead resistance affects reading | Low |
| `"3-wire"` | Compensates for lead resistance | Medium |
| `"4-wire"` | Full compensation, highest accuracy | High |

---

### Channel Type: Voltage Input

For analog sensors with 0-10V or similar voltage output.

```json
"PT_Supply": {
  "name": "PT_Supply",
  "physical_channel": "cDAQ9189-1A2B3C4Mod3/ai0",
  "channel_type": "voltage_input",
  "voltage_range": 10,
  "terminal_config": "differential",
  "unit": "psig",
  "scale_type": "map",
  "pre_scaled_min": 0,
  "pre_scaled_max": 10,
  "scaled_min": 0,
  "scaled_max": 100,
  "description": "Main supply header pressure",
  "alarm_enabled": true,
  "lo_limit": 20,
  "lolo_limit": 10,
  "hi_limit": 80,
  "hihi_limit": 90,
  "alarm_priority": "high",
  "alarm_deadband": 2,
  "log": true,
  "decimals": 1,
  "group": "Pressures"
}
```

#### Voltage Input Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `voltage_range` | number | **Yes** | - | Max voltage: `1`, `5`, `10` |
| `terminal_config` | string | No | `"differential"` | `"differential"`, `"rse"`, `"nrse"` (lowercase preferred) |
| `scale_type` | string | No | `"none"` | Scaling method: `"none"`, `"linear"`, `"map"` |

**Scaling options:**

For **linear scaling** (`scale_type: "linear"`):

| Field | Type | Description |
|-------|------|-------------|
| `scale_slope` | number | Multiplier: `engineering_value = raw * slope + offset` |
| `scale_offset` | number | Offset |

For **map scaling** (`scale_type: "map"`):

| Field | Type | Description |
|-------|------|-------------|
| `pre_scaled_min` | number | Raw value at minimum (e.g., 0V) |
| `pre_scaled_max` | number | Raw value at maximum (e.g., 10V) |
| `scaled_min` | number | Engineering units at minimum |
| `scaled_max` | number | Engineering units at maximum |

#### Terminal Configuration

| Config | Description | Use When |
|--------|-------------|----------|
| `"differential"` | Differential (2 wires per channel) | Best noise rejection, default choice |
| `"rse"` | Referenced Single-Ended | More channels, shared ground |
| `"nrse"` | Non-Referenced Single-Ended | Floating signal sources |

---

### Channel Type: Current Input

For 4-20mA industrial transmitters.

```json
"FT_Water": {
  "name": "FT_Water",
  "physical_channel": "cDAQ9189-1A2B3C4Mod3/ai4",
  "channel_type": "current_input",
  "current_range_ma": 20,
  "four_twenty_scaling": true,
  "terminal_config": "differential",
  "unit": "GPM",
  "eng_units_min": 0,
  "eng_units_max": 100,
  "description": "Circulating water flow through heat exchanger",
  "alarm_enabled": true,
  "lo_limit": 10,
  "lolo_limit": 5,
  "alarm_priority": "high",
  "alarm_deadband": 1,
  "safety_action": "low-flow-shutdown",
  "log": true,
  "decimals": 1,
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
  "name": "Firing_Rate_SP",
  "physical_channel": "cDAQ9189-1A2B3C4Mod5/ao0",
  "channel_type": "voltage_output",
  "voltage_range": 10,
  "unit": "%",
  "scale_type": "map",
  "pre_scaled_min": 0,
  "pre_scaled_max": 10,
  "scaled_min": 0,
  "scaled_max": 100,
  "description": "Burner firing rate command (0-100%)",
  "log": true,
  "decimals": 0,
  "group": "Control"
}
```

#### Voltage Output Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `voltage_range` | number | **Yes** | Output range: `5` or `10` |
| `scale_type` | string | No | Scaling: `"none"`, `"linear"`, `"map"` |

See Voltage Input section above for `scale_slope`/`scale_offset` (linear) or `pre_scaled_min`/`pre_scaled_max`/`scaled_min`/`scaled_max` (map) fields.

---

### Channel Type: Current Output

For 4-20mA control outputs.

```json
"Valve_Position_SP": {
  "name": "Valve_Position_SP",
  "physical_channel": "cDAQ9189-1A2B3C4Mod5/ao2",
  "channel_type": "current_output",
  "current_range_ma": 20,
  "four_twenty_output": true,
  "unit": "%",
  "eng_units_min": 0,
  "eng_units_max": 100,
  "description": "Control valve position command",
  "log": true,
  "decimals": 0,
  "group": "Control"
}
```

---

### Channel Type: Digital Input

For discrete on/off signals (switches, status).

```json
"Flame_Detected": {
  "name": "Flame_Detected",
  "physical_channel": "cDAQ9189-1A2B3C4Mod7/port0/line0",
  "channel_type": "digital_input",
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
  "name": "Burner_Enable",
  "physical_channel": "cDAQ9189-1A2B3C4Mod6/port0/line0",
  "channel_type": "digital_output",
  "description": "Master burner enable relay - energized to run",
  "invert": false,
  "default_state": false,
  "log": true,
  "group": "Control"
}
```

#### Digital Output Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `invert` | boolean | No | `false` | Invert the logic |
| `default_state` | boolean | No | `false` | Value on system startup |

---

### Common Channel Properties (All Types)

| Property | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `physical_channel` | string | Yes for HW | - | NI-DAQmx device path |
| `channel_type` | string | Yes | - | One of the types above |
| `name` | string | Yes | - | TAG name (must match the dictionary key) |
| `unit` | string | No | `""` | Engineering units for display |
| `description` | string | No | `""` | Human-readable description |
| `group` | string | No | `"Ungrouped"` | Logical group for organization |
| `log` | boolean | No | `true` | Include in data recording |
| `log_interval_ms` | number | No | system default | Recording interval override |
| `decimals` | number | No | `2` | Decimal places for display |
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
| `alarm_priority` | string | `"diagnostic"`, `"low"`, `"medium"`, `"high"`, `"critical"` |
| `alarm_deadband` | number | Deadband to prevent alarm chatter |
| `alarm_delay_sec` | number | On-delay: value must exceed limit for this duration before alarm triggers |
| `alarm_clear_delay_sec` | number | Off-delay: value must be within limits for this duration before alarm clears |
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
| `outputs` | object | **Yes** | Map of output channel TAG to value |
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
TC-001 > 500 OR TC-002 > 500
(PT-001 < 10 OR PT-001 > 100) AND Pump_Running == true
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
| `label` | string | No | Widget label/header text |

### Grid System

- **24 columns** across the screen
- Each row is **30 pixels** tall
- Widgets snap to grid
- Position (0,0) is top-left

**Typical Sizes:**
| Widget Type | Minimum Size | Recommended Size |
|-------------|--------------|------------------|
| Title | 4x1 | 8-12x1 |
| Numeric | 2x1 | 3x1 |
| Gauge | 3x2 | 4x3 |
| LED | 2x1 | 2-3x1 |
| Toggle | 2x1 | 2-3x1 |
| Chart | 8x3 | 12x5 |
| Sparkline | 3x2 | 4x2 |
| Action Button | 2x1 | 2-3x2 |
| Heater Zone | 3x2 | 3-4x3 |
| PID Loop | 3x2 | 3-4x3 |
| Script Monitor | 3x3 | 4-6x4 |

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
| `style.fontSize` | string | `"small"`, `"medium"`, `"large"`, `"xlarge"` | Text size |
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
  "format24h": false
}
```

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `showDate` | boolean | `true` | Display the date |
| `showElapsed` | boolean | `false` | Show elapsed session time |
| `format24h` | boolean | `false` | Use 24-hour format |

---

### Widget Type: numeric

Single channel value display.

```json
{
  "id": "w-temp-display",
  "type": "numeric",
  "channel": "TC-001",
  "x": 0, "y": 1, "w": 3, "h": 1,
  "showLabel": true,
  "showUnit": true,
  "decimals": 1
}
```

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `channel` | string | **Required** | Channel TAG to display |
| `showLabel` | boolean | `true` | Show channel label |
| `showUnit` | boolean | `true` | Show engineering units |
| `decimals` | number | from channel | Decimal places |

---

### Widget Type: gauge

Circular gauge visualization.

```json
{
  "id": "w-pressure-gauge",
  "type": "gauge",
  "channel": "PT-001",
  "x": 0, "y": 1, "w": 4, "h": 3,
  "minValue": 0,
  "maxValue": 100,
  "showAlarmStatus": true,
  "showValue": true
}
```

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `channel` | string | **Required** | Channel TAG |
| `minValue` | number | `0` | Gauge minimum |
| `maxValue` | number | `100` | Gauge maximum |
| `showAlarmStatus` | boolean | `false` | Show alarm status indicator |
| `showValue` | boolean | `true` | Show numeric value |

---

### Widget Type: bar_graph

Horizontal or vertical bar graph.

```json
{
  "id": "w-level-bar",
  "type": "bar_graph",
  "channel": "Level",
  "x": 0, "y": 1, "w": 6, "h": 1,
  "minValue": 0,
  "maxValue": 100,
  "showValue": true,
  "orientation": "horizontal",
  "barGraphStyle": "bar"
}
```

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `channel` | string | **Required** | Channel TAG |
| `minValue` | number | `0` | Bar minimum |
| `maxValue` | number | `100` | Bar maximum |
| `showValue` | boolean | `true` | Show numeric value |
| `orientation` | string | `"horizontal"` | `"horizontal"` or `"vertical"` |
| `barGraphStyle` | string | `"bar"` | `"bar"`, `"tank"`, `"thermometer"` |

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
  "invert": false
}
```

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `channel` | string | **Required** | Channel TAG |
| `label` | string | channel name | Display label |
| `onColor` | string | `"#22c55e"` | Color when ON (CSS color) |
| `offColor` | string | `"#64748b"` | Color when OFF |
| `threshold` | number | `null` | For analog: ON if value > threshold |
| `invert` | boolean | `false` | Invert threshold/digital logic |
| `ledSize` | string | `"medium"` | `"small"`, `"medium"`, `"large"` |

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
  "setpointStyle": "standard"
}
```

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `channel` | string | **Required** | Output channel TAG |
| `minValue` | number | `0` | Minimum allowed value |
| `maxValue` | number | `100` | Maximum allowed value |
| `step` | number | `1` | Increment step size |
| `setpointStyle` | string | `"standard"` | Visual style: `"standard"` or `"knob"` |

---

### Widget Type: chart

Multi-channel trend chart.

```json
{
  "id": "w-temp-chart",
  "type": "chart",
  "channels": ["TC-001", "TC-002", "TC-003", "TC-004"],
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
  "label": "Flow Trend"
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
  "label": "System Status"
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
  "label": "Active Alarms",
  "maxItems": 10,
  "showAckButton": true,
  "filterPriority": "critical"
}
```

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `maxItems` | number | `10` | Maximum alarms to show |
| `showAckButton` | boolean | `true` | Show acknowledge button |
| `filterPriority` | string | all | Filter by priority level |

---

### Widget Type: interlock_status

Safety interlock status panel.

```json
{
  "id": "w-interlocks",
  "type": "interlock_status",
  "x": 0, "y": 1, "w": 4, "h": 4,
  "label": "Safety Interlocks"
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
  "channels": ["TC-001", "TC-002", "PT-001", "FT-001"],
  "x": 0, "y": 1, "w": 6, "h": 4,
  "label": "Process Values",
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
  "lineColor": "#3b82f6",
  "lineStyle": "solid"
}
```

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `lineColor` | string | `"#3b82f6"` | Line color |
| `lineStyle` | string | `"solid"` | `"solid"`, `"dashed"`, `"dotted"` |

---

## Section 8: Additional Widget Types

### Widget Type: action_button

Configurable action button with multiple behaviors.

```json
{
  "id": "w-start-btn",
  "type": "action_button",
  "x": 0, "y": 0, "w": 2, "h": 1,
  "label": "START TEST",
  "buttonColor": "#22c55e",
  "buttonBehavior": "one_shot",
  "buttonVisualStyle": "standard",
  "requireConfirmation": true,
  "buttonAction": {
    "type": "system_command",
    "command": "acquisition_start"
  }
}
```

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `label` | string | **Required** | Button text |
| `buttonColor` | string | - | Button color |
| `buttonBehavior` | string | `"one_shot"` | Mechanical action (see below) |
| `buttonVisualStyle` | string | `"standard"` | Visual style (see below) |
| `requireConfirmation` | boolean | `false` | Require confirmation dialog |
| `buttonAction` | object | **Required** | Action to perform (see below) |

**`buttonBehavior` values:**
- `"momentary"` - Active while held, returns to off when released
- `"toggle"` - Alternates state on each press
- `"latching"` - Sets ON and stays until external reset
- `"one_shot"` - Pulses once per press (default)

**`buttonVisualStyle` values:**
- `"standard"` - Default rectangular button
- `"round"` - Circular button
- `"square"` - Square button
- `"emergency"` - Emergency stop style (red, prominent, round)
- `"flat"` - Flat/minimal style

**`buttonAction.type` values:**
- `"mqtt_publish"` - Publish to MQTT topic (requires `topic`, `payload`)
- `"digital_output"` - Set digital output (requires `channel`)
- `"script_run"` - Run a script/sequence
- `"script_oneshot"` - Run a script once
- `"variable_set"` - Set a user variable to a value
- `"variable_reset"` - Reset a user variable
- `"system_command"` - System command (requires `command`)

**System commands for `buttonAction.command`:**
- `"acquisition_start"` / `"acquisition_stop"`
- `"recording_start"` / `"recording_stop"`
- `"alarm_acknowledge_all"`
- `"latch_reset_all"`

---

### Widget Type: pid_loop

PID control loop faceplate.

```json
{
  "id": "w-pid",
  "type": "pid_loop",
  "x": 0, "y": 0, "w": 3, "h": 3,
  "label": "Zone 1 PID"
}
```

Displays PV (Process Variable), SP (Setpoint), CV (Control Variable), and MV (Manipulated Variable) for a PID control loop. PID loops are configured in the backend, not in the widget config.

---

### Widget Type: heater_zone

Dual-loop temperature controller faceplate.

```json
{
  "id": "w-zone1",
  "type": "heater_zone",
  "x": 0, "y": 0, "w": 3, "h": 2,
  "pvChannel": "TC_Zone1_PV",
  "spChannel": "TC_Zone1_SP",
  "enableChannel": "Zone1_Enable",
  "outputChannel": "Zone1_Output",
  "spMin": 0,
  "spMax": 500,
  "temperatureUnit": "F",
  "label": "Zone 1"
}
```

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `pvChannel` | string | **Yes** | Process value channel TAG |
| `spChannel` | string | **Yes** | Setpoint channel TAG |
| `enableChannel` | string | No | Enable/disable channel TAG |
| `outputChannel` | string | No | Output percentage channel TAG |
| `spMin` | number | No | Setpoint minimum |
| `spMax` | number | No | Setpoint maximum |
| `temperatureUnit` | string | No | `"F"` or `"C"` |

---

### Widget Type: recording_status

Recording state display.

```json
{
  "id": "w-rec",
  "type": "recording_status",
  "x": 0, "y": 0, "w": 3, "h": 2,
  "label": "Recording"
}
```

Shows recording state, filename, duration, and file size. No channel required.

---

### Widget Type: script_monitor

Displays script-published values in a table or grid.

```json
{
  "id": "w-scripts",
  "type": "script_monitor",
  "x": 0, "y": 0, "w": 4, "h": 4,
  "label": "Script Values",
  "items": [
    { "tag": "py.PUE", "label": "PUE", "format": "number", "decimals": 2 },
    { "tag": "py.COP", "label": "COP", "format": "number", "decimals": 1 }
  ],
  "columns": 2
}
```

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `items` | array | - | Script value definitions (see below) |
| `columns` | number | `1` | Number of display columns: `1`, `2`, or `3` |
| `showTimestamp` | boolean | `false` | Show last update timestamp |

**Item fields:**

| Field | Type | Description |
|-------|------|-------------|
| `tag` | string | Script output tag (e.g., `"py.PUE"`) |
| `label` | string | Display label |
| `format` | string | `"number"`, `"integer"`, `"percent"`, `"status"`, `"text"` |
| `decimals` | number | Decimal places |
| `unit` | string | Optional unit label |

---

### Widget Type: variable_input

User variable input controls.

```json
{
  "id": "w-vars",
  "type": "variable_input",
  "x": 0, "y": 0, "w": 3, "h": 3,
  "label": "Test Parameters"
}
```

Shows all user variables with appropriate input controls. No channel required.

---

### Widget Type: latch_switch

Safety latch switch button.

```json
{
  "id": "w-latch",
  "type": "latch_switch",
  "x": 0, "y": 0, "w": 2, "h": 2,
  "label": "Safety Latch"
}
```

---

### Widget Type: scheduler_status

Displays scheduler state including active schedules, next run time, and history.

```json
{
  "id": "w-sched",
  "type": "scheduler_status",
  "x": 0, "y": 0, "w": 4, "h": 3,
  "label": "Scheduler"
}
```

---

### Widget Type: crio_status

Shows cRIO controller connection status, firmware version, and channel health.

```json
{
  "id": "w-crio",
  "type": "crio_status",
  "x": 0, "y": 0, "w": 4, "h": 3,
  "label": "cRIO Status"
}
```

---

### Widget Type: python_console

Interactive Python (Pyodide) REPL console in the browser.

```json
{
  "id": "w-console",
  "type": "python_console",
  "x": 0, "y": 0, "w": 6, "h": 5,
  "label": "Python Console"
}
```

---

### Widget Type: script_output

Shows the stdout/stderr output from running scripts.

```json
{
  "id": "w-script-out",
  "type": "script_output",
  "x": 0, "y": 0, "w": 6, "h": 4,
  "label": "Script Output"
}
```

---

### Widget Type: variable_explorer

IPython-like variable inspector showing all live values.

```json
{
  "id": "w-explorer",
  "type": "variable_explorer",
  "x": 0, "y": 0, "w": 5, "h": 4,
  "label": "Variable Explorer"
}
```

---

### Widget Type: status_messages

Scrolling system status message log.

```json
{
  "id": "w-messages",
  "type": "status_messages",
  "x": 0, "y": 0, "w": 6, "h": 3,
  "label": "System Messages"
}
```

---

### Widget Type: svg_symbol

SCADA symbol display with optional live data binding.

```json
{
  "id": "w-valve",
  "type": "svg_symbol",
  "x": 0, "y": 0, "w": 2, "h": 2,
  "symbol": "solenoidValve",
  "channel": "Valve_Main",
  "showValue": true,
  "label": "Main Valve"
}
```

| Property | Type | Description |
|----------|------|-------------|
| `symbol` | string | Symbol type from SCADA_SYMBOLS library |
| `channel` | string | Optional channel binding for live data |
| `showValue` | boolean | Show current value overlay |
| `symbolSize` | string | `"small"`, `"medium"`, `"large"` |
| `rotation` | number | `0`, `90`, `180`, `270` |

---

### Widget Type: image

Static image display.

```json
{
  "id": "w-logo",
  "type": "image",
  "x": 0, "y": 0, "w": 3, "h": 2,
  "imageUrl": "https://example.com/logo.png",
  "imageFit": "contain"
}
```

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `imageUrl` | string | **Required** | Image URL |
| `imageFit` | string | `"contain"` | `"contain"`, `"cover"`, `"fill"`, `"none"` |

---

## Section 8b: ISA-101 HMI Controls (P&ID Canvas)

ISA-101 HMI controls are HTML-based interactive components placed on the P&ID canvas (not dashboard widgets). They are added as P&ID symbols with `type` starting with `hmi_`. HMI controls render live data, support alarm coloring, and provide operator interaction in runtime mode.

HMI controls are configured through P&ID symbol properties in the `layout.pidData.symbols` array.

### Available HMI Control Types

| Type | Name | Default Size | Description |
|------|------|-------------|-------------|
| `hmi_numeric` | Numeric Indicator | 120×50 | Value display with alarm coloring |
| `hmi_led` | Status LED | 40×50 | Boolean on/off indicator |
| `hmi_toggle` | Toggle Switch | 100×50 | Digital output ON/OFF control |
| `hmi_setpoint` | Setpoint Control | 120×60 | Editable setpoint with min/max limits |
| `hmi_bar` | Bar Indicator | 140×40 | Horizontal/vertical bar with alarm zones |
| `hmi_gauge` | Arc Gauge | 100×100 | Circular gauge with alarm zones |
| `hmi_multistate` | Multi-State | 120×40 | Multi-value state indicator (e.g., OFF/IDLE/RUN/FAULT) |
| `hmi_button` | Command Button | 100×40 | Action button (MQTT publish, output set, system command) |
| `hmi_selector` | Selector Switch | 140×50 | Multi-position selector (e.g., OFF/MAN/AUTO) |
| `hmi_annunciator` | Annunciator | 120×50 | ISA-18.2 alarm annunciator tile |
| `hmi_sparkline` | Trend Sparkline | 160×50 | Mini trend line with current value |
| `hmi_valve_pos` | Valve Position | 80×80 | Valve position graphic (0-100%) |
| `hmi_interlock` | Interlock Block | 200×80 | Safety interlock status block |

### HMI Symbol Configuration Fields

All HMI controls are P&ID symbols (`PidSymbol` type). Common fields:

```json
{
  "id": "hmi-tt101",
  "type": "hmi_numeric",
  "x": 200,
  "y": 150,
  "width": 120,
  "height": 50,
  "label": "TT-101",
  "channel": "TT-101",
  "decimals": 1
}
```

### HMI-Specific Config Fields

These fields are only used when the symbol type starts with `hmi_`:

| Field | Type | Default | Used By | Description |
|-------|------|---------|---------|-------------|
| `hmiMinValue` | number | `0` | bar, gauge, setpoint | Scale minimum |
| `hmiMaxValue` | number | `100` | bar, gauge, setpoint | Scale maximum |
| `hmiAlarmHigh` | number | - | numeric, bar, gauge | High alarm threshold (red zone) |
| `hmiAlarmLow` | number | - | numeric, bar, gauge | Low alarm threshold (red zone) |
| `hmiWarningHigh` | number | - | numeric, bar, gauge | High warning threshold (yellow zone) |
| `hmiWarningLow` | number | - | numeric, bar, gauge | Low warning threshold (yellow zone) |
| `hmiOrientation` | string | `"horizontal"` | bar | `"horizontal"` or `"vertical"` |
| `hmiUnit` | string | - | numeric, bar, gauge | Unit label override |
| `hmiStates` | array | - | multistate | State definitions (see below) |
| `hmiSelectorPositions` | array | - | selector | Position definitions (see below) |
| `hmiButtonAction` | object | - | button | Button action (same as widget `buttonAction`) |
| `hmiSparklineSamples` | number | `60` | sparkline | Number of trend samples to display |

### Multi-State Configuration

```json
"hmiStates": [
  { "value": 0, "label": "OFF", "color": "#6b7280" },
  { "value": 1, "label": "IDLE", "color": "#eab308" },
  { "value": 2, "label": "RUNNING", "color": "#22c55e" },
  { "value": 3, "label": "FAULT", "color": "#ef4444" }
]
```

### Selector Switch Configuration

```json
"hmiSelectorPositions": [
  { "value": 0, "label": "OFF" },
  { "value": 1, "label": "MAN" },
  { "value": 2, "label": "AUTO" }
]
```

### HMI Example: Process Overview with Controls

```json
"pidData": {
  "symbols": [
    {
      "id": "hmi-temp",
      "type": "hmi_numeric",
      "x": 100, "y": 50,
      "width": 120, "height": 50,
      "label": "Zone Temp",
      "channel": "TT-101",
      "decimals": 1,
      "hmiUnit": "°F",
      "hmiAlarmHigh": 500,
      "hmiWarningHigh": 450,
      "hmiWarningLow": 100,
      "hmiAlarmLow": 50
    },
    {
      "id": "hmi-valve",
      "type": "hmi_valve_pos",
      "x": 300, "y": 50,
      "width": 80, "height": 80,
      "label": "CV-101",
      "channel": "CV-101_Pos",
      "decimals": 0,
      "hmiMinValue": 0,
      "hmiMaxValue": 100
    },
    {
      "id": "hmi-pump",
      "type": "hmi_toggle",
      "x": 500, "y": 50,
      "width": 100, "height": 50,
      "label": "Pump P-101",
      "channel": "Pump_P101"
    },
    {
      "id": "hmi-mode",
      "type": "hmi_selector",
      "x": 100, "y": 200,
      "width": 140, "height": 50,
      "label": "Control Mode",
      "channel": "Control_Mode",
      "hmiSelectorPositions": [
        { "value": 0, "label": "OFF" },
        { "value": 1, "label": "MAN" },
        { "value": 2, "label": "AUTO" }
      ]
    }
  ]
}
```

---

## Section 9: User Variables (userVariables)

User variables are defined in the `userVariables` array of the project JSON. They provide runtime-computed or user-editable values for formulas, accumulators, timers, and more.

```json
"userVariables": [
  {
    "id": "var-1",
    "name": "batch_total",
    "displayName": "Batch Total Volume",
    "variableType": "accumulator",
    "units": "gal",
    "value": 0,
    "persistent": true,
    "sourceChannel": "FT_Main",
    "edgeType": "rate",
    "sourceRateUnit": "per_minute",
    "scaleFactor": 1,
    "resetMode": "test_session"
  }
]
```

### Variable Types

| Type | Description | Required Fields |
|------|-------------|-----------------|
| `constant` | Fixed value for formulas (e.g., calibration factors) | `value` |
| `manual` | User-editable value | `value` |
| `string` | Text value (batch ID, operator notes) | `stringValue` |
| `accumulator` | Watches counter/rate channel for totalization | `sourceChannel`, `edgeType`, `scaleFactor` |
| `counter` | Edge-triggered counter | `sourceChannel`, `edgeType` |
| `timer` | Elapsed time counter (starts/stops via dashboard) | (none) |
| `sum` | Running sum of channel values | `sourceChannel` |
| `average` | Running average | `sourceChannel` |
| `min` | Minimum value seen | `sourceChannel` |
| `max` | Maximum value seen | `sourceChannel` |
| `expression` | Formula-based calculation | `formula` |
| `rate` | Rate of change (derivative) | `sourceChannel`, `rateWindowMs` |
| `runtime` | Time above/below threshold | `sourceChannel`, `thresholdValue`, `thresholdOperator` |
| `rolling` | Sliding window accumulator (e.g., last 24 hours) | `sourceChannel`, `rollingWindowS` |
| `stddev` | Running standard deviation (Welford's algorithm) | `sourceChannel` |
| `rms` | Root mean square (for AC, vibration) | `sourceChannel` |
| `median` | Running median (reservoir sampling) | `sourceChannel` |
| `peak_to_peak` | Difference between max and min | `sourceChannel` |
| `dwell` | Time in a state/condition | `dwellCondition` |
| `conditional_average` | Average only when condition is true | `sourceChannel`, `conditionChannel`, `conditionOperator`, `conditionValue` |
| `cross_channel` | Min/max/delta across multiple channels | `sourceChannels`, `crossChannelOperation` |

### Common Variable Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `id` | string | **Yes** | - | Unique variable ID |
| `name` | string | **Yes** | - | Variable name (used in formulas) |
| `displayName` | string | **Yes** | - | Human-readable label |
| `variableType` | string | **Yes** | - | One of the types above |
| `units` | string | No | `""` | Engineering units |
| `value` | number | No | `0` | Initial numeric value |
| `persistent` | boolean | No | `false` | Survive service restart |
| `resetMode` | string | **Yes** | - | When to reset (see below) |

### Edge Types (for accumulator/counter)

| Value | Description |
|-------|-------------|
| `"increment"` | Counter increased by any amount |
| `"rising"` | 0 to 1 transition |
| `"falling"` | 1 to 0 transition |
| `"both"` | Any transition |
| `"rate"` | Rate signal (4-20mA, voltage) - integrate over time |

### Reset Modes

| Value | Description |
|-------|-------------|
| `"manual"` | Only reset manually |
| `"time_of_day"` | Reset at specific time each day (requires `resetTime`) |
| `"elapsed"` | Reset after elapsed time (requires `resetElapsedS`) |
| `"test_session"` | Reset when test session starts |
| `"never"` | Never reset (persistent forever) |

---

## Section 10: Recording Configuration

The `recording` object configures data recording behavior.

```json
"recording": {
  "base_path": "./data",
  "file_prefix": "test_data",
  "file_format": "csv",
  "include_timestamp": true,
  "include_date": true,
  "log_rate_hz": 1,
  "decimation": 1,
  "max_file_size_mb": 100,
  "max_file_duration_s": 3600,
  "split_files": true,
  "mode": "manual",
  "selected_channels": [],
  "include_scripts": true,
  "trigger_channel": "",
  "trigger_condition": "above",
  "trigger_value": 0,
  "trigger_hysteresis": 0,
  "pre_trigger_samples": 0,
  "post_trigger_samples": 0
}
```

### Recording Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `base_path` | string | `"./data"` | Directory for recording files |
| `file_prefix` | string | `"test_data"` | Filename prefix |
| `file_format` | string | `"csv"` | `"csv"` or `"tdms"` |
| `include_timestamp` | boolean | `true` | Include timestamp in filename |
| `include_date` | boolean | `true` | Include date in filename |
| `log_rate_hz` | number | `1` | Recording rate in Hz |
| `decimation` | number | `1` | Record every Nth sample |
| `max_file_size_mb` | number | `100` | Maximum file size before rotation |
| `max_file_duration_s` | number | `3600` | Maximum duration per file |
| `split_files` | boolean | `true` | Auto-split files at size/duration limit |
| `mode` | string | `"manual"` | Recording mode (see below) |
| `selected_channels` | array | `[]` | Channel TAGs to record (empty = all) |
| `include_scripts` | boolean | `true` | Include script-published values |

### Recording Modes

| Mode | Description |
|------|-------------|
| `"manual"` | Start/stop via dashboard buttons |
| `"triggered"` | Auto-start when channel condition met |
| `"scheduled"` | Start at scheduled time |

### Triggered Mode Fields

| Field | Type | Description |
|-------|------|-------------|
| `trigger_channel` | string | Channel TAG to monitor |
| `trigger_condition` | string | `"above"`, `"below"`, `"change"` |
| `trigger_value` | number | Threshold value |
| `trigger_hysteresis` | number | Deadband to prevent re-triggering |
| `pre_trigger_samples` | number | Samples to keep before trigger |
| `post_trigger_samples` | number | Samples to record after trigger clears |

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
      "name": "TC_Hot_In",
      "physical_channel": "cDAQ9189-1234Mod1/ai0",
      "channel_type": "thermocouple",
      "thermocouple_type": "K",
      "unit": "degF",
      "description": "Hot side inlet temperature",
      "alarm_enabled": true,
      "hi_limit": 200,
      "hihi_limit": 212,
      "alarm_priority": "high",
      "log": true,
      "decimals": 1,
      "group": "Temperatures"
    },
    "TC_Hot_Out": {
      "name": "TC_Hot_Out",
      "physical_channel": "cDAQ9189-1234Mod1/ai1",
      "channel_type": "thermocouple",
      "thermocouple_type": "K",
      "unit": "degF",
      "description": "Hot side outlet temperature",
      "log": true,
      "decimals": 1,
      "group": "Temperatures"
    },
    "TC_Cold_In": {
      "name": "TC_Cold_In",
      "physical_channel": "cDAQ9189-1234Mod1/ai2",
      "channel_type": "thermocouple",
      "thermocouple_type": "K",
      "unit": "degF",
      "description": "Cold side inlet temperature",
      "log": true,
      "decimals": 1,
      "group": "Temperatures"
    },
    "TC_Cold_Out": {
      "name": "TC_Cold_Out",
      "physical_channel": "cDAQ9189-1234Mod1/ai3",
      "channel_type": "thermocouple",
      "thermocouple_type": "K",
      "unit": "degF",
      "description": "Cold side outlet temperature",
      "log": true,
      "decimals": 1,
      "group": "Temperatures"
    },
    "RTD_Ambient": {
      "name": "RTD_Ambient",
      "physical_channel": "cDAQ9189-1234Mod2/ai4",
      "channel_type": "rtd",
      "rtd_type": "Pt100",
      "rtd_wiring": "3-wire",
      "rtd_current": 0.001,
      "rtd_resistance": 100,
      "unit": "degF",
      "description": "Ambient room temperature",
      "log": true,
      "decimals": 2,
      "group": "Temperatures"
    },
    "FT_Hot": {
      "name": "FT_Hot",
      "physical_channel": "cDAQ9189-1234Mod2/ai0",
      "channel_type": "current_input",
      "current_range_ma": 20,
      "four_twenty_scaling": true,
      "unit": "GPM",
      "eng_units_min": 0,
      "eng_units_max": 50,
      "description": "Hot side flow rate",
      "alarm_enabled": true,
      "lo_limit": 5,
      "alarm_priority": "medium",
      "log": true,
      "decimals": 1,
      "group": "Flow"
    },
    "FT_Cold": {
      "name": "FT_Cold",
      "physical_channel": "cDAQ9189-1234Mod2/ai1",
      "channel_type": "current_input",
      "current_range_ma": 20,
      "four_twenty_scaling": true,
      "unit": "GPM",
      "eng_units_min": 0,
      "eng_units_max": 50,
      "description": "Cold side flow rate",
      "alarm_enabled": true,
      "lo_limit": 5,
      "alarm_priority": "medium",
      "log": true,
      "decimals": 1,
      "group": "Flow"
    },
    "PT_Hot": {
      "name": "PT_Hot",
      "physical_channel": "cDAQ9189-1234Mod3/ai0",
      "channel_type": "voltage_input",
      "voltage_range": 10,
      "terminal_config": "differential",
      "unit": "psig",
      "scale_type": "map",
      "pre_scaled_min": 0,
      "pre_scaled_max": 10,
      "scaled_min": 0,
      "scaled_max": 100,
      "description": "Hot side pressure",
      "log": true,
      "decimals": 1,
      "group": "Pressures"
    },
    "Hot_Pump": {
      "name": "Hot_Pump",
      "physical_channel": "cDAQ9189-1234Mod4/port0/line0",
      "channel_type": "digital_output",
      "description": "Hot side circulation pump",
      "default_state": false,
      "log": true,
      "group": "Control"
    },
    "Cold_Pump": {
      "name": "Cold_Pump",
      "physical_channel": "cDAQ9189-1234Mod4/port0/line1",
      "channel_type": "digital_output",
      "description": "Cold side circulation pump",
      "default_state": false,
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
  "userVariables": [
    {
      "id": "var-hot-total",
      "name": "hot_flow_total",
      "displayName": "Hot Side Total Flow",
      "variableType": "accumulator",
      "units": "gal",
      "value": 0,
      "persistent": true,
      "sourceChannel": "FT_Hot",
      "edgeType": "rate",
      "sourceRateUnit": "per_minute",
      "scaleFactor": 1,
      "resetMode": "test_session"
    },
    {
      "id": "var-test-time",
      "name": "test_duration",
      "displayName": "Test Duration",
      "variableType": "timer",
      "units": "s",
      "value": 0,
      "persistent": false,
      "resetMode": "test_session"
    }
  ],
  "recording": {
    "base_path": "./data",
    "file_prefix": "hx_test",
    "file_format": "csv",
    "include_timestamp": true,
    "include_date": true,
    "log_rate_hz": 1,
    "decimation": 1,
    "max_file_size_mb": 100,
    "max_file_duration_s": 3600,
    "split_files": true,
    "mode": "manual",
    "selected_channels": [],
    "include_scripts": true
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
            "id": "w-rec-status",
            "type": "recording_status",
            "x": 0, "y": 4, "w": 4, "h": 2,
            "label": "Recording"
          },
          {
            "id": "w-gauge-hot-in",
            "type": "gauge",
            "channel": "TC_Hot_In",
            "x": 4, "y": 1, "w": 4, "h": 3,
            "minValue": 50,
            "maxValue": 250,
            "showAlarmStatus": true
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
            "id": "w-start-btn",
            "type": "action_button",
            "x": 20, "y": 1, "w": 2, "h": 1,
            "label": "START",
            "buttonColor": "#22c55e",
            "buttonBehavior": "one_shot",
            "requireConfirmation": true,
            "buttonAction": {
              "type": "system_command",
              "command": "acquisition_start"
            }
          },
          {
            "id": "w-stop-btn",
            "type": "action_button",
            "x": 22, "y": 1, "w": 2, "h": 1,
            "label": "STOP",
            "buttonColor": "#ef4444",
            "buttonBehavior": "one_shot",
            "requireConfirmation": true,
            "buttonAction": {
              "type": "system_command",
              "command": "acquisition_stop"
            }
          },
          {
            "id": "w-toggle-hot-pump",
            "type": "toggle",
            "channel": "Hot_Pump",
            "x": 4, "y": 4, "w": 3, "h": 1,
            "onLabel": "HOT PUMP ON",
            "offLabel": "HOT PUMP OFF"
          },
          {
            "id": "w-toggle-cold-pump",
            "type": "toggle",
            "channel": "Cold_Pump",
            "x": 7, "y": 4, "w": 3, "h": 1,
            "onLabel": "COLD PUMP ON",
            "offLabel": "COLD PUMP OFF"
          },
          {
            "id": "w-flow-hot",
            "type": "numeric",
            "channel": "FT_Hot",
            "x": 10, "y": 4, "w": 3, "h": 1
          },
          {
            "id": "w-flow-cold",
            "type": "numeric",
            "channel": "FT_Cold",
            "x": 13, "y": 4, "w": 3, "h": 1
          },
          {
            "id": "w-ambient",
            "type": "numeric",
            "channel": "RTD_Ambient",
            "x": 16, "y": 4, "w": 3, "h": 1,
            "decimals": 2
          },
          {
            "id": "w-chart",
            "type": "chart",
            "channels": ["TC_Hot_In", "TC_Hot_Out", "TC_Cold_In", "TC_Cold_Out"],
            "x": 0, "y": 6, "w": 24, "h": 6,
            "timeRange": 300,
            "showGrid": true,
            "showLegend": true,
            "title": "Temperature Trends"
          }
        ]
      },
      {
        "id": "safety",
        "name": "Safety",
        "order": 1,
        "widgets": [
          {
            "id": "w-safety-title",
            "type": "title",
            "title": "Safety Overview",
            "x": 0, "y": 0, "w": 12, "h": 1,
            "style": { "fontSize": "large" }
          },
          {
            "id": "w-interlocks",
            "type": "interlock_status",
            "x": 0, "y": 1, "w": 6, "h": 4,
            "label": "Safety Interlocks"
          },
          {
            "id": "w-alarms",
            "type": "alarm_summary",
            "x": 6, "y": 1, "w": 6, "h": 4,
            "label": "Active Alarms",
            "maxItems": 10,
            "showAckButton": true
          },
          {
            "id": "w-latch",
            "type": "latch_switch",
            "x": 12, "y": 1, "w": 2, "h": 2,
            "label": "Safety Reset"
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
- [ ] Channel TAGs use only alphanumeric, underscore, and dash characters
- [ ] Channel `name` field matches the dictionary key
- [ ] Physical channels are properly formatted
- [ ] Field name is `unit` (singular), NOT `units`
- [ ] Field name is `decimals`, NOT `precision`
- [ ] Field name is `description` for human-readable text, NOT `display_name`
- [ ] Field name is `default_state` for digital outputs, NOT `initial_value`
- [ ] RTD uses `rtd_type` (`"Pt100"`, `"Pt500"`, `"Pt1000"`, `"custom"`), `rtd_wiring` (`"2-wire"`, `"3-wire"`, `"4-wire"`), `rtd_current`, `rtd_resistance`
- [ ] Voltage inputs use `scale_type` with `scale_slope`/`scale_offset` (linear) or `pre_scaled_min`/`pre_scaled_max`/`scaled_min`/`scaled_max` (map), NOT `scale_min`/`scale_max`
- [ ] Terminal config uses lowercase: `"differential"`, `"rse"`, `"nrse"`
- [ ] All widget IDs are unique
- [ ] Widgets reference valid channel TAGs
- [ ] Safety actions reference valid output channels
- [ ] Interlocks reference valid actions
- [ ] Page IDs are unique lowercase identifiers
- [ ] Widget positions don't overlap excessively
- [ ] Chart channels arrays don't exceed 8 items
- [ ] Gauge widgets use `showAlarmStatus`, NOT `showLimits` or `colorZones`
- [ ] LED widgets use `invert`, NOT `invertThreshold`
- [ ] Setpoint widgets use `setpointStyle`, NOT `showSlider`
- [ ] No `script`, `calculated`, or `virtual` channel types are used
- [ ] Calculated values use Python scripts with `publish()`, not channels
