@echo off
REM Deploy cRIO Node V2 to cRIO and restart service
REM Usage: deploy_crio_v2.bat [crio_host] [broker_host]
REM Default crio_host: 192.168.1.20
REM Default broker_host: 192.168.1.1 (PC running MQTT broker)

set HOST=%1
if "%HOST%"=="" set HOST=192.168.1.20

set BROKER=%2
if "%BROKER%"=="" set BROKER=192.168.1.1

echo ============================================
echo Deploying cRIO Node V2
echo   cRIO Host: %HOST%
echo   MQTT Broker: %BROKER%
echo ============================================

REM Check SSH connectivity
echo Checking connection...
ssh admin@%HOST% "echo 'Connected'" 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo SSH failed! Check connection to %HOST%
    exit /b 1
)

REM Verify and install Python dependencies on cRIO
REM All wheels stored in vendor\crio-packages\ (manylinux x86_64, cp312)
echo Checking dependencies...
set DEPS_OK=1

ssh admin@%HOST% "python3 -c \"import paho.mqtt.client\" 2>/dev/null"
if %ERRORLEVEL% NEQ 0 (
    echo   paho-mqtt missing, installing...
    scp vendor\crio-packages\paho_mqtt-2.1.0-py3-none-any.whl admin@%HOST%:/tmp/
    ssh admin@%HOST% "python3 -m pip install /tmp/paho_mqtt-2.1.0-py3-none-any.whl --quiet && rm /tmp/paho_mqtt-2.1.0-py3-none-any.whl"
    set DEPS_OK=0
)

ssh admin@%HOST% "python3 -c \"import numpy\" 2>/dev/null"
if %ERRORLEVEL% NEQ 0 (
    echo   numpy missing, installing...
    scp vendor\crio-packages\numpy-2.2.6-cp312-cp312-manylinux_2_17_x86_64.manylinux2014_x86_64.whl admin@%HOST%:/tmp/
    ssh admin@%HOST% "python3 -m pip install /tmp/numpy-2.2.6-cp312-cp312-manylinux_2_17_x86_64.manylinux2014_x86_64.whl --quiet && rm /tmp/numpy-2.2.6-cp312-cp312-manylinux_2_17_x86_64.manylinux2014_x86_64.whl"
    set DEPS_OK=0
)

ssh admin@%HOST% "python3 -c \"import scipy\" 2>/dev/null"
if %ERRORLEVEL% NEQ 0 (
    echo   scipy missing, installing...
    scp vendor\crio-packages\scipy-1.16.3-cp312-cp312-manylinux2014_x86_64.manylinux_2_17_x86_64.whl admin@%HOST%:/tmp/
    ssh admin@%HOST% "python3 -m pip install /tmp/scipy-1.16.3-cp312-cp312-manylinux2014_x86_64.manylinux_2_17_x86_64.whl --quiet && rm /tmp/scipy-1.16.3-cp312-cp312-manylinux2014_x86_64.manylinux_2_17_x86_64.whl"
    set DEPS_OK=0
)

if %DEPS_OK%==1 (
    echo   All dependencies OK
)

REM Verify critical dependency
ssh admin@%HOST% "python3 -c \"import paho.mqtt.client\" 2>/dev/null"
if %ERRORLEVEL% NEQ 0 (
    echo FATAL: paho-mqtt install failed on cRIO.
    exit /b 1
)

REM nidaqmx is provided by NI Linux RT - warn if missing but don't fail
ssh admin@%HOST% "python3 -c \"import nidaqmx\" 2>/dev/null"
if %ERRORLEVEL% NEQ 0 (
    echo   NOTE: nidaqmx not found - will use mock hardware. Install NI-DAQmx RT on cRIO for real hardware.
)

REM Stop existing service
echo Stopping existing service...
ssh admin@%HOST% "pkill -f run_crio_v2.py 2>/dev/null; pkill -f crio_node 2>/dev/null; echo 'Service stopped'"

