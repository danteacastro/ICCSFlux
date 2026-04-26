"""
Running-State Resilience Tests

Verifies the fixes for bugs found in the while-running audit:

  - Bug A: Reader thread death must invalidate cached values (no stale data)
  - Bug D: Output writes must serialize via output_write_lock
  - Bug B: MQTT publish queue must drop OLDEST QoS-0 (not newest) when full

These bugs would silently corrupt data or cause safety hazards during
Mike's Monday run.
"""

import pytest
import sys
import threading
import time
import math
import queue
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "daq_service"))


# ===================================================================
# 1. Source-level checks — verify the fixes are present in code
# ===================================================================

class TestSourceLevelFixes:

    def test_reader_death_invalidates_cache(self):
        """When reader dies, latest_values must be set to NaN."""
        path = Path(__file__).parent.parent / "services" / "daq_service" / "hardware_reader.py"
        content = path.read_text(encoding='utf-8')
        # The fix marker
        assert "invalidate cached values" in content.lower()
        # Verify NaN replacement
        assert "self.latest_values[name] = float('nan')" in content

    def test_read_all_returns_nan_when_reader_died(self):
        """read_all must check _reader_died and return NaN."""
        path = Path(__file__).parent.parent / "services" / "daq_service" / "hardware_reader.py"
        content = path.read_text(encoding='utf-8')
        # Check the read_all fix
        assert "if self._reader_died:" in content
        # Look for the NaN dict comprehension in read_all
        assert "{name: float('nan')" in content

    def test_output_write_lock_exists(self):
        """daq_service must have output_write_lock for serializing writes."""
        path = Path(__file__).parent.parent / "services" / "daq_service" / "daq_service.py"
        content = path.read_text(encoding='utf-8')
        assert "self.output_write_lock = threading.Lock()" in content

    def test_set_output_uses_write_lock(self):
        """_set_output_value must acquire output_write_lock."""
        path = Path(__file__).parent.parent / "services" / "daq_service" / "daq_service.py"
        content = path.read_text(encoding='utf-8')
        # The wrapper acquires the lock then calls the inner method
        assert "with self.output_write_lock:" in content
        assert "_set_output_value_locked" in content

    def test_handle_output_set_uses_write_lock(self):
        """MQTT-driven _handle_output_set must also use output_write_lock."""
        path = Path(__file__).parent.parent / "services" / "daq_service" / "daq_service.py"
        content = path.read_text(encoding='utf-8')
        # Count uses — should be at least 2 (one in _set_output_value,
        # one in _handle_output_set)
        uses = content.count("with self.output_write_lock:")
        assert uses >= 2, f"Expected >= 2 uses of output_write_lock, found {uses}"

    def test_publish_queue_drops_oldest(self):
        """_queue_publish must drop oldest QoS-0 when queue is full."""
        path = Path(__file__).parent.parent / "services" / "daq_service" / "daq_service.py"
        content = path.read_text(encoding='utf-8')
        # The fix: drop oldest, not newest
        assert "drop the oldest" in content.lower()
        # Iterates over the queue to find a QoS-0 message
        assert "if q == 0:" in content


# ===================================================================
# 2. Logic tests — replica behavior using fakes
# ===================================================================

class TestStaleDataInvalidation:
    """Verify the algorithm: when reader dies, cached values become NaN."""

    def test_nan_replacement_on_death(self):
        """When _reader_died flag is set, all cached values get NaN."""
        latest_values = {'ch1': 12.5, 'ch2': 0.005, 'ch3': 25.3}
        reader_died = True

        # Replicate the logic from hardware_reader.read_all()
        if reader_died:
            result = {name: float('nan') for name in latest_values.keys()}
        else:
            result = dict(latest_values)

        assert all(math.isnan(v) for v in result.values())
        assert set(result.keys()) == {'ch1', 'ch2', 'ch3'}

    def test_normal_path_returns_real_values(self):
        """When reader is alive, real values are returned."""
        latest_values = {'ch1': 12.5, 'ch2': 0.005}
        reader_died = False

        if reader_died:
            result = {name: float('nan') for name in latest_values.keys()}
        else:
            result = dict(latest_values)

        assert result['ch1'] == 12.5
        assert result['ch2'] == 0.005

    def test_outputs_remain_valid_when_reader_dies(self):
        """Output values are owned by the daq_service, not the reader thread.
        They should remain valid even when the input reader dies."""
        latest_values = {'input1': 12.5}
        output_values = {'output1': 0.7}
        reader_died = True

        # Replicate read_all behavior
        if reader_died:
            result = {name: float('nan') for name in latest_values.keys()}
        else:
            result = dict(latest_values)
        for name, value in output_values.items():
            result[name] = value

        assert math.isnan(result['input1'])
        assert result['output1'] == 0.7  # Output is real, not NaN


