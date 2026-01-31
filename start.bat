@echo off
REM ============================================================================
REM NISystem Simple Startup - Each service in its own visible window
REM Re-running this script will kill previous windows and start fresh
REM ============================================================================

cd /d "C:\Users\User\Documents\Projects\NISystem"

echo.
echo ================================================================================
echo   NISystem - Starting Services
echo ================================================================================
echo.

REM Check prerequisites
if not exist "venv\Scripts\python.exe" (
    echo ERROR: Python virtual environment not found!
    pause
    exit /b 1
)

REM ============================================================================
REM Kill previous NISystem processes and windows (allows clean restart)
REM ============================================================================
echo [1/5] Cleaning up previous NISystem processes...

REM Stop Mosquitto Windows Service if running
net stop mosquitto >nul 2>&1

REM Kill processes by executable name (most reliable)
taskkill /F /IM mosquitto.exe >nul 2>&1

REM Kill Python processes running our services using psutil
venv\Scripts\python.exe -c "import psutil; [p.kill() for p in psutil.process_iter(['cmdline']) if p.cmdline() and 'daq_service' in ' '.join(p.cmdline()).lower()]" 2>nul
venv\Scripts\python.exe -c "import psutil; [p.kill() for p in psutil.process_iter(['cmdline']) if p.cmdline() and 'watchdog.py' in ' '.join(p.cmdline()).lower()]" 2>nul

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
REM Start MQTT Broker (Mosquitto)
REM ============================================================================
echo [2/5] Starting MQTT Broker...
start "MQTT Broker" cmd /k "cd /d C:\Users\User\Documents\Projects\NISystem && echo === MQTT BROKER === && echo. && "C:\Program Files\mosquitto\mosquitto.exe" -v -c config\mosquitto.conf"
timeout /t 2 /nobreak >nul
echo.

REM ============================================================================
REM Start DAQ Service
REM ============================================================================
echo [3/5] Starting DAQ Service...
start "DAQ Service" cmd /k "cd /d C:\Users\User\Documents\Projects\NISystem && echo === DAQ SERVICE === && echo. && venv\Scripts\python.exe services\daq_service\daq_service.py -c config\system.ini"
timeout /t 3 /nobreak >nul
echo.

REM ============================================================================
REM Start Watchdog
REM ============================================================================
echo [4/5] Starting Watchdog...
start "Watchdog" cmd /k "cd /d C:\Users\User\Documents\Projects\NISystem && echo === WATCHDOG === && echo. && venv\Scripts\python.exe services\daq_service\watchdog.py -c config\system.ini"
timeout /t 1 /nobreak >nul
echo.

REM ============================================================================
REM Start Frontend (Vite)
REM ============================================================================
echo [5/5] Starting Frontend...
start "Frontend (Vite)" cmd /k "cd /d C:\Users\User\Documents\Projects\NISystem\dashboard && echo === FRONTEND (VITE) === && echo. && npm run dev"
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
