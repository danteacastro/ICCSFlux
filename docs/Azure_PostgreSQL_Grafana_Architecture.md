# Azure IoT Hub → PostgreSQL → Grafana Cloud Architecture

## DoD / DOE Compliance Reference Design for ICCSFlux

---

## 1. Applicable Standards

| Standard | Scope | Why It Applies |
|----------|-------|----------------|
| **NIST SP 800-171 r2** | CUI protection | If DAQ telemetry is Controlled Unclassified Information (process data from DoD/DOE facilities) |
| **NIST SP 800-53 r5** | Security controls | Baseline control catalog; FedRAMP and CMMC map to this |
| **CMMC 2.0 Level 2** | DoD contractor cybersecurity | Required if handling CUI for DoD contracts (110 practices from 800-171) |
| **FedRAMP High** | Cloud authorization | Azure Government is FedRAMP High authorized; required for federal workloads |
| **FIPS 140-2 / 140-3** | Cryptographic modules | All encryption (TLS, AES, hashing) must use FIPS-validated modules |
| **NIST SP 800-82 r3** | ICS/SCADA security | Governs the OT-to-cloud boundary and data diode patterns |
| **NIST SP 800-207** | Zero Trust Architecture | DoD Zero Trust strategy mandates identity-based access, no implicit trust |
| **DOE O 205.1C** | DOE cybersecurity program | DOE-specific overlay for NIST 800-53; applies to DOE facility systems |
| **NERC CIP** (if applicable) | Bulk electric system | Only if the monitored process is part of the electric grid |
| **ICD 503 / CNSSI 1253** | Intelligence community | Only if data is classified (unlikely for process telemetry) |
| **STIG** | Hardening guides | PostgreSQL STIG, Azure STIG, OS STIGs for all VMs |

---

## 2. Architecture Overview

```
 ┌─────────────────────────────────────────────────────────────────┐
 │  LEVEL 2 — OT NETWORK (Plant/Lab)                              │
 │                                                                 │
 │  ┌──────────┐    MQTT/TLS    ┌──────────────┐                   │
 │  │ DAQ      │───(port 8883)──│  Mosquitto   │                   │
 │  │ Service  │                │  Broker      │                   │
 │  │          │                └──────┬───────┘                   │
 │  │ cRIO     │                       │                           │
 │  │ Opto22   │                       │                           │
 │  │ CFP      │                       │                           │
 │  └──────────┘                       │                           │
 │                                     │                           │
 │  ┌──────────────────────────────────┴───────────┐               │
 │  │  Azure Uploader Service                      │               │
 │  │  (SQLite relay mode for DMZ deployment)      │               │
 │  │  Reads historian.db → batches → Azure        │               │
 │  └──────────────────────────┬───────────────────┘               │
 │                             │                                   │
 └─────────────────────────────┼───────────────────────────────────┘
                               │ HTTPS/AMQPS (TLS 1.2+, FIPS 140-2)
                               │ Outbound ONLY — no inbound from cloud
 ┌─────────────────────────────┼───────────────────────────────────┐
 │  DMZ / FIREWALL             │                                   │
 │  (Application-level gateway │  Allow: 443/5671 outbound to     │
 │   or data diode)            │  Azure Government endpoints ONLY  │
 └─────────────────────────────┼───────────────────────────────────┘
                               │
 ┌─────────────────────────────▼───────────────────────────────────┐
 │  AZURE GOVERNMENT CLOUD (FedRAMP High)                          │
 │                                                                 │
 │  ┌─────────────────────────────────────────────────────────┐    │
 │  │  Resource Group: rg-nisystem-prod                       │    │
 │  │  Region: USGov Virginia / USGov Arizona                 │    │
 │  │                                                         │    │
 │  │  ┌───────────────┐      ┌──────────────────────┐        │    │
 │  │  │ Azure IoT Hub │      │ Azure Stream         │        │    │
 │  │  │ (S1 Standard) │─────▶│ Analytics / Azure    │        │    │
 │  │  │               │      │ Functions            │        │    │
 │  │  │ • Device auth │      │                      │        │    │
 │  │  │ • X.509 or    │      │ • Decode batches     │        │    │
 │  │  │   SAS tokens  │      │ • Validate schema    │        │    │
 │  │  │ • Message     │      │ • Route telemetry    │        │    │
 │  │  │   routing     │      │   vs safety events   │        │    │
 │  │  └───────────────┘      └──────────┬───────────┘        │    │
 │  │                                    │                    │    │
 │  │                         ┌──────────▼───────────┐        │    │
 │  │                         │ Azure Database for   │        │    │
 │  │                         │ PostgreSQL           │        │    │
 │  │                         │ (Flexible Server)    │        │    │
 │  │                         │                      │        │    │
 │  │                         │ • FIPS 140-2 at rest │        │    │
 │  │                         │ • TLS 1.2+ in transit│        │    │
 │  │                         │ • Private endpoint   │        │    │
 │  │                         │ • pgAudit extension  │        │    │
 │  │                         │ • TimescaleDB ext    │        │    │
 │  │                         └──────────┬───────────┘        │    │
 │  │                                    │                    │    │
 │  │                         ┌──────────▼───────────┐        │    │
 │  │                         │ Grafana              │        │    │
 │  │                         │ (Azure-hosted or     │        │    │
 │  │                         │  Grafana Cloud Gov)  │        │    │
 │  │                         │                      │        │    │
 │  │                         │ • Azure AD/Entra auth│        │    │
 │  │                         │ • RBAC dashboards    │        │    │
 │  │                         │ • TLS-only access    │        │    │
 │  │                         └──────────────────────┘        │    │
 │  │                                                         │    │
 │  │  ┌──────────────────────────────────────────────┐       │    │
 │  │  │ Supporting Services                          │       │    │
 │  │  │ • Azure Key Vault (secrets, certs, CMK)      │       │    │
 │  │  │ • Azure Monitor / Log Analytics              │       │    │
 │  │  │ • Microsoft Defender for Cloud               │       │    │
 │  │  │ • Azure Policy (compliance enforcement)      │       │    │
 │  │  │ • Microsoft Entra ID (identity provider)     │       │    │
 │  │  └──────────────────────────────────────────────┘       │    │
 │  └─────────────────────────────────────────────────────────┘    │
 └─────────────────────────────────────────────────────────────────┘
```

