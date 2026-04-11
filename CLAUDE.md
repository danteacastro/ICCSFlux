# NISystem Project Instructions

## Architecture Overview

- **Backend**: Python DAQ service (`services/daq_service/daq_service.py`, ~13k lines) — reads NI hardware (or simulation), publishes over MQTT
- **Frontend**: Vue 3 + TypeScript dashboard (`dashboard/`) — connects via WebSocket to MQTT
- **Broker**: Mosquitto MQTT — TCP 1883 (authenticated, for services + cRIO) and WebSocket 9002 (localhost-only, anonymous, for dashboard)
- **cRIO**: Python node (`services/crio_node_v2/`) deployed to NI cRIO hardware over SSH
- **Opto22**: Python + CODESYS hybrid node (`services/opto22_node/`) deployed to groov EPIC/RIO — groov Manage MQTT for native I/O, optional CODESYS runtime for deterministic PID/interlocks via Modbus TCP, Python companion for scripts, safety fallback, sequences
- **Azure**: Separate `AzureUploader` exe uploads to Azure IoT Hub (external process, not part of main DAQ service)
- **Portable build**: PyInstaller compiles to `dist/ICCSFlux-Portable/` — runs on any Windows PC without Python/Node installed

**Total codebase**: ~120k LOC backend + ~119k LOC frontend = ~239k LOC across 250+ files

## Running .bat Files (Claude Code)

This project runs on Windows. The Bash tool uses a Unix-style shell, so `.bat` files must be invoked via PowerShell:

```powershell
powershell.exe -NoProfile -Command "Set-Location 'c:\Users\User\Documents\Projects\NISystem'; & '.\venv\Scripts\python.exe' scripts\build_exe.py 2>&1"
```

General pattern for running any `.bat` or Windows command and capturing output:

```powershell
powershell.exe -NoProfile -Command "<commands here> 2>&1"
```

Do NOT use `cmd.exe /c` — it often swallows output. Do NOT call `.bat` files directly — they are not recognized by the Unix shell. Use PowerShell for all Windows-specific invocations.

---

## System Map

### Section 1: DAQ Service Core Engine

The main backend service running on the Windows PC.

| File | LOC | Purpose |
|------|-----|---------|
| `services/daq_service/daq_service.py` | 13,354 | Main service: MQTT, scan loop, orchestration. Classes: `DAQService`, `TokenBucketRateLimiter`, `ScanTimingStats` |
| `services/daq_service/state_machine.py` | 166 | Acquisition lifecycle: STOPPED → INITIALIZING → RUNNING → STOPPING → STOPPED. Class: `DAQStateMachine` |
| `services/daq_service/config_parser.py` | 1,037 | Project JSON/INI parsing. Enums: `ChannelType`, `ThermocoupleType`, `HardwareSource` |
| `services/daq_service/schema_migrations.py` | 104 | Project schema v1.0 → v2.0 migrations |
| `services/daq_service/project_manager.py` | 749 | Load/save/export/import/backup projects. Auto-backup with retention |
| `services/daq_service/backup_logger.py` | 676 | Backup file versioning and retention |
| `services/daq_service/dependency_tracker.py` | 771 | Channel/script/output dependency graph. Cycle detection |
| `services/daq_service/data_source_manager.py` | 452 | Unified multi-source reader (DAQmx, Modbus, OPC-UA, REST, EtherNet/IP) |
| `services/daq_service/scaling.py` | 440 | Raw → engineering unit conversion (linear, polynomial, log, table lookup) |
| `services/daq_service/dashboard_server.py` | 220 | WebSocket server for browser dashboard |
| `services/daq_service/user_session.py` | 573 | Authentication, roles (Admin/Operator/Viewer), permissions |

### Section 2: Hardware & Protocol Readers

| File | LOC | Purpose |
|------|-----|---------|
| `services/daq_service/hardware_reader.py` | 1,967 | NI-DAQmx continuous buffered acquisition. Supports: TC, RTD, strain, IEPE, voltage, current, DIO, counter |
| `services/daq_service/simulator.py` | 584 | Synthetic data generator (ramps, sine, noise, pulse) for testing without hardware |
| `services/daq_service/device_discovery.py` | 1,160 | NI hardware enumeration + module database (cDAQ, cRIO, PXI, USB). Cache staleness: `is_stale()`, `get_scan_age()` |
| `services/daq_service/modbus_reader.py` | 881 | Modbus TCP/RTU client (holding/input registers, coils, discretes) |
| `services/daq_service/opcua_source.py` | 542 | OPC-UA client with value subscriptions |
| `services/daq_service/rest_reader.py` | 566 | REST API polling (supports BASIC, BEARER, API_KEY, OAUTH2 auth) |
| `services/daq_service/ethernet_ip_source.py` | 447 | Allen-Bradley EtherNet/IP scanner client |

### Section 3: Scripts & Sandbox

| File | LOC | Purpose |
|------|-----|---------|
| `services/daq_service/script_manager.py` | 3,507 | User script lifecycle + sandbox. Helpers: `RateCalculator`, `Accumulator`, `EdgeDetector`, `RollingStats`, `SharedVariableStore`. APIs: `TagsAPI`, `OutputsAPI`, `SessionAPI`, `VarsAPI` |
| `services/crio_node_v2/script_engine.py` | 1,777 | cRIO-side script engine (same API as DAQ service). **MUST keep blocked lists in sync with script_manager.py** |
| `services/opto22_node/script_engine.py` | ~1,800 | Opto22-side script engine (same API as DAQ service). **MUST keep blocked lists in sync with script_manager.py** |

### Section 4: Safety, Control & Automation

| File | LOC | Purpose |
|------|-----|---------|
| `services/daq_service/alarm_manager.py` | 1,810 | ISA-18.2 alarms: deadband, on/off delays, rate-of-change, grouping, shelving, latch |
| `services/daq_service/safety_manager.py` | 1,462 | IEC 61511 interlocks with latch state machine (SAFE/ARMED/TRIPPED). Classes: `InterlockCondition`, `InterlockControl`, `Interlock`, `InterlockStatus`, `SafeStateConfig`, `InterlockHistoryEntry`. Condition types: `channel_value`, `digital_input`, `alarm_active`, `no_active_alarms`, `acquiring`, `mqtt_connected`, `daq_connected`, `variable_value`, `expression`. Features: per-interlock bypass with expiry, demand counting, proof test tracking, SIL rating, `channel_offline` detection, `has_offline_channels` flag. Config push auto-filters interlocks to edge nodes |
| `services/daq_service/pid_engine.py` | 605 | PID control loops: auto/manual/cascade, anti-windup, derivative-on-PV, bumpless transfer |
| `services/daq_service/trigger_engine.py` | 628 | Automation triggers: value threshold, time, schedule, state change → actions |
| `services/daq_service/sequence_manager.py` | 552 | Server-side sequences (survive browser disconnect): steps, loops, conditionals, waits |
| `services/daq_service/scheduler.py` | 292 | Cron-like scheduling engine |

### Section 5: Recording & Compliance

| File | LOC | Purpose |
|------|-----|---------|
| `services/daq_service/recording_manager.py` | 1,666 | Data recording: CSV/TDMS, buffered/immediate/circular modes, file rotation, decimation, OS-level file locking, fsync |
| `services/daq_service/user_variables.py` | 1,708 | User variables: accumulator, counter, timer, expression, formula. Mid-session reset |
| `services/daq_service/audit_trail.py` | 537 | 21 CFR Part 11 / ALCOA+ audit: SHA-256 hash chain, append-only JSONL, tamper detection, gzip archive |
| `services/daq_service/archive_manager.py` | 562 | Data archival and retention management |

### Section 6: Monitoring & Notifications

| File | LOC | Purpose |
|------|-----|---------|
| `services/daq_service/notification_manager.py` | 711 | Twilio SMS + SMTP email. Rate limiting, quiet hours, templates, queue with retry |
| `services/daq_service/watchdog.py` | 547 | Heartbeat monitoring, hang detection, auto-recovery |
| `services/daq_service/watchdog_engine.py` | 502 | Multi-channel watchdog monitoring with timeout actions |
| `services/daq_service/azure_iot_uploader.py` | 421 | Azure IoT Hub integration (runs in isolated venv due to paho-mqtt <2.0 conflict) |

### Section 7: cRIO Node (Remote Controller)

Deployed to NI cRIO hardware. Independent of PC — can survive PC disconnection.

| File | LOC | Purpose |
|------|-----|---------|
| `services/crio_node_v2/crio_node.py` | 1,760 | Main cRIO service: event loop, MQTT commands, hardware read, script exec, safety checks. Error threshold 3, safety write retry, hardware health publishing |
| `services/crio_node_v2/script_engine.py` | 1,777 | Script sandbox (same API as DAQ service). 4 Hz rate limiting via TokenBucketRateLimiter. **MUST keep blocked lists in sync with script_manager.py** |
| `services/crio_node_v2/hardware.py` | 1,195 | NI-DAQmx abstraction for cRIO modules. Falls back to MockHardware if nidaqmx unavailable. IndexError guard on partial DI/AI reads (hot-unplug safe) |
| `services/crio_node_v2/state_machine.py` | 215 | cRIO state machine: IDLE → ACQUIRING → SESSION |
| `services/crio_node_v2/mqtt_interface.py` | 337 | paho-mqtt wrapper with auto-reconnect and TLS |
| `services/crio_node_v2/safety.py` | 1,855 | ISA-18.2 alarms + IEC 61511 interlocks. Alarms: shelving (SHELVED/OUT_OF_SERVICE), off-delay, rate-of-change, COMM_FAIL for missing channels, alarm flood detection, safety actions (dict + legacy string). Interlocks: condition evaluation, latch state machine (SAFE/ARMED/TRIPPED), `channel_offline` flag, safe state per channel, bypass with expiry, demand counting. Output blocking prevents script/MQTT override of safety-held outputs. **Synced to opto22_node/safety.py** |
| `services/crio_node_v2/config.py` | 520 | Config loading and channel scaling |
| `services/crio_node_v2/channel_types.py` | 299 | Channel type definitions and NI module mappings |
| `services/crio_node_v2/audit_trail.py` | ~150 | Lightweight audit trail: SHA-256 hash chain, append-only JSONL, 10 MB rotation with gzip |

