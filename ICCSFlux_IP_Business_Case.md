# ICCSFlux: Intellectual Property & Business Case

**Prepared for:** Management Review
**Date:** February 2026
**Classification:** Internal / Confidential

---

## 1. Executive Summary

ICCSFlux is a Python-based, open-architecture industrial data acquisition and control platform. It allows lab developers to build custom measurement and control systems using a configuration-driven node model, a unified web frontend, and pluggable hardware backends -- without writing application code or purchasing expensive proprietary software.

No existing open-source or commercial product occupies this specific position in the market. This document outlines the novel intellectual property, the competitive gap ICCSFlux fills, and recommended terms for protecting and commercializing it.

---

## 2. The Market Gap

### What exists today

| Solution | Limitation |
|----------|-----------|
| **LabVIEW** (National Instruments) | $3,000-5,000+/seat, proprietary graphical language, steep learning curve, NI hardware only |
| **DASYLab / FlexLogger / SignalExpress** | Vendor-locked, limited customization, no distributed safety |
| **DEWESoft / CatmanAP / imc FAMOS** | Expensive commercial DAQ software tied to vendor hardware |
| **EPICS** (Argonne/SLAC) | Built for particle accelerators; assumes large facility teams, C/C++ expertise |
| **Tango Controls** (ESRF) | Built for synchrotrons/telescopes; complex, niche ecosystem |
| **Bluesky/Ophyd** (Brookhaven) | Designed for synchrotron beamline scans; not general lab use |
| **Node-RED** | IoT automation tool; no safety logic, no DAQ integration, no recording |
| **Homebrew Python scripts** | Every lab has them; none are complete systems |

### What does NOT exist

**A general-purpose, open-source, Python-based lab data acquisition and control platform that:**

- Works without per-seat licensing costs
- Supports multiple hardware vendors (NI, Opto22, Modbus, OPC-UA, Siemens S7)
- Provides distributed safety logic on real-time controllers
- Offers a modern web-based UI accessible from any device
- Requires no programming to configure -- only JSON project files
- Deploys as a single portable executable with zero dependencies

**ICCSFlux is that platform.**

---

## 3. Novel Technical Claims

The following are specific, implementable innovations in ICCSFlux that distinguish it from prior art. Each is supported by existing code in the repository.

### Claim 1: ProjectMode -- Backend-Agnostic Architecture with Safety-Aware Switching

**What it is:** A system architecture where the same unified frontend, configuration schema, and user experience operate identically across fundamentally different hardware backends (PC-local DAQ, remote cRIO real-time controller, remote Opto22 groov EPIC). The choice of backend is a single configuration parameter (`project_mode`) that determines not just where data is read, but where safety logic executes.

**Why it matters:** Existing systems require users to commit to an architecture at design time. Switching from a PC-based system to a PLC-based system (e.g., LabVIEW on PC to LabVIEW Real-Time on cRIO) requires significant rework. ICCSFlux allows this switch via one config change.

**Key distinction from prior art:**
- LabVIEW requires separate projects for desktop vs. real-time targets
- Node-RED has no concept of safety-critical backend selection
- EPICS/Tango are single-architecture systems

**Implementation:** `config_parser.py` -- `ProjectMode` enum, `HardwareSource` enum, `ChannelConfig.safety_can_run_locally` property

---

### Claim 2: Declarative Distributed Safety Engine

**What it is:** Safety interlocks defined as JSON data structures (not code) that can execute autonomously on a remote real-time controller (cRIO). The interlock engine supports:

- Condition evaluation with configurable delay and deadband
- Latch state machine (SAFE / ARMED / TRIPPED) with manual reset
- Hardware watchdog output (if the scan loop stops, an external relay trips)
- Proof-testing metadata for regulatory compliance (demand count, last proof test timestamp)
- Bypass tracking with operator identity and reason (audit trail)

**Why it matters:** In existing systems, safety logic is either hard-coded (PLCs with ladder logic) or runs only on the PC (LabVIEW). ICCSFlux allows safety logic to be:

1. Defined declaratively in JSON (no programming)
2. Deployed to a real-time controller automatically
3. Executed independently of the PC (survives PC crashes)
4. Audited for regulatory compliance (IEC 61511, FDA 21 CFR Part 11)

**Key distinction from prior art:**
- PLC ladder logic requires specialized programming; ICCSFlux uses JSON
- LabVIEW safety runs on PC only unless separately developed for RT
- Node-RED/EPICS have no built-in safety interlock framework

**Implementation:** `safety.py` (cRIO), `safety_manager.py` (PC), project JSON `safety.interlocks[]`

---

### Claim 3: Configuration-Driven System Definition (Zero-Code Lab Setup)

