# NISystem Startup Script for Windows
# Ensures clean state and starts all services in correct order

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Split-Path -Parent $ScriptDir
$VenvPython = Join-Path $ProjectDir "venv\Scripts\python.exe"
$DAQService = Join-Path $ProjectDir "services\daq_service\daq_service.py"
$ConfigFile = Join-Path $ProjectDir "config\system.ini"
$PidFile = Join-Path $env:TEMP "nisystem-daq.pid"
$LogFile = Join-Path $env:TEMP "nisystem-daq.log"

function Write-Info { param($msg) Write-Host "[INFO] $msg" -ForegroundColor Green }
function Write-Warn { param($msg) Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Write-Err { param($msg) Write-Host "[ERROR] $msg" -ForegroundColor Red }

function Stop-Services {
    Write-Info "Stopping existing services..."

    # Kill by PID file
    if (Test-Path $PidFile) {
        $oldPid = Get-Content $PidFile
        try {
            Stop-Process -Id $oldPid -Force -ErrorAction SilentlyContinue
        } catch {}
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    }

    # Kill any orphaned processes
    Get-Process -Name "python*" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*daq_service*" } |
        Stop-Process -Force -ErrorAction SilentlyContinue

    Start-Sleep -Seconds 1
}

function Test-Prerequisites {
    Write-Info "Checking prerequisites..."

    if (-not (Test-Path $VenvPython)) {
        Write-Err "Python venv not found at $VenvPython"
        exit 1
    }

    if (-not (Test-Path $ConfigFile)) {
        Write-Err "Config file not found at $ConfigFile"
        exit 1
    }

    # Check MQTT broker (mosquitto)
    $mosquitto = Get-Process -Name "mosquitto" -ErrorAction SilentlyContinue
    if (-not $mosquitto) {
        Write-Warn "Mosquitto not running. Please start it manually or install as a service."
        Write-Warn "Download from: https://mosquitto.org/download/"
    }

    Write-Info "Prerequisites OK"
}

function Start-DAQService {
    Write-Info "Starting DAQ service..."

    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $VenvPython
    $startInfo.Arguments = "`"$DAQService`" -c `"$ConfigFile`""
    $startInfo.WorkingDirectory = Join-Path $ProjectDir "services\daq_service"
    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.CreateNoWindow = $true

    $process = [System.Diagnostics.Process]::Start($startInfo)

    # Save PID
    $process.Id | Out-File $PidFile -Encoding ASCII

    Start-Sleep -Seconds 2

    if ($process.HasExited) {
        Write-Err "DAQ service failed to start"
        exit 1
    }

    Write-Info "DAQ service started (PID: $($process.Id))"
}

function Test-System {
    Write-Info "Verifying system..."

    # Try to get MQTT status (requires mosquitto_sub in PATH)
    try {
        $status = & mosquitto_sub -h localhost -t "nisystem/status/system" -C 1 -W 3 2>$null
        if ($status) {
            Write-Info "System online and publishing"
        }
    } catch {
        Write-Warn "Could not verify MQTT status"
    }
}

# Main
Write-Host "========================================"
Write-Host "  NISystem Startup (Windows)"
Write-Host "========================================"

Stop-Services
Test-Prerequisites
Start-DAQService
Test-System

Write-Host "========================================"
Write-Info "NISystem ready"
Write-Host "  DAQ Service PID: $(Get-Content $PidFile)"
Write-Host "  Log file: $LogFile"
Write-Host "  Dashboard: http://localhost:5173"
Write-Host "========================================"
