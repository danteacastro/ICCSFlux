# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for ICCSFlux Launcher
Creates a native windowed application (tkinter — Python stdlib).
"""

from pathlib import Path

PROJECT_ROOT = Path(SPECPATH).parent

a = Analysis(
    [str(PROJECT_ROOT / 'scripts' / 'ICCSFlux_exe.py')],
    pathex=[],
    binaries=[],
    datas=[
        (str(PROJECT_ROOT / 'scripts' / 'generate_tls_certs.py'), 'scripts'),
        (str(PROJECT_ROOT / 'scripts' / 'mqtt_credentials.py'), 'scripts'),
        (str(PROJECT_ROOT / 'assets' / 'icons' / 'iccsflux.ico'), '.'),
    ],
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
        # TLS certificate generation (first-run)
        'cryptography',
        'cryptography.x509',
        'cryptography.x509.oid',
        'cryptography.hazmat.primitives',
        'cryptography.hazmat.primitives.hashes',
        'cryptography.hazmat.primitives.serialization',
        'cryptography.hazmat.primitives.asymmetric',
        'cryptography.hazmat.primitives.asymmetric.rsa',
        'cryptography.hazmat.backends',
        'cffi',
        # Resource monitoring
        'psutil',
        'configparser',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'numpy',
        'scipy',
        'pandas',
        'matplotlib',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

# Windowed native app (tkinter — no console window)
exe_windowed = EXE(
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
    runtime_tmpdir='_runtime',
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(PROJECT_ROOT / 'assets' / 'icons' / 'iccsflux.ico'),
)
