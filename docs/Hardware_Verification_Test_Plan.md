# Hardware Verification Test Plan

The dashboard presents a uniform interface regardless of backend hardware. A user
configuring channels, writing scripts, setting alarms, or managing interlocks should
not notice any difference between cDAQ, cRIO, Opto22, or cFP. This test plan verifies
that guarantee.

**Bench Hardware:**
- cDAQ-9189 (local, 6 NI modules, 50 channels)
- cRIO at 192.168.1.20 (6 NI modules, 96 channels, node `crio-001`)
- cFP at 192.168.1.30:502 (4 Modbus modules, 7 channels, node `cfp-001`)
- Opto22 groov EPIC/RIO (if available, node `opto22-001`)

**MQTT Monitor (run in separate terminal for all tests):**
```powershell
$creds = Get-Content config\mqtt_credentials.json | ConvertFrom-Json
vendor\mosquitto\mosquitto_sub.exe -h localhost -p 1883 `
  -u $creds.backend.username -P $creds.backend.password -v `
  -t "nisystem/#"
```

**Convention:** Each common test has a results row per platform. Mark P (pass), F (fail),
N/A (not applicable), or S (skip — hardware not on bench).

---

# PART A: PLATFORM-SPECIFIC SETUP

These are the only tests that differ by platform — getting each device online and
talking to the DAQ service.

## A1. cDAQ Setup (Local NI Hardware)

| # | Test | Steps | Expected | Pass |
|---|------|-------|----------|------|
| 1 | NI-DAQmx driver present | Check NI MAX or `device.bat scan` | cDAQ-9189 chassis detected with all 6 modules | |
| 2 | Device discovery | Configuration tab > Scan Devices | Modules listed: 9214, 9201, 9203, 9425, 9475, 9202 | |
| 3 | Channel enumeration | Expand each module | Correct count: 16 TC, 8 AI, 8 CI, 32 DI, 8 DO, 4 AO | |
| 4 | Add channels to project | Drag/select channels into project | Channels appear in channel list with correct types | |
| 5 | Start acquisition | Click Start | Values publishing; dashboard live | |

## A2. cRIO Setup (Remote NI Hardware via MQTT)

| # | Test | Steps | Expected | Pass |
|---|------|-------|----------|------|
| 1 | Deploy | `deploy_crio_v2.bat 192.168.1.20 192.168.1.1` | Files deployed; service restarted | |
| 2 | Node comes online | MQTT monitor | `crio-001/status/system {"status":"online"}` | |
| 3 | Config push | Load cRIO project; DAQ pushes config | cRIO acks with matching config hash | |
| 4 | Channels appear | Dashboard channel list | cRIO channels show with `source_type: crio` | |
| 5 | Start acquisition | Click Start | cRIO values appear in dashboard identically to local channels | |

## A3. cFP Setup (Modbus TCP via MQTT)

| # | Test | Steps | Expected | Pass |
|---|------|-------|----------|------|
| 1 | Modbus connectivity | `Test-NetConnection 192.168.1.30 -Port 502` | Connection successful | |
| 2 | Node comes online | MQTT monitor | `cfp-001/status/system {"status":"online"}` | |
| 3 | Config push | Load project with cFP channels | cFP acks config; channels map to Modbus registers | |
| 4 | Channels appear | Dashboard channel list | cFP channels show alongside cDAQ/cRIO channels — no visible difference | |
| 5 | Start acquisition | Click Start | cFP values appear in dashboard identically to other channels | |

## A4. Opto22 Setup (groov MQTT + System MQTT)

| # | Test | Steps | Expected | Pass |
|---|------|-------|----------|------|
| 1 | System MQTT connect | Start Opto22 node | Connects to ICCSFlux broker (8883 TLS) | |
| 2 | groov MQTT connect | Verify I/O subscription | groov Manage publishes I/O; Python node receives | |
| 3 | Node comes online | MQTT monitor | `opto22-001/status/system {"status":"online"}` | |
| 4 | Config push | Load project with Opto22 channels | Node acks config | |
| 5 | Channels appear | Dashboard channel list | Opto22 channels indistinguishable from any other source | |
| 6 | Start acquisition | Click Start | Values publish to dashboard at same rate as other platforms | |

