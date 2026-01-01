@echo off
REM NISystem Dependency Installer for Windows
REM Run this once after cloning the project

setlocal enabledelayedexpansion

echo ========================================
echo   NISystem Dependency Installer
echo ========================================
echo.

REM Get script directory
set "SCRIPT_DIR=%~dp0"
set "PROJECT_DIR=%SCRIPT_DIR%.."
cd /d "%PROJECT_DIR%"

REM Check Python
echo Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install from https://www.python.org/downloads/
    echo         Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)
for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYTHON_VERSION=%%i
echo [OK] Python %PYTHON_VERSION%

REM Check Node.js
echo Checking Node.js...
node --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js not found. Install from https://nodejs.org/
    pause
    exit /b 1
)
for /f %%i in ('node --version') do set NODE_VERSION=%%i
echo [OK] Node.js %NODE_VERSION%

REM Check npm
echo Checking npm...
npm --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] npm not found. Should be installed with Node.js.
    pause
    exit /b 1
)
for /f %%i in ('npm --version') do set NPM_VERSION=%%i
echo [OK] npm %NPM_VERSION%

REM Check Mosquitto
echo Checking Mosquitto MQTT broker...
sc query mosquitto >nul 2>&1
if errorlevel 1 (
    echo [WARN] Mosquitto service not found.
    echo        Install from https://mosquitto.org/download/
    echo        Select "Install as Windows Service" during setup.
    echo.
    set MOSQUITTO_MISSING=1
) else (
    echo [OK] Mosquitto service installed
)

echo.
echo ========================================
echo   Installing Project Dependencies
echo ========================================
echo.

REM Create Python virtual environment
if not exist "venv" (
    echo Creating Python virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment
        pause
        exit /b 1
    )
    echo [OK] Virtual environment created
) else (
    echo [OK] Virtual environment exists
)

REM Activate venv and install Python packages
echo Installing Python dependencies...
call venv\Scripts\activate.bat

pip install --upgrade pip >nul 2>&1
pip install paho-mqtt >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Failed to install paho-mqtt
    pause
    exit /b 1
)
echo [OK] paho-mqtt

pip install pyinstaller >nul 2>&1
echo [OK] pyinstaller

REM Check for NI-DAQmx (optional)
pip install nidaqmx >nul 2>&1
if errorlevel 1 (
    echo [WARN] nidaqmx not installed - simulation mode only
) else (
    echo [OK] nidaqmx (optional - for real hardware)
)

REM Install dashboard dependencies
echo.
echo Installing dashboard dependencies...
cd dashboard
if not exist "node_modules" (
    call npm install
    if errorlevel 1 (
        echo [ERROR] Failed to install npm packages
        cd ..
        pause
        exit /b 1
    )
)
echo [OK] Dashboard dependencies
cd ..

REM Build launcher executable
echo.
echo Building launcher executable...
cd launcher
if not exist "dist\NISystem Launcher.exe" (
    pyinstaller --onefile --windowed --name "NISystem Launcher" nisystem_launcher.py >nul 2>&1
    if exist "dist\NISystem Launcher.exe" (
        echo [OK] Launcher built: launcher\dist\NISystem Launcher.exe
    ) else (
        echo [WARN] Launcher build failed - you can still use scripts
    )
) else (
    echo [OK] Launcher already built
)
cd ..

echo.
echo ========================================
echo   Installation Complete
echo ========================================
echo.

if defined MOSQUITTO_MISSING (
    echo [!] Remember to install Mosquitto MQTT broker
    echo     https://mosquitto.org/download/
    echo.
)

echo To start the system:
echo   1. Run: launcher\dist\NISystem Launcher.exe
echo   OR
echo   2. Run: scripts\start.ps1
echo.
echo To start the dashboard:
echo   cd dashboard
echo   npm run dev
echo.
echo Dashboard will be at: http://localhost:5173
echo.

pause
