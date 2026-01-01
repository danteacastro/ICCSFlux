@echo off
title NISystem
cd /d "%~dp0"

echo Starting NISystem...
echo.

REM Start Mosquitto
start /B "" "runtime\mosquitto\mosquitto.exe" -c "runtime\mosquitto\mosquitto.conf"
timeout /t 1 /nobreak >nul

REM Start DAQ Service
start /B "" "runtime\python\python.exe" "services\daq_service\daq_service.py" -c "config\system.ini"
timeout /t 2 /nobreak >nul

REM Start web server and open browser
start http://localhost:5173
"runtime\python\python.exe" -m http.server 5173 --directory www

REM When web server stops, kill other processes
taskkill /F /IM mosquitto.exe >nul 2>&1
