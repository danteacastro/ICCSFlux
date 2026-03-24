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
