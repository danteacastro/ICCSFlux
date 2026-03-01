# AI Structured Text Generation Guide

Reference for AI agents generating IEC 61131-3 Structured Text (ST) code for CODESYS on groov EPIC.

## Architecture

```
┌────────────────────────┐     ┌──────────────────────────┐
│  CODESYS Runtime (ST)  │◄───►│  Python Companion        │
│                        │     │                          │
│  FB_PID_Loop     1 ms  │ M   │  Scripts, alarms, MQTT   │
│  FB_Interlock    1 ms  │ o   │  Audit trail, sequences  │
│  FB_SafeState    1 ms  │ d   │                          │
│  Main program          │ b   │  Reads PV/CV/status      │
│                        │ u   │  Writes SP/tuning/cmds   │
│  Direct I/O access     │ s   │                          │
│  (GRV modules)         │     │  Falls back to Python    │
│                        │ T   │  PID if CODESYS offline  │
│                        │ C   │                          │
│                        │ P   │                          │
└────────────────────────┘     └──────────────────────────┘
       localhost:502
```

## File Structure

| File | Purpose |
|------|---------|
| `FB_PID_Loop.st` | PID controller function block |
| `FB_Interlock.st` | IEC 61511 safety interlock function block |
| `FB_SafeState.st` | Global safe state manager |
| `GVL_Registers.st` | Global Variable List — Modbus register mapping |
| `Main.st` | Main program — generated per project |

## Code Generation

Use `st_codegen.py` to generate ST from a project config:

```python
from services.opto22_node.codesys.st_codegen import (
    STCodeGenerator, PIDLoopConfig, InterlockConfig, ChannelInfo
)

codegen = STCodeGenerator(project_name="My Project")

# Add PID loops
codegen.add_pid_loops([
    {'id': 'PID_Zone1', 'name': 'Zone 1 Temp', 'pv_channel': 'TC_Zone1',
     'cv_channel': 'Heater_Zone1', 'kp': 2.0, 'ki': 0.05, 'kd': 0.0,
     'output_min': 0.0, 'output_max': 100.0}
])

# Add interlocks
codegen.add_interlocks([
    {'id': 'ILK_OverTemp', 'name': 'Over Temperature',
     'conditions': [{'type': 'channel_value', 'channel': 'TC_Zone1',
                     'operator': '<', 'value': 200.0}],
     'controls': [{'channel': 'Heater_Zone1'}]}
])

# Add channels
codegen.add_channels({
    'TC_Zone1': {'channel_type': 'thermocouple', 'groov_module_index': 1,
                 'groov_channel_index': 0, 'description': 'Zone 1 TC'},
    'Heater_Zone1': {'channel_type': 'voltage_output', 'groov_module_index': 2,
                     'groov_channel_index': 0, 'safe_value': 0.0}
})

# Generate files
files = codegen.generate()
# files = {'Main.st': '...', 'FB_PID_Loop.st': '...', ...}

# Or write to disk
codegen.generate_to_dir('/path/to/output/')
```

## Modbus Register Map

Communication between CODESYS and Python uses Modbus TCP on `localhost:502`.

### Holding Registers (Python → CODESYS)

| Range | Spacing | Purpose |
|-------|---------|---------|
| 40001-40100 | 2 regs/loop | PID setpoints (float32) |
| 40101-40250 | 6 regs/loop | PID tuning: Kp, Ki, Kd (float32 each) |
| 40251-40350 | 2 regs/ilk | Interlock commands |
| 40351-40450 | 2 regs/out | Output override values (float32) |
| 40451-40460 | 1 reg each | System commands |

### Input Registers (CODESYS → Python)

| Range | Spacing | Purpose |
|-------|---------|---------|
| 30001-30100 | 2 regs/loop | PID CV outputs (float32) |
| 30101-30300 | 2 regs/ch | Process values (float32) |
| 30301-30400 | 2 regs/ilk | Interlock status + trip count |
| 30401-30410 | 1-2 regs | System status |

### Coils (Python → CODESYS, single bits)

| Range | Purpose |
|-------|---------|
| 00001-00050 | PID loop enable flags |
| 00051-00100 | PID manual mode flags |
| 00101-00150 | Interlock arm commands |
| 00151-00200 | Interlock bypass flags |

### Discrete Inputs (CODESYS → Python, single bits)

| Range | Purpose |
|-------|---------|
| 10001-10050 | Interlock tripped flags |
| 10051-10100 | PID loop active flags |
| 10101-10110 | System health flags |

### System Command Registers (from 40451)

| Offset | Name | Values |
|--------|------|--------|
| +0 | E-Stop | 0=normal, 1=E-stop |
| +1 | Mode | 0=auto, 1=manual, 2=safe |
| +2 | Heartbeat | Counter (Python increments, CODESYS watches) |
| +3 | Acquire | 0=stop, 1=run |
| +4 | Config Version | Lower 16 bits of config hash |

