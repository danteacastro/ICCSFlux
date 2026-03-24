@echo off
REM Deploy Opto22 Node to groov EPIC
REM Usage: deploy_opto22.bat [epic_host] [broker_host]
REM Defaults: EPIC at 192.168.1.30, broker at 192.168.1.1

set EPIC_HOST=%1
set BROKER_HOST=%2
if "%EPIC_HOST%"=="" set EPIC_HOST=192.168.1.30
if "%BROKER_HOST%"=="" set BROKER_HOST=192.168.1.1

echo Deploying Opto22 Node to %EPIC_HOST% (broker: %BROKER_HOST%)

REM Activate venv if available
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

python scripts\deploy_opto22.py %EPIC_HOST% %BROKER_HOST%
