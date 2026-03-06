#!/usr/bin/env python3
"""
Systematic cRIO Data Pipeline Diagnostic
=========================================
Tests each stage of the data flow from cRIO hardware to dashboard,
identifying exactly where the pipeline breaks.

Run:  python scripts/test_crio_pipeline.py
      python scripts/test_crio_pipeline.py --test 3   (run specific test)

No browser or DAQ service restart needed. Non-destructive (read-only except
Test 6 which starts/stops acquisition — skippable with --skip-acquire).
"""

import json
import ssl
import sys
import time
import socket
import threading
import argparse
import os
from typing import Dict, List, Optional, Any

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("ERROR: paho-mqtt not installed. Run: pip install paho-mqtt")
    sys.exit(1)


# =============================================================================
# CONFIG
# =============================================================================

BROKER_HOST = "127.0.0.1"
TCP_PORT = 1883
TLS_PORT = 8883
WS_PORT = 9002
CRIO_NODE_ID = "crio-001"
DAQ_NODE_ID = "node-001"
SYSTEM_PREFIX = "nisystem"
CRED_FILE = os.path.join("config", "mqtt_credentials.json")
CA_CERT = os.path.join("config", "tls", "ca.crt")


# =============================================================================
# HELPERS
# =============================================================================

class Colors:
    PASS = "\033[92m"
    FAIL = "\033[91m"
    WARN = "\033[93m"
    INFO = "\033[96m"
    DIM = "\033[90m"
    RESET = "\033[0m"
    BOLD = "\033[1m"


def load_credentials() -> tuple:
    """Load MQTT credentials from config file."""
    try:
        with open(CRED_FILE) as f:
            creds = json.load(f)
        return creds["backend"]["username"], creds["backend"]["password"]
    except (FileNotFoundError, KeyError) as e:
        print(f"  {Colors.WARN}WARNING: Cannot load credentials from {CRED_FILE}: {e}{Colors.RESET}")
        return None, None


def make_tcp_client(client_id: str) -> mqtt.Client:
    """Create authenticated TCP MQTT client for port 1883."""
    user, pwd = load_credentials()
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id)
    if user and pwd:
        c.username_pw_set(user, pwd)
    return c


def make_tls_client(client_id: str) -> mqtt.Client:
    """Create TLS MQTT client for port 8883."""
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id)
    if os.path.exists(CA_CERT):
        c.tls_set(ca_certs=CA_CERT, cert_reqs=ssl.CERT_NONE)
        c.tls_insecure_set(True)
    else:
        c.tls_set(cert_reqs=ssl.CERT_NONE)
        c.tls_insecure_set(True)
    return c


def make_ws_client(client_id: str) -> mqtt.Client:
    """Create WebSocket MQTT client for port 9002."""
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id, transport="websockets")
    c.ws_set_options(path="/")
    return c


def collect_messages(client: mqtt.Client, host: str, port: int, topics: list,
                     duration: float = 5.0) -> List[dict]:
    """Connect, subscribe, collect messages for duration, disconnect."""
    results = []
    connected = threading.Event()

    def on_connect(c, ud, flags, rc, props=None):
        for t, qos in topics:
            c.subscribe(t, qos)
        connected.set()

    def on_msg(c, ud, msg):
        try:
            payload = json.loads(msg.payload)
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = msg.payload.decode("utf-8", errors="replace")[:200]
        results.append({"topic": msg.topic, "payload": payload})

    client.on_connect = on_connect
    client.on_message = on_msg

    try:
        client.connect(host, port, 60)
        client.loop_start()
        if not connected.wait(timeout=5):
            return results  # Connection failed
        time.sleep(duration)
        client.loop_stop()
        client.disconnect()
    except Exception as e:
        print(f"  {Colors.FAIL}Connection error ({host}:{port}): {e}{Colors.RESET}")
    return results


