# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for ICCSFlux Fleet Monitor
Creates a standalone portable executable.
"""

from pathlib import Path

PROJECT_ROOT = Path(SPECPATH).parent

a = Analysis(
    [str(PROJECT_ROOT / 'scripts' / 'monitor_exe.py')],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'os',
        'sys',
        'signal',
        'socket',
        'pathlib',
        'threading',
        'http.server',
        'webbrowser',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'numpy',
        'scipy',
        'pandas',
        'matplotlib',
        'cryptography',
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
    name='FleetMonitor',
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
)
