# Channel-Type Test Coverage & Validation Guide

## Purpose

This document tracks what channel-type-specific behavior is **already tested** by the cRIO acquisition test suite, and what **must be validated** when new module types are plugged in. The pipeline (MQTT commands, data delivery, alarms, interlocks, scripts) is module-agnostic and covered by the existing 70 tests. This document focuses on the hardware-specific code paths in `hardware.py` that differ per channel type.

---

## Current Test Hardware (cRIO-9056)

| Slot | Module | Type | Channels | Tested |
|------|--------|------|----------|--------|
| Mod1 | NI 9202 | 16 AI (voltage) | AI_Mod1_ch00–15 | YES |
| Mod2 | NI 9264 | 16 AO (voltage) | AO_Mod2_ch00–15 | YES |
| Mod3 | NI 9425 | 32 DI | DI_Mod3_ch00–31 | YES |
| Mod4 | NI 9472 | 8 DO | DO_Mod4_ch00–07 | YES |
| Mod5 | NI 9213 | 16 TC | TC_Mod5_ch00–15 | YES |
| Mod6 | NI 9266 | 8 CO (current out) | CO_Mod6_ch00–07 | YES |

---

## What the Existing 70 Tests Already Cover

### Voltage AI (NI 9202) — FULLY TESTED

| Behavior | Test | Group |
|----------|------|-------|
| Values within ±10.5V range | `test_ai_values_in_range` | 3 |
| AO→AI loopback accuracy at -5V, -2.5V, 0V, 2.5V, 5V, 9V | `test_ao_ai_single_channel_accuracy` | 9 |
| All 16 channels respond (wiring completeness) | `test_ao_ai_all_channels` | 9 |
| Monotonic ramp -5V→+5V in 1V steps | `test_ao_ai_ramp` | 9 |
| Step response settling < 2s | `test_ao_ai_step_response` | 9 |
| Zero offset baseline | `test_ao_zero_baseline` | 9 |
| 4 Hz sustained scan rate over 30s | `test_sustained_scan_rate_30s` | 2 |
| No NaN on connected channels | `test_values_are_numeric` | 2 |

### Voltage AO (NI 9264) — FULLY TESTED

| Behavior | Test | Group |
|----------|------|-------|
| MQTT write → hardware output | `test_output_write_during_acquisition` | 5 |
| All 16 channels writable | `test_ao_ai_all_channels` | 9 |
| Voltage accuracy ±0.5V | `test_ao_ai_single_channel_accuracy` | 9 |
| Range validation (±10V) | Implicit in loopback tests | 9 |

### Digital Input (NI 9425) — FULLY TESTED

| Behavior | Test | Group |
|----------|------|-------|
| Binary values (exactly 0.0 or 1.0) | `test_di_values_binary` | 3 |
| Timestamps advancing (not frozen) | `test_di_timestamps_advancing` | 3 |
| Change detection fallback to polling | `test_no_change_detection_errors` | 4 |
| DO→DI loopback LOW/HIGH | `test_loopback_set_low/high` | 8 |
| Toggle cycle latency (<3s per transition) | `test_loopback_toggle_cycle` | 8 |
| Rapid toggle (20 transitions at 50ms) | `test_loopback_rapid_toggle` | 8 |

### Digital Output (NI 9472) — FULLY TESTED

| Behavior | Test | Group |
|----------|------|-------|
| MQTT write → physical output | `test_loopback_set_high` | 8 |
| 24V relay toggle (4 channels) | `test_relay_toggle` | 8 |
| Safety interlock trip → relay fires | `test_crio_trip_fires_relay` | 10 |
| Safe state output on trip | `test_crio_trip_fires_relay` | 10 |
| Cleanup (all DOs to 0) | `test_cleanup_crio_interlock` | 10 |

### Thermocouple (NI 9213) — PARTIALLY TESTED

| Behavior | Test | Group | Status |
|----------|------|-------|--------|
| ch0 (wired TC) reads -50°C to 1800°C | `test_tc_values_in_range` | 3 | TESTED |
| Open TC (ch1-15) reads NaN or ~2300°C | `test_tc_values_in_range` | 3 | TESTED |
| Reader has read_count > 0 | `test_tc_reader_active` | 3 | TESTED |
| On-demand (slow) read mode | Implicit (no errors in log) | 4 | TESTED |
| Scan rate ≥ 1 Hz (slow module) | `test_sustained_scan_rate_30s` | 2 | TESTED |
| K-type default | — | — | TESTED (project uses K) |
| J-type and T-type | — | — | **NOT TESTED** — we use K, J, and T in production |
| CJC source | — | — | Always internal (our hardware has built-in CJC) — no test needed |
| Open-TC detection | — | — | **NEEDS TEST** — important for detecting disconnected sensors |

