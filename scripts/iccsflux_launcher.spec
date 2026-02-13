# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for ICCSFlux Launcher
Compiles the main launcher that starts all services.
"""

import sys
from pathlib import Path

# Project paths
PROJECT_ROOT = Path(SPECPATH).parent

# Analysis
a = Analysis(
    [str(PROJECT_ROOT / 'dist' / 'ICCSFlux-Portable' / 'ICCSFlux.py')],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        # Standard library
        'os',
        'sys',
        'subprocess',
        'time',
        'webbrowser',
        'signal',
        'socket',
        'pathlib',
        'threading',
        'http.server',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'PIL',
        'numpy',
        'scipy',
        'pandas',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

# Two versions: console and windowed (no console)
exe_console = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ICCSFlux',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # Shows console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(PROJECT_ROOT / 'assets' / 'icons' / 'iccsflux.ico'),
)

exe_windowed = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ICCSFlux-Service',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # No console (runs as service/background)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(PROJECT_ROOT / 'assets' / 'icons' / 'iccsflux.ico'),
)