---

# PART B: COMMON FEATURE TESTS

**Run every test on every platform.** The user experience must be identical.

For each test, record result per platform:

```
cDAQ | cRIO | cFP | Opto22
```

## B1. Channel Reading — Analog Input

Pick one AI channel per platform (TC, voltage, current — whatever is available).

| # | Test | Steps | Expected | cDAQ | cRIO | cFP | Opto22 |
|---|------|-------|----------|------|------|-----|--------|
| 1 | Zero/baseline reading | No input applied (or shorted) | Reads ~0 (+/- noise) | | | | |
| 2 | Known input | Apply 5V (or equivalent known signal) | Correct value displayed in dashboard | | | | |
| 3 | Full-scale input | Apply max range signal | Reads max without overflow or crash | | | | |
| 4 | Value in trend chart | Add channel to TrendChart widget | Smooth line; updates at publish rate | | | | |
| 5 | Value in numeric display | Add channel to NumericDisplay widget | Shows value with correct units | | | | |
| 6 | Scaling — linear | Configure slope=2, offset=-10 | Dashboard shows scaled value | | | | |
| 7 | Engineering units | Set unit to "PSI" or "degC" | Unit displays in all widgets | | | | |

## B2. Channel Reading — Digital Input

Pick one DI channel per platform.

| # | Test | Steps | Expected | cDAQ | cRIO | cFP | Opto22 |
|---|------|-------|----------|------|------|-----|--------|
| 1 | Read LOW | No input / open | Dashboard shows 0 / OFF | | | | |
| 2 | Read HIGH | Apply 24V (or close contact) | Dashboard shows 1 / ON | | | | |
| 3 | Toggle | Switch ON/OFF several times | LED widget or toggle updates in real time | | | | |
| 4 | Edge detection | Configure digital alarm (expected=HIGH); remove input | Alarm fires on unexpected state | | | | |

## B3. Channel Writing — Digital Output

Pick one DO channel per platform.

| # | Test | Steps | Expected | cDAQ | cRIO | cFP | Opto22 |
|---|------|-------|----------|------|------|-----|--------|
| 1 | Set HIGH from dashboard | Toggle switch widget ON | Hardware output activates (measure with DMM) | | | | |
| 2 | Set LOW from dashboard | Toggle switch widget OFF | Hardware output deactivates | | | | |
| 3 | Set from script | Script: `outputs['DO_ch'] = 1` | Output activates | | | | |
| 4 | Set from MQTT command | Publish write command | Output activates | | | | |
| 5 | Safe state command | Send safe-state | Output goes to 0 (safe value) | | | | |
| 6 | Default value on stop | Stop acquisition | Output returns to configured default | | | | |

## B4. Channel Writing — Analog Output

Pick one AO channel per platform (if available).

| # | Test | Steps | Expected | cDAQ | cRIO | cFP | Opto22 |
|---|------|-------|----------|------|------|-----|--------|
| 1 | Set 0V | Setpoint widget to 0 | Measure 0V at terminal | | | | |
| 2 | Set mid-range | Setpoint widget to 5V | Measure 5V +/- 0.01V | | | | |
| 3 | Set full scale | Setpoint widget to 10V | Measure 10V | | | | |
| 4 | Script ramp | Script: ramp 0-10V over 10s | Smooth ramp on DMM | | | | |
| 5 | Safe state | Send safe-state command | Returns to 0V | | | | |

## B5. Alarms (ISA-18.2)

Pick one analog channel per platform. Configure alarm thresholds.

