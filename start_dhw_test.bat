@echo off
REM ============================================================================
REM NISystem - Start with DHW Test System Configuration
REM Loads the DHW (Domestic Hot Water) test configuration and project
REM ============================================================================

echo.
echo ================================================================================
echo   NISystem - DHW Test System Startup
echo ================================================================================
echo.

REM Change to NISystem directory
cd /d "%~dp0"

REM Check if Python virtual environment exists
if not exist "venv\Scripts\python.exe" (
    echo ERROR: Python virtual environment not found!
    pause
    exit /b 1
)

REM ============================================================================
REM Step 1: Start MQTT Broker
REM ============================================================================
echo [1/6] Starting MQTT Broker...
tasklist /FI "IMAGENAME eq mosquitto.exe" 2>NUL | find /I /N "mosquitto.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo   - MQTT Broker already running
) else (
    start "NISystem MQTT Broker" "C:\Program Files\mosquitto\mosquitto.exe" -c mosquitto_ws.conf
    timeout /t 2 /nobreak >nul
    echo   - MQTT Broker started
)
echo.

REM ============================================================================
REM Step 2: Start DAQ Service with DHW Configuration
REM ============================================================================
echo [2/6] Starting DAQ Service with DHW Test Configuration...
echo   - Config: config\dhw_test_system_nimax_sim.ini
echo   - Project: config\projects\dhw_test_system.json
echo.

REM Kill existing DAQ service
taskkill /FI "WINDOWTITLE eq NISystem DAQ Service*" /F >nul 2>&1
timeout /t 2 /nobreak >nul

REM Start with DHW config
start "NISystem DAQ Service" venv\Scripts\python.exe services\daq_service\daq_service.py --force -c config\dhw_test_system_nimax_sim.ini
timeout /t 5 /nobreak >nul
echo   - DAQ Service started with DHW configuration
echo.

REM ============================================================================
REM Step 3: Start Watchdog (Safety Monitor)
REM ============================================================================
echo [3/6] Starting Watchdog (Safety Monitor)...
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
REM Step 4: Load DHW Project via MQTT
REM ============================================================================
echo [4/6] Loading DHW Test Project...
echo.

REM Wait for DAQ service to fully start
echo   - Waiting for DAQ service to initialize...
timeout /t 3 /nobreak >nul

REM Send project load command via MQTT
echo   - Sending project load command via MQTT...
"C:\Program Files\mosquitto\mosquitto_pub.exe" -h localhost -p 1884 -t "nisystem/project/load" -m "{\"filename\": \"dhw_test_system.json\"}"
timeout /t 3 /nobreak >nul
echo   - DHW project load command sent
echo.

REM ============================================================================
REM Step 5: Start Frontend
REM ============================================================================
echo [5/6] Starting Frontend Dashboard...
netstat -ano | findstr ":5173" >nul 2>&1
if "%ERRORLEVEL%"=="0" (
    echo   - Frontend already running
) else (
    cd dashboard
    start "NISystem Frontend Dashboard" cmd /c "npm run dev"
    cd ..
    echo   - Frontend starting...
)
timeout /t 8 /nobreak >nul
echo.

REM ============================================================================
REM Step 6: Setup Scheduled Restart (if not exists)
REM ============================================================================
echo [6/6] Checking scheduled restart task...
schtasks /query /tn "NISystem Weekly Restart" >nul 2>&1
if "%ERRORLEVEL%"=="1" (
    echo   - Setting up weekly restart task (Sunday 3 AM)...
    schtasks /create /tn "NISystem Weekly Restart" /tr "powershell.exe -ExecutionPolicy Bypass -File \"C:\Users\User\Documents\Projects\NISystem\restart_daq.ps1\"" /sc weekly /d SUN /st 03:00 /ru "%USERNAME%" /f >nul 2>&1
    if "%ERRORLEVEL%"=="0" (
        echo   - Weekly restart scheduled
    ) else (
        echo   - Note: Could not create scheduled task (run as admin to enable)
    )
) else (
    echo   - Weekly restart task already configured
)
echo.

REM ============================================================================
REM Status Check
REM ============================================================================
echo ================================================================================
echo   DHW Test System Status
echo ================================================================================
echo.
echo   Configuration: config\dhw_test_system_nimax_sim.ini
echo   Project:       config\projects\dhw_test_system.json
echo   Dashboard:     http://localhost:5173
echo   MQTT:          localhost:1884 (Note: DHW uses port 1884!)
echo   Watchdog:      Active (monitors DAQ health)
echo   Weekly Restart: Sunday 3 AM
echo.
echo   Checking system status via MQTT...
echo.

"C:\Program Files\mosquitto\mosquitto_pub.exe" -h localhost -p 1884 -t "nisystem/system/status/request" -m "" >nul 2>&1
timeout /t 1 /nobreak >nul
"C:\Program Files\mosquitto\mosquitto_sub.exe" -h localhost -p 1884 -t "nisystem/status/system" -C 1 2>nul

echo.
echo ================================================================================
echo   Opening DHW Test Dashboard...
echo ================================================================================
timeout /t 2 /nobreak >nul
start http://localhost:5173

echo.
echo   Services running. Check browser for DHW dashboard.
echo   Press any key to exit (services will keep running)...
pause >nul