def check_port(host: str, port: int) -> bool:
    """Check if a TCP port is accepting connections."""
    try:
        s = socket.create_connection((host, port), timeout=2)
        s.close()
        return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def print_result(test_num: int, name: str, passed: bool, detail: str = ""):
    icon = f"{Colors.PASS}PASS{Colors.RESET}" if passed else f"{Colors.FAIL}FAIL{Colors.RESET}"
    print(f"\n  [{icon}] Test {test_num}: {name}")
    if detail:
        for line in detail.strip().split("\n"):
            print(f"         {line}")
    return passed


# =============================================================================
# TESTS
# =============================================================================

def test_1_mosquitto_ports() -> bool:
    """Test 1: Verify all Mosquitto ports are listening."""
    print(f"\n{Colors.BOLD}{'='*60}")
    print(f"Test 1: Mosquitto Ports")
    print(f"{'='*60}{Colors.RESET}")

    ports = {TCP_PORT: "TCP (authenticated)", TLS_PORT: "TLS (cRIO)", WS_PORT: "WebSocket (dashboard)"}
    all_ok = True
    details = []
    for port, desc in ports.items():
        ok = check_port(BROKER_HOST, port)
        status = f"{Colors.PASS}UP{Colors.RESET}" if ok else f"{Colors.FAIL}DOWN{Colors.RESET}"
        details.append(f"Port {port} ({desc}): {status}")
        if not ok:
            all_ok = False

    return print_result(1, "Mosquitto Ports", all_ok, "\n".join(details))


def test_2_crio_online() -> dict:
    """Test 2: Check if cRIO is online and its current state."""
    print(f"\n{Colors.BOLD}{'='*60}")
    print(f"Test 2: cRIO Online Status")
    print(f"{'='*60}{Colors.RESET}")

    client = make_tcp_client("diag-t2")
    msgs = collect_messages(client, BROKER_HOST, TCP_PORT,
                            [(f"{SYSTEM_PREFIX}/nodes/{CRIO_NODE_ID}/#", 0)],
                            duration=5.0)

    crio_info = {
        "heartbeat": False, "status": None, "acquiring": None,
        "state": None, "topics": set()
    }

    for m in msgs:
        t = m["topic"]
        crio_info["topics"].add(t.split("/")[-1] if "/" in t else t)

        if "heartbeat" in t:
            crio_info["heartbeat"] = True
        elif "status/system" in t and isinstance(m["payload"], dict):
            crio_info["status"] = m["payload"]
            crio_info["acquiring"] = m["payload"].get("acquiring")
        elif "/state" in t and isinstance(m["payload"], dict):
            crio_info["state"] = m["payload"].get("new_state")

    details = []
    details.append(f"Heartbeat: {'YES' if crio_info['heartbeat'] else 'NO'}")
    details.append(f"Status received: {'YES' if crio_info['status'] else 'NO'}")
    details.append(f"Acquiring: {crio_info['acquiring']}")
    details.append(f"Topics seen: {', '.join(sorted(crio_info['topics']))}")

    passed = crio_info["heartbeat"] and crio_info["status"] is not None
    print_result(2, "cRIO Online", passed, "\n".join(details))
    return crio_info


