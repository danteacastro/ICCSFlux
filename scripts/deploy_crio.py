"""
Deploy cRIO Node V2 to cRIO and restart service.

Usage:
    python scripts/deploy_crio.py [crio_host] [broker_host]

Defaults:
    crio_host:  192.168.1.20
    broker_host: 192.168.1.1

SAFETY: Ensures exactly ONE cRIO process runs at all times.
        Duplicate processes are a split-brain interlock hazard.
"""

import json
import os
import socket
import struct
import subprocess
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)

# Files to deploy (source -> destination on cRIO)
CRIO_MODULE_FILES = [
    '__init__.py', '__main__.py', 'state_machine.py', 'hardware.py',
    'mqtt_interface.py', 'crio_node.py', 'safety.py', 'config.py',
    'channel_types.py', 'script_engine.py', 'audit_trail.py',
]

NISYSTEM_DIR = '/home/admin/nisystem'


def _get_ntp_timestamp(timeout: float = 3.0) -> int:
    """Query pool.ntp.org and return current UTC as a Unix timestamp integer.

    Returns 0 if all servers fail (caller falls back to PC wall clock).
    """
    for server in ('pool.ntp.org', 'time.cloudflare.com', 'time.windows.com'):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(timeout)
            s.sendto(b'\x1b' + 47 * b'\0', (server, 123))
            data, _ = s.recvfrom(1024)
            s.close()
            if len(data) >= 44:
                t = struct.unpack('!I', data[40:44])[0]
                return t - 2208988800  # NTP epoch → Unix epoch
        except Exception:
            pass
    return 0


