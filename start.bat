@echo off
setlocal enabledelayedexpansion
REM ============================================================================
REM NISystem Complete Startup Script
REM Starts all necessary services for the NISystem
REM ============================================================================

echo.
echo ================================================================================
echo   NISystem - Complete Startup
echo ================================================================================
echo.

REM Change to NISystem directory (uses script location for portability)
cd /d "%~dp0"

REM Check if Python virtual environment exists
if not exist "venv\Scripts\python.exe" (
    echo ERROR: Python virtual environment not found!
    echo Please run setup or create venv first.
    pause
    exit /b 1
)

REM Check if Node.js is available
where node >nul 2>&1
if errorlevel 1 (
    echo ERROR: Node.js not found! Please install Node.js.
    pause
    exit /b 1
)

REM ============================================================================
REM Step 0: Clean up orphaned processes from previous runs
REM ============================================================================
echo [0/5] Cleaning up orphaned processes...
venv\Scripts\python.exe -c "from launcher.service_manager import cleanup_orphaned_processes; cleanup_orphaned_processes()" 2>nul

REM Truncate large log files (prevent disk bloat)
for %%F in (logs\*.log) do (
    for %%A in ("%%F") do (
        REM If file > 50MB (52428800 bytes), truncate it
        if %%~zA GTR 52428800 (
            echo   - Truncating large log file: %%F
            echo. > "%%F"
        )
    )
)
echo.

REM ============================================================================
REM Step 1: Start MQTT Broker (Mosquitto) - with security if configured
REM ============================================================================
echo [1/5] Starting MQTT Broker (Mosquitto)...
echo.

tasklist /FI "IMAGENAME eq mosquitto.exe" 2>NUL | find /I /N "mosquitto.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo   - MQTT Broker already running
) else (
    REM Check if security is configured (password file exists)
    if exist "config\mosquitto_passwd" (
        echo   - Starting Mosquitto with SECURITY ENABLED...
        start "NISystem MQTT Broker" "C:\Program Files\mosquitto\mosquitto.exe" -c config\mosquitto_secure.conf
        set MQTT_SECURE=1
        set MQTT_USERNAME=backend
        set MQTT_PASSWORD=nisystem_backend_2024
    ) else (
        echo   - WARNING: MQTT security not configured!
        echo   - Run setup_mqtt_security.bat to enable authentication
        echo   - Starting Mosquitto WITHOUT security...
        start "NISystem MQTT Broker" "C:\Program Files\mosquitto\mosquitto.exe" -c mosquitto_ws.conf
        set MQTT_SECURE=0
    )
    timeout /t 2 /nobreak >nul
    echo   - MQTT Broker started
)
echo.

REM ============================================================================
REM Step 2: Start DAQ Service (Backend)
REM ============================================================================
echo [2/5] Starting DAQ Service (Backend)...
echo.

REM Start DAQ service with --force to kill any existing instance and ensure clean start
echo   - Starting DAQ service with configuration: config\system.ini
start "NISystem DAQ Service" venv\Scripts\python.exe services\daq_service\daq_service.py --force -c config\system.ini
timeout /t 3 /nobreak >nul
echo   - DAQ Service started
echo   - Check logs\daq_service.log for status
echo.

REM ============================================================================
REM Step 3: Start Watchdog (Safety Monitor)
REM ============================================================================
echo [3/5] Starting Watchdog (Safety Monitor)...
echo.

REM Check if watchdog already running
venv\Scripts\python.exe -c "import psutil; exit(0 if any('watchdog.py' in ' '.join(p.cmdline()).lower() for p in psutil.process_iter(['cmdline']) if p.cmdline()) else 1)" 2>nul
if "%ERRORLEVEL%"=="0" (
    echo   - Watchdog already running
) else (
    echo   - Starting Watchdog (monitors DAQ health, triggers failsafe on hang)
    start "NISystem Watchdog" /MIN venv\Scripts\python.exe services\daq_service\watchdog.py -c config\system.ini
    timeout /t 1 /nobreak >nul
    echo   - Watchdog started
)
echo.

REM ============================================================================
REM Step 4: Start Frontend Dashboard (Dev Server)
REM ============================================================================
echo [4/5] Starting Frontend Dashboard (Vite Dev Server)...
echo.

REM Check if frontend dev server is already running
netstat -ano | findstr ":5173" >nul 2>&1
if "%ERRORLEVEL%"=="0" (
    echo   - Frontend dev server already running on port 5173
) else (
    echo   - Starting Vite dev server...
    cd dashboard
    start "NISystem Frontend Dashboard" cmd /c "npm run dev"
    cd ..
    echo   - Frontend starting... (will be ready in ~10 seconds)
)
echo.

