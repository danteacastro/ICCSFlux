@echo off
setlocal
:: NISystem Service Manager
:: Run as Administrator for full functionality

if exist "%~dp0venv\Scripts\python.exe" (
    set PYTHON=%~dp0venv\Scripts\python.exe
) else (
    set PYTHON=python
)

if "%1"=="" goto menu
goto %1

:menu
echo.
echo ============================================
echo   NISystem Service Manager
echo ============================================
echo.
echo   1. install   - Install as Windows service
echo   2. uninstall - Remove Windows service
echo   3. start     - Start services
echo   4. stop      - Stop services
echo   5. restart   - Restart services
echo   6. status    - Show service status
echo   7. logs      - View recent logs
echo.
echo Usage: service.bat [command]
echo.
"%PYTHON%" "%~dp0services\service_manager.py" status
goto end

:install
echo Installing NISystem services...
"%PYTHON%" "%~dp0services\service_manager.py" install
goto end

:uninstall
echo Uninstalling NISystem services...
"%PYTHON%" "%~dp0services\service_manager.py" uninstall
goto end

:start
echo Starting NISystem services...
"%PYTHON%" "%~dp0services\service_manager.py" start
goto end

:stop
echo Stopping NISystem services...
"%PYTHON%" "%~dp0services\service_manager.py" stop
goto end

:restart
echo Restarting NISystem services...
"%PYTHON%" "%~dp0services\service_manager.py" restart
goto end

:status
"%PYTHON%" "%~dp0services\service_manager.py" status
goto end

:logs
"%PYTHON%" "%~dp0services\service_manager.py" logs
goto end

:end
if "%1"=="" pause
