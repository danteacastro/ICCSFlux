"""
CODESYS Integration Package for Opto22 Node

Provides:
- register_map: Modbus register address allocation for Python ↔ CODESYS bridge
- st_codegen: Structured Text code generator from project config
- templates/: Jinja2 templates for IEC 61131-3 Structured Text
"""

from .register_map import RegisterMap
from .st_codegen import STCodeGenerator