REM ============================================================================
REM Step 5: Wait for Services to Initialize + Setup Scheduled Restart
REM ============================================================================
echo [5/5] Waiting for services to initialize...
echo.

echo   - Waiting 8 seconds for all services to start...
timeout /t 8 /nobreak >nul

REM Setup weekly restart scheduled task (if not exists)
schtasks /query /tn "NISystem Weekly Restart" >nul 2>&1
if "%ERRORLEVEL%"=="1" (
    echo   - Setting up weekly restart task (Sunday 3 AM)...
    schtasks /create /tn "NISystem Weekly Restart" /tr "powershell.exe -ExecutionPolicy Bypass -File \"%CD%\restart_daq.ps1\"" /sc weekly /d SUN /st 03:00 /ru "%USERNAME%" /f >nul 2>&1
    if "%ERRORLEVEL%"=="0" (
        echo   - Weekly restart scheduled
    ) else (
        echo   - Note: Could not create scheduled task (run as admin to enable)
    )
)

REM ============================================================================
REM Service Status Check
REM ============================================================================
echo.
echo ================================================================================
echo   Service Status
echo ================================================================================
echo.

REM Check Mosquitto
tasklist /FI "IMAGENAME eq mosquitto.exe" 2>NUL | find /I /N "mosquitto.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo   [OK] MQTT Broker: Running
) else (
    echo   [ERROR] MQTT Broker: NOT RUNNING
)

REM Check DAQ Service (use Python to check)
venv\Scripts\python.exe -c "import psutil; exit(0 if any('daq_service' in ' '.join(p.cmdline()).lower() for p in psutil.process_iter(['cmdline']) if p.cmdline()) else 1)" 2>nul
if "%ERRORLEVEL%"=="0" (
    echo   [OK] DAQ Service: Running
) else (
    echo   [ERROR] DAQ Service: NOT RUNNING
)

REM Check Watchdog
venv\Scripts\python.exe -c "import psutil; exit(0 if any('watchdog.py' in ' '.join(p.cmdline()).lower() for p in psutil.process_iter(['cmdline']) if p.cmdline()) else 1)" 2>nul
if "%ERRORLEVEL%"=="0" (
    echo   [OK] Watchdog: Running (monitoring DAQ health)
) else (
    echo   [WARN] Watchdog: NOT RUNNING (DAQ health not monitored)
)

REM Check Frontend
netstat -ano | findstr ":5173" >nul 2>&1
if "%ERRORLEVEL%"=="0" (
    echo   [OK] Frontend: Running on http://localhost:5173
) else (
    echo   [ERROR] Frontend: NOT RUNNING
)

REM Check MQTT Security
if exist "config\mosquitto_passwd" (
    echo   [OK] MQTT Security: ENABLED (authentication required)
) else (
    echo   [WARN] MQTT Security: DISABLED (run setup_mqtt_security.bat)
)

echo.
echo ================================================================================
echo   NISystem Started Successfully!
echo ================================================================================
echo.
echo   Dashboard:     http://localhost:5173
echo   MQTT Broker:   localhost:1883 (TCP), localhost:9002 (WebSocket)
echo   Logs:          logs\daq_service.log
echo.
echo   Press Ctrl+C to stop all services, or close this window.
echo.
echo   Opening dashboard in browser in 3 seconds...
timeout /t 3 /nobreak >nul
start http://localhost:5173
echo.

REM Keep window open
echo   Services are running. Close this window to keep services running,
echo   or press any key to view service management menu...
pause >nul

:MENU
cls
echo.
echo ================================================================================
echo   NISystem Service Management
echo ================================================================================
echo.
echo   [1] View DAQ Service Logs (last 50 lines)
echo   [2] View DAQ Service Status via MQTT
echo   [3] Restart DAQ Service
echo   [4] Restart Frontend
echo   [5] Restart Watchdog
echo   [6] Stop All Services
echo   [7] Open Dashboard
echo   [8] Enable MQTT Security (first-time setup)
echo   [0] Exit Menu (keep services running)
echo.
if exist "config\mosquitto_passwd" (
    echo   Security: ENABLED
) else (
    echo   Security: DISABLED - Select [8] to enable
)
echo.
set /p choice="Select option: "

if "%choice%"=="1" goto VIEWLOGS
if "%choice%"=="2" goto VIEWSTATUS
if "%choice%"=="3" goto RESTARTDAQ
if "%choice%"=="4" goto RESTARTFRONTEND
if "%choice%"=="5" goto RESTARTWATCHDOG
if "%choice%"=="6" goto STOPALL
if "%choice%"=="7" goto OPENDASH
if "%choice%"=="8" goto SETUPSECURITY
if "%choice%"=="0" goto END
goto MENU