---

## 3. Component Specifications

### 3.1 Azure IoT Hub (Device Ingestion)

| Setting | Value | Rationale |
|---------|-------|-----------|
| **Cloud** | Azure Government | FedRAMP High boundary; required for DoD/DOE |
| **SKU** | S1 Standard (or S2/S3 for throughput) | Supports message routing, device twins, file upload |
| **Authentication** | X.509 certificates (preferred) or SAS tokens with ≤1h expiry | Security Compliance §3.5.3 — authenticator management |
| **Protocol** | AMQPS (port 5671) or HTTPS (port 443) | TLS 1.2+ mandatory; MQTT-over-TLS also supported |
| **IP Filtering** | Restrict to plant egress IP(s) | Defense in depth — even with device auth |
| **Message Routing** | Route `messageType=telemetry` → Stream Analytics → PostgreSQL | Route `messageType=safety_event` → Event Hub → alert pipeline |
| **DPS** | Azure Device Provisioning Service with X.509 enrollment group | Zero-touch provisioning for multi-site |
| **Diagnostic Logging** | Enabled → Log Analytics workspace | NIST 800-53 AU-2, AU-3 (audit events) |

**Device Identity Format** (matches existing Azure uploader):
```
{HOSTNAME}_ICCSFlux_{node_id}
Example: BOILER-LAB-PC_ICCSFlux_node-001
```

### 3.2 Azure Stream Analytics / Azure Functions (Processing)

Transforms raw IoT Hub messages into PostgreSQL-ready rows.

```sql
-- Stream Analytics query example
SELECT
    GetMetadataPropertyValue(IoTHub, '[IoTHub].[ConnectionDeviceId]') AS device_id,
    data.ArrayElement.timestamp AS ts,
    data.ArrayElement.node_id AS node_id,
    data.ArrayElement.values AS channel_values,
    data.ArrayElement.safety_event AS is_safety_event,
    EventProcessedUtcTime AS ingested_at
INTO [postgresql-output]
FROM [iothub-input] TIMESTAMP BY EventEnqueuedUtcTime
CROSS APPLY GetArrayElements(data) AS data
```