### Current Output (NI 9266) — MINIMALLY TESTED

| Behavior | Test | Group | Status |
|----------|------|-------|--------|
| Channels appear in batch | `test_channel_values_arriving` | 2 | TESTED |
| mA→A conversion in write path | — | — | **NOT TESTED** (no loopback) |
| Hardware limits clamping | — | — | **NOT TESTED** |
| Default value on safe state | — | — | **NOT TESTED** |

---

## What Needs Validation When New Modules Are Plugged In

### Counter Input (e.g., NI 9361)

**Code path:** `_create_counter_input_task()` and `_make_ctr_read_fn()` in `hardware.py`

**Config fields to verify:**
- `counter_mode`: `"frequency"`, `"count"`, `"period"`
- `counter_edge`: `"rising"`, `"falling"`
- `counter_min_freq` / `counter_max_freq`

**Critical behaviors to test:**

| # | Test | Why It Matters |
|---|------|----------------|
| 1 | **Frequency mode: reads Hz** | `add_ci_freq_chan()` called with correct min/max range. Value is frequency in Hz. |
| 2 | **Edge count mode: counts up** | `add_ci_count_edges_chan()` called. Raw value is 32-bit unsigned integer. |
| 3 | **Edge count rollover at 2^32** | Rollover tracking: when `raw < prev`, offset += 0x100000000. Accumulated value must be continuous. This is safety-relevant for totalizer applications (flow meters, batch counters). |
| 4 | **Period mode: returns frequency** | `add_ci_period_chan()` called. Raw value is period in seconds, converted to frequency via `1.0 / value`. |
| 5 | **Rising vs falling edge** | `counter_edge='falling'` must use `Edge.FALLING`. Wrong edge = zero count on unidirectional signals. |
| 6 | **One task per channel** | Counter inputs create per-channel tasks (DAQmx requirement). Verify multiple counter channels don't interfere. |
| 7 | **Frequency range defaults** | Missing `counter_min_freq`/`counter_max_freq` defaults to 0 Hz – 1 MHz. Verify no DAQmx error. |
| 8 | **Counter reset on acquisition restart** | Rollover state (`_counter_rollover`) must clear on stop. Stale offset from previous run = wrong count. |
| 9 | **Zero frequency handling** | Signal stops → frequency reads 0 or timeout. Must not crash or return NaN. |
| 10 | **High-frequency accuracy** | At 100 kHz+, verify measurement matches signal generator within ±1%. |

**Suggested test wiring:**
- Signal generator → counter input ch0 (known frequency, e.g., 1 kHz square wave)
- OR: pulse output (NI 9266 CO) loopback → counter input (self-test)

---

### RTD (e.g., NI 9216, 9217, 9226)

**Code path:** `_create_ai_task()` RTD branch in `hardware.py`

**Config fields to verify:**
- `rtd_type`: `"Pt3850"`, `"Pt3750"`, `"Pt3911"`, etc.
- `rtd_wiring`: `"2-wire"`, `"3-wire"`, `"4-wire"`

**Critical behaviors to test:**

| # | Test | Why It Matters |
|---|------|----------------|
| 1 | **4-wire RTD reads temperature** | `add_ai_rtd_chan()` with `FOUR_WIRE` config. Value in °C. Most common industrial config. |
| 2 | **3-wire RTD reads temperature** | `THREE_WIRE` config. Lead resistance compensation differs from 4-wire. Wrong wiring = offset error. |
| 3 | **2-wire RTD reads temperature** | `TWO_WIRE` config. No lead compensation. Value includes lead resistance error. |
| 4 | **Pt3850 vs Pt3750 type** | Wrong RTD type = wrong temperature curve = wrong reading. Pt100 sensors exist in both standards. |
| 5 | **On-demand read mode** | RTD modules force on-demand reads (no sample clock). Verify reads succeed and don't timeout. |
| 6 | **Open sensor detection** | Disconnected RTD should read NaN or extremely high resistance, not a valid temperature. |
| 7 | **Temperature range** | Pt100: -200°C to +850°C. Values outside this range indicate wiring or config error. |
| 8 | **Default RTD type fallback** | Missing `rtd_type` → defaults to Pt3850. Verify no crash with missing config field. |

**Suggested test wiring:**
- Pt100 RTD sensor in ice water (0°C reference) or room temp
- OR: precision decade resistor set to 100.00Ω (simulates 0°C for Pt100)

---

### Strain Gauge / Bridge Input (e.g., NI 9237, 9235, 9236)

