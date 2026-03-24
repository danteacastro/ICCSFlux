"""
Longevity / resiliency tests — prove months-long operation is safe.

These tests exercise edge cases that only appear after extended runtime:
counter rollover, cooldown pruning, session accumulation, CSV rotation,
notification limits, and Counter cumulative mode accuracy.

All tests run in seconds but simulate conditions equivalent to weeks/months.
"""

import os
import sys
import time
from pathlib import Path
from datetime import datetime, timedelta

import pytest

# Add service paths
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "daq_service"))
sys.path.insert(0, str(Path(__file__).parent.parent / "services"))

from crio_node_v2.script_engine import Counter
from notification_manager import (
    NotificationManager, NotificationConfig, TriggerRules,
    TwilioConfig, EmailConfig,
)
from user_session import UserSessionManager, UserRole

# =========================================================================
# 1. Counter rollover at 2^32 boundary
# =========================================================================

class TestCounterRollover:
    """Prove hardware edge count rollover is handled correctly."""

    def test_rollover_detection_basic(self):
        """Simulate a 32-bit counter wrapping from near-max to 0."""
        c = Counter(mode='cumulative')
        max_32 = 0xFFFFFFFF

        readings = [
            max_32 - 100,
            max_32 - 50,
            max_32 - 10,
            max_32,
            10,       # wrapped — negative delta skipped
            50,
            100,
        ]

        for val in readings:
            c.update(float(val))
            time.sleep(0.001)

        # Pre-rollover deltas: 50, 40, 10 = 100
        # Rollover: skipped (negative)
        # Post-rollover: 40, 50 = 90
        # Total = 190
        assert abs(c.total - 190) < 1, f"Expected ~190, got {c.total}"

    def test_rollover_no_negative_count(self):
        """Counter should never go negative from a rollover."""
        c = Counter(mode='cumulative')

        for val in [100, 200, 300, 400, 500]:
            c.update(float(val))
            time.sleep(0.001)

        count_before = c.total

        # Hardware rolls over / resets to 0
        c.update(0.0)
        time.sleep(0.001)

        assert c.total >= count_before, \
            f"Counter went backwards: {count_before} -> {c.total}"

    def test_multiple_rollovers(self):
        """Simulate multiple rollovers in sequence."""
        c = Counter(mode='cumulative')

        # First run: 0 -> 1000 (deltas sum to 1000, first reading is baseline)
        for val in range(0, 1001, 100):
            c.update(float(val))
            time.sleep(0.001)

        assert abs(c.total - 1000) < 1

        # Rollover 1: drop to 0 (skipped), then 100->500 = 400
        c.update(0.0)
        time.sleep(0.001)
        for val in range(100, 501, 100):
            c.update(float(val))
            time.sleep(0.001)

        # 1000 + 100 (0->100) + 400 (100->500) = 1500
        assert abs(c.total - 1500) < 1

        # Rollover 2: drop to 0 (skipped), then 100->300 = 200
        c.update(0.0)
        time.sleep(0.001)
        for val in range(100, 301, 100):
            c.update(float(val))
            time.sleep(0.001)

        # 1500 + 100 (0->100) + 200 (100->300) = 1800
        assert abs(c.total - 1800) < 1

    def test_large_value_near_32bit_max(self):
        """Counter works with values near 2^32."""
        c = Counter(mode='cumulative')
        base = 0xFFFFF000

        c.update(float(base))
        time.sleep(0.001)
        c.update(float(base + 1000))
        time.sleep(0.001)
        c.update(float(base + 2000))
        time.sleep(0.001)

        assert abs(c.total - 2000) < 1

# =========================================================================
# 2. Counter cumulative vs rate mode accuracy
# =========================================================================