**What it is:** A complete data acquisition and control system -- channels, scaling, limits, alarms, safety interlocks, recording parameters, PID loops, scripts, dashboard layout -- defined entirely in a single JSON project file. No application code changes are required to:

- Add or remove measurement channels
- Change hardware backends
- Define new safety interlocks
- Configure recording strategies
- Set up PID control loops

**Why it matters:** Today, configuring a lab DAQ system requires either proprietary software (LabVIEW, DEWESoft) or custom Python scripting. ICCSFlux eliminates both -- a lab technician can set up a complete measurement and control system by editing a JSON file or using the web-based configuration editor.

**Key distinction from prior art:**
- LabVIEW requires graphical programming for any configuration change
- EPICS uses its own database format (EPICS DB) requiring specialized knowledge
- Homebrew Python scripts require a developer for every change

**Implementation:** `project_manager.py`, project JSON schema (v2.0), web-based configuration editor in dashboard

---

### Claim 4: Unified Channel Type Abstraction Across Hardware Vendors

**What it is:** A semantic channel type system (40+ types) that abstracts measurement types (thermocouple, RTD, strain, current loop, digital I/O, counter, Modbus register, etc.) across hardware from multiple vendors. The same channel type definition works whether the physical hardware is:

- NI cDAQ/PXI (via DAQmx)
- NI cRIO (via remote node)
- Opto22 groov EPIC/RIO (via REST API)
- Generic Modbus device (TCP/RTU)
- OPC-UA server
- Siemens S7 PLC

Includes an auto-detection database mapping 60+ NI C Series module part numbers to their default channel types and hardware limits.

**Key distinction from prior art:**
- LabVIEW channels are hardware-specific; switching vendors requires rewriting
- Node-RED nodes are protocol-specific, not measurement-type-aware
- No existing system maps semantic measurement types across this range of vendors

**Implementation:** `channel_types.py`, `config_parser.py` (`HardwareSource` enum), `NI_MODULE_DATABASE`

---

### Claim 5: Zero-Install Portable Distribution Model

**What it is:** The entire system -- Python runtime, MQTT broker (Mosquitto), web dashboard, DAQ service, and all configuration -- bundles into a single Windows executable (~70 MB). On first run, it:

1. Auto-generates MQTT credentials (PBKDF2-SHA512 hashed)
2. Starts the MQTT broker
3. Starts the DAQ service
4. Serves the web dashboard
5. Opens the user's browser

No installation, no system dependencies, no admin privileges required.

**Why it matters:** Deploying a LabVIEW system requires LabVIEW Runtime Engine, NI drivers, and often admin access. EPICS requires compiling from source. ICCSFlux runs from a USB stick.

**Implementation:** `build_portable.py`, `build_exe.py`, `mqtt_credentials.py`

---

### Claim 6: MQTT-Based Node Mesh with Autonomous Operation

**What it is:** A distributed architecture where hardware nodes (cRIO, Opto22, Compact FieldPoint) operate as autonomous agents connected via MQTT. Each node:

- Discovers and announces itself via heartbeat messages
- Reads its local I/O independently
- Executes safety logic locally
- Publishes data to the MQTT backbone
- Continues operating if the PC or broker disconnects

The PC acts as an HMI (dashboard, recording, user scripts) but is not required for safe operation of the hardware.

**Key distinction from prior art:**
- LabVIEW requires the PC for all logic unless separately programmed for RT
- EPICS uses a custom Channel Access protocol, not a standard like MQTT
- No existing open-source DAQ system uses MQTT as the primary data backbone with autonomous node safety

**Implementation:** `mqtt_interface.py`, `crio_node.py`, `device_discovery.py`

---

## 4. Competitive Positioning

```
                    High Cost
                       |
         LabVIEW  -----+-----  DEWESoft / CatmanAP
         (NI only)     |       (vendor-locked)
                       |
  Complexity ----+-----+-----+---- Simplicity
                 |     |     |
         EPICS / |     |     |  ICCSFlux
         Tango   |     |     |  (THIS GAP)
         (big    |     |     |
          science)|     |     |
                  |     |     |
                  +-----+-----+
                       |
                  Low Cost / Open Source
```

ICCSFlux occupies the **lower-right quadrant** -- low cost, high simplicity -- which is currently empty for industrial-grade lab DAQ systems with distributed safety.

---

## 5. IP Valuation

Three standard methods are used to value software intellectual property. All three are presented below to triangulate a range.

### Method 1: Cost Approach (Replacement Cost)

What would it cost to rebuild ICCSFlux from scratch?

**Codebase scope:**

