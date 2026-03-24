"""
cRIO Service
============

A service for NI cRIO-905x Linux RT systems providing:
- Digital I/O handling
- Safety logic and interlocks
- MQTT communication with NISystem

Usage:
    from services.crio_service import CRIOService

    service = CRIOService('config/crio_service.ini')
    service.run()
"""

from .crio_service import (
    CRIOService,
    CRIOConfig,
    DigitalIOHandler,
    SafetyLogic,
    SafetyAction,
    SafetyState,
    AlarmSeverity,
    parse_config,
)

__all__ = [
    'CRIOService',
    'CRIOConfig',
    'DigitalIOHandler',
    'SafetyLogic',
    'SafetyAction',
    'SafetyState',
    'AlarmSeverity',
    'parse_config',
]

__version__ = '1.0.0'