class TestCounterModes:
    """Verify cumulative mode tracks deltas, rate mode integrates."""

    def test_cumulative_tracks_deltas(self):
        """Cumulative mode: total = sum of deltas between readings."""
        c = Counter(mode='cumulative')

        # Feed cumulative readings: 0, 10, 25, 50, 100
        # First reading (0) is baseline, deltas: 10, 15, 25, 50 = 100
        readings = [0, 10, 25, 50, 100]
        for val in readings:
            c.update(float(val))
            time.sleep(0.001)

        assert abs(c.total - 100) < 1

    def test_cumulative_handles_zero_and_one(self):
        """Cumulative mode correctly handles 0 and 1 as numeric, not bool."""
        c = Counter(mode='cumulative')

        # These values would normally route to _update_bool
        c.update(0.0)
        time.sleep(0.001)
        c.update(1.0)
        time.sleep(0.001)
        c.update(0.0)  # negative delta — skipped
        time.sleep(0.001)
        c.update(1.0)
        time.sleep(0.001)
        c.update(5.0)
        time.sleep(0.001)

        # Deltas: 1 (0->1), skip (1->0), 1 (0->1), 4 (1->5) = 6
        assert abs(c.total - 6) < 1

    def test_rate_integrates_over_time(self):
        """Rate mode: total = sum of (value * dt)."""
        c = Counter(mode='rate')

        for _ in range(11):
            c.update(100.0)
            time.sleep(0.01)

        # 100 Hz * ~0.1s = ~10 units
        assert 5 < c.total < 15, f"Expected ~10, got {c.total}"

    def test_cumulative_ignores_negative_deltas(self):
        """Cumulative mode: negative deltas (resets) are ignored."""
        c = Counter(mode='cumulative')

        c.update(100.0)
        time.sleep(0.001)
        c.update(200.0)
        time.sleep(0.001)
        c.update(50.0)   # hardware reset — skipped
        time.sleep(0.001)
        c.update(150.0)
        time.sleep(0.001)

        # Deltas: 100 (200-100), skip (50-200), 100 (150-50) = 200
        assert abs(c.total - 200) < 1

    def test_cumulative_with_target(self):
        """Cumulative mode works with target/done/batch."""
        c = Counter(mode='cumulative', target=500, auto_reset=True)

        # Feed 600 total pulses in increments of 100
        for val in range(0, 601, 100):
            c.update(float(val))
            time.sleep(0.001)

        # 600 total pulses, target=500, auto_reset — should complete at least 1 batch
        assert c.batch >= 1, "Should have completed at least one batch"

    def test_default_mode_is_rate(self):
        """Default Counter uses rate mode."""
        c = Counter()
        assert c._mode == 'rate'

# =========================================================================
# 3. Notification cooldown pruning
# =========================================================================

class TestCooldownPruning:
    """Prove cooldowns don't grow unbounded over months."""

    def _make_manager(self, tmp_path):
        mgr = NotificationManager(data_dir=tmp_path, publish_callback=None)
        config = NotificationConfig()
        config.twilio = TwilioConfig(
            enabled=True,
            account_sid='ACtest',
            auth_token='test',
            from_number='+15551234567',
            to_numbers=['+15559876543'],
            rules=TriggerRules(
                severities=['critical', 'high', 'medium', 'low'],
                event_types=['triggered'],
            ),
        )
        config.cooldown_seconds = 60
        config.daily_limit = 10000
        mgr._config = config
        return mgr

    def test_cooldowns_pruned_on_day_change(self, tmp_path):
        """Cooldowns older than 24h are removed on daily reset."""
        mgr = self._make_manager(tmp_path)

        old_time = time.monotonic() - 90000  # 25 hours ago
        for i in range(5000):
            mgr._cooldowns['twilio'][f'alarm_{i}'] = old_time

        assert len(mgr._cooldowns['twilio']) == 5000

        mgr._prune_cooldowns(time.monotonic())

        assert len(mgr._cooldowns['twilio']) == 0

    def test_recent_cooldowns_preserved(self, tmp_path):
        """Cooldowns within 24h are kept during pruning."""
        mgr = self._make_manager(tmp_path)

        now = time.monotonic()
        for i in range(100):
            mgr._cooldowns['twilio'][f'recent_{i}'] = now - 3600  # 1 hour ago

        for i in range(200):
            mgr._cooldowns['twilio'][f'stale_{i}'] = now - 90000  # 25 hours ago

        mgr._prune_cooldowns(now)

        assert len(mgr._cooldowns['twilio']) == 100
        assert all(k.startswith('recent_') for k in mgr._cooldowns['twilio'])

    def test_cooldown_growth_bounded(self, tmp_path):
        """Simulate months of alarms — cooldowns stay bounded after pruning."""
        mgr = self._make_manager(tmp_path)

        now = time.monotonic()

        for day in range(30):
            ts = now - (30 - day) * 86400
            for i in range(100):
                mgr._cooldowns['twilio'][f'day{day}_alarm{i}'] = ts

        assert len(mgr._cooldowns['twilio']) == 3000

        mgr._prune_cooldowns(now)

        # Only last 24h entries survive
        assert len(mgr._cooldowns['twilio']) <= 100