REM Clean old deployment (preserve config + state)
echo Cleaning old deployment (preserving config + state)...
ssh admin@%HOST% "rm -rf /home/admin/nisystem/crio_node_v2 /home/admin/nisystem/daq_core /home/admin/nisystem/run_crio_v2.py 2>/dev/null; rm -f /home/admin/nisystem/*.log /home/admin/nisystem/logs/*.log 2>/dev/null; echo 'Clean'"

REM Create directory structure on cRIO
echo Creating directories...
ssh admin@%HOST% "mkdir -p /home/admin/nisystem/crio_node_v2 /home/admin/nisystem/logs"

REM Deploy crio_node_v2 module files (10 files)
echo Deploying crio_node_v2...
scp services\crio_node_v2\__init__.py admin@%HOST%:/home/admin/nisystem/crio_node_v2/
scp services\crio_node_v2\__main__.py admin@%HOST%:/home/admin/nisystem/crio_node_v2/
scp services\crio_node_v2\state_machine.py admin@%HOST%:/home/admin/nisystem/crio_node_v2/
scp services\crio_node_v2\hardware.py admin@%HOST%:/home/admin/nisystem/crio_node_v2/
scp services\crio_node_v2\mqtt_interface.py admin@%HOST%:/home/admin/nisystem/crio_node_v2/
scp services\crio_node_v2\crio_node.py admin@%HOST%:/home/admin/nisystem/crio_node_v2/
scp services\crio_node_v2\safety.py admin@%HOST%:/home/admin/nisystem/crio_node_v2/
scp services\crio_node_v2\config.py admin@%HOST%:/home/admin/nisystem/crio_node_v2/
scp services\crio_node_v2\channel_types.py admin@%HOST%:/home/admin/nisystem/crio_node_v2/
scp services\crio_node_v2\script_engine.py admin@%HOST%:/home/admin/nisystem/crio_node_v2/

if %ERRORLEVEL% NEQ 0 (
    echo SCP failed!
    exit /b 1
)

REM Deploy the runner script
echo Deploying runner script...
scp scripts\run_crio_v2.py admin@%HOST%:/home/admin/nisystem/run_crio_v2.py

REM Set permissions
echo Setting permissions...
ssh admin@%HOST% "chmod +x /home/admin/nisystem/run_crio_v2.py"

REM Verify deployment
echo Verifying deployment...
ssh admin@%HOST% "python3 -c \"import sys; sys.path.insert(0, '/home/admin/nisystem'); from crio_node_v2.config import ChannelConfig; from crio_node_v2.hardware import create_hardware; print('Import check: OK')\" 2>&1"
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo WARNING: Import verification failed! Check deployment.
)

REM Stop any remaining processes
echo Stopping any existing processes...
ssh admin@%HOST% "pkill -f run_crio_v2.py 2>/dev/null || true"
ssh admin@%HOST% "rm -f /var/run/crio_node_v2.pid 2>/dev/null || true"
ping -n 3 127.0.0.1 > nul 2>&1

REM Verify process is stopped
ssh admin@%HOST% "pgrep -f run_crio_v2.py" > nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo Warning: Process still running, force killing...
    ssh admin@%HOST% "pkill -9 -f run_crio_v2.py 2>/dev/null || true"
    ping -n 3 127.0.0.1 > nul 2>&1
)

echo Starting cRIO Node V2 (broker: %BROKER%)...
ssh admin@%HOST% "cd /home/admin/nisystem && MALLOC_CHECK_=0 python3 run_crio_v2.py --broker %BROKER% --daemon"

REM Clear any retained acquire/start messages so cRIO doesn't auto-acquire
echo Clearing retained acquire messages...
python -c "import paho.mqtt.client as m; c=m.Client('deploy-cleanup'); c.connect('%BROKER%', 1883); c.publish('nisystem/nodes/crio-001/system/acquire/start', b'', retain=True); c.publish('nisystem/nodes/crio-001/system/acquire/stop', b'', retain=True); c.loop(0.5); c.disconnect()" 2>nul

echo.
echo ============================================
echo Deployment complete!
echo ============================================
