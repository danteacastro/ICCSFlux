# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for Modbus Poll Tool standalone exe."""

from pathlib import Path

PROJECT_ROOT = Path(SPECPATH).parent
TOOL_DIR = PROJECT_ROOT / 'tools' / 'modbus_tool'

a = Analysis(
    [str(TOOL_DIR / 'modbus_tool.py')],
    pathex=[str(TOOL_DIR)],
    binaries=[],
    datas=[
        (str(TOOL_DIR / 'index.html'), '.'),
    ],
    hiddenimports=[
        # FastAPI + Uvicorn
        'fastapi',
        'fastapi.responses',
        'fastapi.routing',
        'uvicorn',
        'uvicorn.config',
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.http.h11_impl',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.protocols.websockets.websockets_impl',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'starlette',
        'starlette.routing',
        'starlette.responses',
        'starlette.websockets',
        'starlette.middleware',
        'anyio',
        'anyio._backends',
        'anyio._backends._asyncio',
        'h11',
        'websockets',
        'websockets.asyncio',
        'websockets.asyncio.server',
        'websockets.http11',
        'websockets.frames',
        'websockets.protocol',
        'websockets.extensions',
        'websockets.extensions.permessage_deflate',
        # Modbus
        'pymodbus',
        'pymodbus.client',
        'pymodbus.client.tcp',
        'pymodbus.client.serial',
        'pymodbus.exceptions',
        'pymodbus.pdu',
        # Serial
        'serial',
        'serial.tools',
        'serial.tools.list_ports',
        'serial.tools.list_ports_windows',
        # Adapter module
        'modbus_adapter',
    ],
    hookspath=[],
    excludes=[
        'tkinter', 'numpy', 'scipy', 'pandas', 'matplotlib',
        'PIL', 'PyQt5', 'PyQt6', 'pytest', 'IPython', 'jupyter',
        'paho', 'nidaqmx',
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
    name='ModbusTool',
    debug=False,
    strip=False,
    upx=True,
    runtime_tmpdir=None,
    console=True,
    icon=str(PROJECT_ROOT / 'assets' / 'icons' / 'modbus_tool.ico'),
)
