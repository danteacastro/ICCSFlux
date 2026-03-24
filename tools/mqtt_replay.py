"""
MQTT Traffic Replayer — Replays recorded MQTT traffic from JSONL files.

Publishes messages with original timing (adjustable speed), supports topic
remapping for safe replay to test prefixes.

Usage:
    python tools/mqtt_replay.py capture.jsonl.gz --host localhost --port 1883
    python tools/mqtt_replay.py capture.jsonl.gz --speed 2.0       # 2x speed
    python tools/mqtt_replay.py capture.jsonl.gz --speed 0         # as fast as possible
    python tools/mqtt_replay.py capture.jsonl.gz --remap "iccsflux=test"
"""

import argparse
import base64
import gzip
import json
import signal
import sys
import time
from typing import Dict, List, Optional, Tuple

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("Error: paho-mqtt is required. Install with: pip install paho-mqtt", file=sys.stderr)
    sys.exit(1)

class TopicRemapper:
    """Remaps MQTT topics based on prefix substitution rules."""

    def __init__(self, rules: Optional[List[str]] = None):
        self.rules: List[Tuple[str, str]] = []
        if rules:
            for rule in rules:
                if '=' in rule:
                    old, new = rule.split('=', 1)
                    self.rules.append((old, new))

    def remap(self, topic: str) -> str:
        for old_prefix, new_prefix in self.rules:
            if topic.startswith(old_prefix):
                return new_prefix + topic[len(old_prefix):]
        return topic

class MQTTReplayer:
    """Replays MQTT traffic from a JSONL.gz recording."""

    def __init__(self, host: str = 'localhost', port: int = 1883,
                 username: Optional[str] = None, password: Optional[str] = None,
                 client_id: str = 'mqtt-replayer'):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.client_id = client_id
        self._running = False

    def replay(self, file_path: str, speed: float = 1.0,
               remap_rules: Optional[List[str]] = None,
               loop: bool = False) -> int:
        """
        Replay recorded MQTT traffic.

        Args:
            file_path: Path to JSONL.gz capture file
            speed: Playback speed (1.0 = real-time, 2.0 = 2x, 0 = as fast as possible)
            remap_rules: Topic remap rules (e.g. ["iccsflux=test"])
            loop: Loop playback continuously

        Returns:
            Number of messages replayed
        """
        remapper = TopicRemapper(remap_rules)
        self._running = True

        # Handle Ctrl+C
        original_sigint = signal.getsignal(signal.SIGINT)

        def _stop(sig, frame):
            print("\n  Stopping replay...")
            self._running = False

        signal.signal(signal.SIGINT, _stop)

        # Connect to broker
        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=self.client_id,
        )
        if self.username:
            client.username_pw_set(self.username, self.password)

        connected = False

        def on_connect(c, userdata, flags, rc, properties=None):
            nonlocal connected
            connected = rc == 0

        client.on_connect = on_connect
        client.connect(self.host, self.port, keepalive=60)
        client.loop_start()

        # Wait for connection
        deadline = time.time() + 5.0
        while not connected and time.time() < deadline:
            time.sleep(0.05)

        if not connected:
            print("Failed to connect to broker", file=sys.stderr)
            client.loop_stop()
            signal.signal(signal.SIGINT, original_sigint)
            return 0

        total_replayed = 0

        try:
            while self._running:
                records = list(_load_records(file_path))
                if not records:
                    print("No messages in capture file", file=sys.stderr)
                    break

                print(f"Replaying {len(records)} messages at {speed}x speed...")
                if remap_rules:
                    print(f"  Topic remapping: {remap_rules}")

                prev_ts = records[0]['ts']
                start_wall = time.time()

                for i, record in enumerate(records):
                    if not self._running:
                        break

                    # Wait for correct timing
                    if speed > 0 and i > 0:
                        msg_delay = record['ts'] - prev_ts
                        wall_delay = msg_delay / speed
                        if wall_delay > 0:
                            target_time = start_wall + (record['ts'] - records[0]['ts']) / speed
                            sleep_time = target_time - time.time()
                            if sleep_time > 0:
                                time.sleep(sleep_time)

                    prev_ts = record['ts']

                    # Remap topic
                    topic = remapper.remap(record['topic'])

                    # Decode payload
                    if record.get('encoding') == 'base64':
                        payload = base64.b64decode(record['payload'])
                    else:
                        payload = record['payload'].encode('utf-8') if isinstance(record['payload'], str) else record['payload']

                    qos = record.get('qos', 0)
                    retain = record.get('retain', False)

                    client.publish(topic, payload, qos=qos, retain=retain)
                    total_replayed += 1

                    # Progress
                    if total_replayed % 100 == 0:
                        elapsed = time.time() - start_wall
                        rate = total_replayed / elapsed if elapsed > 0 else 0
                        pct = (i + 1) / len(records) * 100
                        print(f"\r  {total_replayed} messages ({pct:.0f}%, {rate:.1f}/s)", end='', flush=True)

                print(f"\r  {total_replayed} messages replayed")

                if not loop:
                    break
                else:
                    print("  Looping...")

        finally:
            signal.signal(signal.SIGINT, original_sigint)
            client.loop_stop()
            client.disconnect()

        elapsed = time.time() - start_wall if 'start_wall' in dir() else 0
        print(f"\nReplay complete: {total_replayed} messages in {elapsed:.1f}s")
        return total_replayed

def _load_records(file_path: str) -> list:
    """Load message records from a JSONL file (skipping summary)."""
    opener = gzip.open if file_path.endswith('.gz') else open
    records = []
    with opener(file_path, 'rt', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get('_summary'):
                continue
            records.append(record)
    return records

def main():
    parser = argparse.ArgumentParser(
        description='Replay recorded MQTT traffic',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('file', help='JSONL.gz capture file to replay')
    parser.add_argument('--host', default='localhost', help='MQTT broker host')
    parser.add_argument('--port', type=int, default=1883, help='MQTT broker port')
    parser.add_argument('--username', '-u', help='MQTT username')
    parser.add_argument('--password', '-p', help='MQTT password')
    parser.add_argument('--speed', type=float, default=1.0,
                        help='Playback speed (0 = max speed, default: 1.0)')
    parser.add_argument('--remap', nargs='+',
                        help='Topic remap rules (e.g. "iccsflux=test")')
    parser.add_argument('--loop', action='store_true',
                        help='Loop playback continuously')
    args = parser.parse_args()

    replayer = MQTTReplayer(
        host=args.host,
        port=args.port,
        username=args.username,
        password=args.password,
    )
    replayer.replay(args.file, speed=args.speed,
                    remap_rules=args.remap, loop=args.loop)

if __name__ == '__main__':
    main()
