@echo off
REM Clean cRIO - Remove ALL deployed files for a fresh start
REM Usage: clean_crio.bat [crio_host]
REM Default crio_host: 192.168.1.20

set HOST=%1
if "%HOST%"=="" set HOST=192.168.1.20

echo ============================================
echo  Clean cRIO: %HOST%
echo ============================================
echo.
echo This will REMOVE everything under /home/admin/nisystem/
echo including saved config, logs, and all deployed code.
echo.
echo Press Ctrl+C to cancel, or
pause

echo.
echo Stopping any running services...
ssh admin@%HOST% "pkill -f run_crio_v2.py 2>/dev/null; pkill -f crio_node 2>/dev/null; echo 'Processes stopped'"

echo Removing all files...
ssh admin@%HOST% "rm -rf /home/admin/nisystem && echo 'Removed /home/admin/nisystem'"

echo Removing stale PID files...
ssh admin@%HOST% "rm -f /var/run/crio_node*.pid 2>/dev/null"

echo Verifying clean state...
ssh admin@%HOST% "ls /home/admin/nisystem 2>/dev/null && echo 'WARNING: Directory still exists' || echo 'Clean - directory removed'"

echo.
echo ============================================
echo  cRIO %HOST% is clean.
echo  Run deploy_crio_v2.bat to deploy fresh.
echo ============================================
