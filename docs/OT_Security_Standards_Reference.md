# OT Security Standards Reference

**System:** ICCSFlux Industrial Data Acquisition Platform
**Date:** February 2026
**Purpose:** Standards-based justification for OT-appropriate security controls
**Companion to:** [IT Security & Compliance Guide](IT_Security_and_Compliance_Guide.md)
**See also:** [Standards & Compliance Reference](Standards_and_Compliance.md) | [Safety Certification Roadmap](Safety_Certification_Roadmap.md)

---

## Why This Document Exists

Enterprise IT security policies are designed for office workstations, SaaS applications, and general-purpose servers. Applying these policies unchanged to Operational Technology (OT) systems — which control physical processes, read industrial sensors, and enforce safety interlocks — can **reduce safety and reliability** rather than improve security.

This document cites authoritative standards from NIST, IEC, ISA, CISA, SANS, and FDA to demonstrate that OT systems require tailored security controls. These are not opinions — they are the same frameworks that IT security teams use to justify their own policies.

---

## Table of Contents

1. [The Foundational Principle: OT Is Not IT](#1-the-foundational-principle-ot-is-not-it)
2. [Endpoint Protection (EDR/Antivirus)](#2-endpoint-protection-edrantivirus)
3. [Patching and Windows Updates](#3-patching-and-windows-updates)
4. [Executable Whitelisting and PyInstaller](#4-executable-whitelisting-and-pyinstaller)
5. [Network Segmentation](#5-network-segmentation)
6. [Password Rotation for Service Accounts](#6-password-rotation-for-service-accounts)
7. [Data Egress and Internet Connectivity](#7-data-egress-and-internet-connectivity)
8. [The CrowdStrike Precedent](#8-the-crowdstrike-precedent)
9. [Applicable Security Levels](#9-applicable-security-levels)
10. [SOC 2 Applicability](#10-soc-2-applicability)
11. [Standards Reference Table](#11-standards-reference-table)
12. [Recommended IT/OT Security Agreement](#12-recommended-itot-security-agreement)

---

## 1. The Foundational Principle: OT Is Not IT

### The Priority Inversion

The most important concept in OT security is that the priority order is **inverted** compared to IT:

| Priority | IT Systems | OT Systems |
|----------|-----------|------------|
| **Highest** | Confidentiality | **Safety** |
| | Integrity | **Availability** |
| | Availability | Integrity |
| **Lowest** | Safety (N/A) | Confidentiality |

A security control that improves confidentiality but risks availability or safety is a **net negative** for OT.

### What the Standards Say

**NIST SP 800-82 Rev. 3** (Section 2, Table 1 — "Summary of Typical Differences Between IT and OT"):

> OT systems "required different precautions and needed to be tailored to meet requirements prioritized by safety, availability, integrity, and confidentiality" rather than the traditional IT CIA triad order.

The document explicitly lists characteristics where IT and OT diverge:

| Characteristic | IT | OT |
|---------------|-----|-----|
| **Performance** | Non-real-time, throughput tolerant | Real-time, delay is unacceptable |
| **Availability** | Reboots acceptable | 24/7 uptime required, reboots may not be possible |
| **Risk management** | Data confidentiality paramount | Human safety and process integrity paramount |
| **Updates/Patches** | Applied promptly | Must be thoroughly tested; may require vendor validation |
| **Anti-malware** | Common, readily deployed | May compromise real-time performance; difficult to deploy |
| **Incident response** | Stop and investigate | Cannot stop process; must maintain operations |

**Source:** [NIST SP 800-82 Rev. 3, Section 2, pp. 25-27](https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-82r3.pdf)

**CISA — Principles of OT Cyber Security (2024):**

CISA, the UK NCSC, the FBI, and five international partner agencies jointly published guidance recognizing that OT environments require fundamentally different security approaches than IT environments, with emphasis on availability and physical safety.

**Source:** [CISA — Principles of OT Cyber Security](https://www.cisa.gov/resources-tools/resources/principles-operational-technology-cyber-security)

---

## 2. Endpoint Protection (EDR/Antivirus)

### The Problem

Traditional EDR/antivirus on an OT data acquisition machine can:
- Cause **CPU spikes during real-time scanning** that disrupt 10 Hz sensor acquisition loops
- **Quarantine legitimate executables** (especially PyInstaller-packed binaries — see Section 4)
- **Lock data files** mid-write, corrupting CSV/TDMS recordings
- **Intercept network traffic** on localhost MQTT ports, adding latency to safety-critical interlock evaluation

### What the Standards Say

**NIST SP 800-82 Rev. 3:**

> Traditional antivirus "may compromise real-time performance" and is "difficult to deploy" in OT environments. Security measures "must be implemented while considering the operational, safety, and availability constraints inherent to OT environments."

**SANS — ICS Five Critical Controls:**

SANS explicitly states that traditional antivirus is inappropriate for many OT systems:

> "Unlike IT environments, OT systems are often unable to rely on traditional antivirus solutions, which fail to address the distinct needs of industrial operations."

SANS identifies specific failure modes:
- OT environments prioritize stability and uptime, often running systems that "cannot accommodate regular updates or resource-intensive antivirus programs"
- "Antivirus scans can disrupt the real-time performance OT systems demand, introducing risks to critical operations"
- Antivirus focuses on detecting known threats after they emerge, "leaving OT environments vulnerable to zero-day exploits"

**SANS recommends application allowlisting** (whitelisting) as the preferred OT endpoint protection:

> "Allowlisting is a proactive cybersecurity strategy that blocks unauthorized programs from running by allowing only pre-approved applications to execute."

**Source:** [SANS — The Five ICS Cybersecurity Critical Controls](https://www.sans.org/white-papers/five-ics-cybersecurity-critical-controls)

**CISA — Guidelines for Application Whitelisting in Industrial Control Systems:**

CISA published dedicated guidance recommending application whitelisting over antivirus for ICS environments.

**Source:** [CISA Application Whitelisting Guidelines (PDF)](https://www.cisa.gov/sites/default/files/documents/Guidelines%20for%20Application%20Whitelisting%20in%20Industrial%20Control%20Systems_S508C.pdf)

### What We Recommend

We are **not asking to disable EDR**. We are asking for:
1. **Path exclusions** for the application directory (`ICCSFlux-Portable/`), data directories (`data/`, `logs/`), and MQTT broker
2. **Process exclusions** for `ICCSFlux.exe`, `DAQService.exe`, `mosquitto.exe`
3. **Behavioral exclusions** for legitimate operations (localhost network traffic, file I/O to data directories)

These are documented best practices per [SentinelOne's own exclusion guidance](https://www.cybervigilance.uk/insights/sentinelone-path-exclusion) and align with NIST SP 800-82's recommendation to balance security with operational requirements.

See [IT Security & Compliance Guide, Part IV](IT_Security_and_Compliance_Guide.md) for the specific exclusion request template.

---

## 3. Patching and Windows Updates

### The Problem

Automatic Windows Updates on an OT machine can:
- **Reboot the system during active data acquisition**, losing in-progress recordings
- **Break NI-DAQmx drivers** that depend on specific Windows kernel versions
- **Trip safety interlocks** by suddenly halting the process without executing safe-state procedures
- **Corrupt audit trails** that require clean shutdown for hash-chain integrity

### What the Standards Say

**NIST SP 800-82 Rev. 3:**

> OT patches must be "thoroughly tested" before deployment. "Prompt software and firmware patching" is recommended, but with "sandbox testing of software updates in order to understand how a patch might impact production." The document emphasizes "ensuring business continuity through any risk management activities, including system-level updates and patching in order to avoid costly device and process shutdowns."

**Source:** [NIST SP 800-82 Rev. 3](https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-82r3.pdf)

**IEC 62443-2-3 — Patch Management in IACS Environments:**

This standard is specifically about patching industrial systems. Key requirements:

> "Patches represent changes that can affect the safety, reliability, certification and performance of IACS. Each patch must be thoroughly tested to ensure it does not inadvertently disrupt system operations."

IEC 62443-2-3 requires:
- A **formal testing process** with test plan, test cases, and documentation
- **Sandbox/staging validation** before production deployment
- **Vendor compatibility testing** (NI publishes DAQmx driver compatibility matrices)
- Risk assessment of each patch against operational impact

The 2024 update strengthened these requirements further, emphasizing "testing patches in sandbox environments, validation processes before deployment, and timelines for patch deployment."

**Source:** [IEC TR 62443-2-3:2015](https://webstore.iec.ch/en/publication/22811) | [ISA analysis of IEC 62443-2-3](https://gca.isa.org/blog/importance-and-challenges-of-ot-patching-in-line-with-isa/iec-62443-2-3)

### What We Recommend

- **WSUS with manual approval**, not automatic updates
- Patches applied during **scheduled maintenance windows** when acquisition is stopped
- **Test on a non-production machine** before deploying to the DAQ workstation
- NI-DAQmx driver updates validated against [NI's compatibility documentation](https://www.ni.com/en/support.html) before deployment
- Windows feature updates (major versions) deferred until validated by NI

---

## 4. Executable Whitelisting and PyInstaller

### The Problem

ICCSFlux is compiled using PyInstaller, which packs Python bytecode into Windows executables. EDR/antivirus products frequently flag these executables as suspicious because:

1. **PyInstaller's packing method resembles malware packing** — the bootloader extracts and executes embedded code, a pattern also used by malicious packers
2. **Malware authors also use PyInstaller** — this has trained ML-based detection models to flag the packing signature
3. **Executable hashes change every build** — timestamps and build paths are embedded, so hash-based whitelisting breaks on every release

This is a **well-documented, industry-wide known issue**, not a security concern specific to ICCSFlux.

### Evidence This Is a Known False-Positive Problem

- [PyInstaller Issue #6754](https://github.com/pyinstaller/pyinstaller/issues/6754) — "My --onefile exe is getting anti-Virus False positive flags"
- [PyInstaller Issue #4694](https://github.com/pyinstaller/pyinstaller/issues/4694) — "AV detecting it as malicious file"
- [PyInstaller Issue #2988](https://github.com/pyinstaller/pyinstaller/issues/2988) — "False-Positive"
- [Code4Lib Journal](https://journal.code4lib.org/articles/18136) — "The Dangers of Building Your Own Python Applications: False-Positives, Unknown Publishers, and Code Licensing"
- [Python.org Discussion](https://discuss.python.org/t/pyinstaller-false-positive/43171) — Community thread on persistent false-positive problem

The root cause, per PyInstaller maintainers:

> "Antivirus software cannot efficiently process Python bytecode, which are the .pyc files included in PyInstaller."

### The Correct IT Control

**Hash-based whitelisting does not work** for PyInstaller executables (hashes change every build). The correct controls are:

1. **Code signing (Authenticode)** — signs the binary with a trusted certificate. Our build pipeline supports this (see [IT Security Guide, Section 3](IT_Security_and_Compliance_Guide.md)).
2. **Application allowlisting by publisher certificate** — EDR allows all executables signed by a specific certificate
3. **Path-based allowlisting** — allow executables in the approved installation directory
4. **SBOM + vulnerability audit** — we generate CycloneDX SBOM and pip-audit reports with every build (see [IT Security Guide, Section 4](IT_Security_and_Compliance_Guide.md))

---

## 5. Network Segmentation

### The Problem

If IT places the DAQ workstation on the general corporate network without segmentation, it increases the attack surface by exposing industrial protocols and MQTT to the entire enterprise.

### What the Standards Say

**ISA-95 / Purdue Reference Model:**

The Purdue Model (adopted by ISA-99/IEC 62443) defines network segmentation levels:

| Level | Name | Examples |
|-------|------|----------|
| **Level 0** | Physical Process | Sensors, actuators, field instruments |
| **Level 1** | Basic Control | PLCs, cRIO controllers, Opto22 controllers |
| **Level 2** | Supervisory Control | **DAQ workstations, HMIs, SCADA** |
| **Level 3** | Manufacturing Operations | MES, data historians |
| **Level 3.5** | IT/OT DMZ | Firewalls, jump servers |
| **Level 4** | Enterprise IT | Email, ERP, corporate network |
| **Level 5** | Internet | Cloud services, remote access |

ICCSFlux sits at **Level 2** (supervisory control). The Purdue Model requires that Level 2 systems be **segmented from Level 4/5** via a DMZ (Level 3.5).

**Source:** [Palo Alto — Purdue Model for ICS Security](https://www.paloaltonetworks.com/cyberpedia/what-is-the-purdue-model-for-ics-security) | [SANS — Introduction to ICS Security Part 2](https://www.sans.org/blog/introduction-to-ics-security-part-2)

**IEC 62443-3-2 — Zones and Conduits:**

IEC 62443 requires systems to be grouped into **security zones** based on risk, with **conduits** controlling communication between zones. A DAQ workstation communicating with cRIO controllers, Modbus devices, and OPC-UA servers should be in its own OT zone, not on the corporate network.

**Source:** [Dragos — Understanding ISA/IEC 62443: Zones and Conduits](https://www.dragos.com/blog/isa-iec-62443-concepts)

### ICCSFlux Network Architecture

ICCSFlux is already designed for proper OT segmentation:

| Port | Bind Address | Transport | Purpose |
|------|-------------|-----------|---------|
| 1883 | **127.0.0.1** | TCP | Local services only (DAQ, watchdog) |
| 8883 | 0.0.0.0 | TCP + TLS | Remote controllers (cRIO, Opto22) — OT LAN only |
| 9002 | **127.0.0.1** | WebSocket | Dashboard (localhost browser) |
| 9003 | 0.0.0.0 | WebSocket + Auth | Remote dashboards (OT LAN only) |

The **Azure IoT Hub uploader** is the only component that crosses from OT to IT/Internet (outbound HTTPS only). It reads data from the historian SQLite database and can run on a DMZ host (Level 3.5) rather than the Level 2 DAQ workstation — see Section 7.

---

## 6. Password Rotation for Service Accounts

### The Problem

IT may require 90-day password rotation for all accounts, including machine-to-machine service credentials (MQTT broker, internal API tokens). Rotating these credentials on a running OT system creates:
- **Service outages** when credentials expire or are rotated without synchronizing all consumers
- **Safety gaps** if edge controllers (cRIO, Opto22) lose MQTT connectivity during rotation
- **Operational risk** disproportionate to the threat mitigated

### What the Standards Say

**NIST SP 800-63B Rev. 4 — Digital Identity Guidelines:**

NIST's current password guidance is unambiguous:

> "Verifiers and CSPs **SHALL NOT** require users to change passwords periodically. However, verifiers SHALL force a change if there is evidence of compromise."

This is not a suggestion — "SHALL NOT" is normative language in NIST standards. The rationale:

> "Research has shown that [periodic rotation] policies often lead to weaker security outcomes. Users tend to make minimal changes (e.g. adding a number or symbol to the end), which attackers can easily guess."

**Source:** [NIST SP 800-63B](https://pages.nist.gov/800-63-3/sp800-63b.html) | [Netwrix — NIST SP 800-63B Rev. 4 Explained](https://netwrix.com/en/resources/blog/nist-password-guidelines/)

### ICCSFlux Credential Security

- MQTT credentials are **auto-generated** with cryptographically random passwords at first run
- Credentials are stored with **restricted file permissions** (chmod 600)
- Port 1883 is **localhost-bound** — credentials cannot be attacked from the network
- Port 8883 requires **TLS** — credentials are encrypted in transit
- Credentials should be rotated **only if compromised**, not on an arbitrary schedule

---

## 7. Data Egress and Internet Connectivity

### Accurate Characterization

ICCSFlux acquires customer-owned process data on our company's hardware. This section describes what data leaves the workstation and where it goes.

ICCSFlux has **no inbound internet-facing services**. No ports are exposed to the public internet, and no component listens for connections from outside the OT network.

The system does have **one outbound internet connection**:

| Component | Direction | Protocol | Destination | Data Owner | Hosted By |
|-----------|-----------|----------|-------------|------------|-----------|
| Azure IoT Hub Uploader | **Outbound only** | HTTPS (443) | Our Azure IoT Hub account | Customer | **Us** |

This uploader:
- Runs as an **isolated process** (separate executable, separate Python environment)
- Reads data from the **historian SQLite database** — no MQTT dependency
- Uses **Azure IoT Hub device authentication** (SAS tokens or X.509 certificates)
- Sends customer data to **our company's Azure IoT Hub account** over HTTPS — encrypted, authenticated, outbound-only
- Customer data is retained in our Azure account for a configured period
- Can be **disabled entirely** if the deployment does not require cloud connectivity
- Does not expose any listening ports or accept inbound connections
- All configuration (connection string, channels, upload interval) is managed from the **DataTab UI**

All other communication (MQTT, WebSocket, Modbus, OPC-UA, EtherNet/IP) is confined to the OT network or localhost.

### Purdue-Compliant Architecture (DMZ Deployment)

The Azure Uploader reads all data from the historian SQLite database — not from MQTT. This means it can run on either the Level 2 DAQ workstation or a **separate host in the IT/OT DMZ (Level 3.5)**, with no code changes. For strict Purdue Model compliance, deploy the uploader on a DMZ host reading historian.db from a read-only network share:

```
Level 2 (DAQ workstation)          Level 3.5 (DMZ host)           Level 5
┌─────────────────────┐     ┌──────────────────────────┐    ┌───────────┐
│ DAQ Service          │     │ AzureUploader.exe         │    │ Azure IoT │
│   ↓ writes 1 Hz      │     │   --db-path \\DAQ\hist.db │───→│ Hub       │
│ historian.db (SQLite)│────→│                           │    └───────────┘
│   channels + events  │ SMB │ Reads config from DB      │
│   + azure_config     │share│ Reads data from DB        │
│                      │(r/o)│ Sends HTTPS to Azure      │
│ No Azure SDK         │     │                           │
│ No internet access   │     │                           │
└─────────────────────┘     └──────────────────────────┘
```

**How it works:**

1. User configures Azure settings in the **DataTab** (connection string, channels, upload interval)
2. DAQ service writes config to `historian.db` → `azure_config` table
3. AzureUploader polls `azure_config` for changes, `datapoints` for channel data, `events` for safety events
4. Data is batched and sent to Azure IoT Hub over HTTPS

The historian captures both channel telemetry (1 Hz) and safety events (alarms, trips, safety actions) so the uploader has complete visibility. The **Upload Interval** setting in the DataTab controls the poll rate (e.g. 1000 ms = 1s, 5000 ms = 5s).

| Factor | Assessment |
|--------|-----------|
| Azure SDK location | DMZ host (Level 3.5) — or Level 2 if DMZ not required |
| Internet access on DAQ PC | **Not required** |
| Data conduit | SQLite read-only (single file, SMB share) |
| Configuration | DataTab UI → historian.db → uploader |
| Safety events | Polled from historian events table |
| Purdue-compliant | **Yes** — Level 2 has no internet-facing code |

---

## 8. The CrowdStrike Precedent

### What Happened

On **July 19, 2024**, CrowdStrike pushed a flawed update to its Falcon EDR agent that caused **8.5 million Windows systems worldwide** to display the Blue Screen of Death (BSOD). The root cause was a mismatch between template fields in a channel file update — a bounds check was missing.

### Impact on Industrial Operations

The outage affected manufacturing, logistics, and industrial operations globally. Amazon warehouse operations were disrupted. The worldwide financial damage was estimated at **over $10 billion**.

**Source:** [Wikipedia — 2024 CrowdStrike-related IT outages](https://en.wikipedia.org/wiki/2024_CrowdStrike-related_IT_outages) | [SecurityWeek analysis](https://www.techtarget.com/whatis/feature/Explaining-the-largest-IT-outage-in-history-and-whats-next)

### Why This Matters for ICCSFlux

This is a real-world example of exactly what NIST SP 800-82 warns about: an IT security tool — pushed automatically, without OT-specific testing — crashing industrial systems. If the ICCSFlux DAQ machine had been running CrowdStrike Falcon with automatic updates:

- The system would have **BSOD'd mid-acquisition**
- In-progress recordings would have been **corrupted or lost**
- Safety interlocks would have **failed without executing safe-state**
- Physical equipment could have been left in an **unsafe operating condition**

The CrowdStrike incident validates every recommendation in this document:
- EDR updates to OT systems must be **tested before deployment** (IEC 62443-2-3)
- OT systems must have **exclusions and controlled update policies** (NIST SP 800-82)
- Application allowlisting is safer than signature-based detection for OT (SANS, CISA)

### Post-Incident Industry Response

CrowdStrike's own remediation acknowledges the problem:
- All updates will be "tested internally and implemented in phases"
- Customers can "choose when they update to the newest version"
- Additional testing and validation will be performed before release

These are the same controls NIST and IEC have recommended for OT systems for over a decade.

**Source:** [Industrial Defender — OT Considerations for the CrowdStrike/Microsoft Outage](https://www.industrialdefender.com/blog/ot-considerations-for-the-global-crowdstrike-microsoft-outage)

---

## 9. Applicable Security Levels

### IEC 62443 Security Level Assessment

IEC 62443-3-3 defines four Security Levels (SL) based on threat actor capability:

| Level | Threat Actor | Description |
|-------|-------------|-------------|
| **SL 1** | Casual/accidental | Protection against unintentional or accidental violation |
| **SL 2** | Intentional, low skill | Protection against intentional violation using simple means |
| **SL 3** | Intentional, moderate skill | Protection against sophisticated attack with moderate resources |
| **SL 4** | Nation-state / APT | Protection against state-sponsored attack with extensive resources |

### ICCSFlux Target Security Level: SL 1–2

ICCSFlux is a data acquisition tool deployed on our company's workstations on a **segmented OT network**, acquiring **customer-owned process data**. The appropriate target security level is **SL 1 to SL 2** based on:

| Factor | Assessment |
|--------|-----------|
| Internet exposure | None inbound; one outbound HTTPS connection to our Azure IoT Hub (optional) |
| Network location | Isolated OT LAN, behind IT/OT DMZ |
| Physical access | Engineering workstation in controlled facility |
| Data sensitivity | Customer-owned process telemetry (temperatures, pressures, flows) — not PII, not financial, but proprietary to the customer |
| Threat model | Insider accident (SL1), disgruntled insider (SL2) |
| Attack surface | No public-facing services, no remote administration |

Applying SL 3–4 controls (designed for nation-state threats) to an internal DAQ workstation is **disproportionate to the risk** and **counter to the IEC 62443 risk-based approach**, which explicitly requires that security levels be assigned "based on the potential consequences should an attack objective be achieved within that zone."

**Source:** [IEC 62443 Security Levels Explained](https://www.graftholders.com/iec-62443-security-levels-explained/) | [Dragos — Understanding ISA/IEC 62443](https://www.dragos.com/blog/isa-iec-62443-concepts)

---

## 10. SOC 2 Applicability

### What SOC 2 Is

SOC 2 (System and Organization Controls 2) is an audit framework created by the [AICPA](https://www.aicpa-cima.com/topic/audit-assurance/audit-and-assurance-greater-than-soc-2) (American Institute of Certified Public Accountants). It is designed for **service organizations** — companies that store, process, or transmit **other organizations' data** as a service.

Per AICPA's own definition, SOC 2 reports:

> "Examine services provided by a service organization so that **end users** can assess and address the risk associated with an **outsourced service**."

SOC 2 reports assess controls "relevant to security, availability, and processing integrity of the systems **the service organization uses to process users' data** and the confidentiality and privacy of the information processed by these systems."

The key words are: **service organization**, **outsourced service**, **users' data**.

### ICCSFlux and Customer Data

ICCSFlux is an internal data acquisition tool that runs on **our computers** and acquires process data (temperature, pressure, flow, etc.) that is **owned by our customers**. Every production deployment — unless it's an internal CIP or research project — is acquiring customer-owned data on our hardware.

When Azure IoT Hub is enabled, customer data is uploaded to **our** Azure IoT Hub account and stored for a period of time. This means:

- Customer data is acquired on **our** hardware (workstations)
- Customer data is stored on **our** local drives (historian.db, CSV/TDMS recordings)
- Customer data is uploaded to **our** cloud infrastructure (Azure IoT Hub)
- We host and retain customer data for a defined period

### SOC 2 Applicability

Given the above, ICCSFlux touches SOC 2 scope in two areas:

| SOC 2 Scope Question | ICCSFlux Answer | Result |
|----------------------|-----------------|--------|
| Does it process **customer data**? | **Yes** — acquires and stores customer-owned process data on our hardware | **In scope** |
| Is customer data stored in **our infrastructure**? | **Yes** — on our workstations locally, and in our Azure IoT Hub account when enabled | **In scope** |
| Do we **retain** customer data? | **Yes** — historian.db retains 30 days locally; Azure IoT Hub retains data for a configured period | **In scope** |
| Is this a **SaaS, cloud, or hosted product**? | No — standalone portable application on a local workstation, not a multi-tenant service | Not a SaaS model |
| Do **multiple customers** share the same system simultaneously? | No — each deployment is a dedicated workstation for one customer's project | No multi-tenancy |
| Is this an **outsourced data processing service**? | No — data acquisition is performed as part of an engineering engagement, not as a standalone data service | Not an outsourced service |

SOC 2 is primarily designed for SaaS, cloud, and managed service providers (AWS, Salesforce, payroll vendors). ICCSFlux is not that — it is an on-premises industrial tool used during engineering engagements. However, because we do acquire, store, and host customer data on our own equipment and cloud accounts, the **data handling obligations** that SOC 2 addresses are real even if the full SOC 2 audit framework is not the right fit.

### What This Means in Practice

The fact that we handle customer data on our equipment and in our Azure account means we need controls around:

- **Data retention and deletion**: Customer data on our workstations and in Azure IoT Hub must have defined retention periods and be deleted when no longer needed
- **Access control**: Only authorized personnel should access customer data (ICCSFlux supports role-based auth with Admin/Operator/Viewer roles)
- **Audit trails**: ALCOA+ compliant audit trails track who did what (21 CFR Part 11 support, SHA-256 hash chain, tamper detection)
- **Network segmentation**: OT data stays on the OT network, isolated from corporate IT (Purdue Model Level 2)
- **Azure IoT Hub security**: Data uploaded to our Azure account over HTTPS via DMZ relay, TLS-encrypted, authenticated
- **Workstation hygiene**: Local data (historian.db, recordings) must be managed between customer engagements

### What Standards Apply

| Standard | Applicability | Why |
|----------|--------------|-----|
| **IEC 62443** | **Yes — primary** | Purpose-built for Industrial Automation and Control Systems (IACS). Governs the on-premises OT portion of ICCSFlux. |
| **NIST SP 800-82** | **Yes** | NIST guidance specifically for Operational Technology security |
| **ISA-95 / Purdue Model** | **Yes** | Network segmentation model for industrial systems |
| **21 CFR Part 11** | **Conditional** | Only if deployed in FDA-regulated pharma/biotech environments requiring electronic records compliance. ICCSFlux supports ALCOA+ audit trails for this case. |
| **GAMP 5** | **Conditional** | Only if the system requires computerized system validation under GxP regulations |
| **ISO 27001** | **Organizational** | Applies to our organization's overall information security management, including how we handle customer data on our equipment and in our Azure account |
| **SOC 2** | **Partial** | The on-premises OT instrument does not fit the SOC 2 service model. However, hosting customer data in our Azure IoT Hub account means SOC 2 Trust Services Criteria (Security, Availability, Confidentiality) are relevant to that cloud component. An organization-level SOC 2 may eventually be warranted as the Azure hosting footprint grows. |

### If IT Cites SOC 2 as Justification

If a customer's IT security team asks whether we are SOC 2 compliant:

> "ICCSFlux is an on-premises data acquisition tool, not a cloud or SaaS product. The on-premises OT components are governed by **IEC 62443**, which is purpose-built for Industrial Automation and Control Systems. ICCSFlux complies with IEC 62443 Security Level 1–2 controls, including role-based access control, ALCOA+ audit trails, authenticated and TLS-encrypted communications, and Purdue Model network segmentation.
>
> When Azure IoT Hub is enabled, customer data is uploaded to our Azure account over HTTPS via a DMZ relay. We apply appropriate access controls, retention policies, and encryption to this data. We recognize that this cloud component carries data handling obligations and we are working to align our Azure practices with SOC 2 Trust Services Criteria.
>
> We welcome a review of our security controls against IEC 62443 (for the OT components) and can discuss our Azure data handling practices in detail."

**Sources:**
- [AICPA — SOC 2 for Service Organizations](https://www.aicpa-cima.com/topic/audit-assurance/audit-and-assurance-greater-than-soc-2)
- [AICPA — SOC Suite of Services](https://www.aicpa-cima.com/resources/landing/system-and-organization-controls-soc-suite-of-services)
- [ISA — Applying ISO/IEC 27001 and IEC 62443 for OT Environments](https://gca.isa.org/blog/white-paper-excerpt-applying-iso/iec-27001/2-and-the-isa/iec-62443-series-for-operational-technology-environments)

---

## 11. Standards Reference Table

Quick reference for IT discussions:

| Topic | Standard | Key Citation |
|-------|----------|-------------|
| OT ≠ IT (priority inversion) | NIST SP 800-82r3, Section 2, Table 1 | Safety > Availability > Integrity > Confidentiality |
| EDR/AV limitations in OT | NIST SP 800-82r3; SANS ICS 5 Critical Controls | "May compromise real-time performance" |
| Application allowlisting preferred | CISA Application Whitelisting for ICS; SANS | Proactive > reactive for OT |
| Patch testing before deployment | IEC 62443-2-3; NIST SP 800-82r3 | "Must be thoroughly tested; may require vendor validation" |
| No periodic password rotation | NIST SP 800-63B Rev. 4 | "SHALL NOT require users to change passwords periodically" |
| Network segmentation (Purdue) | ISA-95 / IEC 62443-3-2 | DAQ = Level 2, must be separated from Level 4/5 |
| Zones and conduits | IEC 62443-3-2 | Risk-based zoning, not one-size-fits-all |
| Security levels (SL 1–4) | IEC 62443-3-3 | Assign SL based on threat actor, not blanket policy |
| OT connectivity principles | CISA + NCSC + FBI (2024) | OT requires fundamentally different security approach |
| EDR auto-update risk | CrowdStrike July 2024 incident | 8.5M systems BSOD'd by untested EDR update |
| PyInstaller false positives | PyInstaller #6754, #4694, #2988 | Known industry issue, not a security indicator |
| Audit trail integrity | 21 CFR Part 11 / ALCOA+ | Unplanned reboots can corrupt hash-chain audit logs |
| SOC 2 partial applicability | AICPA Trust Services Criteria | On-premises OT governed by IEC 62443; Azure IoT Hub hosting of customer data carries SOC 2-relevant data handling obligations |

---

## 12. Recommended IT/OT Security Agreement

Based on the standards above, this is the security posture that aligns with NIST, IEC, ISA, CISA, and SANS guidance:

### What IT Should Do

| Control | Implementation |
|---------|---------------|
| EDR/Endpoint protection | Install with **path and process exclusions** for ICCSFlux directories |
| Windows patching | **WSUS with manual approval**, applied during maintenance windows |
| Network segmentation | Place DAQ workstation on **dedicated OT VLAN**, not corporate network |
| Firewall rules | Allow localhost (127.0.0.1) traffic freely; allow OT LAN ports 8883, 9003; allow outbound HTTPS to our Azure IoT Hub account (if enabled) |
| Executable policy | **Code signing** or **publisher-based allowlisting**, not hash whitelisting |
| Credential rotation | Rotate **only on evidence of compromise**, not on a schedule |
| Monitoring | Network monitoring and **passive** detection (not inline/blocking) on OT segment |
| Change management | Coordinate OT changes through **maintenance windows** with engineering |

### What IT Should Not Do

| Action | Why Not | Standard |
|--------|---------|----------|
| Enable automatic Windows Updates | Reboots during acquisition = data loss + safety risk | IEC 62443-2-3, NIST 800-82r3 |
| Run full AV scans during acquisition | CPU spikes break real-time 10 Hz scan loops | NIST 800-82r3, SANS ICS |
| Block localhost network traffic | Breaks MQTT broker (1883) and dashboard (9002) | Architecture requirement |
| Apply 90-day password rotation to service accounts | Causes service outages; NIST says "SHALL NOT" | NIST SP 800-63B Rev. 4 |
| Quarantine PyInstaller executables | Known false-positive pattern, not a threat indicator | PyInstaller issue tracker |
| Place DAQ on corporate network | Violates Purdue Model Level 2/4 separation | ISA-95, IEC 62443-3-2 |
| Push EDR updates without testing | CrowdStrike 7/19/2024: 8.5M BSOD'd systems | IEC 62443-2-3 |

---

## Document References

### Primary Standards

| Standard | Title | Link |
|----------|-------|------|
| NIST SP 800-82 Rev. 3 | Guide to Operational Technology (OT) Security | [PDF](https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-82r3.pdf) |
| IEC 62443 (series) | Industrial Automation and Control Systems Security | [IEC Webstore](https://webstore.iec.ch/en/publication/22811) |
| IEC 62443-2-3 | Patch Management in the IACS Environment | [ISA Analysis](https://gca.isa.org/blog/importance-and-challenges-of-ot-patching-in-line-with-isa/iec-62443-2-3) |
| IEC 62443-3-2 | Security Risk Assessment for System Design | [Dragos Guide](https://www.dragos.com/blog/isa-iec-62443-concepts) |
| IEC 62443-3-3 | System Security Requirements and Security Levels | [Graftholders Guide](https://www.graftholders.com/iec-62443-security-levels-explained/) |
| NIST SP 800-63B Rev. 4 | Digital Identity Guidelines — Authentication | [NIST](https://pages.nist.gov/800-63-3/sp800-63b.html) |
| ISA-95 / Purdue Model | Enterprise-Control System Integration | [Palo Alto Guide](https://www.paloaltonetworks.com/cyberpedia/what-is-the-purdue-model-for-ics-security) |

### Government Guidance

| Document | Agency | Link |
|----------|--------|------|
| Principles of OT Cyber Security | CISA + NCSC + FBI | [CISA](https://www.cisa.gov/resources-tools/resources/principles-operational-technology-cyber-security) |
| Secure by Demand for OT | CISA + FBI + NCSC | [CISA](https://www.cisa.gov/resources-tools/resources/secure-demand-priority-considerations-operational-technology-owners-and-operators-when-selecting) |
| Guidelines for Application Whitelisting in ICS | CISA (DHS) | [PDF](https://www.cisa.gov/sites/default/files/documents/Guidelines%20for%20Application%20Whitelisting%20in%20Industrial%20Control%20Systems_S508C.pdf) |
| OT Architecture Guidance | CISA | [CISA](https://www.cisa.gov/resources-tools/resources/creating-and-maintaining-definitive-view-your-operational-technology-ot-architecture) |

### Industry Guidance

| Document | Author | Link |
|----------|--------|------|
| Five ICS Cybersecurity Critical Controls | SANS Institute | [Whitepaper](https://www.sans.org/white-papers/five-ics-cybersecurity-critical-controls) |
| Introduction to ICS Security Part 2 — Purdue Model | SANS Institute | [Blog](https://www.sans.org/blog/introduction-to-ics-security-part-2) |
| OT Security Dozen Part 3: Network Segmentation | ISA Global Cybersecurity Alliance | [Blog](https://gca.isa.org/blog/ot-security-dozen-part-3-network-security-architecture-segmentation) |

### Incident References

| Event | Date | Source |
|-------|------|--------|
| CrowdStrike Falcon EDR global outage | July 19, 2024 | [Wikipedia](https://en.wikipedia.org/wiki/2024_CrowdStrike-related_IT_outages) |
| OT lessons from CrowdStrike outage | July 2024 | [Industrial Defender](https://www.industrialdefender.com/blog/ot-considerations-for-the-global-crowdstrike-microsoft-outage) |

### PyInstaller False-Positive Evidence

| Issue | Status | Link |
|-------|--------|------|
| PyInstaller #6754 — AV false positives | Open (ongoing) | [GitHub](https://github.com/pyinstaller/pyinstaller/issues/6754) |
| PyInstaller #4694 — AV detection | Documented | [GitHub](https://github.com/pyinstaller/pyinstaller/issues/4694) |
| PyInstaller #2988 — False-Positive | Documented | [GitHub](https://github.com/pyinstaller/pyinstaller/issues/2988) |
| Code4Lib — False Positives in Python Apps | Published paper | [Journal](https://journal.code4lib.org/articles/18136) |
