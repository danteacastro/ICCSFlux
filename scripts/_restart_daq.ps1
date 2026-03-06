Set-Location 'c:\Users\User\Documents\Projects\NISystem'
$env:MQTT_USERNAME = 'backend'
$env:MQTT_PASSWORD = 'RcC5nnjfxbKRYGWJgAHBQ_PSXAhht4Qm'
Start-Process -FilePath '.\venv\Scripts\python.exe' -ArgumentList 'services\daq_service\daq_service.py','-c','config\system.ini' -WindowStyle Hidden
Write-Host 'DAQ service started'
