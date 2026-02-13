# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Azure IoT Hub Uploader Service
Compiles the Azure uploader to a standalone executable.
Note: This uses paho-mqtt 1.x for Azure SDK compatibility.
"""

import sys
from pathlib import Path

# Project paths
PROJECT_ROOT = Path(SPECPATH).parent
AZURE_DIR = PROJECT_ROOT / 'services' / 'azure_uploader'

# Analysis
a = Analysis(
    [str(AZURE_DIR / 'azure_uploader_service.py')],
    pathex=[str(AZURE_DIR)],
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

        # MQTT (1.x for Azure compatibility)
        'paho',
        'paho.mqtt',
        'paho.mqtt.client',

        # Azure IoT SDK
        'azure',
        'azure.iot',
        'azure.iot.device',
        'azure.iot.device.iothub',
        'azure.iot.device.exceptions',
        'azure.iot.device.aio',

        # Azure SDK dependencies
        'urllib3',
        'certifi',
        'requests',
        'requests.adapters',
        'requests.auth',
        'requests_unixsocket2',
        'janus',
        'typing_extensions',
        'deprecation',
        'packaging',
        'packaging.version',
        'socks',
        'charset_normalizer',
        'idna',
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
    name='AzureUploader',
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
    icon=str(PROJECT_ROOT / 'assets' / 'icons' / 'azure_uploader.ico'),
)
