@echo off
title ICCSFlux Build
cd /d "%~dp0"

REM ── Auto-elevate to stop a running Mosquitto service ─────────────────────────
REM  Stopping a Windows service needs Administrator. Only elevate when it's
REM  actually needed: a 'mosquitto' service is RUNNING, the caller didn't pass
REM  --keep-broker, and we're not already elevated. (build_exe.py does the stop.)
echo %* | find /i "--keep-broker" >nul && goto :after_elevate
sc query mosquitto 2>nul | find /i "RUNNING" >nul || goto :after_elevate
net session >nul 2>&1 && goto :after_elevate
echo [BUILD] A Mosquitto service is running - elevating to Administrator to stop it...
set "ELEV_ARGS=%*"
if defined ELEV_ARGS (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '%ELEV_ARGS%' -Verb RunAs"
) else (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
)
exit /b
:after_elevate

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

REM Build using build_exe.py (compiles to executables)
"%PYTHON%" scripts\build_exe.py %*

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
