@echo off
REM ============================================================================
REM NISystem Simple Startup - Each service in its own visible window
REM Re-running this script will kill previous windows and start fresh
REM ============================================================================

REM Use the batch file's own directory as project root (portable)
set "NISYSTEM_ROOT=%~dp0"
REM Remove trailing backslash
if "%NISYSTEM_ROOT:~-1%"=="\" set "NISYSTEM_ROOT=%NISYSTEM_ROOT:~0,-1%"

cd /d "%NISYSTEM_ROOT%"

echo.
echo ================================================================================
echo   NISystem - Starting Services
echo ================================================================================
echo.

REM Check prerequisites
if not exist "%NISYSTEM_ROOT%\venv\Scripts\python.exe" (
    echo ERROR: Python virtual environment not found!
    pause
    exit /b 1
)

REM ============================================================================
REM Kill previous NISystem processes and windows (allows clean restart)
REM ============================================================================
echo [1/6] Cleaning up previous NISystem processes...

REM Stop Mosquitto Windows Service if running
net stop mosquitto >nul 2>&1

REM Kill processes by executable name (most reliable)
taskkill /F /IM mosquitto.exe >nul 2>&1

REM Kill Python processes running our services using psutil
"%NISYSTEM_ROOT%\venv\Scripts\python.exe" -c "import psutil; [p.kill() for p in psutil.process_iter(['cmdline']) if p.cmdline() and 'daq_service' in ' '.join(p.cmdline()).lower()]" 2>nul
"%NISYSTEM_ROOT%\venv\Scripts\python.exe" -c "import psutil; [p.kill() for p in psutil.process_iter(['cmdline']) if p.cmdline() and 'watchdog.py' in ' '.join(p.cmdline()).lower()]" 2>nul

REM Kill any process on port 5173 (Vite frontend)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5173 ^| findstr LISTENING') do taskkill /F /PID %%a >nul 2>&1

REM Use PowerShell to kill cmd windows by title (more reliable than taskkill filter)
powershell -Command "Get-Process cmd -ErrorAction SilentlyContinue | Where-Object {$_.MainWindowTitle -like 'MQTT Broker*' -or $_.MainWindowTitle -like 'DAQ Service*' -or $_.MainWindowTitle -like 'Watchdog*' -or $_.MainWindowTitle -like 'Frontend*'} | Stop-Process -Force -ErrorAction SilentlyContinue" 2>nul

REM Fallback: taskkill by window title (in case PowerShell missed any)
taskkill /FI "WINDOWTITLE eq MQTT Broker*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq DAQ Service*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Watchdog*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Frontend (Vite)*" /F >nul 2>&1

timeout /t 2 /nobreak >nul
echo   Done.
echo.

REM ============================================================================
REM Auto-generate MQTT credentials (first-run only, idempotent)
REM ============================================================================
echo [2/6] Checking MQTT credentials...
"%NISYSTEM_ROOT%\venv\Scripts\python.exe" "%NISYSTEM_ROOT%\scripts\mqtt_credentials.py"
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Failed to generate MQTT credentials!
    pause
    exit /b 1
)

REM Load MQTT credentials for DAQ service environment
for /f "tokens=1,2 delims=:" %%a in ('"%NISYSTEM_ROOT%\venv\Scripts\python.exe" -c "import json; d=json.load(open(r'%NISYSTEM_ROOT%\config\mqtt_credentials.json')); print(d['backend']['username']+':'+d['backend']['password'])"') do (
    set "MQTT_USERNAME=%%a"
    set "MQTT_PASSWORD=%%b"
)
echo.

REM ============================================================================
REM Generate TLS certificates (if missing — required for MQTT TLS listener)
REM ============================================================================
if not exist "%NISYSTEM_ROOT%\config\tls\ca.crt" (
    echo [3/6] Generating TLS certificates...
    "%NISYSTEM_ROOT%\venv\Scripts\python.exe" scripts\generate_tls_certs.py
    if %ERRORLEVEL% NEQ 0 (
        echo ERROR: TLS certificate generation failed!
        pause
        exit /b 1
    )
) else (
    echo [3/6] TLS certificates OK
)

REM ============================================================================
REM Start MQTT Broker (Mosquitto)
REM ============================================================================
echo [3b/6] Starting MQTT Broker...
start "MQTT Broker" cmd /k "cd /d "%NISYSTEM_ROOT%" && echo === MQTT BROKER === && echo. && "C:\Program Files\mosquitto\mosquitto.exe" -v -c config\mosquitto.conf"
timeout /t 2 /nobreak >nul
echo.

REM ============================================================================
REM Start DAQ Service (with MQTT credentials in environment)
REM ============================================================================
echo [4/6] Starting DAQ Service...
start "DAQ Service" cmd /k "cd /d "%NISYSTEM_ROOT%" && set "MQTT_USERNAME=%MQTT_USERNAME%" && set "MQTT_PASSWORD=%MQTT_PASSWORD%" && echo === DAQ SERVICE === && echo. && venv\Scripts\python.exe services\daq_service\daq_service.py -c config\system.ini"
timeout /t 3 /nobreak >nul
echo.

REM ============================================================================
REM Start Watchdog
REM ============================================================================
echo [5/6] Starting Watchdog...
start "Watchdog" cmd /k "cd /d "%NISYSTEM_ROOT%" && echo === WATCHDOG === && echo. && venv\Scripts\python.exe services\daq_service\watchdog.py -c config\system.ini"
timeout /t 1 /nobreak >nul
echo.

REM ============================================================================
REM Start Frontend (Vite)
REM ============================================================================
echo [6/6] Starting Frontend...
start "Frontend (Vite)" cmd /k "cd /d "%NISYSTEM_ROOT%\dashboard" && echo === FRONTEND (VITE) === && echo. && npm run dev"
echo.

REM ============================================================================
REM Done
REM ============================================================================
echo ================================================================================
echo   All services started in separate windows!
echo ================================================================================
echo.
echo   MQTT Broker:  Window titled "MQTT Broker"
echo   DAQ Service:  Window titled "DAQ Service"
echo   Watchdog:     Window titled "Watchdog"
echo   Frontend:     Window titled "Frontend (Vite)"
echo.
echo   Dashboard: http://localhost:5173
echo.
echo   Opening dashboard in 5 seconds...
timeout /t 5 /nobreak >nul
start http://localhost:5173

echo.
echo   Re-run this script to restart all services with fresh windows.
echo.
echo   TIP: For unattended operation, use: python scripts/supervisor.py
echo   The supervisor auto-restarts crashed services with exponential backoff.
echo.
