@echo off
REM ============================================================
REM GC Node Installer — Run inside the Hyper-V VM
REM
REM Usage: install.bat [broker_ip] [node_id]
REM   broker_ip  : MQTT broker IP on the host PC (default: 10.10.10.1)
REM   node_id    : Unique node identifier (default: gc-001)
REM
REM Prerequisites:
REM   - Python 3.4+ installed (3.8 recommended for Win7)
REM   - Network connectivity to the host PC on the internal switch
REM ============================================================

setlocal enabledelayedexpansion

set BROKER_IP=%~1
if "%BROKER_IP%"=="" set BROKER_IP=10.10.10.1

set NODE_ID=%~2
if "%NODE_ID%"=="" set NODE_ID=gc-001

set INSTALL_DIR=%~dp0
set CONFIG_FILE=%INSTALL_DIR%config.json

echo.
echo ============================================================
echo   GC Node Installer
echo   Broker: %BROKER_IP%:1883
echo   Node ID: %NODE_ID%
echo   Install Dir: %INSTALL_DIR%
echo ============================================================
echo.

REM --- Find Python ---
set PYTHON=
where python >nul 2>&1 && set PYTHON=python
if "%PYTHON%"=="" where python3 >nul 2>&1 && set PYTHON=python3
if "%PYTHON%"=="" where py >nul 2>&1 && set PYTHON=py

if "%PYTHON%"=="" (
    echo [ERROR] Python not found. Please install Python 3.4+ first.
    echo   Win7: https://www.python.org/downloads/release/python-3810/
    echo   XP:   https://www.python.org/downloads/release/python-348/
    pause
    exit /b 1
)

echo [OK] Found Python: %PYTHON%
%PYTHON% --version

REM --- Check pip ---
%PYTHON% -m pip --version >nul 2>&1
if errorlevel 1 (
    echo [INFO] Installing pip...
    %PYTHON% -m ensurepip --default-pip 2>nul
    if errorlevel 1 (
        echo [WARN] ensurepip failed, trying get-pip.py...
        echo Please download get-pip.py and run: %PYTHON% get-pip.py
    )
)

REM --- Install dependencies ---
echo.
echo [INFO] Installing dependencies...
%PYTHON% -m pip install -r "%INSTALL_DIR%requirements.txt" --quiet
if errorlevel 1 (
    echo [WARN] Some dependencies failed to install.
    echo   If on Windows XP, use: pip install paho-mqtt"<"2.0 pymodbus"<"3.0 pyserial
)

REM --- Create config.json ---
echo.
echo [INFO] Creating config.json...

(
echo {
echo   "system": {
echo     "node_id": "%NODE_ID%",
echo     "node_name": "GC Analyzer %NODE_ID%",
echo     "gc_type": "",
echo     "mqtt_broker": "%BROKER_IP%",
echo     "mqtt_port": 1883,
echo     "mqtt_base_topic": "nisystem",
echo     "heartbeat_interval_s": 5.0,
echo     "publish_rate_hz": 0.2
echo   },
echo   "file_watcher": {
echo     "enabled": true,
echo     "watch_directory": "C:\\GCResults",
echo     "file_pattern": "*.csv",
echo     "poll_interval_s": 5.0,
echo     "parse_template": "generic_csv",
echo     "delimiter": ",",
echo     "header_rows": 1,
echo     "encoding": "utf-8",
echo     "column_mapping": {},
echo     "archive_processed": false
echo   },
echo   "modbus_source": {
echo     "enabled": false
echo   },
echo   "serial_source": {
echo     "enabled": false
echo   },
echo   "channels": {}
echo }
) > "%CONFIG_FILE%"

echo [OK] Config written to %CONFIG_FILE%

REM --- Create GCResults directory ---
if not exist "C:\GCResults" (
    mkdir "C:\GCResults"
    echo [OK] Created C:\GCResults watch directory
)

REM --- Create startup scheduled task ---
echo.
echo [INFO] Creating startup scheduled task...

schtasks /create /tn "GCNode_%NODE_ID%" /tr "\"%PYTHON%\" -m gc_node --config \"%CONFIG_FILE%\"" /sc onlogon /rl highest /f >nul 2>&1
if errorlevel 1 (
    echo [WARN] Could not create scheduled task. Manual startup required.
    echo   Run: %PYTHON% -m gc_node --config "%CONFIG_FILE%"
) else (
    echo [OK] Scheduled task "GCNode_%NODE_ID%" created (starts on logon)
)

REM --- Test MQTT connectivity ---
echo.
echo [INFO] Testing MQTT connectivity to %BROKER_IP%:1883...

%PYTHON% -c "import socket; s=socket.socket(); s.settimeout(5); s.connect(('%BROKER_IP%', 1883)); s.close(); print('[OK] MQTT broker reachable')" 2>nul
if errorlevel 1 (
    echo [WARN] Cannot reach MQTT broker at %BROKER_IP%:1883
    echo   Check:
    echo     1. Host PC firewall allows inbound TCP 1883
    echo     2. Mosquitto is running on host
    echo     3. VM has correct IP on internal switch
    echo     4. ping %BROKER_IP% works from this VM
)

REM --- Summary ---
echo.
echo ============================================================
echo   Installation Complete
echo ============================================================
echo.
echo   Node ID:     %NODE_ID%
echo   Broker:      %BROKER_IP%:1883
echo   Config:      %CONFIG_FILE%
echo   Watch Dir:   C:\GCResults
echo.
echo   To start manually:
echo     cd %INSTALL_DIR%
echo     %PYTHON% -m gc_node
echo.
echo   To test:
echo     %PYTHON% -m gc_node --log-level DEBUG
echo.
echo   The node will auto-start on next login.
echo ============================================================
echo.

pause
endlocal