**Or Azure Functions (Python)** for more control:
- Validate message schema (reject malformed payloads)
- Flatten batch → individual channel rows
- Apply quality codes (NaN → NULL, mark stale)
- Write to PostgreSQL via connection pool (asyncpg)
- Dead-letter failed messages to Storage Queue

| Setting | Value |
|---------|-------|
| **Runtime** | Python 3.11+ on Azure Functions v4 |
| **Plan** | Premium (EP1) — VNet integration required |
| **VNet** | Same VNet as PostgreSQL private endpoint |
| **Identity** | System-assigned Managed Identity (no passwords in code) |
| **Key Vault** | Connection strings stored in Key Vault, accessed via MI |

### 3.3 Azure Database for PostgreSQL — Flexible Server

| Setting | Value | Standard |
|---------|-------|----------|
| **Cloud** | Azure Government | FedRAMP High |
| **SKU** | General Purpose D4s_v3 (4 vCores, 16 GB) — scale as needed | — |
| **Storage** | 256 GB SSD, auto-grow enabled | — |
| **HA** | Zone-redundant HA (synchronous standby) | NIST 800-53 CP-6, CP-7 |
| **Version** | PostgreSQL 16 | Latest stable |
| **Encryption at Rest** | AES-256, customer-managed key (CMK) via Key Vault | FIPS 140-2, Security Compliance §3.13.16 |
| **Encryption in Transit** | TLS 1.2+ enforced (`ssl_min_protocol_version = TLSv1.2`) | FIPS 140-2, Security Compliance §3.13.8 |
| **Network** | Private Endpoint only (no public access) | Security Compliance §3.13.1, Zero Trust |
| **Authentication** | Microsoft Entra ID (Azure AD) + pgAudit | NIST 800-53 IA-2 (MFA), AC-2 |
| **Backup** | Geo-redundant, 35-day retention, PITR | NIST 800-53 CP-9 |
| **Extensions** | `pgAudit`, `TimescaleDB` (if hypertable needed), `pg_stat_statements` | AU-2, AU-3 |

#### 3.3.1 Database Schema

