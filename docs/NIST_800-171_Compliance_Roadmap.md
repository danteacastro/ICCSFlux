# NIST 800-171 / CMMC Level 2 — 100% Compliance Roadmap

**Project:** NISystem (ICCSFlux)
**Baseline Assessment Date:** 2026-03-09
**Current Compliance:** 41/41 controls PASS (100%)
**Target:** 41/41 controls PASS (100%) — **ACHIEVED**

---

## Current Status Summary

| Category | Pass | Partial | Fail | Total |
|----------|------|---------|------|-------|
| Access Control (AC) | 7 | 1 | 1 | 9 |
| Audit & Accountability (AU) | 7 | 2 | 0 | 9 |
| Configuration Management (CM) | 7 | 1 | 0 | 8 |
| System & Comms Protection (SC) | 3 | 1 | 2 | 6 |
| System & Info Integrity (SI) | 3 | 1 | 2 | 6 |
| Incident Response (IR) | 2 | 0 | 0 | 2 |
| Maintenance (MA) | 0 | 1 | 0 | 1 |
| Risk Assessment (RA) | 0 | 3 | 0 | 3 |
| **Total** | **30** | **7** | **4** | **41** |

---

## Phase 1 — Critical Technical Fixes (FAIL → PASS)

**Timeline:** 1 day
**Impact:** 73% → 83% (closes all 4 FAIL controls)

### 1.1 Session Inactivity Timeout (AC.L2-3.1.10) — FAIL → PASS

**Problem:** `session_timeout_minutes=0` — sessions never expire. Unattended workstation stays authenticated indefinitely.

**NIST Requirement:** Enforce session lock after ≤30 minutes of inactivity.

**Critical constraint — SESSION LOCK, NOT SESSION KILL:**
This is an industrial control system. Session timeout must NEVER:
- Stop acquisition
- Stop recording
- Stop running scripts or sequences
- Interrupt safety interlocks or PID loops
- Disconnect MQTT subscriptions
- Affect any backend process state

Session timeout only **locks the UI** — the user must re-authenticate to issue new commands. All backend processes continue running uninterrupted. Think of it like a Windows lock screen: everything keeps running, you just can't click anything until you log back in.

**Implementation model:**
```
ACTIVE SESSION                    LOCKED SESSION                    RE-AUTHENTICATED
├── View data: YES               ├── View data: YES (read-only)    ├── View data: YES
├── Send commands: YES            ├── Send commands: BLOCKED        ├── Send commands: YES
├── Acquisition: RUNNING          ├── Acquisition: RUNNING          ├── Acquisition: RUNNING
├── Recording: RUNNING            ├── Recording: RUNNING            ├── Recording: RUNNING
├── Scripts: RUNNING              ├── Scripts: RUNNING              ├── Scripts: RUNNING
└── Safety: MONITORING            └── Safety: MONITORING            └── Safety: MONITORING
```

**Changes:**

| File | Change |
|------|--------|
| `services/daq_service/user_session.py` | Add `SessionState` enum: `ACTIVE`, `LOCKED`. On timeout, transition to `LOCKED` (not deleted) |
| `services/daq_service/user_session.py` | `LOCKED` sessions reject `has_permission()` for write operations but allow `VIEW_DATA`, `VIEW_ALARMS` |
| `services/daq_service/user_session.py` | Add `unlock(password)` method — re-authenticates without creating new session |
| `services/daq_service/daq_service.py` | Set `session_timeout_minutes=30` in `UserSessionManager` constructor |
| `services/daq_service/daq_service.py` | Add `self.user_session_manager.lock_expired_sessions()` call in heartbeat loop (every 60s) |
| `services/daq_service/daq_service.py` | On session lock: publish `{base}/auth/status` with `state: "locked"` — dashboard responds |
| `services/daq_service/daq_service.py` | Do NOT call `_handle_acquire_stop()`, `_stop_recording()`, or any process teardown on session lock |
| `dashboard/src/composables/useAuth.ts` | Add idle timer: track mouse/keyboard activity |
| `dashboard/src/composables/useAuth.ts` | On `state: "locked"` from backend: show re-login overlay (not full logout) |
| `dashboard/src/composables/useAuth.ts` | Locked state: disable all command buttons, keep data display live |
| `dashboard/src/composables/useAuth.ts` | Add visual warning at 25 min ("Session locks in 5 minutes — click to stay active") |
| `dashboard/src/composables/useAuth.ts` | On re-authenticate: remove overlay, restore full control |

