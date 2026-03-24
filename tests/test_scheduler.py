"""
Tests for scheduler.py
Covers time-based scheduling for automated acquisition start/stop.
"""

import pytest
import time
import threading
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock, patch

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "daq_service"))

from scheduler import SimpleScheduler

class TestSimpleScheduler:
    """Tests for SimpleScheduler class"""

    @pytest.fixture
    def callbacks(self):
        """Create mock callbacks"""
        return {
            'start': Mock(),
            'stop': Mock(),
            'start_record': Mock(),
            'stop_record': Mock()
        }

    @pytest.fixture
    def scheduler(self, callbacks):
        """Create a scheduler with mock callbacks"""
        return SimpleScheduler(
            start_callback=callbacks['start'],
            stop_callback=callbacks['stop'],
            start_record_callback=callbacks['start_record'],
            stop_record_callback=callbacks['stop_record']
        )

    # =========================================================================
    # INITIALIZATION TESTS
    # =========================================================================

    def test_initialization(self, scheduler):
        """Test scheduler initialization"""
        assert scheduler.enabled is False
        assert scheduler.start_time == "08:00"
        assert scheduler.stop_time == "17:00"
        assert scheduler.auto_record is True
        assert scheduler._running is False

    def test_initialization_days(self, scheduler):
        """Test default active days"""
        assert "Mon" in scheduler.days
        assert "Tue" in scheduler.days
        assert "Wed" in scheduler.days
        assert "Thu" in scheduler.days
        assert "Fri" in scheduler.days
        assert "Sat" not in scheduler.days
        assert "Sun" not in scheduler.days

    # =========================================================================
    # CONFIGURATION TESTS
    # =========================================================================

    def test_configure(self, scheduler):
        """Test configuring the scheduler"""
        scheduler.configure({
            'enabled': True,
            'start_time': '09:00',
            'stop_time': '18:00',
            'days': ['Mon', 'Wed', 'Fri'],
            'auto_record': False
        })

        assert scheduler.enabled is True
        assert scheduler.start_time == '09:00'
        assert scheduler.stop_time == '18:00'
        assert scheduler.days == ['Mon', 'Wed', 'Fri']
        assert scheduler.auto_record is False

    def test_configure_partial(self, scheduler):
        """Test partial configuration update"""
        original_stop = scheduler.stop_time

        scheduler.configure({'start_time': '10:00'})

        assert scheduler.start_time == '10:00'
        assert scheduler.stop_time == original_stop  # Unchanged

    def test_get_config(self, scheduler):
        """Test getting configuration"""
        scheduler.configure({
            'enabled': True,
            'start_time': '09:00'
        })

        config = scheduler.get_config()

        assert config['enabled'] is True
        assert config['start_time'] == '09:00'
        assert 'stop_time' in config
        assert 'days' in config

    def test_get_status(self, scheduler):
        """Test getting status"""
        status = scheduler.get_status()

        assert 'enabled' in status
        assert 'running' in status
        assert 'current_time' in status
        assert 'current_day' in status
        assert 'in_active_window' in status
        assert 'is_active_day' in status

    # =========================================================================
    # TIME PARSING TESTS
    # =========================================================================

    def test_parse_time(self, scheduler):
        """Test time parsing"""
        hour, minute = scheduler._parse_time("09:30")

        assert hour == 9
        assert minute == 30

    def test_parse_time_leading_zeros(self, scheduler):
        """Test time parsing with leading zeros"""
        hour, minute = scheduler._parse_time("08:05")

        assert hour == 8
        assert minute == 5

    def test_parse_time_midnight(self, scheduler):
        """Test parsing midnight"""
        hour, minute = scheduler._parse_time("00:00")

        assert hour == 0
        assert minute == 0

    def test_parse_time_end_of_day(self, scheduler):
        """Test parsing end of day"""
        hour, minute = scheduler._parse_time("23:59")

        assert hour == 23
        assert minute == 59

    # =========================================================================
    # ACTIVE DAY TESTS
    # =========================================================================

    def test_is_active_day_weekday(self, scheduler):
        """Test checking if weekday is active"""
        # Monday
        monday = datetime(2025, 1, 13, 10, 0)  # This is a Monday
        assert scheduler._is_active_day(monday) is True

    def test_is_active_day_weekend(self, scheduler):
        """Test checking if weekend is inactive by default"""
        # Saturday
        saturday = datetime(2025, 1, 18, 10, 0)  # This is a Saturday
        assert scheduler._is_active_day(saturday) is False

    def test_is_active_day_custom_days(self, scheduler):
        """Test with custom active days"""
        scheduler.days = ['Sat', 'Sun']

        saturday = datetime(2025, 1, 18, 10, 0)
        monday = datetime(2025, 1, 13, 10, 0)

        assert scheduler._is_active_day(saturday) is True
        assert scheduler._is_active_day(monday) is False

    # =========================================================================
    # ACTIVE WINDOW TESTS
    # =========================================================================

    def test_is_in_active_window_inside(self, scheduler):
        """Test checking time inside active window"""
        scheduler.start_time = "08:00"
        scheduler.stop_time = "17:00"

        # 10:00 is inside 08:00-17:00
        dt = datetime(2025, 1, 15, 10, 0)
        assert scheduler._is_in_active_window(dt) is True

    def test_is_in_active_window_before_start(self, scheduler):
        """Test checking time before start"""
        scheduler.start_time = "08:00"
        scheduler.stop_time = "17:00"

        # 07:00 is before 08:00
        dt = datetime(2025, 1, 15, 7, 0)
        assert scheduler._is_in_active_window(dt) is False

    def test_is_in_active_window_after_stop(self, scheduler):
        """Test checking time after stop"""
        scheduler.start_time = "08:00"
        scheduler.stop_time = "17:00"

        # 18:00 is after 17:00
        dt = datetime(2025, 1, 15, 18, 0)
        assert scheduler._is_in_active_window(dt) is False

    def test_is_in_active_window_at_start(self, scheduler):
        """Test checking time exactly at start"""
        scheduler.start_time = "08:00"
        scheduler.stop_time = "17:00"

        dt = datetime(2025, 1, 15, 8, 0)
        assert scheduler._is_in_active_window(dt) is True

    def test_is_in_active_window_at_stop(self, scheduler):
        """Test checking time exactly at stop (should be inactive)"""
        scheduler.start_time = "08:00"
        scheduler.stop_time = "17:00"

        dt = datetime(2025, 1, 15, 17, 0)
        assert scheduler._is_in_active_window(dt) is False

    def test_is_in_active_window_overnight(self, scheduler):
        """Test overnight schedule (e.g., 22:00 to 06:00)"""
        scheduler.start_time = "22:00"
        scheduler.stop_time = "06:00"

        # 23:00 should be active (after start)
        dt1 = datetime(2025, 1, 15, 23, 0)
        assert scheduler._is_in_active_window(dt1) is True

        # 02:00 should be active (before stop)
        dt2 = datetime(2025, 1, 15, 2, 0)
        assert scheduler._is_in_active_window(dt2) is True

        # 12:00 should be inactive
        dt3 = datetime(2025, 1, 15, 12, 0)
        assert scheduler._is_in_active_window(dt3) is False

    # =========================================================================
    # SCHEDULE DECISION TESTS
    # =========================================================================

    def test_should_be_running_active(self, scheduler):
        """Test should_be_running when active"""
        scheduler.start_time = "08:00"
        scheduler.stop_time = "17:00"
        scheduler.days = ["Wed"]  # Wednesday

        # Wednesday 10:00
        dt = datetime(2025, 1, 15, 10, 0)  # This is a Wednesday
        assert scheduler._should_be_running(dt) is True

    def test_should_be_running_inactive_time(self, scheduler):
        """Test should_be_running when time is inactive"""
        scheduler.start_time = "08:00"
        scheduler.stop_time = "17:00"
        scheduler.days = ["Wed"]

        # Wednesday 20:00 (outside time window)
        dt = datetime(2025, 1, 15, 20, 0)
        assert scheduler._should_be_running(dt) is False

    def test_should_be_running_inactive_day(self, scheduler):
        """Test should_be_running when day is inactive"""
        scheduler.start_time = "08:00"
        scheduler.stop_time = "17:00"
        scheduler.days = ["Mon", "Tue"]

        # Wednesday 10:00 (wrong day)
        dt = datetime(2025, 1, 15, 10, 0)  # Wednesday
        assert scheduler._should_be_running(dt) is False

    # =========================================================================
    # SET SCHEDULE TESTS
    # =========================================================================

    def test_set_schedule(self, scheduler):
        """Test setting schedule"""
        scheduler.set_schedule(
            start_time="09:00",
            stop_time="18:00",
            days=["Mon", "Wed", "Fri"],
            auto_record=False
        )

        assert scheduler.start_time == "09:00"
        assert scheduler.stop_time == "18:00"
        assert scheduler.days == ["Mon", "Wed", "Fri"]
        assert scheduler.auto_record is False

    def test_set_schedule_invalid_time_format(self, scheduler):
        """Test setting schedule with invalid time format"""
        with pytest.raises(ValueError):
            scheduler.set_schedule(
                start_time="invalid",
                stop_time="18:00",
                days=["Mon"]
            )

    def test_set_schedule_invalid_day(self, scheduler):
        """Test setting schedule with invalid day"""
        with pytest.raises(ValueError):
            scheduler.set_schedule(
                start_time="09:00",
                stop_time="18:00",
                days=["Monday"]  # Should be "Mon"
            )

    # =========================================================================
    # ENABLE/DISABLE TESTS
    # =========================================================================

    def test_enable(self, scheduler):
        """Test enabling scheduler"""
        scheduler.enable()

        assert scheduler.enabled is True

    def test_disable(self, scheduler):
        """Test disabling scheduler"""
        scheduler.enabled = True
        scheduler._is_scheduled_running = True

        scheduler.disable()

        assert scheduler.enabled is False
        assert scheduler._is_scheduled_running is False

    # =========================================================================
    # START/STOP TESTS
    # =========================================================================

    def test_start(self, scheduler):
        """Test starting scheduler thread"""
        scheduler.start()

        assert scheduler._running is True
        assert scheduler._thread is not None

        scheduler.stop()

    def test_start_already_running(self, scheduler):
        """Test starting when already running"""
        scheduler.start()
        scheduler.start()  # Should not error

        assert scheduler._running is True

        scheduler.stop()

    def test_stop(self, scheduler):
        """Test stopping scheduler thread"""
        scheduler.start()
        scheduler.stop()

        assert scheduler._running is False
        assert scheduler._thread is None

    def test_stop_not_running(self, scheduler):
        """Test stopping when not running"""
        scheduler.stop()  # Should not error

        assert scheduler._running is False

    # =========================================================================
    # CALLBACK TESTS
    # =========================================================================

    def test_check_schedule_triggers_start(self, scheduler, callbacks):
        """Test that check_schedule triggers start callback"""
        # Configure to be active now
        now = datetime.now()
        scheduler.enabled = True
        scheduler.start_time = (now - timedelta(hours=1)).strftime("%H:%M")
        scheduler.stop_time = (now + timedelta(hours=1)).strftime("%H:%M")
        scheduler.days = [now.strftime("%a")]

        scheduler._check_schedule()

        callbacks['start'].assert_called_once()

    def test_check_schedule_triggers_stop(self, scheduler, callbacks):
        """Test that check_schedule triggers stop callback"""
        # Configure to be active, then mark as scheduled running
        now = datetime.now()
        scheduler.enabled = True
        scheduler.start_time = (now + timedelta(hours=1)).strftime("%H:%M")
        scheduler.stop_time = (now + timedelta(hours=2)).strftime("%H:%M")
        scheduler.days = [now.strftime("%a")]
        scheduler._is_scheduled_running = True  # Pretend we started earlier

        scheduler._check_schedule()

        callbacks['stop'].assert_called_once()

    def test_check_schedule_triggers_auto_record(self, scheduler, callbacks):
        """Test that auto_record starts recording with acquisition"""
        now = datetime.now()
        scheduler.enabled = True
        scheduler.auto_record = True
        scheduler.start_time = (now - timedelta(hours=1)).strftime("%H:%M")
        scheduler.stop_time = (now + timedelta(hours=1)).strftime("%H:%M")
        scheduler.days = [now.strftime("%a")]

        scheduler._check_schedule()

        callbacks['start'].assert_called_once()
        callbacks['start_record'].assert_called_once()

    def test_check_schedule_stops_recording_with_acquisition(self, scheduler, callbacks):
        """Test that stopping acquisition stops recording"""
        now = datetime.now()
        scheduler.enabled = True
        scheduler.auto_record = True
        scheduler.start_time = (now + timedelta(hours=1)).strftime("%H:%M")
        scheduler.stop_time = (now + timedelta(hours=2)).strftime("%H:%M")
        scheduler.days = [now.strftime("%a")]
        scheduler._is_scheduled_running = True

        scheduler._check_schedule()

        callbacks['stop_record'].assert_called_once()
        callbacks['stop'].assert_called_once()

    def test_check_schedule_not_enabled(self, scheduler, callbacks):
        """Test that disabled scheduler doesn't trigger callbacks"""
        scheduler.enabled = False

        scheduler._check_schedule()

        callbacks['start'].assert_not_called()
        callbacks['stop'].assert_not_called()

    def test_check_schedule_callback_error_handled(self, scheduler, callbacks):
        """Test that callback errors are handled"""
        callbacks['start'].side_effect = Exception("Test error")

        now = datetime.now()
        scheduler.enabled = True
        scheduler.start_time = (now - timedelta(hours=1)).strftime("%H:%M")
        scheduler.stop_time = (now + timedelta(hours=1)).strftime("%H:%M")
        scheduler.days = [now.strftime("%a")]

        # Should not raise
        scheduler._check_schedule()

    # =========================================================================
    # TRIGGER TRACKING TESTS
    # =========================================================================

    def test_last_start_trigger_recorded(self, scheduler, callbacks):
        """Test that last start trigger time is recorded"""
        now = datetime.now()
        scheduler.enabled = True
        scheduler.start_time = (now - timedelta(hours=1)).strftime("%H:%M")
        scheduler.stop_time = (now + timedelta(hours=1)).strftime("%H:%M")
        scheduler.days = [now.strftime("%a")]

        scheduler._check_schedule()

        assert scheduler._last_start_trigger is not None

    def test_last_stop_trigger_recorded(self, scheduler, callbacks):
        """Test that last stop trigger time is recorded"""
        now = datetime.now()
        scheduler.enabled = True
        scheduler.start_time = (now + timedelta(hours=1)).strftime("%H:%M")
        scheduler.stop_time = (now + timedelta(hours=2)).strftime("%H:%M")
        scheduler.days = [now.strftime("%a")]
        scheduler._is_scheduled_running = True

        scheduler._check_schedule()

        assert scheduler._last_stop_trigger is not None

    # =========================================================================
    # THREAD SAFETY TESTS
    # =========================================================================

    def test_configure_thread_safe(self, scheduler):
        """Test that configure is thread-safe"""
        errors = []

        def configure_loop():
            try:
                for i in range(100):
                    scheduler.configure({'start_time': f'{8 + (i % 4):02d}:00'})
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=configure_loop) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