### System Status Registers (from 30401)

| Offset | Name | Type |
|--------|------|------|
| +0 | Scan Time | uint32 (2 regs, microseconds) |
| +2 | Error Count | uint16 |
| +3 | Watchdog | uint16 (increments each scan) |
| +4 | PID Count | uint16 |
| +5 | Interlock Count | uint16 |

## FB_PID_Loop

### Interface

```
FUNCTION_BLOCK FB_PID_Loop
VAR_INPUT
    PV          : REAL;          (* Process Variable *)
    SP          : REAL;          (* Setpoint *)
    Kp          : REAL := 1.0;   (* Proportional gain *)
    Ki          : REAL := 0.1;   (* Integral gain (per second) *)
    Kd          : REAL := 0.0;   (* Derivative gain *)
    dt          : REAL := 0.001; (* Scan cycle time in seconds *)
    OutMin      : REAL := 0.0;
    OutMax      : REAL := 100.0;
    Enable      : BOOL := TRUE;
    ManualMode  : BOOL := FALSE;
    ManualOutput: REAL := 0.0;
    ReverseAction: BOOL := FALSE;
    Deadband    : REAL := 0.0;
END_VAR
VAR_OUTPUT
    CV          : REAL;          (* Control output *)
    Error       : REAL;
    PTerm, ITerm, DTerm : REAL;
    Active      : BOOL;
END_VAR
```

### Algorithm

1. If disabled → return (Active := FALSE)
2. If manual → CV := ManualOutput (clamped), save state for bumpless
3. Bumpless transfer on manual→auto: integral := lastOutput
4. Error := SP - PV (negated if reverse action)
5. Deadband: if |Error| < Deadband → Error := 0
6. P term := Kp × Error
7. I term: accumulate Ki × Error × dt with anti-windup clamping
8. D term: derivative-on-PV = Kd × (-(PV - lastPV) / dt)
9. CV := P + I + D, clamped to [OutMin, OutMax]

### Usage in Main

```
pid_Zone1(
    PV     := GVL_Registers.PV_TC_Zone1,
    SP     := GVL_Registers.SP_PID_Zone1,
    Kp     := GVL_Registers.Kp_PID_Zone1,
    Ki     := GVL_Registers.Ki_PID_Zone1,
    Kd     := GVL_Registers.Kd_PID_Zone1,
    dt     := 0.001,  (* 1 ms task cycle *)
    OutMin := 0.0,
    OutMax := 100.0,
    Enable := TRUE
);
GVL_Registers.CV_PID_Zone1 := pid_Zone1.CV;
```

## FB_Interlock

### Interface

```
FUNCTION_BLOCK FB_Interlock
VAR_INPUT
    ConditionOK     : BOOL;   (* TRUE = safe, FALSE = trip condition *)
    ArmCommand      : BOOL;   (* Rising edge arms *)
    DisarmCommand   : BOOL;   (* Rising edge disarms *)
    ResetCommand    : BOOL;   (* Rising edge resets trip *)
    BypassActive    : BOOL;   (* Suppress tripping *)
END_VAR
VAR_OUTPUT
    State           : INT;    (* 0=SAFE, 1=ARMED, 2=TRIPPED *)
    Tripped         : BOOL;
    Armed           : BOOL;
    TripCount       : DINT;
    DemandCount     : DINT;
    ApplySafeState  : BOOL;   (* TRUE = set outputs to safe values *)
END_VAR
```

### State Machine (IEC 61511)

```
SAFE (0) ──arm──► ARMED (1) ──condition fail──► TRIPPED (2)
  ▲                  │                              │
  │                  │                              │
  └──disarm──────────┘                              │
  └──disarm─────────────────────────────────────────┘
                     TRIPPED ──reset (if OK)──► ARMED
```

- **SAFE**: Not monitoring. No safe state applied.
- **ARMED**: Monitoring conditions. Trips if ConditionOK goes FALSE (unless bypassed).
- **TRIPPED**: Safe state applied to controlled outputs. Reset returns to ARMED.
- **Bypass**: Suppresses tripping but does NOT change state.
- **Demand count**: Incremented each time condition transitions TRUE→FALSE.

### Condition Expression Generation

Python interlock conditions are converted to ST boolean expressions:

| Python Condition | ST Expression |
|-----------------|---------------|
| `channel_value`, `TC_Zone1`, `<`, `200` | `(GVL_Registers.PV_TC_Zone1 < 200.0)` |
| `digital_input`, `DI_Door`, expected=True | `(GVL_Registers.PV_DI_Door > 0.5)` |
| `alarm_active`, `mqtt_connected` | `TRUE` (evaluated in Python layer only) |