**Code path:** `_create_ai_task()` bridge_input branch in `hardware.py`

**Config fields to verify:**
- `excitation_voltage` (default 2.5V)
- Bridge configuration (full-bridge hardcoded)

**Critical behaviors to test:**

| # | Test | Why It Matters |
|---|------|----------------|
| 1 | **Full bridge reads mV/V** | `add_ai_bridge_chan()` with `FULL_BRIDGE`. Value in mV/V. Range ±0.002. |
| 2 | **Excitation voltage setting** | Wrong excitation = wrong sensitivity. 2.5V vs 5V vs 10V depends on sensor rating. |
| 3 | **Zero balance at rest** | Unloaded strain gauge should read ~0 mV/V. Large offset = bad wiring or unbalanced bridge. |
| 4 | **Fallback to voltage on error** | If `add_ai_bridge_chan()` fails, code falls back to `add_ai_voltage_chan()` with ±0.1V. Verify fallback works and is logged. |
| 5 | **Bridge config varieties** | Code hardcodes `FULL_BRIDGE`. Half-bridge and quarter-bridge need testing if those sensors are used. |
| 6 | **Scaling from mV/V to engineering units** | Raw mV/V must be scaled to strain (µε) or force (N/lbs). Verify scale_slope/offset applied correctly. |

**Suggested test wiring:**
- Load cell with known weight (calibration check)
- OR: short all bridge arms for zero check

---

### IEPE / Accelerometer (e.g., NI 9234, 9233)

**Code path:** `_create_ai_task()` IEPE branch in `hardware.py`

**Config fields to verify:**
- `sensitivity` (default 100.0 mV/g)
- `excitation_current` (default 0.002 A = 2 mA)

**Critical behaviors to test:**

| # | Test | Why It Matters |
|---|------|----------------|
| 1 | **IEPE channel reads acceleration** | `add_ai_accel_chan()` with correct sensitivity. Value in g or m/s². |
| 2 | **Excitation current flows** | IEPE sensors need constant current (2-4 mA). No excitation = no signal. Verify bias voltage present (~8-12V DC). |
| 3 | **Sensitivity parameter** | Wrong sensitivity (mV/g) = wrong amplitude scaling. 100 mV/g accelerometer configured as 10 mV/g reads 10x too high. |
| 4 | **Fallback to voltage on error** | If IEPE setup fails, falls back to voltage (±5V). Verify fallback logged as WARNING. |
| 5 | **AC coupling** | IEPE is AC-coupled. DC offset should be removed. Verify baseline sits near 0g at rest. |
| 6 | **At-rest value** | Accelerometer at rest on flat surface should read ~0g horizontal, ~1g vertical (gravity). |

**Suggested test wiring:**
- IEPE accelerometer mounted on table (baseline: ~0g X/Y, ~1g Z)
- OR: tap test for impulse response

---

### Resistance Input (e.g., NI 9219 in resistance mode)

**Code path:** `_create_ai_task()` resistance_input branch in `hardware.py`

**Config fields to verify:**
- `resistance_wiring`: `"2-wire"`, `"4-wire"`
- `resistance_range` (default 1000Ω)

**Critical behaviors to test:**

| # | Test | Why It Matters |
|---|------|----------------|
| 1 | **4-wire resistance reads ohms** | `add_ai_resistance_chan()` with `FOUR_WIRE`. Value in Ω. Excitation: 1 mA internal. |
| 2 | **2-wire includes lead resistance** | `TWO_WIRE` doesn't compensate for leads. Reading should be higher than actual by lead resistance. |
| 3 | **Known resistor reads correctly** | 100Ω precision resistor should read 100 ±0.5Ω (module accuracy spec). |
| 4 | **Open circuit reads NaN or overrange** | Disconnected leads should not produce a valid resistance reading. |
| 5 | **Range setting** | `resistance_range=1000` means 0–1000Ω. Exceeding range = overrange or clamped value. |

**Suggested test wiring:**
- Precision decade resistor (100Ω, 350Ω, 1000Ω test points)
- OR: known RTD at known temperature

---

### Pulse Output (NI 9266 CO channels, or counter output modules)

**Code path:** `_create_pulse_output_task()` in `hardware.py`

**Config fields to verify:**
- `pulse_frequency` (default 1000 Hz)
- `pulse_duty_cycle` (default 50%)
- `pulse_idle_state`: `"LOW"`, `"HIGH"`

**Critical behaviors to test:**

