"""
Simple time-based scheduler for NISystem DAQ
Supports scheduled start/stop of data acquisition based on time of day and day of week.
"""

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Callable, Optional, Dict, Any
import json

logger = logging.getLogger(__name__)

class SimpleScheduler:
    """
    Time-based scheduler for automated data acquisition control.

    Features:
    - Start acquisition at a specific time
    - Stop acquisition at a specific time
    - Day-of-week filtering
    - Auto-record option (start recording when acquisition starts)
    """

    def __init__(self,
                 start_callback: Callable[[], None],
                 stop_callback: Callable[[], None],
                 start_record_callback: Optional[Callable[[], None]] = None,
                 stop_record_callback: Optional[Callable[[], None]] = None):
        """
        Initialize the scheduler.

        Args:
            start_callback: Function to call when starting acquisition
            stop_callback: Function to call when stopping acquisition
            start_record_callback: Optional function to call when starting recording
            stop_record_callback: Optional function to call when stopping recording
        """
        self.start_callback = start_callback
        self.stop_callback = stop_callback
        self.start_record_callback = start_record_callback
        self.stop_record_callback = stop_record_callback

        # Schedule configuration
        self.enabled = False
        self.start_time = "08:00"  # HH:MM format
        self.stop_time = "17:00"   # HH:MM format
        self.days = ["Mon", "Tue", "Wed", "Thu", "Fri"]  # Active days
        self.auto_record = True  # Auto-start recording when acquiring

        # State tracking
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._last_start_trigger = None
        self._last_stop_trigger = None
        self._is_scheduled_running = False  # Track if we started acquisition via schedule

        # DST protection: minimum time between same triggers (prevents double-trigger during fall-back)
        self._DST_GUARD_MINUTES = 60

    def configure(self, config: Dict[str, Any]) -> None:
        """
        Configure the scheduler from a dictionary.

        Args:
            config: Dictionary with keys: enabled, start_time, stop_time, days, auto_record
        """
        with self._lock:
            if "enabled" in config:
                self.enabled = bool(config["enabled"])
            if "start_time" in config:
                self.start_time = config["start_time"]
            if "stop_time" in config:
                self.stop_time = config["stop_time"]
            if "days" in config:
                self.days = config["days"]
            if "auto_record" in config:
                self.auto_record = bool(config["auto_record"])

        logger.info(f"Scheduler configured: enabled={self.enabled}, "
                   f"start={self.start_time}, stop={self.stop_time}, "
                   f"days={self.days}, auto_record={self.auto_record}")

    def get_config(self) -> Dict[str, Any]:
        """Get current scheduler configuration."""
        with self._lock:
            return {
                "enabled": self.enabled,
                "start_time": self.start_time,
                "stop_time": self.stop_time,
                "days": list(self.days),
                "auto_record": self.auto_record
            }

    def get_status(self) -> Dict[str, Any]:
        """Get current scheduler status."""
        now = datetime.now()
        with self._lock:
            return {
                "enabled": self.enabled,
                "running": self._running,
                "is_scheduled_running": self._is_scheduled_running,
                "current_time": now.strftime("%H:%M:%S"),
                "current_day": now.strftime("%a"),
                "start_time": self.start_time,
                "stop_time": self.stop_time,
                "days": list(self.days),
                "auto_record": self.auto_record,
                "in_active_window": self._is_in_active_window(now),
                "is_active_day": self._is_active_day(now),
                "last_start_trigger": self._last_start_trigger.isoformat() if self._last_start_trigger else None,
                "last_stop_trigger": self._last_stop_trigger.isoformat() if self._last_stop_trigger else None
            }

    def _parse_time(self, time_str: str) -> tuple:
        """Parse HH:MM string to (hour, minute) tuple."""
        parts = time_str.split(":")
        return int(parts[0]), int(parts[1])

    def _is_active_day(self, dt: datetime) -> bool:
        """Check if the given datetime is on an active day."""
        day_abbrev = dt.strftime("%a")
        return day_abbrev in self.days

    def _is_in_active_window(self, dt: datetime) -> bool:
        """Check if the given datetime is within the active time window."""
        start_h, start_m = self._parse_time(self.start_time)
        stop_h, stop_m = self._parse_time(self.stop_time)

        start_minutes = start_h * 60 + start_m
        stop_minutes = stop_h * 60 + stop_m
        current_minutes = dt.hour * 60 + dt.minute

        # Handle overnight schedules (e.g., 22:00 to 06:00)
        if stop_minutes < start_minutes:
            # Overnight: active if after start OR before stop
            return current_minutes >= start_minutes or current_minutes < stop_minutes
        else:
            # Normal: active if between start and stop
            return start_minutes <= current_minutes < stop_minutes

    def _should_be_running(self, dt: datetime) -> bool:
        """Determine if acquisition should be running at the given time."""
        return self._is_active_day(dt) and self._is_in_active_window(dt)

    def _check_schedule(self) -> None:
        """Check if we need to start or stop acquisition based on schedule.

        Includes DST protection: won't re-trigger start/stop within _DST_GUARD_MINUTES
        to prevent double-triggers during DST "fall back" when clocks repeat an hour.
        """
        if not self.enabled:
            return

        now = datetime.now()
        should_run = self._should_be_running(now)

        with self._lock:
            if should_run and not self._is_scheduled_running:
                # DST guard: prevent double-trigger within guard window
                if self._last_start_trigger:
                    elapsed = (now - self._last_start_trigger).total_seconds() / 60
                    if elapsed < self._DST_GUARD_MINUTES:
                        logger.debug(f"Schedule START suppressed (DST guard: {elapsed:.1f}min < {self._DST_GUARD_MINUTES}min)")
                        return

                # Time to start
                logger.info(f"Schedule triggered START at {now.strftime('%H:%M:%S')}")
                self._last_start_trigger = now
                self._is_scheduled_running = True

                # Start acquisition
                try:
                    self.start_callback()

                    # Auto-start recording if enabled
                    if self.auto_record and self.start_record_callback:
                        self.start_record_callback()
                except Exception as e:
                    logger.error(f"Error starting scheduled acquisition: {e}")

            elif not should_run and self._is_scheduled_running:
                # DST guard: prevent double-trigger within guard window
                if self._last_stop_trigger:
                    elapsed = (now - self._last_stop_trigger).total_seconds() / 60
                    if elapsed < self._DST_GUARD_MINUTES:
                        logger.debug(f"Schedule STOP suppressed (DST guard: {elapsed:.1f}min < {self._DST_GUARD_MINUTES}min)")
                        return

                # Time to stop
                logger.info(f"Schedule triggered STOP at {now.strftime('%H:%M:%S')}")
                self._last_stop_trigger = now
                self._is_scheduled_running = False

                # Stop recording first if auto-record was on
                try:
                    if self.auto_record and self.stop_record_callback:
                        self.stop_record_callback()

                    # Stop acquisition
                    self.stop_callback()
                except Exception as e:
                    logger.error(f"Error stopping scheduled acquisition: {e}")

    def _run_loop(self) -> None:
        """Main scheduler loop - checks every 10 seconds."""
        logger.info("Scheduler loop started")

        while self._running:
            try:
                self._check_schedule()
            except Exception as e:
                logger.error(f"Error in scheduler loop: {e}")

            # Sleep for 10 seconds, but check running flag more frequently
            for _ in range(10):
                if not self._running:
                    break
                time.sleep(1)

        logger.info("Scheduler loop stopped")

    def start(self) -> None:
        """Start the scheduler background thread."""
        if self._running:
            logger.warning("Scheduler already running")
            return

        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("Scheduler started")

    def stop(self) -> None:
        """Stop the scheduler background thread."""
        if not self._running:
            return

        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None
        logger.info("Scheduler stopped")

    def enable(self) -> None:
        """Enable scheduled operation."""
        with self._lock:
            self.enabled = True
        logger.info("Scheduler enabled")

    def disable(self) -> None:
        """Disable scheduled operation."""
        with self._lock:
            self.enabled = False
            # Reset scheduled running state
            self._is_scheduled_running = False
        logger.info("Scheduler disabled")

    def set_schedule(self, start_time: str, stop_time: str,
                     days: list, auto_record: bool = True) -> None:
        """
        Set the schedule parameters.

        Args:
            start_time: Start time in HH:MM format
            stop_time: Stop time in HH:MM format
            days: List of day abbreviations (Mon, Tue, Wed, Thu, Fri, Sat, Sun)
            auto_record: Whether to auto-start recording
        """
        # Validate time format
        for time_str in [start_time, stop_time]:
            try:
                self._parse_time(time_str)
            except (ValueError, IndexError):
                raise ValueError(f"Invalid time format: {time_str}. Use HH:MM")

        # Validate days
        valid_days = {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}
        for day in days:
            if day not in valid_days:
                raise ValueError(f"Invalid day: {day}. Use Mon, Tue, Wed, Thu, Fri, Sat, Sun")

        with self._lock:
            self.start_time = start_time
            self.stop_time = stop_time
            self.days = list(days)
            self.auto_record = auto_record

        logger.info(f"Schedule set: {start_time}-{stop_time} on {days}, auto_record={auto_record}")