Multiple conditions are joined with AND (all must pass for "safe").

## FB_SafeState

```
FUNCTION_BLOCK FB_SafeState
VAR_INPUT
    ApplyAll    : BOOL;    (* Apply safe state to all outputs *)
    EStopActive : BOOL;    (* Emergency stop active *)
END_VAR
VAR_OUTPUT
    SafeStateActive : BOOL; (* TRUE if any safe state is active *)
END_VAR
```

SafeStateActive is TRUE when ApplyAll OR EStopActive. Individual interlock tripping is handled via `ilk_*.ApplySafeState` in the Main program.

## GVL_Registers

The Global Variable List maps CODESYS variables to Modbus registers using AT declarations:

```
{VAR_GLOBAL}
    (* PID Setpoints — Python writes via Modbus holding registers *)
    SP_PID_Zone1    AT %QW0  : REAL;     (* [40001] *)
    SP_PID_Zone2    AT %QW4  : REAL;     (* [40003] *)

    (* PID Tuning — Python writes *)
    Kp_PID_Zone1    AT %QW200  : REAL;   (* [40101] *)
    Ki_PID_Zone1    AT %QW204  : REAL;   (* [40103] *)
    Kd_PID_Zone1    AT %QW208  : REAL;   (* [40105] *)

    (* PID Outputs — CODESYS writes, Python reads via input registers *)
    CV_PID_Zone1    AT %IW0  : REAL;     (* [30001] *)

    (* Process Values — CODESYS writes *)
    PV_TC_Zone1     AT %IW200  : REAL;   (* [30101] *)

    (* Interlock Commands — coils *)
    Arm_ILK_OverTemp    AT %QX12.4  : BOOL;  (* [coil 101] *)
    Bypass_ILK_OverTemp AT %QX18.6  : BOOL;  (* [coil 151] *)

    (* Interlock Status — input registers *)
    State_ILK_OverTemp  AT %IW600  : INT;    (* [30301] *)

    (* System Commands *)
    SYS_EStop       AT %QW900  : INT;    (* E-stop *)
    SYS_Heartbeat   AT %QW904  : INT;    (* Python heartbeat *)
END_VAR
```

AT offsets are calculated from the register base addresses by `st_codegen.py`. The formula:
- Holding register offset: `(address - 40001) * 2` bytes → `%QW` word offset
- Input register offset: `(address - 30001) * 2` bytes → `%IW` word offset
- Coil byte/bit: `(coil - 1) // 8` and `(coil - 1) % 8` → `%QX byte.bit`

## Main Program Structure

The Main program follows a fixed execution order every scan (1 ms):

```
1. READ I/O        — Copy groov module values to GVL_Registers.PV_*
2. PID EXECUTION   — Run all FB_PID_Loop instances
3. INTERLOCKS       — Run all FB_Interlock instances
4. SAFE STATE       — Determine which outputs are blocked
5. WRITE OUTPUTS   — Write to groov modules (safe value if blocked)
6. HEARTBEAT       — Python watchdog (5 seconds timeout)
7. SYSTEM STATUS   — Update scan time, watchdog counter
```

### Output Blocking Logic

```
blocked_Heater_Zone1 := safeState.SafeStateActive
    OR ilk_ILK_OverTemp.ApplySafeState;

IF blocked_Heater_Zone1 THEN
    GRV_EPIC_PR1.Slot02.Ch00 := 0.0;    (* Safe value *)
ELSE
    GRV_EPIC_PR1.Slot02.Ch00 := GVL_Registers.CV_PID_Zone1;
END_IF
```

### Python Heartbeat Watchdog

```
(* If Python stops incrementing heartbeat for 5 seconds, go safe *)
IF GVL_Registers.SYS_Heartbeat <> prevHeartbeat THEN
    prevHeartbeat := GVL_Registers.SYS_Heartbeat;
    heartbeatTimeout := 0;
ELSE
    heartbeatTimeout := heartbeatTimeout + 1;
    IF heartbeatTimeout > 5000 THEN  (* 5000 × 1 ms = 5 s *)
        safeState.ApplyAll := TRUE;
    END_IF
END_IF
```

## Example: 3-Zone Heater System

### Project Config

```json
{
  "pidLoops": {
    "loops": [
      {"id": "PID_Z1", "name": "Zone 1", "pv_channel": "TC_Z1",
       "cv_channel": "HTR_Z1", "kp": 3.0, "ki": 0.02, "output_max": 100.0},
      {"id": "PID_Z2", "name": "Zone 2", "pv_channel": "TC_Z2",
       "cv_channel": "HTR_Z2", "kp": 3.0, "ki": 0.02, "output_max": 100.0},
      {"id": "PID_Z3", "name": "Zone 3", "pv_channel": "TC_Z3",
       "cv_channel": "HTR_Z3", "kp": 3.0, "ki": 0.02, "output_max": 100.0}
    ]
  }
}
```