def run_ssh(host: str, cmd: str, check: bool = True, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run command on cRIO via SSH."""
    result = subprocess.run(
        ['ssh', '-o', 'ConnectTimeout=5', '-o', 'StrictHostKeyChecking=no',
         f'admin@{host}', cmd],
        capture_output=True, text=True, timeout=timeout
    )
    # Filter out the NI Linux RT banner from stderr
    stderr_lines = [l for l in result.stderr.splitlines()
                    if 'NI Linux Real-Time' not in l and l.strip()]
    if check and result.returncode != 0 and stderr_lines:
        print(f"  SSH error: {' '.join(stderr_lines)}")
    return result


def run_scp(host: str, local_path: str, remote_path: str, timeout: int = 30):
    """Copy file to cRIO via SCP."""
    result = subprocess.run(
        ['scp', '-o', 'ConnectTimeout=5', '-o', 'StrictHostKeyChecking=no',
         local_path, f'admin@{host}:{remote_path}'],
        capture_output=True, text=True, timeout=timeout
    )
    if result.returncode != 0:
        stderr = [l for l in result.stderr.splitlines()
                  if 'NI Linux Real-Time' not in l and l.strip()]
        raise RuntimeError(f"SCP failed: {local_path} -> {remote_path}: {' '.join(stderr)}")


def load_mqtt_credentials() -> tuple:
    """Load MQTT credentials from config/mqtt_credentials.json."""
    creds_path = os.path.join(PROJECT_ROOT, 'config', 'mqtt_credentials.json')
    if not os.path.exists(creds_path):
        # Auto-generate
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
        return 8883, True, '/home/admin/nisystem/ca.crt', ca_path
    return 1883, False, '', None


def count_crio_processes(host: str) -> int:
    """Count cRIO-related python processes on the target.

    Uses ps + grep instead of pgrep -f to avoid self-matching.
    The grep -v grep excludes the grep process itself.
    """
    result = run_ssh(host,
        "ps aux | grep 'run_crio_v2.py' | grep -v grep | wc -l",
        check=False)
    try:
        return int(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return 0


def main():
    host = sys.argv[1] if len(sys.argv) > 1 else '192.168.1.20'
    broker = sys.argv[2] if len(sys.argv) > 2 else '192.168.1.1'

    mqtt_user, mqtt_pass = load_mqtt_credentials()
    port, tls_enabled, tls_ca_remote, tls_ca_local = get_tls_settings()

    print("=" * 50)
    print("Deploying cRIO Node V2")
    print(f"  cRIO Host:   {host}")
    print(f"  MQTT Broker: {broker}")
    print(f"  Port:        {port} (TLS={'enabled' if tls_enabled else 'disabled'})")
    print(f"  MQTT Auth:   {mqtt_user or 'anonymous'}")
    print("=" * 50)

    # ── [1/8] SSH connectivity ────────────────────────────────────────────
    print("\n[1/8] Checking SSH connection...")
    result = run_ssh(host, "echo OK", check=False, timeout=10)
    if result.returncode != 0 or 'OK' not in result.stdout:
        print(f"FATAL: SSH connection to {host} failed!")
        sys.exit(1)
    print("  Connected.")

    # NIST 800-171 Phase 2.7: Check for SSH key-based authentication
    key_check = subprocess.run(
        ['ssh', '-o', 'ConnectTimeout=5', '-o', 'StrictHostKeyChecking=no',
         '-o', 'BatchMode=yes', f'admin@{host}', 'echo OK'],
        capture_output=True, text=True, timeout=10
    )
    if key_check.returncode != 0 or 'OK' not in key_check.stdout:
        print("  \u26a0 SSH password authentication detected. For NIST 800-171 compliance,")
        print("    configure SSH key-based authentication and disable password auth on the cRIO.")

    # ── [2/8] SAFETY: Stop ALL cRIO processes ─────────────────────────────
    print("\n[2/8] Stopping ALL cRIO node processes...")
    # Stop init.d services (both old and new)
    run_ssh(host, "/etc/init.d/crio_node stop 2>/dev/null; true", check=False)
    # Kill ALL cRIO-related python processes (belt and suspenders)
    run_ssh(host, (
        "pkill -9 -f 'run_crio_v2.py' 2>/dev/null; "
        "pkill -9 -f 'python3 -m crio_node' 2>/dev/null; "
        "rm -f /var/run/crio_node.pid /var/run/crio_node_v2.pid 2>/dev/null; "
        "true"
    ), check=False)
    time.sleep(2)

    # SAFETY CHECK: Verify zero processes
    proc_count = count_crio_processes(host)
    if proc_count > 0:
        print(f"FATAL: {proc_count} cRIO process(es) still running after kill!")
        run_ssh(host, "pgrep -af 'run_crio_v2.py'", check=False)
        sys.exit(1)
    print("  All processes stopped.")

    # ── [3/8] Check dependencies ──────────────────────────────────────────
    print("\n[3/8] Checking dependencies...")
    deps_ok = True
    vendor_dir = os.path.join(PROJECT_ROOT, 'vendor', 'crio-packages')

    for module, wheel in [
        ('paho.mqtt.client', 'paho_mqtt-2.1.0-py3-none-any.whl'),
        ('numpy', 'numpy-2.2.6-cp312-cp312-manylinux_2_17_x86_64.manylinux2014_x86_64.whl'),
        ('scipy', 'scipy-1.16.3-cp312-cp312-manylinux2014_x86_64.manylinux_2_17_x86_64.whl'),
    ]:
        r = run_ssh(host, f'python3 -c "import {module}" 2>/dev/null', check=False)
        if r.returncode != 0:
            wheel_path = os.path.join(vendor_dir, wheel)
            if os.path.exists(wheel_path):
                print(f"  {module} missing, installing...")
                run_scp(host, wheel_path, f'/tmp/{wheel}')
                run_ssh(host, f'python3 -m pip install /tmp/{wheel} --quiet && rm /tmp/{wheel}')
                deps_ok = False
            else:
                print(f"  WARNING: {module} missing and wheel not found at {wheel_path}")

    # Verify critical dependency
    r = run_ssh(host, 'python3 -c "import paho.mqtt.client" 2>/dev/null', check=False)
    if r.returncode != 0:
        print("FATAL: paho-mqtt not available on cRIO!")
        sys.exit(1)
    if deps_ok:
        print("  All dependencies OK.")

    # Check nidaqmx (informational only)
    r = run_ssh(host, 'python3 -c "import nidaqmx" 2>/dev/null', check=False)
    if r.returncode != 0:
        print("  NOTE: nidaqmx not found — will use mock hardware.")

    # ── [4/8] Clean + deploy files ────────────────────────────────────────
    print("\n[4/8] Deploying files...")
    run_ssh(host, (
        f"rm -rf {NISYSTEM_DIR}/crio_node_v2 {NISYSTEM_DIR}/run_crio_v2.py 2>/dev/null; "
        f"mkdir -p {NISYSTEM_DIR}/crio_node_v2 {NISYSTEM_DIR}/logs"
    ))

    module_dir = os.path.join(PROJECT_ROOT, 'services', 'crio_node_v2')
    for fname in CRIO_MODULE_FILES:
        local = os.path.join(module_dir, fname)
        if os.path.exists(local):
            run_scp(host, local, f'{NISYSTEM_DIR}/crio_node_v2/{fname}')
        else:
            print(f"  WARNING: {fname} not found locally, skipping")
    print(f"  {len(CRIO_MODULE_FILES)} module files deployed.")

    # Deploy runner script
    run_scp(host, os.path.join(SCRIPT_DIR, 'run_crio_v2.py'),
            f'{NISYSTEM_DIR}/run_crio_v2.py')
    run_ssh(host, f'chmod +x {NISYSTEM_DIR}/run_crio_v2.py')
    print("  Runner script deployed.")

    # Deploy TLS CA cert
    if tls_ca_local:
        run_scp(host, tls_ca_local, f'{NISYSTEM_DIR}/ca.crt')
        print("  TLS CA certificate deployed.")
    else:
        print("  WARNING: No TLS CA cert found. cRIO will use plaintext port 1883.")

    # Deploy NTP sync helper (NI Linux RT has no ntpdate/ntpd — uses Python UDP)
    run_scp(host, os.path.join(SCRIPT_DIR, 'ntp_sync.py'),
            f'{NISYSTEM_DIR}/ntp_sync.py')
    run_ssh(host, f'chmod +x {NISYSTEM_DIR}/ntp_sync.py')
    print("  NTP sync helper deployed.")

    # ── [5/8] Write connection config ────────────────────────────────────
    print("\n[5/8] Writing connection config...")
    # Port 8883 is anonymous (TLS-only auth via CA cert) — credentials optional.
    # Always write broker/port/TLS settings; include credentials if available.
    creds = {
        'broker': broker,
        'port': port,
        'tls_enabled': tls_enabled,
        'tls_ca_cert': tls_ca_remote,
        'node_id': 'crio-001',
    }
    if mqtt_user:
        creds['mqtt_user'] = mqtt_user
        creds['mqtt_pass'] = mqtt_pass
    tmp_creds = os.path.join(PROJECT_ROOT, '_crio_creds_tmp.json')
    try:
        with open(tmp_creds, 'w') as f:
            json.dump(creds, f, indent=2)
        run_scp(host, tmp_creds, f'{NISYSTEM_DIR}/mqtt_creds.json')
        run_ssh(host, f'chmod 600 {NISYSTEM_DIR}/mqtt_creds.json')
        auth_info = f"user={mqtt_user}" if mqtt_user else "anonymous"
        print(f"  Config written ({auth_info}, port={port}, TLS={tls_enabled})")
    finally:
        if os.path.exists(tmp_creds):
            os.remove(tmp_creds)

    # Verify on cRIO
    r = run_ssh(host, (
        f'python3 -c "'
        f"import json; d=json.load(open('{NISYSTEM_DIR}/mqtt_creds.json')); "
        f"print('  Verified: broker=' + d.get('broker','?') + ' port=' + str(d.get('port','?')) + ' TLS=' + str(d.get('tls_enabled','?')))"
        f'"'
    ), check=False)
    if r.returncode == 0:
        print(r.stdout.strip())
    else:
        print("  WARNING: Config verification failed on cRIO!")

    # ── [6/9] Verify deployment ───────────────────────────────────────────
    print("\n[6/9] Verifying deployment...")
    r = run_ssh(host, (
        f'python3 -c "'
        f"import sys; sys.path.insert(0, '{NISYSTEM_DIR}'); "
        f"from crio_node_v2.config import ChannelConfig; "
        f"from crio_node_v2.hardware import create_hardware; "
        f"print('  Import check: OK')"
        f'"'
    ), check=False)
    if r.returncode != 0:
        print("FATAL: Import verification failed! Deployment is broken.")
        print(f"  stderr: {r.stderr.strip()}")
        sys.exit(1)
    print(r.stdout.strip())

    # ── [7/9] NTP time sync ────────────────────────────────────────────────
    print("\n[7/9] Correcting cRIO clock...")
    # The cRIO hardware RTC can drift from real UTC. nitsmd (NI Time Sync
    # manager) continuously re-applies the RTC value, so a simple 'date -s'
    # reverts within seconds.  Reliable fix:
    #   1. Obtain authoritative NTP time on the PC (UDP 123 outbound).
    #   2. Stop nitsmd so it stops fighting us.
    #   3. Set system clock + write hardware RTC (hwclock -w).
    #   4. Restart nitsmd — it now reads the corrected RTC as its baseline.
    ntp_ts = _get_ntp_timestamp()
    if ntp_ts:
        ref_ts = ntp_ts
        ref_source = "NTP"
    else:
        # NTP unreachable (firewall) — fall back to PC wall clock.
        # PC clock may drift slightly from UTC but is good enough for logging.
        ref_ts = int(time.time())
        ref_source = "PC clock (NTP unreachable)"

    run_ssh(host, (
        f"/etc/init.d/nitsmd stop 2>/dev/null; "
        f"date -s @{ref_ts} && hwclock -w; "
        f"/etc/init.d/nitsmd start 2>/dev/null; "
        f"true"
    ), check=False)
    print(f"  cRIO clock set from {ref_source} ({ref_ts}).")

    # Verify: read back cRIO time and report offset
    try:
        r = run_ssh(host, "date +%s", check=False)
        lines = [l.strip() for l in r.stdout.splitlines()
                 if l.strip() and 'NI Linux Real-Time' not in l]
        if lines:
            crio_ts = int(lines[0])
            offset = crio_ts - ref_ts
            if abs(offset) <= 5:
                print(f"  Clock verified: cRIO={crio_ts}, ref={ref_ts}, offset={offset:+d}s ✓")
            else:
                print(f"  WARNING: clock offset {offset:+d}s after correction "
                      f"(nitsmd may be syncing to an external PTP reference).")
    except Exception:
        pass

    # Also launch ntp_sync.py in background so the service re-syncs if nitsmd
    # drifts after deploy (runs once at each service restart).
    run_ssh(host,
            f"nohup python3 {NISYSTEM_DIR}/ntp_sync.py >> /var/log/crio_node_v2.log 2>&1 &",
            check=False)
    print(f"  NTP sync helper started in background.")

    # ── [8/9] Install + start init.d service ──────────────────────────────
    print("\n[8/9] Installing and starting init.d service...")

    # Remove deprecated old crio_service (V1) to prevent conflicts
    run_ssh(host, (
        "/etc/init.d/crio_service stop 2>/dev/null; "
        "update-rc.d -f crio_service remove 2>/dev/null; "
        "rm -f /etc/init.d/crio_service 2>/dev/null; "
        "true"
    ), check=False)

    # Deploy the init.d service script
    init_script = os.path.join(SCRIPT_DIR, 'crio_init_service.sh')
    run_scp(host, init_script, '/etc/init.d/crio_node')
    run_ssh(host, 'chmod +x /etc/init.d/crio_node')
    run_ssh(host, 'update-rc.d crio_node defaults 2>/dev/null || true', check=False)

    # Start the service (should return immediately since init.d detaches)
    try:
        r = run_ssh(host, '/etc/init.d/crio_node start', timeout=15)
        for line in r.stdout.strip().splitlines():
            if 'NI Linux Real-Time' not in line:
                print(f"  {line}")
    except subprocess.TimeoutExpired:
        print("  WARNING: init.d start timed out (service may still be starting)")
        # Kill the hung SSH process — the service should still be running on cRIO
        pass

    # Wait for service to initialize
    time.sleep(4)

    # ── [9/9] SAFETY VERIFICATION ─────────────────────────────────────────
    print("\n[9/9] Safety verification...")
    proc_count = count_crio_processes(host)

    if proc_count == 0:
        print("SAFETY FAIL: No cRIO process running!")
        print("  Check logs: ssh admin@{host} 'tail -50 /var/log/crio_node_v2.log'")
        sys.exit(1)
    elif proc_count > 1:
        print(f"SAFETY FAIL: {proc_count} cRIO processes detected — split-brain hazard!")
        r = run_ssh(host, "pgrep -af 'run_crio_v2.py'", check=False)
        print(r.stdout.strip())
        sys.exit(1)
    else:
        r = run_ssh(host, "pgrep -af 'run_crio_v2.py'", check=False)
        proc_info = [l for l in r.stdout.strip().splitlines()
                     if 'NI Linux Real-Time' not in l and l.strip()]
        print(f"  SAFETY OK: Exactly 1 process running")
        if proc_info:
            print(f"  {proc_info[0]}")

    # ── Done ──────────────────────────────────────────────────────────────
    print("\n" + "=" * 50)
    print("Deployment complete!")
    print(f"  Service managed by: /etc/init.d/crio_node")
    print(f"  Logs: ssh admin@{host} 'tail -f /var/log/crio_node_v2.log'")
    print("=" * 50)


if __name__ == '__main__':
    main()
