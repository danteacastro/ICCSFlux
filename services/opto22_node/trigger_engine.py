"""
Trigger Engine for Opto22 Node

Automation triggers that fire actions on value threshold crossings:
- Condition types: >, <, >=, <=, ==
- Actions: set output, run sequence, send notification
- Rising-edge detection (fires only on transition from false to true)

Extracted from the Opto22 monolithic node.
"""

import logging
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger('Opto22Node.Triggers')

class TriggerEngine:
    def __init__(self):
        self.triggers: Dict[str, Dict[str, Any]] = {}
        self.set_output: Optional[Callable[[str, Any], None]] = None
        self.run_sequence: Optional[Callable[[str], None]] = None
        self.publish_notification: Optional[Callable[[str, str, str], None]] = None
        self._is_acquiring = False
        self._last_values: Dict[str, bool] = {}

    def on_acquisition_start(self):
        self._is_acquiring = True

    def on_acquisition_stop(self):
        self._is_acquiring = False

    def process_scan(self, channel_values: Dict[str, float]):
        if not self._is_acquiring: return
        for tid, trigger in self.triggers.items():
            if not trigger.get('enabled', True): continue
            cond = trigger.get('condition', {})
            channel = cond.get('channel')
            if not channel or channel not in channel_values: continue
            val = channel_values[channel]
            threshold = cond.get('threshold', 0)
            op = cond.get('operator', '>')
            met = False
            if op == '>': met = val > threshold
            elif op == '<': met = val < threshold
            elif op == '>=': met = val >= threshold
            elif op == '<=': met = val <= threshold
            elif op == '==': met = abs(val - threshold) < 0.001
            was = self._last_values.get(tid, False)
            self._last_values[tid] = met
            if met and not was:
                for action in trigger.get('actions', []):
                    self._execute_action(action, trigger)

    def _execute_action(self, action: Dict, trigger: Dict):
        atype = action.get('type', '')
        if atype == 'setOutput' and self.set_output:
            self.set_output(action.get('channel'), action.get('value'))
        elif atype == 'runSequence' and self.run_sequence:
            self.run_sequence(action.get('sequenceId'))
        elif atype == 'notification' and self.publish_notification:
            self.publish_notification('trigger', trigger.get('name', ''), action.get('message', ''))

    def load_config(self, config: Dict[str, Any]):
        self.triggers = {t['id']: t for t in config.get('triggers', [])}