def test_3_cross_listener_routing() -> dict:
    """Test 3: Verify messages route between all listener pairs."""
    print(f"\n{Colors.BOLD}{'='*60}")
    print(f"Test 3: Cross-Listener Message Routing")
    print(f"{'='*60}{Colors.RESET}")

    test_topic = f"{SYSTEM_PREFIX}/test/routing/{int(time.time())}"
    results = {}

    pairs = [
        ("TCP→WS", TCP_PORT, WS_PORT, make_tcp_client, make_ws_client),
        ("TCP→TLS", TCP_PORT, TLS_PORT, make_tcp_client, make_tls_client),
        ("TLS→TCP", TLS_PORT, TCP_PORT, make_tls_client, make_tcp_client),
        ("TLS→WS", TLS_PORT, WS_PORT, make_tls_client, make_ws_client),
    ]

    for name, pub_port, sub_port, pub_factory, sub_factory in pairs:
        received = threading.Event()
        received_payload = [None]

        def on_connect(c, ud, flags, rc, props=None):
            c.subscribe(test_topic, 1)

        def on_msg(c, ud, msg):
            try:
                received_payload[0] = json.loads(msg.payload)
                received.set()
            except Exception:
                pass

        # Set up subscriber
        sub = sub_factory(f"diag-t3-sub-{name}")
        sub.on_connect = on_connect
        sub.on_message = on_msg
        try:
            sub.connect(BROKER_HOST, sub_port, 60)
            sub.loop_start()
            time.sleep(1)  # Let subscription settle

            # Publish
            pub = pub_factory(f"diag-t3-pub-{name}")
            pub.connect(BROKER_HOST, pub_port, 60)
            pub.loop_start()
            time.sleep(0.5)
            payload = json.dumps({"source": name, "ts": time.time()})
            pub.publish(test_topic, payload, qos=1)
            time.sleep(0.5)

            ok = received.wait(timeout=3)
            results[name] = ok

            pub.loop_stop()
            pub.disconnect()
            sub.loop_stop()
            sub.disconnect()
        except Exception as e:
            results[name] = False
            print(f"  {Colors.FAIL}{name}: Error - {e}{Colors.RESET}")
            try:
                sub.loop_stop()
                sub.disconnect()
            except Exception:
                pass

    details = []
    all_ok = True
    for name, ok in results.items():
        status = f"{Colors.PASS}OK{Colors.RESET}" if ok else f"{Colors.FAIL}BLOCKED{Colors.RESET}"
        details.append(f"{name}: {status}")
        if not ok:
            all_ok = False

    print_result(3, "Cross-Listener Routing", all_ok, "\n".join(details))
    return results


def test_4_crio_command_delivery() -> dict:
    """Test 4: Can we deliver a command to the cRIO and get a response?"""
    print(f"\n{Colors.BOLD}{'='*60}")
    print(f"Test 4: cRIO Command Delivery")
    print(f"{'='*60}{Colors.RESET}")

    results = {"tcp_1883": False, "tls_8883": False}

    for label, port, factory in [
        ("tcp_1883", TCP_PORT, make_tcp_client),
        ("tls_8883", TLS_PORT, make_tls_client),
    ]:
        ack_received = threading.Event()
        status_received = threading.Event()

        def on_connect(c, ud, flags, rc, props=None):
            # Subscribe to both ACK and status topics
            c.subscribe(f"{SYSTEM_PREFIX}/nodes/{CRIO_NODE_ID}/command/ack", 1)
            c.subscribe(f"{SYSTEM_PREFIX}/nodes/{CRIO_NODE_ID}/status/system", 0)

        def on_msg(c, ud, msg):
            if "command/ack" in msg.topic:
                ack_received.set()
            elif "status/system" in msg.topic:
                status_received.set()

        client = factory(f"diag-t4-{label}")
        client.on_connect = on_connect
        client.on_message = on_msg

        try:
            client.connect(BROKER_HOST, port, 60)
            client.loop_start()
            time.sleep(1)

            # Send status request to cRIO
            cmd_topic = f"{SYSTEM_PREFIX}/nodes/{CRIO_NODE_ID}/system/status/request"
            client.publish(cmd_topic, json.dumps({"request_id": f"diag-{label}"}), qos=1)

            # Wait for response
            got_ack = ack_received.wait(timeout=3)
            got_status = status_received.wait(timeout=3)
            results[label] = got_ack or got_status

            client.loop_stop()
            client.disconnect()
        except Exception as e:
            print(f"  {Colors.FAIL}{label}: Connection error - {e}{Colors.RESET}")

    details = []
    for label, ok in results.items():
        status = f"{Colors.PASS}RESPONDED{Colors.RESET}" if ok else f"{Colors.FAIL}NO RESPONSE{Colors.RESET}"
        details.append(f"Command via {label}: {status}")

    any_ok = any(results.values())
    if not any_ok:
        details.append(f"{Colors.WARN}cRIO not responding to commands on any port!{Colors.RESET}")
        details.append(f"Check: is cRIO subscribed? SSH and check logs.")

    print_result(4, "cRIO Command Delivery", any_ok, "\n".join(details))
    return results


