@echo off
title ICCSFlux Fleet Monitor Build
cd /d "%~dp0"

echo.
echo ========================================
echo   ICCSFlux Fleet Monitor Portable Build
echo ========================================
echo.

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

REM Check monitor/package.json exists
if not exist "monitor\package.json" (
    echo [ERROR] monitor\package.json not found!
    echo.
    pause
    exit /b 1
)

REM Build using build_monitor.py
"%PYTHON%" scripts\build_monitor.py %*

echo.
if errorlevel 1 (
    echo Build failed.
) else (
    echo.
    echo Build complete: dist\FleetMonitor-Portable\
    echo.
    echo To run: dist\FleetMonitor-Portable\FleetMonitor.exe
)
echo.
pause