```sql
-- ─── Telemetry Schema ──────────────────────────────────────────
CREATE SCHEMA telemetry;

-- Devices / data sources
CREATE TABLE telemetry.devices (
    device_id       TEXT PRIMARY KEY,        -- BOILER-LAB-PC_ICCSFlux_node-001
    hostname        TEXT NOT NULL,
    node_id         TEXT NOT NULL,
    first_seen      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen       TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata        JSONB DEFAULT '{}'       -- firmware version, config hash, etc.
);

-- Channel registry (auto-populated from first telemetry)
CREATE TABLE telemetry.channels (
    id              SERIAL PRIMARY KEY,
    device_id       TEXT NOT NULL REFERENCES telemetry.devices(device_id),
    channel_name    TEXT NOT NULL,
    unit            TEXT DEFAULT '',
    channel_type    TEXT DEFAULT '',          -- thermocouple, rtd, voltage_input, etc.
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (device_id, channel_name)
);

-- Time-series data (partitioned by time — TimescaleDB hypertable or native partitioning)
CREATE TABLE telemetry.datapoints (
    ts              TIMESTAMPTZ NOT NULL,
    channel_id      INTEGER NOT NULL REFERENCES telemetry.channels(id),
    value           DOUBLE PRECISION,
    quality         SMALLINT DEFAULT 0,       -- 0=GOOD, 1=UNCERTAIN, 2=BAD, 3=COMM_FAIL
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now()
) PARTITION BY RANGE (ts);

-- Create monthly partitions (or use TimescaleDB: SELECT create_hypertable(...))
CREATE TABLE telemetry.datapoints_2026_01 PARTITION OF telemetry.datapoints
    FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');
CREATE TABLE telemetry.datapoints_2026_02 PARTITION OF telemetry.datapoints
    FOR VALUES FROM ('2026-02-01') TO ('2026-03-01');
-- ... auto-create via pg_partman or cron

CREATE INDEX idx_datapoints_ts ON telemetry.datapoints (ts);
CREATE INDEX idx_datapoints_channel_ts ON telemetry.datapoints (channel_id, ts);

-- ─── Safety / Alarm Events Schema ─────────────────────────────
CREATE SCHEMA safety;

CREATE TABLE safety.events (
    id              BIGSERIAL PRIMARY KEY,
    ts              TIMESTAMPTZ NOT NULL,
    device_id       TEXT NOT NULL,
    event_type      TEXT NOT NULL,            -- alarm, alarm_cleared, safety_trip, safety_action
    severity        TEXT,                     -- CRITICAL, HIGH, MEDIUM, LOW
    alarm_id        TEXT,
    channel_name    TEXT,
    threshold_type  TEXT,                     -- high_high, high, low, low_low, rate_of_change
    details         JSONB NOT NULL DEFAULT '{}',
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_safety_events_ts ON safety.events (ts);
CREATE INDEX idx_safety_events_device ON safety.events (device_id, ts);
CREATE INDEX idx_safety_events_type ON safety.events (event_type, ts);

-- ─── Audit Schema (cloud-side audit trail) ────────────────────
CREATE SCHEMA audit;

CREATE TABLE audit.access_log (
    id              BIGSERIAL PRIMARY KEY,
    ts              TIMESTAMPTZ NOT NULL DEFAULT now(),
    user_id         TEXT NOT NULL,            -- Entra ID principal
    action          TEXT NOT NULL,            -- query, dashboard_view, export, config_change
    resource        TEXT NOT NULL,            -- table name, dashboard UID, etc.
    details         JSONB DEFAULT '{}',
    source_ip       INET,
    session_id      TEXT
);

-- ─── Data Retention Policy ────────────────────────────────────
-- Full resolution: 90 days (configurable per contract)
-- 1-minute aggregates: 2 years
-- 1-hour aggregates: 7 years (DOE records retention)
-- Safety events: 7 years (never aggregated)

CREATE TABLE telemetry.datapoints_1min (
    ts              TIMESTAMPTZ NOT NULL,
    channel_id      INTEGER NOT NULL,
    avg_value       DOUBLE PRECISION,
    min_value       DOUBLE PRECISION,
    max_value       DOUBLE PRECISION,
    sample_count    INTEGER,
    quality_worst   SMALLINT DEFAULT 0
) PARTITION BY RANGE (ts);

CREATE TABLE telemetry.datapoints_1hr (
    ts              TIMESTAMPTZ NOT NULL,
    channel_id      INTEGER NOT NULL,
    avg_value       DOUBLE PRECISION,
    min_value       DOUBLE PRECISION,
    max_value       DOUBLE PRECISION,
    sample_count    INTEGER,
    quality_worst   SMALLINT DEFAULT 0
) PARTITION BY RANGE (ts);
```

#### 3.3.2 PostgreSQL Hardening (per DISA STIG)

```ini
# postgresql.conf — STIG-aligned settings
ssl = on
ssl_min_protocol_version = 'TLSv1.2'
ssl_ciphers = 'TLS_AES_256_GCM_SHA384:TLS_AES_128_GCM_SHA256:ECDHE-RSA-AES256-GCM-SHA384'
password_encryption = scram-sha-256
log_connections = on
log_disconnections = on
log_statement = 'ddl'                    # Log all DDL
log_line_prefix = '%m [%p] %q%u@%d '
pgaudit.log = 'read,write,ddl,role'      # Full audit via pgAudit
pgaudit.log_catalog = off
pgaudit.log_parameter = on
pgaudit.log_statement_once = on
shared_preload_libraries = 'pgaudit'
```

#### 3.3.3 Role-Based Access Control

