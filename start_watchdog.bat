@echo off
REM =============================================================================
REM NISystem Watchdog - Run as separate process for safety monitoring
REM Monitors DAQ service heartbeat and triggers failsafe if unresponsive
REM =============================================================================

cd /d "%~dp0"

echo Starting NISystem Watchdog...
echo.
echo Watchdog will:
echo   - Monitor DAQ service heartbeat every 2 seconds
echo   - Trigger failsafe if no heartbeat for 10 seconds
echo   - Attempt to restart DAQ service on failure
echo.
echo Press Ctrl+C to stop watchdog
echo.

venv\Scripts\python.exe services\daq_service\watchdog.py -c config\system.ini