| # | Test | Steps | Expected | cDAQ | cRIO | cFP | Opto22 |
|---|------|-------|----------|------|------|-----|--------|
| 1 | High alarm fires | Set hi_limit=30; exceed 30 | Alarm banner appears in dashboard; alarm widget shows active | | | | |
| 2 | High-high (CRITICAL) | Set hihi_limit=50; exceed 50 | CRITICAL severity alarm; red indicator | | | | |
| 3 | Low alarm | Set lo_limit=10; go below 10 | Low alarm fires | | | | |
| 4 | Deadband | hi_limit=30, deadband=5; exceed 35, return to 28 | Alarm stays active at 28 (need <25 to clear) | | | | |
| 5 | On-delay | on_delay_s=5; briefly spike above threshold for 2s | Alarm does NOT fire (too brief) | | | | |
| 6 | On-delay — sustained | Sustain above threshold for 6s | Alarm fires after 5s | | | | |
| 7 | Off-delay | off_delay_s=10; return to normal | Alarm stays active for 10s then clears | | | | |
| 8 | Rate-of-change | roc_threshold=10/min; rapid change | ROC alarm fires | | | | |
| 9 | Acknowledge | Alarm active > click Ack in dashboard | Alarm state changes to acknowledged | | | | |
| 10 | Latching | latch=true; trigger; value returns normal | Alarm stays active until acknowledged | | | | |
| 11 | Shelving | Shelve for 2 minutes | Alarm suppressed; auto-unshelves after 2 min | | | | |
| 12 | Out-of-service | Mark alarm OOS | Alarm disabled; threshold violations ignored | | | | |
| 13 | Return-to-service | Return alarm to service while value is in violation | Alarm fires immediately | | | | |
| 14 | COMM_FAIL | Disconnect hardware/module | COMM_FAIL alarm fires for affected channels | | | | |
| 15 | COMM_FAIL clear | Reconnect hardware | COMM_FAIL clears automatically | | | | |
| 16 | First-out tracking | Trigger two alarms simultaneously | First-out flag on earliest alarm | | | | |
| 17 | Alarm history | Check alarm history in dashboard | All events logged with timestamps | | | | |

## B6. Interlocks (IEC 61511)

Pick one analog + one digital channel per platform. Create interlocks via the Safety tab.

| # | Test | Steps | Expected | cDAQ | cRIO | cFP | Opto22 |
|---|------|-------|----------|------|------|-----|--------|
| 1 | Create interlock | Safety tab: condition=channel_value > 50, control=set DO=0 | Interlock appears in list | | | | |
| 2 | Arm latch | Click "Arm" | State: SAFE -> ARMED | | | | |
| 3 | Trip | Exceed threshold | State: ARMED -> TRIPPED; DO forced to 0 | | | | |
| 4 | Output blocked | While tripped: try to write DO from dashboard | Rejected with "blocked by interlock" | | | | |
| 5 | Output blocked — script | While tripped: script writes DO | Rejected; script gets error | | | | |
| 6 | Reset | Clear condition; click Reset | State: TRIPPED -> SAFE; DO unlocked | | | | |
| 7 | AND logic | Two conditions, both must fail to trip | Only trips when BOTH conditions met | | | | |
| 8 | OR logic | Two conditions, either can trip | Trips when EITHER condition met | | | | |
| 9 | Condition delay | on_delay=5s on condition | Must be in violation 5s before trip | | | | |
| 10 | Bypass | Bypass for 60s | Interlock ignored; auto-expires at 60s | | | | |
| 11 | Demand count | Trip/reset 3 times | Dashboard shows demand count = 3 | | | | |
| 12 | Proof test | Record proof test from Safety tab | Logged with user, notes, next-due date | | | | |
| 13 | Channel offline | Disconnect module/hardware for interlock channel | `channel_offline=true` in interlock status | | | | |
| 14 | Retained state | Disconnect MQTT monitor; reconnect | `safety/latch/state` appears immediately (retained) | | | | |

## B7. Scripts

Pick any readable channel per platform.

