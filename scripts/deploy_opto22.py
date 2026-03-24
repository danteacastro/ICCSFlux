"""
Deploy Opto22 Node to groov EPIC and restart service.

Usage:
    python scripts/deploy_opto22.py [epic_host] [broker_host]

Defaults:
    epic_host:   192.168.1.30
    broker_host: 192.168.1.1

SAFETY: Ensures exactly ONE Opto22 node process runs at all times.
        Duplicate processes are a split-brain interlock hazard.

The groov EPIC runs Linux (Debian-based), so we use systemd for service
management (unlike cRIO which uses init.d).
"""

import json
import os
import subprocess
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)

# Files to deploy (source -> destination on EPIC)
OPTO22_MODULE_FILES = [
    '__init__.py', 'state_machine.py', 'hardware.py',
    'mqtt_interface.py', 'opto22_node.py', 'safety.py', 'config.py',
    'channel_types.py', 'script_engine.py', 'audit_trail.py',
    'pid_engine.py', 'sequence_manager.py', 'trigger_engine.py',
    'watchdog_engine.py', 'codesys_bridge.py',
]

# CODESYS package files
CODESYS_PACKAGE_FILES = [
    'codesys/__init__.py',
    'codesys/register_map.py',
    'codesys/st_codegen.py',
]

DEPLOY_DIR = '/home/dev/nisystem'
DEPLOY_USER = 'dev'

