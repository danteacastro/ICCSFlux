"""
Notification Manager — Twilio SMS + Email (SMTP)

Sends alarm notifications with granular trigger rules per channel.
Each channel (SMS/Email) has independent filtering:
  - Severity levels
  - Event types (triggered, cleared, acknowledged, alarm_flood)
  - Alarm groups
  - Per-alarm include/exclude selection

Rate limiting:
  - Per-alarm cooldown (same alarm can't re-trigger within window)
  - Daily global limit (resets at midnight)
  - Quiet hours (suppresses non-CRITICAL alarms)

Architecture:
  - Background worker thread processes queue — never blocks scan loop
  - Twilio via requests.post() to REST API (no SDK)
  - Email via stdlib smtplib + email.mime
  - Config persisted to data/notification_config.json
"""

import json
import logging
import os
import queue
import smtplib
import stat
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import requests

logger = logging.getLogger('DAQService')

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TriggerRules:
    """Per-channel filtering rules for alarm notifications."""
    severities: List[str] = field(default_factory=lambda: ['critical', 'high'])
    event_types: List[str] = field(default_factory=lambda: ['triggered', 'alarm_flood'])
    groups: List[str] = field(default_factory=list)           # empty = all groups
    alarm_select_mode: str = 'all'                             # 'all' | 'include_only' | 'exclude'
    alarm_ids: List[str] = field(default_factory=list)         # for include_only / exclude

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> 'TriggerRules':
        if not isinstance(d, dict):
            return cls()
        return cls(
            severities=[s.lower() for s in d.get('severities', ['critical', 'high'])],
            event_types=d.get('event_types', ['triggered', 'alarm_flood']),
            groups=d.get('groups', []),
            alarm_select_mode=d.get('alarm_select_mode', 'all'),
            alarm_ids=d.get('alarm_ids', []),
        )


@dataclass
class TwilioConfig:
    """Twilio SMS channel configuration."""
    enabled: bool = False
    account_sid: str = ''
    auth_token: str = ''
    from_number: str = ''
    to_numbers: List[str] = field(default_factory=list)
    rules: TriggerRules = field(default_factory=TriggerRules)

    def to_dict(self) -> dict:
        d = asdict(self)
        d['rules'] = self.rules.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> 'TwilioConfig':
        if not isinstance(d, dict):
            return cls()
        return cls(
            enabled=d.get('enabled', False),
            account_sid=d.get('account_sid', ''),
            auth_token=d.get('auth_token', ''),
            from_number=d.get('from_number', ''),
            to_numbers=d.get('to_numbers', []),
            rules=TriggerRules.from_dict(d.get('rules', {})),
        )


@dataclass
class EmailConfig:
    """SMTP email channel configuration."""
    enabled: bool = False
    smtp_host: str = ''
    smtp_port: int = 587
    use_tls: bool = True
    username: str = ''
    password: str = ''
    from_address: str = ''
    to_addresses: List[str] = field(default_factory=list)
    rules: TriggerRules = field(default_factory=TriggerRules)

    def to_dict(self) -> dict:
        d = asdict(self)
        d['rules'] = self.rules.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> 'EmailConfig':
        if not isinstance(d, dict):
            return cls()
        return cls(
            enabled=d.get('enabled', False),
            smtp_host=d.get('smtp_host', ''),
            smtp_port=d.get('smtp_port', 587),
            use_tls=d.get('use_tls', True),
            username=d.get('username', ''),
            password=d.get('password', ''),
            from_address=d.get('from_address', ''),
            to_addresses=d.get('to_addresses', []),
            rules=TriggerRules.from_dict(d.get('rules', {})),
        )