### Generated Main.st (excerpt)

```
PROGRAM Main
VAR
    pid_PID_Z1 : FB_PID_Loop;
    pid_PID_Z2 : FB_PID_Loop;
    pid_PID_Z3 : FB_PID_Loop;
    ilk_ILK_OverTemp : FB_Interlock;
    safeState : FB_SafeState;
END_VAR

(* 1. READ I/O *)
GVL_Registers.PV_TC_Z1 := GRV_EPIC_PR1.Slot01.Ch00;
GVL_Registers.PV_TC_Z2 := GRV_EPIC_PR1.Slot01.Ch01;
GVL_Registers.PV_TC_Z3 := GRV_EPIC_PR1.Slot01.Ch02;

(* 2. PID EXECUTION *)
pid_PID_Z1(PV := GVL_Registers.PV_TC_Z1, SP := GVL_Registers.SP_PID_Z1,
           Kp := GVL_Registers.Kp_PID_Z1, Ki := GVL_Registers.Ki_PID_Z1,
           Kd := GVL_Registers.Kd_PID_Z1, dt := 0.001,
           OutMin := 0.0, OutMax := 100.0);
GVL_Registers.CV_PID_Z1 := pid_PID_Z1.CV;
(* ...repeat for Z2, Z3... *)

(* 3. INTERLOCKS *)
ilk_ILK_OverTemp(
    ConditionOK := (GVL_Registers.PV_TC_Z1 < 250.0)
                   AND (GVL_Registers.PV_TC_Z2 < 250.0)
                   AND (GVL_Registers.PV_TC_Z3 < 250.0),
    ArmCommand := GVL_Registers.Arm_ILK_OverTemp
);

(* 4-5. OUTPUT with blocking *)
IF ilk_ILK_OverTemp.ApplySafeState THEN
    GRV_EPIC_PR1.Slot02.Ch00 := 0.0;
ELSE
    GRV_EPIC_PR1.Slot02.Ch00 := GVL_Registers.CV_PID_Z1;
END_IF
```

## Conventions

1. **Naming**: FB_ prefix for function blocks, GVL_ for global variable lists, PV_ for process values, SP_ for setpoints, CV_ for control variables, ILK_ for interlocks
2. **Types**: Use REAL for analog values, INT for state enums, BOOL for flags, DINT for counters
3. **Comments**: `(* comment *)` syntax. Include register addresses in comments for traceability.
4. **Safe values**: Every output channel must have a defined safe value (typically 0.0 for analog, FALSE for digital)
5. **Scan time**: 1 ms task cycle assumed. The `dt` parameter is always `0.001`.
6. **Register mapping**: Always use AT declarations in GVL to bind to Modbus. Never hard-code register addresses in logic.
7. **Jinja2 templates**: All generated code uses `.st.j2` templates in `services/opto22_node/codesys/templates/`

## CODESYS IDE Import

Generated ST files are not deployed automatically — CODESYS programs must be compiled and downloaded via the CODESYS IDE:

1. Open CODESYS IDE → create new Standard Project for groov EPIC
2. Import `FB_PID_Loop.st`, `FB_Interlock.st`, `FB_SafeState.st` as POUs
3. Import `GVL_Registers.st` as a Global Variable List
4. Replace the default `Main` program with `Main.st`
5. Add a Modbus TCP Slave device and map GVL variables to I/O
6. Set the task cycle to 1 ms (Priority 0)
7. Build → Download → Run

This is a **one-time structural setup**. Runtime parameter changes (setpoints, tuning, arm/bypass) go through Modbus registers without recompilation.

## Debugging

### From Python

```python
# Read CODESYS health
bridge = codesys_bridge
health = bridge.get_health()
# {'available': True, 'scan_time_us': 450, 'consecutive_errors': 0, ...}

# Read all PV values
pvs = bridge.read_process_values()
# {'TC_Z1': 185.2, 'TC_Z2': 190.1, 'TC_Z3': 188.7}

# Read PID outputs
cvs = bridge.read_pid_outputs()
# {'PID_Z1': 42.5, 'PID_Z2': 38.1, 'PID_Z3': 40.0}

# Read interlock status
ilks = bridge.read_interlock_status()
# {'ILK_OverTemp': {'state': 1, 'trip_count': 0}}
```

### From CODESYS IDE

- Online mode → watch variables in real-time
- Trace recording for millisecond-level analysis
- Force values for testing (bypasses Modbus writes)

### From MQTT Dashboard

All CODESYS values are published to MQTT by the Python companion at 4 Hz:
- `{base}/values` — includes all PV and CV values
- `{base}/status` — includes `codesys.available`, `codesys.health`
