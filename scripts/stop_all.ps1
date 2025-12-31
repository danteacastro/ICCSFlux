<#
.SYNOPSIS
    NISystem Stop All Services Script for Windows
.DESCRIPTION
    Stops DAQ service (optionally Mosquitto)
#>

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Split-Path -Parent $ScriptDir

Write-Host "Stopping NISystem services..." -ForegroundColor Yellow
Write-Host ""

# Stop DAQ Service
$pidFile = Join-Path $ProjectDir "logs\daq_service.pid"
if (Test-Path $pidFile) {
    $pid = Get-Content $pidFile
    try {
        $process = Get-Process -Id $pid -ErrorAction SilentlyContinue
        if ($process) {
            Stop-Process -Id $pid -Force
            Write-Host "DAQ Service stopped (PID: $pid)" -ForegroundColor Green
        }
    } catch {
        Write-Host "DAQ Service not running" -ForegroundColor Yellow
    }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
} else {
    # Try to find by process name
    $processes = Get-Process python -ErrorAction SilentlyContinue | Where-Object {
        try {
            $_.CommandLine -like "*daq_service*"
        } catch {
            $false
        }
    }
    if ($processes) {
        $processes | Stop-Process -Force
        Write-Host "DAQ Service stopped" -ForegroundColor Green
    } else {
        Write-Host "DAQ Service not running" -ForegroundColor Yellow
    }
}

# Optionally stop Mosquitto (commented out as it may be used by other services)
# try {
#     Stop-Service mosquitto -ErrorAction SilentlyContinue
#     Write-Host "Mosquitto stopped" -ForegroundColor Green
# } catch {
#     Write-Host "Mosquitto not running as service" -ForegroundColor Yellow
# }

Write-Host ""
Write-Host "All NISystem services stopped" -ForegroundColor Green
