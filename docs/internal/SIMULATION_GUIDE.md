# Boiler Combustion Simulation - Engineer's Guide

## Overview

The **Boiler_Simulation_Debug** project is a simulated boiler/combustion system with 56 channels across 8 NI module types. No real hardware is needed — the DAQ service generates realistic data for all channels automatically.

Use this project to:
- Build and test P&ID diagrams (pipe drawing, symbol placement, channel binding)
- Configure dashboard widgets and verify channel type filtering
- Test tag renaming and verify propagation to widgets, alarms, and backend
- Evaluate alarm behavior with simulated process drift
- Familiarize yourself with the NISystem dashboard before working with real hardware

---

## Getting Started

1. Open the dashboard in your browser (typically `http://localhost:8080`)
2. Go to **Configuration** tab
3. Load the project: **Boiler_Simulation_Debug**
4. Click **START** to begin acquisition
5. Switch to the **Data** tab — you should see all 56 channels updating with simulated values

---

## ISA Tag Naming Convention

All tags follow ISA-5.1 instrument identification standards used in chemical and process engineering:

### Tag Format: `XX_NNN`

The **first letters** identify the measurement or function:

| Prefix | Meaning | Example |
|--------|---------|---------|
| **TT** | Temperature Transmitter | TT_101 = furnace gas temperature |
| **TE** | Temperature Element (RTD sensor) | TE_201 = bearing temperature |
| **PT** | Pressure Transmitter | PT_302 = steam header pressure |
| **FT** | Flow Transmitter | FT_401 = natural gas flow rate |
| **LT** | Level Transmitter | LT_308 = drum water level |
| **AT** | Analyzer Transmitter | AT_306 = O2 in flue gas |
| **XS** | Safety Switch (discrete) | XS_501 = E-Stop status |
| **ZS** | Position Switch | ZS_509 = gas valve closed position |
| **XY** | Solenoid / Discrete Output | XY_601 = main gas shutoff valve |
| **FCV** | Flow Control Valve (analog output) | FCV_701 = gas control valve position |
| **TCV** | Temperature Control Valve | TCV_704 = economizer bypass valve |

### Number Ranges

The hundreds digit indicates the channel type / NI module:

| Range | Channel Type | NI Module | Slot |
|-------|-------------|-----------|------|
| 100s | Thermocouple | NI 9213 | Mod5 |
| 200s | RTD | NI 9217 | Mod6 |
| 300s | Voltage Input (0-10V) | NI 9205 | Mod1 |
| 400s | Current Input (4-20mA) | NI 9208 | Mod2 |
| 500s | Digital Input (24V) | NI 9425 | Mod3 |
| 600s | Digital Output (24V) | NI 9472 | Mod4 |
| 700s | Voltage Output (0-10V) | NI 9264 | Mod7 |
| 800s | Current Output (4-20mA) | NI 9265 | Mod8 |

---

## Process Groups

Channels are organized by process area:

### Combustion
| Tag | Type | Description |
|-----|------|-------------|
| TT_101 | TC | Furnace gas temperature (K-type, alarm at 800/950 degC) |
| PT_301 | VI | Furnace draft pressure (-5 to +5 inH2O) |
| XY_603 | DO | Ignition transformer on/off |

### Fuel System
| Tag | Type | Description |
|-----|------|-------------|
| PT_304 | VI | Natural gas supply pressure (0-15 psig, alarm low 2/3) |
| FT_401 | CI | Natural gas flow rate (0-10000 SCFH) |
| ZS_509 | DI | Gas shutoff valve - closed position |
| ZS_510 | DI | Gas shutoff valve - open position |
| XY_601 | DO | Main gas shutoff valve command |
| XY_602 | DO | Pilot gas shutoff valve command |
| FCV_701 | VO | Gas control valve position (0-100%) |

### Air System
| Tag | Type | Description |
|-----|------|-------------|
| TT_106 | TC | Combustion air preheat temperature |
| FT_305 | VI | Combustion air flow (0-5000 SCFM) |
| PT_404 | CI | Combustion air pressure (0-30 inH2O) |
| ZS_511 | DI | FD (Forced Draft) fan running status |
| ZS_515 | DI | Damper limit - open |
| ZS_516 | DI | Damper limit - closed |
| XS_508 | DI | Combustion air flow switch (safety) |
| XY_604 | DO | FD fan start/stop command |
| FCV_702 | VO | Air damper position (0-100%) |

