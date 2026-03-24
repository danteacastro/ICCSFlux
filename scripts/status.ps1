# NISystem Status Script for Windows

$PidFile = Join-Path $env:TEMP "nisystem-daq.pid"

Write-Host "========================================"
Write-Host "  NISystem Status"
Write-Host "========================================"

# Check Mosquitto
$mosquitto = Get-Process -Name "mosquitto" -ErrorAction SilentlyContinue
if ($mosquitto) {
    Write-Host "MQTT Broker:    " -NoNewline
    Write-Host "RUNNING" -ForegroundColor Green
} else {
    Write-Host "MQTT Broker:    " -NoNewline
    Write-Host "STOPPED" -ForegroundColor Red
}

# Check DAQ Service
if (Test-Path $PidFile) {
    $pid = Get-Content $PidFile
    try {
        $proc = Get-Process -Id $pid -ErrorAction Stop
        Write-Host "DAQ Service:    " -NoNewline
        Write-Host "RUNNING (PID: $pid)" -ForegroundColor Green
    } catch {
        Write-Host "DAQ Service:    " -NoNewline
        Write-Host "STOPPED (stale PID file)" -ForegroundColor Red
    }
} else {
    # Check for orphaned process
    $orphan = Get-Process -Name "python*" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*daq_service*" } |
        Select-Object -First 1

    if ($orphan) {
        Write-Host "DAQ Service:    " -NoNewline
        Write-Host "ORPHANED (PID: $($orphan.Id))" -ForegroundColor Yellow
    } else {
        Write-Host "DAQ Service:    " -NoNewline
        Write-Host "STOPPED" -ForegroundColor Red
    }
}

Write-Host "========================================"
