"""
MQTT Traffic Analyzer — Analyzes recorded MQTT traffic from JSONL files.

Provides topic hierarchy, rate statistics, gap detection, and payload analysis.

Usage:
    python tools/mqtt_analyzer.py capture.jsonl.gz
    python tools/mqtt_analyzer.py capture.jsonl.gz --gaps 5.0
    python tools/mqtt_analyzer.py capture.jsonl.gz --topic "iccsflux/nodes/+/channels/batch"
"""

import argparse
import fnmatch
import gzip
import json
import sys
from collections import defaultdict
from typing import Dict, List, Optional


class TopicStats:
    """Statistics for a single MQTT topic."""

    def __init__(self, topic: str):
        self.topic = topic
        self.count = 0
        self.timestamps: List[float] = []
        self.payload_sizes: List[int] = []
        self.first_ts: Optional[float] = None
        self.last_ts: Optional[float] = None

    def add(self, ts: float, payload_size: int):
        self.count += 1
        self.timestamps.append(ts)
        self.payload_sizes.append(payload_size)
        if self.first_ts is None or ts < self.first_ts:
            self.first_ts = ts
        if self.last_ts is None or ts > self.last_ts:
            self.last_ts = ts

    def intervals(self) -> List[float]:
        """Calculate inter-message intervals."""
        if len(self.timestamps) < 2:
            return []
        sorted_ts = sorted(self.timestamps)
        return [sorted_ts[i + 1] - sorted_ts[i] for i in range(len(sorted_ts) - 1)]

    def rate_stats(self) -> Dict[str, float]:
        """Calculate rate statistics."""
        ivs = self.intervals()
        if not ivs:
            return {'min_interval': 0, 'max_interval': 0, 'avg_interval': 0,
                    'p95_interval': 0, 'avg_rate_hz': 0}

        ivs_sorted = sorted(ivs)
        avg = sum(ivs) / len(ivs)
        p95_idx = int(len(ivs_sorted) * 0.95)
        p95 = ivs_sorted[min(p95_idx, len(ivs_sorted) - 1)]

        return {
            'min_interval': ivs_sorted[0],
            'max_interval': ivs_sorted[-1],
            'avg_interval': avg,
            'p95_interval': p95,
            'avg_rate_hz': 1.0 / avg if avg > 0 else 0,
        }

    def payload_stats(self) -> Dict[str, float]:
        """Calculate payload size statistics."""
        if not self.payload_sizes:
            return {'min_bytes': 0, 'max_bytes': 0, 'avg_bytes': 0, 'total_bytes': 0}

        return {
            'min_bytes': min(self.payload_sizes),
            'max_bytes': max(self.payload_sizes),
            'avg_bytes': sum(self.payload_sizes) / len(self.payload_sizes),
            'total_bytes': sum(self.payload_sizes),
        }

    def find_gaps(self, threshold: float) -> List[Dict]:
        """Find gaps larger than threshold seconds."""
        gaps = []
        ivs = self.intervals()
        sorted_ts = sorted(self.timestamps)
        for i, iv in enumerate(ivs):
            if iv >= threshold:
                gaps.append({
                    'start': sorted_ts[i],
                    'end': sorted_ts[i + 1],
                    'duration': iv,
                })
        return gaps


