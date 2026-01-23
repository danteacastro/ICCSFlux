@echo off
setlocal enabledelayedexpansion
:: NISystem Device CLI
:: Unified command-line interface for industrial devices
:: Supports: cRIO, cDAQ, Opto-22, cFP (CompactFieldPoint)

cd /d "%~dp0"

if exist "%~dp0venv\Scripts\python.exe" (
    set PYTHON=%~dp0venv\Scripts\python.exe
) else (
    set PYTHON=python
)

if "%1"=="" goto menu

:: Route to appropriate handler based on command
if /i "%1"=="deploy" goto node_cmd
if /i "%1"=="logs" goto node_cmd
if /i "%1"=="restart" goto node_cmd
if /i "%1"=="install" goto node_cmd
if /i "%1"=="config" goto node_cmd
if /i "%1"=="node" goto node_subcmd

:: All other commands go to device_cli.py (MQTT operations)
goto device_cmd

:menu
echo.
echo ============================================
echo   NISystem Device CLI
echo ============================================
echo   Supports: cRIO, cDAQ, Opto-22, cFP
echo.
echo   INTERACTIVE MODE:
echo     device                 Start interactive shell
echo.
echo   HARDWARE DISCOVERY:
echo     device scan            Scan for all devices
echo     device scan local      Scan local NI hardware (cDAQ)
echo     device scan network    Scan network for devices
echo     device ping            Discover online MQTT nodes
echo.
echo   DEVICE INFORMATION:
echo     device info ^<node^>     Show device details
echo     device modules ^<node^>  List installed modules
echo     device firmware ^<node^> Show firmware versions
echo     device status          Show all node status
echo.
echo   CHANNEL OPERATIONS:
echo     device channels        List all channels
echo     device read ^<ch^>       Read channel value
echo     device write ^<ch^> ^<v^>  Write to channel
echo     device monitor         Live monitor channels
echo.
echo   DIAGNOSTICS:
echo     device diag ^<node^>     Run diagnostics
echo     device test ^<ch^>       Toggle test an output
echo     device registers ...   Raw Modbus register access
echo.
echo   SAFETY ^& ALARMS:
echo     device alarms          Show active alarms
echo     device safety          Show safety status
echo.
echo   NODE MANAGEMENT (SSH):
echo     device deploy crio     Deploy code to cRIO
echo     device deploy opto22   Deploy code to Opto22
echo     device deploy cfp      Deploy code to cFP
echo     device deploy all -r   Deploy all and restart
echo     device restart ^<node^>  Restart node service
echo     device logs ^<node^>     View node logs
echo     device logs ^<node^> -f  Follow node logs
echo     device config          Show node configuration
echo     device config --setup  Run setup wizard
echo.
echo   OPTIONS:
echo     --broker ^<ip^>         MQTT broker address
echo     --port ^<port^>         MQTT broker port
echo.
echo   Examples:
echo     device                           # Interactive mode
echo     device scan                      # Discover all devices
echo     device info crio-001             # Show cRIO details
echo     device read TC001                # Read thermocouple
echo     device write DO001 1             # Turn on digital output
echo     device test DO001 3 500          # Toggle test 3x @ 500ms
echo     device diag crio-001             # Run diagnostics
echo     device deploy crio --restart     # Deploy and restart
echo     device --broker 192.168.1.100 ping
echo.
"%PYTHON%" "%~dp0services\device_cli.py"
goto end

:node_cmd
:: Commands that go to node_deploy.py
"%PYTHON%" "%~dp0services\node_deploy.py" %*
goto end

:node_subcmd
:: Handle "device node <cmd>" syntax - strip "node" and pass rest
shift
"%PYTHON%" "%~dp0services\node_deploy.py" %1 %2 %3 %4 %5 %6 %7 %8 %9
goto end

:device_cmd
:: Commands that go to device_cli.py (MQTT)
"%PYTHON%" "%~dp0services\device_cli.py" %*
goto end

:end