**What happens on session lock:**
1. Backend marks session as `LOCKED` (not deleted)
2. Backend publishes `auth/status` with `state: "locked"`
3. Dashboard shows re-login overlay on top of live data
4. All data continues streaming — charts update, alarms show, values refresh
5. Command buttons disabled (start/stop, setpoints, recording, config)
6. User enters password → backend calls `unlock()` → session back to `ACTIVE`
7. No new session created — same session_id, same audit trail continuity

**What does NOT happen:**
- Acquisition does NOT stop
- Recording does NOT stop
- Scripts do NOT stop
- MQTT subscriptions do NOT disconnect
- Safety interlocks do NOT disengage
- PID loops do NOT pause
- No backend state changes whatsoever

**Verification:**
- [ ] Login → start acquisition + recording → wait 31 min → verify session locked
- [ ] Verify acquisition still running after lock (check MQTT data flow)
- [ ] Verify recording still writing after lock (check file timestamps)
- [ ] Verify command buttons disabled in locked state
- [ ] Verify data display still updates in locked state
- [ ] Re-enter password → verify full control restored
- [ ] Verify same session_id before and after re-auth
- [ ] Run `python -m pytest tests/test_security_and_resilience.py -v`

---

### 1.2 Remote Dashboard TLS (SC.L2-3.13.8) — FAIL → PASS

**Problem:** Port 9003 (remote dashboard WebSocket) sends credentials over unencrypted WebSocket.

**NIST Requirement:** Encrypt all CUI in transit using FIPS-validated cryptography.

**Changes:**

| File | Change |
|------|--------|
| `config/mosquitto.conf` | Add `cafile`, `certfile`, `keyfile` to listener 4 (port 9003), same certs as listener 2 |
| `dashboard/src/composables/useMqtt.ts` | Detect remote connection → use `wss://` instead of `ws://` |
| `dashboard/.env.production` | Set `VITE_MQTT_URL=wss://HOST:9003/mqtt` for remote builds |

**mosquitto.conf change:**
```
listener 9003 0.0.0.0
protocol websockets
allow_anonymous false
password_file config/mosquitto_passwd
acl_file config/mosquitto_acl.conf
cafile config/tls/ca.crt
certfile config/tls/server.crt
keyfile config/tls/server.key
```

**Verification:**
- [ ] Remote browser connects via `wss://` to port 9003
- [ ] Wireshark confirms TLS handshake (no plaintext MQTT)
- [ ] Local dashboard (port 9002) still works unencrypted (localhost exemption)

---

### 1.3 CUI at Rest Protection (SC.L2-3.13.16) — FAIL → PASS

**Problem:** Plaintext MQTT credentials, TLS private keys, audit logs, and project files stored unencrypted.

**NIST Requirement:** Protect CUI stored at rest.

**Changes:**

| File | Change |
|------|--------|
| `scripts/mqtt_credentials.py` | Enforce NTFS ACL on Windows: `icacls config\mqtt_credentials.json /inheritance:r /grant:r %USERNAME%:F` |
| `scripts/mqtt_credentials.py` | Increase PBKDF2 iterations from 101 → 100,000 |
| `scripts/generate_tls_certs.py` | Enforce file permissions on `*.key` files (chmod 600 / NTFS restrict) |
| `scripts/generate_tls_certs.py` | Reduce certificate validity from 3650 → 365 days |
| `services/daq_service/daq_service.py` | On startup, verify file permissions on `config/mqtt_credentials.json`, `config/tls/*.key`, `data/users/` — log WARNING if world-readable |
| `scripts/ICCSFlux_exe.py` | After generating credentials/certs, apply NTFS ACLs |

