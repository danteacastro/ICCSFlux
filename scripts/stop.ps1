# NISystem Stop Script for Windows

$PidFile = Join-Path $env:TEMP "nisystem-daq.pid"

function Write-Info { param($msg) Write-Host "[INFO] $msg" -ForegroundColor Green }

Write-Info "Stopping NISystem services..."

# Stop via PID file
if (Test-Path $PidFile) {
    $pid = Get-Content $PidFile
    try {
        Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
        Write-Info "Stopped DAQ service (PID: $pid)"
    } catch {}
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
}

# Clean up any remaining processes
Get-Process -Name "python*" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*daq_service*" } |
    Stop-Process -Force -ErrorAction SilentlyContinue

Write-Info "NISystem stopped"