### Exhaust
| Tag | Type | Description |
|-----|------|-------------|
| TT_102 | TC | Flue gas exit temperature (alarm at 500/600 degC) |
| TT_105 | TC | Stack exhaust temperature (alarm at 250/300 degC) |
| AT_306 | VI | O2 analyzer - flue gas (0-25%, alarm low 2%, high 8%) |
| AT_307 | VI | CO analyzer - flue gas (0-1000 ppm, alarm 200/500) |
| ZS_512 | DI | ID (Induced Draft) fan running status |
| XY_605 | DO | ID fan start/stop command |

### Water Loop
| Tag | Type | Description |
|-----|------|-------------|
| TT_103 | TC | Economizer inlet water temperature |
| TT_104 | TC | Economizer outlet water temperature |
| TT_108 | TC | Feedwater inlet temperature |
| PT_303 | VI | Feedwater pressure (0-200 psig) |
| LT_308 | VI | Drum water level (0-100%, alarm low 20/30%, high 80/90%) |
| FT_402 | CI | Feedwater flow rate (0-500 GPM) |
| FT_405 | CI | Blowdown flow rate (0-50 GPM) |
| PT_406 | CI | Condensate return pressure (0-100 psig) |
| ZS_513 | DI | Boiler feed pump running status |
| ZS_514 | DI | Blowdown valve position |
| XY_606 | DO | Boiler feed pump start/stop command |
| XY_607 | DO | Blowdown valve open/close command |
| FCV_703 | VO | Feedwater control valve (0-100%) |
| TCV_704 | VO | Economizer bypass valve (0-100%) |
| FCV_802 | CO | Blowdown rate control (0-100%) |

### Steam
| Tag | Type | Description |
|-----|------|-------------|
| TT_107 | TC | Superheater outlet temperature (alarm at 450/500 degC) |
| PT_302 | VI | Steam header pressure (0-300 psig, alarm 250/280) |
| FT_403 | CI | Steam flow rate (0-50000 lb/hr) |
| FCV_801 | CO | Steam pressure control valve (0-100%) |

### Safety
| Tag | Type | Description |
|-----|------|-------------|
| XS_501 | DI | E-Stop status (1=OK, 0=tripped) |
| XS_502 | DI | Flame scanner - main burner |
| XS_503 | DI | Flame scanner - pilot |
| XS_504 | DI | High steam pressure switch |
| XS_505 | DI | Low water cutoff |
| XS_506 | DI | High gas pressure switch |
| XS_507 | DI | Low gas pressure switch |
| XY_608 | DO | Alarm horn command |

### Equipment
| Tag | Type | Description |
|-----|------|-------------|
| TE_201 | RTD | Bearing temperature - ID fan |
| TE_202 | RTD | Bearing temperature - FD fan |
| TE_203 | RTD | Motor winding temp - boiler feed pump (alarm 80/100 degC) |

### Environment
| Tag | Type | Description |
|-----|------|-------------|
| TE_204 | RTD | Ambient / room temperature |

---

## Channel Type Legend

When configuring widgets, the channel dropdown shows type abbreviations:

| Abbreviation | Full Name | Widget Compatibility |
|-------------|-----------|---------------------|
| **DI** | Digital Input | LED, Numeric, Chart, Value Table |
| **DO** | Digital Output | Toggle Switch only |
| **VI** | Voltage Input | Numeric, Gauge, Chart, Sparkline, Bar Graph, LED |
| **VO** | Voltage Output | Setpoint only |
| **CI** | Current Input | Numeric, Gauge, Chart, Sparkline, Bar Graph, LED |
| **CO** | Current Output | Setpoint only |
| **TC** | Thermocouple | Numeric, Gauge, Chart, Sparkline, Bar Graph, LED |
| **RTD** | RTD Sensor | Numeric, Gauge, Chart, Sparkline, Bar Graph, LED |

---

## Scaling

### Voltage Inputs (VI) — Map Scaling
Voltage inputs use **map scaling** to convert raw 0-10V signals to engineering units:

| Tag | Raw Range | Scaled Range | Unit |
|-----|-----------|-------------|------|
| PT_301 | 0-10V | -5 to +5 | inH2O |
| PT_302 | 0-10V | 0-300 | psig |
| PT_303 | 0-10V | 0-200 | psig |
| PT_304 | 0-10V | 0-15 | psig |
| FT_305 | 0-10V | 0-5000 | SCFM |
| AT_306 | 0-10V | 0-25 | % O2 |
| AT_307 | 0-10V | 0-1000 | ppm CO |
| LT_308 | 0-10V | 0-100 | % level |

### Current Inputs (CI) — 4-20mA Scaling
Current inputs use **4-20mA scaling** where 4mA = min and 20mA = max:

