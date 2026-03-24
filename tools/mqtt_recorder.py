"""
MQTT Traffic Recorder — Captures MQTT messages to JSONL files.

Records all messages matching topic patterns with timestamps, payload,
QoS, and retain flag. Output is gzip-compressed JSONL.

Usage:
    python tools/mqtt_recorder.py --host localhost --port 1883 --topics "iccsflux/#" -o capture.jsonl.gz
    python tools/mqtt_recorder.py --duration 300        # stop after 5 min
    python tools/mqtt_recorder.py --max-messages 10000  # stop after 10k messages
"""

import argparse
import base64
import gzip
import json
import signal
import sys
import time
from pathlib import Path
from typing import List, Optional

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("Error: paho-mqtt is required. Install with: pip install paho-mqtt", file=sys.stderr)
    sys.exit(1)

class MQTTRecorder:
    """Records MQTT messages to a gzip-compressed JSONL file."""

    def __init__(self, host: str = 'localhost', port: int = 1883,
                 topics: Optional[List[str]] = None,
                 username: Optional[str] = None, password: Optional[str] = None,
                 client_id: str = 'mqtt-recorder'):
        self.host = host
        self.port = port
        self.topics = topics or ['#']
        self.username = username
        self.password = password
        self.client_id = client_id

        self._client: Optional[mqtt.Client] = None
        self._output_file = None
        self._message_count = 0
        self._start_time = 0.0
        self._running = False
        self._max_messages = 0
        self._max_duration = 0.0
        self._first_ts: Optional[float] = None
        self._last_ts: Optional[float] = None
        self._topic_counts: dict = {}

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            for topic in self.topics:
                client.subscribe(topic)
                print(f"  Subscribed to: {topic}")
        else:
            print(f"Connection failed with code {rc}", file=sys.stderr)

    def _on_message(self, client, userdata, msg):
        ts = time.time()
        if self._first_ts is None:
            self._first_ts = ts
        self._last_ts = ts

        # Build record
        record = {
            'ts': ts,
            'topic': msg.topic,
            'qos': msg.qos,
            'retain': msg.retain,
        }

        # Try to decode payload as UTF-8 text
        try:
            payload_str = msg.payload.decode('utf-8')
            record['payload'] = payload_str
        except (UnicodeDecodeError, AttributeError):
            record['payload'] = base64.b64encode(msg.payload).decode('ascii')
            record['encoding'] = 'base64'

        # Write to file
        line = json.dumps(record, separators=(',', ':')) + '\n'
        self._output_file.write(line.encode('utf-8'))

        self._message_count += 1
        self._topic_counts[msg.topic] = self._topic_counts.get(msg.topic, 0) + 1

        # Progress indicator
        if self._message_count % 100 == 0:
            elapsed = ts - self._start_time
            rate = self._message_count / elapsed if elapsed > 0 else 0
            print(f"\r  {self._message_count} messages ({rate:.1f}/s, "
                  f"{len(self._topic_counts)} topics)", end='', flush=True)

        # Check limits
        if self._max_messages > 0 and self._message_count >= self._max_messages:
            print(f"\n  Reached message limit ({self._max_messages})")
            self._running = False

    def record(self, output_path: str,
               max_messages: int = 0, max_duration: float = 0.0):
        """
        Start recording MQTT traffic.

        Args:
            output_path: Path to output JSONL.gz file
            max_messages: Stop after this many messages (0 = unlimited)
            max_duration: Stop after this many seconds (0 = unlimited)
        """
        self._max_messages = max_messages
        self._max_duration = max_duration
        self._message_count = 0
        self._start_time = time.time()
        self._running = True
        self._first_ts = None
        self._last_ts = None
        self._topic_counts = {}

        # Open output file
        self._output_file = gzip.open(output_path, 'wb')

        # Set up MQTT client
        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=self.client_id,
        )
        if self.username:
            self._client.username_pw_set(self.username, self.password)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message

        # Handle Ctrl+C
        original_sigint = signal.getsignal(signal.SIGINT)

        def _stop(sig, frame):
            print("\n  Stopping...")
            self._running = False

        signal.signal(signal.SIGINT, _stop)

        try:
            print(f"Connecting to {self.host}:{self.port}...")
            self._client.connect(self.host, self.port, keepalive=60)
            self._client.loop_start()

            # Wait until stopped
            while self._running:
                time.sleep(0.1)
                if self._max_duration > 0:
                    elapsed = time.time() - self._start_time
                    if elapsed >= self._max_duration:
                        print(f"\n  Reached duration limit ({self._max_duration}s)")
                        self._running = False

        finally:
            signal.signal(signal.SIGINT, original_sigint)
            self._client.loop_stop()
            self._client.disconnect()

            # Write summary as last line
            summary = {
                '_summary': True,
                'total_messages': self._message_count,
                'duration_seconds': (self._last_ts - self._first_ts) if self._first_ts and self._last_ts else 0,
                'topics': len(self._topic_counts),
                'topic_counts': self._topic_counts,
                'start_time': self._first_ts,
                'end_time': self._last_ts,
            }
            line = json.dumps(summary, separators=(',', ':')) + '\n'
            self._output_file.write(line.encode('utf-8'))
            self._output_file.close()

            print(f"\nRecording complete:")
            print(f"  Messages: {self._message_count}")
            print(f"  Topics:   {len(self._topic_counts)}")
            if self._first_ts and self._last_ts:
                print(f"  Duration: {self._last_ts - self._first_ts:.1f}s")
            print(f"  Output:   {output_path}")

        return self._message_count

def read_jsonl(file_path: str):
    """
    Generator that yields parsed records from a JSONL.gz file.
    Skips the summary record.
    """
    opener = gzip.open if file_path.endswith('.gz') else open
    with opener(file_path, 'rt', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get('_summary'):
                continue
            yield record

def read_summary(file_path: str) -> Optional[dict]:
    """Read the summary record from a JSONL.gz file (last line)."""
    opener = gzip.open if file_path.endswith('.gz') else open
    last_line = None
    with opener(file_path, 'rt', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                last_line = line
    if last_line:
        record = json.loads(last_line)
        if record.get('_summary'):
            return record
    return None

def main():
    parser = argparse.ArgumentParser(
        description='Record MQTT traffic to JSONL file',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--host', default='localhost', help='MQTT broker host')
    parser.add_argument('--port', type=int, default=1883, help='MQTT broker port')
    parser.add_argument('--topics', nargs='+', default=['#'],
                        help='Topic patterns to subscribe to')
    parser.add_argument('--username', '-u', help='MQTT username')
    parser.add_argument('--password', '-p', help='MQTT password')
    parser.add_argument('--output', '-o', default=None,
                        help='Output file path (default: capture_TIMESTAMP.jsonl.gz)')
    parser.add_argument('--duration', type=float, default=0,
                        help='Stop after N seconds (0 = unlimited)')
    parser.add_argument('--max-messages', type=int, default=0,
                        help='Stop after N messages (0 = unlimited)')
    args = parser.parse_args()

    if args.output is None:
        ts = time.strftime('%Y%m%d_%H%M%S')
        args.output = f'capture_{ts}.jsonl.gz'

    recorder = MQTTRecorder(
        host=args.host,
        port=args.port,
        topics=args.topics,
        username=args.username,
        password=args.password,
    )
    recorder.record(args.output,
                    max_messages=args.max_messages,
                    max_duration=args.duration)

if __name__ == '__main__':
    main()