| # | Test | Steps | Expected | cDAQ | cRIO | cFP | Opto22 |
|---|------|-------|----------|------|------|-----|--------|
| 1 | Read channel | Script: `val = tags['ch_name']` | Returns current value | | | | |
| 2 | Publish computed value | Script: `publish('doubled', tags['ch'] * 2)` | "doubled" appears as published value in MQTT | | | | |
| 3 | Write output | Script: `outputs['DO_ch'] = 1` | Hardware output activates | | | | |
| 4 | RateCalculator | `rate.update(tags['ch']); publish('rate', rate.value)` | Shows derivative | | | | |
| 5 | Accumulator | `acc.update(tags['ch']); publish('total', acc.value)` | Running sum | | | | |
| 6 | EdgeDetector | `edge.update(tags['DI']); publish('rising', edge.rising)` | Detects transitions | | | | |
| 7 | Conditional output | `outputs['DO'] = 1 if tags['AI'] > 5 else 0` | DO follows condition | | | | |
| 8 | Auto-start (ACQUISITION) | Set mode=ACQUISITION; start acq | Script auto-starts | | | | |
| 9 | Auto-start (SESSION) | Set mode=SESSION; start session | Script starts only with session | | | | |
| 10 | Sandbox — import blocked | Script: `import os` | Rejected with security error | | | | |
| 11 | Sandbox — builtins blocked | Script: `eval('1+1')` | Rejected | | | | |
| 12 | Sandbox — dunder blocked | Script: `().__class__.__bases__` | Rejected | | | | |
| 13 | Script timeout | Script: `while True: pass` | Killed after timeout | | | | |
| 14 | Rate limiting | Script publishes rapidly | Capped at 4Hz publish rate | | | | |

## B8. Sessions

| # | Test | Steps | Expected | cDAQ | cRIO | cFP | Opto22 |
|---|------|-------|----------|------|------|-----|--------|
| 1 | Start session | Session tab > name, operator, locked outputs | State changes; session active | | | | |
| 2 | Output locked | Try to write locked output from dashboard | Rejected: "locked by session" | | | | |
| 3 | Output locked — script | Script writes locked output | Rejected | | | | |
| 4 | Unlocked output still works | Write non-locked output | Succeeds normally | | | | |
| 5 | Stop session | Click Stop | Outputs unlocked; state returns to ACQUIRING | | | | |
| 6 | Alarm guard | require_no_active=true; trigger alarm; try start session | Start rejected | | | | |
| 7 | Session timeout | Set timeout=1min; start; wait 65s | Auto-stops | | | | |

## B9. Recording (DAQ Service Only — data from all sources)

Recording happens on the PC regardless of source. All platform channels are recorded identically.

| # | Test | Steps | Expected | Pass |
|---|------|-------|----------|------|
| 1 | CSV recording | Start recording; include channels from all platforms | Single CSV with columns from cDAQ + cRIO + cFP + Opto22 | |
| 2 | Data integrity | Record 60s; open CSV | All platforms' channels present; timestamps aligned | |
| 3 | Buffered mode | Switch to buffered; record 60s | Same data, written in batches | |
| 4 | File rotation | Set max 100KB | New file at boundary; no data loss | |
| 5 | Circular mode | Max 3 files | Oldest deleted when 4th created | |
| 6 | Decimation | Factor=10 | 1/10th the rows | |
| 7 | Channel filter | Select 2 channels from each platform (8 total) | Only 8 columns + timestamp in CSV | |
| 8 | Crash recovery | Kill DAQ mid-recording; restart | File not corrupted; OS file lock released | |

## B10. PID Control

| # | Test | Steps | Expected | cDAQ | cRIO | cFP | Opto22 |
|---|------|-------|----------|------|------|-----|--------|
| 1 | Auto mode | PV=AI, SP=target, CV=AO; set Kp/Ki/Kd | AO drives PV toward SP | | | N/A | |
| 2 | Manual mode | Switch to manual; set CV directly | AO holds at set value | | | N/A | |
| 3 | Bumpless transfer | Switch auto->manual mid-control | No output spike | | | N/A | |
| 4 | Anti-windup | SP above plant max; wait | Integral doesn't saturate | | | N/A | |

*Note: cFP typically doesn't run PID (no local compute). PID for cRIO runs on DAQ service;
PID for Opto22 runs locally on groov EPIC.*

## B11. Audit Trail

| # | Test | Steps | Expected | cDAQ | cRIO | cFP | Opto22 |
|---|------|-------|----------|------|------|-----|--------|
| 1 | Output write logged | Write an output from dashboard | Audit entry with user, channel, value, timestamp | | | | |
| 2 | Alarm ack logged | Acknowledge an alarm | Audit entry with alarm ID and user | | | | |
| 3 | Interlock trip logged | Trip an interlock | Audit entry with reason and timestamp | | | | |
| 4 | SHA-256 hash chain | Read audit file; verify chain | Each entry hash includes previous hash | | | | |
| 5 | Tamper detection | Manually edit audit file; restart | Tamper detected; security event logged | | | | |

