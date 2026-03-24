# NISystem Security Policy

## Responsible Disclosure

If you discover a security vulnerability in NISystem, please report it responsibly.

**Contact:** File a confidential issue or email the system administrator directly.

**Response Timeline:**
- Acknowledgment: within 48 hours
- Initial assessment: within 5 business days
- Fix deployed per severity SLA (see below)

**Safe Harbor:** We will not take legal action against researchers who:
- Make a good faith effort to avoid privacy violations, data destruction, or service disruption
- Report findings promptly and do not publicly disclose before a fix is available

## Patch Management SLAs

| Severity | CVSS Score | Remediation Timeline |
|----------|-----------|---------------------|
| Critical | 9.0-10.0 | 72 hours |
| High | 7.0-8.9 | 30 days |
| Medium | 4.0-6.9 | 90 days |
| Low | 0.1-3.9 | Next release |

## Monitored Dependencies

The following packages are actively monitored for security advisories:

### Python (Backend)

| Package | Advisory Source |
|---------|----------------|
| `paho-mqtt` | [GitHub Security Advisories](https://github.com/eclipse/paho.mqtt.python/security) |
| `cryptography` | [pyca/cryptography Advisories](https://github.com/pyca/cryptography/security/advisories) |
| `bcrypt` | [GitHub Security Advisories](https://github.com/pyca/bcrypt/security) |
| `pymodbus` | [GitHub Security Advisories](https://github.com/pymodbus-dev/pymodbus/security) |
| `pyserial` | [GitHub Security Advisories](https://github.com/pyserial/pyserial/security) |
| `nidaqmx` | [NI Security Center](https://www.ni.com/en/support/security.html) |

### JavaScript (Dashboard)

| Package | Advisory Source |
|---------|----------------|
| `mqtt.js` | [GitHub Security Advisories](https://github.com/mqttjs/MQTT.js/security) |
| `vue` | [Vue.js Security Advisories](https://github.com/vuejs/core/security/advisories) |
| `vite` | [GitHub Security Advisories](https://github.com/vitejs/vite/security) |

### Infrastructure

| Component | Advisory Source |
|-----------|----------------|
| Eclipse Mosquitto | [Mosquitto Security](https://mosquitto.org/security/) |
| NI-DAQmx Runtime | [NI Security Center](https://www.ni.com/en/support/security.html) |

## Automated Scanning

Run the security audit tool:

```bash
# Full audit (pip-audit + npm audit + bandit)
python scripts/audit_dependencies.py

# Python dependencies only
python scripts/audit_dependencies.py --python

# Dashboard dependencies only
python scripts/audit_dependencies.py --npm

# Static analysis only
python scripts/audit_dependencies.py --bandit
```

Reports are saved to `data/security_scans/`.

**Scanning Schedule:**
- Every build: `pip-audit` and `npm audit`
- Weekly: Full scan including `bandit` static analysis
- On dependency update: Re-run full audit before merging

## CVE Tracking Template

When a vulnerability is identified, create a tracking entry:

```
CVE ID:          CVE-YYYY-XXXXX
Severity:        Critical/High/Medium/Low
CVSS Score:      X.X
Affected:        package-name==X.Y.Z
Component:       backend/dashboard/infrastructure
Discovered:      YYYY-MM-DD
Fix Available:   Yes/No (version X.Y.Z)
Fix Applied:     YYYY-MM-DD
Tested:          YYYY-MM-DD
Deployed:        YYYY-MM-DD
Notes:           ...
```

## Deployment Security

### Edge Node SSH Hardening

After deploying to cRIO or Opto22 nodes, harden SSH access:

```bash
# On the edge node — disable password auth after SSH key deployment
# Edit /etc/ssh/sshd_config:
PasswordAuthentication no
PubkeyAuthentication yes
PermitRootLogin no

# Restart SSH daemon
/etc/init.d/sshd restart   # cRIO
systemctl restart sshd      # Opto22 (groov EPIC)
```

The deploy scripts (`deploy_crio_v2.bat`, `deploy_opto22.bat`) will warn if password-based SSH authentication is detected.

### TLS Certificate Management

- Certificates auto-generated on first run (1-year validity per NIST recommendation)
- Private keys restricted to owner-only access (chmod 600 / NTFS ACL)
- Annual renewal recommended — regenerate with: `python scripts/generate_tls_certs.py --force`

### MQTT Authentication

- Credentials auto-generated on first run (PBKDF2-SHA512, 100,000 iterations)
- Credential file restricted to owner-only access
- To regenerate: delete `config/mqtt_credentials.json` and restart

## Compliance References

- NIST SP 800-171 Rev. 2 (Protecting CUI in Nonfederal Systems)
- Security Compliance (Cybersecurity Maturity Model Certification)
- NIST SP 800-132 (PBKDF2 recommendations)
- NIST SP 800-30 (Risk Assessment methodology)

See `docs/NIST_800-171_Compliance_Roadmap.md` for the full compliance matrix.