```sql
-- Service account: Azure Function writes telemetry (Managed Identity)
CREATE ROLE nisystem_ingestion LOGIN;
GRANT USAGE ON SCHEMA telemetry, safety TO nisystem_ingestion;
GRANT INSERT ON ALL TABLES IN SCHEMA telemetry TO nisystem_ingestion;
GRANT INSERT ON ALL TABLES IN SCHEMA safety TO nisystem_ingestion;
GRANT SELECT ON telemetry.channels, telemetry.devices TO nisystem_ingestion;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA telemetry TO nisystem_ingestion;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA safety TO nisystem_ingestion;

-- Grafana service account: read-only (Managed Identity)
CREATE ROLE grafana_reader LOGIN;
GRANT USAGE ON SCHEMA telemetry, safety, audit TO grafana_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA telemetry TO grafana_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA safety TO grafana_reader;
GRANT SELECT ON audit.access_log TO grafana_reader;

-- DBA: admin with audit (Entra ID, MFA required)
CREATE ROLE nisystem_dba LOGIN;
GRANT ALL ON SCHEMA telemetry, safety, audit TO nisystem_dba;

-- Analyst: read telemetry + export (Entra ID, MFA required)
CREATE ROLE nisystem_analyst LOGIN;
GRANT USAGE ON SCHEMA telemetry, safety TO nisystem_analyst;
GRANT SELECT ON ALL TABLES IN SCHEMA telemetry TO nisystem_analyst;
GRANT SELECT ON ALL TABLES IN SCHEMA safety TO nisystem_analyst;
```

### 3.4 Grafana (Visualization)

| Setting | Value | Standard |
|---------|-------|----------|
| **Deployment** | Azure-hosted Grafana (Azure Managed Grafana) or self-hosted on AKS behind App Gateway | FedRAMP boundary |
| **Authentication** | Microsoft Entra ID (SSO + MFA) | Security Compliance §3.5.3, §3.7 |
| **Authorization** | Org-level RBAC: Viewer / Editor / Admin mapped to Entra groups | AC-2, AC-3, AC-6 |
| **Network** | Private endpoint or VNet-integrated; public access via Azure Front Door with WAF | SC-7 |
| **TLS** | TLS 1.2+ only, certificate from Azure-managed PKI | SC-8 |
| **Data Source** | PostgreSQL via private endpoint (Managed Identity auth, no password) | SC-28 |
| **Alerting** | Grafana alerting → Azure Monitor Action Groups → email/Teams/PagerDuty | — |
| **Dashboard Provisioning** | Infrastructure-as-Code (Terraform + JSON dashboard models in git) | CM-2, CM-3 |

#### 3.4.1 Dashboard Layout for DoD/DOE Viewers