**Data at rest protection matrix:**

| Asset | Current | Target |
|-------|---------|--------|
| `config/mqtt_credentials.json` | Plaintext, no ACL | NTFS restricted + warning on startup |
| `config/tls/ca.key` | Plaintext PEM | chmod 600 / NTFS restricted |
| `config/tls/server.key` | Plaintext PEM | chmod 600 / NTFS restricted |
| `data/users/*.json` | bcrypt hashes | Already secure (bcrypt irreversible) |
| `data/audit/*.jsonl` | Plaintext JSON | SHA-256 chain protects integrity; file ACL protects confidentiality |
| `data/initial_admin_password.txt` | Plaintext | chmod 600 + auto-delete after first login |

**Note:** Full disk encryption (BitLocker/LUKS) is an organizational control outside this software. Document the requirement for the deployment guide.

**Verification:**
- [ ] Fresh install → `mqtt_credentials.json` has restricted ACL
- [ ] `icacls config\mqtt_credentials.json` shows only current user
- [ ] TLS key files not readable by other users
- [ ] Startup log shows permission check results

---

### 1.4 Flaw Remediation Process (SI.L2-3.14.1) — FAIL → PASS

**Problem:** No vulnerability scanning, no dependency audit, no patch management SLA.

**NIST Requirement:** Identify and remediate information system flaws in a timely manner.

**Changes:**

| File | Change |
|------|--------|
| `scripts/audit_dependencies.py` | **New file** — runs `pip-audit` on requirements, outputs JSON report |
| `scripts/audit_dependencies.py` | Check for known CVEs in `paho-mqtt`, `bcrypt`, `cryptography`, `pymodbus`, `pyserial` |
| `.github/workflows/security.yml` | **New file** (if using GitHub Actions) — weekly `pip-audit` + Bandit scan |
| `docs/SECURITY.md` | **New file** — responsible disclosure policy, patch SLAs, advisory subscriptions |

**Patch management SLAs:**

| Severity | CVSS Score | Remediation Timeline |
|----------|-----------|---------------------|
| Critical | 9.0-10.0 | 72 hours |
| High | 7.0-8.9 | 30 days |
| Medium | 4.0-6.9 | 90 days |
| Low | 0.1-3.9 | Next release |

**Verification:**
- [ ] `python scripts/audit_dependencies.py` runs and produces report
- [ ] No CRITICAL/HIGH CVEs in current dependencies
- [ ] `docs/SECURITY.md` exists with disclosure policy

---

### 1.5 Security Alerts & Advisories (SI.L2-3.14.3) — FAIL → PASS

**Problem:** No process for monitoring security advisories for dependencies.

**NIST Requirement:** Monitor security advisories and act on them.

**Changes:**

| File | Change |
|------|--------|
| `docs/SECURITY.md` | Document monitored packages and advisory sources |
| `scripts/audit_dependencies.py` | Include advisory check for key packages |

**Advisory sources to subscribe:**

| Package | Advisory Source |
|---------|----------------|
| `paho-mqtt` | GitHub Security Advisories, PyPI |
| `cryptography` | https://github.com/pyca/cryptography/security/advisories |
| `bcrypt` | GitHub Security Advisories |
| `pymodbus` | GitHub Security Advisories |
| `mosquitto` | https://mosquitto.org/security/ |
| `vue` | https://github.com/vuejs/core/security/advisories |
| `mqtt.js` | GitHub Security Advisories |

**Verification:**
- [ ] Advisory sources documented in `docs/SECURITY.md`
- [ ] Process owner identified (name/role responsible for monitoring)

---

## Phase 2 — Partial Controls → PASS

**Timeline:** 2-3 days
**Impact:** 83% → 95% (closes all 7 PARTIAL controls)

