"""
Tests for MQTT Traffic Tools — Recorder, Replayer, and Analyzer.

Tests are fully self-contained using temp files and mock MQTT.
No running broker required.
"""

import base64
import gzip
import json
import os
import sys
import tempfile
import time
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))

from mqtt_recorder import MQTTRecorder, read_jsonl, read_summary
from mqtt_replay import MQTTReplayer, TopicRemapper, _load_records
from mqtt_analyzer import MQTTAnalyzer, TopicStats, _format_bytes


# ===== Helper: Write test JSONL files =====

def _write_jsonl(path: str, records: list, include_summary: bool = True):
    """Write test records to a JSONL.gz file."""
    opener = gzip.open if path.endswith('.gz') else open
    with opener(path, 'wt', encoding='utf-8') as f:
        for record in records:
            f.write(json.dumps(record) + '\n')
        if include_summary:
            summary = {
                '_summary': True,
                'total_messages': len(records),
                'duration_seconds': records[-1]['ts'] - records[0]['ts'] if len(records) >= 2 else 0,
                'topics': len(set(r['topic'] for r in records)),
            }
            f.write(json.dumps(summary) + '\n')


def _make_records(n: int, base_ts: float = 1000.0, interval: float = 0.25,
                  topic: str = 'test/data', payload: str = '{"value": 42}'):
    """Generate n test records."""
    records = []
    for i in range(n):
        records.append({
            'ts': base_ts + i * interval,
            'topic': f'{topic}',
            'payload': payload,
            'qos': 0,
            'retain': False,
        })
    return records


# ===== TopicRemapper Tests =====

class TestTopicRemapper:
    def test_no_rules(self):
        r = TopicRemapper()
        assert r.remap('test/topic') == 'test/topic'

    def test_prefix_remap(self):
        r = TopicRemapper(['iccsflux=test'])
        assert r.remap('iccsflux/nodes/1/data') == 'test/nodes/1/data'

    def test_no_match(self):
        r = TopicRemapper(['iccsflux=test'])
        assert r.remap('other/topic') == 'other/topic'

    def test_multiple_rules(self):
        r = TopicRemapper(['a=x', 'b=y'])
        assert r.remap('a/data') == 'x/data'
        assert r.remap('b/data') == 'y/data'

    def test_first_match_wins(self):
        r = TopicRemapper(['a=x', 'a=y'])
        assert r.remap('a/data') == 'x/data'

    def test_empty_rules(self):
        r = TopicRemapper([])
        assert r.remap('test/topic') == 'test/topic'

    def test_exact_match(self):
        r = TopicRemapper(['exact=replaced'])
        assert r.remap('exact') == 'replaced'


# ===== JSONL Read/Write Tests =====

class TestJsonlIO:
    def test_read_jsonl_gz(self, tmp_path):
        records = _make_records(5)
        path = str(tmp_path / 'test.jsonl.gz')
        _write_jsonl(path, records)

        loaded = list(read_jsonl(path))
        assert len(loaded) == 5
        for rec in loaded:
            assert 'ts' in rec
            assert 'topic' in rec
            assert not rec.get('_summary')

    def test_read_jsonl_plain(self, tmp_path):
        records = _make_records(3)
        path = str(tmp_path / 'test.jsonl')
        _write_jsonl(path, records)

        loaded = list(read_jsonl(path))
        assert len(loaded) == 3

    def test_read_summary(self, tmp_path):
        records = _make_records(10)
        path = str(tmp_path / 'test.jsonl.gz')
        _write_jsonl(path, records)

        summary = read_summary(path)
        assert summary is not None
        assert summary['total_messages'] == 10

    def test_read_summary_missing(self, tmp_path):
        path = str(tmp_path / 'test.jsonl.gz')
        _write_jsonl(path, _make_records(3), include_summary=False)
        summary = read_summary(path)
        assert summary is None

    def test_load_records(self, tmp_path):
        records = _make_records(7)
        path = str(tmp_path / 'test.jsonl.gz')
        _write_jsonl(path, records)

        loaded = _load_records(path)
        assert len(loaded) == 7

    def test_binary_payload(self, tmp_path):
        records = [{
            'ts': 1000.0,
            'topic': 'test/binary',
            'payload': base64.b64encode(b'\x00\x01\x02\xff').decode('ascii'),
            'encoding': 'base64',
            'qos': 0,
            'retain': False,
        }]
        path = str(tmp_path / 'test.jsonl.gz')
        _write_jsonl(path, records)

        loaded = list(read_jsonl(path))
        assert len(loaded) == 1
        assert loaded[0]['encoding'] == 'base64'
        decoded = base64.b64decode(loaded[0]['payload'])
        assert decoded == b'\x00\x01\x02\xff'


