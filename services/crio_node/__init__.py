"""
cRIO Node Service for NISystem

Standalone service that runs on NI cRIO-9056 (or compatible cRIO with RT Linux).
Communicates with NISystem PC via MQTT for configuration and data streaming.

Features:
- NI-DAQmx hardware watchdog for automatic safe state on failure
- Local config persistence (survives PC disconnect)
- Python script execution pushed from NISystem
- Full channel support: TC, voltage, current, DI, DO
"""

from .crio_node import CRIONodeService, CRIOConfig, ChannelConfig

__all__ = ['CRIONodeService', 'CRIOConfig', 'ChannelConfig']