@dataclass
class NotificationConfig:
    """Top-level notification configuration."""
    twilio: TwilioConfig = field(default_factory=TwilioConfig)
    email: EmailConfig = field(default_factory=EmailConfig)
    cooldown_seconds: int = 300     # per-alarm cooldown
    daily_limit: int = 100          # global daily cap
    quiet_hours_enabled: bool = False
    quiet_hours_start: str = '22:00'
    quiet_hours_end: str = '06:00'

    def to_dict(self) -> dict:
        return {
            'twilio': self.twilio.to_dict(),
            'email': self.email.to_dict(),
            'cooldown_seconds': self.cooldown_seconds,
            'daily_limit': self.daily_limit,
            'quiet_hours_enabled': self.quiet_hours_enabled,
            'quiet_hours_start': self.quiet_hours_start,
            'quiet_hours_end': self.quiet_hours_end,
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'NotificationConfig':
        if not isinstance(d, dict):
            return cls()
        return cls(
            twilio=TwilioConfig.from_dict(d.get('twilio', {})),
            email=EmailConfig.from_dict(d.get('email', {})),
            cooldown_seconds=max(60, min(3600, d.get('cooldown_seconds', 300))),
            daily_limit=max(1, min(1000, d.get('daily_limit', 100))),
            quiet_hours_enabled=d.get('quiet_hours_enabled', False),
            quiet_hours_start=d.get('quiet_hours_start', '22:00'),
            quiet_hours_end=d.get('quiet_hours_end', '06:00'),
        )


# ---------------------------------------------------------------------------
# Notification Manager
# ---------------------------------------------------------------------------

class NotificationManager:
    """
    Manages alarm notification delivery via Twilio SMS and SMTP email.

    Thread-safe: alarm events are enqueued and processed by a background
    worker so the scan loop is never blocked.
    """

    def __init__(
        self,
        data_dir: Path,
        publish_callback: Optional[Callable] = None,
    ):
        self._data_dir = Path(data_dir)
        self._config_path = self._data_dir / 'notification_config.json'
        self._publish = publish_callback

        self._config = NotificationConfig()
        self._lock = threading.Lock()

        # Rate limiting state
        self._cooldowns: Dict[str, Dict[str, float]] = {
            'twilio': {},
            'email': {},
        }
        self._daily_count: int = 0
        self._daily_reset_date: str = ''

        # Background worker
        self._queue: queue.Queue = queue.Queue(maxsize=100)
        self._running = False
        self._worker: Optional[threading.Thread] = None

        # Load persisted config
        self._load_config()

        # Start worker
        self._start_worker()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def on_alarm_event(self, event_type: str, data: dict):
        """
        Called by DAQ service when an alarm event occurs.

        Args:
            event_type: 'triggered', 'cleared', 'acknowledged', 'alarm_flood'
            data: Alarm event data (ActiveAlarm.to_dict() enriched with 'group')
        """
        with self._lock:
            config = self._config

        if not config.twilio.enabled and not config.email.enabled:
            return

        # Check each channel independently
        for channel_name, channel_cfg in [('twilio', config.twilio), ('email', config.email)]:
            if not channel_cfg.enabled:
                continue

            if not self._passes_filters(channel_name, channel_cfg.rules, event_type, data, config):
                continue

            # Enqueue for background delivery
            try:
                self._queue.put_nowait({
                    'channel': channel_name,
                    'event_type': event_type,
                    'data': data,
                })
            except queue.Full:
                logger.warning(f"[NOTIFY] Queue full — dropping {channel_name} notification for {data.get('alarm_id')}")

    def configure(self, payload: dict) -> bool:
        """Update notification configuration from MQTT command."""
        try:
            new_config = NotificationConfig.from_dict(payload)
            with self._lock:
                self._config = new_config
            self._save_config()
            logger.info("[NOTIFY] Configuration updated")
            if self._publish:
                self._publish('notification_config', new_config.to_dict())
            return True
        except Exception as e:
            logger.error(f"[NOTIFY] Config update failed: {e}")
            return False

    def get_config(self) -> dict:
        """Return current config as dict (for MQTT publishing)."""
        with self._lock:
            return self._config.to_dict()

    def send_test_notification(self, channel: str, config_override: Optional[dict] = None) -> dict:
        """
        Send a test notification synchronously (bypasses cooldown/limits).

        Args:
            channel: 'twilio' or 'email'
            config_override: Optional config to use instead of saved config

        Returns:
            {'success': bool, 'message': str}
        """
        with self._lock:
            config = self._config

        if config_override:
            config = NotificationConfig.from_dict(config_override)

        test_data = {
            'alarm_id': 'test-notification',
            'channel': 'TEST',
            'name': 'Test Notification',
            'severity': 'HIGH',
            'threshold_type': 'high',
            'threshold_value': 100.0,
            'triggered_value': 105.0,
            'current_value': 105.0,
            'message': 'This is a test notification from the DAQ system.',
            'triggered_at': datetime.now(timezone.utc).isoformat(),
            'group': 'Test',
        }

        try:
            if channel == 'twilio':
                self._send_twilio(config.twilio, 'triggered', test_data)
                return {'success': True, 'message': 'Test SMS sent successfully'}
            elif channel == 'email':
                self._send_email(config.email, 'triggered', test_data)
                return {'success': True, 'message': 'Test email sent successfully'}
            else:
                return {'success': False, 'message': f'Unknown channel: {channel}'}
        except Exception as e:
            logger.error(f"[NOTIFY] Test {channel} failed: {e}")
            return {'success': False, 'message': str(e)}

    def shutdown(self):
        """Stop the background worker."""
        self._running = False
        if self._worker and self._worker.is_alive():
            # Push sentinel to unblock worker
            try:
                self._queue.put_nowait(None)
            except queue.Full:
                pass
            self._worker.join(timeout=5.0)
        logger.info("[NOTIFY] Notification manager shut down")

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------

    def _passes_filters(
        self,
        channel_name: str,
        rules: TriggerRules,
        event_type: str,
        data: dict,
        config: NotificationConfig,
    ) -> bool:
        """Check all filter layers for a single channel. Returns True if notification should send."""

        alarm_id = data.get('alarm_id', '')
        severity = (data.get('severity') or '').lower()
        group = data.get('group', '')

        # 1. Event type
        if event_type not in rules.event_types:
            return False

        # 2. Severity (alarm_flood events don't have a single severity — always pass)
        if event_type != 'alarm_flood' and severity not in rules.severities:
            return False

        # 3. Group filter (empty list = all groups pass)
        if rules.groups and group not in rules.groups:
            return False

        # 4. Alarm selection
        if rules.alarm_select_mode == 'include_only':
            if alarm_id not in rules.alarm_ids:
                return False
        elif rules.alarm_select_mode == 'exclude':
            if alarm_id in rules.alarm_ids:
                return False
        # 'all' always passes

        # 5. Per-alarm cooldown
        now = time.monotonic()
        cooldowns = self._cooldowns.get(channel_name, {})
        last_sent = cooldowns.get(alarm_id, 0.0)
        if (now - last_sent) < config.cooldown_seconds:
            return False

        # 6. Daily limit (also prune stale cooldowns on day change)
        today = datetime.now().strftime('%Y-%m-%d')
        if self._daily_reset_date != today:
            self._daily_reset_date = today
            self._daily_count = 0
            self._prune_cooldowns(now)
        if self._daily_count >= config.daily_limit:
            logger.warning(f"[NOTIFY] Daily limit ({config.daily_limit}) reached — suppressing")
            return False

        # 7. Quiet hours (CRITICAL always passes)
        if config.quiet_hours_enabled and severity != 'critical':
            if self._is_quiet_hours(config.quiet_hours_start, config.quiet_hours_end):
                return False

        return True

    @staticmethod
    def _is_quiet_hours(start_str: str, end_str: str) -> bool:
        """Check if current local time is within quiet hours window."""
        try:
            now = datetime.now()
            current_minutes = now.hour * 60 + now.minute
            sh, sm = map(int, start_str.split(':'))
            eh, em = map(int, end_str.split(':'))
            start_minutes = sh * 60 + sm
            end_minutes = eh * 60 + em

            if start_minutes <= end_minutes:
                # Same-day window (e.g., 08:00–17:00)
                return start_minutes <= current_minutes < end_minutes
            else:
                # Overnight window (e.g., 22:00–06:00)
                return current_minutes >= start_minutes or current_minutes < end_minutes
        except (ValueError, AttributeError):
            return False

    def _prune_cooldowns(self, now: float):
        """Remove cooldown entries older than 24 hours to prevent unbounded growth."""
        cutoff = now - 86400  # 24 hours in seconds
        for channel_name in list(self._cooldowns.keys()):
            stale = [aid for aid, ts in self._cooldowns[channel_name].items() if ts < cutoff]
            for aid in stale:
                del self._cooldowns[channel_name][aid]
            if stale:
                logger.debug(f"[NOTIFY] Pruned {len(stale)} stale cooldown entries for {channel_name}")

    # ------------------------------------------------------------------
    # Background worker
    # ------------------------------------------------------------------

    def _start_worker(self):
        """Start the background notification delivery thread."""
        self._running = True
        self._worker = threading.Thread(
            target=self._worker_loop,
            name='NotificationWorker',
            daemon=True,
        )
        self._worker.start()

    def _worker_loop(self):
        """Process notification queue items."""
        while self._running:
            try:
                item = self._queue.get(timeout=1.0)
                if item is None:
                    break

                channel = item['channel']
                event_type = item['event_type']
                data = item['data']
                alarm_id = data.get('alarm_id', '')

                with self._lock:
                    config = self._config

                try:
                    if channel == 'twilio':
                        self._send_twilio(config.twilio, event_type, data)
                    elif channel == 'email':
                        self._send_email(config.email, event_type, data)

                    # Update cooldown and daily count on success
                    self._cooldowns.setdefault(channel, {})[alarm_id] = time.monotonic()
                    self._daily_count += 1

                    logger.info(f"[NOTIFY] {channel} notification sent for alarm {alarm_id} ({event_type})")

                    if self._publish:
                        self._publish('notification_sent', {
                            'channel': channel,
                            'alarm_id': alarm_id,
                            'event_type': event_type,
                            'timestamp': datetime.now(timezone.utc).isoformat(),
                        })

                except Exception as e:
                    logger.error(f"[NOTIFY] {channel} send failed for {alarm_id}: {e}")
                    if self._publish:
                        self._publish('notification_error', {
                            'channel': channel,
                            'alarm_id': alarm_id,
                            'error': str(e),
                            'timestamp': datetime.now(timezone.utc).isoformat(),
                        })

            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"[NOTIFY] Worker error: {e}")

    # ------------------------------------------------------------------
    # Twilio SMS
    # ------------------------------------------------------------------

    def _send_twilio(self, cfg: TwilioConfig, event_type: str, data: dict):
        """Send SMS via Twilio REST API."""
        if not cfg.account_sid or not cfg.auth_token or not cfg.from_number:
            raise ValueError("Twilio configuration incomplete (missing SID, token, or from number)")

        if not cfg.to_numbers:
            raise ValueError("No SMS recipients configured")

        body = self._format_sms_body(event_type, data)
        url = f"https://api.twilio.com/2010-04-01/Accounts/{cfg.account_sid}/Messages.json"

        for to_number in cfg.to_numbers:
            to_number = to_number.strip()
            if not to_number:
                continue
            resp = requests.post(
                url,
                data={
                    'From': cfg.from_number,
                    'To': to_number,
                    'Body': body,
                },
                auth=(cfg.account_sid, cfg.auth_token),
                timeout=10,
            )
            if resp.status_code not in (200, 201):
                error_msg = resp.json().get('message', resp.text) if resp.text else f"HTTP {resp.status_code}"
                raise RuntimeError(f"Twilio API error ({resp.status_code}): {error_msg}")

    @staticmethod
    def _format_sms_body(event_type: str, data: dict) -> str:
        """Format a concise SMS message body (160 char target)."""
        severity = (data.get('severity') or 'UNKNOWN').upper()
        name = data.get('name', data.get('alarm_id', 'Unknown'))
        channel = data.get('channel', '')

        if event_type == 'alarm_flood':
            count = data.get('alarm_count', '?')
            return f"ALARM FLOOD: {count} alarms triggered. Root cause: {data.get('root_cause', 'unknown')}"

        event_label = {
            'triggered': 'ALARM',
            'cleared': 'CLEARED',
            'acknowledged': 'ACK',
        }.get(event_type, event_type.upper())

        value = data.get('triggered_value') or data.get('current_value', '')
        threshold = data.get('threshold_value', '')

        msg = f"[{severity}] {event_label}: {name}"
        if channel:
            msg += f" ({channel})"
        if value != '' and event_type == 'triggered':
            msg += f" Value={value}"
            if threshold != '':
                msg += f" Limit={threshold}"

        return msg[:160]

    # ------------------------------------------------------------------
    # Email (SMTP)
    # ------------------------------------------------------------------

    def _send_email(self, cfg: EmailConfig, event_type: str, data: dict):
        """Send email via SMTP."""
        if not cfg.smtp_host or not cfg.from_address:
            raise ValueError("Email configuration incomplete (missing SMTP host or from address)")

        if not cfg.to_addresses:
            raise ValueError("No email recipients configured")

        subject, body_html = self._format_email(event_type, data)

        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = cfg.from_address
        msg['To'] = ', '.join(cfg.to_addresses)

        # Plain text fallback
        plain = self._format_email_plain(event_type, data)
        msg.attach(MIMEText(plain, 'plain'))
        msg.attach(MIMEText(body_html, 'html'))

        if cfg.use_tls:
            server = smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=10)
            server.starttls()
        else:
            server = smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=10)

        try:
            if cfg.username and cfg.password:
                server.login(cfg.username, cfg.password)
            server.sendmail(cfg.from_address, cfg.to_addresses, msg.as_string())
        finally:
            server.quit()

    @staticmethod
    def _format_email(event_type: str, data: dict) -> tuple:
        """Return (subject, html_body) for alarm email."""
        severity = (data.get('severity') or 'UNKNOWN').upper()
        name = data.get('name', data.get('alarm_id', 'Unknown'))
        channel = data.get('channel', '')

        if event_type == 'alarm_flood':
            subject = f"ALARM FLOOD — {data.get('alarm_count', '?')} alarms"
            html = f"""<h2 style="color:#d32f2f">Alarm Flood Detected</h2>
<p><strong>Alarm count:</strong> {data.get('alarm_count', '?')}</p>
<p><strong>Root cause:</strong> {data.get('root_cause', 'unknown')}</p>
<p><strong>Time:</strong> {data.get('timestamp', '')}</p>"""
            return subject, html

        event_label = {
            'triggered': 'ALARM TRIGGERED',
            'cleared': 'Alarm Cleared',
            'acknowledged': 'Alarm Acknowledged',
        }.get(event_type, event_type.upper())

        severity_colors = {
            'CRITICAL': '#d32f2f',
            'HIGH': '#f57c00',
            'MEDIUM': '#fbc02d',
            'LOW': '#388e3c',
        }
        color = severity_colors.get(severity, '#666')

        subject = f"[{severity}] {event_label}: {name}"

        html = f"""<h2 style="color:{color}">{event_label}</h2>
<table style="border-collapse:collapse; font-family:monospace;">
<tr><td style="padding:4px 12px 4px 0;font-weight:bold">Alarm</td><td>{name}</td></tr>
<tr><td style="padding:4px 12px 4px 0;font-weight:bold">Channel</td><td>{channel}</td></tr>
<tr><td style="padding:4px 12px 4px 0;font-weight:bold">Severity</td>
    <td><span style="color:{color};font-weight:bold">{severity}</span></td></tr>
<tr><td style="padding:4px 12px 4px 0;font-weight:bold">Threshold Type</td><td>{data.get('threshold_type', '')}</td></tr>
<tr><td style="padding:4px 12px 4px 0;font-weight:bold">Triggered Value</td><td>{data.get('triggered_value', '')}</td></tr>
<tr><td style="padding:4px 12px 4px 0;font-weight:bold">Threshold</td><td>{data.get('threshold_value', '')}</td></tr>
<tr><td style="padding:4px 12px 4px 0;font-weight:bold">Time</td><td>{data.get('triggered_at', '')}</td></tr>
<tr><td style="padding:4px 12px 4px 0;font-weight:bold">Message</td><td>{data.get('message', '')}</td></tr>
</table>
<hr style="margin-top:16px">
<p style="color:#999;font-size:12px">Sent by ICCSFlux DAQ Notification System</p>"""

        return subject, html

    @staticmethod
    def _format_email_plain(event_type: str, data: dict) -> str:
        """Plain-text fallback for email."""
        severity = (data.get('severity') or 'UNKNOWN').upper()
        name = data.get('name', data.get('alarm_id', 'Unknown'))
        channel = data.get('channel', '')

        if event_type == 'alarm_flood':
            return (
                f"ALARM FLOOD DETECTED\n"
                f"Alarm count: {data.get('alarm_count', '?')}\n"
                f"Root cause: {data.get('root_cause', 'unknown')}\n"
                f"Time: {data.get('timestamp', '')}"
            )

        event_label = {
            'triggered': 'ALARM TRIGGERED',
            'cleared': 'Alarm Cleared',
            'acknowledged': 'Alarm Acknowledged',
        }.get(event_type, event_type.upper())

        lines = [
            f"{event_label}",
            f"",
            f"Alarm:           {name}",
            f"Channel:         {channel}",
            f"Severity:        {severity}",
            f"Threshold Type:  {data.get('threshold_type', '')}",
            f"Triggered Value: {data.get('triggered_value', '')}",
            f"Threshold:       {data.get('threshold_value', '')}",
            f"Time:            {data.get('triggered_at', '')}",
            f"Message:         {data.get('message', '')}",
            f"",
            f"---",
            f"Sent by ICCSFlux DAQ Notification System",
        ]
        return '\n'.join(lines)

    # ------------------------------------------------------------------
    # Config persistence
    # ------------------------------------------------------------------

    def _load_config(self):
        """Load config from disk."""
        try:
            if self._config_path.exists():
                with open(self._config_path, 'r') as f:
                    data = json.load(f)
                self._config = NotificationConfig.from_dict(data)
                logger.info("[NOTIFY] Configuration loaded from disk")
        except Exception as e:
            logger.error(f"[NOTIFY] Failed to load config: {e}")
            self._config = NotificationConfig()

    def _save_config(self):
        """Persist config to disk with restricted permissions."""
        try:
            self._data_dir.mkdir(parents=True, exist_ok=True)
            config_dict = self._config.to_dict()
            tmp_path = self._config_path.with_suffix('.tmp')
            with open(tmp_path, 'w') as f:
                json.dump(config_dict, f, indent=2)
                f.flush()
                os.fsync(f.fileno())

            # Atomic rename
            if self._config_path.exists():
                self._config_path.unlink()
            tmp_path.rename(self._config_path)

            # Restrict permissions (owner-only) — best-effort on Windows
            try:
                os.chmod(self._config_path, stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                pass

            logger.info("[NOTIFY] Configuration saved to disk")
        except Exception as e:
            logger.error(f"[NOTIFY] Failed to save config: {e}")
