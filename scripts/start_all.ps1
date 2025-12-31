<#
.SYNOPSIS
    NISystem Start All Services Script for Windows
.DESCRIPTION
    Starts MQTT broker and DAQ service
#>

$ErrorActionPreference = "Continue"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Split-Path -Parent $ScriptDir

Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "NISystem - Starting All Services"
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host ""

function Start-Mosquitto {
    Write-Host "Starting Mosquitto MQTT Broker..." -ForegroundColor Yellow

    # Check if already running
    $mosquittoProcess = Get-Process mosquitto -ErrorAction SilentlyContinue
    if ($mosquittoProcess) {
        Write-Host "Mosquitto already running" -ForegroundColor Green
        return
    }

    # Try to start as service
    try {
        $service = Get-Service mosquitto -ErrorAction SilentlyContinue
        if ($service) {
            if ($service.Status -ne 'Running') {
                Start-Service mosquitto
            }
            Write-Host "Mosquitto service started" -ForegroundColor Green
            return
        }
    } catch {
        # Service doesn't exist, try running directly
    }

    # Run directly if service not available
    $mosquittoPath = "C:\Program Files\mosquitto\mosquitto.exe"
    if (Test-Path $mosquittoPath) {
        Start-Process -FilePath $mosquittoPath -WindowStyle Hidden
        Write-Host "Mosquitto started" -ForegroundColor Green
    } else {
        Write-Host "Warning: Mosquitto not found. Install with: choco install mosquitto" -ForegroundColor Yellow
    }
}

function Start-DAQService {
    Write-Host "Starting DAQ Service..." -ForegroundColor Yellow

    # Check if already running
    $existingProcess = Get-Process python -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -like "*daq_service*"
    }
    if ($existingProcess) {
        Write-Host "DAQ Service already running" -ForegroundColor Green
        return
    }

    # Activate virtual environment and run
    $venvPath = Join-Path $ProjectDir "venv"
    $pythonPath = Join-Path $venvPath "Scripts\python.exe"
    $servicePath = Join-Path $ProjectDir "services\daq_service\daq_service.py"
    $configPath = Join-Path $ProjectDir "config\system.ini"
    $logPath = Join-Path $ProjectDir "logs\daq_service.log"

    if (-not (Test-Path $pythonPath)) {
        Write-Host "Error: Virtual environment not found. Run install_dependencies.ps1 first." -ForegroundColor Red
        return
    }

    # Create logs directory if needed
    $logsDir = Join-Path $ProjectDir "logs"
    if (-not (Test-Path $logsDir)) {
        New-Item -ItemType Directory -Path $logsDir -Force | Out-Null
    }

    # Start DAQ service
    $process = Start-Process -FilePath $pythonPath `
        -ArgumentList "$servicePath -c `"$configPath`"" `
        -WorkingDirectory (Join-Path $ProjectDir "services\daq_service") `
        -WindowStyle Hidden `
        -RedirectStandardOutput $logPath `
        -RedirectStandardError (Join-Path $ProjectDir "logs\daq_service_error.log") `
        -PassThru

    # Save PID
    $process.Id | Out-File (Join-Path $ProjectDir "logs\daq_service.pid")

    Write-Host "DAQ Service started (PID: $($process.Id))" -ForegroundColor Green
}

# Create logs directory
$logsDir = Join-Path $ProjectDir "logs"
if (-not (Test-Path $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir -Force | Out-Null
}

# Main startup sequence
Start-Mosquitto
Write-Host ""
Start-DAQService

Write-Host ""
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "NISystem Started"
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Services:"
Write-Host "  - MQTT Broker:    localhost:1883"
Write-Host "  - DAQ Service:    Running (simulation mode)"
Write-Host ""
Write-Host "To start the dashboard:"
Write-Host "  cd dashboard"
Write-Host "  npm run dev"
Write-Host ""
Write-Host "Logs:"
Write-Host "  - DAQ Service:    $ProjectDir\logs\daq_service.log"
Write-Host ""
Write-Host "To stop all services: .\scripts\stop_all.ps1"
Write-Host ""