### Section 8: Opto22 Node (Remote Controller)

Deployed to Opto22 groov EPIC/RIO. **Hybrid CODESYS + Python architecture**: CODESYS runtime handles deterministic PID and interlocks via IEC 61131-3 Structured Text, Python companion handles scripts, sequencing, MQTT orchestration, and serves as automatic fallback when CODESYS is unavailable.

**Runtime modes** (auto-switching, see `opto22_node.py:1190`):
- **CODESYS mode**: PID loops and interlocks execute in PLC (1 ms cycle). Python reads PID outputs and interlock status via Modbus TCP, pushes setpoints/commands, publishes to MQTT.
- **Python fallback mode**: If CODESYS connection lost (3 consecutive errors or 5 s timeout), Python PID engine and safety.py take over automatically. Logged as `"CODESYS lost — falling back to Python PID/safety"`.

**Core:**

| File | LOC | Purpose |
|------|-----|---------|
| `services/opto22_node/opto22_node.py` | 1,350 | Main service orchestrator: dual MQTT, scan loop, CODESYS/Python mode switching, command dispatch, stale I/O detection |
| `services/opto22_node/state_machine.py` | ~200 | States: IDLE → CONNECTING_MQTT → ACQUIRING → SESSION |
| `services/opto22_node/mqtt_interface.py` | ~375 | Dual MQTT: SystemMQTT (NISystem broker, TLS) + GroovMQTT (groov Manage, local). Both have `reconnect()` |
| `services/opto22_node/hardware.py` | ~310 | GroovIOSubscriber (MQTT I/O with stale detection) + GroovRestFallback (REST API). HardwareInterface auto-wires groov MQTT → subscriber |
| `services/opto22_node/config.py` | ~590 | NodeConfig, ChannelConfig, CODESYSConfig, groov MQTT + REST settings |
| `services/opto22_node/channel_types.py` | ~300 | ChannelType enum + Opto22 module database (GRV-series) |

**CODESYS integration layer:**

| File | LOC | Purpose |
|------|-----|---------|
| `services/opto22_node/codesys_bridge.py` | ~525 | Modbus TCP bridge to CODESYS runtime (localhost:502). Structured + tag-map modes. Heartbeat, health monitoring, `codesys_available` property for mode switching |
| `services/opto22_node/codesys/register_map.py` | ~460 | Modbus register allocation: 50 PID loops, 50 interlocks, 100 channels, 50 outputs. Holding/input regs, coils, discrete inputs. No-overlap validation |
| `services/opto22_node/codesys/st_codegen.py` | ~350 | IEC 61131-3 Structured Text code generator. Produces FB_PID_Loop, FB_Interlock, FB_SafeState, GVL_Registers, Main from project config |
| `services/opto22_node/codesys/templates/*.st.j2` | 5 files | Jinja2 templates for ST function blocks, GVL, and Main program |

**Python fallback engines (active when CODESYS unavailable):**

| File | LOC | Purpose |
|------|-----|---------|
| `services/opto22_node/pid_engine.py` | ~120 | PID loops: auto/manual/cascade, anti-windup, derivative-on-PV |
| `services/opto22_node/sequence_manager.py` | ~130 | Server-side sequences: setOutput, wait, condition, loops |
| `services/opto22_node/trigger_engine.py` | ~50 | Rising-edge threshold detection → actions |
| `services/opto22_node/watchdog_engine.py` | ~60 | Stale data + out-of-range monitoring with recovery |

**Safety & scripting (always active, shared with cRIO v2):**

| File | LOC | Purpose |
|------|-----|---------|
| `services/opto22_node/script_engine.py` | ~1,800 | Script sandbox (same API as DAQ service). 4 Hz rate limiting. **MUST keep blocked lists in sync with script_manager.py** |
| `services/opto22_node/safety.py` | 1,855 | Synced copy of cRIO safety.py (logger='Opto22Node'). ISA-18.2 alarms + IEC 61511 interlocks, COMM_FAIL, channel_offline. Runs as monitoring layer even in CODESYS mode. **MUST stay in sync with crio_node_v2/safety.py** |
| `services/opto22_node/audit_trail.py` | ~150 | SHA-256 hash chain, append-only JSONL, 10 MB rotation |

### Section 9: Other Device Services

| File | LOC | Purpose |
|------|-----|---------|
| `services/cfp_node/cfp_node.py` | ~800 | CFPNodeV2: modular Modbus-to-MQTT bridge for NI CompactFieldPoint (cFP-18xx/20xx). pymodbus, TLS, safety, audit trail, state machine (same architecture as cRIO v2) |
| `services/cfp_node/mqtt_interface.py` | ~290 | paho-mqtt wrapper with TLS + auto-reconnect (synced from cRIO v2) |
| `services/cfp_node/state_machine.py` | ~215 | IDLE → ACQUIRING → SESSION state machine (synced from cRIO v2) |
| `services/cfp_node/safety.py` | ~1,855 | ISA-18.2 alarms + IEC 61511 interlocks (synced from cRIO v2, logger='CFPNode'). **MUST stay in sync with crio_node_v2/safety.py** |
| `services/cfp_node/audit_trail.py` | ~150 | SHA-256 hash chain, append-only JSONL, 10 MB rotation (synced from cRIO v2) |
| `services/cfp_node/config.py` | ~310 | CFPChannelConfig, CFPNodeConfig, Modbus-specific config types, v1→v2 migration |
| `services/azure_uploader/azure_uploader_service.py` | 574 | Azure IoT Hub uploader (isolated process, paho-mqtt <2.0) |
| `services/service_manager.py` | 749 | Service lifecycle management (start/stop/status/logs) |
| `services/node_deploy.py` | 821 | Remote deployment via SSH/SCP with rollback |
| `services/device_cli.py` | 800+ | Interactive CLI for device management |

**Deprecated** (replaced by crio_node_v2 — do NOT use):
- `services/crio_node/crio_node.py` (7,715 LOC)
- `services/crio_service/crio_service.py` (1,385 LOC)

### Section 10: Build & Deployment Scripts