def test_5_config_sync() -> dict:
    """Test 5: Check config version sync between DAQ service and cRIO."""
    print(f"\n{Colors.BOLD}{'='*60}")
    print(f"Test 5: Config Push & Sync")
    print(f"{'='*60}{Colors.RESET}")

    client = make_tcp_client("diag-t5")
    msgs = collect_messages(client, BROKER_HOST, TCP_PORT,
                            [(f"{SYSTEM_PREFIX}/nodes/+/status/system", 0)],
                            duration=5.0)

    versions = {}
    for m in msgs:
        if "status/system" not in m["topic"]:
            continue
        parts = m["topic"].split("/")
        try:
            node_id = parts[parts.index("nodes") + 1]
        except (ValueError, IndexError):
            continue
        if isinstance(m["payload"], dict):
            versions[node_id] = {
                "config_version": m["payload"].get("config_version"),
                "acquiring": m["payload"].get("acquiring"),
                "channel_count": m["payload"].get("channel_count"),
            }

    details = []
    for node, info in sorted(versions.items()):
        details.append(f"{node}: version={info['config_version']}, "
                       f"acquiring={info['acquiring']}, channels={info['channel_count']}")

    crio_ver = versions.get(CRIO_NODE_ID, {}).get("config_version")
    daq_ver = versions.get(DAQ_NODE_ID, {}).get("config_version")
    synced = crio_ver is not None and daq_ver is not None and crio_ver == daq_ver
    if crio_ver and daq_ver:
        details.append(f"Sync: cRIO={crio_ver} vs DAQ={daq_ver} → {'MATCH' if synced else 'MISMATCH'}")
    elif not crio_ver:
        details.append(f"{Colors.WARN}cRIO has no config_version (config never pushed?){Colors.RESET}")

    print_result(5, "Config Sync", synced, "\n".join(details))
    return versions


