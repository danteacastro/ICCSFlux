# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for DAQ Service
Compiles the DAQ service to a standalone executable.
"""

import sys
from pathlib import Path

# Project paths
PROJECT_ROOT = Path(SPECPATH).parent
DAQ_DIR = PROJECT_ROOT / 'services' / 'daq_service'

# Analysis
a = Analysis(
    [str(DAQ_DIR / 'daq_service.py')],
    pathex=[str(DAQ_DIR), str(PROJECT_ROOT / 'services')],
    binaries=[],
    datas=[],
    hiddenimports=[
        # Standard library
        'json',
        'logging',
        'threading',
        'queue',
        'time',
        'datetime',
        'pathlib',
        'argparse',
        'signal',
        'configparser',
        'collections',
        'os',
        'sys',
        'subprocess',
        'socket',
        'struct',
        'enum',
        'traceback',
        'warnings',

        # MQTT (2.x)
        'paho',
        'paho.mqtt',
        'paho.mqtt.client',

        # Scientific computing
        'numpy',
        'scipy',
        'scipy.signal',
        'scipy.interpolate',
        'scipy.stats',

        # Data handling
        'dateutil',
        'dateutil.parser',

        # Security
        'bcrypt',

        # Utilities
        'psutil',

        # Industrial protocols
        'pymodbus',
        'pymodbus.client',
        'pymodbus.server',
        'serial',
        'pycomm3',

        # HTTP
        'requests',
        'httpx',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'PIL',
        'PyQt5',
        'PyQt6',
        'pytest',
        'IPython',
        'jupyter',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='DAQService',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
