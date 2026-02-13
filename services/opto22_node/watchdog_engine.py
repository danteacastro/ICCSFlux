"""
Watchdog Engine for Opto22 Node

Multi-channel watchdog monitoring:
- Stale data detection (no update within timeout)
- Out-of-range detection (value outside min/max bounds)
- Actions on trigger: set output, send notification, raise alarm
- Recovery actions when condition clears

Extracted from the Opto22 monolithic node.
"""

import logging
import time
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger('Opto22Node.Watchdog')


class WatchdogEngine:
    def __init__(self):
        self.watchdogs: Dict[str, Dict[str, Any]] = {}
        self.set_output: Optional[Callable[[str, Any], None]] = None
        self.run_sequence: Optional[Callable[[str], None]] = None
        self.stop_sequence: Optional[Callable[[str], None]] = None
        self.publish_notification: Optional[Callable[[str, str, str], None]] = None
        self.raise_alarm: Optional[Callable[[str, str, str], None]] = None
        self._is_acquiring = False
        self._triggered: Dict[str, bool] = {}
        self._last_values: Dict[str, tuple] = {}

    def on_acquisition_start(self):
        self._is_acquiring = True

    def on_acquisition_stop(self):
        self._is_acquiring = False

    def process_scan(self, channel_values: Dict[str, float], timestamps: Dict[str, float] = None):
        if not self._is_acquiring: return
        now = time.time()
        for wid, wd in self.watchdogs.items():
            if not wd.get('enabled', True): continue
            channels = wd.get('channels', [])
            cond = wd.get('condition', {})
            ctype = cond.get('type', 'stale_data')
            triggered_chs = []
            for ch in channels:
                if ch not in channel_values: continue
                val = channel_values[ch]
                ts = timestamps.get(ch, now) if timestamps else now
                if ctype == 'stale_data':
                    max_stale = cond.get('maxStaleMs', 5000) / 1000.0
                    if now - ts > max_stale: triggered_chs.append(ch)
                elif ctype == 'out_of_range':
                    min_v, max_v = cond.get('minValue'), cond.get('maxValue')
                    if (min_v is not None and val < min_v) or (max_v is not None and val > max_v):
                        triggered_chs.append(ch)
            if triggered_chs and not self._triggered.get(wid, False):
                self._triggered[wid] = True
                for action in wd.get('actions', []):
                    self._execute_action(action, wd)
                logger.warning(f"Watchdog triggered: {wd.get('name')} on {triggered_chs}")
            elif not triggered_chs and self._triggered.get(wid, False):
                self._triggered[wid] = False
                for action in wd.get('recoveryActions', []):
                    self._execute_action(action, wd)

    def _execute_action(self, action: Dict, wd: Dict):
        atype = action.get('type', '')
        if atype == 'setOutput' and self.set_output:
            self.set_output(action.get('channel'), action.get('value'))
        elif atype == 'notification' and self.publish_notification:
            self.publish_notification('watchdog', wd.get('name', ''), action.get('message', ''))
        elif atype == 'alarm' and self.raise_alarm:
            self.raise_alarm(wd.get('id', ''), action.get('severity', 'warning'), action.get('message', ''))

    def load_config(self, config: Dict[str, Any]):
        self.watchdogs = {w['id']: w for w in config.get('watchdogs', [])}
