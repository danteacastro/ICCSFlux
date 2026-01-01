@echo off
REM NISystem Portable Builder
REM Run this on your development machine to create the portable package.
REM Requirements: Python 3.10+, Node.js, npm

echo ============================================================
echo   NISystem Portable Builder
echo ============================================================
echo.

cd /d "%~dp0"

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.10+ first.
    pause
    exit /b 1
)

REM Check Node
node --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js not found. Install Node.js first.
    pause
    exit /b 1
)

REM Run the build script
python build.py

echo.
pause