# ===== MQTTRecorder Tests (unit tests, no broker) =====

class TestMQTTRecorderUnit:
    def test_constructor_defaults(self):
        r = MQTTRecorder()
        assert r.host == 'localhost'
        assert r.port == 1883
        assert r.topics == ['#']

    def test_constructor_custom(self):
        r = MQTTRecorder(host='broker', port=8883, topics=['a/#', 'b/#'],
                         username='user', password='pass')
        assert r.host == 'broker'
        assert r.port == 8883
        assert r.topics == ['a/#', 'b/#']
        assert r.username == 'user'

    def test_initial_state(self):
        r = MQTTRecorder()
        assert r._message_count == 0
        assert r._running is False


# ===== MQTTReplayer Tests (unit tests, no broker) =====

class TestMQTTReplayerUnit:
    def test_constructor_defaults(self):
        r = MQTTReplayer()
        assert r.host == 'localhost'
        assert r.port == 1883

    def test_constructor_custom(self):
        r = MQTTReplayer(host='broker', port=8883, username='u', password='p')
        assert r.host == 'broker'


# ===== TopicStats Tests =====

class TestTopicStats:
    def test_empty(self):
        s = TopicStats('test')
        assert s.count == 0
        assert s.intervals() == []

    def test_add_single(self):
        s = TopicStats('test')
        s.add(1000.0, 100)
        assert s.count == 1
        assert s.first_ts == 1000.0
        assert s.last_ts == 1000.0

    def test_intervals(self):
        s = TopicStats('test')
        s.add(1.0, 10)
        s.add(2.0, 10)
        s.add(4.0, 10)
        ivs = s.intervals()
        assert len(ivs) == 2
        assert ivs[0] == 1.0
        assert ivs[1] == 2.0

    def test_rate_stats(self):
        s = TopicStats('test')
        for i in range(10):
            s.add(i * 0.25, 50)
        stats = s.rate_stats()
        assert stats['avg_rate_hz'] == pytest.approx(4.0, abs=0.1)
        assert stats['avg_interval'] == pytest.approx(0.25, abs=0.01)

    def test_rate_stats_empty(self):
        s = TopicStats('test')
        stats = s.rate_stats()
        assert stats['avg_rate_hz'] == 0

    def test_rate_stats_single(self):
        s = TopicStats('test')
        s.add(1.0, 10)
        stats = s.rate_stats()
        assert stats['avg_rate_hz'] == 0

    def test_payload_stats(self):
        s = TopicStats('test')
        s.add(1.0, 100)
        s.add(2.0, 200)
        s.add(3.0, 300)
        ps = s.payload_stats()
        assert ps['min_bytes'] == 100
        assert ps['max_bytes'] == 300
        assert ps['avg_bytes'] == 200
        assert ps['total_bytes'] == 600

    def test_payload_stats_empty(self):
        s = TopicStats('test')
        ps = s.payload_stats()
        assert ps['total_bytes'] == 0

    def test_find_gaps(self):
        s = TopicStats('test')
        s.add(1.0, 10)
        s.add(2.0, 10)
        s.add(12.0, 10)  # 10s gap
        s.add(13.0, 10)
        gaps = s.find_gaps(5.0)
        assert len(gaps) == 1
        assert gaps[0]['duration'] == 10.0

    def test_find_gaps_none(self):
        s = TopicStats('test')
        for i in range(10):
            s.add(i * 0.1, 10)
        gaps = s.find_gaps(5.0)
        assert len(gaps) == 0


