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
echo [1/4] Starting MQTT Broker...
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
echo [2/4] Starting DAQ Service with DHW Test Configuration...
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
REM Step 3: Load DHW Project via MQTT
REM ============================================================================
echo [3/4] Loading DHW Test Project...
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
REM Step 4: Start Frontend
REM ============================================================================
echo [4/4] Starting Frontend Dashboard...
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