| Component | Files | Lines of Code |
|-----------|------:|-------------:|
| Python backend (services, tests, scripts) | 141 | 88,850 |
| TypeScript (dashboard logic) | 65 | 37,432 |
| Vue components (dashboard UI) | 62 | 58,348 |
| **Total** | **268** | **184,630** |

**Labor estimate using industry rates:**

A system of this complexity requires overlapping expertise in: industrial control systems, real-time safety engineering, NI hardware/DAQmx, MQTT/IoT architecture, Python backend development, Vue.js frontend development, and portable deployment engineering. This combination is rare in a single developer or even a small team.

Using COCOMO II (Constructive Cost Model) for 185K SLOC of moderate-to-high complexity:

| Factor | Estimate |
|--------|----------|
| Effective person-months (COCOMO II, semi-detached) | 40-60 person-months |
| Blended senior rate (controls + full-stack + domain) | $12,000-18,000/month fully loaded |
| Domain expertise premium (industrial safety, DAQmx, regulatory) | 1.5x multiplier |
| **Replacement cost estimate** | **$720,000 - $1,620,000** |

This does not account for the trial-and-error knowledge embedded in the architecture -- the decisions about what NOT to do, which are often more valuable than the code itself.

**Cost approach value: $700K - $1.6M**

---

### Method 2: Market Approach (Comparable Transactions)

What have similar assets sold for?

**Industry context:**

- Emerson acquired National Instruments (LabVIEW, cDAQ, cRIO ecosystem) in 2023 for **$8.2 billion** on ~$1.7B revenue (~4.8x revenue multiple). NI's Test & Measurement segment alone generated $1.46B in FY2024.
- The global DAQ system market is valued at **$2.8-3.3 billion** (2025), growing at 5.9-6.5% CAGR.
- The SCADA software market specifically is valued at **$1.08 billion** (2025), growing at 8.7% CAGR to $2.1B by 2033.
- Median software M&A multiple: **3.0x EV/Revenue** (2015-2025 data).
- SCADA-specific acquisitions increased 47% in recent years. Schneider Electric acquired AVEVA; Honeywell acquired analytics firms; SCADA International acquired NovoGrid -- all for software IP in this space.

**Comparable positioning:**

ICCSFlux is pre-revenue, so direct revenue multiples don't apply yet. However, as a technology asset:

- It directly competes with LabVIEW in the general lab DAQ space (8,000-14,000 companies use LabVIEW at $3,000-5,000/seat)
- It addresses a segment NI itself is trying to modernize (NI launched FlexLogger plugins on GitHub in Feb 2025, signaling a move toward open ecosystems)
- Pre-revenue software IP in industrial automation typically transacts at **$1M-$5M** for a complete, deployable platform with demonstrated capability, based on comparable early-stage acquisitions in the industrial software space

**Market approach value: $1M - $5M** (as a technology acquisition, pre-revenue)

---

### Method 3: Income Approach (Discounted Future Cash Flow)

What could ICCSFlux generate if commercialized?

**Addressable market -- site license model:**

| Segment | Estimated Sites | Notes |
|---------|----------------:|-------|
| R&D labs (pharma, chemical, materials) | ~15,000 | Currently using LabVIEW, FlexLogger, or homebrew scripts |
| Manufacturing test floors | ~20,000 | End-of-line test, quality control |
| University research labs | ~10,000 | Budget-constrained, strong open-source affinity |
| Government / national labs | ~2,000 | EPICS users looking for simpler alternatives |
| **Total addressable sites** | **~47,000** | |

Even capturing a small fraction of this market with site licenses produces meaningful revenue:

**Conservative scenario (1% penetration over 5 years):**

| Year | Sites | Revenue/Site | Annual Revenue |
|------|------:|-------------:|---------------:|
| 1 | 25 | -- | $0 (free tier / adoption) |
| 2 | 75 | -- | $0 (building base) |
| 3 | 150 | Site-dependent | Early revenue |
| 4 | 300 | Site-dependent | Growing revenue |
| 5 | 470 | Site-dependent | Established revenue |

Note: Specific revenue-per-site figures depend on pricing decisions that haven't been made yet. The point is the market size -- even modest penetration of 47,000 addressable sites represents significant potential.

**What drives value in the income model:**

- LabVIEW costs $3,000-5,000 per seat, per year. A site with 5 engineers pays $15,000-25,000/year to NI.
- ICCSFlux eliminates per-seat costs entirely. A site license priced at any fraction of the LabVIEW equivalent is immediately attractive.
- Switching costs are low (Python skills are common; LabVIEW skills are not).
- The site license model means revenue scales with adoption, not headcount.

**Discounted cash flow (10% discount rate, 5-year horizon):**

The present value of the income stream depends entirely on pricing and go-to-market execution. However, the addressable market supports a **net present value of $2M-$10M** under reasonable penetration assumptions (0.5-2% of addressable sites).

