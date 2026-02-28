# ICCSFlux — Standards & Compliance Reference

*Industrial Control & Condition-monitoring System with Flexible User eXperience*

This document catalogues every industry standard, regulatory framework, and protocol that ICCSFlux implements, references, or aligns with. Each entry identifies the standard, what ICCSFlux does with it, and where the implementation lives.

---

## Table of Contents

1. [Process Safety](#1-process-safety)
2. [Alarm Management](#2-alarm-management)
3. [HMI & Operator Interface](#3-hmi--operator-interface)
4. [Regulatory Compliance & Data Integrity](#4-regulatory-compliance--data-integrity)
5. [Industrial Communication Protocols](#5-industrial-communication-protocols)
6. [Cryptography & Data Protection](#6-cryptography--data-protection)
7. [OT Network Security](#7-ot-network-security)
8. [Cybersecurity Frameworks & Guidance](#8-cybersecurity-frameworks--guidance)
9. [Data Formats & Recording](#9-data-formats--recording)
10. [Build Integrity & Software Assurance](#10-build-integrity--software-assurance)
11. [Summary Matrix](#11-summary-matrix)

---

## 1. Process Safety

### IEC 61511 — Safety Instrumented Systems for the Process Industry

| Aspect | Implementation |
|--------|---------------|
| **Scope** | Interlock evaluation, latch state machine, demand tracking, proof test intervals |
| **Latch States** | Three-state machine: **SAFE** → **ARMED** → **TRIPPED** (IEC 61511 SIF lifecycle) |
| **Condition Types** | `channel_value`, `digital_input`, `alarm_active`, `no_active_alarms`, `acquiring`, `mqtt_connected`, `daq_connected`, `variable_value`, `expression` |
| **Voting Logic** | AND (all conditions must pass) or OR (any condition passes) |
| **Per-Condition On-Delay** | Prevents premature interlock clearing from transient good readings |
| **Bypass with Expiry** | Per-interlock bypass with optional auto-expiry timer; `bypass_allowed` flag per interlock |
| **Demand Counting** | Tracks satisfied → unsatisfied transitions per interlock for SIF performance monitoring |
| **Proof Test Tracking** | `last_proof_test` timestamp and `proof_test_interval_days` per interlock |
| **SIL Rating** | Informational SIL 1–4 field per interlock (design intent, not certified) |
| **Trip Actions** | `set_digital_output`, `set_analog_output`, `stop_session` — with output blocking |
| **Output Blocking** | Interlock-held and safety-held outputs cannot be overridden by scripts or MQTT commands |
| **Trip Acknowledgment** | Operator must acknowledge trip before reset; audited with user attribution |
| **Three-Tier Execution** | DAQ service (backend-authoritative), cRIO node (autonomous local), Opto22/CFP nodes |
| **Edge Node Autonomy** | cRIO/Opto22/CFP continue interlock evaluation when PC is disconnected |
| **Config Push** | DAQ pushes only relevant interlocks to each edge node (filtered by output channels) |
| **Persistence** | Interlock state (bypass, demand count, proof test) persisted to disk, survives restarts |

**Files:** `safety_manager.py`, `crio_node_v2/safety.py`, `opto22_node/safety.py`, `cfp_node/safety.py`

### IEC 61508 — Functional Safety of E/E/PE Systems

| Aspect | Implementation |
|--------|---------------|
| **Scope** | Referenced as the parent standard for IEC 61511; SIL rating fields in interlock config |
| **Current State** | Python implementation follows IEC 61508 design patterns but cannot be formally certified |
| **Certification Path** | Documented roadmap for C/C++ rewrite to certified toolchain (TÜV/exida pathway) |

**Files:** `docs/Safety_Certification_Roadmap.md`

### Safe State Management

| Aspect | Implementation |
|--------|---------------|
| **Per-Channel Safe Values** | `SafeStateConfig` maps each output channel to its safe value |
| **Atomic Safe State** | Single command sets ALL outputs to safe values simultaneously |
| **Session Stop on Safe State** | Configurable `stop_session` flag in safe state config |
| **Communication Watchdog** | 30-second timeout — if PC stops communicating, cRIO transitions to safe state autonomously |
| **Watchdog Output** | Toggling digital output for external safety relay monitoring; loss of pulse = fault detected |
| **Safety Write Verification** | After safety action: hardware readback check, single retry on failure, MQTT alert on double-failure |
| **Error Recovery** | 3 consecutive hardware errors → safe state → exponential backoff (5s → 60s) |

---

## 2. Alarm Management

### ISA-18.2 — Management of Alarm Systems for the Process Industries

| Aspect | Implementation |
|--------|---------------|
| **Alarm State Model** | Six states: **NORMAL**, **ACTIVE**, **ACKNOWLEDGED**, **RETURNED**, **SHELVED**, **OUT_OF_SERVICE** |
| **Severity Levels** | Four-level thresholds: HIHI (Critical), HI (Warning), LO (Warning), LOLO (Critical) |
| **Deadband** | Configurable per-channel hysteresis to prevent alarm chattering |
| **On-Delay** | Alarm condition must persist for `delay_seconds` before transitioning to ACTIVE |
| **Off-Delay** | Alarm condition must clear for `off_delay_seconds` before returning to NORMAL |
| **Rate-of-Change** | Configurable ROC limit with 20% hysteresis for clearing |
| **Alarm Shelving** | Operator-initiated suppression with timed auto-unshelve; `shelved_by` attribution |
| **Out-of-Service** | Maintenance suppression with no auto-expiry; requires explicit return-to-service |
| **Acknowledgment** | Operator must acknowledge active alarms; RETURNED state holds until acknowledged |
| **Safety Actions** | Alarms can trigger output writes (`set:channel:value`) or session stops |
| **Output Holds** | Safety-held outputs (from alarm actions) block scripts and MQTT overrides |
| **COMM_FAIL** | Missing channel values generate CRITICAL COMM_FAIL alarm; auto-clears on reconnection |
| **Alarm Flood Detection** | Configurable threshold (default: 10 alarms in 60 seconds); suppresses non-CRITICAL alarms during flood; publishes first-out alarm for root cause analysis |
| **Alarm History** | Persisted to disk with configurable retention (200 entries default) |
| **Alarm Counts** | Real-time counts: active, acknowledged, returned, shelved, out_of_service, total |

**Files:** `alarm_manager.py` (DAQ), `safety.py` (cRIO/Opto22/CFP), `useSafety.ts` (dashboard), `SafetyTab.vue`, `AlarmConfigModal.vue`

---

## 3. HMI & Operator Interface

### ISA-101 — Human Machine Interfaces for Process Automation Systems

| Aspect | Implementation |
|--------|---------------|
| **Design Philosophy** | Grayscale by default; color reserved for alarm/abnormal conditions |
| **12 HMI Controls** | Purpose-built components following ISA-101 high-performance principles |
| **Color Usage** | Alarm-state-driven coloring (red = critical, yellow = warning, green = normal) |
| **No Skeuomorphism** | Flat, functional design — no decorative 3D effects or photo-realistic textures |
| **Proper Labeling** | Units, tag names, and descriptions displayed with every value |
| **Display Hierarchy** | Level 1 (Overview) → Level 2 (Area) → Level 3 (Detail) → Level 4 (Diagnostic) |

**HMI Control Components:**

| Component | Type | Purpose |
|-----------|------|---------|
| `HmiNumericIndicator` | `hmi_numeric` | Value display with alarm coloring |
| `HmiStatusLed` | `hmi_led` | Boolean indicator LED |
| `HmiToggleControl` | `hmi_toggle` | Digital output toggle switch |
| `HmiSetpointControl` | `hmi_setpoint` | Slider/knob for analog outputs |
| `HmiBarIndicator` | `hmi_bar` | Horizontal/vertical bar with alarm zones |
| `HmiArcGauge` | `hmi_gauge` | 270-degree circular arc gauge |
| `HmiMultiStateIndicator` | `hmi_multistate` | Named state indicator (e.g., OFF/IDLE/RUN) |
| `HmiCommandButton` | `hmi_button` | Action button with interlock check |
| `HmiSelectorSwitch` | `hmi_selector` | Multi-position selector switch |
| `HmiAlarmAnnunciator` | `hmi_annunciator` | Alarm banner/annunciator panel |
| `HmiTrendSparkline` | `hmi_sparkline` | Mini trend sparkline chart |
| `HmiValvePosition` | `hmi_valve_pos` | Valve position graphic |

**Files:** `dashboard/src/components/hmi/`, `constants/hmiControls.ts`, `stores/dashboard.ts`

### ISA-5.1 — Instrumentation Symbols and Identification

| Aspect | Implementation |
|--------|---------------|
| **P&ID Symbols** | 50+ SVG symbols: valves (9 types), pumps (3), tanks (4), heat exchangers (3), instruments (8+), piping (5+) |
| **Symbol Library** | Categorized by type with search; drag-to-canvas placement |
| **Pipe Routing** | A* pathfinding on orthogonal visibility graph for auto-routing |
| **Channel Binding** | Symbols bind to live channel values for real-time animation |

**Files:** `PidCanvas.vue`, `PidToolbar.vue`, `assets/symbols/index.ts`, `utils/autoRoute.ts`

---

## 4. Regulatory Compliance & Data Integrity

### 21 CFR Part 11 — Electronic Records; Electronic Signatures (FDA)

| Aspect | Implementation |
|--------|---------------|
| **Append-Only Audit Trail** | JSONL format — records cannot be deleted or modified after creation |
| **SHA-256 Hash Chain** | Each entry includes `prev_hash` (hash of previous entry) and `hash` (hash of current entry); any insertion, deletion, or modification breaks the chain |
| **Tamper Detection** | `verify_integrity()` method validates entire hash chain and reports errors |
| **User Attribution** | Every audit entry records `operator`, `timestamp`, `event_type`, `channel`, `details` |
| **Microsecond Timestamps** | `acquisition_ts_us` field provides high-precision event timing |
| **Event Categories** | `alarm_trip`, `alarm_ack`, `safety_trip`, `interlock_arm/disarm/bypass/reset`, `session_start/stop`, `config_change`, `output_write`, `recording_start/stop`, `project_load/save` |
| **File Integrity** | `fsync` after every write to ensure crash-safe persistence |
| **Log Rotation** | Automatic rotation at configurable threshold (10 MB default) with gzip archival |
| **Read-Only Enforcement** | Rotated logs compressed and archived; original files replaced |
| **Role-Based Access** | Four roles: Admin, Operator, Viewer, Supervisor — with permission matrix |
| **Electronic Signatures** | User authentication required for critical operations (alarm ack, bypass, session start) |
| **Deployed on All Nodes** | Separate audit trails on DAQ service, cRIO, Opto22, and CFP nodes |

**Files:** `audit_trail.py` (DAQ + 3 edge nodes), `user_session.py`, `recording_manager.py`, `useAuth.ts`

### ALCOA+ — Data Integrity Principles

| Principle | Implementation |
|-----------|---------------|
| **Attributable** | Every record includes operator identity and role |
| **Legible** | JSONL plaintext format — human-readable without special tools |
| **Contemporaneous** | Timestamps recorded at time of event, not retroactively |
| **Original** | SHA-256 hash chain preserves original record integrity |
| **Accurate** | Hash verification detects any modification to recorded data |
| **Complete** | All required fields validated before recording; no partial entries |
| **Consistent** | UTC timestamps with ISO 8601 format across all nodes |
| **Enduring** | Configurable retention policy; gzip archival for long-term storage |
| **Available** | Records exportable; query methods for retrieval by type, time range, channel |

**Files:** `audit_trail.py`, `recording_manager.py`, `archive_manager.py`, `DataTab.vue`

### Recording Compliance

| Feature | Implementation |
|---------|---------------|
| **Recording Modes** | Buffered (batch writes), Immediate (per-scan), Circular (ring buffer) |
| **File Formats** | CSV (human-readable), TDMS (NI binary, high-performance) |
| **File Rotation** | By time interval, sample count, or file size |
| **OS-Level Locking** | `msvcrt` (Windows) / `fcntl` (Unix) prevents concurrent access |
| **Crash Safety** | `fsync` after flush ensures data reaches disk |
| **Decimation** | Configurable sample reduction for long-duration recordings |
| **Channel Selection** | Per-recording channel list; script-published values included |
| **SHA-256 Checksums** | File integrity checksum written alongside recordings |

---

## 5. Industrial Communication Protocols

### MQTT v3.1.1 (ISO/IEC 20922) / MQTT v5.0

| Aspect | Implementation |
|--------|---------------|
| **Protocol Version** | v3.1.1 (via paho-mqtt client library) |
| **QoS Levels** | QoS 0 (at most once) for data, QoS 1 (at least once) for commands and safety |
| **Last Will & Testament** | Automatic offline status on unexpected disconnect |
| **Retained Messages** | System status, alarm status, interlock status published with retain flag |
| **Topic Structure** | `{base}/nodes/{node_id}/{category}/{entity}` — hierarchical namespace |
| **Payload Format** | JSON with defined schemas per topic |
| **Payload Size Limit** | 256 KB maximum per message |
| **Auto-Reconnect** | Exponential backoff (5s → 60s max); node never exits on broker loss |

**Network Listeners:**

| Port | Transport | Auth | Bind | Purpose |
|------|-----------|------|------|---------|
| 1883 | TCP | Authenticated | 127.0.0.1 | Local services (DAQ, watchdog, Azure uploader) |
| 8883 | TCP + TLS | Authenticated | 0.0.0.0 | Remote edge nodes (cRIO, Opto22, CFP) |
| 9002 | WebSocket | Anonymous | 127.0.0.1 | Dashboard (app-level auth) |
| 9003 | WebSocket | Authenticated | 0.0.0.0 | Remote dashboards (LAN) |

### Modbus TCP/RTU (IEC 61158 / IEC 61784)

| Aspect | Implementation |
|--------|---------------|
| **TCP Client** | Ethernet-based Modbus client via pymodbus 3.x |
| **RTU Client** | Serial RS-485/RS-232 Modbus client |
| **Function Codes** | FC01 (coils), FC02 (discrete inputs), FC03 (holding registers), FC04 (input registers), FC05/15 (write coils), FC06/16 (write registers) |
| **Exception Handling** | Modbus exception code parsing (illegal function, address, value, device failure) |
| **Slave ID Routing** | Per-device slave ID configuration with dynamic channel mapping |
| **Data Types** | 16-bit register, 32-bit float (word swap), coil, discrete input |
| **Channel Types** | `modbus_register`, `modbus_coil` |

**Files:** `modbus_reader.py`, `ModbusDeviceConfig.vue`, `cfp_node/cfp_node.py`

### OPC UA (IEC 62541)

| Aspect | Implementation |
|--------|---------------|
| **Client** | OPC-UA client with subscription-based value monitoring |
| **Discovery** | Server endpoint discovery |
| **Authentication** | Username/password and certificate-based |
| **Data Types** | Automatic type conversion from OPC-UA to Python native |

**Files:** `opcua_source.py`, `OpcUaDeviceConfig.vue`

### EtherNet/IP (IEC 61158 Type 2 / ODVA CIP)

| Aspect | Implementation |
|--------|---------------|
| **Scanner Client** | Allen-Bradley EtherNet/IP scanner for ControlLogix/CompactLogix |
| **Tag-Based Access** | Read/write by tag name |
| **Connection Management** | Automatic connection establishment and recovery |

**Files:** `ethernet_ip_source.py`, `EtherNetIPDeviceConfig.vue`

### REST / HTTP(S)

| Aspect | Implementation |
|--------|---------------|
| **Polling Client** | Configurable HTTP/HTTPS polling for third-party API integration |
| **Authentication** | BASIC, BEARER token, API_KEY (header or query), OAUTH2 (client credentials) |
| **Response Parsing** | JSON response with JSONPath-style value extraction |

**Files:** `rest_reader.py`, `RestApiDeviceConfig.vue`

---

## 6. Cryptography & Data Protection

### SHA-256 (FIPS 180-4)

| Usage | Implementation |
|-------|---------------|
| **Audit Trail Hash Chain** | Each entry hashes to previous; tamper-evident append-only log |
| **Recording Checksums** | File integrity verification for CSV/TDMS recordings |
| **Build Manifests** | `SHA256SUMS.txt` for all compiled executables |
| **Version Tracking** | Git commit hash (SHA-1) embedded in VERSION.txt |

### PBKDF2-SHA512 (RFC 8018 / NIST SP 800-132)

| Usage | Implementation |
|-------|---------------|
| **MQTT Password Storage** | Mosquitto password file uses PBKDF2-SHA512 hashing |
| **Auto-Generated** | Credentials generated at first run via Python `hashlib`; no manual password management |
| **File Permissions** | `chmod 600` on credential files (owner-only access) |

### TLS 1.2/1.3 (RFC 5246 / RFC 8446)

| Usage | Implementation |
|-------|---------------|
| **Edge Node Communication** | Port 8883 — TCP + TLS for cRIO, Opto22, and CFP nodes |
| **Certificate Generation** | Self-signed CA with 10-year validity via `cryptography` library |
| **Subject Alternative Names** | Hostname + all local IP addresses for flexible deployment |
| **Validation** | `ssl.CERT_REQUIRED` with `ssl.PROTOCOL_TLS_CLIENT` |
| **Certificate Deployment** | CA cert deployed to edge nodes via deploy scripts (SCP over SSH) |

### Authenticode Code Signing (Microsoft)

| Usage | Implementation |
|-------|---------------|
| **Executable Signing** | RSA-4096 key, SHA-256 digest for Windows PE binaries |
| **Timestamp** | RFC 3161 timestamp via DigiCert TSA (signatures remain valid after cert expiry) |
| **Publisher Identity** | Organization Validation (OV) certificate |

---

## 7. OT Network Security

### ISA-95 / IEC 62264 — Enterprise-Control System Integration (Purdue Model)

| Level | Description | ICCSFlux Placement |
|-------|-------------|--------------------|
| Level 0 | Physical Process | Sensors, actuators, NI C-Series modules |
| Level 1 | Basic Control | cRIO, Opto22, CompactFieldPoint nodes |
| **Level 2** | **Supervisory Control** | **ICCSFlux DAQ service, dashboard, HMI** |
| Level 3 | Manufacturing Operations | MES, historians (optional SQL Server) |
| Level 3.5 | IT/OT DMZ | Azure uploader (read-only data export) |
| Level 4 | Enterprise IT | Corporate network |
| Level 5 | Internet | Azure IoT Hub (HTTPS only) |

**Network Segmentation:** ICCSFlux runs at Level 2 on a segmented OT LAN. Data only leaves the machine via Azure IoT Hub (HTTPS) or local SQL Server — never exposed directly to corporate IT or internet.

### ISA/IEC 62443 — Security for Industrial Automation and Control Systems

| Aspect | Implementation |
|--------|---------------|
| **Security Level Target** | SL 1–2 (protection against casual and intentional low-skill attacks) |
| **Zones and Conduits** | MQTT topics form conduit boundaries; per-listener auth and ACL |
| **Role-Based Access** | Admin, Operator, Viewer, Supervisor roles with permission matrix |
| **Authentication** | MQTT username/password (services), session tokens (dashboard) |
| **Audit Trails** | Change tracking for all configuration, safety, and operational actions |
| **Patch Management** | IEC 62443-2-3: patches tested in staging before OT deployment |

---

## 8. Cybersecurity Frameworks & Guidance

### NIST SP 800-82 Rev. 3 — Guide to Operational Technology Security

| Guidance Area | ICCSFlux Alignment |
|---------------|-------------------|
| **Safety > Availability > Integrity > Confidentiality** | Safety system evaluates before all other processing; communication watchdog ensures availability |
| **Antivirus Impact on RT** | Application allowlisting recommended over antivirus for OT hosts |
| **Patch Testing** | Documented patch validation workflow before production deployment |
| **Incident Response** | Cannot halt operations — safety system degrades gracefully |

### NIST SP 800-63B Rev. 4 — Digital Identity Guidelines

| Guidance Area | ICCSFlux Alignment |
|---------------|-------------------|
| **No Periodic Password Rotation** | MQTT and user credentials are not subject to forced rotation schedules |
| **Rotate on Compromise** | Credential rotation triggered only by evidence of compromise |

### NIST SP 800-52 — Guidelines for TLS Implementations

| Guidance Area | ICCSFlux Alignment |
|---------------|-------------------|
| **TLS Configuration** | Port 8883 uses TLS 1.2+ with `ssl.CERT_REQUIRED` |
| **Certificate Management** | Auto-generated with SANs; 10-year validity for OT stability |

### CISA — Principles of OT Cyber Security (2024)

| Principle | ICCSFlux Alignment |
|-----------|-------------------|
| **OT ≠ IT** | Security controls designed for industrial environment, not enterprise IT |
| **Safety First** | Interlock and alarm systems take priority over all other functions |
| **Network Segmentation** | Localhost-only services, TLS for remote nodes, no direct internet exposure |

### SANS ICS — Five Critical Controls

| Control | ICCSFlux Alignment |
|---------|-------------------|
| **Application Allowlisting** | Recommended for DAQ workstation; portable build has known-good executable set |
| **No Traditional AV on RT** | OT host runs purpose-built software; AV real-time scanning can disrupt acquisition |

---

## 9. Data Formats & Recording

### NI TDMS (Technical Data Management Streaming)

| Aspect | Implementation |
|--------|---------------|
| **Binary Format** | High-performance streaming for large datasets |
| **Metadata** | Channel properties, units, timestamps embedded in file |
| **Hierarchical** | Group → Channel → Data structure |

### CSV (RFC 4180)

| Aspect | Implementation |
|--------|---------------|
| **Text Format** | Human-readable, universally compatible |
| **Headers** | Timestamp column + one column per channel |
| **Rotation** | By time, sample count, or file size |

### JSON / JSONL (RFC 8259 / JSON Lines)

| Usage | Implementation |
|-------|---------------|
| **MQTT Payloads** | All command/response messages use JSON encoding |
| **Audit Trail** | Append-only JSONL format (one JSON object per line) |
| **Project Files** | Configuration stored as structured JSON with schema versioning |
| **Config Persistence** | cRIO/Opto22/CFP save config to local JSON files |

### Gzip (RFC 1952)

| Usage | Implementation |
|-------|---------------|
| **Audit Log Archival** | Rotated audit logs compressed with gzip |
| **Storage Optimization** | Reduces disk usage on edge nodes with limited storage |

---

## 10. Build Integrity & Software Assurance

### Reproducible Builds

| Aspect | Implementation |
|--------|---------------|
| **PYTHONHASHSEED** | Set to fixed value for deterministic Python builds |
| **SOURCE_DATE_EPOCH** | Fixed timestamp for reproducible archive creation |
| **SHA-256 Manifest** | `SHA256SUMS.txt` lists hash of every compiled executable |
| **Version Embedding** | Git commit hash, branch, and timestamp in `VERSION.txt` |

### Semantic Versioning (SemVer 2.0.0)

| Aspect | Implementation |
|--------|---------------|
| **Format** | MAJOR.MINOR.PATCH (e.g., v2.2.0) |
| **Components** | DAQ service, cRIO node, dashboard each independently versioned |

### PyInstaller Compilation

| Aspect | Implementation |
|--------|---------------|
| **Portable Build** | Single-directory distribution — runs on any Windows PC without Python/Node |
| **Isolated Azure venv** | Azure uploader compiled separately (paho-mqtt <2.0 isolation) |
| **Offline Build** | All dependencies vendored in `vendor/` for air-gapped environments |

---

## 11. Summary Matrix

| Standard | Category | Implementation Scope |
|----------|----------|---------------------|
| **IEC 61511** | Process Safety | Interlock latch state machine, condition evaluation, bypass, demand tracking, proof test |
| **IEC 61508** | Functional Safety | Design patterns and SIL rating fields; certification roadmap documented |
| **ISA-18.2** | Alarm Management | Six-state alarm model, shelving, OOS, flood detection, COMM_FAIL, safety actions |
| **ISA-101** | HMI Design | 12 high-performance HMI controls, grayscale-first, alarm-driven color |
| **ISA-5.1** | P&ID Symbols | 50+ SVG symbols with live channel binding and auto-routing |
| **ISA-95 / IEC 62264** | Network Architecture | Purdue Model Level 2 deployment with DMZ data export |
| **ISA/IEC 62443** | OT Cybersecurity | SL 1–2 target, zones/conduits, RBAC, audit trails |
| **21 CFR Part 11** | FDA Compliance | Append-only audit trail, SHA-256 hash chain, user attribution, electronic signatures |
| **ALCOA+** | Data Integrity | All 8 principles implemented across audit trail and recording systems |
| **MQTT v3.1.1** | Messaging Protocol | Pub/sub with QoS 0/1, LWT, retained messages, TLS, 4 listeners |
| **Modbus TCP/RTU** | Field Protocol | FC01-04 reads, FC05/06/15/16 writes, exception handling, RTU serial |
| **OPC UA (IEC 62541)** | Field Protocol | Client with subscriptions, discovery, authentication |
| **EtherNet/IP (CIP)** | Field Protocol | Allen-Bradley scanner client, tag-based access |
| **REST/HTTP(S)** | Integration Protocol | Polling client with BASIC, BEARER, API_KEY, OAUTH2 auth |
| **SHA-256 (FIPS 180-4)** | Cryptography | Hash chain, file checksums, build manifests |
| **PBKDF2-SHA512** | Key Derivation | MQTT password hashing |
| **TLS 1.2/1.3** | Transport Security | Edge node communication on port 8883 |
| **RFC 3161** | Timestamping | Code signing timestamps via DigiCert TSA |
| **NIST SP 800-82** | OT Security Guidance | Safety-first priorities, patch management, RT considerations |
| **NIST SP 800-63B** | Identity Guidelines | No forced password rotation; rotate on compromise only |
| **NIST SP 800-52** | TLS Guidelines | TLS configuration for edge node communication |
| **CISA OT Principles** | Cybersecurity Guidance | OT-appropriate security controls, network segmentation |
| **NI TDMS** | Data Format | Binary recording format with metadata |
| **CSV (RFC 4180)** | Data Format | Text recording format with rotation |
| **JSON (RFC 8259)** | Data Format | Configuration, MQTT payloads, audit trail |
| **Gzip (RFC 1952)** | Compression | Audit log archival |
| **SemVer 2.0.0** | Versioning | Component version tracking |

---

## Related Documents

| Document | Scope |
|----------|-------|
| [IT Security & Compliance Guide](IT_Security_and_Compliance_Guide.md) | Build integrity, code signing, SBOM, SOC 2 mapping, network architecture, and IT deployment procedures |
| [OT Security Standards Reference](OT_Security_Standards_Reference.md) | Why OT systems require tailored security controls vs. enterprise IT policies — cites NIST, IEC, ISA, CISA, and SANS |
| [Safety Certification Roadmap](Safety_Certification_Roadmap.md) | IEC 61508/61511 certification paths, cost estimates, and phased roadmap for formal safety certification |

---

*Document generated: 2026-02-28*
*Covers: ICCSFlux codebase (~239k LOC across 250+ files)*
