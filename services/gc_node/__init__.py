"""
GC Node - Gas Chromatograph Bridge Service

Bridges GC (Gas Chromatograph) data to NISystem MQTT broker via:
- File watching (CSV/TXT results from vendor software)
- Modbus TCP/RTU registers
- Serial COM port data
- Built-in chromatogram analysis (peak detection, integration, area normalization)

Can run directly on the host PC (serial/Modbus to old GCs) or inside
a Hyper-V VM alongside legacy vendor software.
"""

__version__ = '1.0.0'