**Income approach value: $2M - $10M** (dependent on commercialization execution)

---

### Valuation Summary

| Method | Range | Confidence | Notes |
|--------|-------|-----------|-------|
| **Cost (replacement)** | $700K - $1.6M | High | Floor value. What it would cost to rebuild. |
| **Market (comparables)** | $1M - $5M | Medium | Pre-revenue technology asset in a growing market. |
| **Income (future cash flow)** | $2M - $10M | Lower | Dependent on go-to-market execution. |

**Defensible IP value range: $1M - $5M**

The cost approach sets a hard floor (~$700K). The market approach, anchored by comparable transactions in the SCADA/DAQ space, centers the value at $1M-$5M for a pre-revenue but complete, deployable platform. The income approach suggests higher upside ($2M-$10M) if commercialized, but carries execution risk.

For a conversation with management, **$1M-$5M** is the defensible range to present, with the $2M-$10M income figure as upside potential.

---

## 6. Site License Model

ICCSFlux is best suited to a **site license** model rather than per-seat or per-channel pricing. The rationale:

| Factor | Why Site License Wins |
|--------|----------------------|
| **No per-seat cost** | This is ICCSFlux's core advantage over LabVIEW. Don't give it away by charging per user. |
| **Scales with value, not headcount** | A site with 50 engineers gets the same value as one with 5. Price by site, not by people. |
| **Simplifies procurement** | One PO per site per year. No license counting, no audits, no compliance headaches. |
| **Matches deployment model** | ICCSFlux runs as one instance per site (one MQTT broker, one dashboard, multiple nodes). The license matches the architecture. |
| **Competitive displacement** | A site paying $25,000+/year for 5 LabVIEW seats can switch to a single site license at a fraction of the cost. The savings sell themselves. |

**What a site license includes:**

- Unlimited users at one physical location
- Unlimited channels and hardware nodes
- All software updates for the license term
- Web dashboard access from any device on the site network
- Configuration and project file support
- Access to community node library

**What remains separate (potential revenue streams):**

| Add-On | Description |
|--------|-------------|
| **SIL certification package** | Pre-validated safety configurations for IEC 61511 compliance |
| **Custom node development** | Purpose-built hardware nodes for client-specific equipment |
| **On-site deployment & training** | Engineering services for initial system setup |
| **Priority support SLA** | Guaranteed response for production-critical issues |

---

## 7. Immediate Next Steps

1. **Establish ownership:** Confirm IP assignment (was this developed on company time, with company resources, or independently?). This determines who can file patents and license the software.

2. **Formal IP valuation:** Engage a qualified IP valuation firm to produce a defensible appraisal. The ranges in this document are estimates based on publicly available data -- a formal valuation (typically $5,000-15,000) produces a number that holds up in negotiations, M&A, or tax/accounting contexts.

3. **File provisional patent:** Engage a patent attorney specializing in software/industrial systems. Focus claims on:
   - ProjectMode backend-agnostic architecture with safety-aware switching
   - Declarative distributed safety engine with JSON-defined interlocks on real-time controllers
   - Zero-code configuration model for complete DAQ/control systems

4. **Prior art search:** Attorney conducts formal search against EPICS, LabVIEW RT, Node-RED, and commercial SCADA systems to validate novelty of claims.

5. **Site license pilot:** Identify 3-5 internal or partner sites willing to run ICCSFlux in production. Real deployments convert the income-approach valuation from theoretical to demonstrated.

6. **Clean room the codebase:** Ensure no third-party code or licenses conflict with chosen IP strategy. Verify all dependencies are compatible with commercial licensing.

---

## 8. Summary

ICCSFlux fills a genuine gap in the lab data acquisition market. The combination of:

- **Zero-code configuration** (JSON project files)
- **Multi-vendor hardware support** (NI, Opto22, Modbus, OPC-UA, S7)
- **Distributed safety on real-time controllers** (cRIO, groov EPIC)
- **Unified web frontend** (Vue 3 dashboard)
- **Zero-install portable deployment** (single .exe)
- **Python-based open architecture** (no proprietary language)

...does not exist in any current product, open-source or commercial. The closest competitors are either locked to a single ecosystem (LabVIEW, EPICS), lack safety capabilities (Node-RED), or require significant cost and expertise (commercial SCADA).

Using three standard valuation methods (cost, market, and income), the IP is estimated at **$1M-$5M** today, with **$2M-$10M** upside if commercialized via a site license model. A provisional patent filing should be pursued to establish priority on the novel claims while a formal IP valuation and site license pilot are developed.

---

*This document is for internal discussion purposes. Consult a qualified intellectual property attorney before making filing or licensing decisions.*