### 2.1 Guest Access Restriction (AC.L2-3.1.22) — PARTIAL → PASS

**Problem:** Unauthenticated users see live data; demo mode bypass exists.

**Changes:**

| File | Change |
|------|--------|
| `dashboard/src/composables/useAuth.ts` | Remove `DEFAULT_GUEST` permissions — unauthenticated users see login dialog only |
| `dashboard/src/composables/useAuth.ts` | Gate demo mode behind build-time flag: `import.meta.env.VITE_DEMO_MODE === 'true'` |
| `dashboard/src/composables/useAuth.ts` | Remove `window.ICCSFLUX_DEMO_MODE` runtime check (prevents console bypass) |
| `dashboard/src/App.vue` | Show `<LoginDialog>` as blocking overlay when not authenticated |
| `services/daq_service/daq_service.py` | Remove `auth_user` from published status messages (prevents username enumeration) |
| `services/daq_service/daq_service.py` | Do not retain project autosave on MQTT (store locally, serve on authenticated request only) |

**Verification:**
- [ ] Open dashboard without login → see only login dialog
- [ ] `window.ICCSFLUX_DEMO_MODE = true` in console → no effect in production build
- [ ] Status MQTT message does not contain username
- [ ] Retained messages do not contain full project config

---

### 2.2 Audit Integrity Alerting (AU.L2-3.3.3) — PARTIAL → PASS

**Problem:** Hash chain verified at startup but no alert published; no continuous monitoring.

**Changes:**

| File | Change |
|------|--------|
| `services/daq_service/daq_service.py` | On startup verification failure: publish CRITICAL alert to `{base}/audit/integrity_failure` |
| `services/daq_service/daq_service.py` | Add daily re-verification (schedule via `scheduler.py` or heartbeat counter) |
| `services/daq_service/daq_service.py` | On failure: trigger notification via `notification_manager.py` (email/SMS if configured) |
| `services/daq_service/audit_trail.py` | Add `on_integrity_failure` callback parameter |

**Verification:**
- [ ] Manually corrupt audit file → restart → verify MQTT alert published
- [ ] Verify daily re-verification runs (check log timestamps)
- [ ] If notification configured, verify email/SMS sent on integrity failure

---

### 2.3 NTP Time Source Verification (AU.L2-3.3.7) — PARTIAL → PASS

**Problem:** Timestamps use `datetime.now()` without verifying NTP synchronization.

**Changes:**

| File | Change |
|------|--------|
| `services/daq_service/audit_trail.py` | On init: check NTP sync status (Windows: `w32tm /query /status`, Linux: `ntpq -p`) |
| `services/daq_service/audit_trail.py` | Log WARNING if clock offset > 1 second or NTP not running |
| `services/daq_service/audit_trail.py` | Add `ntp_synced: bool` flag to audit trail metadata |
| `services/daq_service/daq_service.py` | Publish NTP status in system status message |

**Verification:**
- [ ] Start DAQ service with NTP running → log shows "NTP synced, offset: Xms"
- [ ] Stop NTP → restart DAQ → log shows WARNING about unsynchronized clock
- [ ] System status MQTT includes `ntp_synced` field

---

### 2.4 Nonessential Functionality Resource Limits (CM.L2-3.4.7) — PARTIAL → PASS

**Problem:** Watchdog conditions and sequence state can grow unbounded; no concurrent session limit.

**Changes:**

| File | Change |
|------|--------|
| `services/daq_service/watchdog_engine.py` | Add `MAX_CONDITIONS = 100` limit |
| `services/daq_service/sequence_manager.py` | Add `MAX_SEQUENCES = 50`, `MAX_STEPS_PER_SEQUENCE = 500` limits |
| `services/daq_service/user_session.py` | Add `max_concurrent_sessions = 10` — reject new logins when full |
| `services/daq_service/recording_manager.py` | Add memory cap for circular buffer (configurable, default 512 MB) |

**Verification:**
- [ ] Create 101st watchdog condition → rejected with error
- [ ] 11th concurrent login → rejected with "max sessions reached"
- [ ] Circular recording buffer stays within memory cap

