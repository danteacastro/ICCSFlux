# NISystem Risk Assessment (NIST SP 800-30)

**System:** NISystem (ICCSFlux) — Industrial Data Acquisition & Control
**Assessment Date:** 2026-03-09
**Assessor:** System Engineering Team
**Review Cycle:** Annually or after significant system changes

---

## 1. System Characterization

### 1.1 System Boundary

NISystem is a distributed industrial data acquisition and control system consisting of:

- **PC Application**: DAQ service (Python), MQTT broker (Mosquitto), dashboard (Vue 3)
- **Edge Controllers**: NI cRIO, Opto22 groov EPIC, NI CompactFieldPoint
- **Network**: Ethernet (plant LAN), USB Ethernet (point-to-point to cRIO)
- **Cloud**: Azure IoT Hub (optional, one-way upload only)

### 1.2 Data Classification

| Data Type | Classification | Location |
|-----------|---------------|----------|
| Process telemetry (temperatures, pressures, flows) | CUI | MQTT, CSV files, TDMS files |
| Safety interlock states | CUI | MQTT, audit trail |
| User credentials | CUI (sensitive) | config/mqtt_credentials.json, data/users/ |
| TLS private keys | CUI (sensitive) | config/tls/*.key |
| Audit trail | CUI | data/audit/*.jsonl |
| Project configuration | CUI | config/projects/*.json |
| PID tuning parameters | CUI | Project JSON, MQTT |
| Script source code | CUI | Project JSON |

### 1.3 Network Topology

```
┌─────────────────────────────────────────────────────────┐
│  Control Network (plant LAN or isolated segment)         │
│                                                          │
│  ┌──────────┐  TCP 1883   ┌───────────┐  TCP 8883 (TLS)│
│  │  DAQ PC   │◄──────────►│ Mosquitto  │◄──────────────►│
│  │           │  WS  9002  │  Broker    │                 │
│  │  Dashboard│◄──────────►│            │  ┌──────────┐   │
│  │  (browser)│            └───────────┘  │  cRIO     │   │
│  └──────────┘                            │  (remote) │   │
│       │                                  └──────────┘   │
│       │ HTTPS (optional)                                 │
│       ▼                                                  │
│  Azure IoT Hub                                           │
└─────────────────────────────────────────────────────────┘
```

---

## 2. Threat Identification

### 2.1 Threat Sources

| ID | Threat Source | Motivation | Capability |
|----|-------------- |-----------|------------|
| TS-1 | Insider (operator) | Curiosity, error, disgruntlement | Authenticated access, physical proximity |
| TS-2 | Insider (administrator) | Error, policy violation | Full system access |
| TS-3 | Network attacker (LAN) | Espionage, sabotage | Network access to control segment |
| TS-4 | Malware on PC | Opportunistic, targeted | Code execution on DAQ PC |
| TS-5 | Physical intruder | Theft, sabotage | Physical access to equipment |
| TS-6 | Environmental | N/A | Power loss, hardware failure, temperature |

### 2.2 Threat Actions and Risk

| ID | Threat Action | Source | Likelihood | Impact | Risk Level |
|----|--------------|--------|-----------|--------|------------|
| T-1 | Unauthorized config change | TS-1 | Medium | High | **HIGH** |
| T-2 | Safety interlock bypass | TS-1, TS-2 | Low | Critical | **HIGH** |
| T-3 | MQTT message injection | TS-3 | Low | High | **MEDIUM** |
| T-4 | Credential theft from disk | TS-4 | Medium | High | **HIGH** |
| T-5 | Credential theft from network | TS-3 | Low | High | **MEDIUM** |
| T-6 | Audit trail tampering | TS-1, TS-4 | Low | High | **MEDIUM** |
| T-7 | Script sandbox escape | TS-1 | Very Low | Critical | **MEDIUM** |
| T-8 | Module hot-unplug during operation | TS-6 | High | Medium | **MEDIUM** |
| T-9 | Power loss during recording | TS-6 | Medium | Medium | **MEDIUM** |
| T-10 | Denial of service (MQTT flood) | TS-3 | Low | Medium | **LOW** |
| T-11 | Data exfiltration via Azure | TS-4 | Low | Medium | **LOW** |
| T-12 | USB device attack | TS-5 | Very Low | High | **LOW** |

---

## 3. Existing Controls

### 3.1 Control Mapping

| Threat | Existing Controls | Residual Risk |
|--------|-------------------|---------------|
| T-1 Unauthorized config | Role-based access (Admin/Operator/Viewer), MQTT ACLs, audit trail | **LOW** — All config changes logged with user attribution |
| T-2 Interlock bypass | Bypass requires Admin role, bypass expiry timer, demand counting, audit trail | **LOW** — Multiple safeguards prevent unauthorized bypass |
| T-3 MQTT injection | TLS on port 8883, authenticated listeners, MQTT ACLs, anomaly detection | **LOW** — Authentication + encryption prevents injection |
| T-4 Credential theft (disk) | NTFS ACLs, bcrypt password hashing, PBKDF2 for MQTT passwords (100k iterations) | **LOW** — File permissions + strong hashing |
| T-5 Credential theft (network) | TLS on all non-localhost connections, WSS on remote dashboard | **LOW** — All network traffic encrypted |
| T-6 Audit tampering | SHA-256 hash chain, append-only JSONL, file permissions, integrity alerting | **LOW** — Tampering is detectable |
| T-7 Script sandbox escape | AST-based validation, blocked imports/builtins/dunders, 98 security tests | **VERY LOW** — Comprehensive sandbox with continuous testing |
| T-8 Hot-unplug | IndexError guards, NaN propagation, COMM_FAIL alarms, graceful degradation | **LOW** — System continues operating with degraded I/O |
| T-9 Power loss recording | OS-level file locking, fsync after flush, buffered writes | **LOW** — At most one buffer of data lost |
| T-10 DoS via MQTT | Rate limiting (TokenBucketRateLimiter), anomaly detection, command flood alerts | **LOW** — Rate limiting prevents overload |
| T-11 Data exfiltration | Azure uploader is one-way (HTTPS out only), isolated venv, no inbound Azure | **LOW** — Data flow is outbound only |
| T-12 USB attack | Not mitigated in software | **MEDIUM** — Organizational policy required |

### 3.2 Control Effectiveness Summary

| Risk Level | Count | Threats |
|-----------|-------|---------|
| **VERY LOW** | 1 | T-7 |
| **LOW** | 9 | T-1, T-2, T-3, T-4, T-5, T-6, T-8, T-9, T-10, T-11 |
| **MEDIUM** | 1 | T-12 |
| **HIGH** | 0 | — |

---

## 4. Risk Determination

### 4.1 Risk Matrix

| | Low Impact | Medium Impact | High Impact | Critical Impact |
|---|-----------|--------------|-------------|----------------|
| **High Likelihood** | LOW | MEDIUM | HIGH | CRITICAL |
| **Medium Likelihood** | LOW | MEDIUM | HIGH | HIGH |
| **Low Likelihood** | VERY LOW | LOW | MEDIUM | MEDIUM |
| **Very Low Likelihood** | VERY LOW | VERY LOW | LOW | MEDIUM |

### 4.2 Risk Treatment Decisions

| Threat | Residual Risk | Decision | Notes |
|--------|--------------|----------|-------|
| T-1 through T-11 | LOW/VERY LOW | **ACCEPT** | Controls reduce risk to acceptable level |
| T-12 USB attack | MEDIUM | **MITIGATE** | Require organizational USB policy + BIOS lockdown |

---

## 5. Recommendations

1. **USB Policy** (T-12): Implement organizational policy restricting USB device connections to authorized devices only. Consider BIOS-level USB port disabling on DAQ PCs.

2. **Full Disk Encryption**: Deploy BitLocker (Windows) on DAQ PCs to protect CUI at rest beyond file-level ACLs.

3. **Network Segmentation**: Ensure the control network is isolated from the corporate network. Use a firewall or VLAN to restrict traffic.

4. **Incident Response Plan**: Develop and test an incident response plan specific to industrial control system security events.

5. **Security Training**: Provide annual security awareness training to all operators and administrators.

---

## 6. Review Schedule

| Activity | Frequency |
|----------|-----------|
| Risk assessment review | Annually |
| Dependency vulnerability scan | Weekly (automated) |
| Penetration test | Annually or after major changes |
| Security training | Annually |
| Incident response drill | Semi-annually |

---

*This document satisfies NIST 800-171 RA.L2-3.11.1 (Risk Assessment), RA.L2-3.11.2 (Vulnerability Scanning), and RA.L2-3.11.3 (Vulnerability Remediation).*
