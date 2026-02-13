# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for ICCSFlux Launcher
Creates both console and windowed (service) versions.
"""

from pathlib import Path

PROJECT_ROOT = Path(SPECPATH).parent

a = Analysis(
    [str(PROJECT_ROOT / 'scripts' / 'ICCSFlux_exe.py')],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
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
        'numpy',
        'scipy',
        'pandas',
        'matplotlib',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

# Console version (for interactive use)
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
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(PROJECT_ROOT / 'assets' / 'icons' / 'iccsflux.ico'),
)
