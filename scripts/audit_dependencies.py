#!/usr/bin/env python3
"""
Dependency Security Audit for NISystem

Checks Python and npm dependencies for known CVEs using pip-audit and npm audit.
Produces a JSON report in data/security_scans/.

NIST 800-171 controls:
  SI.L2-3.14.1 — Flaw Remediation
  SI.L2-3.14.3 — Security Alerts & Advisories
  RA.L2-3.11.2 — Vulnerability Scanning

Usage:
    python scripts/audit_dependencies.py           # Run all checks
    python scripts/audit_dependencies.py --python   # Python only
    python scripts/audit_dependencies.py --npm      # npm only
    python scripts/audit_dependencies.py --json     # JSON output to stdout
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = PROJECT_ROOT / "data" / "security_scans"


def run_pip_audit() -> dict:
    """Run pip-audit on the current environment."""
    result = {
        "tool": "pip-audit",
        "timestamp": datetime.now().isoformat(),
        "success": False,
        "vulnerabilities": [],
        "error": None,
    }

    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip_audit", "--format", "json", "--progress-spinner", "off"],
            capture_output=True, text=True, timeout=120,
            cwd=str(PROJECT_ROOT),
        )
        if proc.returncode == 0:
            result["success"] = True
            result["vulnerabilities"] = []
            print("[AUDIT] pip-audit: No vulnerabilities found")
        else:
            # pip-audit returns non-zero when vulnerabilities are found
            try:
                vulns = json.loads(proc.stdout)
                result["vulnerabilities"] = vulns if isinstance(vulns, list) else vulns.get("dependencies", [])
                result["success"] = True
                count = len(result["vulnerabilities"])
                print(f"[AUDIT] pip-audit: {count} vulnerable package(s) found")
                for v in result["vulnerabilities"][:10]:
                    name = v.get("name", "?")
                    version = v.get("version", "?")
                    vulns_list = v.get("vulns", [])
                    for vuln in vulns_list:
                        cve = vuln.get("id", "?")
                        desc = vuln.get("description", "")[:80]
                        print(f"  - {name}=={version}: {cve} — {desc}")
            except json.JSONDecodeError:
                result["error"] = proc.stderr.strip() or proc.stdout.strip()
                print(f"[AUDIT] pip-audit error: {result['error'][:200]}")
    except FileNotFoundError:
        result["error"] = "pip-audit not installed. Install with: pip install pip-audit"
        print(f"[AUDIT] {result['error']}")
    except subprocess.TimeoutExpired:
        result["error"] = "pip-audit timed out after 120s"
        print(f"[AUDIT] {result['error']}")
    except Exception as e:
        result["error"] = str(e)
        print(f"[AUDIT] pip-audit error: {e}")

    return result


def run_npm_audit() -> dict:
    """Run npm audit on the dashboard."""
    result = {
        "tool": "npm-audit",
        "timestamp": datetime.now().isoformat(),
        "success": False,
        "vulnerabilities": [],
        "summary": {},
        "error": None,
    }

    dashboard_dir = PROJECT_ROOT / "dashboard"
    if not (dashboard_dir / "package.json").exists():
        result["error"] = "dashboard/package.json not found"
        print(f"[AUDIT] {result['error']}")
        return result

    try:
        proc = subprocess.run(
            ["npm", "audit", "--json"],
            capture_output=True, text=True, timeout=120,
            cwd=str(dashboard_dir),
            shell=True,
        )
        try:
            data = json.loads(proc.stdout)
            result["success"] = True
            result["summary"] = data.get("metadata", {}).get("vulnerabilities", {})

            # Extract individual advisories
            advisories = data.get("advisories", data.get("vulnerabilities", {}))
            if isinstance(advisories, dict):
                for name, info in advisories.items():
                    severity = info.get("severity", "unknown") if isinstance(info, dict) else "unknown"
                    result["vulnerabilities"].append({
                        "name": name,
                        "severity": severity,
                        "info": info if isinstance(info, dict) else {},
                    })

            total = sum(result["summary"].values()) if result["summary"] else 0
            if total == 0:
                print("[AUDIT] npm audit: No vulnerabilities found")
            else:
                print(f"[AUDIT] npm audit: {total} vulnerability(ies)")
                for sev, count in result["summary"].items():
                    if count > 0:
                        print(f"  - {sev}: {count}")
        except json.JSONDecodeError:
            result["error"] = proc.stderr.strip() or "Failed to parse npm audit output"
            print(f"[AUDIT] npm audit parse error: {result['error'][:200]}")
    except FileNotFoundError:
        result["error"] = "npm not found. Install Node.js."
        print(f"[AUDIT] {result['error']}")
    except subprocess.TimeoutExpired:
        result["error"] = "npm audit timed out after 120s"
        print(f"[AUDIT] {result['error']}")
    except Exception as e:
        result["error"] = str(e)
        print(f"[AUDIT] npm audit error: {e}")

    return result


def run_bandit() -> dict:
    """Run bandit static analysis on Python code."""
    result = {
        "tool": "bandit",
        "timestamp": datetime.now().isoformat(),
        "success": False,
        "issues": [],
        "error": None,
    }

    try:
        proc = subprocess.run(
            [sys.executable, "-m", "bandit", "-r", "services/", "scripts/",
             "-f", "json", "-q", "--severity-level", "medium"],
            capture_output=True, text=True, timeout=300,
            cwd=str(PROJECT_ROOT),
        )
        try:
            data = json.loads(proc.stdout)
            result["success"] = True
            result["issues"] = data.get("results", [])
            count = len(result["issues"])
            if count == 0:
                print("[AUDIT] bandit: No security issues found")
            else:
                print(f"[AUDIT] bandit: {count} issue(s) found")
                for issue in result["issues"][:10]:
                    sev = issue.get("issue_severity", "?")
                    text = issue.get("issue_text", "?")[:80]
                    fname = issue.get("filename", "?")
                    line = issue.get("line_number", "?")
                    print(f"  - [{sev}] {fname}:{line} — {text}")
        except json.JSONDecodeError:
            if proc.returncode == 0:
                result["success"] = True
                result["issues"] = []
                print("[AUDIT] bandit: No security issues found")
            else:
                result["error"] = proc.stderr.strip() or "Failed to parse bandit output"
    except FileNotFoundError:
        result["error"] = "bandit not installed. Install with: pip install bandit"
        print(f"[AUDIT] {result['error']}")
    except subprocess.TimeoutExpired:
        result["error"] = "bandit timed out after 300s"
        print(f"[AUDIT] {result['error']}")
    except Exception as e:
        result["error"] = str(e)
        print(f"[AUDIT] bandit error: {e}")

    return result


def main():
    parser = argparse.ArgumentParser(description="NISystem Dependency Security Audit")
    parser.add_argument("--python", action="store_true", help="Run pip-audit only")
    parser.add_argument("--npm", action="store_true", help="Run npm audit only")
    parser.add_argument("--bandit", action="store_true", help="Run bandit only")
    parser.add_argument("--json", action="store_true", help="Output JSON to stdout")
    args = parser.parse_args()

    run_all = not (args.python or args.npm or args.bandit)

    print("=" * 60)
    print("NISystem Security Audit")
    print(f"Date: {datetime.now().isoformat()}")
    print("=" * 60)

    report = {
        "timestamp": datetime.now().isoformat(),
        "project": "NISystem",
        "results": [],
    }

    if run_all or args.python:
        report["results"].append(run_pip_audit())

    if run_all or args.npm:
        report["results"].append(run_npm_audit())

    if run_all or args.bandit:
        report["results"].append(run_bandit())

    # Summary
    total_vulns = sum(
        len(r.get("vulnerabilities", []) or r.get("issues", []))
        for r in report["results"]
    )
    report["total_findings"] = total_vulns
    report["verdict"] = "PASS" if total_vulns == 0 else "FINDINGS"

    print("\n" + "=" * 60)
    print(f"Total findings: {total_vulns}")
    print(f"Verdict: {report['verdict']}")
    print("=" * 60)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        # Save report
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = REPORT_DIR / f"security_audit_{timestamp}.json"
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2)
        print(f"\nReport saved: {report_path}")

    return 0 if total_vulns == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
