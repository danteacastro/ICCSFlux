"""Acquisition Event Pipeline - structured lifecycle event tracking.

Emits structured events at each step of the acquisition lifecycle
(start, stop, hardware init, cRIO forwarding, scan loop, safety eval)
so the dashboard can show exactly where things break.

Events are published to MQTT on {base}/acquisition/events (QoS 0)
and kept in a ring buffer for query.
"""
import json
import time
import logging
from enum import Enum
from typing import Optional, Dict, Any
from datetime import datetime
from collections import deque

logger = logging.getLogger('DAQService')

class AcquisitionEvent(str, Enum):
    """Acquisition lifecycle events."""
    # Start flow
    START_REQUESTED = 'start_requested'
    START_PERMISSION_CHECK = 'start_permission_check'
    START_STATE_TRANSITION = 'start_state_transition'
    CONFIG_LOADED = 'config_loaded'
    HARDWARE_INIT_STARTED = 'hardware_init_started'
    HARDWARE_INIT_COMPLETE = 'hardware_init_complete'
    HARDWARE_INIT_FAILED = 'hardware_init_failed'
    CRIO_CONFIG_PUSH_SENT = 'crio_config_push_sent'
    CRIO_CONFIG_ACK_RECEIVED = 'crio_config_ack_received'
    CRIO_CONFIG_ACK_TIMEOUT = 'crio_config_ack_timeout'
    CRIO_START_FORWARDED = 'crio_start_forwarded'
    CRIO_START_ACK_RECEIVED = 'crio_start_ack_received'
    CRIO_START_ACK_TIMEOUT = 'crio_start_ack_timeout'
    ENGINES_NOTIFIED = 'engines_notified'
    ACQUIRE_RUNNING = 'acquire_running'
    START_FAILED = 'start_failed'
    START_REJECTED = 'start_rejected'

    # Runtime
    SCAN_LOOP_STARTED = 'scan_loop_started'
    SCAN_LOOP_ERROR = 'scan_loop_error'
    SCAN_LOOP_RECOVERED = 'scan_loop_recovered'
    SCAN_LOOP_FATAL = 'scan_loop_fatal'
    HARDWARE_DEGRADED = 'hardware_degraded'
    HARDWARE_RECOVERED = 'hardware_recovered'
    SAFETY_EVAL_FAILED = 'safety_eval_failed'
    SAFETY_EVAL_RECOVERED = 'safety_eval_recovered'
    SAFETY_SAFE_STATE_APPLIED = 'safety_safe_state_applied'
    HISTORIAN_ERROR = 'historian_error'

    # Stop flow
    STOP_REQUESTED = 'stop_requested'
    STOP_CASCADE_RECORDING = 'stop_cascade_recording'
    CRIO_STOP_FORWARDED = 'crio_stop_forwarded'
    ACQUIRE_STOPPED = 'acquire_stopped'
    STOP_FAILED = 'stop_failed'

    # Health
    HEALTH_PUBLISHED = 'health_published'

class AcquisitionEventPipeline:
    """Tracks and publishes acquisition lifecycle events."""

    def __init__(self, mqtt_client, topic_base: str, max_history: int = 200):
        self._mqtt = mqtt_client
        self._topic_base = topic_base
        self._history: deque = deque(maxlen=max_history)
        self._current_flow_id: Optional[str] = None

    def emit(self, event: AcquisitionEvent, details: Optional[Dict[str, Any]] = None,
             severity: str = 'info', flow_id: Optional[str] = None):
        """Emit an acquisition event to MQTT and history buffer."""
        entry = {
            'event': event.value,
            'timestamp': datetime.now().isoformat(),
            'epoch_ms': int(time.time() * 1000),
            'severity': severity,
            'flow_id': flow_id or self._current_flow_id,
            'details': details or {}
        }
        self._history.append(entry)

        # Log based on severity
        msg = f"[ACQ_EVENT] {event.value}"
        if details:
            msg += f" | {details}"
        if severity == 'error':
            logger.error(msg)
        elif severity == 'warning':
            logger.warning(msg)
        else:
            logger.info(msg)

        # Publish to MQTT (fire-and-forget, QoS 0 — events must not slow down scan loop)
        if self._mqtt:
            try:
                self._mqtt.publish(
                    f"{self._topic_base}/acquisition/events",
                    json.dumps(entry),
                    qos=0
                )
            except Exception:
                pass  # Event publishing must never disrupt acquisition

    def start_flow(self, flow_id: str):
        """Begin tracking a new start/stop flow."""
        self._current_flow_id = flow_id

    def end_flow(self):
        """End the current flow."""
        self._current_flow_id = None

    def get_history(self) -> list:
        """Get recent event history."""
        return list(self._history)

    def update_topic_base(self, topic_base: str):
        """Update the MQTT topic base (e.g., after config reload)."""
        self._topic_base = topic_base