def test_6_acquire_start(skip: bool = False) -> bool:
    """Test 6: Send acquire start and verify cRIO transitions."""
    print(f"\n{Colors.BOLD}{'='*60}")
    print(f"Test 6: Acquire Start → cRIO")
    print(f"{'='*60}{Colors.RESET}")

    if skip:
        print(f"  {Colors.WARN}SKIPPED (--skip-acquire){Colors.RESET}")
        return False

    # First check current state
    client = make_tcp_client("diag-t6-check")
    msgs = collect_messages(client, BROKER_HOST, TCP_PORT,
                            [(f"{SYSTEM_PREFIX}/nodes/{CRIO_NODE_ID}/status/system", 0)],
                            duration=3.0)

    already_acquiring = False
    for m in msgs:
        if isinstance(m["payload"], dict) and m["payload"].get("acquiring"):
            already_acquiring = True

    if already_acquiring:
        return print_result(6, "Acquire Start", True, "cRIO already acquiring — no action needed")

    # Try sending acquire start via DAQ service path (how dashboard does it)
    details = []

    # Method 1: Via DAQ service (dashboard path)
    details.append("Attempt 1: Send to DAQ service (dashboard path)...")
    client = make_tcp_client("diag-t6-daq")
    status_msgs = []
    connected_evt = threading.Event()

    def on_connect(c, ud, flags, rc, props=None):
        c.subscribe(f"{SYSTEM_PREFIX}/nodes/{CRIO_NODE_ID}/status/system", 0)
        c.subscribe(f"{SYSTEM_PREFIX}/nodes/{DAQ_NODE_ID}/command/ack", 0)
        connected_evt.set()

    def on_msg(c, ud, msg):
        try:
            status_msgs.append({"topic": msg.topic, "payload": json.loads(msg.payload)})
        except Exception:
            pass

    client.on_connect = on_connect
    client.on_message = on_msg
    client.connect(BROKER_HOST, TCP_PORT, 60)
    client.loop_start()
    connected_evt.wait(3)

    # Send start to DAQ service
    start_topic = f"{SYSTEM_PREFIX}/nodes/{DAQ_NODE_ID}/system/acquire/start"
    client.publish(start_topic, json.dumps({"request_id": "diag-t6-start"}), qos=1)
    details.append(f"  Published to: {start_topic}")

    time.sleep(8)  # Wait for DAQ to process and forward to cRIO

    crio_acquiring = False
    for m in status_msgs:
        if CRIO_NODE_ID in m["topic"] and isinstance(m["payload"], dict):
            if m["payload"].get("acquiring"):
                crio_acquiring = True

    if crio_acquiring:
        details.append(f"  {Colors.PASS}cRIO started acquiring via DAQ path!{Colors.RESET}")
        client.loop_stop()
        client.disconnect()
        return print_result(6, "Acquire Start", True, "\n".join(details))

    details.append(f"  {Colors.FAIL}cRIO did NOT start via DAQ path{Colors.RESET}")

    # Method 2: Direct to cRIO on TCP 1883
    details.append("Attempt 2: Send directly to cRIO on TCP 1883...")
    direct_topic = f"{SYSTEM_PREFIX}/nodes/{CRIO_NODE_ID}/system/acquire/start"
    client.publish(direct_topic, json.dumps({"command": "start", "request_id": "diag-t6-direct"}), qos=1)
    details.append(f"  Published to: {direct_topic}")
    time.sleep(5)

    for m in status_msgs:
        if CRIO_NODE_ID in m["topic"] and isinstance(m["payload"], dict):
            if m["payload"].get("acquiring"):
                crio_acquiring = True

    if crio_acquiring:
        details.append(f"  {Colors.PASS}cRIO started via direct TCP 1883!{Colors.RESET}")
        details.append(f"  {Colors.WARN}DIAGNOSIS: DAQ service forwarding is broken{Colors.RESET}")
        client.loop_stop()
        client.disconnect()
        return print_result(6, "Acquire Start", True, "\n".join(details))

    details.append(f"  {Colors.FAIL}cRIO did NOT start via direct TCP 1883{Colors.RESET}")

    # Method 3: Direct to cRIO on TLS 8883
    details.append("Attempt 3: Send directly to cRIO on TLS 8883...")
    tls_client = make_tls_client("diag-t6-tls")

    tls_status = []
    tls_connected = threading.Event()

    def tls_on_connect(c, ud, flags, rc, props=None):
        c.subscribe(f"{SYSTEM_PREFIX}/nodes/{CRIO_NODE_ID}/status/system", 0)
        tls_connected.set()

    def tls_on_msg(c, ud, msg):
        try:
            tls_status.append(json.loads(msg.payload))
        except Exception:
            pass

    tls_client.on_connect = tls_on_connect
    tls_client.on_message = tls_on_msg
    tls_client.connect(BROKER_HOST, TLS_PORT, 60)
    tls_client.loop_start()
    tls_connected.wait(3)

    tls_client.publish(direct_topic, json.dumps({"command": "start", "request_id": "diag-t6-tls"}), qos=1)
    details.append(f"  Published to: {direct_topic} (via TLS 8883)")
    time.sleep(5)

    for s in tls_status:
        if isinstance(s, dict) and s.get("acquiring"):
            crio_acquiring = True

    tls_client.loop_stop()
    tls_client.disconnect()
    client.loop_stop()
    client.disconnect()

    if crio_acquiring:
        details.append(f"  {Colors.PASS}cRIO started via TLS 8883!{Colors.RESET}")
        details.append(f"  {Colors.WARN}DIAGNOSIS: Cross-listener routing is broken{Colors.RESET}")
        details.append(f"  Commands from TCP 1883 don't reach cRIO on TLS 8883")
        return print_result(6, "Acquire Start", True, "\n".join(details))

    details.append(f"  {Colors.FAIL}cRIO refused to start on ALL paths{Colors.RESET}")
    details.append(f"  {Colors.WARN}Possible: cRIO stuck in non-IDLE state, or no channels configured{Colors.RESET}")
    return print_result(6, "Acquire Start", False, "\n".join(details))