```
┌─────────────────────────────────────────────────────────────┐
│  ICCSFlux Operational Dashboard                    [Org/Site]│
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─── System Health ────┐  ┌─── Active Alarms ───────────┐ │
│  │ Device: ONLINE ●     │  │ HiHi: TC-01 > 500°C  [ACK] │ │
│  │ Channels: 48 / 48    │  │ COMM_FAIL: RTD-03    [VIEW] │ │
│  │ Last update: 2s ago  │  │                              │ │
│  └──────────────────────┘  └──────────────────────────────┘ │
│                                                             │
│  ┌─── Temperature Trends (24h) ─────────────────────────┐  │
│  │  TC-01 ████████████████████▓▓▓▓░░░░░░░ 423°C         │  │
│  │  TC-02 ██████████████████████████████░░ 389°C         │  │
│  │  RTD-01 █████████████████████████░░░░░ 72°C           │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌─── Safety Event Log ─────────────────────────────────┐  │
│  │ 2026-02-25 14:32:01  TRIP  Interlock_High_Temp       │  │
│  │ 2026-02-25 14:32:01  ACTION  set_output Heater=OFF   │  │
│  │ 2026-02-25 14:35:22  RESET  Operator: jsmith         │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌─── Data Quality ────┐  ┌─── Ingestion Metrics ──────┐  │
│  │ Good: 98.2%         │  │ Points/min: 2,880          │  │
│  │ Uncertain: 1.1%     │  │ Latency (p99): 4.2s        │  │
│  │ Bad/CommFail: 0.7%  │  │ Queue depth: 0             │  │
│  └─────────────────────┘  └────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. Security Controls Matrix

### 4.1 Data Protection

| Layer | At Rest | In Transit | Standard |
|-------|---------|------------|----------|
| **Plant → Azure IoT Hub** | N/A (streaming) | TLS 1.2+ (AMQPS/HTTPS), FIPS 140-2 validated | 800-171 §3.13.8 |
| **IoT Hub → Function** | Azure-managed encryption | Internal Azure backbone (encrypted) | 800-53 SC-28 |
| **Function → PostgreSQL** | AES-256 CMK (Key Vault) | TLS 1.2+ (private endpoint) | 800-171 §3.13.16, FIPS 140-2 |
| **PostgreSQL → Grafana** | AES-256 CMK | TLS 1.2+ (private endpoint) | 800-53 SC-8, SC-28 |
| **PostgreSQL backups** | AES-256 (geo-redundant, CMK) | TLS 1.2+ to paired region | 800-53 CP-9, SC-28 |

### 4.2 Identity & Access (Zero Trust)

| Requirement | Implementation | Standard |
|-------------|----------------|----------|
| **Multi-factor authentication** | Entra ID Conditional Access — MFA for all human users | 800-171 §3.5.3 |
| **Service-to-service auth** | Managed Identity (no passwords/keys stored) | 800-207 Zero Trust |
| **Device auth** | X.509 certificates enrolled via DPS | 800-53 IA-3 |
| **Least privilege** | PostgreSQL roles per §3.3.3; Grafana RBAC; Azure RBAC | 800-53 AC-6 |
| **Session management** | Entra token lifetime ≤1h, idle timeout 15min | 800-53 AC-12 |
| **Privileged access** | PIM (Privileged Identity Management) for DBA role | 800-53 AC-2(7) |

### 4.3 Network Segmentation

| Zone | Resources | Access |
|------|-----------|--------|
| **OT Network (Level 2)** | DAQ, MQTT, Azure Uploader | Outbound HTTPS/AMQPS only; no inbound from cloud |
| **DMZ / Firewall** | Application gateway or data diode | Allows only Azure Government endpoint IPs outbound |
| **Azure VNet** | IoT Hub, Functions, PostgreSQL, Grafana | Private endpoints; no public IPs on data path |
| **Internet** | Grafana front-end (if DoD/DOE users access remotely) | Azure Front Door + WAF + Entra auth; IP allowlisting optional |

```
OT Network ──(outbound only)──▶ DMZ/FW ──▶ Azure Gov VNet
                                              │
                                              ├── Subnet: ingestion (Functions)
                                              ├── Subnet: data (PostgreSQL PE)
                                              ├── Subnet: visualization (Grafana)
                                              └── Subnet: management (Key Vault, Monitor)
```

### 4.4 Audit & Logging

| What | Where | Retention | Standard |
|------|-------|-----------|----------|
| **IoT Hub operations** | Azure Monitor → Log Analytics | 1 year (active) + 6 years (archive) | AU-2, AU-3 |
| **PostgreSQL queries** | pgAudit → Log Analytics | 1 year active + archive | AU-2, AU-3, AU-12 |
| **Grafana access** | Grafana audit log → Log Analytics | 1 year | AC-2, AU-2 |
| **Entra sign-ins** | Entra ID audit logs | 1 year active + archive | IA-2, AU-2 |
| **Network flows** | NSG flow logs → Log Analytics | 90 days | AU-12, SI-4 |
| **Key Vault access** | Key Vault diagnostics → Log Analytics | 1 year | AU-2, SC-12 |
| **Plant-side audit** | audit_trail.py SHA-256 JSONL chain | 1 year on-site + cloud copy | 21 CFR Part 11 |

All logs centralized in a **single Log Analytics workspace** for SIEM correlation. Microsoft Sentinel recommended for automated threat detection.

### 4.5 FIPS 140-2 Compliance Chain

| Component | FIPS Module | Status |
|-----------|-------------|--------|
| Azure IoT Hub TLS | Windows CNG / SymCrypt | FIPS 140-2 Level 1 validated |
| Azure PostgreSQL TLS | OpenSSL (FIPS mode) | FIPS 140-2 Level 1 validated |
| Azure Storage encryption | Azure Storage Encryption Service | FIPS 140-2 Level 1 validated |
| Azure Key Vault (CMK) | HSM-backed keys (Premium SKU) | **FIPS 140-2 Level 2** (HSM) or Level 3 (mHSM) |
| Plant-side TLS (Mosquitto) | OpenSSL | Requires FIPS-validated build if CUI |

---

## 5. Data Flow Sequence

```
1. DAQ Service scan loop (10 Hz) reads hardware
2. Values published to MQTT at ≤4 Hz (rate-limited)
3. Historian writes 1 Hz snapshots to local SQLite
4. Azure Uploader batches data (configurable interval, default 1s)
5. Uploader sends to Azure IoT Hub via AMQPS (TLS 1.2+)
   ├── Telemetry messages → default route → Stream Analytics / Function
   └── Safety events → custom route → Event Hub → alert pipeline