---

# PART C: RESILIENCE & FAILOVER

These tests verify graceful degradation when things go wrong. The key principle:
**edge nodes (cRIO, Opto22, cFP) must survive PC disconnection.**

## C1. Hardware Disconnect (per platform)

| # | Test | Steps | Expected | cDAQ | cRIO | cFP | Opto22 |
|---|------|-------|----------|------|------|-----|--------|
| 1 | Module hot-unplug | Remove a module mid-acquisition | COMM_FAIL alarm for affected channels; other channels unaffected | | | | |
| 2 | Module re-plug | Reconnect module | COMM_FAIL clears; values resume | | | | |
| 3 | Full device disconnect | Unplug cDAQ USB / cRIO Ethernet / cFP Ethernet | All channels show COMM_FAIL; dashboard degrades gracefully | | | | |
| 4 | Device reconnect | Plug back in | Channels recover; alarms clear | | | | |

## C2. PC / Network Disconnect (edge nodes only)

| # | Test | Steps | Expected | cRIO | cFP | Opto22 |
|---|------|-------|----------|------|-----|--------|
| 1 | Continue acquiring standalone | Unplug PC network; wait 10s | Edge node keeps reading hardware and running scripts | | | |
| 2 | Comm watchdog trip | Wait 30+s disconnected | Safe state applied; outputs go to safe values; state -> IDLE | | | |
| 3 | Verify outputs are safe | Measure outputs with DMM while disconnected | AO=0V, DO=OFF (or configured safe values) | | | |
| 4 | Scripts survive | Script was running before disconnect | Script continues on edge node (cRIO/Opto22) | | N/A | |
| 5 | PID survives | PID loop running before disconnect | PID continues controlling locally (Opto22 only) | N/A | N/A | |
| 6 | Sequences survive | Sequence running before disconnect | Sequence completes on edge node (Opto22 only) | N/A | N/A | |
| 7 | Reconnection | Plug PC back in | comm_watchdog clears; node reconnects; dashboard recovers | | | |
| 8 | Re-push config | DAQ service sends config after reconnect | Edge node picks up latest config; resumes normal operation | | | |

## C3. MQTT Broker Failure

| # | Test | Steps | Expected | Pass |
|---|------|-------|----------|------|
| 1 | Kill Mosquitto | Stop broker process | All nodes log disconnect; cDAQ logs "unexpectedly" | |
| 2 | Local ops continue | Edge nodes keep reading hardware | cRIO/Opto22/cFP continue standalone; only MQTT publishing stops | |
| 3 | Restart Mosquitto | Start broker again | All nodes auto-reconnect; DAQ logs "Reconnected"; LWT clears | |
| 4 | Retained state correct | Check retained messages after restart | `safety/latch/state` and `status/system` correct | |

## C4. DAQ Service Crash

| # | Test | Steps | Expected | Pass |
|---|------|-------|----------|------|
| 1 | Kill DAQ service | End Task in Task Manager | LWT publishes `{"status":"offline","reason":"unexpected_disconnect"}` | |
| 2 | Edge nodes unaffected | Check cRIO/Opto22/cFP | Still running; comm watchdog starts counting | |
| 3 | Restart DAQ | Restart DAQ service | Reconnects; pushes config to nodes; dashboard recovers | |
| 4 | Recording crash-safe | Kill mid-recording; check CSV | File not corrupted; OS lock released | |

## C5. Opto22 groov MQTT Failure (Opto22-specific)

| # | Test | Steps | Expected | Pass |
|---|------|-------|----------|------|
| 1 | Stop groov Manage MQTT | Kill groov broker on device | `status/groov_mqtt {"connected":false}` published | |
| 2 | Stale detection | Wait 10s+ | `status/stale_channels` lists all channels | |
| 3 | COMM_FAIL alarms | Stale channels excluded from safety snapshot | COMM_FAIL fires per channel (new hardening) | |
| 4 | Restart groov MQTT | Restart groov Manage | Stale clears; COMM_FAIL clears; values resume | |

---

# PART D: CROSS-PLATFORM INTEGRATION

## D1. Mixed-Source Dashboard

