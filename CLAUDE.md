# NISystem Project Instructions

## Architecture Overview

- **Backend**: Python DAQ service (`services/daq_service/daq_service.py`, ~13k lines) — reads NI hardware (or simulation), publishes over MQTT
- **Frontend**: Vue 3 + TypeScript dashboard (`dashboard/`) — connects via WebSocket to MQTT
- **Broker**: Mosquitto MQTT — TCP 1883 (authenticated, for services + cRIO) and WebSocket 9002 (localhost-only, anonymous, for dashboard)
- **cRIO**: Python node (`services/crio_node_v2/`) deployed to NI cRIO hardware over SSH
- **Opto22**: Python node (`services/opto22_node/`) deployed to groov EPIC/RIO — hybrid architecture with groov Manage MQTT for I/O + Python for scripts, safety, PID, sequences
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

Deployed to Opto22 groov EPIC/RIO. Hybrid architecture: groov Manage MQTT for native I/O scanning + Python node for scripts, safety, PID, sequences.

**Core:**

| File | LOC | Purpose |
|------|-----|---------|
| `services/opto22_node/opto22_node.py` | 1,350 | Main service orchestrator: dual MQTT, scan loop, command dispatch, stale I/O detection, groov MQTT health monitoring |
| `services/opto22_node/state_machine.py` | ~200 | States: IDLE → CONNECTING_MQTT → ACQUIRING → SESSION |
| `services/opto22_node/mqtt_interface.py` | ~375 | Dual MQTT: SystemMQTT (NISystem) + GroovMQTT (groov Manage). Both have `reconnect()` |
| `services/opto22_node/hardware.py` | ~310 | GroovIOSubscriber (MQTT I/O with stale detection) + GroovRestFallback (REST API). HardwareInterface auto-wires groov MQTT → subscriber |
| `services/opto22_node/config.py` | ~500 | NodeConfig, ChannelConfig, groov MQTT + REST settings |
| `services/opto22_node/channel_types.py` | ~300 | ChannelType enum + Opto22 module database (GRV-series) |

**Intelligence (shared with cRIO v2):**

| File | LOC | Purpose |
|------|-----|---------|
| `services/opto22_node/script_engine.py` | ~1,800 | Script sandbox (same API as DAQ service). 4 Hz rate limiting. **MUST keep blocked lists in sync with script_manager.py** |
| `services/opto22_node/safety.py` | 1,855 | Synced copy of cRIO safety.py (logger='Opto22Node'). ISA-18.2 alarms + IEC 61511 interlocks, COMM_FAIL, channel_offline. **MUST stay in sync with crio_node_v2/safety.py** |
| `services/opto22_node/audit_trail.py` | ~150 | SHA-256 hash chain, append-only JSONL, 10 MB rotation |

**Autonomous engines (Opto22-unique):**

| File | LOC | Purpose |
|------|-----|---------|
| `services/opto22_node/pid_engine.py` | ~120 | PID loops: auto/manual/cascade, anti-windup, derivative-on-PV |
| `services/opto22_node/sequence_manager.py` | ~130 | Server-side sequences: setOutput, wait, condition, loops |
| `services/opto22_node/trigger_engine.py` | ~50 | Rising-edge threshold detection → actions |
| `services/opto22_node/watchdog_engine.py` | ~60 | Stale data + out-of-range monitoring with recovery |
| `services/opto22_node/codesys_bridge.py` | ~240 | Optional: Modbus TCP bridge to CODESYS runtime for deterministic PID |

### Section 9: Other Device Services

| File | LOC | Purpose |
|------|-----|---------|
| `services/cfp_node/cfp_node.py` | 998 | NI CompactFieldPoint hardware support |
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

**Dashboard tests** (Vitest): `npm run test` in `dashboard/` — 20+ test files covering stores, composables, widgets

**Dashboard type check + build**: `npm run build` in `dashboard/` (runs `vue-tsc -b && vite build`)

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

The safety system runs at three levels: DAQ service (backend-authoritative), cRIO node, and Opto22 node. All three share the same interlock data structures with camelCase↔snake_case serialization compatibility.

### Three-Tier Safety

| Layer | File | Role |
|-------|------|------|
| DAQ Service | `safety_manager.py` | Backend-authoritative. Evaluates all interlocks, manages latch state, pushes interlocks to edge nodes via config. Has full condition type set including `mqtt_connected`, `variable_value`, `expression` |
| cRIO Node | `crio_node_v2/safety.py` | Local safety. Evaluates interlocks independently (survives PC disconnect). Condition types: `channel_value`, `digital_input`, `alarm_active`, `no_active_alarms`, `acquiring` |
| Opto22 Node | `opto22_node/safety.py` | Identical to cRIO (synced copy with different logger) |

### Interlock Config Push (DAQ → Edge Nodes)

The DAQ service pushes interlocks to edge nodes during config sync (`_push_crio_channel_config()`):
- Filters interlocks: only those with controls targeting the node's channels, or `stop_session` controls
- Includes `safe_state_config` with per-channel safe values
- Interlocks are included in the config hash for version tracking
- Edge nodes deserialize via `from_dict()` which accepts both camelCase (DAQ format) and snake_case (node format)

```
DAQ Service (safety_manager.py)         Edge Nodes (cRIO/Opto22 safety.py)
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
`crio_node_v2/safety.py` and `opto22_node/safety.py` are identical except for the logger name. When modifying safety logic, **edit cRIO first, then copy to Opto22** and change `logger = logging.getLogger('cRIONode')` to `logging.getLogger('Opto22Node')`.

### Interlock Commands (cRIO/Opto22)

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