class MQTTAnalyzer:
    """Analyzes MQTT traffic from a JSONL.gz recording."""

    def __init__(self):
        self.topic_stats: Dict[str, TopicStats] = {}
        self.total_messages = 0
        self.first_ts: Optional[float] = None
        self.last_ts: Optional[float] = None
        self._all_timestamps: List[float] = []

    def load(self, file_path: str, topic_filter: Optional[str] = None):
        """Load and analyze a JSONL.gz capture file."""
        opener = gzip.open if file_path.endswith('.gz') else open

        with opener(file_path, 'rt', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                if record.get('_summary'):
                    continue

                topic = record.get('topic', '')
                ts = record.get('ts', 0.0)
                payload = record.get('payload', '')
                payload_size = len(payload.encode('utf-8')) if isinstance(payload, str) else len(payload)

                # Apply topic filter (supports MQTT wildcards via fnmatch)
                if topic_filter:
                    pattern = topic_filter.replace('+', '*').replace('#', '**')
                    if not fnmatch.fnmatch(topic, pattern):
                        continue

                if topic not in self.topic_stats:
                    self.topic_stats[topic] = TopicStats(topic)
                self.topic_stats[topic].add(ts, payload_size)

                self.total_messages += 1
                self._all_timestamps.append(ts)

                if self.first_ts is None or ts < self.first_ts:
                    self.first_ts = ts
                if self.last_ts is None or ts > self.last_ts:
                    self.last_ts = ts

    @property
    def duration(self) -> float:
        if self.first_ts and self.last_ts:
            return self.last_ts - self.first_ts
        return 0.0

    def topic_tree(self) -> Dict:
        """Build a topic hierarchy tree with counts."""
        tree: Dict = {}
        for topic, stats in sorted(self.topic_stats.items()):
            parts = topic.split('/')
            node = tree
            for part in parts:
                if part not in node:
                    node[part] = {'_count': 0, '_children': {}}
                node[part]['_count'] += stats.count
                node = node[part]['_children']
        return tree

    def find_all_gaps(self, threshold: float) -> List[Dict]:
        """Find gaps across all messages (regardless of topic)."""
        if len(self._all_timestamps) < 2:
            return []

        sorted_ts = sorted(self._all_timestamps)
        gaps = []
        for i in range(len(sorted_ts) - 1):
            iv = sorted_ts[i + 1] - sorted_ts[i]
            if iv >= threshold:
                gaps.append({
                    'start': sorted_ts[i],
                    'end': sorted_ts[i + 1],
                    'duration': iv,
                })
        return gaps

    def report(self, gap_threshold: float = 5.0) -> str:
        """Generate a text report."""
        lines = []

        # Header
        lines.append("=" * 70)
        lines.append("MQTT Traffic Analysis")
        lines.append("=" * 70)
        lines.append(f"Total messages: {self.total_messages}")
        lines.append(f"Unique topics:  {len(self.topic_stats)}")
        lines.append(f"Duration:       {self.duration:.1f}s")
        if self.duration > 0:
            lines.append(f"Overall rate:   {self.total_messages / self.duration:.1f} msg/s")
        lines.append("")

        # Topic hierarchy
        lines.append("-" * 70)
        lines.append("Topic Hierarchy")
        lines.append("-" * 70)
        tree = self.topic_tree()
        self._format_tree(tree, lines, indent=0)
        lines.append("")

        # Per-topic rate stats
        lines.append("-" * 70)
        lines.append(f"{'Topic':<50s} {'Count':>7s} {'Rate':>8s} {'Avg(ms)':>8s}")
        lines.append("-" * 70)

        for topic in sorted(self.topic_stats.keys()):
            stats = self.topic_stats[topic]
            rs = stats.rate_stats()
            rate_str = f"{rs['avg_rate_hz']:.1f}Hz" if rs['avg_rate_hz'] > 0 else "—"
            avg_ms = f"{rs['avg_interval'] * 1000:.0f}" if rs['avg_interval'] > 0 else "—"
            topic_short = topic if len(topic) <= 50 else '...' + topic[-47:]
            lines.append(f"{topic_short:<50s} {stats.count:>7d} {rate_str:>8s} {avg_ms:>8s}")
        lines.append("")

        # Payload stats
        total_bytes = sum(s.payload_stats()['total_bytes'] for s in self.topic_stats.values())
        lines.append("-" * 70)
        lines.append("Payload Statistics")
        lines.append("-" * 70)
        lines.append(f"Total payload:  {_format_bytes(total_bytes)}")
        if self.total_messages > 0:
            lines.append(f"Avg per msg:    {total_bytes / self.total_messages:.0f} bytes")
        lines.append("")

        # Gap detection
        gaps = self.find_all_gaps(gap_threshold)
        if gaps:
            lines.append("-" * 70)
            lines.append(f"Gaps > {gap_threshold}s")
            lines.append("-" * 70)
            for gap in gaps[:20]:  # Limit to 20
                import datetime
                start_str = datetime.datetime.fromtimestamp(gap['start']).strftime('%H:%M:%S.%f')[:-3]
                lines.append(f"  {start_str}  +{gap['duration']:.1f}s")
            if len(gaps) > 20:
                lines.append(f"  ... and {len(gaps) - 20} more gaps")
            lines.append("")

        return '\n'.join(lines)

    def report_json(self, gap_threshold: float = 5.0) -> Dict:
        """Generate a JSON-serializable report."""
        topics = {}
        for topic, stats in self.topic_stats.items():
            topics[topic] = {
                'count': stats.count,
                'rate_stats': stats.rate_stats(),
                'payload_stats': stats.payload_stats(),
                'gaps': stats.find_gaps(gap_threshold),
            }

        return {
            'total_messages': self.total_messages,
            'unique_topics': len(self.topic_stats),
            'duration_seconds': self.duration,
            'overall_rate_hz': self.total_messages / self.duration if self.duration > 0 else 0,
            'topics': topics,
            'global_gaps': self.find_all_gaps(gap_threshold),
        }

    def _format_tree(self, tree: Dict, lines: List[str], indent: int):
        for key in sorted(tree.keys()):
            node = tree[key]
            count = node['_count']
            prefix = '  ' * indent
            lines.append(f"{prefix}{key}/ ({count})")
            if node['_children']:
                self._format_tree(node['_children'], lines, indent + 1)


def _format_bytes(n: float) -> str:
    for unit in ('B', 'KB', 'MB', 'GB'):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def main():
    parser = argparse.ArgumentParser(
        description='Analyze recorded MQTT traffic',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('file', help='JSONL.gz capture file to analyze')
    parser.add_argument('--gaps', type=float, default=5.0,
                        help='Gap detection threshold in seconds (default: 5.0)')
    parser.add_argument('--topic', '-t', default=None,
                        help='Filter to specific topic pattern (supports + and # wildcards)')
    parser.add_argument('--format', choices=['text', 'json'], default='text',
                        help='Output format')
    args = parser.parse_args()

    analyzer = MQTTAnalyzer()
    analyzer.load(args.file, topic_filter=args.topic)

    if args.format == 'json':
        print(json.dumps(analyzer.report_json(args.gaps), indent=2))
    else:
        print(analyzer.report(args.gaps))


if __name__ == '__main__':
    main()
