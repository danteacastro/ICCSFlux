#!/usr/bin/env python3
"""
cRIO Digital Output Toggle Test Script

Tests the DO toggle functionality for cRIO channels (tag_72 - tag_79).
Verifies MQTT command routing from DAQ service to cRIO node.

Usage:
    python scripts/test_crio_do.py
"""

import json
import time
import paho.mqtt.client as mqtt
from datetime import datetime

# Configuration
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
BASE_TOPIC = "nisystem"

# DO channels to test (NI 9472 on Mod4)
DO_CHANNELS = [f"tag_7{i}" for i in range(2, 10)]  # tag_72 - tag_79

# Track received messages
received_messages = {}
test_results = {}


def on_connect(client, userdata, flags, rc, properties=None):
    print(f"[{timestamp()}] Connected to MQTT broker (rc={rc})")

    # Subscribe to relevant topics
    subscriptions = [
        f"{BASE_TOPIC}/nodes/+/channels/#",      # Channel values
        f"{BASE_TOPIC}/nodes/+/status/#",        # Status updates
        f"{BASE_TOPIC}/nodes/+/commands/#",      # Command echo (if any)
    ]
    for topic in subscriptions:
        client.subscribe(topic)
        print(f"[{timestamp()}] Subscribed to: {topic}")


def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        topic = msg.topic

        # Track DO channel values from cRIO
        if "/channels/" in topic and "crio" in topic:
            # Extract channel name from batch or individual message
            if topic.endswith("/batch"):
                # Batch message - check for DO channels
                for ch_name, data in payload.items():
                    if "Mod4" in ch_name or any(do in ch_name for do in DO_CHANNELS):
                        received_messages[ch_name] = {
                            'value': data.get('value'),
                            'timestamp': data.get('timestamp'),
                            'topic': topic
                        }
            else:
                # Individual channel message
                parts = topic.split("/")
                ch_name = parts[-1] if parts else ""
                if "Mod4" in ch_name or ch_name in DO_CHANNELS:
                    received_messages[ch_name] = {
                        'value': payload.get('value'),
                        'timestamp': payload.get('timestamp'),
                        'topic': topic
                    }

    except Exception as e:
        pass  # Ignore parse errors


def timestamp():
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def send_command_via_daq(client, channel_name, value):
    """Send command through DAQ service (simulates dashboard toggle)"""
    # This is what the dashboard sends - goes to DAQ service which should route to cRIO
    topic = f"{BASE_TOPIC}/nodes/node-001/commands/{channel_name}"
    payload = {"value": value}
    client.publish(topic, json.dumps(payload))
    print(f"[{timestamp()}] -> DAQ command: {topic} = {payload}")


def send_command_direct_crio(client, channel_name, value):
    """Send command directly to cRIO (bypasses DAQ service)"""
    # Direct to cRIO's command topic
    topic = f"{BASE_TOPIC}/nodes/crio-001/commands/output"
    payload = {"channel": channel_name, "value": value}
    client.publish(topic, json.dumps(payload))
    print(f"[{timestamp()}] -> cRIO direct: {topic} = {payload}")


def send_output_set(client, channel_name, value):
    """Send via output/set topic (another dashboard path)"""
    topic = f"{BASE_TOPIC}/nodes/node-001/output/set"
    payload = {"channel": channel_name, "value": value}
    client.publish(topic, json.dumps(payload))
    print(f"[{timestamp()}] -> output/set: {topic} = {payload}")


def wait_for_change(channel_name, expected_value, timeout=3.0):
    """Wait for channel value to change"""
    start = time.time()
    while time.time() - start < timeout:
        # Check both TAG name and physical channel name
        for key in [channel_name, f"Mod4/port0/line{int(channel_name[-1]) - 2}"]:
            if key in received_messages:
                val = received_messages[key].get('value')
                if val is not None:
                    # Compare as bool (0/0.0 = False, 1/1.0 = True)
                    if bool(val) == bool(expected_value):
                        return True, val
        time.sleep(0.1)
    return False, None