# =========================================================================
# 4. Notification daily limit and reset
# =========================================================================

class TestDailyLimitReset:
    """Prove daily limit resets at midnight and doesn't accumulate forever."""

    def _make_manager(self, tmp_path, daily_limit=5):
        mgr = NotificationManager(data_dir=tmp_path, publish_callback=None)
        config = NotificationConfig()
        config.twilio = TwilioConfig(
            enabled=True,
            account_sid='ACtest',
            auth_token='test',
            from_number='+15551234567',
            to_numbers=['+15559876543'],
            rules=TriggerRules(
                severities=['critical'],
                event_types=['triggered'],
            ),
        )
        config.cooldown_seconds = 0
        config.daily_limit = daily_limit
        mgr._config = config
        return mgr

    def test_daily_limit_blocks_after_threshold(self, tmp_path):
        """After daily_limit notifications, further ones are blocked."""
        mgr = self._make_manager(tmp_path, daily_limit=5)

        mgr._daily_count = 5
        mgr._daily_reset_date = datetime.now().strftime('%Y-%m-%d')

        result = mgr._passes_filters(
            'twilio',
            mgr._config.twilio.rules,
            'triggered',
            {'alarm_id': 'test', 'severity': 'critical', 'group': ''},
            mgr._config,
        )
        assert result is False

    def test_daily_limit_resets_on_new_day(self, tmp_path):
        """Daily count resets when date changes."""
        mgr = self._make_manager(tmp_path, daily_limit=100)

        mgr._daily_count = 999
        mgr._daily_reset_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

        result = mgr._passes_filters(
            'twilio',
            mgr._config.twilio.rules,
            'triggered',
            {'alarm_id': 'fresh_alarm', 'severity': 'critical', 'group': ''},
            mgr._config,
        )
        assert result is True
        assert mgr._daily_count == 0  # was reset

# =========================================================================
# 5. Session cleanup — no unbounded growth
# =========================================================================

class TestSessionCleanup:
    """Prove sessions don't accumulate forever."""

    def test_expired_sessions_removed(self, tmp_path):
        """cleanup_expired_sessions removes old sessions."""
        mgr = UserSessionManager(data_dir=str(tmp_path))
        # session_timeout is in MINUTES — use 0.01 min (0.6 seconds)
        mgr.session_timeout = 0.01

        # Create a test user with known password (default accounts get random passwords)
        mgr.create_user("testuser", "TestPass123!", UserRole.OPERATOR, "Test User")

        # Create a few sessions (bcrypt is slow, so keep count low)
        for i in range(3):
            mgr.authenticate("testuser", "TestPass123!", f"10.0.0.{i}")

        assert len(mgr.sessions) >= 1

        time.sleep(2)
        mgr.cleanup_expired_sessions()

        assert len(mgr.sessions) == 0, \
            f"Expected 0 sessions after cleanup, got {len(mgr.sessions)}"

    def test_active_sessions_preserved(self, tmp_path):
        """Active sessions survive cleanup while expired ones are removed."""
        mgr = UserSessionManager(data_dir=str(tmp_path))
        mgr.session_timeout = 30  # 30 minutes — plenty of time

        # Create a test user with known password
        mgr.create_user("testuser", "TestPass123!", UserRole.OPERATOR, "Test User")

        active_session = mgr.authenticate("testuser", "TestPass123!", "10.0.0.1")
        assert active_session is not None, "authenticate should succeed"
        active_id = active_session.session_id

        # Now create short-lived sessions (0.01 min = 0.6 seconds)
        mgr.session_timeout = 0.01
        for i in range(3):
            mgr.authenticate("testuser", "TestPass123!", f"10.0.0.{i+10}")

        time.sleep(2)

        # Restore long timeout and touch active session so it's not expired
        mgr.session_timeout = 30
        mgr.validate_session(active_id)

        mgr.cleanup_expired_sessions()

        # The recently-touched session should survive, short-lived ones should be gone
        assert active_id in mgr.sessions

    def test_repeated_cleanup_is_safe(self, tmp_path):
        """Calling cleanup multiple times with no sessions doesn't error."""
        mgr = UserSessionManager(data_dir=str(tmp_path))

        for _ in range(100):
            mgr.cleanup_expired_sessions()

        assert len(mgr.sessions) == 0