6. Function flattens batch → individual rows
7. Function writes to PostgreSQL via private endpoint (Managed Identity)
8. PostgreSQL stores in partitioned hypertable
9. Grafana queries PostgreSQL via private endpoint (Managed Identity)
10. DoD/DOE users access Grafana via Entra SSO + MFA
```

**Latency budget** (plant event → Grafana dashboard):

| Hop | Typical Latency |
|-----|----------------|
| Hardware → MQTT → Azure Uploader queue | <250 ms |
| Azure Uploader batch + send | 1-5 s (configurable) |
| IoT Hub → Function processing | 1-3 s |
| Function → PostgreSQL write | <100 ms |
| Grafana auto-refresh (polling) | 5-30 s (configurable) |
| **Total end-to-end** | **~7-40 seconds** |

For safety events: force-flush bypasses batching, reducing to ~3-10 seconds.

---

## 6. Data Retention & Compliance

| Data Tier | Resolution | Retention | Storage | Compliance |
|-----------|------------|-----------|---------|------------|
| **Raw telemetry** | 1 Hz (all channels) | 90 days | PostgreSQL partitions | DOE O 205.1C |
| **1-minute rollups** | min/max/avg per channel | 2 years | PostgreSQL rollup table | NIST 800-53 AU-11 |
| **1-hour rollups** | min/max/avg per channel | 7 years | PostgreSQL rollup table | DOE records schedule |
| **Safety events** | Full detail | 7 years minimum | PostgreSQL (never aggregated) | IEC 61511, 21 CFR 11 |
| **Audit logs** | Full detail | 7 years | Log Analytics → cold storage | NIST 800-53 AU-11 |
| **Backups** | PITR snapshots | 35 days (active) | Azure geo-redundant backup | NIST 800-53 CP-9 |

Aggregation jobs (pg_cron or Azure Function on schedule):
```sql
-- 1-minute rollup (runs every minute)
INSERT INTO telemetry.datapoints_1min (ts, channel_id, avg_value, min_value, max_value, sample_count, quality_worst)
SELECT
    date_trunc('minute', ts) AS ts,
    channel_id,
    avg(value),
    min(value),
    max(value),
    count(*),
    max(quality)
FROM telemetry.datapoints
WHERE ts >= now() - interval '2 minutes'
  AND ts < date_trunc('minute', now())
