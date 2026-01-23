@echo off
REM Setup MQTT Security for NISystem
REM Run this once to create password file and configure Mosquitto

echo ============================================
echo  NISystem MQTT Security Setup
echo ============================================
echo.

set MOSQUITTO_PATH=C:\Program Files\mosquitto
set CONFIG_PATH=C:\Users\User\Documents\Projects\NISystem\config
set DATA_PATH=C:\Users\User\Documents\Projects\NISystem\data\mosquitto

REM Create data directory
if not exist "%DATA_PATH%" mkdir "%DATA_PATH%"

REM Generate password file
echo Creating password file...
echo.

REM Backend service password (change this in production!)
echo Creating backend user (password: nisystem_backend_2024)
"%MOSQUITTO_PATH%\mosquitto_passwd.exe" -c -b "%CONFIG_PATH%\mosquitto_passwd" backend nisystem_backend_2024

REM Dashboard user password (change this in production!)
echo Creating dashboard user (password: nisystem_dashboard_2024)
"%MOSQUITTO_PATH%\mosquitto_passwd.exe" -b "%CONFIG_PATH%\mosquitto_passwd" dashboard nisystem_dashboard_2024

echo.
echo Password file created at: %CONFIG_PATH%\mosquitto_passwd
echo.

REM Test the config
echo Testing configuration...
"%MOSQUITTO_PATH%\mosquitto.exe" -c "%CONFIG_PATH%\mosquitto_secure.conf" -t
if %ERRORLEVEL% EQU 0 (
    echo Configuration is valid!
) else (
    echo ERROR: Configuration has errors. Please check the config file.
    pause
    exit /b 1
)

echo.
echo ============================================
echo  Setup Complete!
echo ============================================
echo.
echo To use secured MQTT:
echo   1. Stop any running Mosquitto instance
echo   2. Start with: mosquitto -c "%CONFIG_PATH%\mosquitto_secure.conf"
echo.
echo Update your services to use these credentials:
echo   Backend:   username=backend, password=nisystem_backend_2024
echo   Dashboard: username=dashboard, password=nisystem_dashboard_2024
echo.
echo IMPORTANT: Change these passwords in production!
echo.
pause