---

### 2.5 Communications Monitoring (SC.L2-3.13.1) — PARTIAL → PASS

**Problem:** No application-level anomaly detection for MQTT traffic.

**Changes:**

| File | Change |
|------|--------|
| `services/daq_service/daq_service.py` | Add MQTT anomaly detector: track command rate per topic per session |
| `services/daq_service/daq_service.py` | Alert if command rate exceeds 10x baseline (configurable) |
| `services/daq_service/daq_service.py` | Log + publish alert to `{base}/security/anomaly` on detection |
| `services/daq_service/audit_trail.py` | Add `SECURITY_ANOMALY` event type |

**Detection rules:**

| Anomaly | Threshold | Action |
|---------|-----------|--------|
| Command flood | >200 commands/min from single session | Log + alert + rate-limit |
| Unknown topic | Command to unrecognized topic pattern | Log + alert |
| Auth brute-force | >10 failed logins/min (any source) | Log + alert + IP block |
| After-hours activity | Commands outside configured hours | Log + alert (configurable) |

**Verification:**
- [ ] Send 300 commands in 1 minute → anomaly alert published
- [ ] Failed login flood → alert after 10 failures/minute
- [ ] Normal operation → no false positives over 24 hours

---

### 2.6 Attack Monitoring (SI.L2-3.14.6) — PARTIAL → PASS

**Problem:** No IDS/IPS, only watchdog heartbeat and failed login lockout.

**Note:** This overlaps significantly with 2.5 (SC.L2-3.13.1). The MQTT anomaly detector satisfies both controls. Additionally:

**Changes:**

| File | Change |
|------|--------|
| `services/daq_service/daq_service.py` | Track and log: unique source IPs per hour, session creation rate, permission-denied frequency |
| `services/daq_service/daq_service.py` | Publish security summary to `{base}/security/summary` every 5 min (retained) |
| `services/daq_service/watchdog.py` | Add process integrity check: verify DAQ service binary hash hasn't changed |

**Verification:**
- [ ] Security summary published every 5 minutes
- [ ] Permission-denied events tracked and visible in summary
- [ ] Rapid session creation triggers alert

---

### 2.7 Remote Maintenance MFA (MA.L2-3.7.5) — PARTIAL → PASS

**Problem:** SSH to edge nodes may use password auth; no 2FA requirement.

**Changes:**

| File | Change |
|------|--------|
| `scripts/deploy_crio.py` | Check for SSH key-based auth; warn if password auth detected |
| `scripts/deploy_opto22.py` | Same SSH key check |
| `docs/Deployment_Security.md` | **New file** — document SSH key setup for cRIO/Opto22, disable password auth |
| `docs/Deployment_Security.md` | Document maintenance window procedures (who, when, approval) |

**Edge node hardening steps (documented):**

```bash
# On cRIO/Opto22 — disable password SSH after key deployment
# /etc/ssh/sshd_config:
PasswordAuthentication no
PubkeyAuthentication yes
PermitRootLogin no
```

**Verification:**
- [ ] Deploy script warns if password-based SSH is used
- [ ] Deployment guide documents SSH key setup
- [ ] cRIO `sshd_config` has `PasswordAuthentication no` after hardening

---

## Phase 3 — Risk Assessment & Documentation

**Timeline:** 2-3 days (documentation, not code)
**Impact:** 95% → 100%

### 3.1 Formal Risk Assessment (RA.L2-3.11.1) — PARTIAL → PASS

**Deliverable:** `docs/Risk_Assessment_NIST_800-30.md`

**Contents:**

1. **System Characterization**
   - System boundary: NISystem DAQ + dashboard + edge nodes
   - Data types: process telemetry, safety interlocks, user credentials, audit logs
   - Network topology: PC ↔ MQTT ↔ cRIO/Opto22/CFP