| # | Test | Steps | Expected | Pass |
|---|------|-------|----------|------|
| 1 | Single trend chart | Add 1 channel from each platform to same TrendChart | All 4 lines plot together; same time axis; no gaps | |
| 2 | Single numeric page | NumericDisplay widgets from all 4 platforms on one page | All display values; no visual difference between sources | |
| 3 | Mixed recording | Record to CSV with channels from all platforms | Single file; all sources interleaved by timestamp | |
| 4 | Alarm summary | Trigger alarms on all 4 platforms | All appear in same AlarmSummary widget | |

## D2. Cross-Node Interlocks

| # | Test | Steps | Expected | Pass |
|---|------|-------|----------|------|
| 1 | cRIO condition -> cFP action | Interlock: if cRIO TC > 50, set cFP DO=0 | cFP output forced to 0 when cRIO temp exceeds 50 | |
| 2 | cDAQ condition -> cRIO action | Interlock: if cDAQ AI > threshold, set cRIO DO=0 | cRIO output controlled by cDAQ reading | |
| 3 | Multi-source condition | AND: cRIO TC > 50 AND cFP DI = LOW | Both conditions from different nodes must be true | |

## D3. Config Push Consistency

| # | Test | Steps | Expected | Pass |
|---|------|-------|----------|------|
| 1 | Same alarms everywhere | Configure alarm on cRIO channel from Safety tab | Same config UI as cDAQ alarm; no platform-specific options exposed | |
| 2 | Same interlocks everywhere | Create interlock targeting Opto22 channel | Same Safety tab UI; same condition types available | |
| 3 | Same scripts everywhere | Push script to cRIO and Opto22 | Same Scripts tab UI; same API (tags, outputs, publish) | |
| 4 | Channel config uniform | Edit cFP channel in Configuration tab | Same fields as cDAQ channel (name, unit, scaling, alarm limits) | |

---

# SUMMARY: Feature Parity Checklist

Every row should be identical across all platforms. If any cell differs from the
others, that's a bug in the abstraction layer.

| Feature | cDAQ | cRIO | cFP | Opto22 |
|---------|------|------|-----|--------|
| Configuration tab — add/edit channels | | | | |
| Configuration tab — scan rate / publish rate | | | | |
| Configuration tab — scaling (linear, 4-20mA) | | | | |
| Configuration tab — alarm limits | | | | |
| Data tab — recording to CSV | | | | |
| Data tab — recording modes (buffered/immediate/circular) | | | | |
| Safety tab — create/edit alarms | | | | |
| Safety tab — alarm lifecycle (ack/shelve/OOS) | | | | |
| Safety tab — COMM_FAIL on disconnect | | | | |
| Safety tab — create/edit interlocks | | | | |
| Safety tab — latch arm/trip/reset | | | | |
| Safety tab — bypass with expiry | | | | |
| Safety tab — output blocking | | | | |
| Safety tab — channel_offline detection | | | | |
| Scripts tab — read tags | | | | |
| Scripts tab — write outputs | | | | |
| Scripts tab — publish values | | | | |
| Scripts tab — helpers (Rate, Accum, Edge, Stats) | | | | |
| Scripts tab — sandbox security | | | | |
| Scripts tab — auto-start modes | | | | |
| Session management — start/stop | | | | |
| Session management — output locking | | | | |
| Session management — alarm guards | | | | |
| Dashboard widgets — TrendChart | | | | |
| Dashboard widgets — NumericDisplay | | | | |
| Dashboard widgets — ToggleSwitch (DO) | | | | |
| Dashboard widgets — SetpointWidget (AO) | | | | |
| Dashboard widgets — LedIndicator (DI) | | | | |
| Dashboard widgets — AlarmSummary | | | | |
| Dashboard widgets — InterlockStatus | | | | |
| Audit trail — events logged | | | | |
| Audit trail — hash chain integrity | | | | |
| Safe state — all outputs to safe values | | | | |
| Resilience — hardware disconnect -> COMM_FAIL | | | | |
| Resilience — PC disconnect -> edge continues | N/A | | | |
| Resilience — comm watchdog -> safe state | N/A | | | |
| Resilience — MQTT retain on reconnect | | | | |