def run_ssh(host: str, cmd: str, user: str = DEPLOY_USER,
            check: bool = True, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run command on EPIC via SSH."""
    result = subprocess.run(
        ['ssh', '-o', 'ConnectTimeout=5', '-o', 'StrictHostKeyChecking=no',
         f'{user}@{host}', cmd],
        capture_output=True, text=True, timeout=timeout
    )
    if check and result.returncode != 0 and result.stderr.strip():
        print(f"  SSH error: {result.stderr.strip()}")
    return result

def run_scp(host: str, local_path: str, remote_path: str,
            user: str = DEPLOY_USER, timeout: int = 30):
    """Copy file to EPIC via SCP."""
    result = subprocess.run(
        ['scp', '-o', 'ConnectTimeout=5', '-o', 'StrictHostKeyChecking=no',
         local_path, f'{user}@{host}:{remote_path}'],
        capture_output=True, text=True, timeout=timeout
    )
    if result.returncode != 0:
        raise RuntimeError(f"SCP failed: {local_path} -> {remote_path}: {result.stderr.strip()}")

def load_mqtt_credentials() -> tuple:
    """Load MQTT credentials from config/mqtt_credentials.json."""
    creds_path = os.path.join(PROJECT_ROOT, 'config', 'mqtt_credentials.json')
    if not os.path.exists(creds_path):
        print("  Generating MQTT credentials...")
        subprocess.run(
            [sys.executable, os.path.join(SCRIPT_DIR, 'mqtt_credentials.py')],
            cwd=PROJECT_ROOT, check=True
        )
    try:
        with open(creds_path) as f:
            d = json.load(f)
        return d['backend']['username'], d['backend']['password']
    except (FileNotFoundError, KeyError, json.JSONDecodeError):
        return None, None

def get_tls_settings() -> tuple:
    """Determine TLS port/settings based on local config/tls/ca.crt."""
    ca_path = os.path.join(PROJECT_ROOT, 'config', 'tls', 'ca.crt')
    if os.path.exists(ca_path):
        return 8883, True, f'{DEPLOY_DIR}/ca.crt', ca_path
    return 1883, False, '', None

def count_opto22_processes(host: str) -> int:
    """Count Opto22 node python processes on the target."""
    result = run_ssh(host,
        "ps aux | grep 'run_opto22.py' | grep -v grep | wc -l",
        check=False)
    try:
        return int(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return 0

def main():
    host = sys.argv[1] if len(sys.argv) > 1 else '192.168.1.30'
    broker = sys.argv[2] if len(sys.argv) > 2 else '192.168.1.1'

    mqtt_user, mqtt_pass = load_mqtt_credentials()
    port, tls_enabled, tls_ca_remote, tls_ca_local = get_tls_settings()

    print("=" * 55)
    print("Deploying Opto22 Node to groov EPIC")
    print(f"  EPIC Host:   {host}")
    print(f"  MQTT Broker: {broker}")
    print(f"  Port:        {port} (TLS={'enabled' if tls_enabled else 'disabled'})")
    print(f"  MQTT Auth:   {mqtt_user or 'anonymous'}")
    print("=" * 55)

    # ── [1/10] SSH connectivity ──────────────────────────────────────────
    print("\n[1/10] Checking SSH connection...")
    result = run_ssh(host, "echo OK", check=False, timeout=10)
    if result.returncode != 0 or 'OK' not in result.stdout:
        print(f"FATAL: SSH connection to {host} failed!")
        print(f"  Ensure SSH is enabled in groov Manage and user '{DEPLOY_USER}' exists.")
        sys.exit(1)
    print("  Connected.")

    key_check = subprocess.run(
        ['ssh', '-o', 'ConnectTimeout=5', '-o', 'StrictHostKeyChecking=no',
         '-o', 'BatchMode=yes', f'{DEPLOY_USER}@{host}', 'echo OK'],
        capture_output=True, text=True, timeout=10
    )
    if key_check.returncode != 0 or 'OK' not in key_check.stdout:
        print("  \u26a0 SSH password authentication detected. For Security Compliance compliance,")
        print("    configure SSH key-based authentication and disable password auth on the groov EPIC.")

    # ── [2/10] SAFETY: Stop ALL Opto22 processes ─────────────────────────
    print("\n[2/10] Stopping ALL Opto22 node processes...")
    run_ssh(host, "sudo systemctl stop opto22_node 2>/dev/null; true", check=False)
    run_ssh(host, (
        "pkill -9 -f 'run_opto22.py' 2>/dev/null; "
        "pkill -9 -f 'python3 -m opto22_node' 2>/dev/null; "
        "true"
    ), check=False)
    time.sleep(2)

    # SAFETY CHECK: Verify zero processes
    proc_count = count_opto22_processes(host)
    if proc_count > 0:
        print(f"FATAL: {proc_count} Opto22 process(es) still running after kill!")
        run_ssh(host, "ps aux | grep 'run_opto22.py' | grep -v grep", check=False)
        sys.exit(1)
    print("  All processes stopped.")

    # ── [3/10] Check Python 3 ────────────────────────────────────────────
    print("\n[3/10] Checking Python 3...")
    r = run_ssh(host, 'python3 --version', check=False)
    if r.returncode != 0:
        print("FATAL: Python 3 not available on EPIC!")
        sys.exit(1)
    print(f"  {r.stdout.strip()}")

    # ── [4/10] Check dependencies ────────────────────────────────────────
    print("\n[4/10] Checking dependencies...")
    for module in ['paho.mqtt.client']:
        r = run_ssh(host, f'python3 -c "import {module}" 2>/dev/null', check=False)
        if r.returncode != 0:
            print(f"  WARNING: {module} not installed. Install with: pip3 install paho-mqtt")

    # Check pymodbus (for CODESYS bridge — optional)
    r = run_ssh(host, 'python3 -c "import pymodbus" 2>/dev/null', check=False)
    if r.returncode != 0:
        print("  NOTE: pymodbus not found — CODESYS bridge will be unavailable")
    else:
        print("  pymodbus available (CODESYS bridge supported)")

    # ── [5/10] Clean + deploy files ──────────────────────────────────────
    print("\n[5/10] Deploying files...")
    run_ssh(host, (
        f"rm -rf {DEPLOY_DIR}/opto22_node {DEPLOY_DIR}/run_opto22.py 2>/dev/null; "
        f"mkdir -p {DEPLOY_DIR}/opto22_node/codesys/templates {DEPLOY_DIR}/logs"
    ))

    module_dir = os.path.join(PROJECT_ROOT, 'services', 'opto22_node')
    deployed_count = 0
    for fname in OPTO22_MODULE_FILES:
        local = os.path.join(module_dir, fname)
        if os.path.exists(local):
            run_scp(host, local, f'{DEPLOY_DIR}/opto22_node/{fname}')
            deployed_count += 1
        else:
            print(f"  WARNING: {fname} not found locally, skipping")
    print(f"  {deployed_count} module files deployed.")

    # Deploy CODESYS package
    for fname in CODESYS_PACKAGE_FILES:
        local = os.path.join(module_dir, fname)
        if os.path.exists(local):
            run_scp(host, local, f'{DEPLOY_DIR}/opto22_node/{fname}')

    # Deploy ST templates (for reference — CODESYS imports these manually)
    template_dir = os.path.join(module_dir, 'codesys', 'templates')
    if os.path.isdir(template_dir):
        for fname in os.listdir(template_dir):
            if fname.endswith('.st.j2'):
                run_scp(host, os.path.join(template_dir, fname),
                         f'{DEPLOY_DIR}/opto22_node/codesys/templates/{fname}')
    print("  CODESYS package and templates deployed.")

    # Deploy runner script
    run_scp(host, os.path.join(SCRIPT_DIR, 'run_opto22.py'),
            f'{DEPLOY_DIR}/run_opto22.py')
    run_ssh(host, f'chmod +x {DEPLOY_DIR}/run_opto22.py')
    print("  Runner script deployed.")

    # Deploy TLS CA cert
    if tls_ca_local:
        run_scp(host, tls_ca_local, f'{DEPLOY_DIR}/ca.crt')
        print("  TLS CA certificate deployed.")
    else:
        print("  WARNING: No TLS CA cert found. Node will use plaintext port 1883.")

    # ── [6/10] Write connection config ──────────────────────────────────
    print("\n[6/10] Writing connection config...")
    # Port 8883 is anonymous (TLS-only auth via CA cert) — credentials optional.
    creds = {
        'broker': broker,
        'port': port,
        'tls_enabled': tls_enabled,
        'tls_ca_cert': tls_ca_remote,
        'node_id': 'opto22-001',
    }
    if mqtt_user:
        creds['mqtt_user'] = mqtt_user
        creds['mqtt_pass'] = mqtt_pass
    tmp_creds = os.path.join(PROJECT_ROOT, '_opto22_creds_tmp.json')
    try:
        with open(tmp_creds, 'w') as f:
            json.dump(creds, f, indent=2)
        run_scp(host, tmp_creds, f'{DEPLOY_DIR}/mqtt_creds.json')
        run_ssh(host, f'chmod 600 {DEPLOY_DIR}/mqtt_creds.json')
        auth_info = f"user={mqtt_user}" if mqtt_user else "anonymous"
        print(f"  Config written ({auth_info}, port={port}, TLS={tls_enabled})")
    finally:
        if os.path.exists(tmp_creds):
            os.remove(tmp_creds)

    # ── [7/10] Verify deployment ─────────────────────────────────────────
    print("\n[7/10] Verifying deployment...")
    r = run_ssh(host, (
        f'python3 -c "'
        f"import sys; sys.path.insert(0, '{DEPLOY_DIR}'); "
        f"from opto22_node.config import NodeConfig; "
        f"from opto22_node.state_machine import Opto22StateMachine; "
        f"print('  Import check: OK')"
        f'"'
    ), check=False)
    if r.returncode != 0:
        print("FATAL: Import verification failed! Deployment is broken.")
        print(f"  stderr: {r.stderr.strip()}")
        sys.exit(1)
    print(r.stdout.strip())

    # ── [8/10] Deploy generated ST files (if any) ────────────────────────
    print("\n[8/10] Deploying generated ST files...")
    st_output_dir = os.path.join(PROJECT_ROOT, 'dist', 'codesys_st')
    if os.path.isdir(st_output_dir):
        run_ssh(host, f'mkdir -p {DEPLOY_DIR}/codesys_st')
        st_count = 0
        for fname in os.listdir(st_output_dir):
            if fname.endswith('.st'):
                run_scp(host, os.path.join(st_output_dir, fname),
                         f'{DEPLOY_DIR}/codesys_st/{fname}')
                st_count += 1
        print(f"  {st_count} ST files deployed to {DEPLOY_DIR}/codesys_st/")
        print("  Import these into CODESYS IDE to compile and download to the runtime.")
    else:
        print("  No generated ST files found — run st_codegen to generate them.")

    # ── [9/10] Install + start systemd service ───────────────────────────
    print("\n[9/10] Installing and starting systemd service...")

    # Deploy the systemd service unit file
    service_file = os.path.join(SCRIPT_DIR, 'opto22_init_service.sh')
    if os.path.exists(service_file):
        # The .sh is actually a systemd unit — deploy it
        run_scp(host, service_file, '/tmp/opto22_node.service')
        run_ssh(host, (
            "sudo cp /tmp/opto22_node.service /etc/systemd/system/opto22_node.service; "
            "sudo systemctl daemon-reload; "
            "sudo systemctl enable opto22_node; "
            "rm /tmp/opto22_node.service"
        ))
    else:
        # Create a minimal systemd service inline
        run_ssh(host, f"""cat > /tmp/opto22_node.service << 'UNIT'
[Unit]
Description=ICCSFlux Opto22 Node
After=network.target

[Service]
Type=simple
User={DEPLOY_USER}
WorkingDirectory={DEPLOY_DIR}
ExecStart=/usr/bin/python3 {DEPLOY_DIR}/run_opto22.py --daemon --log-file {DEPLOY_DIR}/logs/opto22_node.log
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
sudo cp /tmp/opto22_node.service /etc/systemd/system/opto22_node.service
sudo systemctl daemon-reload
sudo systemctl enable opto22_node
rm /tmp/opto22_node.service""")

    # Start the service
    run_ssh(host, "sudo systemctl start opto22_node", check=False)
    time.sleep(4)

    # ── [10/10] SAFETY VERIFICATION ──────────────────────────────────────
    print("\n[10/10] Safety verification...")
    proc_count = count_opto22_processes(host)

    if proc_count == 0:
        print("SAFETY FAIL: No Opto22 process running!")
        print(f"  Check logs: ssh {DEPLOY_USER}@{host} 'tail -50 {DEPLOY_DIR}/logs/opto22_node.log'")
        r = run_ssh(host, "sudo journalctl -u opto22_node --no-pager -n 20", check=False)
        if r.stdout.strip():
            print(r.stdout.strip())
        sys.exit(1)
    elif proc_count > 1:
        print(f"SAFETY FAIL: {proc_count} Opto22 processes detected — split-brain hazard!")
        run_ssh(host, "ps aux | grep 'run_opto22.py' | grep -v grep", check=False)
        sys.exit(1)
    else:
        print(f"  SAFETY OK: Exactly 1 process running")

    # ── Done ─────────────────────────────────────────────────────────────
    print("\n" + "=" * 55)
    print("Deployment complete!")
    print(f"  Service managed by: systemctl {{start|stop|status}} opto22_node")
    print(f"  Logs: ssh {DEPLOY_USER}@{host} 'tail -f {DEPLOY_DIR}/logs/opto22_node.log'")
    print(f"  Status: ssh {DEPLOY_USER}@{host} 'sudo systemctl status opto22_node'")
    print("=" * 55)

if __name__ == '__main__':
    main()