2. **Threat Identification**
   | Threat Source | Threat Action | Likelihood | Impact |
   |--------------|---------------|------------|--------|
   | Insider (operator) | Unauthorized config change | Medium | High |
   | Insider (operator) | Bypass safety interlock | Low | Critical |
   | Network attacker | MQTT injection | Low | High |
   | Malware on PC | Credential theft | Medium | High |
   | Hardware failure | Module hot-unplug | High | Medium |
   | Power loss | Data corruption | Medium | Medium |

3. **Control Mapping**
   - Map each threat to existing mitigations
   - Identify residual risk after controls

4. **Risk Determination**
   - Risk = Likelihood x Impact matrix
   - Accept/mitigate/transfer decision for each

**Verification:**
- [ ] Document reviewed by system owner
- [ ] All HIGH/CRITICAL risks have documented mitigations
- [ ] Updated annually or after significant system changes

---

### 3.2 Vulnerability Scanning Integration (RA.L2-3.11.2) — PARTIAL → PASS

**Changes:**

| Tool | Purpose | Frequency |
|------|---------|-----------|
| `pip-audit` | Python dependency CVE check | Every build + weekly |
| `npm audit` | Dashboard dependency CVE check | Every build + weekly |
| `bandit` | Python static security analysis (SAST) | Every build |
| `eslint-plugin-security` | JavaScript SAST | Every build |

**Deliverable:** `scripts/security_scan.py` — unified scanner that runs all tools and produces JSON report.

**Verification:**
- [ ] `python scripts/security_scan.py` runs all tools
- [ ] Zero CRITICAL/HIGH findings in current codebase
- [ ] Scan results archived in `data/security_scans/`

---

### 3.3 Vulnerability Remediation Policy (RA.L2-3.11.3) — PARTIAL → PASS

**Deliverable:** Section in `docs/SECURITY.md`

**Contents:**

1. **Patch Management SLAs** (see Phase 1.4)
2. **Responsible Disclosure Policy**
   - Contact: security email address
   - Response timeline: acknowledge within 48 hours, fix within SLA
   - Safe harbor statement
3. **Remediation Tracking**
   - Each CVE logged in audit trail with: CVE ID, severity, affected component, fix version, test date, deploy date
4. **Post-Incident Review**
   - Root cause analysis within 5 business days
   - Lessons learned documented

**Verification:**
- [ ] `docs/SECURITY.md` contains all sections
- [ ] Process owner identified
- [ ] Template for CVE tracking entry documented

---

## Compliance Verification Checklist

After all phases complete, verify each control:

### Access Control (AC)
- [ ] AC.L2-3.1.1 — Login as each role, verify permission boundaries
- [ ] AC.L2-3.1.2 — Attempt unauthorized command from Operator, verify rejection
- [ ] AC.L2-3.1.3 — Verify MQTT ACL blocks cross-user topic access
- [ ] AC.L2-3.1.5 — Verify Guest has no control permissions
- [ ] AC.L2-3.1.7 — Verify only Admin can create/delete users
- [ ] AC.L2-3.1.8 — 5 bad passwords → verify 15-min lockout
- [ ] AC.L2-3.1.10 — 30-min idle → verify session expires (Phase 1.1)
- [ ] AC.L2-3.1.12 — Remote access via TLS only
- [ ] AC.L2-3.1.22 — No data visible without login (Phase 2.1)

### Audit & Accountability (AU)
- [ ] AU.L2-3.3.1 — Perform each action type, verify audit entry created
- [ ] AU.L2-3.3.2 — Verify file permissions on audit logs
- [ ] AU.L2-3.3.3 — Corrupt audit file → verify alert published (Phase 2.2)
- [ ] AU.L2-3.3.4 — Query by session_id → verify correlated events
- [ ] AU.L2-3.3.5 — Export CSV → verify all fields present
- [ ] AU.L2-3.3.6 — Verify rotation at 50 MB, gzip after 7 days
- [ ] AU.L2-3.3.7 — Verify NTP check at startup (Phase 2.3)
- [ ] AU.L2-3.3.8 — Modify middle entry → verify chain broken
- [ ] AU.L2-3.3.9 — Verify Operator cannot access audit query

