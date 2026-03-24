"""
NISystem CFP Node V2 — CompactFieldPoint Bridge Service

Bridges NI CompactFieldPoint (cFP-20xx) Modbus I/O to MQTT with:
- Authenticated + TLS MQTT connection
- ISA-18.2 alarms + IEC 61511 interlocks
- SHA-256 hash chain audit trail
- Formal state machine (IDLE → ACQUIRING → SESSION)
- pymodbus-based hardware communication
"""

__version__ = '2.0.0'

from .state_machine import State, StateTransition, SessionInfo
from .mqtt_interface import MQTTInterface, MQTTConfig
from .audit_trail import AuditTrail
from .config import (
    CFPNodeConfig,
    CFPChannelConfig,
    CFPModuleConfig,
    load_config,
    save_config,
    find_config_file,
)

# Safety imports (may fail if dependencies not available)
try:
    from .safety import (
        SafetyManager,
        AlarmConfig,
        AlarmEvent,
        AlarmSeverity,
        AlarmState,
    )
except ImportError:
    pass

# Main node class
from .cfp_node import CFPNodeV2

__all__ = [
    'CFPNodeV2',
    'State', 'StateTransition', 'SessionInfo',
    'MQTTInterface', 'MQTTConfig',
    'SafetyManager', 'AlarmConfig', 'AlarmEvent', 'AlarmSeverity', 'AlarmState',
    'AuditTrail',
    'CFPNodeConfig', 'CFPChannelConfig', 'CFPModuleConfig',
    'load_config', 'save_config', 'find_config_file',
]