# =========================================================================
# 6. CSV log midnight rotation
# =========================================================================

class TestCSVMidnightRotation:
    """Prove CSV logs rotate at midnight without file handle leaks."""

    def test_date_change_closes_old_file(self):
        """Simulated date change should close old handle and open new."""
        handles_opened = []
        handles_closed = []

        class FakeLogFile:
            def __init__(self, date_str):
                self.date = date_str
                handles_opened.append(date_str)
            def flush(self):
                pass
            def close(self):
                handles_closed.append(self.date)

        log_file = None
        log_file_date = ''

        for day in ['20260201', '20260201', '20260202', '20260202', '20260203']:
            if log_file is not None and log_file_date != day:
                log_file.flush()
                log_file.close()
                log_file = None

            if log_file is None:
                log_file = FakeLogFile(day)
                log_file_date = day

        assert len(handles_opened) == 3
        assert len(handles_closed) == 2
        assert handles_opened == ['20260201', '20260202', '20260203']
        assert handles_closed == ['20260201', '20260202']

    def test_no_handle_leak_over_many_days(self):
        """Simulate 365 days of rotation — exactly 365 opens, 364 closes."""
        open_count = 0
        close_count = 0
        current_handle = None
        current_date = ''

        for day_offset in range(365):
            date_str = f'2026{(day_offset // 30 + 1):02d}{(day_offset % 30 + 1):02d}'

            if current_handle is not None and current_date != date_str:
                close_count += 1
                current_handle = None

            if current_handle is None:
                open_count += 1
                current_handle = True
                current_date = date_str

        assert open_count == 365
        assert close_count == 364

# =========================================================================
# 7. Notification filter layers
# =========================================================================

class TestNotificationFilters:
    """Test all 7 filter layers work correctly."""

    def _make_manager(self, tmp_path, **kwargs):
        mgr = NotificationManager(data_dir=tmp_path, publish_callback=None)
        config = NotificationConfig()
        config.twilio = TwilioConfig(
            enabled=True,
            account_sid='ACtest',
            auth_token='test',
            from_number='+15551234567',
            to_numbers=['+15559876543'],
            rules=TriggerRules(
                severities=kwargs.get('severities', ['critical', 'high', 'medium', 'low']),
                event_types=kwargs.get('event_types', ['triggered', 'cleared', 'acknowledged', 'alarm_flood']),
                groups=kwargs.get('groups', []),
                alarm_select_mode=kwargs.get('alarm_select_mode', 'all'),
                alarm_ids=kwargs.get('alarm_ids', []),
            ),
        )
        config.cooldown_seconds = kwargs.get('cooldown_seconds', 0)
        config.daily_limit = kwargs.get('daily_limit', 10000)
        config.quiet_hours_enabled = kwargs.get('quiet_hours_enabled', False)
        config.quiet_hours_start = kwargs.get('quiet_hours_start', '22:00')
        config.quiet_hours_end = kwargs.get('quiet_hours_end', '06:00')
        mgr._config = config
        mgr._daily_reset_date = datetime.now().strftime('%Y-%m-%d')
        return mgr

    def _check(self, mgr, event_type, data):
        """Helper to call _passes_filters with correct arg order."""
        return mgr._passes_filters(
            'twilio',
            mgr._config.twilio.rules,
            event_type,
            data,
            mgr._config,
        )

    def test_severity_filter(self, tmp_path):
        mgr = self._make_manager(tmp_path, severities=['critical'])
        assert self._check(mgr, 'triggered', {'alarm_id': 'a1', 'severity': 'critical', 'group': ''}) is True
        assert self._check(mgr, 'triggered', {'alarm_id': 'a2', 'severity': 'medium', 'group': ''}) is False

    def test_event_type_filter(self, tmp_path):
        mgr = self._make_manager(tmp_path, event_types=['triggered'])
        assert self._check(mgr, 'triggered', {'alarm_id': 'a1', 'severity': 'critical', 'group': ''}) is True
        assert self._check(mgr, 'cleared', {'alarm_id': 'a1', 'severity': 'critical', 'group': ''}) is False

    def test_group_filter(self, tmp_path):
        mgr = self._make_manager(tmp_path, groups=['Boiler', 'Cooling'])
        assert self._check(mgr, 'triggered', {'alarm_id': 'a1', 'severity': 'critical', 'group': 'Boiler'}) is True
        assert self._check(mgr, 'triggered', {'alarm_id': 'a1', 'severity': 'critical', 'group': 'Electrical'}) is False

    def test_include_only_mode(self, tmp_path):
        mgr = self._make_manager(tmp_path, alarm_select_mode='include_only', alarm_ids=['alarm_A', 'alarm_B'])
        assert self._check(mgr, 'triggered', {'alarm_id': 'alarm_A', 'severity': 'critical', 'group': ''}) is True
        assert self._check(mgr, 'triggered', {'alarm_id': 'alarm_C', 'severity': 'critical', 'group': ''}) is False

    def test_exclude_mode(self, tmp_path):
        mgr = self._make_manager(tmp_path, alarm_select_mode='exclude', alarm_ids=['noisy_alarm'])
        assert self._check(mgr, 'triggered', {'alarm_id': 'noisy_alarm', 'severity': 'critical', 'group': ''}) is False
        assert self._check(mgr, 'triggered', {'alarm_id': 'good_alarm', 'severity': 'critical', 'group': ''}) is True

    def test_cooldown_blocks_repeat(self, tmp_path):
        mgr = self._make_manager(tmp_path, cooldown_seconds=300)
        assert self._check(mgr, 'triggered', {'alarm_id': 'alarm_X', 'severity': 'critical', 'group': ''}) is True

        # Record cooldown
        mgr._cooldowns['twilio']['alarm_X'] = time.monotonic()

        assert self._check(mgr, 'triggered', {'alarm_id': 'alarm_X', 'severity': 'critical', 'group': ''}) is False

    def test_quiet_hours_blocks_non_critical(self, tmp_path):
        mgr = self._make_manager(
            tmp_path,
            severities=['critical', 'medium'],
            quiet_hours_enabled=True,
            quiet_hours_start='00:00',
            quiet_hours_end='23:59',
        )
        # Critical passes through quiet hours
        assert self._check(mgr, 'triggered', {'alarm_id': 'a1', 'severity': 'critical', 'group': ''}) is True
        # Medium blocked
        assert self._check(mgr, 'triggered', {'alarm_id': 'a2', 'severity': 'medium', 'group': ''}) is False