def test_7_channel_data(duration: float = 10.0) -> dict:
    """Test 7: Check if cRIO channel batch data is flowing."""
    print(f"\n{Colors.BOLD}{'='*60}")
    print(f"Test 7: Channel Data Flow ({duration}s)")
    print(f"{'='*60}{Colors.RESET}")

    batch_data = {"tcp_batches": 0, "ws_batches": 0, "tcp_keys": 0, "ws_keys": 0, "sample": {}}

    # TCP listener
    tcp_client = make_tcp_client("diag-t7-tcp")
    tcp_msgs = collect_messages(tcp_client, BROKER_HOST, TCP_PORT,
                                [(f"{SYSTEM_PREFIX}/nodes/{CRIO_NODE_ID}/channels/batch", 0)],
                                duration=duration)

    for m in tcp_msgs:
        if isinstance(m["payload"], dict):
            batch_data["tcp_batches"] += 1
            batch_data["tcp_keys"] = max(batch_data["tcp_keys"], len(m["payload"]))
            if not batch_data["sample"]:
                batch_data["sample"] = {k: v for k, v in list(m["payload"].items())[:3]}

    # WS listener
    ws_client = make_ws_client("diag-t7-ws")
    ws_msgs = collect_messages(ws_client, BROKER_HOST, WS_PORT,
                               [(f"{SYSTEM_PREFIX}/nodes/{CRIO_NODE_ID}/channels/batch", 0)],
                               duration=duration)

    for m in ws_msgs:
        if isinstance(m["payload"], dict):
            batch_data["ws_batches"] += 1
            batch_data["ws_keys"] = max(batch_data["ws_keys"], len(m["payload"]))

    details = []
    details.append(f"TCP 1883: {batch_data['tcp_batches']} batches, max {batch_data['tcp_keys']} channels/batch")
    details.append(f"WS  9002: {batch_data['ws_batches']} batches, max {batch_data['ws_keys']} channels/batch")
    if batch_data["sample"]:
        details.append(f"Sample keys: {list(batch_data['sample'].keys())}")

    passed = batch_data["tcp_batches"] > 0 or batch_data["ws_batches"] > 0
    if not passed:
        details.append(f"{Colors.WARN}No batch data! Is cRIO acquiring? (check Test 2/6){Colors.RESET}")

    print_result(7, "Channel Data Flow", passed, "\n".join(details))
    return batch_data


def test_8_per_module(batch_data: dict) -> bool:
    """Test 8: Verify all 7 modules have data in the batch."""
    print(f"\n{Colors.BOLD}{'='*60}")
    print(f"Test 8: Per-Module Data Verification")
    print(f"{'='*60}{Colors.RESET}")

    if not batch_data.get("tcp_batches") and not batch_data.get("ws_batches"):
        return print_result(8, "Per-Module Data", False, "No batch data available (Test 7 failed)")

    # Collect one full batch
    client = make_tcp_client("diag-t8")
    msgs = collect_messages(client, BROKER_HOST, TCP_PORT,
                            [(f"{SYSTEM_PREFIX}/nodes/{CRIO_NODE_ID}/channels/batch", 0)],
                            duration=5.0)

    if not msgs:
        return print_result(8, "Per-Module Data", False, "No batch messages received")

    # Use the largest batch
    largest = {}
    for m in msgs:
        if isinstance(m["payload"], dict) and len(m["payload"]) > len(largest):
            largest = m["payload"]

    # Group by module
    modules: Dict[str, list] = {}
    for key, data in largest.items():
        # Keys are either "tag_N" or "Mod1/ai0" style or "AO_Mod2_ch00" style
        if key.startswith("tag_"):
            # We need to figure out which module from the channel data
            # Just count them for now
            modules.setdefault("tagged", []).append(key)
        elif "/" in key:
            mod = key.split("/")[0]
            modules.setdefault(mod, []).append(key)
        elif "_Mod" in key:
            parts = key.split("_")
            for p in parts:
                if p.startswith("Mod"):
                    modules.setdefault(p, []).append(key)
                    break
        else:
            modules.setdefault("other", []).append(key)

    expected = {
        "Mod1": 16, "Mod2": 16, "Mod3": 32, "Mod4": 8,
        "Mod5": 16, "Mod6": 8, "Mod7": 16,
    }

    details = []
    details.append(f"Total channels in batch: {len(largest)}")
    details.append(f"Module groups found: {list(modules.keys())}")
    for mod, channels in sorted(modules.items()):
        exp = expected.get(mod, "?")
        details.append(f"  {mod}: {len(channels)} channels (expected: {exp})")

    # Check for NaN values
    nan_count = 0
    for key, data in largest.items():
        if isinstance(data, dict):
            v = data.get("value")
            if v is None or (isinstance(v, float) and v != v):  # NaN check
                nan_count += 1

    details.append(f"NaN/null values: {nan_count}")

    passed = len(largest) >= 100  # Should be ~112 channels
    print_result(8, "Per-Module Data", passed, "\n".join(details))
    return passed