:VIEWLOGS
echo.
echo Last 50 lines of DAQ service log:
echo ----------------------------------------
powershell -Command "Get-Content logs\daq_service.log -Tail 50"
echo.
pause
goto MENU

:VIEWSTATUS
echo.
echo Requesting status via MQTT...
echo (This requires mosquitto_pub and mosquitto_sub to be in PATH)
echo.
"C:\Program Files\mosquitto\mosquitto_pub.exe" -h localhost -p 1883 -t "nisystem/system/status/request" -m ""
timeout /t 1 /nobreak >nul
"C:\Program Files\mosquitto\mosquitto_sub.exe" -h localhost -p 1883 -t "nisystem/status/system" -C 1
echo.
pause
goto MENU

:RESTARTDAQ
echo.
echo Restarting DAQ Service...
REM Use --force flag which handles killing existing instance
start "NISystem DAQ Service" venv\Scripts\python.exe services\daq_service\daq_service.py --force -c config\system.ini
echo DAQ Service restarted.
timeout /t 3 /nobreak >nul
goto MENU

:RESTARTFRONTEND
echo.
echo Restarting Frontend...
REM Kill process on port 5173
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5173') do taskkill /F /PID %%a >nul 2>&1
timeout /t 2 /nobreak >nul
cd dashboard
start "NISystem Frontend Dashboard" cmd /c "npm run dev"
cd ..
echo Frontend restarted.
timeout /t 3 /nobreak >nul
goto MENU

:RESTARTWATCHDOG
echo.
echo Restarting Watchdog...
REM Kill existing watchdog
venv\Scripts\python.exe -c "import psutil; [p.kill() for p in psutil.process_iter(['cmdline']) if p.cmdline() and 'watchdog.py' in ' '.join(p.cmdline()).lower()]" 2>nul
timeout /t 2 /nobreak >nul
REM Start new watchdog
start "NISystem Watchdog" /MIN venv\Scripts\python.exe services\daq_service\watchdog.py -c config\system.ini
echo Watchdog restarted.
timeout /t 2 /nobreak >nul
goto MENU

:OPENDASH
start http://localhost:5173
goto MENU

:STOPALL
echo.
echo Stopping all services...
echo.
echo Stopping Watchdog...
venv\Scripts\python.exe -c "import psutil; [p.kill() for p in psutil.process_iter(['cmdline']) if p.cmdline() and 'watchdog.py' in ' '.join(p.cmdline()).lower()]" 2>nul
echo Stopping DAQ Service...
venv\Scripts\python.exe -c "import psutil; [p.kill() for p in psutil.process_iter(['cmdline']) if p.cmdline() and 'daq_service' in ' '.join(p.cmdline()).lower()]" 2>nul
echo Stopping Frontend...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5173') do taskkill /F /PID %%a >nul 2>&1
echo Stopping MQTT Broker...
taskkill /IM mosquitto.exe /F >nul 2>&1
echo.
echo All services stopped.
timeout /t 2 /nobreak >nul
exit /b 0

:SETUPSECURITY
echo.
echo ================================================================================
echo   MQTT Security Setup
echo ================================================================================
echo.
if exist "config\mosquitto_passwd" (
    echo Security is already enabled!
    echo.
    echo To reset security, delete config\mosquitto_passwd and run this again.
    pause
    goto MENU
)
echo This will enable MQTT authentication to protect against:
echo   - Unauthorized control of outputs
echo   - Code injection via scripts
echo   - Unauthorized user management
echo.
echo Default credentials will be created:
echo   Backend:   backend / nisystem_backend_2024
echo   Dashboard: dashboard / nisystem_dashboard_2024
echo.
echo IMPORTANT: Change these passwords in production!
echo.
set /p confirm="Enable security now? (Y/N): "
if /i "%confirm%"=="Y" (
    echo.
    echo Creating password file...
    "C:\Program Files\mosquitto\mosquitto_passwd.exe" -c -b "config\mosquitto_passwd" backend nisystem_backend_2024
    "C:\Program Files\mosquitto\mosquitto_passwd.exe" -b "config\mosquitto_passwd" dashboard nisystem_dashboard_2024
    echo.
    echo Security enabled! Restart all services to apply.
    echo.
    set /p restart="Restart all services now? (Y/N): "
    if /i "!restart!"=="Y" (
        goto STOPALL
    )
)
pause
goto MENU

:END
echo.
echo Exiting menu. Services remain running.
echo.
exit /b 0
