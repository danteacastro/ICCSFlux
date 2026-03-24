Set-Location 'c:\Users\User\Documents\Projects\NISystem'
$env:MQTT_USERNAME = 'backend'
$env:MQTT_PASSWORD = 'RcC5nnjfxbKRYGWJgAHBQ_PSXAhht4Qm'

# Run directly (not Start-Process) to avoid double-spawn
& '.\venv\Scripts\python.exe' 'services\daq_service\daq_service.py' '-c' 'config\system.ini'