def test_9_daq_republish() -> bool:
    """Test 9: Check DAQ service re-publish of cRIO data as node-001."""
    print(f"\n{Colors.BOLD}{'='*60}")
    print(f"Test 9: DAQ Re-Publish (Path B)")
    print(f"{'='*60}{Colors.RESET}")

    client = make_tcp_client("diag-t9")
    msgs = collect_messages(client, BROKER_HOST, TCP_PORT,
                            [(f"{SYSTEM_PREFIX}/nodes/{DAQ_NODE_ID}/channels/#", 0)],
                            duration=10.0)

    batch_count = 0
    individual_count = 0
    batch_keys = 0
    individual_channels = set()

    for m in msgs:
        if "channels/batch" in m["topic"]:
            batch_count += 1
            if isinstance(m["payload"], dict):
                batch_keys = max(batch_keys, len(m["payload"]))
        else:
            individual_count += 1
            ch = m["topic"].split("/")[-1]
            individual_channels.add(ch)

    details = []
    details.append(f"node-001 batches: {batch_count} (max {batch_keys} keys)")
    details.append(f"node-001 individual: {individual_count} messages, {len(individual_channels)} unique channels")
    if individual_channels:
        sample = sorted(individual_channels)[:5]
        details.append(f"Sample channels: {sample}")

    passed = individual_count > 0 or batch_keys > 0
    if not passed:
        details.append(f"{Colors.WARN}DAQ not re-publishing cRIO data. Check DAQ acquiring state.{Colors.RESET}")

    print_result(9, "DAQ Re-Publish", passed, "\n".join(details))
    return passed