| # | Test | Why It Matters |
|---|------|----------------|
| 1 | **Pulse output at configured frequency** | `add_co_pulse_chan_freq()` with continuous timing. Verify frequency on scope or counter input. |
| 2 | **Duty cycle setting** | 25%, 50%, 75% duty cycles measured correctly. Wrong duty = wrong average power in PWM applications. |
| 3 | **Frequency update (dynamic)** | Write new frequency via MQTT → task stops, reconfigures, restarts. No glitch or crash. |
| 4 | **Frequency zero stops output** | Write 0 Hz → `task.stop()`. Output goes to idle state. No crash. |
| 5 | **Idle state (LOW vs HIGH)** | `pulse_idle_state='HIGH'` means output is HIGH when stopped. Safety-relevant for normally-closed valves. |
| 6 | **Immediate start on creation** | Pulse output starts in `_create_pulse_output_task()`, not deferred. Verify output begins immediately when acquisition starts. |

**Suggested test wiring:**
- Pulse output → counter input (loopback, verify frequency match)
- OR: pulse output → oscilloscope

---

### Current Input (e.g., NI 9203, 9208)

**Code path:** `_create_ai_task()` current_input branch in `hardware.py`

**Config fields to verify:**
- `current_range_ma` (default 20.0)

**Critical behaviors to test:**

| # | Test | Why It Matters |
|---|------|----------------|
| 1 | **Reads milliamps** | `add_ai_current_chan()` with range converted from mA to A. Value in amps (not mA). |
| 2 | **4-20mA scaling** | With `four_twenty_scaling=true`, 4mA maps to `eng_units_min`, 20mA maps to `eng_units_max`. Critical for all 4-20mA transmitters. |
| 3 | **Open loop detection** | Disconnected 4-20mA loop reads <3.5mA (below live zero). Should trigger COMM_FAIL or low alarm. |
| 4 | **mA→A unit conversion** | `current_range_ma / 1000.0` in constructor. Display should show mA (not raw amps). |

**Suggested test wiring:**
- 4-20mA current loop simulator
- OR: precision current source at 4mA, 12mA, 20mA

---

## Summary: Test Readiness by Channel Type

| Channel Type | Code Exists | Tested with Real Hardware | Ready to Plug In | Needs New Tests |
|--------------|-------------|---------------------------|-------------------|-----------------|
| Voltage AI | YES | YES (NI 9202) | YES | NO |
| Voltage AO | YES | YES (NI 9264) | YES | NO |
| Digital Input | YES | YES (NI 9425) | YES | NO |
| Digital Output | YES | YES (NI 9472) | YES | NO |
| Thermocouple | YES | YES (NI 9213, K-type) | YES (K-type) | Other TC types, CJC modes |
| Current Output | YES | YES (NI 9266) | YES | Loopback accuracy |
| **Counter Input** | YES | **NO** | Probably works | **YES — rollover, modes, edge** |
| **RTD** | YES | **NO** | Probably works | **YES — wiring, types, on-demand** |
| **Strain/Bridge** | YES | **NO** | Probably works | **YES — bridge config, excitation, fallback** |
| **IEPE** | YES | **NO** | Probably works | **YES — excitation, sensitivity, fallback** |
| **Resistance** | YES | **NO** | Probably works | **YES — wiring, range, open circuit** |
| **Pulse Output** | YES | **NO** | Probably works | **YES — freq update, duty, idle state** |
| **Current Input** | YES | **NO** | Probably works | **YES — 4-20mA scaling, open loop** |
| **Frequency Input** | YES | **NO** | Probably works | **YES — range, edge, accuracy** |

---

## Configuration Reference (for Test Project JSON)

When adding a new module to `_CrioAcquisitionTest.json`, use these templates:

### Counter Input Channel
```json
{
  "name": "CTR_Mod7_ch00",
  "physical_channel": "Mod7/ctr0",
  "channel_type": "counter_input",
  "unit": "Hz",
  "group": "Mod7_CTR",
  "source_type": "crio",
  "source_node_id": "crio-001",
  "counter_mode": "frequency",
  "counter_edge": "rising",
  "counter_min_freq": 0.1,
  "counter_max_freq": 100000
}
```

### Counter Input (Edge Count)
```json
{
  "name": "CTR_Mod7_ch01",
  "physical_channel": "Mod7/ctr1",
  "channel_type": "counter_input",
  "unit": "counts",
  "group": "Mod7_CTR",
  "source_type": "crio",
  "source_node_id": "crio-001",
  "counter_mode": "count",
  "counter_edge": "rising"
}
```

### RTD Channel
```json
{
  "name": "RTD_Mod7_ch00",
  "physical_channel": "Mod7/ai0",
  "channel_type": "rtd",
  "unit": "°C",
  "group": "Mod7_RTD",
  "source_type": "crio",
  "source_node_id": "crio-001",
  "rtd_type": "Pt3850",
  "rtd_wiring": "4-wire"
}
```

