@echo off
setlocal enabledelayedexpansion
REM ============================================================================
REM ICCSFlux H2-Ready Boiler Combustion Research Demo
REM Starts NISystem with the boiler demo configuration
REM ============================================================================

echo.
echo ================================================================================
echo   ICCSFlux - H2-Ready Boiler Combustion Research Platform
echo   Demo Mode - Simulated Data
echo ================================================================================
echo.

REM Change to NISystem directory
cd /d "%~dp0"

REM Check Python venv
if not exist "venv\Scripts\python.exe" (
    echo ERROR: Python virtual environment not found!
    echo Please run setup or create venv first.
    pause
    exit /b 1
)

REM ============================================================================
REM Update system.ini to use the boiler demo project
REM ============================================================================
echo [1/5] Configuring for Boiler Demo...
echo.

REM Backup original config
if not exist "config\system.ini.backup" (
    copy "config\system.ini" "config\system.ini.backup" >nul
)

REM Update project path in system.ini (using PowerShell for reliable find/replace)
powershell -Command "(Get-Content 'config\system.ini') -replace 'project_file\s*=\s*.*', 'project_file = config/projects/boiler_combustion_demo.json' | Set-Content 'config\system.ini'"
echo   - Project set to: boiler_combustion_demo.json
echo.

REM ============================================================================
REM Step 2: Start MQTT Broker
REM ============================================================================
echo [2/5] Starting MQTT Broker...
echo.

tasklist /FI "IMAGENAME eq mosquitto.exe" 2>NUL | find /I /N "mosquitto.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo   - MQTT Broker already running
) else (
    if exist "config\mosquitto_passwd" (
        start "MQTT Broker" "C:\Program Files\mosquitto\mosquitto.exe" -c config\mosquitto_secure.conf
    ) else (
        start "MQTT Broker" "C:\Program Files\mosquitto\mosquitto.exe" -c mosquitto_ws.conf
    )
    timeout /t 2 /nobreak >nul
    echo   - MQTT Broker started
)
echo.

REM ============================================================================
REM Step 3: Start DAQ Service
REM ============================================================================
echo [3/5] Starting DAQ Service with Boiler Demo...
echo.

start "DAQ Service - Boiler Demo" venv\Scripts\python.exe services\daq_service\daq_service.py --force -c config\system.ini
timeout /t 3 /nobreak >nul
echo   - DAQ Service started (simulation mode)
echo.

REM ============================================================================
REM Step 4: Start Frontend
REM ============================================================================
echo [4/5] Starting Dashboard...
echo.

netstat -ano | findstr ":5173" >nul 2>&1
if "%ERRORLEVEL%"=="0" (
    echo   - Frontend already running on port 5173
) else (
    cd dashboard
    start "Dashboard" cmd /c "npm run dev"
    cd ..
    echo   - Dashboard starting...
)
echo.

REM ============================================================================
REM Step 5: Wait and Open Browser
REM ============================================================================
echo [5/5] Waiting for services...
echo.
timeout /t 8 /nobreak >nul

echo.
echo ================================================================================
echo   Boiler Demo Started!
echo ================================================================================
echo.
echo   Dashboard:  http://localhost:5173
echo   Project:    H2-Ready Boiler Combustion Research
echo   Mode:       Simulation (no hardware required)
echo.
echo   Channels:   40+ (temps, pressures, flows, emissions)
echo   Safety:     9 safety actions, 5 interlocks configured
echo   Scripts:    Efficiency calc, Emissions logger
echo.
echo   Opening dashboard in 3 seconds...
timeout /t 3 /nobreak >nul
start http://localhost:5173

echo.
echo   Press any key to restore original config and exit...
pause >nul

REM Restore original config
if exist "config\system.ini.backup" (
    copy "config\system.ini.backup" "config\system.ini" >nul
    echo   - Original config restored
)

echo.
echo   Services still running. Close service windows to stop.
exit /b 0