def test_10_cleanup(skip: bool = False) -> bool:
    """Test 10: Stop acquisition cleanly."""
    print(f"\n{Colors.BOLD}{'='*60}")
    print(f"Test 10: Cleanup (Stop Acquisition)")
    print(f"{'='*60}{Colors.RESET}")

    if skip:
        print(f"  {Colors.WARN}SKIPPED (--skip-acquire){Colors.RESET}")
        return True

    client = make_tcp_client("diag-t10")
    stop_topic = f"{SYSTEM_PREFIX}/nodes/{DAQ_NODE_ID}/system/acquire/stop"
    connected_evt = threading.Event()
    stopped = threading.Event()

    def on_connect(c, ud, flags, rc, props=None):
        c.subscribe(f"{SYSTEM_PREFIX}/nodes/{DAQ_NODE_ID}/command/ack", 0)
        connected_evt.set()

    def on_msg(c, ud, msg):
        stopped.set()

    client.on_connect = on_connect
    client.on_message = on_msg
    client.connect(BROKER_HOST, TCP_PORT, 60)
    client.loop_start()
    connected_evt.wait(3)

    client.publish(stop_topic, json.dumps({"request_id": "diag-t10-stop"}), qos=1)
    ok = stopped.wait(timeout=5)

    client.loop_stop()
    client.disconnect()

    return print_result(10, "Cleanup", ok, "Acquisition stopped" if ok else "No ACK received (may already be stopped)")


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="cRIO Data Pipeline Diagnostic")
    parser.add_argument("--test", type=int, help="Run specific test number (1-10)")
    parser.add_argument("--skip-acquire", action="store_true",
                        help="Skip tests that start/stop acquisition (6, 10)")
    args = parser.parse_args()

    print(f"\n{Colors.BOLD}╔══════════════════════════════════════════════════╗")
    print(f"║   cRIO Data Pipeline Diagnostic                  ║")
    print(f"║   Target: {CRIO_NODE_ID} @ {BROKER_HOST}                  ║")
    print(f"╚══════════════════════════════════════════════════╝{Colors.RESET}")

    results = {}

    if args.test:
        # Run specific test
        tests = {
            1: lambda: test_1_mosquitto_ports(),
            2: lambda: test_2_crio_online(),
            3: lambda: test_3_cross_listener_routing(),
            4: lambda: test_4_crio_command_delivery(),
            5: lambda: test_5_config_sync(),
            6: lambda: test_6_acquire_start(args.skip_acquire),
            7: lambda: test_7_channel_data(),
            8: lambda: test_8_per_module(test_7_channel_data()),
            9: lambda: test_9_daq_republish(),
            10: lambda: test_10_cleanup(args.skip_acquire),
        }
        if args.test in tests:
            tests[args.test]()
        else:
            print(f"Unknown test number: {args.test}")
        return

    # Run all tests in order
    results[1] = test_1_mosquitto_ports()
    if not results[1]:
        print(f"\n{Colors.FAIL}ABORT: Mosquitto not running. Start it first.{Colors.RESET}")
        return

    crio_info = test_2_crio_online()
    results[2] = crio_info.get("heartbeat", False)
    if not results[2]:
        print(f"\n{Colors.FAIL}ABORT: cRIO not reachable. Check network/power.{Colors.RESET}")
        return

    routing = test_3_cross_listener_routing()
    results[3] = all(routing.values())

    cmd_results = test_4_crio_command_delivery()
    results[4] = any(cmd_results.values())

    test_5_config_sync()

    if not args.skip_acquire:
        results[6] = test_6_acquire_start()
        time.sleep(2)  # Let acquisition settle
    else:
        results[6] = crio_info.get("acquiring", False)

    batch_data = test_7_channel_data()
    results[7] = batch_data.get("tcp_batches", 0) > 0

    results[8] = test_8_per_module(batch_data)
    results[9] = test_9_daq_republish()

    if not args.skip_acquire:
        results[10] = test_10_cleanup()

    # Summary
    print(f"\n{Colors.BOLD}{'='*60}")
    print(f"SUMMARY")
    print(f"{'='*60}{Colors.RESET}")

    passed = sum(1 for v in results.values() if v)
    total = len(results)
    for num, ok in sorted(results.items()):
        icon = f"{Colors.PASS}PASS{Colors.RESET}" if ok else f"{Colors.FAIL}FAIL{Colors.RESET}"
        print(f"  Test {num:2d}: {icon}")

    print(f"\n  {passed}/{total} passed")

    if not results.get(3):
        print(f"\n  {Colors.WARN}LIKELY ROOT CAUSE: Cross-listener message routing broken")
        print(f"  DAQ publishes commands on port 1883, cRIO listens on 8883.{Colors.RESET}")
    elif not results.get(4):
        print(f"\n  {Colors.WARN}LIKELY ROOT CAUSE: cRIO not responding to commands")
        print(f"  Check cRIO process logs via SSH.{Colors.RESET}")
    elif not results.get(7):
        print(f"\n  {Colors.WARN}LIKELY ROOT CAUSE: cRIO acquiring but no data flowing")
        print(f"  Check hardware.start() on cRIO — SSH and check logs.{Colors.RESET}")


if __name__ == "__main__":
    main()
