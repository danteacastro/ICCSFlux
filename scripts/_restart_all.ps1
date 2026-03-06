Set-Location 'c:\Users\User\Documents\Projects\NISystem'

# Start Mosquitto
$mosquitto = 'vendor\mosquitto\mosquitto.exe'
if (Test-Path $mosquitto) {
    Start-Process -FilePath $mosquitto -ArgumentList '-c','config\mosquitto.conf' -WindowStyle Hidden
    Write-Host 'Mosquitto started'
} else {
    Write-Host 'ERROR: mosquitto not found'
    exit 1
}

Start-Sleep -Seconds 2

# Start DAQ service with credentials
$env:MQTT_USERNAME = 'backend'
$env:MQTT_PASSWORD = 'RcC5nnjfxbKRYGWJgAHBQ_PSXAhht4Qm'
Start-Process -FilePath '.\venv\Scripts\python.exe' -ArgumentList 'services\daq_service\daq_service.py','-c','config\system.ini' -WindowStyle Hidden
Write-Host 'DAQ service started'

Start-Sleep -Seconds 3

# Verify
$pyCount = (Get-Process python -ErrorAction SilentlyContinue).Count
$mqCount = (Get-Process mosquitto -ErrorAction SilentlyContinue).Count
Write-Host "Running: mosquitto=$mqCount python=$pyCount"
