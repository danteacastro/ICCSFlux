# ICCSFlux IT Security & Compliance Guide

**System:** ICCSFlux Industrial Data Acquisition Platform
**Version:** 2.0
**Date:** February 2026
**Audience:** IT Security, Compliance Officers, SOC 2 Auditors, Network Administrators, Engineering

---

## Table of Contents

**Part I — Software Integrity & Build Compliance**
1. [Executive Summary: The Hash Problem](#1-executive-summary-the-hash-problem)
2. [Why the Executable Hash Changes Every Build](#2-why-the-executable-hash-changes-every-build)
3. [Code Signing (The Solution)](#3-code-signing-the-solution)
4. [Vulnerability Management & SBOM](#4-vulnerability-management--sbom)
5. [Build Process & Change Management](#5-build-process--change-management)
6. [IT Implementation Guide](#6-it-implementation-guide)

**Part II — System Security Architecture**
7. [System Overview](#7-system-overview)
8. [Architecture Diagram](#8-architecture-diagram)
9. [System Components & Dependencies](#9-system-components--dependencies)
10. [Network Ports & Firewall Rules](#10-network-ports--firewall-rules)
11. [MQTT Broker Security](#11-mqtt-broker-security)
12. [TLS / Encryption](#12-tls--encryption)
13. [Authentication & Access Control](#13-authentication--access-control)
14. [Data Flow & Egress](#14-data-flow--egress)
15. [Audit Trail & Compliance](#15-audit-trail--compliance)
16. [Secrets & Credential Management](#16-secrets--credential-management)

**Part III — Compliance**
17. [SOC 2 Control Mapping](#17-soc-2-control-mapping)
18. [Hardening Checklist](#18-hardening-checklist)

**Part IV — Endpoint Security (SentinelOne / EDR)**
19. [SentinelOne and EDR Compatibility](#19-sentinelone-and-edr-compatibility)

**Appendices**
- [A. Build Verification Script](#appendix-a-build-verification-script)
- [B. Monthly Vulnerability Re-Scan Procedure](#appendix-b-monthly-vulnerability-re-scan-procedure)
- [C. SentinelOne Exclusion Request Template](#appendix-c-sentinelone-exclusion-request-template)

---

# Part I — Software Integrity & Build Compliance

---

## 1. Executive Summary: The Hash Problem

ICCSFlux is an internally-developed industrial data acquisition system compiled from Python source code using PyInstaller. Unlike LabVIEW executables (which compile to deterministic native code), Python-based executables produce a **different SHA-256 hash on every build** — even when the source code has not changed.

This is an inherent property of the Python language runtime, not a deficiency in our build process. Every Python, Java, .NET, Go, and Rust application exhibits the same behavior unless specific countermeasures are taken.

### What This Document Proposes

| Problem | Solution | IT Effort |
|---------|----------|-----------|
| Hash changes every build, triggering review | **Code signing** — IT approves the certificate once, not every hash | One-time setup (~2 hours) |
| No visibility into third-party dependencies | **SBOM** — machine-readable inventory ships with every build | Automated (zero effort) |
| No vulnerability scanning | **pip-audit** — automated scan against CVE databases on every build | Automated (zero effort) |
| Slow release turnaround due to compliance | **Signed builds with SBOM** — no IT ticket needed per release | Zero ongoing effort |

**Bottom line:** We implement the same integrity controls used by Microsoft, NI, Adobe, and every software vendor — code signing with a trusted certificate. IT approves the certificate once; every future build is automatically trusted.

---

## 2. Why the Executable Hash Changes Every Build

### 2.1 Root Cause: Python Hash Randomization

Python 3.3+ enables **hash randomization** by default ([PEP 456](https://peps.python.org/pep-0456/)). On every interpreter startup, Python generates a random seed that changes the internal ordering of dictionaries, sets, and string hashes. This is a **security feature** designed to prevent hash collision denial-of-service attacks (CVE-2012-1150).

When PyInstaller compiles ICCSFlux, it bundles compiled Python bytecode (`.pyc` files). Because Python's hash seed is different on every invocation, the internal layout of these bytecode files changes:

- Dictionary ordering within `__dict__` objects is different each time
- Module ordering in the PYZ archive (the bundled Python library) varies
- Constant tables in compiled code are reordered

**This is the single largest source of non-determinism** and affects every Python application on earth.

### 2.2 Additional Sources of Hash Variation

| Source | Description |
|--------|-------------|
| **PE timestamps** | The Windows PE32+ `.exe` format contains a `TimeDateStamp` field that records the current time at build |
| **UPX compression** | If enabled, the UPX packer can introduce minor variations between runs |

### 2.3 Why LabVIEW Executables Don't Have This Problem

LabVIEW compiles to deterministic native machine code via LLVM. There is no dictionary randomization, no bytecode ordering variation, and no runtime hash seed. The compilation is inherently deterministic.

Additionally, LabVIEW executables are typically **code-signed** by NI or by the customer's own certificate. IT departments whitelist by the publisher certificate, not by individual file hashes. The hash stability question never comes up because the trust model doesn't depend on hashes.

### 2.4 Can We Make Builds Deterministic?

**Yes.** Our build pipeline sets two environment variables that eliminate non-determinism:

```
PYTHONHASHSEED=1              — fixes Python's hash randomization seed
SOURCE_DATE_EPOCH=<git_ts>    — fixes PE header timestamps to the git commit time
```

With these set, two builds from the same git commit on the same machine produce **identical SHA-256 hashes**. However, deterministic builds are a verification aid — the primary integrity mechanism is code signing.

### 2.5 Summary: Hash Changes Are Expected and Safe

| Fact | Implication |
|------|-------------|
| Python randomizes internal data structures on every startup | Hash changes are inherent to the language, not a sign of tampering |
| Every major Python application has this behavior | This is industry-normal, not a deficiency |
| LabVIEW compiles to deterministic native code | Different language → different build properties |
| Code signing proves integrity regardless of hash | Hash tracking is unnecessary when signing is in place |

---

## 3. Code Signing (The Solution)

### 3.1 How Code Signing Works

Every production build is signed with an **Authenticode code signing certificate** (RSA-4096, SHA-256, timestamped via RFC 3161). This embeds a cryptographic signature into the PE header of each `.exe` file that proves three things:

1. **Publisher identity** — the executable was built by our organization
2. **Tamper detection** — any modification to the binary after signing invalidates the signature
3. **Timestamp** — the signature was applied while the certificate was valid (survives certificate expiration)

### 3.2 Code Signing vs. Hash Tracking

| | Per-Hash Approval (Current) | Code Signing (Proposed) |
|---|---|---|
| IT effort per release | New ticket every build | **Zero** (certificate approved once) |
| Build determinism required | Yes | No (we do it anyway, but it's not required) |
| Tamper detection | Must manually recompute hash and compare | **Automatic** (Windows verifies on execution) |
| Publisher verification | No — a hash says nothing about who built it | **Yes** — certificate identifies the signer |
| Survives file transfer | Must recompute hash at destination | Signature travels with the file |
| Industry standard | Rare (impractical at scale) | **Universal** (Microsoft, NI, Adobe, etc.) |
| SOC 2 compliant | Yes | **Yes** |
| Scales to frequent releases | No | **Yes** |

### 3.3 Certificate Details

| Property | Value |
|----------|-------|
| **Type** | OV (Organization Validation) Code Signing |
| **Key algorithm** | RSA-4096 |
| **Digest algorithm** | SHA-256 |
| **Timestamp server** | RFC 3161 (DigiCert TSA) |
| **Validity** | 1 year (renewed annually) |
| **Storage** | Hardware token or password-protected `.pfx` with restricted filesystem ACL |
| **Annual cost** | ~$200-500 (OV) or ~$300-700 (EV) |
| **Signed artifacts** | `ICCSFlux.exe`, `DAQService.exe`, `AzureUploader.exe`, `ModbusTool.exe` |

**Recommended vendor:** Sectigo OV Code Signing (~$226/year). EV provides immediate SmartScreen trust but requires a hardware USB token; OV is sufficient for internal industrial software.

### 3.4 Verification (Three Methods)

**Windows Explorer (non-technical users):**
Right-click any `.exe` → Properties → Digital Signatures tab → verify "This digital signature is OK"

**PowerShell (IT admins):**
```powershell
Get-AuthenticodeSignature "dist\ICCSFlux-Portable\ICCSFlux.exe"

# Expected output:
# SignerCertificate: [Thumbprint]   Subject: CN=Your Company Name...
# Status:           Valid
# StatusMessage:    Signature verified.
```

**Command line (CI/CD):**
```cmd
signtool verify /pa /v "dist\ICCSFlux-Portable\ICCSFlux.exe"
```

### 3.5 What Happens When the Certificate Expires

Because we timestamp every signature (RFC 3161), previously signed executables remain valid indefinitely — the timestamp proves the signature was created while the certificate was active. Only new builds require a valid (renewed) certificate.

---

## 4. Vulnerability Management & SBOM

### 4.1 Software Bill of Materials (SBOM)

Every production build includes a machine-readable **SBOM in CycloneDX JSON format** (`sbom.json`). This lists every third-party dependency with exact versions, enabling:

- Automated vulnerability scanning against NVD/OSV databases
- License compliance auditing
- Supply chain transparency

Example entry:
```json
{
  "type": "library",
  "name": "paho-mqtt",
  "version": "2.1.0",
  "purl": "pkg:pypi/paho-mqtt@2.1.0",
  "licenses": [{ "license": { "id": "EPL-2.0" } }]
}
```

### 4.2 Automated Vulnerability Scanning

Our build pipeline runs **pip-audit** (maintained by the Python Packaging Authority) on every build. It checks all dependencies against the **OSV** (Open Source Vulnerabilities) database and PyPI advisory feed.

A `vulnerability-audit.json` file ships with every build. If critical vulnerabilities are found, the build report flags them for engineering review before release.

### 4.3 Dependency Inventory

| Package | Version | Purpose | License |
|---------|---------|---------|---------|
| paho-mqtt | >=2.0.0 | MQTT messaging | EPL-2.0 |
| cryptography | >=42.0.0 | TLS certificate generation | Apache-2.0 / BSD |
| bcrypt | >=4.0.0 | Password hashing | Apache-2.0 |
| numpy | >=1.26.0 | Numerical computation | BSD-3 |
| scipy | >=1.10.0 | Signal processing | BSD-3 |
| pymodbus | >=3.0.0 | Modbus TCP/RTU | BSD-3 |
| opcua | >=0.98.0 | OPC-UA client | LGPL-3.0 |
| pyserial | >=3.5 | Serial communication | BSD-3 |
| requests | >=2.28.0 | HTTP client | Apache-2.0 |
| psutil | >=5.9.0 | System monitoring | BSD-3 |
| psycopg2-binary | >=2.9.0 | PostgreSQL client | LGPL-3.0 |
| pyinstaller | >=6.0.0 | Build tool (not shipped in final package) | GPL-2.0 |

The Azure IoT uploader uses an isolated dependency set (`paho-mqtt<2.0`, `azure-iot-device`) compiled into a separate executable to avoid version conflicts.

### 4.4 Scanning Schedule

| Trigger | Action |
|---------|--------|
| **Every production build** | Full pip-audit scan + SBOM regeneration (automated) |
| **Monthly** | Re-scan deployed build against updated vulnerability databases |
| **CVE notification** | Immediate rescan; patch and rebuild if affected |

---

## 5. Build Process & Change Management

### 5.1 Build Pipeline

```
Source Code (git repository)
    |
    +-- 1. Version capture      git hash, branch, tag, dirty flag
    +-- 2. Reproducible env     PYTHONHASHSEED=1, SOURCE_DATE_EPOCH=<git commit time>
    +-- 3. Dashboard build      npm run build (Vue.js + TypeScript)
    +-- 4. PyInstaller compile  ICCSFlux.exe, DAQService.exe
    +-- 5. Azure compile        Isolated venv (paho-mqtt 1.x)
    +-- 6. Vulnerability scan   pip-audit -> vulnerability-audit.json
    +-- 7. SBOM generation      CycloneDX -> sbom.json
    +-- 8. Code signing         signtool + Authenticode certificate
    +-- 9. Hash manifest        SHA-256 of all signed executables
    +-- 10. Package             dist/ICCSFlux-Portable/
```

### 5.2 Build Artifacts

Every production build produces these files in `dist/ICCSFlux-Portable/`:

| File | Purpose |
|------|---------|
| `ICCSFlux.exe` | Signed launcher + service manager |
| `DAQService.exe` | Signed data acquisition backend |
| `AzureUploader.exe` | Signed Azure IoT Hub uploader |
| `VERSION.txt` | Git commit hash, branch, build timestamp |
| `sbom.json` | CycloneDX Software Bill of Materials |
| `vulnerability-audit.json` | pip-audit vulnerability scan results |
| `SHA256SUMS.txt` | SHA-256 hashes of all executables |
| `requirements-lock.txt` | Exact dependency versions used in this build |

### 5.3 Change Management Trail

Every release is traceable through:

1. **Git commit hash** — embedded in `VERSION.txt` and every runtime log message
2. **Git log** — full history of code changes with author, date, and description
3. **Signed binary** — cryptographic proof of publisher identity + tamper detection
4. **SBOM** — exact third-party dependency versions at build time
5. **Vulnerability audit** — evidence that dependencies were scanned before release
6. **SHA-256 manifest** — hash verification for file transfer integrity

### 5.4 Release Turnaround

With code signing in place, the release process requires **zero IT involvement**:

| Step | Time | IT Involvement |
|------|------|----------------|
| Code change + git commit | Developer time | None |
| Build (`build.bat`) | ~5 minutes | None |
| Sign + SBOM + audit (automated) | ~30 seconds | None |
| Deploy to target PC (copy folder) | ~1 minute | None |
| Run on target PC | Automatically trusted via publisher rule | **None** |

---

## 6. IT Implementation Guide

### 6.1 One-Time Setup (Estimated: 1-2 Hours)

#### Step 1: Receive the Code Signing Certificate

Engineering will provide:
- One signed sample executable (e.g., `ICCSFlux.exe`)
- The public certificate file (`.cer`)
- This document

#### Step 2: Create an AppLocker Publisher Rule

AppLocker publisher rules trust all executables signed by a specific certificate, regardless of version or hash.

**Via Group Policy Editor:**
1. Open `gpedit.msc`
2. Navigate to: Computer Configuration → Windows Settings → Security Settings → Application Control Policies → AppLocker
3. Right-click "Executable Rules" → Create New Rule
4. Action: **Allow**
5. Conditions: **Publisher**
6. Reference file: browse to the signed `ICCSFlux.exe`
7. Slide the trust level to **Publisher** (trusts any product, any version from this signer)
8. Apply

**Via PowerShell:**
```powershell
# Extract publisher info and create rule
Get-AppLockerFileInformation -Path "\\share\ICCSFlux-Portable\ICCSFlux.exe" |
    New-AppLockerPolicy -RuleType Publisher -User Everyone |
    Set-AppLockerPolicy -Merge
```

#### Step 3: (Alternative) Create a WDAC Publisher Rule

For higher-security environments using Windows Defender Application Control:

```powershell
# Scan signed executables
$Files = Get-SystemDriver -ScanPath "\\share\ICCSFlux-Portable\" -UserPEs -NoScript

# Create policy at Publisher level
New-CIPolicy -Level Publisher -Fallback Hash `
    -FilePath "C:\WDAC\ICCSFlux-Policy.xml" -DriverFiles $Files

# Merge with base policy and deploy
Merge-CIPolicy -PolicyPaths "C:\WDAC\BasePolicy.xml", "C:\WDAC\ICCSFlux-Policy.xml" `
    -OutputFilePath "C:\WDAC\MergedPolicy.xml"
ConvertFrom-CIPolicy "C:\WDAC\MergedPolicy.xml" "C:\WDAC\MergedPolicy.bin"
```

Or use the **WDAC Policy Wizard** GUI tool from Microsoft for a more accessible workflow.

#### Step 4: Test

Run a signed ICCSFlux build on a target machine with the policy applied. Verify it launches without being blocked.

#### Step 5: Annual Maintenance

When the code signing certificate is renewed (annually), Engineering provides the updated `.cer` file. The AppLocker/WDAC publisher rule does **not** need to change — it trusts the publisher identity, which remains the same across renewals.

### 6.2 Ongoing Effort: Zero

After the one-time setup, no IT action is required for new releases. The publisher rule trusts the signing certificate. New builds, new features, bug fixes, security patches — all automatically trusted.

### 6.3 AppLocker Rule Levels Explained

| Rule Level | What It Matches | Maintenance Burden | Recommendation |
|------------|----------------|-------------------|----------------|
| **Hash** | Exact SHA-256 file hash | New rule per build | **Do not use** |
| FileName | PE original filename | Medium | Not recommended |
| FilePublisher | Publisher + product name + version | Low-medium | Acceptable |
| **Publisher** | Certificate signer identity | Approve once, done forever | **Recommended** |

### 6.4 Internal CA Alternative

If your organization has an internal Certificate Authority (Active Directory Certificate Services), IT can:

1. Issue a code signing certificate from the internal CA (free, no annual cost)
2. Create a WDAC/AppLocker rule trusting the internal CA for code signing
3. All executables signed by internal CA certificates are automatically trusted

The downside: internal CA certificates are not trusted outside your organization. For external distribution, a public CA certificate (Sectigo, DigiCert) is required.

---

# Part II — System Security Architecture

---

## 7. System Overview

ICCSFlux is a portable industrial data acquisition system that runs on our company's Windows PCs. It acquires process data (temperature, pressure, flow, etc.) that is **owned by our customers**. The system reads hardware sensors (NI DAQmx, Modbus, OPC-UA, REST, EtherNet/IP), processes data through safety interlocks and scripts, records to local files, and optionally uploads to our Azure IoT Hub account.

**Data ownership:** The process data acquired by ICCSFlux belongs to the customer. Our company's equipment (workstations, Azure account) hosts customer-owned data during and after the engagement for a defined retention period.

**Deployment model:** Single Windows PC (owned by our company) runs all core services at or near the customer's process. Optional remote controllers (NI cRIO, Opto22 groov, CompactFieldPoint) connect over the plant LAN. The system is designed to run air-gapped or with limited internet access.

**Cloud component:** The system operates fully offline by default. When Azure IoT Hub is enabled, customer data is uploaded to **our company's Azure IoT Hub account** (HTTPS :443, outbound only) and retained for a configured period. This is the only internet-facing connection.

---

## 8. Architecture Diagram

```
                         INTERNET (optional)
                              |
                         [Azure IoT Hub]
                         (our Azure account —
                          hosts customer data)
                         HTTPS :443 (outbound only)
                              ^
                              |
    +---------------------------------------------------------+
    |                    WINDOWS PC                            |
    |                                                         |
    |  +-------------+  +-------------+  +-----------------+  |
    |  | ICCSFlux    |  | DAQService  |  | AzureUploader   |  |
    |  | Launcher    |  | (.exe)      |  | (.exe)          |  |
    |  +------+------+  +------+------+  +--------+--------+  |
    |         |                |    \              |            |
    |         |                |     \    +--------+--------+  |
    |         |                |      +-->| historian.db    |  |
    |         |                |          | (SQLite, WAL)   |--+
    |         |         +------+------+  +-----------------+  |
    |         +-------->| Mosquitto   |   AzureUploader reads |
    |                   | MQTT Broker |   data + config from  |
    |                   +--+--+--+--+-+   historian.db — no   |
    |                      |  |  |  |     MQTT dependency     |
    |     TCP :1883 -------+  |  |  +------- WS :9003 ------->| LAN
    |     (localhost only)    |  |           (LAN, auth)       |
    |                         |  |                             |
    |     TLS :8883 ----------+  +---------- WS :9002         |
    |     (LAN, encrypted)       (localhost, anonymous)        |
    |                                    |                     |
    |                            +-------+--------+            |
    |                            | HTTP :5173     |            |
    |                            | Dashboard      |            |
    |                            | (browser)      |            |
    |                            +----------------+            |
    +---------------------------------------------------------+
              |                          |
         TLS :8883                  TLS :8883
              |                          |
    +---------+--------+    +------------+-----------+
    |  NI cRIO         |    |  Opto22 groov EPIC     |
    |  (remote node)   |    |  (remote node)         |
    +------------------+    +------------------------+
```

---

## 9. System Components & Dependencies

### 9.1 Core Services (all run on the Windows PC)

| Component | Executable | Role | Starts On | Depends On |
|-----------|-----------|------|-----------|------------|
| **Mosquitto MQTT Broker** | `mosquitto/mosquitto.exe` | Central message bus | System start | Nothing |
| **DAQ Service** | `DAQService.exe` | Main backend: hardware I/O, scripts, alarms, safety, recording | After Mosquitto | Mosquitto |
| **Azure Uploader** | `AzureUploader.exe` | Uploads telemetry to our Azure IoT Hub account (optional) | After DAQ Service | historian.db (SQLite) |
| **Dashboard HTTP Server** | Built into `ICCSFlux.exe` | Serves the Vue 3 web dashboard | System start | Nothing |
| **ICCSFlux Launcher** | `ICCSFlux.exe` | Starts/stops/monitors all services | User launches | Nothing |

### 9.2 Optional Remote Nodes

| Component | Platform | Role | Connection |
|-----------|----------|------|------------|
| **cRIO Node** | NI cRIO (Linux RT) | Local I/O scanning + independent safety | MQTT TLS :8883 |
| **Opto22 Node** | groov EPIC/RIO (Linux) | Local I/O scanning + independent safety | MQTT TLS :8883 |
| **cFP Node** | NI CompactFieldPoint | Modbus-to-MQTT bridge + safety | MQTT TLS :8883 |

---

## 10. Network Ports & Firewall Rules

### 10.1 Inbound Ports

| Port | Protocol | Bind Address | Encryption | Auth | Purpose | Firewall Rule |
|------|----------|-------------|------------|------|---------|---------------|
| **1883** | MQTT TCP | `127.0.0.1` | None | PBKDF2-SHA512 | Local service communication | **BLOCK from network** |
| **8883** | MQTT TCP | `0.0.0.0` | TLS 1.2+ | PBKDF2-SHA512 | Remote node connections | **ALLOW from plant LAN** |
| **9002** | WebSocket | `127.0.0.1` | None | Anonymous (app-level) | Local dashboard browser | **BLOCK from network** |
| **9003** | WebSocket | `0.0.0.0` | None* | PBKDF2-SHA512 | Remote dashboards on LAN | **ALLOW from trusted LAN** |
| **5173** | HTTP | `127.0.0.1` | None | None (static files) | Dashboard web server | **BLOCK from network** |

> \* Port 9003 does not have TLS. If remote dashboards are used over an untrusted network, deploy a reverse proxy with TLS termination.

### 10.2 Outbound Connections

| Destination | Port | Protocol | Encryption | Purpose | Required? |
|-------------|------|----------|------------|---------|-----------|
| Azure IoT Hub | 443 | HTTPS | TLS 1.2+ | Telemetry upload | Optional |
| Twilio API | 443 | HTTPS | TLS 1.2+ | SMS alarm notifications | Optional |
| SMTP Server | 587 | SMTP | STARTTLS | Email alarm notifications | Optional |
| Modbus Devices | 502 | TCP | None | Register polling | Per project |
| OPC-UA Servers | 4840 | OPC-UA | Configurable | Tag subscriptions | Per project |
| REST Endpoints | Varies | HTTP/HTTPS | Configurable | API polling | Per project |
| EtherNet/IP | 44818 | TCP | None | Allen-Bradley scanning | Per project |

### 10.3 Recommended Firewall Policy

```
# Required for remote nodes
ALLOW TCP IN  :8883  FROM <plant-LAN-subnet>   # cRIO/Opto22 MQTT (TLS)

# Optional — remote dashboards
ALLOW TCP IN  :9003  FROM <supervisor-subnet>   # Remote dashboard WebSocket

# Optional — outbound (only if features enabled)
ALLOW TCP OUT :443   TO *.azure-devices.net     # Azure IoT Hub
ALLOW TCP OUT :443   TO api.twilio.com          # Twilio SMS
ALLOW TCP OUT :587   TO <smtp-server>           # Email

# Default deny
DENY  ALL IN         FROM any
```

---

## 11. MQTT Broker Security

### 11.1 Listener Configuration

Mosquitto runs with `per_listener_settings true` — each port has independent auth and ACL.

| Listener | Bind | Transport | Auth | Anonymous |
|----------|------|-----------|------|-----------|
| :1883 | 127.0.0.1 | TCP | Yes | No |
| :8883 | 0.0.0.0 | TCP + TLS | Yes | No |
| :9002 | 127.0.0.1 | WebSocket | No | Yes |
| :9003 | 0.0.0.0 | WebSocket | Yes | No |

### 11.2 MQTT Users

| Username | Purpose | Hash Algorithm |
|----------|---------|----------------|
| `backend` | DAQ Service, Azure Uploader, Watchdog | PBKDF2-SHA512 |
| `dashboard` | Remote dashboard browsers (port 9003) | PBKDF2-SHA512 |

Passwords are 24-byte cryptographically random tokens generated by `secrets.token_urlsafe(24)`.

### 11.3 Access Control

The `dashboard` user has **no wildcard write access** — only explicitly listed command topics (start/stop acquisition, acknowledge alarms, etc.). The `backend` user has full read/write access to all topics.

---

## 12. TLS / Encryption

### 12.1 Certificate Authority (Self-Signed)

| Property | Value |
|----------|-------|
| Algorithm | RSA 2048-bit, SHA-256 |
| Validity | 10 years |
| Issuer | `O=ICCSFlux, CN=ICCSFlux MQTT CA` |
| Generation | Automatic on first run |

### 12.2 TLS Usage

| Connection | TLS | Notes |
|-----------|-----|-------|
| MQTT :8883 (remote nodes) | **Yes** | Server cert verified by CA cert on nodes |
| MQTT :1883 (local) | No | Localhost-only |
| WebSocket :9002 (local dashboard) | No | Localhost-only |
| Azure IoT Hub | **Yes** | TLS 1.2+ enforced by Azure SDK |
| Twilio / SMTP | **Yes** | HTTPS / STARTTLS |

---

## 13. Authentication & Access Control

### 13.1 Three Authentication Layers

| Layer | Mechanism | Scope |
|-------|----------|-------|
| **MQTT Broker** | PBKDF2-SHA512 password file | Controls broker access |
| **Dashboard App** | bcrypt + session tokens | Controls UI permissions |
| **Industrial Protocol** | Per-protocol (OPC-UA certs, API keys) | Controls data source access |

### 13.2 Dashboard User Roles (RBAC)

| Role | Permissions |
|------|------------|
| **Guest** | View data, view alarms (read-only) |
| **Operator** | + Acknowledge alarms, start/stop recording, control outputs |
| **Supervisor** | + Configure channels/alarms/safety, load/save projects |
| **Admin** | + Manage users, modify system config, bypass safety locks |

### 13.3 Session Security

| Setting | Value |
|---------|-------|
| Session max age | 24 hours |
| Idle timeout | 30 minutes |
| Password hashing | bcrypt (adaptive cost) |
| Account lockout | 5 failed attempts → 15-minute lockout |
| Default admin password | Random, written to `data/initial_admin_password.txt` (owner-only permissions) |

---

## 14. Data Flow & Egress

All data acquired by ICCSFlux is customer-owned process data. This section describes where that data resides and where it is transmitted.

### 14.1 Data That Stays on Our Workstation

| Data Type | Location | Format | Data Owner |
|-----------|---------|--------|------------|
| Recorded sensor data | `data/recordings/` | CSV or TDMS | Customer |
| Historian database | `logs/historian/historian.db` | SQLite (WAL mode, 30-day retention) | Customer |
| Audit trail | `data/audit_*.jsonl` | JSONL (append-only, SHA-256 hash chain) | Customer |
| Project configuration | `config/projects/*.json` | JSON | Customer |
| User accounts | `data/users.json` | JSON (bcrypt hashes) | Internal |

### 14.2 Data That Leaves Our Workstation

| Destination | What Data | Data Owner | Transport | Rate Limit | Hosted By |
|-------------|-----------|------------|-----------|------------|-----------|
| Our Azure IoT Hub account | Selected channel values + safety events | Customer | HTTPS :443 | Configurable (1 Hz default) | **Us** |
| Twilio API | Alarm name + severity (160 chars) | Customer | HTTPS :443 | 300s cooldown per alarm | Third party (Twilio) |
| SMTP Server | Alarm details | Customer | STARTTLS :587 | Same as SMS | Varies |

**What is NOT uploaded:** Credentials, system configuration, user accounts, raw file recordings, script code.

**Data retention:** Customer data on our workstation is retained locally for the duration of the engagement. Data uploaded to our Azure IoT Hub account is retained for a configured period. Retention policies should be agreed upon with the customer before enabling Azure upload.

---

## 15. Audit Trail & Compliance

### 15.1 Standards Addressed

| Standard | Feature |
|----------|---------|
| **21 CFR Part 11** | Electronic records, electronic signatures, audit trail, user attribution |
| **ALCOA+** | Attributable, Legible, Contemporaneous, Original, Accurate (SHA-256 hash chain) |
| **ISA-18.2** | Alarm management lifecycle audit |
| **IEC 61511** | Safety interlock demand counting, proof test tracking |

### 15.2 Implementation

| Property | Value |
|----------|-------|
| Format | JSON Lines (one entry per line) |
| Integrity | SHA-256 hash chain (each entry hashes the previous) |
| Tamper detection | `verify_integrity()` walks full chain |
| File permissions | chmod 600 (owner read/write only) |
| Rotation | Size-based (50 MB default) |
| Retention | 365 days (configurable), older logs auto-compressed |

---

## 16. Secrets & Credential Management

| File | Content | Generated | Permission |
|------|---------|-----------|------------|
| `config/mqtt_credentials.json` | MQTT passwords (plaintext) | Auto, first run | chmod 600 |
| `config/mosquitto_passwd` | PBKDF2-SHA512 hashed passwords | Auto, first run | chmod 600 |
| `config/tls/ca.key` | CA private key | Auto, first run | chmod 600 |
| `config/tls/server.key` | Server private key | Auto, first run | chmod 600 |
| `data/initial_admin_password.txt` | Bootstrap admin password | Auto, first run | chmod 600 |

**Rules:**
- Passwords are never logged to console or log files
- MQTT credentials are never transmitted over the network
- Azure IoT Hub connection strings are configured via the dashboard UI, stored in the `azure_config` table in `historian.db`, and read by AzureUploader at runtime — never in source code or environment variables
- The admin password file should be deleted after first login

---

# Part III — Compliance

---

## 17. SOC 2 Control Mapping

### Applicability Note

ICCSFlux acquires and stores customer-owned process data on our equipment (workstations) and, when Azure IoT Hub is enabled, in our Azure cloud account. The on-premises OT components are primarily governed by **IEC 62443** (see [OT Security Standards Reference](OT_Security_Standards_Reference.md), Section 10). However, because we host customer data on our infrastructure, the data handling controls that SOC 2 addresses are relevant — particularly around access control, encryption, audit trails, and data retention.

The table below maps ICCSFlux controls to SOC 2 Trust Services Criteria. This is not a claim of SOC 2 compliance — it documents which controls exist and where they align.

| SOC 2 Criterion | Requirement | ICCSFlux Control |
|-----------------|-------------|------------------|
| **CC6.1** — Logical access | Restrict access to assets | MQTT auth (PBKDF2), dashboard RBAC, account lockout |
| **CC6.2** — Authorization | Principle of least privilege | Per-topic MQTT ACL, role-based permissions (Guest/Operator/Supervisor/Admin) |
| **CC6.3** — Encryption in transit | Protect data in motion | TLS 1.2+ on port 8883, HTTPS for Azure IoT Hub |
| **CC6.6** — Network access | Restrict network exposure | Localhost binding on ports 1883/9002/5173 |
| **CC6.8** — Prevent unauthorized software | Control software execution | Code-signed executables, AppLocker/WDAC publisher rule |
| **CC7.1** — Monitoring | Detect anomalies | Alarm flood detection, COMM_FAIL on missing channels |
| **CC7.3** — Security events | Evaluate threats | Failed login audit with lockout, hash chain tamper detection |
| **CC8.1** — Change management | Authorize and document changes | Git commits, signed builds, SBOM, vulnerability audit |
| **CC8.1** — Integrity verification | Verify deployed software | Authenticode code signing, SHA-256 manifests |
| **CC3.4** — Risk assessment | Identify and assess risks | Automated pip-audit vulnerability scanning on every build |
| **A1.2** — Recovery | Auto-restart and crash safety | Exponential backoff restart, OS-level file locks, fsync |
| **PI1.1** — Data integrity | Protect records | SHA-256 hash chain audit trail, ALCOA+ compliance |
| **C1.1** — Confidentiality | Protect confidential information | Customer data encrypted in transit (TLS/HTTPS), localhost-only ports for sensitive services, Azure connection strings stored in local DB (not env vars or source) |
| **C1.2** — Data disposal | Dispose of confidential data | Historian 30-day auto-prune, configurable Azure retention, local recordings managed per engagement |

### Gaps

The following SOC 2 areas are not currently addressed by ICCSFlux and would need organizational-level controls:

| SOC 2 Criterion | Gap |
|-----------------|-----|
| **CC1.x–CC2.x** — Governance | No formal security governance policy within the software itself — this is an organizational responsibility |
| **CC6.7** — Data classification | No built-in data classification labels — all acquired data is treated as customer-confidential by default |
| **CC9.1** — Risk mitigation | No formal risk register — risk assessment is per-deployment via IEC 62443 security levels |
| **P1.x** — Privacy | Process data (temperatures, pressures, flows) is not typically PII, but no privacy impact assessment framework is built in |

---

## 18. Hardening Checklist

### Software Integrity (NEW)

- [ ] Code signing certificate obtained and verified
- [ ] AppLocker or WDAC publisher rule deployed to all target machines
- [ ] Sample signed executable verified on target machine
- [ ] SBOM (`sbom.json`) reviewed for unexpected dependencies
- [ ] Vulnerability audit (`vulnerability-audit.json`) reviewed — no critical CVEs
- [ ] Annual certificate renewal scheduled

### Network Security

- [ ] Port 1883 bound to `127.0.0.1` only
- [ ] Port 9002 bound to `127.0.0.1` only
- [ ] Port 5173 bound to `127.0.0.1` only
- [ ] Port 8883 restricted to plant LAN subnet via Windows Firewall
- [ ] Port 9003 restricted to supervisor subnet (or disabled)
- [ ] No other inbound ports open

### MQTT Broker

- [ ] `per_listener_settings true` in `mosquitto.conf`
- [ ] `allow_anonymous false` on ports 1883, 8883, 9003
- [ ] ACL restricts `dashboard` user to explicit topics only
- [ ] Credentials are unique per installation (auto-generated)
- [ ] Password file uses PBKDF2-SHA512

### Authentication

- [ ] Default admin password changed after first login
- [ ] `data/initial_admin_password.txt` deleted
- [ ] Account lockout enabled (5 failures, 15-minute lockout)
- [ ] Session timeout configured (30-minute idle)
- [ ] Guest role is read-only

### Data Protection

- [ ] NTFS permissions on `config/` restrict to service account + administrators
- [ ] NTFS permissions on `data/` restrict to service account + administrators
- [ ] Azure uploads limited to selected channels only
- [ ] Audit trail hash chain integrity verified periodically

### Endpoint Security (SentinelOne / EDR)

- [ ] SentinelOne Signer Identity exclusion created for code signing certificate
- [ ] Path exclusion for `_runtime/` directory (PyInstaller extraction)
- [ ] Child process spawning not triggering false positives
- [ ] Network port listening (1883, 5173, 8883, 9002, 9003) not triggering alerts
- [ ] Exclusion scoped to correct site/group (not overly broad)
- [ ] Hash-based exclusions removed (replaced by certificate-based)

### Operational

- [ ] Windows Defender exclusion for `ICCSFlux-Portable/` directory
- [ ] Windows power settings prevent sleep during acquisition
- [ ] Automatic Windows Update restarts disabled during production hours
- [ ] Backup strategy covers `config/` and `data/` directories

---

# Part IV — Endpoint Security (SentinelOne / EDR)

---

## 19. SentinelOne and EDR Compatibility

### 19.1 The Problem

SentinelOne (and similar EDR products like CrowdStrike, Carbon Black, and Cylance) can flag ICCSFlux executables for two reasons:

1. **PyInstaller packing pattern** — PyInstaller bundles Python bytecode into a self-extracting `.exe` that unpacks to a temporary `_runtime` directory at launch. This runtime extraction behavior is structurally similar to how some malware packers operate, triggering behavioral heuristics even though the software is legitimate.

2. **Hash changes between builds** — If SentinelOne was configured with a hash-based allow rule for a previous build, a new build with a different hash will be treated as an unknown/untrusted executable and may be quarantined or blocked.

3. **Behavioral triggers** — ICCSFlux's legitimate behaviors (listening on network ports, spawning child processes for Mosquitto/DAQService, reading hardware via DLLs) can trigger behavioral detection rules designed to catch malware.

### 19.2 The Solution: Certificate-Based Exclusion (Signer Identity)

SentinelOne supports **three types of exclusions**. Only one is appropriate for ICCSFlux:

| Exclusion Type | How It Works | Maintenance | Recommendation |
|---------------|-------------|-------------|----------------|
| **Hash exclusion** | Whitelists a specific SHA-256 hash | New exclusion every build | **Do not use** |
| **Path exclusion** | Suppresses alerts from a specific folder | Medium — must match install path | Acceptable as a backup |
| **Signer Identity (Certificate)** | Whitelists all executables signed by a specific certificate | **Approve once, all builds trusted** | **Recommended** |

A **Signer Identity exclusion** tells SentinelOne: "Trust all executables signed by this certificate." This is the same mechanism used by vendors like Microsoft, Axcient, ConnectWise, and Automox to prevent their agents from being flagged by SentinelOne.

### 19.3 Creating the SentinelOne Exclusion (IT Steps)

#### Option A: Certificate / Signer Identity Exclusion (Preferred)

This requires that ICCSFlux executables are code-signed (see Section 3).

**In the SentinelOne Management Console:**

1. Navigate to **Sentinels** → **Exclusions** (or **Settings** → **Exclusions**)
2. Click **New Exclusion**
3. Exclusion Type: **Signer Identity** (or **Certificate**)
4. Enter the **Signer Identity** value from the code signing certificate
   - To find this: on any machine with SentinelOne, run the signed `.exe` and check the detection details in the console — the "Signer Identity" field will be populated
   - Or: right-click the `.exe` → Properties → Digital Signatures → Details → view the signer's Common Name (CN)
5. Exclusion Mode: **Suppress Alerts**
6. OS Type: **Windows**
7. Scope: Apply to the site group or site where ICCSFlux machines are located
8. Description: `ICCSFlux industrial data acquisition system — internally developed, code-signed`
9. Save

After this, every executable signed with the same certificate is automatically trusted by SentinelOne — no matter how many times the hash changes.

#### Option B: Path Exclusion (Fallback — Use If Not Yet Code-Signed)

If code signing is not yet in place, a path exclusion prevents SentinelOne from scanning the ICCSFlux installation directory.

**In the SentinelOne Management Console:**

1. Navigate to **Exclusions** → **New Exclusion**
2. Exclusion Type: **Path**
3. Path: `C:\ICCSFlux-Portable\` (or wherever the system is installed)
4. Include Sub-Folders: **Yes**
5. Exclusion Mode: **Suppress Alerts**
6. Scope: Apply to relevant site/group
7. Save

**Important:** Path exclusions are less secure than certificate exclusions because they trust any file in the path regardless of origin. Use this only as a temporary measure until code signing is implemented.

#### Option C: Hash Exclusion (Not Recommended)

A hash exclusion whitelists one specific file. Since ICCSFlux hashes change with every build, this requires a new exclusion on every release — defeating the purpose.

If IT insists on hash exclusions as a temporary measure:

1. Find the SHA-256 hash: `Get-FileHash "ICCSFlux.exe" -Algorithm SHA256`
2. In SentinelOne: **Exclusions** → **New Exclusion** → **File Hash** → enter the hash
3. Repeat for `DAQService.exe` and `AzureUploader.exe`
4. **Repeat the entire process on every new build**

This is explicitly **not recommended** and is the workflow we are trying to eliminate.

### 19.4 Additional SentinelOne Configuration

#### Runtime Directory Exclusion

PyInstaller extracts bundled files to a `_runtime` temporary directory on first launch. SentinelOne's behavioral engine may flag this extraction. Add a path exclusion for the runtime directory:

- Path: `C:\ICCSFlux-Portable\_runtime\`
- Include Sub-Folders: Yes
- Mode: Suppress Alerts

#### Child Process Trust

ICCSFlux launches child processes (Mosquitto, DAQService, AzureUploader). If SentinelOne flags these as suspicious child process spawning:

- The Signer Identity exclusion (Option A) covers all signed child executables automatically
- If using path exclusion, ensure the path covers all executable locations

#### Network Activity

SentinelOne may flag ICCSFlux for listening on network ports (1883, 5173, 8883, 9002, 9003). These are legitimate MQTT broker and web server ports. If firewall or network activity alerts trigger:

- Create a **Network exclusion** for the specific ports if your SentinelOne policy supports it
- Or document these ports as expected behavior in the exclusion description

### 19.5 Other EDR Products

The same principles apply to other endpoint detection and response (EDR) products:

| EDR Product | Certificate Exclusion | Path Exclusion | Hash Exclusion |
|-------------|----------------------|----------------|----------------|
| **SentinelOne** | Signer Identity | Path exclusion | File hash |
| **CrowdStrike Falcon** | Certificate-based IOA exclusion | Sensor visibility exclusion | Allow by hash (ML/detection) |
| **Carbon Black** | Certificate reputation | Path-based bypass | Hash-based allow |
| **Cylance** | Certificate safe list | Script/folder exclusion | Hash safe list |
| **Microsoft Defender for Endpoint** | Certificate indicator (Allow) | Folder exclusion | File hash indicator (Allow) |
| **Sophos Intercept X** | Signing certificate exclusion | Path exclusion | SHA-256 allow |

In all cases, **certificate-based exclusion is the recommended approach** — it survives hash changes, proves publisher identity, and is the industry standard for internally-developed software.

### 19.6 Pre-Signed Workaround (Immediate Relief)

If IT needs to unblock ICCSFlux immediately while the code signing certificate is being procured (~1-3 business days):

1. **Path exclusion** on the ICCSFlux installation directory (see Option B)
2. **Inform IT** that this is temporary and will be replaced with a certificate exclusion
3. Once the certificate arrives, sign the executables, create the Signer Identity exclusion, and remove the path exclusion

---

## Appendix A: Build Verification Script

IT can run this PowerShell script to verify any ICCSFlux build:

```powershell
param([string]$BuildPath = "dist\ICCSFlux-Portable")

Write-Host "`nICCSFlux Build Verification" -ForegroundColor Cyan
Write-Host "==========================" -ForegroundColor Cyan

# 1. Verify code signatures
$exes = Get-ChildItem "$BuildPath\*.exe"
$allValid = $true
foreach ($exe in $exes) {
    $sig = Get-AuthenticodeSignature $exe.FullName
    if ($sig.Status -eq "Valid") {
        Write-Host "[PASS] $($exe.Name) - Signed by: $($sig.SignerCertificate.Subject)" -ForegroundColor Green
    } else {
        Write-Host "[FAIL] $($exe.Name) - $($sig.StatusMessage)" -ForegroundColor Red
        $allValid = $false
    }
}

# 2. Check VERSION.txt
if (Test-Path "$BuildPath\VERSION.txt") {
    Write-Host "`n--- VERSION.txt ---" -ForegroundColor Yellow
    Get-Content "$BuildPath\VERSION.txt"
}

# 3. Check SBOM
if (Test-Path "$BuildPath\sbom.json") {
    $sbom = Get-Content "$BuildPath\sbom.json" | ConvertFrom-Json
    Write-Host "`n[INFO] SBOM: $($sbom.components.Count) components" -ForegroundColor Cyan
} else {
    Write-Host "[WARN] sbom.json not found" -ForegroundColor Yellow
}

# 4. Check vulnerability audit
if (Test-Path "$BuildPath\vulnerability-audit.json") {
    Write-Host "[INFO] Vulnerability audit present" -ForegroundColor Cyan
} else {
    Write-Host "[WARN] vulnerability-audit.json not found" -ForegroundColor Yellow
}

# 5. Verify SHA256SUMS
if (Test-Path "$BuildPath\SHA256SUMS.txt") {
    Write-Host "`n--- Hash Verification ---" -ForegroundColor Yellow
    foreach ($line in Get-Content "$BuildPath\SHA256SUMS.txt") {
        $parts = $line -split "  "
        $expectedHash = $parts[0]
        $fileName = $parts[1]
        $filePath = Join-Path $BuildPath $fileName
        if (Test-Path $filePath) {
            $actualHash = (Get-FileHash $filePath -Algorithm SHA256).Hash.ToLower()
            if ($actualHash -eq $expectedHash) {
                Write-Host "[PASS] $fileName" -ForegroundColor Green
            } else {
                Write-Host "[FAIL] $fileName — hash mismatch" -ForegroundColor Red
                $allValid = $false
            }
        }
    }
}

# Result
if ($allValid) {
    Write-Host "`n[RESULT] All checks passed." -ForegroundColor Green
} else {
    Write-Host "`n[RESULT] VERIFICATION FAILED — do not deploy." -ForegroundColor Red
}
```

---

## Appendix B: Monthly Vulnerability Re-Scan Procedure

For deployed systems that are not rebuilt frequently, re-scan the dependency lock file monthly:

```powershell
# Re-scan against current vulnerability databases
pip-audit --requirement "\\target-pc\ICCSFlux-Portable\requirements-lock.txt" `
    --format json --output monthly-audit.json

# Review results
python -c "
import json, sys
with open('monthly-audit.json') as f:
    data = json.load(f)
vulns = [d for d in data.get('dependencies', []) if d.get('vulns')]
if vulns:
    print(f'WARNING: {len(vulns)} packages with known vulnerabilities:')
    for v in vulns:
        print(f'  {v[\"name\"]} {v[\"version\"]}: {len(v[\"vulns\"])} issue(s)')
    sys.exit(1)
else:
    print('No known vulnerabilities found.')
"
```

If vulnerabilities are found, rebuild from source with updated dependencies and redeploy.

---

## Appendix C: SentinelOne Exclusion Request Template

Use this template when submitting an exclusion request to your IT/Security team:

```
SENTINELONE EXCLUSION REQUEST
==============================

Application:     ICCSFlux Industrial Data Acquisition System
Developer:       [Your Company Name]
Exclusion Type:  Signer Identity (Certificate-based)

Signer Identity: [CN from code signing certificate]
Certificate:     [Certificate thumbprint — get from: Get-AuthenticodeSignature ICCSFlux.exe]

Exclusion Mode:  Suppress Alerts
OS Type:         Windows
Scope:           [Site/Group name for ICCSFlux machines]

Justification:
ICCSFlux is an internally-developed industrial data acquisition system
compiled with PyInstaller. PyInstaller bundles Python bytecode into a
self-extracting .exe, which can trigger behavioral heuristics. The
application is code-signed with our organization's Authenticode
certificate. A certificate-based (Signer Identity) exclusion is
requested so that all current and future builds are automatically
trusted without requiring per-hash exclusions on every release.

Expected behaviors that may trigger alerts:
- Extracts bundled files to _runtime/ directory on first launch
- Launches child processes: mosquitto.exe, DAQService.exe, AzureUploader.exe
- Listens on TCP ports: 1883, 5173, 8883, 9002, 9003
- Reads NI-DAQmx hardware DLLs for sensor data acquisition
- Writes to data/recordings/ and data/audit_*.jsonl files

Additional path exclusion (if needed):
- C:\ICCSFlux-Portable\          (installation directory)
- C:\ICCSFlux-Portable\_runtime\ (PyInstaller runtime extraction)

Requested by:    [Your Name]
Date:            [Date]
Approved by:     [IT Security Manager]
```

---

## Related Documents

| Document | Scope |
|----------|-------|
| [OT Security Standards Reference](OT_Security_Standards_Reference.md) | Why OT systems require tailored security controls vs. enterprise IT policies — cites NIST, IEC, ISA, CISA, and SANS |
| [Standards & Compliance Reference](Standards_and_Compliance.md) | Complete catalogue of all 27 industry standards ICCSFlux implements (IEC 61511, ISA-18.2, 21 CFR Part 11, MQTT 5, etc.) |
| [Safety Certification Roadmap](Safety_Certification_Roadmap.md) | IEC 61508/61511 certification paths, cost estimates, and phased roadmap for formal safety certification |
