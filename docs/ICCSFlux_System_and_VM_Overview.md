# ICCSFlux: System Architecture & GC Virtual Machine Integration

**Internal Technical Brief for IT and Management**

| | |
|---|---|
| **Document Version** | 1.0 |
| **Date** | 2026-02-12 |
| **Classification** | Internal |
| **Prepared for** | IT Department, Engineering Management |
| **Author** | NISystem Engineering |

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [System Architecture](#2-system-architecture)
3. [Hardware Integration Methods](#3-hardware-integration-methods)
4. [GC Instrument Integration: The VM Method](#4-gc-instrument-integration-the-vm-method)
5. [Regulatory Compliance](#5-regulatory-compliance)
6. [Data Integrity & Security](#6-data-integrity--security)
7. [Network Architecture](#7-network-architecture)
8. [Operational Benefits](#8-operational-benefits)
9. [IT Requirements Summary](#9-it-requirements-summary)

---

## 1. Executive Summary

ICCSFlux is a portable, self-contained data acquisition and monitoring platform built for industrial measurement, test, and laboratory environments. It collects data from NI hardware (cDAQ, cRIO), Opto22 controllers, Modbus devices, OPC-UA servers, REST APIs, and Gas Chromatograph (GC) instruments, then presents it through a real-time browser-based dashboard with alarms, interlocks, recording, scripting, and audit trail capabilities.

**Key points for management:**

- **Single-PC deployment.** The entire system runs on one Windows PC with no cloud dependency, external databases, or internet requirement. Data never leaves the machine unless explicitly configured (Azure IoT Hub upload is optional).
- **Regulatory ready.** The system implements controls for FDA 21 CFR Part 11 (electronic records and signatures), ISO/IEC 17025 (calibration traceability and measurement uncertainty), and SOC 2 Type II (logical access, network segmentation, monitoring).
- **Legacy GC support.** Gas chromatograph instruments that require Windows XP or Windows 7 vendor software run in isolated Hyper-V virtual machines. A lightweight bridge service (`gc_node`) publishes GC analysis results over MQTT to the main system. The VMs have no internet access and no route to the corporate LAN.
- **Zero IT infrastructure.** No domain controller, Active Directory, SQL Server, or cloud subscription is required. The system generates its own MQTT credentials on first run, uses local file-based storage, and operates on an isolated network segment.
- **Tested.** 663 automated unit tests cover the backend, with additional Vitest coverage for the dashboard.

---

## 2. System Architecture

### 2.1 Component Overview

ICCSFlux consists of four main components, all running on a single Windows PC:

```
 +-----------------------------------------------------------------+
 |  Windows PC (Win10/11 Pro or Server 2022/2025)                  |
 |                                                                 |
 |  +------------------+    +------------------+                   |
 |  |  DAQ Service     |    |  Mosquitto MQTT  |                   |
 |  |  (Python)        |<-->|  Broker          |                   |
 |  |                  |    |  Port 1883 (TCP)  |                   |
 |  |  - Scan loop     |    |  Port 9002 (WS)  |                   |
 |  |  - Scripts       |    +--------+---------+                   |
 |  |  - Alarms        |             |                             |
 |  |  - Recording     |             | WebSocket                   |
 |  |  - Safety        |             |                             |
 |  |  - Audit trail   |    +--------v---------+                   |
 |  +------------------+    |  Dashboard        |                   |
 |                          |  (Vue 3 / Browser)|                   |
 |  +------------------+    |                  |                   |
 |  |  Remote Nodes    |    |  - Widgets       |                   |
 |  |  (MQTT clients)  |    |  - Charts        |                   |
 |  |  - cRIO          |    |  - P&ID Editor   |                   |
 |  |  - Opto22        |    |  - Config        |                   |
 |  |  - GC Node (VM)  |    +------------------+                   |
 |  +------------------+                                           |
 +-----------------------------------------------------------------+
```

| Component | Technology | Purpose |
|-----------|------------|---------|
| **DAQ Service** | Python (~13,000 LOC) | Core engine: hardware reading, MQTT orchestration, alarm evaluation, safety interlocks, PID control, script execution, recording, audit trail |
| **MQTT Broker** | Mosquitto 2.x | Message bus connecting all components. TCP port 1883 (authenticated, for services and remote nodes) and WebSocket port 9002 (localhost-only, for dashboard) |
| **Dashboard** | Vue 3 + TypeScript (~119,000 LOC) | Browser-based HMI with 30+ widget types, P&ID editor, configuration interface, alarm management, recording control |
| **Remote Nodes** | Python (cRIO, Opto22, GC) | Standalone services on remote hardware that communicate via MQTT. Continue operating if the PC disconnects |

### 2.2 Data Flow

```
Hardware Sensors
      |
      v
Hardware Reader (10-100 Hz scan)
      |
      v
Channel Values (in-memory dictionary)
      |
      +---> Script Engine (user calculations, formulas)
      |
      +---> Alarm Manager (ISA-18.2 evaluation)
      |
      +---> Safety Manager (interlock checks, trip actions)
      |
      +---> PID Engine (control loop output)
      |
      v
Token Bucket Rate Limiter (max 4 Hz publish)
      |
      v
MQTT Broker
      |
      +---> Dashboard (real-time display via WebSocket)
      |
      +---> Recording Manager (CSV/TDMS files, buffered write, fsync)
      |
      +---> Audit Trail (append-only JSONL, SHA-256 hash chain)
      |
      +---> Azure IoT Hub (optional, HTTPS upload)
```

### 2.3 Codebase Scale

| Area | Lines of Code | Files |
|------|---------------|-------|
| Backend (Python) | ~120,000 | ~80 |
| Frontend (TypeScript/Vue) | ~119,000 | ~100 |
| Tests | ~14,000 | ~25 |
| Documentation | ~10,000 | ~16 |
| **Total** | **~263,000** | **~220+** |

---

## 3. Hardware Integration Methods

ICCSFlux supports six hardware integration methods. Each can be used independently or in combination within the same project.

### 3.1 Integration Summary

| Method | Connection | Location | Use Case |
|--------|-----------|----------|----------|
| **NI cDAQ** | USB or PCIe | Same PC | Desktop/bench testing, local I/O |
| **NI cRIO** | Ethernet (MQTT) | Remote | Industrial control, harsh environments, autonomous operation |
| **Opto22 groov EPIC** | Ethernet (MQTT) | Remote | Existing Opto22 installations, deterministic PID via CODESYS |
| **Modbus TCP/RTU** | Ethernet or serial | Local or remote | PLCs, power meters, VFDs, third-party instruments |
| **OPC-UA** | Ethernet | Local or remote | SCADA integration, DCS bridging |
| **GC Node** | Ethernet (MQTT) | VM or direct serial | Gas chromatographs (legacy vendor software in Hyper-V VMs) |

Additional protocols: REST API polling, EtherNet/IP (Allen-Bradley), NI CompactFieldPoint.

### 3.2 Remote Node Autonomy

cRIO, Opto22, and GC nodes are independent services that communicate with the central DAQ service over MQTT. If the PC goes offline:

| Capability | cRIO | Opto22 | GC Node |
|-----------|------|--------|---------|
| Continue reading I/O | Yes | Yes | Yes |
| Evaluate alarms locally | Yes | Yes | No |
| Execute safety trip actions | Yes | Yes | No |
| Run user scripts | Yes | Yes | No |
| Log to local audit trail | Yes | Yes | No |
| Auto-reconnect when PC returns | Yes | Yes | Yes |

GC nodes are read-only data bridges. They do not evaluate alarms or execute scripts.

---

## 4. GC Instrument Integration: The VM Method

### 4.1 The Problem

Many Gas Chromatograph instruments in active use rely on vendor analysis software that only runs on Windows XP SP3 or Windows 7 SP1. These operating systems are end-of-life:

- **Windows XP**: End of support April 2014
- **Windows 7**: End of support January 2020

Connecting an XP or Win7 machine to the corporate network or internet violates SOC 2, NIST 800-53, and most corporate security policies. However, the GC instruments themselves are functioning hardware that may have years of service life remaining. Replacing them solely due to software compatibility is costly and often unnecessary.

### 4.2 The Solution: Isolated Hyper-V VMs

ICCSFlux solves this by running the legacy GC vendor software inside Hyper-V Generation 1 virtual machines on the same Windows PC that runs the DAQ service. The VMs connect to an **internal-only virtual switch** with no physical network adapter bridged.

```
  Host PC (Windows 10/11 Pro or Server 2022/2025)
  +------------------------------------------------------------+
  |                                                            |
  |  ICCSFlux DAQ Service  <--- MQTT <--- Mosquitto Broker     |
  |                                       (0.0.0.0:1883)       |
  |                                                            |
  |  Hyper-V                                                   |
  |  +--------------------------------------------------------+|
  |  |  Internal-Only Virtual Switch ("GC-Internal")          ||
  |  |  Subnet: 10.10.10.0/24 (no gateway, no DNS)           ||
  |  |                                                        ||
  |  |  Host adapter: 10.10.10.1                              ||
  |  |                                                        ||
  |  |  VM: GC-Node-01 (Win XP, 10.10.10.10)                 ||
  |  |    GC vendor software writes CSV to C:\GCResults\      ||
  |  |    gc_node.py monitors files, publishes via MQTT       ||
  |  |    --> 10.10.10.1:1883 (host only)                     ||
  |  |                                                        ||
  |  |  VM: GC-Node-02 (Win 7, 10.10.10.11)                  ||
  |  |    GC vendor software (Modbus interface)               ||
  |  |    gc_node.py reads Modbus, publishes via MQTT         ||
  |  |    --> 10.10.10.1:1883 (host only)                     ||
  |  +--------------------------------------------------------+|
  |                                                            |
  |  Dashboard (browser, localhost:9002)                       |
  +------------------------------------------------------------+
```

**What "internal-only" means:**
- The virtual switch has no physical network adapter. It exists only in software between the host and VMs.
- The VMs have no default gateway and no DNS server. They cannot resolve hostnames or route packets beyond 10.10.10.0/24.
- The only outbound path from a VM is TCP port 1883 to 10.10.10.1 (the host). Guest firewalls enforce this.
- There is no NAT, no internet, no corporate LAN access. The VMs are completely air-gapped from everything except the MQTT broker on the host.

### 4.3 How GC Data Flows

The `gc_node` service is a lightweight Python process (~2,700 LOC) that runs inside the VM (or directly on the host for serial/Modbus GC instruments that don't need legacy software). It supports three data acquisition methods:

| Method | How It Works | When to Use |
|--------|-------------|-------------|
| **File watching** | GC vendor software writes result files (CSV/TXT). gc_node monitors the output directory and parses new files as they appear. | Most common. Works with any vendor software that exports results to disk. |
| **Modbus TCP/RTU** | gc_node polls Modbus registers on the GC instrument at a configurable interval. | GC instruments with Modbus output (e.g., ABB NGC, some Emerson models). |
| **Serial (RS-232)** | gc_node reads serial data frames from the GC instrument. Supports line-delimited, STX/ETX, and custom framing protocols. | Older GC instruments with serial-only output. |

Once gc_node parses an analysis result, it publishes the data over MQTT:

```
gc_node (in VM)
    |
    | MQTT publish: nisystem/nodes/gc-001/channels/batch
    | MQTT publish: nisystem/nodes/gc-001/gc/analysis
    | MQTT publish: nisystem/nodes/gc-001/status/system
    | MQTT publish: nisystem/nodes/gc-001/heartbeat
    |
    v
Mosquitto Broker (host, port 1883)
    |
    v
DAQ Service (host)
    |
    +---> Channel values available in dashboard widgets
    +---> Available for alarms, scripts, recording
    +---> Audit trail logs GC analysis events
```

### 4.4 GC Analysis Engine

The gc_node includes a built-in chromatographic analysis engine that processes raw peak data:

| Capability | Description |
|-----------|-------------|
| **Peak detection** | Configurable slope sensitivity, minimum height/area, noise threshold |
| **Baseline correction** | Valley-to-valley and horizontal modes |
| **Peak identification** | Retention index (RI) matching against compound libraries |
| **Quantification** | External standard, normalization, internal standard methods |
| **System Suitability Testing** | USP <621> — theoretical plates (N), tailing factor (T), resolution (R), capacity factor (k') |
| **Quality Control** | Blank checks, duplicate analysis, check standards, spike recovery, calibration verification |

### 4.5 Direct Connection (No VM Required)

If the GC instrument provides data over serial or Modbus without requiring legacy vendor software, gc_node runs directly on the host PC. No VM is needed. This is the simpler and preferred approach when possible.

```
Host PC
  gc_node (runs on host)
      |
      | USB-to-serial adapter
      v
  GC Instrument (serial/Modbus)
```

### 4.6 Python Version Compatibility

| Guest OS | Python Version | Notes |
|----------|---------------|-------|
| Windows XP SP3 | Python 3.4.x | No f-strings, no dataclasses. Uses polling for file watching (no watchdog library). |
| Windows 7 SP1 | Python 3.8.x | Full feature support. |
| Host PC (direct) | Python 3.10+ | Same Python as the DAQ service. |

---

## 5. Regulatory Compliance

ICCSFlux implements controls for three regulatory frameworks. The table below maps specific system capabilities to regulatory requirements.

### 5.1 FDA 21 CFR Part 11 — Electronic Records and Signatures

| 21 CFR Part 11 Section | Requirement | ICCSFlux Implementation |
|------------------------|-------------|------------------------|
| **11.10(a)** | Validate systems | 663 automated tests. IQ/OQ/PQ documentation templates. |
| **11.10(b)** | Generate accurate copies | Project export (JSON), recording export (CSV/TDMS), audit trail export (JSONL + gzip archives). All exports include SHA-256 checksums. |
| **11.10(c)** | Protect records | Append-only audit trail. OS-level file locking on recordings. SHA-256 hash chain for tamper detection. |
| **11.10(d)** | Limit system access | Role-based access control: Guest (view only), Operator (control), Supervisor (configure), Admin (full). Account lockout after failed attempts. |
| **11.10(e)** | Audit trail | Every configuration change, session start/stop, alarm event, safety action, recording operation, and login/logout is logged with: who, what, when, why (reason field), and a SHA-256 hash linking to the previous entry. |
| **11.10(g)** | Authority checks | Role-based permissions enforced on every command. Operators cannot modify alarm limits. Viewers cannot start sessions. |
| **11.10(k)(1)** | Signer accountability | Electronic signatures require password re-verification (not just an active session). Signature events are logged to the audit trail with signature ID, action type, description, reason, and operator identity. |
| **11.10(k)(2)** | Continuous signing | Session tokens expire after configurable timeout (default 30 minutes). Re-authentication required for critical actions. |
| **11.50** | Signature manifestations | Electronic signatures include: printed name, date/time, action description, and reason. Displayed in the audit trail viewer. |
| **11.70** | Signature/record linking | Each signature is linked to its record by a unique signature_id stored in both the audit trail entry and the signed record. |
| **11.100** | General requirements | Electronic signatures are unique to one individual. No shared accounts permitted. Each user has a unique username and password. |
| **11.300** | Controls for ID codes/passwords | Password policy enforcement. Account lockout (default: 5 failed attempts, 15-minute lockout). Session timeout. Passwords hashed with bcrypt. |

### 5.2 ISO/IEC 17025:2017 — Testing and Calibration Laboratories

| ISO 17025 Clause | Requirement | ICCSFlux Implementation |
|-----------------|-------------|------------------------|
| **6.4.1** | Equipment traceability | `CalibrationManager` module tracks calibration records per channel with: certificate number, reference standard, calibration date, due date, and traceability chain back to NIST/SI standards. |
| **6.4.6** | Calibration status | Overdue calibration tracking with health summary. Dashboard can display calibration status per channel. |
| **6.4.7** | Intermediate checks | QC sample tracking (check standards, blanks, duplicates) with pass/fail evaluation against configurable limits. |
| **7.2.1** | Method selection and validation | `MethodValidation` module calculates LOD, LOQ, linearity (R^2), precision (%RSD), and accuracy (% recovery) per ICH Q2(R1). |
| **7.2.2** | Validation of methods | Method validation results stored with the analysis method. Can be re-evaluated when method parameters change. |
| **7.6.1** | Measurement uncertainty | GUM-compliant `UncertaintyBudget` with Type A (statistical) and Type B (non-statistical) components. RSS combination. Welch-Satterthwaite effective degrees of freedom. Coverage factor k=2 for 95% confidence interval. |
| **7.6.2** | Reporting uncertainty | Expanded uncertainty reported alongside measurement values. Components individually documented. |
| **7.7.1** | Data integrity | ALCOA+ principles: Attributable (user ID on every record), Legible (structured JSON), Contemporaneous (timestamps at point of capture), Original (append-only), Accurate (SHA-256 integrity), Complete, Consistent, Enduring, Available. |
| **8.3** | Control of management system documents | Project versioning with schema migrations. Audit trail logs all configuration changes with before/after values. |
| **8.5** | Actions to address risks | ISA-18.2 alarm system with deadband, on/off delays, rate-of-change detection, shelving. Safety interlocks with trip actions. |

### 5.3 SOC 2 Type II — Trust Service Criteria

These controls apply specifically to the GC VM infrastructure:

| SOC 2 Control | Criteria | Implementation |
|--------------|----------|----------------|
| **CC6.1** | Logical access | MQTT broker requires username/password. Each gc_node has unique credentials. No interactive accounts on VMs beyond local admin for maintenance. |
| **CC6.6** | Network segmentation | Internal-only Hyper-V virtual switch. No physical adapter bridged. No default gateway. VMs cannot reach any network outside 10.10.10.0/24. |
| **CC6.7** | Restrict data transmission | Guest firewall allows only outbound TCP 1883 to 10.10.10.1. All other outbound traffic blocked. Data leaves the VM exclusively as MQTT messages. |
| **CC7.2** | Monitoring | Audit trail with SHA-256 hash chain. gc_node heartbeats over MQTT. Mosquitto logs all connection and authentication events. |
| **CC8.1** | Change management | VM snapshots before any software change. gc_node configuration changes logged in audit trail. |
| **A1.2** | Backup and recovery | Weekly VM exports. Daily gc_node config backup. 4-week retention. Annual restore test documented. |

---

## 6. Data Integrity & Security

### 6.1 Audit Trail Architecture

The audit trail is the backbone of compliance. Every significant system event is logged as an append-only JSONL record with cryptographic integrity verification.

```
Entry N:
{
  "sequence": 1042,
  "timestamp": "2026-02-12T14:30:15.123Z",
  "event_type": "configuration.change",
  "user": "jsmith",
  "description": "Changed alarm HIHI limit on TC-001 from 250 to 275",
  "details": { "channel": "TC-001", "field": "hihi_limit", "old": 250, "new": 275 },
  "reason": "Updated per engineering change order ECO-2026-047",
  "hash": "a3f8b2c1d4e5...{SHA-256 of this entry + previous hash}"
}
```

**Tamper detection:** Each entry's hash is computed from the entry payload concatenated with the previous entry's hash. Modifying or deleting any entry breaks the chain. Verification is performed by recalculating hashes from the first entry forward.

**Events logged:**

| Category | Events |
|----------|--------|
| Authentication | Login, logout, failed login, account lockout, electronic signature, failed signature |
| Configuration | Channel add/modify/delete, alarm limit changes, interlock changes, script changes |
| Session | Session start/stop, acquisition start/stop |
| Safety | Alarm triggered/cleared/acknowledged/shelved, interlock trip, safe-state activation |
| Recording | Recording start/stop, file rotation, file close |
| System | Service start/stop, node connect/disconnect, watchdog events |

### 6.2 Electronic Signatures

Critical actions require electronic signature verification — the user must re-enter their password even if they have an active session. Signature events are logged to the audit trail with:

- Signature ID (unique identifier)
- Signer identity (username, role, source IP)
- Action type and description
- Reason for the action
- Timestamp

### 6.3 Recording File Integrity

Data recordings use multiple layers of protection:

| Protection | Mechanism |
|-----------|-----------|
| File locking | OS-level exclusive lock (`msvcrt.locking` on Windows) prevents concurrent writes |
| Flush + sync | `file.flush()` followed by `os.fsync()` after each write buffer ensures data survives power loss |
| SHA-256 checksum | Computed over the complete recording file at close |
| Metadata header | Operator ID, session ID, start time, channel list, project name embedded in file header |
| File rotation | Automatic rotation by size, sample count, or time interval prevents single-file corruption from affecting all data |

### 6.4 MQTT Security

| Layer | Control |
|-------|---------|
| Authentication | PBKDF2-SHA512 hashed passwords. Unique credentials per service (backend, dashboard, each remote node). Auto-generated on first run. |
| Authorization | ACL restricts dashboard to read-all + write-control-topics-only. Backend has full access. |
| Network isolation | MQTT TCP (1883) is accessible from remote nodes on dedicated Ethernet links. WebSocket (9002) is localhost-only. |
| No TLS | Intentional — all traffic is on localhost or dedicated physical links. No shared network. TLS would add certificate management complexity without meaningful security benefit in this deployment model. |

### 6.5 User Access Control

Four role levels with progressively broader permissions:

| Role | View Data | Control Outputs | Configure System | Manage Users |
|------|-----------|----------------|-----------------|-------------|
| Guest/Viewer | Yes | No | No | No |
| Operator | Yes | Yes | No | No |
| Supervisor | Yes | Yes | Yes | No |
| Admin | Yes | Yes | Yes | Yes |

- Account lockout after configurable failed attempts (default: 5 attempts, 15-minute lockout)
- Session timeout (default: 30 minutes of inactivity)
- Passwords stored with bcrypt hashing
- Admin password written to file on first run (chmod 600), never displayed in console or logs

---

## 7. Network Architecture

### 7.1 Standard Deployment (No VMs)

```
   +---------------------+
   |  Windows PC          |
   |                     |
   |  DAQ Service        |
   |  Mosquitto (1883)   |
   |  Dashboard (9002)   |
   |                     |
   +---+--------+--------+
       |        |
  USB Ethernet  USB Serial
       |        |
   +---v---+ +--v-------+
   | cRIO  | | GC Instr |
   +-------+ +----------+
```

All components run on one PC. The cRIO connects via a dedicated USB Ethernet adapter (not the corporate LAN). GC instruments connect via USB-to-serial adapters for direct Modbus/serial communication.

### 7.2 VM Deployment (Legacy GC Software)

When legacy vendor software is required, Hyper-V VMs are added:

```
   +--------------------------------------------------+
   |  Windows PC                                       |
   |                                                  |
   |  DAQ Service                                     |
   |  Mosquitto (0.0.0.0:1883)                        |
   |  Dashboard (localhost:9002)                       |
   |                                                  |
   |  Hyper-V                                         |
   |  +-----------------------------------------+     |
   |  | Internal Switch: 10.10.10.0/24          |     |
   |  |                                         |     |
   |  | Host: 10.10.10.1                        |     |
   |  |                                         |     |
   |  | VM1: 10.10.10.10 (XP) -- gc_node        |     |
   |  | VM2: 10.10.10.11 (W7) -- gc_node        |     |
   |  +-----------------------------------------+     |
   |                                                  |
   +---+--------+-------------------------------------+
       |        |
  USB Ethernet  USB Serial
       |        |
   +---v---+ +--v-------+
   | cRIO  | | GC Instr |
   +-------+ +----------+
```

**Key isolation properties:**
- The internal virtual switch has no bridge to any physical adapter
- VMs have no default gateway and no DNS
- The only outbound traffic from VMs is MQTT to 10.10.10.1:1883
- Guest firewalls block all other outbound traffic
- The host's physical network adapters are completely separate from the VM network

### 7.3 Ports and Protocols

| Port | Protocol | Binding | Purpose | Authentication |
|------|----------|---------|---------|----------------|
| 1883 | MQTT/TCP | 0.0.0.0 | Service-to-service MQTT | PBKDF2-SHA512 username/password |
| 9002 | MQTT/WS | 127.0.0.1 | Dashboard WebSocket | Application-level (useAuth.ts) |
| 22 | SSH | Remote nodes | cRIO/Opto22 deployment | SSH key or password |
| 443 | HTTPS | Outbound (optional) | Azure IoT Hub upload | SAS token |

No inbound internet connections are required. No ports need to be opened on the corporate firewall for normal operation.

---

## 8. Operational Benefits

### 8.1 For Engineering / Operations

| Benefit | Description |
|---------|-------------|
| **Unified view** | All instrument data — thermocouples, pressure transducers, flow meters, GC analysis results, Modbus devices — appears in one dashboard |
| **Real-time alarms** | ISA-18.2 compliant alarm system with shelving, acknowledgment, rate-of-change, and off-delay. Alarms evaluate at scan rate (10-100 Hz) |
| **Safety interlocks** | Backend-authoritative interlocks that trip outputs independent of the browser. Defense-in-depth: edge nodes (cRIO, Opto22) and PC backend both evaluate |
| **Python scripting** | User scripts for calculations, derived values, and automation. Sandboxed for safety. Same API on PC and remote nodes |
| **Automated recording** | CSV or TDMS recording with file rotation, decimation, triggered start/stop, and ALCOA+ data integrity |
| **GC analysis** | Built-in peak detection, compound identification, quantification, system suitability testing, and QC tracking |
| **P&ID editor** | Drag-and-drop process and instrumentation diagram editor with 50+ SCADA symbols, live value binding, and auto-pipe routing |

### 8.2 For IT

| Benefit | Description |
|---------|-------------|
| **No infrastructure** | No AD, SQL Server, IIS, or cloud subscriptions required |
| **Portable** | PyInstaller builds to a self-contained directory. Copy to a USB drive and run on any Windows PC |
| **Isolated network** | MQTT and dashboard traffic stays on localhost or dedicated physical links. Never touches the corporate LAN |
| **VM containment** | Legacy OS instances run in fully isolated Hyper-V VMs with no internet or LAN connectivity |
| **Auto-generated credentials** | MQTT credentials are generated on first run. No manual credential management |
| **Backup-friendly** | All state is in flat files (JSON configs, JSONL audit trail, CSV/TDMS recordings). Standard file backup tools work. VM exports for full recovery |
| **Low maintenance** | Services auto-restart on failure. Remote nodes auto-reconnect. Watchdog monitors for hangs |

### 8.3 For Compliance / Quality

| Benefit | Description |
|---------|-------------|
| **Audit trail** | Cryptographic hash chain, append-only, tamper-detectable. Covers all configuration changes, safety events, and user actions |
| **Electronic signatures** | Password re-verification for critical actions. Signature events logged with full attribution |
| **Calibration traceability** | Per-channel calibration records with certificate references, traceability to NIST/SI, overdue monitoring |
| **Measurement uncertainty** | GUM-compliant uncertainty budgets (Type A + Type B, RSS, Welch-Satterthwaite) |
| **Method validation** | LOD, LOQ, linearity, precision, accuracy calculations per ICH Q2(R1) |
| **QC tracking** | Blanks, check standards, duplicates, spike recovery, calibration verification with pass/fail evaluation |
| **System suitability** | USP <621> evaluation: theoretical plates, tailing factor, resolution, capacity factor |

---

## 9. IT Requirements Summary

### 9.1 Minimum Hardware

| Component | Standard Deployment | With Hyper-V VMs |
|-----------|-------------------|-----------------|
| CPU | Intel Core i5 (4 core) | Intel Core i7 (6+ core), VT-x/AMD-V enabled |
| RAM | 8 GB | 16 GB (+ 2 GB per VM) |
| Storage | 100 GB SSD | 200 GB SSD (+ 20-40 GB per VM VHD) |
| Network | 1x Ethernet | 1x Ethernet + USB Ethernet for cRIO |
| OS | Windows 10/11 Pro (64-bit) | Windows 10/11 Pro or Server 2022/2025 |

Home editions of Windows do not support Hyper-V.

### 9.2 Software Dependencies

| Software | Version | Installed By |
|----------|---------|-------------|
| Python | 3.10+ | Engineering (or portable build includes it) |
| Mosquitto | 2.x | Included in portable build |
| Node.js | 18+ | Only for dashboard development (not needed for portable build) |
| Chrome/Edge | Latest | User's browser |
| Hyper-V | Windows feature | IT (only if VMs are needed) |

### 9.3 What IT Needs to Do

**Standard deployment (no VMs):**
1. Provision a Windows 10/11 Pro PC meeting the hardware requirements
2. No domain join required (standalone is fine)
3. No firewall changes required (all traffic is localhost or dedicated physical links)
4. Ensure the PC has a USB port for cRIO Ethernet adapter (if using cRIO)
5. Standard file backup of `C:\ICCSFlux\` covers all system state

**With GC VMs:**
1. All of the above, plus:
2. Enable Hyper-V (`Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V -All`)
3. Follow the [GC VM Setup Guide](GC_VM_Setup_Guide.md) for VM creation and network configuration
4. Schedule weekly VM exports for backup (`Export-VM`)
5. Document the VM configuration for change management records

### 9.4 What IT Does NOT Need to Do

- No Active Directory integration
- No SQL Server or database provisioning
- No cloud subscriptions (Azure IoT Hub is optional and configured by engineering)
- No TLS certificate management
- No firewall rules for inbound internet traffic
- No load balancer or reverse proxy
- No container runtime (Docker, etc.)
- No scheduled Windows Updates on VMs (they are air-gapped)

---

## Appendix A: Document References

| Document | Location | Audience |
|----------|----------|---------|
| GC VM Setup Guide (step-by-step) | `docs/GC_VM_Setup_Guide.md` | IT |
| Administrator Guide | `docs/ICCSFlux_Administrator_Guide.md` | IT, Engineering |
| Remote Nodes Guide | `docs/ICCSFlux_Remote_Nodes_Guide.md` | Engineering |
| User Manual | `docs/ICCSFlux_User_Manual.md` | Operations |
| Python Scripting Guide | `docs/ICCSFlux_Python_Scripting_Guide.md` | Engineering |
| System Validation Report | `docs/SYSTEM_VALIDATION_REPORT.md` | Quality |

## Appendix B: Glossary

| Term | Definition |
|------|-----------|
| **ALCOA+** | Attributable, Legible, Contemporaneous, Original, Accurate, Complete, Consistent, Enduring, Available — data integrity principles for regulated industries |
| **cDAQ** | Compact Data Acquisition — NI USB/PCIe measurement hardware |
| **cRIO** | CompactRIO — NI industrial controller with real-time Linux OS |
| **DAQmx** | NI's hardware abstraction layer for data acquisition |
| **GC** | Gas Chromatograph — analytical instrument that separates and measures chemical compounds in a gas mixture |
| **GUM** | Guide to the Expression of Uncertainty in Measurement — international standard for reporting measurement uncertainty |
| **ICH Q2(R1)** | International Council for Harmonisation guideline for analytical method validation |
| **ISA-18.2** | International standard for alarm management in process industries |
| **MQTT** | Message Queuing Telemetry Transport — lightweight publish/subscribe messaging protocol |
| **P&ID** | Piping and Instrumentation Diagram |
| **RBAC** | Role-Based Access Control |
| **RI** | Retention Index — standardized measure of compound retention on a GC column |
| **SOC 2** | Service Organization Control Type 2 — audit framework for service organizations |
| **SST** | System Suitability Testing — verification that a chromatographic system performs adequately |
| **USP <621>** | United States Pharmacopeia chapter on chromatography system suitability |
| **21 CFR Part 11** | FDA regulation governing electronic records and electronic signatures |

---

**ICCSFlux System & VM Overview v1.0**
*February 2026*
