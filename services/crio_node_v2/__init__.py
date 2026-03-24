"""
cRIO Node V2 - Simplified State Machine Architecture

This is a complete rewrite of the cRIO node service with:
- Single state machine for acquisition/session
- Command queue (MQTT callbacks never block)
- Hardware abstraction for testability
- Deterministic single main loop

Architecture:
    ┌─────────────────────────────────────────────┐
    │              CRIONodeV2                     │
    │  ┌─────────────┐  ┌──────────────────────┐  │
    │  │ StateTransition │  │   CommandQueue    │  │
    │  │  IDLE→ACQ→SESS  │  │  (never blocks)   │  │
    │  └─────────────┘  └──────────────────────┘  │
    │                                             │
    │  ┌─────────────┐  ┌──────────────────────┐  │
    │  │  Hardware   │  │   MQTTInterface      │  │
    │  │ (NI-DAQmx)  │  │   (paho wrapper)     │  │
    │  └─────────────┘  └──────────────────────┘  │
    │                                             │
    │  ┌─────────────┐  ┌──────────────────────┐  │
    │  │   Safety    │  │      Config          │  │
    │  │ (alarms)    │  │   (JSON parsing)     │  │
    │  └─────────────┘  └──────────────────────┘  │
    └─────────────────────────────────────────────┘

Main loop pattern:
    1. Process pending commands (from queue)
    2. Read channels (if acquiring)
    3. Check safety (single pass)
    4. Publish values (rate-limited)
"""

from .state_machine import State, StateTransition
from .crio_node import CRIONodeV2, NodeConfig
from .hardware import HardwareInterface, HardwareConfig, ChannelConfig, create_hardware
from .mqtt_interface import MQTTInterface, MQTTConfig
from .safety import SafetyManager, AlarmConfig, AlarmEvent, AlarmSeverity, AlarmState
from .config import load_config, find_config_file
from .channel_types import ChannelType, MODULE_TYPE_MAP, get_module_channel_type

__all__ = [
    # Main class
    'CRIONodeV2',

    # State machine
    'State',
    'StateTransition',

    # Hardware
    'HardwareInterface',
    'HardwareConfig',
    'ChannelConfig',
    'create_hardware',

    # MQTT
    'MQTTInterface',
    'MQTTConfig',

    # Safety
    'SafetyManager',
    'AlarmConfig',
    'AlarmEvent',
    'AlarmSeverity',
    'AlarmState',

    # Config
    'NodeConfig',
    'load_config',
    'find_config_file',

    # Channel Types
    'ChannelType',
    'MODULE_TYPE_MAP',
    'get_module_channel_type',
]

__version__ = '2.0.0'
