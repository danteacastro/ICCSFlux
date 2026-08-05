@echo off
title ICCSFlux Build
cd /d "%~dp0"

echo.
echo ========================================
echo   ICCSFlux Portable Build (EXE Edition)
echo ========================================
echo.

REM Check if vendor folder exists with required files
if not exist "vendor\mosquitto\mosquitto.exe" (
    echo [ERROR] Vendor folder not populated!
    echo.
    echo Run this first to download dependencies:
    echo   python scripts\download_dependencies.py
    echo.
    pause
    exit /b 1
)

REM Find Python
if exist "venv\Scripts\python.exe" (
    set PYTHON=venv\Scripts\python.exe
) else (
    set PYTHON=python
)

REM Check PyInstaller is installed
"%PYTHON%" -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo [ERROR] PyInstaller not installed!
    echo.
    echo Install it with: pip install pyinstaller
    echo.
    pause
    exit /b 1
)

REM ── Mosquitto broker conflict prompt ────────────────────────────────────────
REM  A running Mosquitto broker must be stopped (needs admin) so the freshly-built
REM  portable can own port 1883. Only ask when it's actually needed: a broker is
REM  running, we're NOT already elevated, and the caller didn't pass --keep-broker.
set "KEEP_BROKER_FLAG="
echo %* | find /i "--keep-broker" >nul && goto :after_broker_check
whoami /groups 2>nul | find "S-1-16-12288" >nul && goto :after_broker_check
sc query mosquitto 2>nul | find /i "RUNNING" >nul || goto :after_broker_check

echo.
echo ------------------------------------------------------------
echo   A running instance of Mosquitto was detected.
echo ------------------------------------------------------------
echo.
echo   It must be stopped before continuing with the build, otherwise
echo   the portable you run next will attach to this external broker
echo   with the wrong config and the dashboard will show
echo   "Connection Lost". Stopping the Mosquitto service requires
echo   administrator privileges.
echo.
echo     [1] Stop Mosquitto automatically   (opens an elevated window)
echo     [2] Continue without privileges    (leave Mosquitto running; build anyway)
echo     [3] Halt the build                 (stop Mosquitto yourself, or re-run elevated)
echo.
choice /c 123 /n /m "Select [1/2/3]: "
if errorlevel 3 goto :broker_halt
if errorlevel 2 goto :broker_continue

REM [1] Elevate: relaunch this build in an Administrator window, then exit this one.
echo.
echo [BUILD] Opening an elevated window to stop Mosquitto and build...
set "ELEV_ARGS=%*"
if defined ELEV_ARGS (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '%ELEV_ARGS%' -Verb RunAs"
) else (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
)
exit /b

:broker_continue
echo.
echo [BUILD] Continuing WITHOUT stopping Mosquitto (--keep-broker).
echo         The built portable may fail to connect until you stop the old broker.
set "KEEP_BROKER_FLAG=--keep-broker"
goto :after_broker_check

:broker_halt
echo.
echo [BUILD] Build halted. Stop Mosquitto yourself (as admin: net stop mosquitto),
echo         or re-run build.bat from an elevated terminal.
echo.
pause
exit /b 1

:after_broker_check

REM Build using build_exe.py (compiles to executables)
"%PYTHON%" scripts\build_exe.py %* %KEEP_BROKER_FLAG%

echo.
if errorlevel 1 (
    echo Build failed.
) else (
    echo.
    echo Build complete: dist\ICCSFlux-Portable\
    echo.
    echo To run: dist\ICCSFlux-Portable\ICCSFlux.exe
)
echo.
pause
