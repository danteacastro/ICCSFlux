@echo off
setlocal enabledelayedexpansion
title NISystem
cd /d "%~dp0"

echo.
echo ========================================
echo   NISystem
echo ========================================
echo.

:: Check for venv Python
if not exist "venv\Scripts\python.exe" (
    echo ERROR: Python environment not set up.
    echo.
    echo For end users: Use the portable version in dist\ICCSFlux-Portable\
    echo For developers: Run scripts\setup.bat first
    echo.
    pause
    exit /b 1
)

set PYTHON=venv\Scripts\python.exe

:: Check/Start Mosquitto
echo [1/3] Checking MQTT broker...
set MOSQUITTO_CONF=%~dp0config\mosquitto.conf
sc query Mosquitto >nul 2>&1
if errorlevel 1 (
    echo      Mosquitto service not found.
    echo      Attempting to start mosquitto.exe directly...

    where mosquitto >nul 2>&1
    if errorlevel 1 (
        if exist "C:\Program Files\mosquitto\mosquitto.exe" (
            start "Mosquitto MQTT" "C:\Program Files\mosquitto\mosquitto.exe" -c "%MOSQUITTO_CONF%" -v
            timeout /t 2 >nul
        ) else (
            echo      WARNING: Mosquitto not found. Install from mosquitto.org
        )
    ) else (
        start "Mosquitto MQTT" mosquitto -c "%MOSQUITTO_CONF%" -v
        timeout /t 2 >nul
    )
) else (
    net start Mosquitto >nul 2>&1
    echo      Mosquitto service OK
)

:: Start DAQ Service
echo [2/3] Starting backend service...
start "NISystem Backend" /min "%PYTHON%" services\daq_service\daq_service.py -c config\system.ini

timeout /t 3 >nul

:: Start Dashboard
echo [3/3] Starting dashboard...

:: Check if built dashboard exists
if exist "dashboard\dist\index.html" (
    echo      Using built dashboard on http://localhost:8080
    start "NISystem Dashboard" /min "%PYTHON%" services\daq_service\dashboard_server.py --port 8080
    timeout /t 2 >nul
    start http://localhost:8080
) else (
    :: Check for Node.js (dev mode)
    where npm >nul 2>&1
    if errorlevel 1 (
        echo      ERROR: Dashboard not built and Node.js not installed.
        echo.
        echo      Options:
        echo        1. Build dashboard: cd dashboard ^&^& npm install ^&^& npm run build
        echo        2. Install Node.js for dev mode: https://nodejs.org
        echo        3. Use portable version: dist\ICCSFlux-Portable\ICCSFlux.bat
        echo.
    ) else (
        echo      Starting Vue dev server on http://localhost:5173
        cd dashboard
        start "NISystem Dashboard Dev" cmd /c "npm run dev"
        cd ..
        timeout /t 5 >nul
        start http://localhost:5173
    )
)

echo.
echo ========================================
echo   NISystem Running
echo ========================================
echo.
echo   Backend:   Running (check logs\ for output)
echo   Dashboard: http://localhost:8080 (prod) or :5173 (dev)
echo   MQTT:      localhost:1883
echo.
echo   Close this window to stop viewing status.
echo   Services continue running in background.
echo.
echo ========================================
echo.
pause