# ===== MQTTAnalyzer Tests =====

class TestMQTTAnalyzer:
    @pytest.fixture
    def sample_file(self, tmp_path):
        records = []
        base_ts = 1000.0
        # 20 messages on topic A at 4Hz
        for i in range(20):
            records.append({
                'ts': base_ts + i * 0.25,
                'topic': 'nisystem/nodes/1/channels/batch',
                'payload': json.dumps({'values': {'TT_101': 42}}),
                'qos': 0,
                'retain': False,
            })
        # 5 messages on topic B at 1Hz
        for i in range(5):
            records.append({
                'ts': base_ts + i * 1.0,
                'topic': 'nisystem/status/system',
                'payload': json.dumps({'state': 'RUNNING'}),
                'qos': 0,
                'retain': True,
            })
        path = str(tmp_path / 'test.jsonl.gz')
        _write_jsonl(path, records)
        return path

    def test_load(self, sample_file):
        a = MQTTAnalyzer()
        a.load(sample_file)
        assert a.total_messages == 25
        assert len(a.topic_stats) == 2

    def test_duration(self, sample_file):
        a = MQTTAnalyzer()
        a.load(sample_file)
        assert a.duration > 0

    def test_topic_filter(self, sample_file):
        a = MQTTAnalyzer()
        a.load(sample_file, topic_filter='nisystem/status/#')
        assert a.total_messages == 5

    def test_topic_tree(self, sample_file):
        a = MQTTAnalyzer()
        a.load(sample_file)
        tree = a.topic_tree()
        assert 'nisystem' in tree

    def test_find_all_gaps(self, tmp_path):
        records = [
            {'ts': 1.0, 'topic': 'a', 'payload': '', 'qos': 0, 'retain': False},
            {'ts': 2.0, 'topic': 'a', 'payload': '', 'qos': 0, 'retain': False},
            {'ts': 20.0, 'topic': 'a', 'payload': '', 'qos': 0, 'retain': False},
        ]
        path = str(tmp_path / 'gaps.jsonl.gz')
        _write_jsonl(path, records)

        a = MQTTAnalyzer()
        a.load(path)
        gaps = a.find_all_gaps(5.0)
        assert len(gaps) == 1
        assert gaps[0]['duration'] == 18.0

    def test_report_text(self, sample_file):
        a = MQTTAnalyzer()
        a.load(sample_file)
        report = a.report(gap_threshold=5.0)
        assert 'Total messages: 25' in report
        assert 'MQTT Traffic Analysis' in report

    def test_report_json(self, sample_file):
        a = MQTTAnalyzer()
        a.load(sample_file)
        rj = a.report_json()
        assert rj['total_messages'] == 25
        assert 'topics' in rj

    def test_empty_file(self, tmp_path):
        path = str(tmp_path / 'empty.jsonl.gz')
        _write_jsonl(path, [], include_summary=False)
        a = MQTTAnalyzer()
        a.load(path)
        assert a.total_messages == 0
        assert a.duration == 0.0


# ===== Utility Tests =====

class TestFormatBytes:
    def test_bytes(self):
        assert 'B' in _format_bytes(500)

    def test_kilobytes(self):
        assert 'KB' in _format_bytes(2048)

    def test_megabytes(self):
        assert 'MB' in _format_bytes(5 * 1024 * 1024)

    def test_zero(self):
        assert '0.0 B' == _format_bytes(0)