GROUP BY 1, 2
ON CONFLICT DO NOTHING;
```

---

## 7. Disaster Recovery & Availability

| Component | RPO | RTO | Mechanism |
|-----------|-----|-----|-----------|
| **PostgreSQL** | <5 min | <1 hour | Zone-redundant HA + geo-redundant backup |
| **IoT Hub** | 0 (regional HA) | <10 min | Azure-managed failover |
| **Azure Functions** | 0 (stateless) | <5 min | Multi-zone deployment |
| **Grafana** | N/A (stateless views) | <15 min | Redeploy from IaC |
| **Plant-side** | 0 (local SQLite historian) | Independent of cloud | Continues operating if cloud is down |

**Critical**: The plant-side DAQ service operates independently of the cloud. If Azure is unreachable, the Azure Uploader queues locally (up to 10,000 messages). The SQLite historian retains 30 days of full-resolution data on-site regardless of cloud status.

---

## 8. Infrastructure-as-Code

Deploy via Terraform (recommended) or Bicep. Store in version control alongside ICCSFlux.

```hcl
# Example Terraform structure
terraform/
  main.tf                    # Provider config (azurerm, azuread)
  variables.tf               # Environment-specific vars
  iot_hub.tf                 # IoT Hub + DPS + message routes
  postgresql.tf              # Flexible Server + private endpoint + extensions
  functions.tf               # Function App + VNet integration
  grafana.tf                 # Managed Grafana + data source
  networking.tf              # VNet, subnets, NSGs, private DNS zones
  keyvault.tf                # Key Vault + CMK + access policies
  monitoring.tf              # Log Analytics, diagnostic settings, Sentinel
  policy.tf                  # Azure Policy assignments (CIS, NIST 800-53)
  entra.tf                   # App registrations, groups, role assignments
```

Azure Policy assignments to enforce at the subscription level:
- **NIST SP 800-53 r5** initiative (built-in)
- **FedRAMP High** initiative (built-in)
- **CIS Azure Benchmark** (supplemental)
- Custom policies: deny public endpoints, require CMK, enforce TLS 1.2

---

## 9. Compliance Mapping Summary

| Security Compliance Family | Key Controls | How This Architecture Meets Them |
|---------------------|-------------|----------------------------------|
| **3.1 Access Control** | AC-2, AC-3, AC-6 | Entra ID + MFA, PostgreSQL RBAC, Grafana RBAC, Managed Identity |
| **3.3 Audit** | AU-2, AU-3, AU-6, AU-11 | pgAudit, Log Analytics, Sentinel, 7-year retention |
| **3.4 Config Mgmt** | CM-2, CM-3, CM-8 | IaC (Terraform), Azure Policy, asset inventory via IoT Hub device registry |
| **3.5 Identification** | IA-2, IA-3, IA-5 | Entra MFA (humans), X.509 (devices), Managed Identity (services) |
| **3.8 Media Protection** | MP-2, MP-4 | Azure-managed disk encryption, Key Vault CMK |
| **3.10 Physical** | PE-2, PE-3 | Azure Government data centers (FedRAMP audited) |
| **3.11 Risk Assessment** | RA-3, RA-5 | Defender for Cloud, vulnerability scanning |
| **3.12 Security Assessment** | CA-2, CA-7 | Continuous monitoring via Defender, compliance dashboard |
| **3.13 System & Comm** | SC-7, SC-8, SC-28 | Private endpoints, TLS 1.2+, AES-256 CMK, VNet segmentation |
| **3.14 System Integrity** | SI-2, SI-3, SI-4 | Defender for Cloud, auto-patching (Flexible Server), Sentinel analytics |

---

## 10. Deployment Checklist

- [ ] Provision Azure Government subscription with appropriate clearance
- [ ] Enable NIST 800-53 r5 and FedRAMP High policy initiatives
- [ ] Deploy VNet with private DNS zones (`privatelink.postgres.database.usgovcloudapi.net`)
- [ ] Provision Key Vault (Premium SKU for HSM-backed CMK)
- [ ] Deploy IoT Hub with X.509 enrollment group via DPS
- [ ] Deploy PostgreSQL Flexible Server with private endpoint + CMK + pgAudit
- [ ] Run schema migration (§3.3.1)
- [ ] Deploy Azure Function with VNet integration + Managed Identity
- [ ] Configure IoT Hub message routing → Function
- [ ] Deploy Managed Grafana with Entra SSO
- [ ] Configure Grafana PostgreSQL data source (Managed Identity)
- [ ] Import dashboard JSON models
- [ ] Enable diagnostic logging on all resources → Log Analytics
- [ ] Configure Microsoft Sentinel analytics rules
- [ ] Run NIST 800-53 compliance scan (Defender for Cloud)
- [ ] Generate POA&M for any non-compliant controls
- [ ] Configure Azure Uploader on plant-side with X.509 device cert
- [ ] Validate end-to-end data flow (plant → Grafana)
- [ ] Document SSP (System Security Plan) per NIST 800-18
