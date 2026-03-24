# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for DAQ Service
Compiles the DAQ service to a standalone executable.
"""

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, copy_metadata

# Project paths
PROJECT_ROOT = Path(SPECPATH).parent
DAQ_DIR = PROJECT_ROOT / 'services' / 'daq_service'
LAUNCHER_DIR = PROJECT_ROOT / 'launcher'

# Collect all nidaqmx + nitypes submodules automatically (nidaqmx is conditionally imported)
nidaqmx_imports = collect_submodules('nidaqmx')
nitypes_imports = collect_submodules('nitypes')
hightime_imports = collect_submodules('hightime')

# Collect package metadata (.dist-info) needed by importlib.metadata.version() calls
nidaqmx_meta = copy_metadata('nidaqmx')
nitypes_meta = copy_metadata('nitypes')
hightime_meta = copy_metadata('hightime')
deprecation_meta = copy_metadata('deprecation')

# Analysis
a = Analysis(
    [str(DAQ_DIR / 'daq_service.py')],
    pathex=[str(DAQ_DIR), str(PROJECT_ROOT / 'services'), str(LAUNCHER_DIR), str(PROJECT_ROOT / 'tools')],
    binaries=[],
    datas=nidaqmx_meta + nitypes_meta + hightime_meta + deprecation_meta,
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

        # Single instance guard (from launcher/)
        'single_instance',

        # nidaqmx dependencies (pip packages required by nidaqmx 1.x)
        'hightime',
        'nitypes',
        'nitypes.types',
        'click',
        'deprecation',
        'tzlocal',
        'decouple',

        # Process simulator (tools/)
        'process_simulator',

        # Industrial protocols
        'pymodbus',
        'pymodbus.client',
        'pymodbus.server',
        'serial',
        'pycomm3',

        # HTTP
        'requests',
        'httpx',
    ] + nidaqmx_imports + nitypes_imports + hightime_imports,
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
    icon=str(PROJECT_ROOT / 'assets' / 'icons' / 'daq_service.ico'),
)
