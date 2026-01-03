@echo off
REM ============================================================================
REM NISystem Complete Startup Script
REM Starts all necessary services for the NISystem
REM ============================================================================

echo.
echo ================================================================================
echo   NISystem - Complete Startup
echo ================================================================================
echo.

REM Change to NISystem directory (hardcoded for shortcuts to work)
cd /d "C:\Users\User\Documents\Projects\NISystem"

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
echo [0/4] Cleaning up orphaned processes...
venv\Scripts\python.exe -c "from launcher.service_manager import cleanup_orphaned_processes; cleanup_orphaned_processes()" 2>nul
echo.

REM ============================================================================
REM Step 1: Start MQTT Broker (Mosquitto)
REM ============================================================================
echo [1/4] Starting MQTT Broker (Mosquitto)...
echo.

tasklist /FI "IMAGENAME eq mosquitto.exe" 2>NUL | find /I /N "mosquitto.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo   - MQTT Broker already running
) else (
    echo   - Starting Mosquitto...
    start "NISystem MQTT Broker" "C:\Program Files\mosquitto\mosquitto.exe" -c mosquitto_ws.conf
    timeout /t 2 /nobreak >nul
    echo   - MQTT Broker started
)
echo.

REM ============================================================================
REM Step 2: Start DAQ Service (Backend)
REM ============================================================================
echo [2/4] Starting DAQ Service (Backend)...
echo.

REM Start DAQ service with --force to kill any existing instance and ensure clean start
echo   - Starting DAQ service with configuration: config\system.ini
start "NISystem DAQ Service" venv\Scripts\python.exe services\daq_service\daq_service.py --force -c config\system.ini
timeout /t 3 /nobreak >nul
echo   - DAQ Service started
echo   - Check logs\daq_service.log for status
echo.

REM ============================================================================
REM Step 3: Start Frontend Dashboard (Dev Server)
REM ============================================================================
echo [3/4] Starting Frontend Dashboard (Vite Dev Server)...
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
REM Step 4: Wait for Services to Initialize
REM ============================================================================
echo [4/4] Waiting for services to initialize...
echo.

echo   - Waiting 8 seconds for all services to start...
timeout /t 8 /nobreak >nul

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

REM Check Frontend
netstat -ano | findstr ":5173" >nul 2>&1
if "%ERRORLEVEL%"=="0" (
    echo   [OK] Frontend: Running on http://localhost:5173
) else (
    echo   [ERROR] Frontend: NOT RUNNING
)

echo.
echo ================================================================================
echo   NISystem Started Successfully!
echo ================================================================================
echo.
echo   Dashboard:     http://localhost:5173
echo   MQTT Broker:   localhost:1884 (TCP), localhost:9002 (WebSocket)
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
echo   [5] Stop All Services
echo   [6] Open Dashboard
echo   [0] Exit Menu (keep services running)
echo.
set /p choice="Select option: "

if "%choice%"=="1" goto VIEWLOGS
if "%choice%"=="2" goto VIEWSTATUS
if "%choice%"=="3" goto RESTARTDAQ
if "%choice%"=="4" goto RESTARTFRONTEND
if "%choice%"=="5" goto STOPALL
if "%choice%"=="6" goto OPENDASH
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
"C:\Program Files\mosquitto\mosquitto_pub.exe" -h localhost -p 1884 -t "nisystem/system/status/request" -m ""
timeout /t 1 /nobreak >nul
"C:\Program Files\mosquitto\mosquitto_sub.exe" -h localhost -p 1884 -t "nisystem/status/system" -C 1
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

:OPENDASH
start http://localhost:5173
goto MENU

:STOPALL
echo.
echo Stopping all services...
echo.
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

:END
echo.
echo Exiting menu. Services remain running.
echo.
exit /b 0