| Tag | 4mA = | 20mA = | Unit |
|-----|-------|--------|------|
| FT_401 | 0 | 10000 | SCFH |
| FT_402 | 0 | 500 | GPM |
| FT_403 | 0 | 50000 | lb/hr |
| PT_404 | 0 | 30 | inH2O |
| FT_405 | 0 | 50 | GPM |
| PT_406 | 0 | 100 | psig |

### Voltage/Current Outputs
Output channels also have scaling so that 0-10V (or 4-20mA) maps to 0-100% valve position.

---

## Pre-Configured Alarms

These channels have alarm thresholds set. In simulation mode, values will drift and may trigger alarms:

| Tag | Low Limit | Low Warning | High Warning | High Limit | Unit |
|-----|-----------|-------------|-------------|------------|------|
| TT_101 | — | — | 800 | 950 | degC |
| TT_102 | — | — | 500 | 600 | degC |
| TT_105 | — | — | 250 | 300 | degC |
| TT_107 | — | — | 450 | 500 | degC |
| TE_203 | — | — | 80 | 100 | degC |
| PT_302 | — | — | 250 | 280 | psig |
| PT_304 | 2 | 3 | — | — | psig |
| AT_306 | — | 2 | 8 | — | % |
| AT_307 | — | — | 200 | 500 | ppm |
| LT_308 | 20 | 30 | 80 | 90 | % |

---

## Testing Checklist

Use this checklist to verify system behavior:

### Widget Configuration
- [ ] Add a **Setpoint** widget — dropdown should ONLY show: FCV_701, FCV_702, FCV_703, TCV_704, FCV_801, FCV_802
- [ ] Add a **Toggle** widget — dropdown should ONLY show: XY_601 through XY_608
- [ ] Add a **Gauge** widget — dropdown should show all analog channels (no DI/DO)
- [ ] Add a **Numeric** display — dropdown should show ALL channels
- [ ] Add an **LED** indicator — dropdown should show ALL channels
- [ ] Verify dropdown shows type labels: `TT_101 (TC · degC)`, `XS_501 (DI)`, `FCV_701 (VO · %)`

### P&ID Canvas
- [ ] Place a pump symbol and bind it to ZS_513 (boiler feed pump running)
- [ ] Place a valve symbol and bind it to FCV_701 (gas control valve)
- [ ] Draw pipes connecting symbols
- [ ] Open a faceplate on a bound symbol — verify live value display
- [ ] Test pipe path types: polyline, bezier, orthogonal

### Tag Renaming
- [ ] Rename TT_101 to TC_FURNACE_GAS
- [ ] Verify: any widget bound to TT_101 now shows TC_FURNACE_GAS
- [ ] Verify: any P&ID symbol bound to TT_101 updates
- [ ] Verify: alarm config still applies to the renamed channel
- [ ] Rename back to TT_101 to restore original state

### Alarms
- [ ] Wait for simulated values to drift into alarm range
- [ ] Verify alarm indicators appear on the dashboard
- [ ] Check that alarm summary widget shows active alarms

### Recording
- [ ] Start a recording with selected channels
- [ ] Verify CSV file is created with correct column headers
- [ ] Stop recording and check file integrity

### Data Flow
- [ ] Confirm all 56 channels show values in the Data tab
- [ ] Verify thermocouples show realistic temperature drift (~25 degC ambient)
- [ ] Verify 4-20mA channels show values in engineering units (not raw mA)
- [ ] Verify digital inputs show 0 or 1
- [ ] Toggle a digital output and confirm state change
- [ ] Set a voltage output via setpoint widget and confirm value updates

---

## Simulator Behavior

The simulation generates realistic data patterns:

| Channel Type | Behavior |
|-------------|----------|
| **Thermocouple** | Starts at ~25 degC (ambient), drifts with Gaussian noise and sine wave oscillation. Slow thermal response. |
| **RTD** | Similar to thermocouple but more stable (less noise). |
| **Voltage Input** | Varies around midpoint of scaled range with periodic oscillation. |
| **Current Input** | Simulates 4-20mA loop with slow trending and pump-cycle periodicity. |
| **Digital Input** | Safety inputs (XS_*) default to 1 (safe). Others may toggle randomly. |
| **Digital Output** | Holds last written value (0 or 1). Default is 0 (off). |
| **Voltage Output** | Holds last written value. Set via Setpoint widget. |
| **Current Output** | Holds last written value. Set via Setpoint widget. |

To change a simulated temperature target, use the DAQ service's internal API (advanced usage — not needed for basic testing).