| File | LOC | Purpose |
|------|-----|---------|
| `scripts/build_exe.py` | 1,000 | PyInstaller compilation → `dist/ICCSFlux-Portable/` |
| `scripts/build_portable.py` | 1,359 | Full portable build with dependency vendoring |
| `scripts/supervisor.py` | 320 | Process supervisor: auto-restart, exponential backoff, graceful shutdown |
| `scripts/download_dependencies.py` | 466 | Populate `vendor/` for offline builds |
| `scripts/run_crio_v2.py` | 248 | cRIO service entry point |
| `scripts/create_boiler_project.py` | 324 | Demo project generator |
| `scripts/ICCSFlux_exe.py` | 484 | Windows .exe wrapper for frontend |
| `scripts/generate_tls_certs.py` | 209 | Self-signed TLS certificate generation |
| `scripts/cleanup_portable.py` | 263 | Remove old portable builds |
| `scripts/mqtt_credentials.py` | 124 | MQTT credential generation (auto-generated at first run, chmod 600) |
| `scripts/write_crio_creds.py` | 39 | Generate cRIO credential JSON for deploy_crio_v2.bat (avoids CMD parenthesis issues) |
| `scripts/read_mqtt_creds.py` | 22 | Read MQTT credentials → print user:pass for deploy_crio_v2.bat |
| `scripts/deploy_opto22.py` | 345 | 10-step Opto22 deploy pipeline (SSH/SCP, systemd, CODESYS ST files, safety verification) |
| `scripts/run_opto22.py` | 196 | Opto22 service entry point (on groov EPIC). Rotating log, signal handlers, credential loading |
| `scripts/opto22_init_service.sh` | ~30 | systemd unit file for opto22_node service (SCP'd to `/etc/systemd/system/`) |
| `scripts/clear_retained_mqtt.py` | 34 | Clear retained MQTT acquire messages after cRIO deploy |
| `scripts/generate_codesys_st.py` | ~170 | CLI: generate CODESYS Structured Text from project JSON (PID loops, interlocks, channels → 5 ST files) |

### Section 11: Dashboard — Core & Stores

| File | LOC | Purpose |
|------|-----|---------|
| `dashboard/src/App.vue` | 1,564 | Application shell: tab routing, MQTT setup, startup dialogs, project recovery |
| `dashboard/src/main.ts` | 11 | Vue 3 entry point |
| `dashboard/src/stores/dashboard.ts` | 3,410 | Pinia central store: widgets, pages, channels, values, status, P&ID, recording, variables |
| `dashboard/src/types/index.ts` | 1,976 | Master types: ChannelConfig, WidgetConfig, SystemStatus, AlarmConfig, PidSymbol, etc. |
| `dashboard/src/types/scripts.ts` | 2,183 | Script types: CalculatedParam, SequenceStep (25+ subtypes), TriggerConfig |
| `dashboard/src/types/python-scripts.ts` | 509 | Pyodide Python integration types |

### Section 12: Dashboard — Composables (26 hooks)

| File | LOC | Purpose |
|------|-----|---------|
| `composables/useMqtt.ts` | 2,156 | MQTT WebSocket client: connect, subscribe, sendCommand, onData, onStatus |
| `composables/useScripts.ts` | 3,852 | Script evaluation: sequences, calculated params, formulas, triggers |
| `composables/useSafety.ts` | 2,319 | Alarm & interlock management: evaluate, acknowledge, shelve, bypass |
| `composables/usePythonScripts.ts` | 1,503 | Pyodide Python runtime: initPython, runScript, captureOutput |
| `composables/useProjectFiles.ts` | 1,129 | Project I/O: load, save, markDirty, backend autosave |
| `composables/usePlayground.ts` | 699 | Test session management |
| `composables/useProjectManager.ts` | 698 | Multi-project support |
| `composables/useBackendScripts.ts` | 628 | Remote script execution on backend |
| `composables/useNotebook.ts` | 595 | Markdown experiment notebooks |
| `composables/useAuth.ts` | 524 | Authentication & session: login, logout, roles (Guest/Operator/Supervisor/Admin) |
| `composables/useTheme.ts` | ~200 | Dark/light mode toggle |
| `composables/useHistoricalData.ts` | ~200 | Recording playback |
| `composables/useCrio.ts` | ~180 | cRIO remote management |
| `composables/useAzureIot.ts` | ~150 | Azure IoT Hub integration |
| `composables/useSOE.ts` | ~120 | Sequence of Events |
| `composables/useTagDependencies.ts` | ~100 | Dependency graph analysis |
| `composables/useWindowSync.ts` | ~100 | Multi-monitor window position memory |

### Section 13: Dashboard — Tab Components

| File | LOC | Purpose |
|------|-----|---------|
| `components/ConfigurationTab.vue` | 10,678 | Channel/device configuration: device discovery, cDAQ/cRIO/Fieldpoint/Modbus/OPC-UA/EtherNet-IP/REST setup |
| `components/ScriptsTab.vue` | 6,468 | Script editor: sequence builder, calculated params, Monaco editor, triggers |
| `components/SafetyTab.vue` | 4,348 | Alarm & interlock configuration: ISA-18.2 thresholds, voting logic, bypass |
| `components/DataTab.vue` | 3,796 | Recording configuration: CSV/TDMS, rotation, ALCOA+, decimation, database |
| `components/PidCanvas.vue` | 4,439 | P&ID editor: symbols, pipes, layers, rulers, guides, auto-routing, inline editing |
| `components/PlaygroundTab.vue` | 1,503 | Test session UI |
| `components/VariablesTab.vue` | 1,296 | User variable management |
| `components/AdminTab.vue` | 1,182 | User management: roles, permissions |
| `components/NotebookTab.vue` | 880 | Markdown notebook with Python cells |
| `components/SessionTab.vue` | 631 | Test session history |

### Section 14: Dashboard — P&ID Editor Components

| File | LOC | Purpose |
|------|-----|---------|
| `components/PidToolbar.vue` | 1,445 | Edit tools: select, draw, delete, group, align, rulers, layers, auto-route |
| `components/PidPropertiesPanel.vue` | 1,081 | Symbol/pipe properties: type, rotation, label, channel binding, line style, linked page |
| `components/PidFaceplate.vue` | 610 | Runtime popup: value display, control slider, trend sparkline |
| `components/PidSymbolPanel.vue` | ~500 | Symbol library (50+ SCADA symbols): search, categories, drag-to-canvas |
| `components/PidLayerPanel.vue` | ~400 | Layer management: show/hide, lock, opacity, reorder |
| `components/PipeOverlay.vue` | 463 | Pipe connection UI: bezier, polyline, orthogonal routing |
| `components/PidContextMenu.vue` | ~200 | Right-click: copy, paste, delete, group, align |
| `assets/symbols/index.ts` | 2,093 | SVG symbol library: valves (9), pumps (3), tanks (4), heat exchangers (3), instruments (8+), piping (5+) |
| `utils/autoRoute.ts` | ~200 | A* pathfinding on orthogonal visibility graph for pipe routing |
| `constants/pidSymbols.ts` | 1,200+ | P&ID symbol metadata and categories |

### Section 15: Dashboard — Widgets (30+ types)

**Data Display:**

| File | LOC | Type |
|------|-----|------|
| `widgets/TrendChart.vue` | 2,406 | `chart` — uPlot (strip/scope/sweep), XY mode, cursors, thresholds |
| `widgets/SetpointWidget.vue` | 785 | `setpoint` — slider + numeric input for analog outputs |
| `widgets/HeaterZoneWidget.vue` | 692 | `heater_zone` — dual-loop temperature controller faceplate |
| `widgets/BarGraphWidget.vue` | 633 | `bar_graph` — horizontal/vertical bar with alarm zones |
| `widgets/PythonConsoleWidget.vue` | 572 | `python_console` — interactive Pyodide REPL |
| `widgets/SystemStatusWidget.vue` | 551 | `system_status` — connection, CPU, memory, uptime |
| `widgets/VariableExplorerWidget.vue` | 509 | `variable_explorer` — IPython-like variable inspector |
| `widgets/ActionButtonWidget.vue` | 620 | `action_button` — trigger sequences/MQTT with interlock check |
| `widgets/PidLoopWidget.vue` | 470 | `pid_loop` — PID faceplate (PV, SP, CV, MV) |
| `widgets/LedIndicator.vue` | 456 | `led` — boolean on/off indicator |
| `widgets/LatchSwitchWidget.vue` | 433 | `latch_switch` — safety latch button |
| `widgets/VariableInputWidget.vue` | 430 | `variable_input` — user parameter input |
| `widgets/TitleLabel.vue` | 408 | `title` — static text/section header |
| `widgets/NumericDisplay.vue` | ~250 | `numeric` — value + unit with alarm background |
| `widgets/ToggleSwitch.vue` | ~250 | `toggle` — digital output ON/OFF |
| `widgets/SparklineWidget.vue` | ~350 | `sparkline` — mini trend + current value |
| `widgets/GaugeWidget.vue` | ~350 | `gauge` — circular gauge with colored zones |
| `widgets/StatusMessages.vue` | 664 | `(overlay)` — scrolling status message log |

Plus: `ValueTableWidget`, `AlarmSummaryWidget`, `RecordingStatusWidget`, `SchedulerStatusWidget`, `InterlockStatusWidget`, `CrioStatusWidget`, `ScriptMonitorWidget`, `ScriptOutputWidget`, `ClockWidget`, `SvgSymbolWidget`, `DividerWidget`

**Widget registry:** `widgets/index.ts` (294 lines) — component metadata and lazy loading

### Section 16: Dashboard — ISA-101 HMI Controls (12 components)

Located in `components/hmi/`. HTML-based (not SVG). Support backend alarm flags and HMI threshold overrides.

| File | Type | Purpose |
|------|------|---------|
| `HmiNumericIndicator.vue` | `hmi_numeric` | Value display with alarm coloring |
| `HmiStatusLed.vue` | `hmi_led` | Boolean indicator LED |
| `HmiToggleControl.vue` | `hmi_toggle` | Digital output toggle |
| `HmiSetpointControl.vue` | `hmi_setpoint` | Slider/knob control |
| `HmiBarIndicator.vue` | `hmi_bar` | Horizontal/vertical bar indicator |
| `HmiArcGauge.vue` | `hmi_gauge` | Circular arc gauge |
| `HmiMultiStateIndicator.vue` | `hmi_multistate` | Multi-value state indicator |
| `HmiCommandButton.vue` | `hmi_button` | Action button |
| `HmiSelectorSwitch.vue` | `hmi_selector` | Multi-position selector |
| `HmiAlarmAnnunciator.vue` | `hmi_annunciator` | Alarm banner/annunciator |
| `HmiTrendSparkline.vue` | `hmi_sparkline` | Mini trend sparkline |
| `HmiValvePosition.vue` | `hmi_valve_pos` | Valve position graphic |

Registry: `constants/hmiControls.ts` (350+ lines) — HMI control catalog with SVG thumbnails

### Section 17: Dashboard — Device Configuration Components

| File | LOC | Purpose |
|------|-----|---------|
| `components/CompactFieldpointDeviceConfig.vue` | 1,458 | NI CompactFieldPoint setup |
| `components/RestApiDeviceConfig.vue` | 1,324 | REST API polling client |
| `components/OpcUaDeviceConfig.vue` | 1,204 | OPC-UA server connection |
| `components/EtherNetIPDeviceConfig.vue` | 1,186 | Allen-Bradley EtherNet/IP scanner |
| `components/ModbusDeviceConfig.vue` | 1,004 | Modbus RTU/TCP slave setup |
| `components/ModbusAddressChanger.vue` | ~300 | Bulk Modbus address reassignment |

### Section 18: Dashboard — Dialogs & Utility Components

| File | LOC | Purpose |
|------|-----|---------|
| `components/WidgetConfigModal.vue` | 1,878 | Widget properties editor (30+ widget config forms) |
| `components/PythonScriptsTab.vue` | 1,729 | Python script editor (Pyodide) |
| `components/AlarmConfigModal.vue` | 1,400 | Alarm threshold editor (ISA-18.2) |
| `components/SafetyActionsPanel.vue` | 989 | Safety action buttons (emergency stop, reset) |
| `components/DashboardGrid.vue` | 708 | grid-layout-plus wrapper: drag/drop/resize, multi-select |
| `components/FormulaEditor.vue` | 718 | Expression editor with syntax highlighting |
| `components/ProjectManager.vue` | 599 | Project listing, delete, rename |
| `components/CorrelationRuleModal.vue` | 543 | Alarm correlation logic |
| `components/PageSelector.vue` | 540 | Page tab navigation + drag-to-move |
| `components/LoginDialog.vue` | ~500 | Authentication UI |
| `components/ConnectionOverlay.vue` | ~250 | MQTT connection status banner |
| `components/NotificationToast.vue` | ~200 | System notifications |
| `components/InterlockBlockOverlay.vue` | ~200 | Safety block indicator |

### Section 19: Dashboard — Utilities & Assets

| File | LOC | Purpose |
|------|-----|---------|
| `utils/pyodideLoader.ts` | 592 | Lazy-load Pyodide Python runtime from CDN |
| `utils/formatUnit.ts` | ~100 | Unit conversion (degC/degF, psi/bar, inches/mm) |
| `utils/autoRoute.ts` | ~200 | A* orthogonal pipe routing |

### Section 20: Testing

**558 unit tests** (no external deps required):

```bash
python -m pytest tests/test_daq_orchestration.py tests/test_longevity.py tests/test_security_and_resilience.py tests/test_crio_script_engine_unit.py tests/test_recording_manager.py tests/test_session_and_recording.py tests/test_script_helpers.py tests/test_safety_manager.py tests/test_hot_unplug_resilience.py -v
```

| File | Tests | Coverage |
|------|-------|---------|
| `test_daq_orchestration.py` | 68 | State machine, alarm manager, script manager (Counter, sandbox), channel config, recording config |
| `test_longevity.py` | 32 | Counter rollover at 2^32, cumulative mode, midnight reset, notification queue overflow, cooldown pruning, session cleanup |
| `test_security_and_resilience.py` | 98 | Sandbox security (imports, dunders, builtins, escapes, safe ops, blocked list sync), notification manager, state persistence |
| `test_crio_script_engine_unit.py` | 75 | RateCalculator, Accumulator, EdgeDetector, RollingStats, SharedVariableStore, TagsAPI, OutputsAPI, SessionAPI, VarsAPI |
| `test_recording_manager.py` | 37 | Recording config, start/stop, decimation, time interval, channel selection, script values, filenames, directories, buffered/immediate mode, triggered recording, file rotation by samples, thread safety |
| `test_session_and_recording.py` | 63 | Session state validation (start guards, alarm checks), variable resets, timer management, callbacks (scheduler, recording, sequences), timeout, ALCOA+ integrity (SHA-256, tamper detection, read-only), rotation (size, samples, stop mode), circular mode, acquisition cascade |
| `test_script_helpers.py` | 104 | SignalFilter (EMA, tau/dt, convergence), LookupTable (interpolation, clamping, sorting), RampSoak (ramp/soak/reset), TrendLine (regression, predict, time_to_value), RingBuffer (wrap, stats, clear), PeakDetector (height/distance filtering, area), SpectralAnalysis (FFT, pure-Python fallback), SPCChart (Xbar/R, Western Electric rules, Cp/Cpk), BiquadFilter (LP/HP/BP/notch, cascade), DataLog (publish, marks), cRIO DAQ-only stubs |
| `test_safety_manager.py` | 47 | Interlock latch state machine (SAFE/ARMED/TRIPPED), condition evaluation (channel_value, digital_input, operators, delay), InterlockCondition/Control/Interlock serialization (to_dict, from_dict with camelCase↔snake_case compat), bypass with expiry, trip/reset system, auto-trip on interlock failure, output blocking, history recording, persistence, SafeStateConfig |
| `test_hot_unplug_resilience.py` | 34 | COMM_FAIL alarm (trigger, clear, dedup, shelve respect), channel_offline flag (DAQ + node), has_offline_channels in InterlockStatus, discovery staleness (is_stale, get_scan_age), Opto22 GroovIOSubscriber (stale detection, topic mapping, payload extraction), Opto22 HardwareInterface (construction, wiring, health) |

**Safety integration tests** (require MQTT broker): `python -m pytest tests/test_safety_interlocks.py -v` — 18 tests covering alarm lifecycle (latch, auto-clear, timed), acknowledge/reset, shelving, session interlocks, output blocking, first-out tracking, alarm history

**Integration tests** (require MQTT broker + DAQ service): `python -m pytest tests/`

**Dashboard tests** (Vitest): `cd dashboard && npx vitest run` — 41 test files, 2200+ tests covering stores, composables, widgets

**Dashboard type check + build**: `npm run build` in `dashboard/` (runs `vue-tsc -b && vite build`)

### Hardware-in-the-Loop (HIL) Tests

4-tier test suite in `tests/test_hardware_hil.py` for validating real NI hardware. Auto-starts Mosquitto silently — no manual `NISystem Start.bat` needed.

```bash
# Run all HIL tests (auto-starts MQTT broker):
python -m pytest tests/test_hardware_hil.py -v

# Run specific tier:
python -m pytest tests/test_hardware_hil.py -v -k "tier1"
python -m pytest tests/test_hardware_hil.py -v -k "tier4"
```

| Tier | Requires | Tests |
|------|----------|-------|
| Tier 1 — NI Driver | NI-DAQmx runtime installed | `nidaqmx` import, `System.local()`, driver version |
| Tier 2 — Local Hardware | cDAQ/cRIO physically connected | Device enumeration, module detection, channel listing, AI/TC/DI reads |
| Tier 3 — Loopback Wiring | AO→AI wired on same chassis | Write AO → read AI within tolerance, DI toggle verification |
| Tier 4 — MQTT + Services | MQTT broker (auto-started) | Broker connectivity, DAQ service status, cRIO node online, Opto22 node online |

**Test infrastructure files:**

| File | Purpose |
|------|---------|
| `tests/test_hardware_hil.py` | HIL test suite (4 tiers) |
| `tests/service_fixtures.py` | Auto-start/stop Mosquitto and DAQ service for pytest |
| `tests/conftest.py` | Session-scoped `mqtt_broker` and `daq_service` fixtures |
| `tests/test_helpers.py` | `MQTTTestHarness` with auth support |

**Auto-start behavior:** The `mqtt_broker` session fixture in `conftest.py` checks if port 1883 is already open. If not, it finds `mosquitto.exe` (in `vendor/` or Program Files), writes a minimal test config, and starts it silently. On teardown, only services we started are terminated. If Mosquitto was already running (user ran `NISystem Start.bat`), it is reused and not killed.

**Reference hardware (cRIO-9056 at 192.168.1.20):**

| Slot | Module | Type | Wiring |
|------|--------|------|--------|
| Mod1 | NI 9202 | 16 AI (voltage) | AO loopback from Mod2 |
| Mod2 | NI 9264 | 16 AO (voltage) | Wired to Mod1 AI |
| Mod3 | NI 9425 | 32 DI (spring) | 2 switches on ch0-1 |
| Mod4 | NI 9472 | 8 DO | 4 relays on ch0-1 |
| Mod5 | NI 9213 | 16 TC | TC on ch0 only |
| Mod6 | NI 9266 | 8 AO (current) | Wired to Mod7 CI (CO loopback) |
| Mod7 | NI 9208 | 8 CI (4-20mA current) | CO loopback from Mod6 |

### cRIO Hardware Acquisition Test Suite

**81-test end-to-end validation** of the full cRIO hardware acquisition pipeline. Tests are grouped and run in order (pytest-ordering); each group depends on prior groups passing.

**No manual startup required** — the `mqtt_broker` and `daq_service` session fixtures auto-start Mosquitto (ports 1883 + 8883 TLS + 9002 WS) and the DAQ service. Only the cRIO itself must be powered on.

**Prerequisites (hardware only):**
- cRIO-9056 powered on and accessible at 192.168.1.20 (service starts at boot via `/etc/init.d/crio_node`)
- Loopback wiring in place: AO Mod2→AI Mod1, DO Mod4→DI Mod3, CO Mod6→CI Mod7 (ai0-7)
- Mod7 ai8-ai15 must be unwired (used for open-circuit detection — naturally reads ~0mA)

```bash
# Full suite (81 tests) — auto-starts broker + DAQ service
python -m pytest tests/test_crio_acquisition.py -v --tb=short

# Individual groups
python -m pytest tests/test_crio_acquisition.py -v -k "Group1"
python -m pytest tests/test_crio_acquisition.py -v -k "Group11 or Group12 or Group13"
python -m pytest tests/test_crio_acquisition.py -v -k "Group14"

# New groups only (faster iteration on command/safety features)
python -m pytest tests/test_crio_acquisition.py -v -k "Group11 or Group12 or Group13 or Group14"
```

| Group | Tests | What it validates |
|-------|-------|-------------------|
| 1 — Infrastructure | 7 | MQTT online, cRIO node heartbeat, project load, acquisition start, NTP config, NTP sync status |
| 2 — Channel Discovery | 4 | All 105 channels arriving, channel count, group presence, module slots |
| 3 — Thermocouple (Mod5) | 4 | TC readings realistic (−40–250°C), TC type, open-sensor detection |
| 4 — Analog Input (Mod1) | 5 | AI baseline, accuracy at 5V reference, noise floor, all 16 channels |
| 5 — Analog Output (Mod2) | 4 | AO write → AI read loopback accuracy at 0/2.5/5V |
| 6 — Digital Input (Mod3) | 4 | DI channel count, debounce, switch state |
| 7 — Digital Output (Mod4) | 4 | DO write → DI read loopback, relay states |
| 8 — AO→AI Full Sweep | 5 | Multi-point sweep 0–10V, linearity, hysteresis, channel cross-talk |
| 9 — AO/AI Simultaneous | 6 | Simultaneous multi-channel AO→AI, scan-rate timing, update rate |
| 10 — Safety Interlocks | 8 | DI interlock condition, latch arm/trip/reset, DO safe state, bypass, output blocking |
| 11 — Alarms | 8 | Alarm config push, Hi alarm fires on AO→AI loopback, acknowledge, clear on return, shelve suppresses, unshelve fires, OOS suppresses, cleanup |
| 12 — Scripts | 6 | Script add/start/stop/remove on real cRIO, script publishes computed values, clear-all |
| 13 — Interlock Bypass | 5 | Configure bypass-allowed interlock, bypass suppresses trip, unbypass restores trip, cleanup |
| 14 — Current I/O (Mod6/7) | 7 | CI channels arriving, CO→CI loopback accuracy, all 8 channels at 12mA, ramp monotonicity, 4-20mA scaling (0/50/100%), open-circuit detection (CI_Mod7_ch08 = Mod7/ai8, physically unwired, reads ~0mA, LOLO fires), cleanup |

**Test project:** `config/projects/_CrioAcquisitionTest.json` — 105 channels across 7 modules. Mod7: ai0-7 wired (CO loopback from Mod6), ai8 unwired (genuine open-circuit for LOLO detection). Alarm on AI_Mod1_ch00 (Hi/HiHi for Group 11) and CI_Mod7_ch08 (LoLo, always active as open-circuit alarm).

**Key file:** `tests/test_crio_acquisition.py`

**Skip behavior:** Groups 2-14 auto-skip if acquisition is not running (Group 1 must pass first). Groups 10-13 auto-skip if earlier safety/script infrastructure is missing.

**NTP tests (Group 1):** SSH into cRIO, read `/etc/ntp.conf`, verify `minpoll 4 maxpoll 6` polling parameters; run `ntpq -p`, verify a synced peer (`*`), and clock offset < 1000ms. Skips with a note if NTP is still converging.

### DHWSIM cDAQ 72-Hour Soak Test

**20-test sustained operation validation** of the cDAQ-9189-DHWSIM chassis. 5 groups: infrastructure → project/acquisition → baseline capture → continuous soak loop → post-soak validation.

**No manual startup required** — auto-starts Mosquitto + DAQ service. Only the DHWSIM cDAQ must be visible in NI MAX.

**Prerequisites:**
- cDAQ-9189-DHWSIM visible in NI MAX (6 modules: NI 9213, NI 9205, NI 9203, NI 9375×2, NI 9264)
- Project file: `config/projects/_DhwSimSoakTest.json` (88 channels, generated by `scripts/create_dhwsim_soak_project.py`)

```bash
# Full 72-hour soak:
python -m pytest tests/test_dhwsim_soak.py -v -s

# Quick 1-hour smoke test:
SOAK_HOURS=1 python -m pytest tests/test_dhwsim_soak.py -v -s

# 15-minute dry run:
SOAK_HOURS=0.25 python -m pytest tests/test_dhwsim_soak.py -v -s

# Setup + baseline only (no soak loop):
python -m pytest tests/test_dhwsim_soak.py -v -k "Group1 or Group2 or Group3"

# Regenerate project config:
python scripts/create_dhwsim_soak_project.py
```

| Group | Tests | What it validates |
|-------|-------|-------------------|
| 1 — Infrastructure | 4 | MQTT broker, DAQ service online, admin login, WebSocket |
| 2 — Project & Acquisition | 5 | Project load, channel config, acquisition start, data flow, recording |
| 3 — Baseline | 5 | TC/AI/CI/DI baseline readings, system health baseline |
| 4 — Continuous Soak | 1 | Long-running checkpoint loop: channel dropouts, memory, jitter, alarms, MQTT stability |
| 5 — Post-Soak | 5 | Stop recording, verify files, stop acquisition, final status, report |

**Environment variables:**

| Variable | Default | Purpose |
|----------|---------|---------|
| `SOAK_HOURS` | 72 | Total soak duration |
| `CHECKPOINT_MINUTES` | 15 | Minutes between health checks |
| `DHWSIM_DEVICE` | cDAQ-9189-DHWSIM | NI MAX device name |
| `SOAK_RECORD` | 1 | Enable CSV recording (0 to disable) |
| `SOAK_MAX_MEMORY_MB` | 2048 | Memory ceiling before FAIL |
| `SOAK_MAX_DROPOUT_PCT` | 5 | Max channel dropout % per checkpoint |
| `SOAK_MAX_JITTER_MS` | 50 | Max scan timing jitter |

**Output files:**
- `data/logs/soak_report.txt` — human-readable final report with PASS/FAIL verdict
- `data/logs/soak_checkpoints.json` — machine-readable checkpoint history
- `data/*.csv` — recorded channel data (if SOAK_RECORD=1)

**DHWSIM module map (88 channels):**

| Slot | Module | Channels | Group | Physical |
|------|--------|----------|-------|----------|
| Mod1 | NI 9213 | 16 TC | Mod1_TC | `TC_M1_ch00`–`TC_M1_ch15` |
| Mod2 | NI 9205 | 16 AI | Mod2_AI | `AI_M2_ch00`–`AI_M2_ch15` |
| Mod3 | NI 9203 | 8 CI | Mod3_CI | `CI_M3_ch00`–`CI_M3_ch07` |
| Mod4 | NI 9375 | 16 DI | Mod4_DI | `DI_M4_ch00`–`DI_M4_ch15` |
| Mod5 | NI 9375 | 16 DO | Mod5_DO | `DO_M5_ch00`–`DO_M5_ch15` |
| Mod6 | NI 9264 | 16 AO | Mod6_AO | `AO_M6_ch00`–`AO_M6_ch15` |

### System Validation Suite (Field Diagnostics)

9-layer end-to-end diagnostic in `tests/test_system_validation.py`. Auto-starts Mosquitto + DAQ service — no manual setup needed. Kills stale processes from previous runs automatically.

```bash
# Full diagnostic (auto-starts everything):
python -m pytest tests/test_system_validation.py -v

# Quick infrastructure check (layers 1-3):
python -m pytest tests/test_system_validation.py -v -k "Layer1 or Layer2 or Layer3"

# Just data pipeline:
python -m pytest tests/test_system_validation.py -v -k "Layer4"

# Edge nodes only (cRIO/cFP/Opto22):
python -m pytest tests/test_system_validation.py -v -k "Layer5"
```

| Layer | Tests | What it validates |
|-------|-------|-------------------|
| 1 — Infrastructure | 4 | Mosquitto alive, MQTT auth, DAQ service online, heartbeat |
| 2 — Project & Config | 4 | Project load via MQTT, channel config published, project list/get |
| 3 — Acquisition Lifecycle | 4 | Start/stop/restart acquisition, state transitions |
| 4 — Data Pipeline | 4 | Channel values arriving, payload format, scan rate timing, valid simulation data |
| 5 — Edge Nodes | 4 | cRIO/cFP/Opto22 discovery and status (skips if not connected) |
| 6 — Alarms | 4 | Alarm config sync, active topic, acknowledge, reset |
| 7 — Safety & Interlocks | 4 | Interlock config loaded, arm latch, trip on condition, reset |
| 8 — Recording | 4 | Recording start/stop, file created on disk, sample count |
| 9 — Device Discovery | 2 | NI hardware scan, result format (skips if NI-DAQmx not installed) |

**Test project:** `config/projects/_SystemValidation_Test.json` — 4 simulated channels, 1 alarm, 1 interlock. Uses `simulation_mode: true` so layers 1-4, 6-8 work on any PC without hardware.

**Key files:**

| File | Purpose |
|------|---------|
| `tests/test_system_validation.py` | 9-layer diagnostic suite (34 tests) |
| `tests/service_fixtures.py` | Auto-start/stop Mosquitto + DAQ, stale process cleanup, TLS listener for edge nodes |
| `tests/conftest.py` | Session fixtures (`mqtt_broker`, `daq_service`, `ensure_test_admin`) |
| `config/projects/_SystemValidation_Test.json` | Minimal test project (simulation mode) |

**Expected results on healthy system (no edge hardware):**
```
Layer 1-4, 6-8: PASSED
Layer 5: 2-4 SKIPPED (no cFP/Opto22)  — cRIO passes if connected
Layer 9: PASSED (if NI-DAQmx installed) or SKIPPED
```

**Troubleshooting:**
- "DAQ service not publishing status" → stale processes; fixture now auto-kills them, but `taskkill /F /IM python.exe` clears manually
- "Mosquitto failed to start" → check if another Mosquitto instance holds port 1883
- Layer 5 skips → edge node not powered on, not on network, or TLS certs missing (`config/tls/`)
- Layer 7 interlock tests → condition semantics: `satisfied=True` means "safe state" (e.g., `TC < 100` = safe while below 100)

### Complete Field Test Workflow

Run backend + frontend validation together. The test broker includes a WebSocket listener (port 9002) so the dashboard connects during tests.

```bash
# Step 1: Run backend validation (auto-starts Mosquitto + DAQ service)
python -m pytest tests/test_system_validation.py -v

# Step 2: While services are still running, open the dashboard
cd dashboard && npm run dev
# Browse to http://localhost:5173 — dashboard connects via WebSocket on port 9002

# Step 3: Run dashboard unit tests (separate terminal, no MQTT needed)
cd dashboard && npx vitest run

# Step 4: Type check + production build
cd dashboard && npm run build
```

**What the dashboard shows during validation tests:**
- Live channel values (TC_VAL_01, TC_VAL_02, AO_VAL_01, DI_VAL_01) updating at 4 Hz
- Alarm events firing and clearing as Layer 6 runs
- Interlock state changes (SAFE → ARMED → TRIPPED → reset) during Layer 7
- Recording indicator toggling during Layer 8
- cRIO status (if connected) during Layer 5

**Test broker listeners (matches production):**

| Port | Transport | Auth | Purpose |
|------|-----------|------|---------|
| 1883 | TCP | Authenticated | Backend services (DAQ, tests) |
| 8883 | TCP + TLS | Authenticated | Edge nodes (cRIO, Opto22, cFP) |
| 9002 | WebSocket | Anonymous | Dashboard (localhost only) |

---

## Portable Build

```cmd
build.bat                    # Full build (requires PyInstaller, npm, vendor/mosquitto)
python scripts/build_exe.py  # Direct invocation (preferred from Claude Code — see above)
```

- Azure uploader builds in an **isolated venv** (`build/azure-venv/`) because it requires paho-mqtt <2.0 while the main project uses paho-mqtt >=2.0
- Offline builds use `--no-index --find-links vendor/azure-packages/` — no internet required
- `scripts/download_dependencies.py` populates `vendor/` with all offline dependencies
- Build output includes `VERSION.txt` with git hash, branch, and timestamp

## cRIO Deployment

**ALWAYS use `deploy_crio_v2.bat` when deploying changes to the cRIO.**

```cmd
deploy_crio_v2.bat [crio_host] [broker_host]
```

Default values:
- crio_host: 192.168.1.20
- broker_host: 192.168.1.1

**DO NOT manually scp individual files** — use the deploy script to ensure all files are deployed together and the service is properly restarted.

### Deploy Script Architecture

`deploy_crio_v2.bat` is a thin wrapper that calls `scripts/deploy_crio.py`. All deploy logic is in Python to avoid CMD escaping issues with SSH, shell scripts, and inline Python.

**SAFETY**: The deploy enforces exactly ONE cRIO process at all times. Duplicate processes are a split-brain interlock hazard. The deploy verifies zero processes before deploying and exactly one process after starting.

**Service management**: The cRIO service is managed by `/etc/init.d/crio_node` (source: `scripts/crio_init_service.sh`). This is the SINGLE authority for process lifecycle — it auto-restarts on crash and starts on boot. The service runs `run_crio_v2.py` which loads credentials from `mqtt_creds.json`.

**MQTT resilience**: `crio_node.py:run()` retries MQTT connection with exponential backoff (5s → 60s max). The node never exits on broker unavailability — it keeps retrying until the broker comes up or SIGTERM is received.

| Deploy Script/Helper | Purpose |
|---------------------|---------|
| `scripts/deploy_crio.py` | Main deploy logic (SSH/SCP, safety checks, service install) |
| `scripts/crio_init_service.sh` | init.d service script (SCP'd to `/etc/init.d/crio_node`) |
| `scripts/write_crio_creds.py` | Generate cRIO credential JSON file |
| `scripts/read_mqtt_creds.py` | Read `config/mqtt_credentials.json` → print `user:pass` |
| `scripts/verify_crio_process.sh` | Verify exactly 1 cRIO process (safety check) |
| `scripts/check_crio_stopped.sh` | Verify 0 cRIO processes (pre-deploy safety) |

### CMD Batch File Pitfalls

**Never put complex logic in .bat files.** CMD cannot handle `$`, `()`, `#`, heredocs, or any characters that shell scripts/Python need. Always put logic in Python scripts or `.sh` files and SCP them. The bat file should only be a thin wrapper.

## Opto22 Deployment

**ALWAYS use `deploy_opto22.bat` when deploying changes to the groov EPIC.**

```cmd
deploy_opto22.bat [epic_host] [broker_host]
```

Default values:
- epic_host: 192.168.1.30
- broker_host: 192.168.1.1

**DO NOT manually scp individual files** — use the deploy script to ensure all files, CODESYS templates, and credentials are deployed together.

### Hybrid Architecture Overview

The Opto22 node runs as a **Python + CODESYS hybrid** on the groov EPIC:

```
┌──────────────────────────────────────────────────────┐
│  groov EPIC                                          │
│                                                      │
│  ┌──────────────┐     Modbus TCP     ┌────────────┐  │
│  │ Python Node  │◄──────────────────►│  CODESYS   │  │
│  │ (companion)  │    localhost:502    │  Runtime   │  │
│  │              │                    │            │  │
│  │ • Scripts    │  ── setpoints ──►  │ • PID      │  │
│  │ • Sequences  │  ── commands ──►   │ • Interlock│  │
│  │ • MQTT pub   │  ◄── PV/CV ──     │ • Safe     │  │
│  │ • Safety     │  ◄── status ──     │   state    │  │
│  │   (fallback) │  ── heartbeat ──►  │ • Watchdog │  │
│  └──────┬───────┘                    └──────┬─────┘  │
│         │                                   │        │
│    MQTT (TLS)                          groov I/O     │
│    port 8883                          (native scan)  │
│         │                                   │        │
└─────────┼───────────────────────────────────┼────────┘
          │                                   │
          ▼                                   ▼
    NISystem Broker                    Physical I/O
    (PC, port 8883)                    (GRV modules)
```

**CODESYS runs PID and interlocks at 1 ms cycle** — deterministic, not affected by Python GC or OS scheduling. Python pushes setpoints and reads outputs via Modbus. If CODESYS goes down, Python PID/safety engines activate automatically.

### Deploy Script Architecture

`deploy_opto22.bat` is a thin wrapper that calls `scripts/deploy_opto22.py`. 10-step pipeline:

1. SSH connectivity check (user `dev`)
2. Stop all processes (split-brain prevention: exactly ONE process allowed)
3. Python 3 verification on EPIC
4. Dependency checks (paho-mqtt required, pymodbus for CODESYS bridge)
5. Deploy files via SCP (15 Python modules + CODESYS package + templates)
6. Write MQTT credentials (`mqtt_creds.json`, chmod 600)
7. Import verification (test Python imports on EPIC)
8. Deploy generated ST files from `dist/codesys_st/` (if present)
9. Install and start systemd service (`opto22_node.service`)
10. Safety verification (exactly 1 process running)

**Service management**: systemd unit at `/etc/systemd/system/opto22_node.service` (source: `scripts/opto22_init_service.sh`). `Restart=always`, `RestartSec=5`, security-hardened (`NoNewPrivileges`, `ProtectSystem=strict`).

| Deploy Script/Helper | Purpose |
|---------------------|---------|
| `scripts/deploy_opto22.py` | Main deploy logic (SSH/SCP, safety checks, systemd install) |
| `scripts/run_opto22.py` | Service entry point on EPIC (rotating log, signal handlers, credential loading) |
| `scripts/opto22_init_service.sh` | systemd unit file (SCP'd to `/etc/systemd/system/opto22_node.service`) |

### CODESYS Structured Text Workflow

The ST code is **generated from project config**, not hand-written:

```bash
python scripts/generate_codesys_st.py config/projects/MyProject.json
```

```
Project JSON ──► generate_codesys_st.py ──► dist/codesys_st/*.st ──► CODESYS IDE ──► groov EPIC PLC
(with pidLoops)    (reads PID, interlocks,     (5 files)              (manual import)
                    channels from JSON)
```

**IMPORTANT**: PID loops must be saved to the project before generating ST code. PID loops are configured via MQTT commands at runtime and are injected into the project JSON by the backend during save. If the project has no `pidLoops` key, the generated ST will have no PID control logic.

**Generated files:**
| File | Purpose |
|------|---------|
| `FB_PID_Loop.st` | PID function block (P/I/D terms, anti-windup, bumpless transfer) |
| `FB_Interlock.st` | IEC 61511 interlock state machine (SAFE/ARMED/TRIPPED) |
| `FB_SafeState.st` | Safe state manager (sets all outputs to configured safe values) |
| `GVL_Registers.st` | Global variable list with Modbus AT declarations |
| `Main.st` | Main program: read I/O → PID → interlocks → safe state → write outputs |

**CODESYS IDE steps** (manual, after deploy):
1. Open/create groov EPIC project in CODESYS IDE
2. Import the 5 ST files as POUs + GVL
3. Add Modbus TCP Slave device, map variables to GVL_Registers
4. Set task cycle to 1 ms
5. Build → Download → Run

**Register map** (`codesys/register_map.py`):
| Range | Direction | Content |
|-------|-----------|---------|
| 40001-40100 | Python → CODESYS | PID setpoints (50 loops, float32) |
| 40101-40250 | Python → CODESYS | PID tuning (Kp/Ki/Kd triplets) |
| 40401-40500 | Python → CODESYS | Interlock commands |
| 40601-40610 | Python → CODESYS | System commands (E-stop, heartbeat, mode) |
| 30001-30100 | CODESYS → Python | PID CV outputs |
| 30101-30300 | CODESYS → Python | Process values (100 channels) |
| 30301-30400 | CODESYS → Python | Interlock status + trip counts |

**Heartbeat**: Python increments counter every scan → CODESYS watchdog detects Python failure after 5 s → PLC applies safe state autonomously.

### Python ↔ CODESYS Mode Switching

In `opto22_node.py` main loop:
- `codesys_available` = bridge connected AND last successful read < 5 s AND < 3 consecutive errors
- On mode change: logged as info/warning, published in status MQTT
- In CODESYS mode: Python still runs safety.py as **monitoring layer** (not control layer), evaluates alarms, publishes to MQTT
- In Python fallback: PID engine + safety.py handle everything (same behavior as pre-CODESYS)

### Test Coverage

| File | Tests | What |
|------|-------|------|
| `tests/test_codesys_codegen.py` | 51 | Register allocation, no-overlap validation, ST condition conversion, GVL generation, Main program wiring, serialization round-trip |
| `tests/test_opto22_node.py` | — | Node integration tests |

### Reference: docs/ai/AI_Structured_Text_Guide.md

Comprehensive guide for AI-assisted ST code generation. Covers FB interfaces, register map, Main program structure, CODESYS IDE import workflow, and naming conventions.

## Device CLI

Use `device.bat` for device management operations (NOT for starting services):
- `device scan` — Discover devices
- `device deploy crio --host <ip> -r` — Deploy to cRIO
- `device logs crio --host <ip> -f` — Follow cRIO logs

The DAQ service runs on the PC and is started separately (not via device.bat).

## cRIO Hardware Notes

- cRIO modules require DIFFERENTIAL terminal configuration (not RSE)
- Use `TerminalConfiguration.DEFAULT` to let DAQmx auto-select
- Thermocouple channels need `channel_type == 'thermocouple'` check before using thermocouple setup

## Startup & Auto-Setup

Both dev and portable modes auto-generate everything on first run — no manual steps required.

### Auto-Generated on First Run

| Item | Generator | Output |
|------|-----------|--------|
| MQTT credentials | `scripts/mqtt_credentials.py` | `config/mqtt_credentials.json`, `config/mosquitto_passwd`, `dashboard/.env.local` |
| TLS certificates | `scripts/generate_tls_certs.py` | `config/tls/ca.crt`, `ca.key`, `server.crt`, `server.key` (10-year validity, SAN includes hostname + all local IPs) |
| Azure IoT venv (dev only) | Desktop startup bat | `azure-venv/` with `paho-mqtt<2.0` + `azure-iot-device` (installed offline from `vendor/azure-packages/`) |
| Admin password | DAQ service first run | `data/initial_admin_password.txt` (chmod 600) |

### MQTT Listeners (mosquitto.conf)

| Port | Bind | Transport | Auth | Purpose |
|------|------|-----------|------|---------|
| 1883 | 127.0.0.1 | TCP | Authenticated | Local services (DAQ, watchdog, Azure uploader) |
| 8883 | 0.0.0.0 | TCP + TLS | Authenticated | Remote nodes (cRIO, Opto22, GC) |
| 9002 | 127.0.0.1 | WebSocket | Anonymous | Dashboard (app-level auth via useAuth.ts) |
| 9003 | 0.0.0.0 | WebSocket | Authenticated | Remote dashboards (supervisor PCs) |

### Service MQTT Connection Methods

| Service | Port | Transport | Credentials |
|---------|------|-----------|-------------|
| DAQ Service | 1883 | TCP | Env vars `MQTT_USERNAME`/`MQTT_PASSWORD` → fallback `config/mqtt_credentials.json` |
| Watchdog | 1883 | TCP | Same credential chain as DAQ service |
| Azure Uploader | 1883 | TCP | Same credential chain as DAQ service |
| Dashboard (browser) | 9002 | WebSocket | Anonymous (port is localhost-only) |
| cRIO/Opto22 nodes | 8883 | TCP + TLS | Credentials from config push, CA cert deployed via deploy scripts |

### Dev Startup (`NISystem Start.bat`)

8-step startup sequence:
1. Kill previous NISystem windows
2. Clean up old processes (mosquitto, DAQ, watchdog, vite)
3. Auto-generate MQTT credentials (idempotent)
4. Auto-generate TLS certificates (if missing)
5. Start MQTT Broker (Mosquitto)
6. Start DAQ Service (with MQTT credentials via env vars)
7. Start Watchdog (with MQTT credentials via env vars)
8. Start Azure IoT Uploader (isolated `azure-venv/`, auto-created from `vendor/azure-packages/`)
9. Start Frontend (Vite dev server)

### Portable Startup (`ICCSFlux.exe`)

Same auto-setup sequence compiled into the launcher:
1. `setup_mqtt_credentials()` — generates credentials + mosquitto passwd file (PBKDF2-SHA512 in Python, no external tools)
2. `generate_tls_certs()` — `cryptography` library bundled in exe via PyInstaller
3. Start Mosquitto (bundled in `mosquitto/` dir)
4. Start DAQService.exe (credentials via env vars)
5. Start AzureUploader.exe (if present, credentials via env vars)
6. Start HTTP server (serves `www/` dashboard on port 5173)

### Azure IoT SDK Isolation

The Azure IoT SDK (`azure-iot-device`) requires `paho-mqtt<2.0`, which conflicts with the main project's `paho-mqtt>=2.0`. Both dev and portable handle this:

- **Dev**: Isolated `azure-venv/` created on first startup from `vendor/azure-packages/` (offline, no internet)
- **Portable**: `AzureUploader.exe` compiled from isolated build venv (`build/azure-venv/`). Ships as standalone binary with paho-mqtt 1.x baked in
- **Vendor packages**: `vendor/azure-packages/` contains `azure-iot-device-2.14.0`, `paho-mqtt-1.6.1`, and all transitive dependencies as wheels

## MQTT Security Decisions

- Port 1883 binds to 127.0.0.1 — local services only (DAQ, watchdog, Azure uploader)
- Port 8883 binds to 0.0.0.0 with TLS — for remote cRIO/Opto22/GC nodes over network
- Authentication + ACL enforced on all authenticated listeners — credentials auto-generated at first run
- TLS certificates auto-generated with 10-year validity and machine-specific SANs
- WebSocket 9002 is localhost-only and anonymous — dashboard uses app-level auth (useAuth.ts)
- WebSocket 9003 is network-accessible and authenticated — for remote dashboards on LAN
- Data only leaves the machine via Azure IoT Hub (HTTPS) or local SQL Server — never through MQTT

## Script Sandbox

User scripts run via `exec()` with AST-based validation (not process isolation). The sandbox blocks:
- All imports and `__import__`
- Dangerous dunders (`__subclasses__`, `__globals__`, `__code__`, `__mro__`, etc.)
- Dangerous builtins (`eval`, `exec`, `compile`, `open`, `getattr`, `vars`, `dir`, `globals`, `locals`)
- Module access (`os`, `sys`, `subprocess`, `ctypes`, `socket`, etc.)
- `type()` is removed from safe_builtins (prevents `type([]).__bases__[0].__subclasses__()` escape)

All three script engines share the same blocked lists — keep them in sync when modifying:
- `services/daq_service/script_manager.py`
- `services/crio_node_v2/script_engine.py`
- `services/opto22_node/script_engine.py`

## Project JSON Constraints

When creating or modifying project JSON files (`config/projects/*.json`):

### Valid Channel Types

**ONLY these channel types are valid** (defined in `config_parser.py` ChannelType enum):

| Type | Description |
|------|-------------|
| `thermocouple` | Thermocouple temperature sensors (J, K, T, E, N, R, S, B) |
| `rtd` | RTD temperature sensors |
| `voltage_input` | Analog voltage input (0-10V) |
| `current_input` | Analog current input (4-20mA) |
| `voltage_output` | Analog voltage output |
| `current_output` | Analog current output |
| `digital_input` | Discrete input |
| `digital_output` | Discrete output |
| `counter` or `counter_input` | Counter/pulse input |
| `counter_output` | Counter/pulse output |
| `frequency_input` | Frequency measurement input |
| `pulse_output` | Pulse train output |
| `strain` or `strain_input` | Strain gauge / bridge input |
| `bridge_input` | Wheatstone bridge / universal bridge input |
| `iepe` or `iepe_input` | IEPE accelerometer/microphone input |
| `resistance` or `resistance_input` | Resistance measurement |
| `modbus_register` | Modbus holding/input register |
| `modbus_coil` | Modbus coil/discrete input |

Short forms (`strain`, `iepe`, `resistance`, `counter`) and explicit forms (`strain_input`, `iepe_input`, `resistance_input`, `counter_input`) are both valid and behave identically.

**DO NOT USE**: `script`, `calculated`, `virtual`, or any other type not listed above. These will cause `ValueError: 'xxx' is not a valid ChannelType` when loading the project.

### Calculated Values

Calculated/derived values (PUE, COP, delta-T, heat loads, etc.) should NOT be defined as channels. Instead:
1. Create Python scripts in the `pythonScripts` section
2. Use `publish('ValueName', value, units='...')` to output calculated values
3. Script-published values go to MQTT but cannot be displayed in dashboard widgets (widgets must reference real channels)

### Rate Limits

- Maximum publish rate: **4 Hz** (configurable up to 4 Hz, not higher)
- Scan rate can be higher (10-100 Hz) for internal PID loops and script calculations

## Key Design Decisions

- DAQ service uses a **state machine** (`state_machine.py`) for acquisition lifecycle: STOPPED → INITIALIZING → RUNNING → STOPPING → STOPPED
- Critical MQTT commands (acquire start/stop, recording, session, safe-state) use **per-topic callbacks** that bypass the command queue for low latency
- Recording uses **OS-level file locking** (msvcrt on Windows, fcntl on Unix) and **fsync after flush** for crash safety
- Admin password is written to `data/initial_admin_password.txt` (chmod 600), never logged to console
- Script code payloads are limited to 256 KB, script names to 256 chars

## Data Flow

```
Hardware Read (10 Hz scan):
  Hardware → HardwareReader (continuous buffer) → latest_values dict

Script Execution:
  latest_values → User scripts (in sandbox) → vars, outputs, computed values

MQTT Publishing (4 Hz rate-limited):
  values → TokenBucketRateLimiter → MQTT broker → Dashboard (WebSocket)

Recording:
  values → RecordingManager → Buffered write → File (async, fsync)

Safety:
  values → SafetyManager → Interlock evaluation → Trip actions (MQTT commands)
```

## Safety & Interlock Architecture

The safety system runs at four levels: DAQ service (backend-authoritative), cRIO node, Opto22 node, and CFP node. All four share the same interlock data structures with camelCase↔snake_case serialization compatibility.

### Three-Tier Safety

| Layer | File | Role |
|-------|------|------|
| DAQ Service | `safety_manager.py` | Backend-authoritative. Evaluates all interlocks, manages latch state, pushes interlocks to edge nodes via config. Has full condition type set including `mqtt_connected`, `variable_value`, `expression` |
| cRIO Node | `crio_node_v2/safety.py` | Local safety. Evaluates interlocks independently (survives PC disconnect). Condition types: `channel_value`, `digital_input`, `alarm_active`, `no_active_alarms`, `acquiring` |
| Opto22 Node | `opto22_node/safety.py` | Identical to cRIO (synced copy with different logger) |
| CFP Node | `cfp_node/safety.py` | Identical to cRIO (synced copy with logger='CFPNode'). Provides safety for Modbus-based CompactFieldPoint I/O |

### Interlock Config Push (DAQ → Edge Nodes)

The DAQ service pushes interlocks to edge nodes during config sync (`_push_crio_channel_config()` / `_push_cfp_channel_config()`):
- Filters interlocks: only those with controls targeting the node's channels, or `stop_session` controls
- Includes `safe_state_config` with per-channel safe values
- Interlocks are included in the config hash for version tracking
- Edge nodes deserialize via `from_dict()` which accepts both camelCase (DAQ format) and snake_case (node format)

```
DAQ Service (safety_manager.py)         Edge Nodes (cRIO/Opto22/CFP safety.py)
─────────────────────────────           ──────────────────────────────────
InterlockCondition.to_dict()    ──MQTT──>  InterlockCondition.from_dict()
  uses 'type', camelCase                   accepts both camelCase + snake_case
InterlockControl.to_dict()      ──MQTT──>  InterlockControl.from_dict()
  uses 'type', 'setValue'                  accepts 'type'/'setValue' + 'control_type'/'set_value'
SafeStateConfig.to_dict()       ──MQTT──>  SafeStateConfig.from_dict()
  category-based format                   accepts both category-based + per-channel
```

### Interlock Evaluation
- **Conditions**: `channel_value`, `digital_input`, `alarm_active`, `no_active_alarms`, `acquiring` (edge); plus `mqtt_connected`, `daq_connected`, `not_recording`, `variable_value`, `expression` (DAQ only)
- **Logic**: AND (all must pass) or OR (any can pass), with per-condition on-delay
- **Latch states**: SAFE → ARMED → TRIPPED (IEC 61511)
- **Controls**: `set_output` (write channel value), `stop_session` (halt acquisition)
- **Bypass**: Per-interlock, with optional auto-expiry timer
- **Demand tracking**: Counts satisfied→unsatisfied transitions per interlock
- **Output blocking**: Safety-held outputs (from alarms) and interlock-held outputs cannot be overridden by scripts or MQTT commands
- **Evaluation order**: Alarms first → COMM_FAIL detection → interlock evaluation (so `alarm_active` conditions see current state)

### COMM_FAIL Alarm
When `check_all(channel_values, configured_channels=set)` is called with a set of expected channels, any channel in `configured_channels` but missing from `channel_values` triggers a CRITICAL COMM_FAIL alarm. The alarm auto-clears when the channel reappears. Respects shelving (shelved channels don't trigger COMM_FAIL). Does not duplicate (fires once, stays active until cleared).

### channel_offline Flag
When an interlock condition references a channel with no value (None), the evaluation result includes `channel_offline: True`. This propagates to `has_offline_channels` in the interlock status (DAQ: `InterlockStatus.has_offline_channels`, serialized as `hasOfflineChannels`; nodes: `has_offline_channels` key in status dict). Distinguishes hardware failures from legitimate process condition failures.

### Safety File Sync
`crio_node_v2/safety.py`, `opto22_node/safety.py`, and `cfp_node/safety.py` are identical except for the logger name. When modifying safety logic, **edit cRIO first, then copy to Opto22 and CFP**, changing `logger = logging.getLogger('cRIONode')` to `logging.getLogger('Opto22Node')` or `logging.getLogger('CFPNode')` respectively.

### Interlock Commands (cRIO/Opto22/CFP)

Edge nodes accept these MQTT commands on `{base}/commands/interlock`:
- `arm_latch` / `disarm_latch` — arm/disarm the safety latch
- `bypass_interlock` / `unbypass_interlock` — per-interlock bypass with duration
- `acknowledge_trip` / `reset_trip` — trip acknowledgment and reset
- `safe_state` — apply safe state to all configured outputs

## Hot-Unplug Resilience

The system handles hardware module disconnection during operation:

| Scenario | Behavior |
|----------|----------|
| Module unplugged mid-read (cRIO) | DI/AI loops guard `i >= len(values)`, return NaN for missing channels |
| Module unplugged mid-read (Opto22) | groov MQTT stops publishing; GroovIOSubscriber detects stale channels via `get_stale_channels(timeout_s)` |
| Safety channel goes offline | COMM_FAIL alarm fires (CRITICAL), safety actions execute if configured |
| Interlock channel goes offline | Condition fails with `channel_offline=True`, interlock trips if ARMED |
| Discovery after unplug | `is_stale(max_age_s)` warns if results are old; `get_scan_age()` reports age |
| cRIO consecutive errors | After 3 errors (not 10), sets safe state, publishes `status/degraded`, attempts recovery with exponential backoff |
| Safety write fails | Single retry after 50ms; if still fails, publishes `safety/write_failure` to MQTT |
| groov MQTT disconnects | Detected in main loop, logged, published to `status/groov_mqtt` |
| Hardware health | Published in status messages: `hardware_health` dict with healthy/error_count/stale_channels |

## Frontend Dependencies

```
Vue 3.5.24 + Pinia 3.0.4 + Vue Router 4.6.4
MQTT.js 5.14.1 (WebSocket client)
grid-layout-plus 1.1.1 (widget grid)
uPlot 1.6.32 (charts/trends)
Monaco Editor 0.55.1 (code editing)
Pyodide 0.26.4 (Python runtime, lazy-loaded)
Tailwind CSS 4.1.18
TypeScript 5.9.3 (strict mode)
Vitest 4.0.16 (unit tests)
Vite 7.2.4 (bundler)
```

## Quality Gates (Claude Code)

After making changes, run these checks BEFORE telling the user you're done. Do not skip these.

### After any frontend edit (.vue, .ts, .tsx)
1. Run `cd dashboard && npx vue-tsc -b --noEmit` — fix all TypeScript errors before proceeding
2. If you added a field to a type/interface: grep for every place that type is constructed from external data (MQTT payloads, JSON, localStorage) and add the field there too
3. If you added a backend MQTT publisher: check that the frontend subscribes to that topic in the relevant composable

### After any backend edit (.py)
1. Run `python -m pytest tests/test_safety_manager.py tests/test_alarm_manager.py -v` at minimum for safety/alarm changes
2. If you modified a dataclass `to_dict()`/`from_dict()`: check both camelCase and snake_case paths, and update the corresponding TypeScript type

### After any edge node safety.py edit
1. Edit cRIO first, then copy to Opto22 and CFP (changing only the logger name)
2. Verify with `diff` that the files match (minus logger name)

### Cross-cutting consistency checks
- When adding a field to `Interlock`, `InterlockCondition`, or `InterlockControl`: update ALL of these locations:
  - `services/daq_service/safety_manager.py` (dataclass + to_dict + from_dict)
  - `services/crio_node_v2/safety.py` (dataclass + to_dict + from_dict) → copy to opto22/cfp
  - `dashboard/src/types/index.ts` (TypeScript interface)
  - `dashboard/src/composables/useSafety.ts` (syncInterlockToBackend payload + handleBackendInterlockList deserialization)
  - `dashboard/src/components/SafetyTab.vue` (newInterlock ref + openNewInterlockModal reset + openEditInterlockModal copy + saveInterlock fields)
- When adding a field to `AlarmConfig`: update safety_manager.py, alarm_manager.py, types/index.ts, useSafety.ts, SafetyTab.vue
- Never pass a function with optional params directly to `.forEach()` / `.map()` — wrap in a lambda to avoid index/array leaking into optional params