def run_tests():
    print("\n" + "=" * 60)
    print("cRIO Digital Output Toggle Test")
    print("=" * 60)
    print(f"Broker: {MQTT_BROKER}:{MQTT_PORT}")
    print(f"Testing channels: {DO_CHANNELS}")
    print("=" * 60 + "\n")

    # Connect to MQTT
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="crio_do_test")
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_BROKER, MQTT_PORT)
    client.loop_start()

    time.sleep(1)  # Wait for connection and initial messages

    # Test 1: Direct cRIO command (should always work if cRIO is running)
    print("\n--- TEST 1: Direct cRIO commands ---")
    print("(Sends directly to cRIO, bypassing DAQ service)\n")

    test_channel = "tag_72"

    # Turn ON
    print(f"Setting {test_channel} = True (direct to cRIO)...")
    send_command_direct_crio(client, test_channel, True)
    time.sleep(0.5)
    success, val = wait_for_change(test_channel, True)
    test_results["direct_on"] = success
    print(f"  Result: {'PASS' if success else 'FAIL'} (value={val})")

    time.sleep(1)

    # Turn OFF
    print(f"Setting {test_channel} = False (direct to cRIO)...")
    send_command_direct_crio(client, test_channel, False)
    time.sleep(0.5)
    success, val = wait_for_change(test_channel, False)
    test_results["direct_off"] = success
    print(f"  Result: {'PASS' if success else 'FAIL'} (value={val})")

    time.sleep(1)

    # Test 2: Via DAQ service commands topic (what dashboard uses)
    print("\n--- TEST 2: Via DAQ service (commands topic) ---")
    print("(Sends to DAQ service which should route to cRIO)\n")

    # Turn ON
    print(f"Setting {test_channel} = True (via DAQ commands)...")
    send_command_via_daq(client, test_channel, True)
    time.sleep(0.5)
    success, val = wait_for_change(test_channel, True)
    test_results["daq_cmd_on"] = success
    print(f"  Result: {'PASS' if success else 'FAIL'} (value={val})")

    time.sleep(1)

    # Turn OFF
    print(f"Setting {test_channel} = False (via DAQ commands)...")
    send_command_via_daq(client, test_channel, False)
    time.sleep(0.5)
    success, val = wait_for_change(test_channel, False)
    test_results["daq_cmd_off"] = success
    print(f"  Result: {'PASS' if success else 'FAIL'} (value={val})")

    time.sleep(1)

    # Test 3: Via output/set topic (another dashboard path)
    print("\n--- TEST 3: Via DAQ service (output/set topic) ---")
    print("(Uses _handle_output_set code path)\n")

    # Turn ON
    print(f"Setting {test_channel} = True (via output/set)...")
    send_output_set(client, test_channel, True)
    time.sleep(0.5)
    success, val = wait_for_change(test_channel, True)
    test_results["output_set_on"] = success
    print(f"  Result: {'PASS' if success else 'FAIL'} (value={val})")

    time.sleep(1)

    # Turn OFF
    print(f"Setting {test_channel} = False (via output/set)...")
    send_output_set(client, test_channel, False)
    time.sleep(0.5)
    success, val = wait_for_change(test_channel, False)
    test_results["output_set_off"] = success
    print(f"  Result: {'PASS' if success else 'FAIL'} (value={val})")

    # Test 4: Toggle all DO channels
    print("\n--- TEST 4: Toggle all DO channels ---")
    print("(Quick test of all 8 DO channels)\n")

    all_success = True
    for ch in DO_CHANNELS:
        send_command_direct_crio(client, ch, True)
        time.sleep(0.2)

    time.sleep(1)
    print("All channels set to ON")

    for ch in DO_CHANNELS:
        send_command_direct_crio(client, ch, False)
        time.sleep(0.2)

    time.sleep(1)
    print("All channels set to OFF")

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    passed = sum(1 for v in test_results.values() if v)
    total = len(test_results)

    for test_name, result in test_results.items():
        status = "PASS" if result else "FAIL"
        print(f"  {test_name}: {status}")

    print(f"\nTotal: {passed}/{total} tests passed")

    if passed == total:
        print("\nAll tests PASSED!")
    else:
        print("\nSome tests FAILED - check DAQ service logs for errors")
        print("\nDebug tips:")
        print("  1. Check if DAQ service is running and restarted with latest code")
        print("  2. Check if cRIO node is connected (mosquitto_sub -t 'nisystem/nodes/crio-001/#' -v)")
        print("  3. Check DAQ service logs for 'Routing to cRIO' messages")

    print("=" * 60)

    # Show received channel values
    print("\nReceived DO channel values:")
    for ch, data in sorted(received_messages.items()):
        if "Mod4" in ch or any(do in ch for do in DO_CHANNELS):
            print(f"  {ch}: {data.get('value')}")

    client.loop_stop()
    client.disconnect()


if __name__ == "__main__":
    run_tests()
