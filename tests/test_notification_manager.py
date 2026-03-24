"""
Unified test suite for NotificationManager.

Tests all aspects of the notification system:
  - Config dataclass construction, defaults, persistence, and edge cases
  - 7-layer filter pipeline (event type, severity, group, alarm selection,
    cooldown, daily limit, quiet hours) and multi-layer interaction
  - Twilio SMS: payload formatting, validation, API mocking, error handling
  - SMTP Email: template rendering (HTML + plain), variable substitution,
    connection mocking, error handling
  - Queue: overflow, worker delivery, daily counter, cooldown pruning
  - Channel enable/disable, test send, fallback behavior

All tests are self-contained unit tests -- no real Twilio or SMTP needed.
"""

import json
import os
import smtplib
import sys
import time
import queue
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest

# Add service paths
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "daq_service"))
sys.path.insert(0, str(Path(__file__).parent.parent / "services"))

from notification_manager import (
    NotificationManager,
    NotificationConfig,
    TriggerRules,
    TwilioConfig,
    EmailConfig,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(
    twilio_enabled=False,
    email_enabled=False,
    cooldown=300,
    daily_limit=100,
    quiet_hours=False,
    quiet_hours_start='22:00',
    quiet_hours_end='06:00',
    twilio_severities=None,
    twilio_event_types=None,
    twilio_groups=None,
    twilio_alarm_select_mode='all',
    twilio_alarm_ids=None,
    email_severities=None,
    email_event_types=None,
    email_groups=None,
    email_alarm_select_mode='all',
    email_alarm_ids=None,
) -> NotificationConfig:
    """Build a NotificationConfig with full control over trigger rules."""
    return NotificationConfig(
        twilio=TwilioConfig(
            enabled=twilio_enabled,
            account_sid='AC_test_sid',
            auth_token='test_token',
            from_number='+15551234567',
            to_numbers=['+15559876543'],
            rules=TriggerRules(
                severities=twilio_severities or ['critical', 'high', 'medium', 'low'],
                event_types=twilio_event_types or ['triggered', 'cleared', 'acknowledged', 'alarm_flood'],
                groups=twilio_groups or [],
                alarm_select_mode=twilio_alarm_select_mode,
                alarm_ids=twilio_alarm_ids or [],
            ),
        ),
        email=EmailConfig(
            enabled=email_enabled,
            smtp_host='smtp.test.com',
            smtp_port=587,
            use_tls=True,
            username='test@test.com',
            password='testpassword',
            from_address='alerts@test.com',
            to_addresses=['admin@test.com'],
            rules=TriggerRules(
                severities=email_severities or ['critical', 'high', 'medium', 'low'],
                event_types=email_event_types or ['triggered', 'cleared', 'acknowledged', 'alarm_flood'],
                groups=email_groups or [],
                alarm_select_mode=email_alarm_select_mode,
                alarm_ids=email_alarm_ids or [],
            ),
        ),
        cooldown_seconds=cooldown,
        daily_limit=daily_limit,
        quiet_hours_enabled=quiet_hours,
        quiet_hours_start=quiet_hours_start,
        quiet_hours_end=quiet_hours_end,
    )

def _alarm_data(
    alarm_id='ALARM-001',
    severity='high',
    group='Process',
    channel='TC-001',
    name=None,
    triggered_value=105.0,
    threshold_value=100.0,
    message='Test alarm triggered',
):
    """Build alarm event data dict."""
    return {
        'alarm_id': alarm_id,
        'name': name or f'Test Alarm {alarm_id}',
        'channel': channel,
        'severity': severity,
        'threshold_type': 'high',
        'threshold_value': threshold_value,
        'triggered_value': triggered_value,
        'current_value': triggered_value,
        'message': message,
        'triggered_at': datetime.now(timezone.utc).isoformat(),
        'group': group,
    }

def _make_manager(tmp_path, config=None, stop_worker=False, publish_callback=None):
    """Create a NotificationManager, optionally stopping the worker for queue inspection."""
    mgr = NotificationManager(data_dir=tmp_path, publish_callback=publish_callback)
    if stop_worker:
        mgr._running = False
        if mgr._worker:
            mgr._worker.join(timeout=3)
    if config is not None:
        with mgr._lock:
            mgr._config = config
    # Reset daily date so daily limit checks use today
    mgr._daily_reset_date = datetime.now().strftime('%Y-%m-%d')
    return mgr

def _passes(mgr, channel_name, event_type, data):
    """Helper to call _passes_filters on a specific channel."""
    with mgr._lock:
        config = mgr._config
    rules = config.twilio.rules if channel_name == 'twilio' else config.email.rules
    return mgr._passes_filters(channel_name, rules, event_type, data, config)

# =========================================================================
# 1. TestNotificationConfig — Config dataclass construction & defaults
# =========================================================================

class TestNotificationConfig:
    """Config loading, defaults, clamping, and edge cases."""

    def test_default_config_values(self):
        """Default NotificationConfig has sensible defaults."""
        cfg = NotificationConfig()
        assert cfg.twilio.enabled is False
        assert cfg.email.enabled is False
        assert cfg.cooldown_seconds == 300
        assert cfg.daily_limit == 100
        assert cfg.quiet_hours_enabled is False
        assert cfg.quiet_hours_start == '22:00'
        assert cfg.quiet_hours_end == '06:00'

    def test_default_trigger_rules(self):
        """Default TriggerRules: critical+high severity, triggered+alarm_flood events."""
        rules = TriggerRules()
        assert rules.severities == ['critical', 'high']
        assert rules.event_types == ['triggered', 'alarm_flood']
        assert rules.groups == []
        assert rules.alarm_select_mode == 'all'
        assert rules.alarm_ids == []

    def test_config_from_dict_full(self):
        """NotificationConfig.from_dict populates all fields correctly."""
        d = {
            'twilio': {
                'enabled': True,
                'account_sid': 'ACXXX',
                'auth_token': 'tok',
                'from_number': '+1555',
                'to_numbers': ['+1666', '+1777'],
                'rules': {
                    'severities': ['critical'],
                    'event_types': ['triggered'],
                    'groups': ['Boiler'],
                    'alarm_select_mode': 'include_only',
                    'alarm_ids': ['a1'],
                },
            },
            'email': {
                'enabled': True,
                'smtp_host': 'mail.example.com',
                'smtp_port': 465,
                'use_tls': False,
                'username': 'u',
                'password': 'p',
                'from_address': 'f@x.com',
                'to_addresses': ['t@x.com'],
                'rules': {},
            },
            'cooldown_seconds': 120,
            'daily_limit': 50,
            'quiet_hours_enabled': True,
            'quiet_hours_start': '23:00',
            'quiet_hours_end': '05:00',
        }
        cfg = NotificationConfig.from_dict(d)
        assert cfg.twilio.enabled is True
        assert cfg.twilio.to_numbers == ['+1666', '+1777']
        assert cfg.twilio.rules.severities == ['critical']
        assert cfg.twilio.rules.groups == ['Boiler']
        assert cfg.email.smtp_port == 465
        assert cfg.email.use_tls is False
        assert cfg.cooldown_seconds == 120
        assert cfg.daily_limit == 50
        assert cfg.quiet_hours_start == '23:00'

    def test_config_from_dict_clamps_cooldown(self):
        """Cooldown is clamped to [60, 3600]."""
        cfg = NotificationConfig.from_dict({'cooldown_seconds': 10})
        assert cfg.cooldown_seconds == 60
        cfg = NotificationConfig.from_dict({'cooldown_seconds': 99999})
        assert cfg.cooldown_seconds == 3600

    def test_config_from_dict_clamps_daily_limit(self):
        """Daily limit is clamped to [1, 1000]."""
        cfg = NotificationConfig.from_dict({'daily_limit': 0})
        assert cfg.daily_limit == 1
        cfg = NotificationConfig.from_dict({'daily_limit': 5000})
        assert cfg.daily_limit == 1000

    def test_config_from_dict_non_dict_returns_default(self):
        """Passing non-dict (None, string, list) yields default config."""
        for bad in [None, 'hello', 42, [1, 2]]:
            cfg = NotificationConfig.from_dict(bad)
            assert cfg.cooldown_seconds == 300
            assert cfg.twilio.enabled is False

    def test_trigger_rules_from_dict_non_dict_returns_default(self):
        """TriggerRules.from_dict with non-dict returns defaults."""
        rules = TriggerRules.from_dict(None)
        assert rules.severities == ['critical', 'high']
        assert rules.alarm_select_mode == 'all'

    def test_config_round_trip_to_dict_from_dict(self):
        """to_dict -> from_dict produces equivalent config."""
        original = _make_config(
            twilio_enabled=True, email_enabled=True,
            cooldown=600, daily_limit=50,
            quiet_hours=True, quiet_hours_start='21:00', quiet_hours_end='07:00',
            twilio_severities=['critical'],
            twilio_groups=['Boiler'],
            twilio_alarm_select_mode='exclude',
            twilio_alarm_ids=['noisy'],
        )
        rebuilt = NotificationConfig.from_dict(original.to_dict())
        assert rebuilt.twilio.enabled == original.twilio.enabled
        assert rebuilt.twilio.rules.severities == original.twilio.rules.severities
        assert rebuilt.twilio.rules.groups == original.twilio.rules.groups
        assert rebuilt.twilio.rules.alarm_select_mode == 'exclude'
        assert rebuilt.twilio.rules.alarm_ids == ['noisy']
        assert rebuilt.cooldown_seconds == 600
        assert rebuilt.daily_limit == 50
        assert rebuilt.quiet_hours_start == '21:00'

    def test_config_persistence_save_load(self, tmp_path):
        """Config survives save -> load cycle on disk."""
        mgr = _make_manager(tmp_path, config=_make_config(
            twilio_enabled=True, email_enabled=True, cooldown=600, daily_limit=77,
        ))
        mgr._save_config()

        mgr2 = NotificationManager(data_dir=tmp_path)
        assert mgr2._config.twilio.enabled is True
        assert mgr2._config.email.enabled is True
        assert mgr2._config.cooldown_seconds == 600
        assert mgr2._config.daily_limit == 77
        mgr.shutdown()
        mgr2.shutdown()

    def test_corrupt_config_falls_back_to_defaults(self, tmp_path):
        """Corrupted JSON on disk falls back to defaults without crash."""
        config_file = tmp_path / 'notification_config.json'
        config_file.write_text("{broken json!!")

        mgr = NotificationManager(data_dir=tmp_path)
        assert mgr._config.twilio.enabled is False
        assert mgr._config.cooldown_seconds == 300
        mgr.shutdown()

    def test_configure_method_updates_config(self, tmp_path):
        """configure() updates internal config and saves to disk."""
        published = []
        mgr = _make_manager(tmp_path, publish_callback=lambda t, d: published.append((t, d)))

        result = mgr.configure({
            'twilio': {'enabled': True, 'account_sid': 'NEW_SID', 'auth_token': 'tok',
                       'from_number': '+1', 'to_numbers': ['+2']},
            'cooldown_seconds': 120,
            'daily_limit': 25,
        })
        assert result is True
        assert mgr._config.twilio.enabled is True
        assert mgr._config.twilio.account_sid == 'NEW_SID'
        assert mgr._config.cooldown_seconds == 120
        # Check published
        assert any(t == 'notification_config' for t, _ in published)
        mgr.shutdown()

# =========================================================================
# 2. TestNotificationFiltering — 7-layer filter pipeline
# =========================================================================

class TestNotificationFiltering:
    """Test all 7 filter layers and their interactions."""

    def test_event_type_pass(self, tmp_path):
        """Event type in rules.event_types passes."""
        mgr = _make_manager(tmp_path, config=_make_config(
            twilio_enabled=True, cooldown=0, daily_limit=10000,
            twilio_event_types=['triggered'],
        ))
        assert _passes(mgr, 'twilio', 'triggered', _alarm_data()) is True

    def test_event_type_blocked(self, tmp_path):
        """Event type not in rules.event_types is blocked."""
        mgr = _make_manager(tmp_path, config=_make_config(
            twilio_enabled=True, cooldown=0, daily_limit=10000,
            twilio_event_types=['triggered'],
        ))
        assert _passes(mgr, 'twilio', 'cleared', _alarm_data()) is False
        mgr.shutdown()

    def test_severity_pass(self, tmp_path):
        """Matching severity passes."""
        mgr = _make_manager(tmp_path, config=_make_config(
            twilio_enabled=True, cooldown=0, daily_limit=10000,
            twilio_severities=['critical'],
        ))
        assert _passes(mgr, 'twilio', 'triggered', _alarm_data(severity='critical')) is True
        mgr.shutdown()

    def test_severity_blocked(self, tmp_path):
        """Non-matching severity is blocked."""
        mgr = _make_manager(tmp_path, config=_make_config(
            twilio_enabled=True, cooldown=0, daily_limit=10000,
            twilio_severities=['critical'],
        ))
        assert _passes(mgr, 'twilio', 'triggered', _alarm_data(severity='low')) is False
        mgr.shutdown()

    def test_alarm_flood_bypasses_severity(self, tmp_path):
        """alarm_flood event type always passes severity check."""
        mgr = _make_manager(tmp_path, config=_make_config(
            twilio_enabled=True, cooldown=0, daily_limit=10000,
            twilio_severities=['critical'],
            twilio_event_types=['alarm_flood'],
        ))
        # alarm_flood with 'low' severity still passes
        data = _alarm_data(severity='low')
        assert _passes(mgr, 'twilio', 'alarm_flood', data) is True
        mgr.shutdown()

    def test_group_filter_pass(self, tmp_path):
        """Matching group passes."""
        mgr = _make_manager(tmp_path, config=_make_config(
            twilio_enabled=True, cooldown=0, daily_limit=10000,
            twilio_groups=['Boiler', 'Cooling'],
        ))
        assert _passes(mgr, 'twilio', 'triggered', _alarm_data(group='Boiler')) is True
        mgr.shutdown()

    def test_group_filter_blocked(self, tmp_path):
        """Non-matching group is blocked."""
        mgr = _make_manager(tmp_path, config=_make_config(
            twilio_enabled=True, cooldown=0, daily_limit=10000,
            twilio_groups=['Boiler'],
        ))
        assert _passes(mgr, 'twilio', 'triggered', _alarm_data(group='Electrical')) is False
        mgr.shutdown()

    def test_empty_groups_passes_all(self, tmp_path):
        """Empty group list means all groups pass."""
        mgr = _make_manager(tmp_path, config=_make_config(
            twilio_enabled=True, cooldown=0, daily_limit=10000,
            twilio_groups=[],
        ))
        assert _passes(mgr, 'twilio', 'triggered', _alarm_data(group='Anything')) is True
        mgr.shutdown()

    def test_include_only_mode(self, tmp_path):
        """include_only mode only passes listed alarm_ids."""
        mgr = _make_manager(tmp_path, config=_make_config(
            twilio_enabled=True, cooldown=0, daily_limit=10000,
            twilio_alarm_select_mode='include_only',
            twilio_alarm_ids=['alarm_A', 'alarm_B'],
        ))
        assert _passes(mgr, 'twilio', 'triggered', _alarm_data(alarm_id='alarm_A')) is True
        assert _passes(mgr, 'twilio', 'triggered', _alarm_data(alarm_id='alarm_C')) is False
        mgr.shutdown()

    def test_exclude_mode(self, tmp_path):
        """exclude mode blocks listed alarm_ids."""
        mgr = _make_manager(tmp_path, config=_make_config(
            twilio_enabled=True, cooldown=0, daily_limit=10000,
            twilio_alarm_select_mode='exclude',
            twilio_alarm_ids=['noisy_alarm'],
        ))
        assert _passes(mgr, 'twilio', 'triggered', _alarm_data(alarm_id='noisy_alarm')) is False
        assert _passes(mgr, 'twilio', 'triggered', _alarm_data(alarm_id='good_alarm')) is True
        mgr.shutdown()

    def test_cooldown_blocks_repeat(self, tmp_path):
        """Same alarm within cooldown window is blocked."""
        mgr = _make_manager(tmp_path, config=_make_config(
            twilio_enabled=True, cooldown=300, daily_limit=10000,
        ))
        # First time passes
        assert _passes(mgr, 'twilio', 'triggered', _alarm_data(alarm_id='X')) is True
        # Record cooldown
        mgr._cooldowns['twilio']['X'] = time.monotonic()
        # Second time blocked
        assert _passes(mgr, 'twilio', 'triggered', _alarm_data(alarm_id='X')) is False
        mgr.shutdown()

    def test_cooldown_expires(self, tmp_path):
        """Alarm after cooldown window passes again."""
        mgr = _make_manager(tmp_path, config=_make_config(
            twilio_enabled=True, cooldown=60, daily_limit=10000,
        ))
        # Record cooldown far in the past
        mgr._cooldowns['twilio']['X'] = time.monotonic() - 120
        assert _passes(mgr, 'twilio', 'triggered', _alarm_data(alarm_id='X')) is True
        mgr.shutdown()

    def test_daily_limit_blocks(self, tmp_path):
        """Exceeding daily limit blocks notifications."""
        mgr = _make_manager(tmp_path, config=_make_config(
            twilio_enabled=True, cooldown=0, daily_limit=5,
        ))
        mgr._daily_count = 5
        assert _passes(mgr, 'twilio', 'triggered', _alarm_data(alarm_id='unique_1')) is False
        mgr.shutdown()

    def test_daily_limit_resets_on_new_day(self, tmp_path):
        """Daily counter resets when the date changes."""
        mgr = _make_manager(tmp_path, config=_make_config(
            twilio_enabled=True, cooldown=0, daily_limit=5,
        ))
        mgr._daily_count = 5
        mgr._daily_reset_date = '2020-01-01'  # Force stale date
        # Next check should reset counter
        assert _passes(mgr, 'twilio', 'triggered', _alarm_data(alarm_id='fresh')) is True
        assert mgr._daily_count == 0
        mgr.shutdown()

    def test_quiet_hours_blocks_non_critical(self, tmp_path):
        """During quiet hours, non-critical alarms are blocked."""
        mgr = _make_manager(tmp_path, config=_make_config(
            twilio_enabled=True, cooldown=0, daily_limit=10000,
            quiet_hours=True,
            quiet_hours_start='00:00',
            quiet_hours_end='23:59',
        ))
        assert _passes(mgr, 'twilio', 'triggered', _alarm_data(severity='medium')) is False
        mgr.shutdown()

    def test_quiet_hours_critical_passes(self, tmp_path):
        """During quiet hours, CRITICAL alarms still pass."""
        mgr = _make_manager(tmp_path, config=_make_config(
            twilio_enabled=True, cooldown=0, daily_limit=10000,
            quiet_hours=True,
            quiet_hours_start='00:00',
            quiet_hours_end='23:59',
        ))
        assert _passes(mgr, 'twilio', 'triggered', _alarm_data(severity='critical')) is True
        mgr.shutdown()

    def test_quiet_hours_disabled_passes_all(self, tmp_path):
        """When quiet hours are disabled, all severities pass."""
        mgr = _make_manager(tmp_path, config=_make_config(
            twilio_enabled=True, cooldown=0, daily_limit=10000,
            quiet_hours=False,
        ))
        assert _passes(mgr, 'twilio', 'triggered', _alarm_data(severity='low')) is True
        mgr.shutdown()

    def test_multi_layer_severity_and_group(self, tmp_path):
        """Both severity AND group must pass simultaneously."""
        mgr = _make_manager(tmp_path, config=_make_config(
            twilio_enabled=True, cooldown=0, daily_limit=10000,
            twilio_severities=['critical'],
            twilio_groups=['Boiler'],
        ))
        # Right severity, wrong group
        assert _passes(mgr, 'twilio', 'triggered', _alarm_data(severity='critical', group='HVAC')) is False
        # Wrong severity, right group
        assert _passes(mgr, 'twilio', 'triggered', _alarm_data(severity='low', group='Boiler')) is False
        # Both correct
        assert _passes(mgr, 'twilio', 'triggered', _alarm_data(severity='critical', group='Boiler')) is True
        mgr.shutdown()

    def test_multi_layer_cooldown_and_daily_limit(self, tmp_path):
        """Cooldown and daily limit interact independently."""
        mgr = _make_manager(tmp_path, config=_make_config(
            twilio_enabled=True, cooldown=300, daily_limit=2,
        ))
        # Use two different alarm_ids to bypass per-alarm cooldown
        assert _passes(mgr, 'twilio', 'triggered', _alarm_data(alarm_id='A1')) is True
        mgr._cooldowns['twilio']['A1'] = time.monotonic()
        mgr._daily_count = 1
        # A1 blocked by cooldown (daily limit still ok)
        assert _passes(mgr, 'twilio', 'triggered', _alarm_data(alarm_id='A1')) is False
        # A2 passes (no cooldown, daily limit not yet exceeded)
        assert _passes(mgr, 'twilio', 'triggered', _alarm_data(alarm_id='A2')) is True
        mgr._daily_count = 2
        # A3 blocked by daily limit
        assert _passes(mgr, 'twilio', 'triggered', _alarm_data(alarm_id='A3')) is False
        mgr.shutdown()

    def test_multi_layer_all_seven_pass(self, tmp_path):
        """Alarm that passes all 7 layers succeeds."""
        mgr = _make_manager(tmp_path, config=_make_config(
            twilio_enabled=True,
            cooldown=60,
            daily_limit=100,
            quiet_hours=True,
            # Quiet hours window that does NOT include current time
            quiet_hours_start='03:00',
            quiet_hours_end='03:01',
            twilio_severities=['critical', 'high'],
            twilio_event_types=['triggered'],
            twilio_groups=['Boiler'],
            twilio_alarm_select_mode='include_only',
            twilio_alarm_ids=['alarm_X'],
        ))
        data = _alarm_data(alarm_id='alarm_X', severity='critical', group='Boiler')
        assert _passes(mgr, 'twilio', 'triggered', data) is True
        mgr.shutdown()

    def test_is_quiet_hours_same_day_window(self):
        """Same-day window (e.g. 08:00-17:00)."""
        # This tests the static method directly
        now = datetime.now()
        current_minutes = now.hour * 60 + now.minute
        # Build a window that includes current time
        start_m = max(0, current_minutes - 10)
        end_m = min(23 * 60 + 59, current_minutes + 10)
        start_str = f"{start_m // 60:02d}:{start_m % 60:02d}"
        end_str = f"{end_m // 60:02d}:{end_m % 60:02d}"
        assert NotificationManager._is_quiet_hours(start_str, end_str) is True

    def test_is_quiet_hours_overnight_window(self):
        """Overnight window (e.g. 22:00-06:00) wraps around midnight."""
        # Build a window from 00:00 to 23:59 -- always inside
        assert NotificationManager._is_quiet_hours('00:00', '23:59') is True

    def test_is_quiet_hours_invalid_format(self):
        """Malformed time string returns False (no crash)."""
        assert NotificationManager._is_quiet_hours('invalid', '06:00') is False
        assert NotificationManager._is_quiet_hours('22:00', '') is False

# =========================================================================
# 3. TestTwilioSMS — SMS payload, validation, API mocking
# =========================================================================

class TestTwilioSMS:
    """Twilio SMS formatting, validation, and API error handling."""

    def test_sms_body_triggered(self):
        """Triggered alarm SMS has severity, event label, name, value, threshold."""
        body = NotificationManager._format_sms_body('triggered', _alarm_data(
            severity='critical', triggered_value=105.0, threshold_value=100.0,
        ))
        assert '[CRITICAL]' in body
        assert 'ALARM' in body
        assert 'Value=105.0' in body
        assert 'Limit=100.0' in body

    def test_sms_body_cleared(self):
        """Cleared alarm SMS shows CLEARED label, no value/limit."""
        body = NotificationManager._format_sms_body('cleared', _alarm_data(severity='high'))
        assert 'CLEARED' in body
        assert 'Value=' not in body  # value not shown for cleared

    def test_sms_body_acknowledged(self):
        """Acknowledged alarm SMS shows ACK label."""
        body = NotificationManager._format_sms_body('acknowledged', _alarm_data())
        assert 'ACK' in body

    def test_sms_body_alarm_flood(self):
        """Alarm flood SMS shows count and root cause."""
        data = {'alarm_count': 15, 'root_cause': 'Compressor failure'}
        body = NotificationManager._format_sms_body('alarm_flood', data)
        assert 'ALARM FLOOD' in body
        assert '15' in body
        assert 'Compressor failure' in body

    def test_sms_body_truncated_to_160(self):
        """SMS body is truncated to 160 characters."""
        data = _alarm_data(name='A' * 200, channel='B' * 200)
        body = NotificationManager._format_sms_body('triggered', data)
        assert len(body) <= 160

    def test_sms_body_includes_channel(self):
        """SMS body includes the channel name in parentheses."""
        body = NotificationManager._format_sms_body('triggered', _alarm_data(channel='TC-007'))
        assert '(TC-007)' in body

    def test_twilio_missing_credentials_raises(self, tmp_path):
        """Missing SID/token/from_number raises ValueError."""
        mgr = _make_manager(tmp_path)
        cfg = TwilioConfig(
            enabled=True, account_sid='', auth_token='tok',
            from_number='+1', to_numbers=['+2'],
        )
        with pytest.raises(ValueError, match="incomplete"):
            mgr._send_twilio(cfg, 'triggered', _alarm_data())
        mgr.shutdown()

    def test_twilio_no_recipients_raises(self, tmp_path):
        """Empty to_numbers raises ValueError."""
        mgr = _make_manager(tmp_path)
        cfg = TwilioConfig(
            enabled=True, account_sid='SID', auth_token='tok',
            from_number='+1', to_numbers=[],
        )
        with pytest.raises(ValueError, match="No SMS recipients"):
            mgr._send_twilio(cfg, 'triggered', _alarm_data())
        mgr.shutdown()

    @patch('notification_manager.requests.post')
    def test_twilio_api_call_correct(self, mock_post, tmp_path):
        """Twilio API is called with correct URL, auth, and payload."""
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_post.return_value = mock_resp

        mgr = _make_manager(tmp_path)
        cfg = TwilioConfig(
            enabled=True, account_sid='ACtest123', auth_token='mytoken',
            from_number='+15551234567', to_numbers=['+15559876543'],
        )
        mgr._send_twilio(cfg, 'triggered', _alarm_data())

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert 'ACtest123' in call_kwargs[0][0]  # URL contains account SID
        assert call_kwargs[1]['auth'] == ('ACtest123', 'mytoken')
        assert call_kwargs[1]['data']['From'] == '+15551234567'
        assert call_kwargs[1]['data']['To'] == '+15559876543'
        assert call_kwargs[1]['timeout'] == 10
        mgr.shutdown()

    @patch('notification_manager.requests.post')
    def test_twilio_multiple_recipients(self, mock_post, tmp_path):
        """Twilio sends to each recipient separately."""
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_post.return_value = mock_resp

        mgr = _make_manager(tmp_path)
        cfg = TwilioConfig(
            enabled=True, account_sid='ACSID', auth_token='tok',
            from_number='+1', to_numbers=['+100', '+200', '+300'],
        )
        mgr._send_twilio(cfg, 'triggered', _alarm_data())
        assert mock_post.call_count == 3

        to_numbers = [c[1]['data']['To'] for c in mock_post.call_args_list]
        assert '+100' in to_numbers
        assert '+200' in to_numbers
        assert '+300' in to_numbers
        mgr.shutdown()

    @patch('notification_manager.requests.post')
    def test_twilio_api_error_raises_runtime(self, mock_post, tmp_path):
        """Non-200/201 from Twilio API raises RuntimeError."""
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = '{"message": "Invalid credentials"}'
        mock_resp.json.return_value = {"message": "Invalid credentials"}
        mock_post.return_value = mock_resp

        mgr = _make_manager(tmp_path)
        cfg = TwilioConfig(
            enabled=True, account_sid='ACSID', auth_token='badtok',
            from_number='+1', to_numbers=['+2'],
        )
        with pytest.raises(RuntimeError, match="Twilio API error"):
            mgr._send_twilio(cfg, 'triggered', _alarm_data())
        mgr.shutdown()

    @patch('notification_manager.requests.post')
    def test_twilio_timeout_propagates(self, mock_post, tmp_path):
        """requests.post timeout exception propagates."""
        mock_post.side_effect = Exception("Connection timed out")

        mgr = _make_manager(tmp_path)
        cfg = TwilioConfig(
            enabled=True, account_sid='ACSID', auth_token='tok',
            from_number='+1', to_numbers=['+2'],
        )
        with pytest.raises(Exception, match="timed out"):
            mgr._send_twilio(cfg, 'triggered', _alarm_data())
        mgr.shutdown()

    @patch('notification_manager.requests.post')
    def test_twilio_empty_to_number_skipped(self, mock_post, tmp_path):
        """Whitespace-only to_numbers entries are skipped."""
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_post.return_value = mock_resp

        mgr = _make_manager(tmp_path)
        cfg = TwilioConfig(
            enabled=True, account_sid='ACSID', auth_token='tok',
            from_number='+1', to_numbers=['', '  ', '+1234'],
        )
        mgr._send_twilio(cfg, 'triggered', _alarm_data())
        # Only +1234 should be called
        assert mock_post.call_count == 1
        assert mock_post.call_args[1]['data']['To'] == '+1234'
        mgr.shutdown()

# =========================================================================
# 4. TestSMTPEmail — Template rendering, connection mocking, errors
# =========================================================================

class TestSMTPEmail:
    """SMTP email template rendering and send logic."""

    def test_email_subject_triggered(self):
        """Triggered alarm email subject includes severity and name."""
        subject, _ = NotificationManager._format_email('triggered', _alarm_data(
            severity='critical', name='High Temp',
        ))
        assert '[CRITICAL]' in subject
        assert 'ALARM TRIGGERED' in subject
        assert 'High Temp' in subject

    def test_email_subject_cleared(self):
        """Cleared alarm email subject shows 'Alarm Cleared'."""
        subject, _ = NotificationManager._format_email('cleared', _alarm_data(severity='high'))
        assert 'Alarm Cleared' in subject

    def test_email_html_contains_alarm_details(self):
        """HTML body contains all alarm fields."""
        data = _alarm_data(
            name='Boiler Temp', channel='TC-001', severity='HIGH',
            triggered_value=105.5, threshold_value=100.0,
            message='Temperature exceeded limit',
        )
        _, html = NotificationManager._format_email('triggered', data)
        assert 'Boiler Temp' in html
        assert 'TC-001' in html
        assert '105.5' in html
        assert '100.0' in html
        assert 'Temperature exceeded limit' in html
        assert 'ICCSFlux' in html

    def test_email_html_severity_color(self):
        """HTML body uses different colors for different severities."""
        _, html_crit = NotificationManager._format_email('triggered', _alarm_data(severity='critical'))
        _, html_low = NotificationManager._format_email('triggered', _alarm_data(severity='low'))
        # CRITICAL uses red (#d32f2f), LOW uses green (#388e3c)
        assert '#d32f2f' in html_crit
        assert '#388e3c' in html_low

    def test_email_alarm_flood_format(self):
        """Alarm flood email has special subject and body."""
        data = {'alarm_count': 10, 'root_cause': 'Pump failure', 'timestamp': '2026-02-28T12:00:00Z'}
        subject, html = NotificationManager._format_email('alarm_flood', data)
        assert 'ALARM FLOOD' in subject
        assert '10' in subject
        assert 'Pump failure' in html
        assert 'Alarm Flood Detected' in html

    def test_email_plaintext_fallback(self):
        """Plain-text email contains all alarm fields."""
        data = _alarm_data(name='Pressure High', channel='PT-001', severity='HIGH')
        plain = NotificationManager._format_email_plain('triggered', data)
        assert 'ALARM TRIGGERED' in plain
        assert 'Pressure High' in plain
        assert 'PT-001' in plain
        assert 'HIGH' in plain
        assert 'ICCSFlux' in plain

    def test_email_plaintext_alarm_flood(self):
        """Plain-text alarm flood email."""
        data = {'alarm_count': 5, 'root_cause': 'Power loss', 'timestamp': '2026-02-28T12:00:00Z'}
        plain = NotificationManager._format_email_plain('alarm_flood', data)
        assert 'ALARM FLOOD' in plain
        assert '5' in plain
        assert 'Power loss' in plain

    def test_email_missing_host_raises(self, tmp_path):
        """Missing SMTP host raises ValueError."""
        mgr = _make_manager(tmp_path)
        cfg = EmailConfig(
            enabled=True, smtp_host='', from_address='a@b.com',
            to_addresses=['c@d.com'],
        )
        with pytest.raises(ValueError, match="incomplete"):
            mgr._send_email(cfg, 'triggered', _alarm_data())
        mgr.shutdown()

    def test_email_no_recipients_raises(self, tmp_path):
        """Empty to_addresses raises ValueError."""
        mgr = _make_manager(tmp_path)
        cfg = EmailConfig(
            enabled=True, smtp_host='smtp.test.com', from_address='a@b.com',
            to_addresses=[],
        )
        with pytest.raises(ValueError, match="No email recipients"):
            mgr._send_email(cfg, 'triggered', _alarm_data())
        mgr.shutdown()

    @patch('notification_manager.smtplib.SMTP')
    def test_email_tls_starttls_called(self, mock_smtp_cls, tmp_path):
        """When use_tls=True, starttls() is called."""
        mock_smtp = MagicMock()
        mock_smtp_cls.return_value = mock_smtp

        mgr = _make_manager(tmp_path)
        cfg = EmailConfig(
            enabled=True, smtp_host='smtp.test.com', smtp_port=587,
            use_tls=True, username='user', password='pass',
            from_address='a@b.com', to_addresses=['c@d.com'],
        )
        mgr._send_email(cfg, 'triggered', _alarm_data())
        mock_smtp.starttls.assert_called_once()
        mock_smtp.login.assert_called_once_with('user', 'pass')
        mock_smtp.sendmail.assert_called_once()
        mock_smtp.quit.assert_called_once()
        mgr.shutdown()

    @patch('notification_manager.smtplib.SMTP')
    def test_email_no_tls_no_starttls(self, mock_smtp_cls, tmp_path):
        """When use_tls=False, starttls() is not called."""
        mock_smtp = MagicMock()
        mock_smtp_cls.return_value = mock_smtp

        mgr = _make_manager(tmp_path)
        cfg = EmailConfig(
            enabled=True, smtp_host='smtp.test.com', smtp_port=25,
            use_tls=False, from_address='a@b.com', to_addresses=['c@d.com'],
        )
        mgr._send_email(cfg, 'triggered', _alarm_data())
        mock_smtp.starttls.assert_not_called()
        mock_smtp.login.assert_not_called()  # No username/password set
        mock_smtp.sendmail.assert_called_once()
        mock_smtp.quit.assert_called_once()
        mgr.shutdown()

    @patch('notification_manager.smtplib.SMTP')
    def test_email_connection_failure_propagates(self, mock_smtp_cls, tmp_path):
        """SMTP connection failure raises exception."""
        mock_smtp_cls.side_effect = smtplib.SMTPConnectError(421, b'Service not available')

        mgr = _make_manager(tmp_path)
        cfg = EmailConfig(
            enabled=True, smtp_host='bad.host', smtp_port=587,
            use_tls=True, from_address='a@b.com', to_addresses=['c@d.com'],
        )
        with pytest.raises(smtplib.SMTPConnectError):
            mgr._send_email(cfg, 'triggered', _alarm_data())
        mgr.shutdown()

    @patch('notification_manager.smtplib.SMTP')
    def test_email_auth_failure_propagates(self, mock_smtp_cls, tmp_path):
        """SMTP auth failure propagates and quit is still called."""
        mock_smtp = MagicMock()
        mock_smtp.login.side_effect = smtplib.SMTPAuthenticationError(535, b'Bad credentials')
        mock_smtp_cls.return_value = mock_smtp

        mgr = _make_manager(tmp_path)
        cfg = EmailConfig(
            enabled=True, smtp_host='smtp.test.com', smtp_port=587,
            use_tls=True, username='user', password='wrong',
            from_address='a@b.com', to_addresses=['c@d.com'],
        )
        with pytest.raises(smtplib.SMTPAuthenticationError):
            mgr._send_email(cfg, 'triggered', _alarm_data())
        # quit() should still be called (finally block)
        mock_smtp.quit.assert_called_once()
        mgr.shutdown()

    @patch('notification_manager.smtplib.SMTP')
    def test_email_multipart_has_both_parts(self, mock_smtp_cls, tmp_path):
        """Email message includes both text/plain and text/html parts."""
        mock_smtp = MagicMock()
        mock_smtp_cls.return_value = mock_smtp

        mgr = _make_manager(tmp_path)
        cfg = EmailConfig(
            enabled=True, smtp_host='smtp.test.com', smtp_port=587,
            use_tls=True, from_address='sender@test.com',
            to_addresses=['admin@test.com'],
        )
        mgr._send_email(cfg, 'triggered', _alarm_data())

        # Inspect the message passed to sendmail
        sendmail_args = mock_smtp.sendmail.call_args[0]
        raw_msg = sendmail_args[2]
        assert 'text/plain' in raw_msg
        assert 'text/html' in raw_msg
        assert 'sender@test.com' in raw_msg
        assert 'admin@test.com' in raw_msg
        mgr.shutdown()

# =========================================================================
# 5. TestNotificationQueue — overflow, worker delivery, cooldown pruning
# =========================================================================

class TestNotificationQueue:
    """Queue overflow, worker delivery, daily counter, cooldown pruning."""

    def test_queue_full_drops_notification(self, tmp_path):
        """When queue is full (100), new events are dropped without crash."""
        mgr = _make_manager(tmp_path, config=_make_config(twilio_enabled=True), stop_worker=True)

        for i in range(100):
            mgr._queue.put_nowait({'channel': 'twilio', 'event_type': 'triggered', 'data': {}})
        assert mgr._queue.full()

        # Should not raise
        mgr.on_alarm_event('triggered', _alarm_data(alarm_id='OVERFLOW'))
        assert mgr._queue.qsize() == 100
        mgr.shutdown()

    def test_queue_rapid_events_no_crash(self, tmp_path):
        """200 rapid events do not crash."""
        mgr = _make_manager(tmp_path, config=_make_config(twilio_enabled=True), stop_worker=True)
        for i in range(200):
            mgr.on_alarm_event('triggered', _alarm_data(alarm_id=f'RAPID-{i}'))
        mgr.shutdown()

    @patch('notification_manager.requests.post')
    def test_worker_delivers_twilio(self, mock_post, tmp_path):
        """Worker thread picks up queued item and calls Twilio API."""
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_post.return_value = mock_resp

        mgr = _make_manager(tmp_path, config=_make_config(twilio_enabled=True, cooldown=0))
        mgr.on_alarm_event('triggered', _alarm_data(alarm_id='WORKER-TEST'))

        # Wait for worker to process
        deadline = time.monotonic() + 5
        while mgr._queue.qsize() > 0 and time.monotonic() < deadline:
            time.sleep(0.05)

        assert mock_post.called
        mgr.shutdown()

    @patch('notification_manager.smtplib.SMTP')
    def test_worker_delivers_email(self, mock_smtp_cls, tmp_path):
        """Worker thread picks up queued item and sends email."""
        mock_smtp = MagicMock()
        mock_smtp_cls.return_value = mock_smtp

        mgr = _make_manager(tmp_path, config=_make_config(email_enabled=True, cooldown=0))
        mgr.on_alarm_event('triggered', _alarm_data(alarm_id='EMAIL-WORKER'))

        deadline = time.monotonic() + 5
        while mgr._queue.qsize() > 0 and time.monotonic() < deadline:
            time.sleep(0.05)

        assert mock_smtp.sendmail.called
        mgr.shutdown()

    @patch('notification_manager.requests.post')
    def test_worker_increments_daily_count(self, mock_post, tmp_path):
        """Successful send increments daily count."""
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_post.return_value = mock_resp

        mgr = _make_manager(tmp_path, config=_make_config(twilio_enabled=True, cooldown=0))
        initial_count = mgr._daily_count

        mgr.on_alarm_event('triggered', _alarm_data(alarm_id='DAILY-COUNT'))

        deadline = time.monotonic() + 5
        while mgr._queue.qsize() > 0 and time.monotonic() < deadline:
            time.sleep(0.05)

        assert mgr._daily_count > initial_count
        mgr.shutdown()

    @patch('notification_manager.requests.post')
    def test_worker_records_cooldown(self, mock_post, tmp_path):
        """Successful send records cooldown timestamp."""
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_post.return_value = mock_resp

        mgr = _make_manager(tmp_path, config=_make_config(twilio_enabled=True, cooldown=0))
        mgr.on_alarm_event('triggered', _alarm_data(alarm_id='COOLDOWN-REC'))

        deadline = time.monotonic() + 5
        while mgr._queue.qsize() > 0 and time.monotonic() < deadline:
            time.sleep(0.05)

        assert 'COOLDOWN-REC' in mgr._cooldowns.get('twilio', {})
        mgr.shutdown()

    @patch('notification_manager.requests.post')
    def test_worker_publishes_sent_event(self, mock_post, tmp_path):
        """Successful send publishes notification_sent event."""
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_post.return_value = mock_resp

        published = []
        mgr = _make_manager(
            tmp_path,
            config=_make_config(twilio_enabled=True, cooldown=0),
            publish_callback=lambda t, d: published.append((t, d)),
        )
        mgr.on_alarm_event('triggered', _alarm_data(alarm_id='PUB-TEST'))

        deadline = time.monotonic() + 5
        while mgr._queue.qsize() > 0 and time.monotonic() < deadline:
            time.sleep(0.05)

        sent_events = [t for t, _ in published if t == 'notification_sent']
        assert len(sent_events) >= 1
        mgr.shutdown()

    @patch('notification_manager.requests.post')
    def test_worker_publishes_error_on_failure(self, mock_post, tmp_path):
        """Failed send publishes notification_error event."""
        mock_post.side_effect = Exception("Network error")

        published = []
        mgr = _make_manager(
            tmp_path,
            config=_make_config(twilio_enabled=True, cooldown=0),
            publish_callback=lambda t, d: published.append((t, d)),
        )
        mgr.on_alarm_event('triggered', _alarm_data(alarm_id='ERR-TEST'))

        deadline = time.monotonic() + 5
        while mgr._queue.qsize() > 0 and time.monotonic() < deadline:
            time.sleep(0.05)

        error_events = [t for t, _ in published if t == 'notification_error']
        assert len(error_events) >= 1
        mgr.shutdown()

    def test_cooldown_pruning(self, tmp_path):
        """Stale cooldown entries (>24h) are pruned."""
        mgr = _make_manager(tmp_path)
        now = time.monotonic()
        # Add a stale entry (>24h old) and a fresh one
        mgr._cooldowns['twilio']['old_alarm'] = now - 90000  # ~25 hours ago
        mgr._cooldowns['twilio']['fresh_alarm'] = now - 100    # 100 seconds ago

        mgr._prune_cooldowns(now)

        assert 'old_alarm' not in mgr._cooldowns['twilio']
        assert 'fresh_alarm' in mgr._cooldowns['twilio']
        mgr.shutdown()

    def test_shutdown_stops_worker(self, tmp_path):
        """shutdown() stops the background worker thread."""
        mgr = NotificationManager(data_dir=tmp_path)
        assert mgr._running is True
        assert mgr._worker.is_alive()

        mgr.shutdown()
        assert mgr._running is False
        # Give thread a moment to finish
        time.sleep(0.2)
        assert not mgr._worker.is_alive()

# =========================================================================
# 6. TestNotificationChannels — enable/disable, test send, per-channel
# =========================================================================

class TestNotificationChannels:
    """Channel enable/disable, channel-specific config, test send."""

    def test_both_disabled_skips_enqueue(self, tmp_path):
        """Both channels disabled means nothing is enqueued."""
        mgr = _make_manager(
            tmp_path,
            config=_make_config(twilio_enabled=False, email_enabled=False),
            stop_worker=True,
        )
        mgr.on_alarm_event('triggered', _alarm_data())
        assert mgr._queue.qsize() == 0
        mgr.shutdown()

    def test_only_twilio_enabled_enqueues_twilio(self, tmp_path):
        """Only the enabled Twilio channel is enqueued."""
        mgr = _make_manager(
            tmp_path,
            config=_make_config(twilio_enabled=True, email_enabled=False, cooldown=0),
            stop_worker=True,
        )
        mgr.on_alarm_event('triggered', _alarm_data())

        items = []
        while not mgr._queue.empty():
            items.append(mgr._queue.get_nowait())

        channels = [item['channel'] for item in items]
        assert 'twilio' in channels
        assert 'email' not in channels
        mgr.shutdown()

    def test_only_email_enabled_enqueues_email(self, tmp_path):
        """Only the enabled email channel is enqueued."""
        mgr = _make_manager(
            tmp_path,
            config=_make_config(twilio_enabled=False, email_enabled=True, cooldown=0),
            stop_worker=True,
        )
        mgr.on_alarm_event('triggered', _alarm_data())

        items = []
        while not mgr._queue.empty():
            items.append(mgr._queue.get_nowait())

        channels = [item['channel'] for item in items]
        assert 'email' in channels
        assert 'twilio' not in channels
        mgr.shutdown()

    def test_both_enabled_enqueues_both(self, tmp_path):
        """Both channels enabled enqueues both."""
        mgr = _make_manager(
            tmp_path,
            config=_make_config(twilio_enabled=True, email_enabled=True, cooldown=0),
            stop_worker=True,
        )
        mgr.on_alarm_event('triggered', _alarm_data())

        items = []
        while not mgr._queue.empty():
            items.append(mgr._queue.get_nowait())

        channels = [item['channel'] for item in items]
        assert 'twilio' in channels
        assert 'email' in channels
        mgr.shutdown()

    def test_channels_have_independent_rules(self, tmp_path):
        """Twilio and email can have different severity filters."""
        config = _make_config(
            twilio_enabled=True, email_enabled=True, cooldown=0,
            twilio_severities=['critical'],       # Twilio: critical only
            email_severities=['critical', 'high', 'medium', 'low'],  # Email: all
        )
        mgr = _make_manager(tmp_path, config=config, stop_worker=True)

        # Medium alarm: should pass email but not twilio
        mgr.on_alarm_event('triggered', _alarm_data(severity='medium'))

        items = []
        while not mgr._queue.empty():
            items.append(mgr._queue.get_nowait())

        channels = [item['channel'] for item in items]
        assert 'email' in channels
        assert 'twilio' not in channels
        mgr.shutdown()

    def test_test_send_unknown_channel(self, tmp_path):
        """Unknown channel returns error dict."""
        mgr = _make_manager(tmp_path)
        result = mgr.send_test_notification('carrier_pigeon')
        assert result['success'] is False
        assert 'Unknown channel' in result['message']
        mgr.shutdown()

    @patch('notification_manager.requests.post')
    def test_test_send_twilio_success(self, mock_post, tmp_path):
        """Test SMS send returns success dict."""
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_post.return_value = mock_resp

        mgr = _make_manager(tmp_path, config=_make_config(twilio_enabled=True))
        result = mgr.send_test_notification('twilio')
        assert result['success'] is True
        assert 'SMS' in result['message']
        mgr.shutdown()

    @patch('notification_manager.smtplib.SMTP')
    def test_test_send_email_success(self, mock_smtp_cls, tmp_path):
        """Test email send returns success dict."""
        mock_smtp = MagicMock()
        mock_smtp_cls.return_value = mock_smtp

        mgr = _make_manager(tmp_path, config=_make_config(email_enabled=True))
        result = mgr.send_test_notification('email')
        assert result['success'] is True
        assert 'email' in result['message']
        mgr.shutdown()

    @patch('notification_manager.requests.post')
    def test_test_send_with_config_override(self, mock_post, tmp_path):
        """Test send can use a config override dict."""
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_post.return_value = mock_resp

        mgr = _make_manager(tmp_path)
        override = {
            'twilio': {
                'enabled': True,
                'account_sid': 'OVERRIDE_SID',
                'auth_token': 'OVERRIDE_TOK',
                'from_number': '+10000000000',
                'to_numbers': ['+19999999999'],
            },
        }
        result = mgr.send_test_notification('twilio', config_override=override)
        assert result['success'] is True

        # Verify the override SID was used in the API call
        call_url = mock_post.call_args[0][0]
        assert 'OVERRIDE_SID' in call_url
        mgr.shutdown()

    @patch('notification_manager.requests.post')
    def test_test_send_failure_returns_error(self, mock_post, tmp_path):
        """Test send failure returns error dict with message."""
        mock_post.side_effect = Exception("Connection refused")

        mgr = _make_manager(tmp_path, config=_make_config(twilio_enabled=True))
        result = mgr.send_test_notification('twilio')
        assert result['success'] is False
        assert 'Connection refused' in result['message']
        mgr.shutdown()

    def test_get_config_returns_dict(self, tmp_path):
        """get_config() returns a plain dict representation."""
        mgr = _make_manager(tmp_path, config=_make_config(twilio_enabled=True, daily_limit=42))
        cfg = mgr.get_config()
        assert isinstance(cfg, dict)
        assert cfg['twilio']['enabled'] is True
        assert cfg['daily_limit'] == 42
        mgr.shutdown()
