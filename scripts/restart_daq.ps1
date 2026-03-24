# =============================================================================
# NISystem DAQ Service Weekly Restart Script
# Schedule with Windows Task Scheduler for Sunday 3 AM
# =============================================================================

$ProjectPath = "C:\Users\User\Documents\Projects\NISystem"

Write-Host "$(Get-Date) - Stopping NISystem services..."

# Stop existing Python processes (DAQ service)
Stop-Process -Name "python" -Force -ErrorAction SilentlyContinue

# Wait for processes to terminate
Start-Sleep -Seconds 5

# Change to project directory
Set-Location $ProjectPath

Write-Host "$(Get-Date) - Starting DAQ service..."

# Start DAQ service
Start-Process -FilePath "venv\Scripts\python.exe" `
    -ArgumentList "services\daq_service\daq_service.py", "-c", "config\system.ini", "--force" `
    -WindowStyle Hidden

Write-Host "$(Get-Date) - DAQ service restarted successfully"