### Strain / Bridge Channel
```json
{
  "name": "STR_Mod7_ch00",
  "physical_channel": "Mod7/ai0",
  "channel_type": "bridge_input",
  "unit": "mV/V",
  "group": "Mod7_STRAIN",
  "source_type": "crio",
  "source_node_id": "crio-001",
  "excitation_voltage": 2.5
}
```

### IEPE Channel
```json
{
  "name": "IEPE_Mod7_ch00",
  "physical_channel": "Mod7/ai0",
  "channel_type": "iepe_input",
  "unit": "g",
  "group": "Mod7_IEPE",
  "source_type": "crio",
  "source_node_id": "crio-001",
  "sensitivity": 100.0,
  "excitation_current": 0.004
}
```

### Resistance Channel
```json
{
  "name": "RES_Mod7_ch00",
  "physical_channel": "Mod7/ai0",
  "channel_type": "resistance_input",
  "unit": "Ω",
  "group": "Mod7_RES",
  "source_type": "crio",
  "source_node_id": "crio-001",
  "resistance_range": 1000.0,
  "resistance_wiring": "4-wire"
}
```

### Pulse Output Channel
```json
{
  "name": "PULSE_Mod7_ch00",
  "physical_channel": "Mod7/ctr0",
  "channel_type": "pulse_output",
  "unit": "Hz",
  "group": "Mod7_PULSE",
  "source_type": "crio",
  "source_node_id": "crio-001",
  "pulse_frequency": 1000.0,
  "pulse_duty_cycle": 50.0,
  "pulse_idle_state": "LOW"
}
```

### Current Input Channel
```json
{
  "name": "CI_Mod7_ch00",
  "physical_channel": "Mod7/ai0",
  "channel_type": "current_input",
  "unit": "mA",
  "group": "Mod7_CI",
  "source_type": "crio",
  "source_node_id": "crio-001",
  "current_range_ma": 20.0,
  "four_twenty_scaling": true,
  "eng_units_min": 0.0,
  "eng_units_max": 100.0
}
```

---

## Hardware Constants (from hardware.py)

| Constant | Value | Affects |
|----------|-------|---------|
| `AI_SLOW_READ_TIMEOUT_S` | 5.0 | TC/RTD on-demand read timeout |
| `AI_ONDEMAND_READ_TIMEOUT_S` | 1.0 | Non-TC on-demand read timeout |
| `AI_TIMED_READ_TIMEOUT_S` | 1.0 | Continuous AI read timeout |
| `CTR_READ_TIMEOUT_S` | 0.1 | Counter read timeout |
| `DI_READ_TIMEOUT_S` | 0.01 | DI on-demand read timeout |
| `RESISTANCE_EXCITATION_A` | 0.001 | Resistance channel excitation (1 mA) |
| `DEFAULT_MIN_PERIOD_S` | 0.001 | Period counter minimum |
| `DEFAULT_MAX_PERIOD_S` | 10.0 | Period counter maximum |
| `DEFAULT_DI_POLL_HZ` | 20.0 | DI polling rate |
| `MAX_DI_POLL_HZ` | 100.0 | Maximum DI polling rate |

## Error Handling & Fallbacks (from hardware.py)

These fallback paths exist but have NOT been tested with real hardware:

| Scenario | Fallback | Tested |
|----------|----------|--------|
| DI change detection fails (-201020) | Recreate as polling task | YES (NI 9425 triggers this) |
| IEPE setup fails | Voltage input ±5V | **NO** |
| Bridge setup fails | Voltage input ±0.1V | **NO** |
| Invalid TC type string | Default to K-type | **NO** |
| Invalid RTD wiring string | Default to 4-wire | **NO** |
| Counter read timeout | Return last cached value | **NO** |
| 3+ consecutive read errors | All channel values → NaN | **NO** (hot-unplug tested in unit tests only) |
| Hardware limit exceeded on write | Clamp value, log ERROR | **NO** |

---

## Recommended Test Priority

When new hardware arrives, test in this order:

1. **Counter input** — Most complex untested path (3 modes, rollover tracking, per-channel tasks)
2. **RTD** — On-demand read mode same as TC but different constructor, wiring configs
3. **Pulse output** — Dynamic frequency update requires stop/reconfigure/restart
4. **Current input** — 4-20mA scaling is used on almost every industrial transmitter
5. **IEPE** — Excitation current is pass/fail (no current = no signal)
6. **Strain/Bridge** — Excitation voltage + fallback path
7. **Resistance** — Simplest of the untested types