# =========================================================================
# 8. Hardware rollover tracking (the dict in hardware_reader)
# =========================================================================

class TestHardwareRolloverTracking:
    """Test the rollover tracking logic from hardware_reader.py."""

    def _simulate_rollover_logic(self, readings):
        """Replicate the hardware_reader rollover logic."""
        state = {'prev': 0, 'offset': 0}
        results = []

        for raw_val in readings:
            raw = int(raw_val)
            if raw < state['prev']:
                state['offset'] += 0x100000000
            state['prev'] = raw
            results.append(raw + state['offset'])

        return results

    def test_normal_counting(self):
        results = self._simulate_rollover_logic([0, 100, 200, 300])
        assert results == [0, 100, 200, 300]

    def test_single_rollover(self):
        max32 = 0xFFFFFFFF
        results = self._simulate_rollover_logic([max32 - 10, max32, 5, 15])
        assert results == [max32 - 10, max32, 0x100000000 + 5, 0x100000000 + 15]

    def test_double_rollover(self):
        max32 = 0xFFFFFFFF
        results = self._simulate_rollover_logic([
            max32 - 1, max32, 0, 100,
            max32, 0, 50,
        ])
        o1 = 0x100000000
        o2 = 0x200000000
        assert results == [max32 - 1, max32, o1, o1 + 100, o1 + max32, o2, o2 + 50]

    def test_rollover_at_1khz_50_days(self):
        max32 = 0xFFFFFFFF
        results = self._simulate_rollover_logic([max32, 1000])
        assert results[1] == 0x100000000 + 1000

    def test_rollover_monotonic(self):
        max32 = 0xFFFFFFFF
        readings = [
            0, 1000, 2000, max32 - 1000, max32,
            0, 500, 1000, max32,
            0, 100,
        ]
        results = self._simulate_rollover_logic(readings)

        for i in range(1, len(results)):
            assert results[i] >= results[i-1], \
                f"Not monotonic at index {i}: {results[i-1]} > {results[i]}"
