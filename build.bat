@echo off
title ICCSFlux Build
cd /d "%~dp0"

echo.
echo ========================================
echo   ICCSFlux Portable Build (Offline)
echo ========================================
echo.

REM Check if vendor folder exists with required files
if not exist "vendor\python\python-3.11.7-embed-amd64.zip" (
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

REM Build using offline mode (uses vendor/ folder)
"%PYTHON%" scripts\build_portable.py --offline %*

echo.
if errorlevel 1 (
    echo Build failed.
) else (
    echo.
    echo Build complete: dist\ICCSFlux-Portable\
    echo.
    echo To run: dist\ICCSFlux-Portable\ICCSFlux.bat
)
echo.
pause
