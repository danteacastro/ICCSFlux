"""Tests for the universal Counter class."""

import time
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'services'))

from crio_node_v2.script_engine import Counter

class TestCounterBasic:

    def test_increment(self):
        c = Counter()
        c.increment()
        c.increment()
        c.increment()
        assert c.count == 3
        assert c.total == 3

    def test_increment_by_n(self):
        c = Counter()
        c.increment(5)
        assert c.count == 5

    def test_decrement(self):
        c = Counter()
        c.increment(10)
        c.decrement(3)
        assert c.count == 7

    def test_reset_preserves_total(self):
        c = Counter()
        c.increment(10)
        c.reset()
        assert c.count == 0
        assert c.total == 10

    def test_set(self):
        c = Counter()
        c.set(42)
        assert c.count == 42

    def test_tick(self):
        c = Counter()
        c.tick()
        c.tick()
        c.tick()
        assert c.count == 3
        assert c.total == 3

class TestCounterTarget:

    def test_done(self):
        c = Counter(target=3)
        c.increment()
        c.increment()
        assert not c.done
        c.increment()
        assert c.done

    def test_remaining(self):
        c = Counter(target=10)
        c.increment(7)
        assert c.remaining == 3

    def test_no_target(self):
        c = Counter()
        c.increment(999)
        assert not c.done
        assert c.remaining == 0

    def test_auto_reset(self):
        c = Counter(target=5, auto_reset=True)
        for _ in range(5):
            c.increment()
        assert c.count == 0
        assert c.batch == 1
        assert c.total == 5

    def test_batch_count(self):
        c = Counter(target=3, auto_reset=True)
        for _ in range(9):
            c.increment()
        assert c.batch == 3
        assert c.total == 9

    def test_target_setter(self):
        c = Counter()
        c.target = 5
        c.increment(5)
        assert c.done

class TestCounterSlidingWindow:

    def test_window_count(self):
        c = Counter(window=10)
        c.tick()
        c.tick()
        c.tick()
        assert c.window_count == 3

    def test_rate(self):
        c = Counter(window=10)
        c.tick()
        c.tick()
        # Rate should be ~0.2 events/sec (2 events in 10 sec window)
        assert c.rate > 0

    def test_events_age_out(self):
        c = Counter(window=0.1)  # 100ms window
        c.tick()
        time.sleep(0.15)
        assert c.window_count == 0  # event aged out

class TestCounterDebounce:

    def test_no_debounce(self):
        c = Counter()
        c.update(True)
        assert c.state is True

    def test_debounce_requires_stable(self):
        c = Counter(debounce=3)
        c.update(True)
        c.update(True)
        # Only 2 readings, not stable yet (need 3)
        assert not c.stable
        c.update(True)
        assert c.stable
        assert c.state is True

    def test_debounce_rejects_noise(self):
        c = Counter(debounce=3)
        c.update(False)
        c.update(False)
        c.update(False)
        assert c.state is False
        # Noisy signal
        c.update(True)
        c.update(False)
        c.update(True)
        # Should still be False (not 3 consecutive True)
        assert c.state is False

class TestCounterUpdateBool:

    def test_rising_edge_increments(self):
        c = Counter()
        c.update(False)
        c.update(True)  # rising edge
        assert c.count == 1
        c.update(True)  # no edge
        assert c.count == 1
        c.update(False)
        c.update(True)  # another rising edge
        assert c.count == 2

    def test_cycle_tracking(self):
        c = Counter()
        c.update(False)
        c.update(True)   # ON
        time.sleep(0.05)
        c.update(False)  # OFF → 1 cycle
        assert c.cycles == 1
        assert c.cycle_avg > 0
        assert c.cycle_min > 0
        assert c.cycle_max > 0

    def test_duty_cycle(self):
        c = Counter()
        c.update(True)
        time.sleep(0.05)
        c.update(True)
        # Should have some duty > 0
        assert c.duty > 0

    def test_run_time(self):
        c = Counter()
        c.update(False)
        c.update(True)
        time.sleep(0.05)
        c.update(True)
        assert c.run_time > 0
        assert c.run_hours >= 0

class TestCounterUpdateAnalog:

    def test_totalizer(self):
        c = Counter()
        # Simulate 10 GPM for ~0.05 seconds
        c.update(10.0)
        time.sleep(0.05)
        c.update(10.0)
        # total should be ~0.5 (10 * 0.05)
        assert c.total > 0.3
        assert c.total < 1.0

    def test_first_update_no_accumulation(self):
        c = Counter()
        c.update(100.0)
        assert c.total == 0  # first reading, no dt yet

class TestCounterStopwatch:

    def test_elapsed(self):
        c = Counter()
        time.sleep(0.05)
        assert c.elapsed > 0.04

    def test_lap(self):
        c = Counter()
        time.sleep(0.05)
        c.lap('phase1')
        time.sleep(0.05)
        c.lap('phase2')
        assert 'phase1' in c.laps
        assert 'phase2' in c.laps
        assert c.laps['phase1'] > 0.03
        assert c.laps['phase2'] > 0.03

    def test_reset_resets_elapsed(self):
        c = Counter()
        time.sleep(0.05)
        c.reset()
        assert c.elapsed < 0.02

class TestCounterCombined:
    """Test multiple features used simultaneously."""

    def test_batch_with_sliding_window(self):
        c = Counter(target=3, window=10, auto_reset=True)
        for _ in range(9):
            c.tick()
        assert c.batch == 3
        assert c.window_count == 9
        assert c.rate > 0

    def test_bool_with_target(self):
        c = Counter(target=2)
        c.update(False)
        c.update(True)   # edge 1
        c.update(False)
        c.update(True)   # edge 2
        assert c.done

    def test_full_scenario(self):
        """Burner counter: debounce + target + duty + cycles."""
        c = Counter(target=3, debounce=2, window=10)

        # Simulate 3 burner on/off cycles
        for _ in range(3):
            c.update(False)
            c.update(False)
            c.update(True)
            c.update(True)
            time.sleep(0.02)
            c.update(False)
            c.update(False)

        assert c.done
        assert c.cycles >= 2  # at least some complete cycles
        assert c.duty >= 0
        assert c.run_time >= 0
        assert c.elapsed > 0