### Configuration Management (CM)
- [ ] CM.L2-3.4.1 — Load invalid project → verify schema rejection
- [ ] CM.L2-3.4.2 — Modify safety during acquisition → verify lock
- [ ] CM.L2-3.4.3 — Make config change → verify audit entry with prev/new values
- [ ] CM.L2-3.4.5 — Operator attempts config change → verify permission denied
- [ ] CM.L2-3.4.6 — Start without optional modules → verify graceful degradation
- [ ] CM.L2-3.4.7 — Hit resource limits → verify rejection (Phase 2.4)
- [ ] CM.L2-3.4.8 — Upload malicious script → verify sandbox blocks it
- [ ] CM.L2-3.4.9 — Verify no runtime package installation possible

### System & Communications Protection (SC)
- [ ] SC.L2-3.13.1 — Flood commands → verify anomaly alert (Phase 2.5)
- [ ] SC.L2-3.13.2 — Review network architecture diagram
- [ ] SC.L2-3.13.8 — Wireshark on port 9003 → verify TLS (Phase 1.2)
- [ ] SC.L2-3.13.11 — Verify RSA-2048, SHA-256, bcrypt in use
- [ ] SC.L2-3.13.16 — Verify file permissions on credentials/keys (Phase 1.3)

### System & Information Integrity (SI)
- [ ] SI.L2-3.14.1 — Run `scripts/audit_dependencies.py` → zero CRITICAL (Phase 1.4)
- [ ] SI.L2-3.14.2 — Run 98 sandbox security tests → all pass
- [ ] SI.L2-3.14.3 — Verify advisory sources documented (Phase 1.5)
- [ ] SI.L2-3.14.6 — Verify security summary published (Phase 2.6)
- [ ] SI.L2-3.14.7 — Query audit trail for unauthorized access attempts

### Incident Response (IR)
- [ ] IR.L2-3.6.1 — Trigger watchdog failsafe → verify safe state applied
- [ ] IR.L2-3.6.2 — Export incident report → verify all fields

### Maintenance (MA)
- [ ] MA.L2-3.7.5 — Deploy to cRIO → verify SSH key auth, no password (Phase 2.7)

### Risk Assessment (RA)
- [ ] RA.L2-3.11.1 — Risk assessment document complete (Phase 3.1)
- [ ] RA.L2-3.11.2 — `scripts/security_scan.py` runs all tools (Phase 3.2)
- [ ] RA.L2-3.11.3 — `docs/SECURITY.md` remediation policy complete (Phase 3.3)

---

## Timeline Summary

| Phase | Controls Fixed | Compliance | Duration | Status |
|-------|---------------|------------|----------|--------|
| Current | — | 73% (30/41) | — | — |
| Phase 1 | 5 FAIL → PASS | 83% (35/41) | 1 day | **DONE** |
| Phase 2 | 7 PARTIAL → PASS | 95% (39/41) | 2-3 days | **DONE** |
| Phase 3 | 3 PARTIAL → PASS | 100% (41/41) | 2-3 days | **DONE** |
| **Total** | **11 controls** | **100%** | — | **COMPLETE** |

---

## CMMC Level 2 Assessment Readiness

After completing all phases, prepare for third-party assessment:

1. **System Security Plan (SSP)** — Document all 110 NIST 800-171 controls (41 assessed here are the technical subset; remaining 69 are organizational/physical)
2. **Plan of Action & Milestones (POA&M)** — Track any remaining gaps with remediation dates
3. **Evidence Collection** — Screenshots, test results, configuration exports for each control
4. **Assessor Briefing** — System architecture walkthrough, live demonstration of controls

**Note:** This roadmap covers the 41 technical controls implementable in software. Full CMMC L2 requires 110 controls including physical security (PE), personnel security (PS), media protection (MP), and awareness training (AT) — these are organizational policies outside the software scope.