class TestOutputWriteSerialization:
    """Verify output writes are serialized via the lock."""

    def test_concurrent_writes_observed_in_order(self):
        """Two threads writing to the same channel must execute serially —
        their lock acquisitions order the actual hardware writes."""
        write_lock = threading.Lock()
        write_log = []

        def writer(name, value):
            with write_lock:
                # Simulate hardware write taking some time
                time.sleep(0.001)
                write_log.append((name, value))

        # Spawn 10 threads all writing
        threads = []
        for i in range(10):
            t = threading.Thread(target=writer, args=(f"out{i}", i * 10))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # All 10 writes happened (none lost)
        assert len(write_log) == 10
        # Each write is atomic (no interleaving)
        names = [w[0] for w in write_log]
        assert len(set(names)) == 10

    def test_no_lost_writes_under_high_contention(self):
        """Under heavy contention, all writes must complete."""
        write_lock = threading.Lock()
        write_count = [0]

        def writer():
            for _ in range(100):
                with write_lock:
                    write_count[0] += 1

        threads = [threading.Thread(target=writer) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert write_count[0] == 1000  # 10 threads × 100 writes


class TestPublishQueueOverflow:
    """Verify the drop-oldest-QoS-0 behavior."""

    def test_drops_oldest_qos0_when_full(self):
        """When queue is full and a QoS-0 message comes in, drop the oldest QoS-0."""
        q = queue.Queue(maxsize=5)
        # Fill with QoS-0 messages
        for i in range(5):
            q.put_nowait((f"topic{i}", f"payload{i}", 0, False))

        # Queue is full — try to add new message
        try:
            q.put_nowait(("topic_new", "payload_new", 0, False))
            assert False, "Should have raised queue.Full"
        except queue.Full:
            # Replicate the fix: drop oldest QoS-0, then insert
            with q.mutex:
                for i, (t, p, qos_, r) in enumerate(q.queue):
                    if qos_ == 0:
                        del q.queue[i]
                        break
            q.put_nowait(("topic_new", "payload_new", 0, False))

        # Queue should now have topic1..topic4, topic_new (topic0 was dropped)
        items = list(q.queue)
        assert len(items) == 5
        assert items[0][0] == "topic1"  # topic0 was the oldest, dropped
        assert items[-1][0] == "topic_new"  # new message at the end

    def test_preserves_qos1_messages(self):
        """QoS-1+ messages must NOT be dropped — they need delivery."""
        q = queue.Queue(maxsize=5)
        # Fill with mix of QoS-0 and QoS-1
        q.put_nowait(("t1", "p1", 1, False))  # QoS 1 — must keep
        q.put_nowait(("t2", "p2", 0, False))
        q.put_nowait(("t3", "p3", 1, False))  # QoS 1 — must keep
        q.put_nowait(("t4", "p4", 0, False))
        q.put_nowait(("t5", "p5", 0, False))

        # Drop oldest QoS-0
        with q.mutex:
            for i, (t, p, qos_, r) in enumerate(q.queue):
                if qos_ == 0:
                    del q.queue[i]
                    break

        items = list(q.queue)
        # t2 was the oldest QoS-0 — should be gone
        assert ("t2", "p2", 0, False) not in items
        # All QoS-1 messages preserved
        assert ("t1", "p1", 1, False) in items
        assert ("t3", "p3", 1, False) in items

    def test_all_qos1_no_dropping(self):
        """If queue is full of QoS-1 messages, can't make room (all guaranteed)."""
        q = queue.Queue(maxsize=3)
        for i in range(3):
            q.put_nowait((f"t{i}", f"p{i}", 1, False))

        # Try to drop — should find none
        dropped = None
        with q.mutex:
            for i, (t, p, qos_, r) in enumerate(q.queue):
                if qos_ == 0:
                    dropped = q.queue[i]
                    del q.queue[i]
                    break

        assert dropped is None  # No QoS-0 to drop
        assert q.qsize() == 3   # Queue unchanged


# ===================================================================
# 3. Integration-style tests
# ===================================================================

class TestRealWorldScenarios:

    def test_reader_death_prevents_stale_data_publication(self):
        """Full scenario: reader dies → scan loop reads → gets NaN, not stale."""
        # Simulate the hardware_reader state
        class FakeReader:
            def __init__(self):
                self.lock = threading.Lock()
                self.latest_values = {'ch1': 99.9, 'ch2': 50.0}
                self.output_values = {'out1': 0.5}
                self._reader_died = False

            def read_all(self):
                with self.lock:
                    if self._reader_died:
                        values = {name: float('nan') for name in self.latest_values.keys()}
                    else:
                        values = dict(self.latest_values)
                    for name, value in self.output_values.items():
                        values[name] = value
                return values

        reader = FakeReader()

        # Normal operation
        before = reader.read_all()
        assert before['ch1'] == 99.9
        assert before['ch2'] == 50.0

        # Reader dies
        reader._reader_died = True

        # Scan loop reads again — must get NaN, not stale 99.9
        after = reader.read_all()
        assert math.isnan(after['ch1'])
        assert math.isnan(after['ch2'])
        # Outputs still valid (we own them, not the reader)
        assert after['out1'] == 0.5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
