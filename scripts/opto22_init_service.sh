[Unit]
Description=ICCSFlux Opto22 Node — groov EPIC Python Companion
Documentation=https://github.com/iccsflux
After=network.target mosquitto.service

[Service]
Type=simple
User=dev
Group=dev
WorkingDirectory=/home/dev/nisystem
ExecStart=/usr/bin/python3 /home/dev/nisystem/run_opto22.py --log-file /home/dev/nisystem/logs/opto22_node.log
Restart=always
RestartSec=5
StartLimitIntervalSec=60
StartLimitBurst=5

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=opto22_node

# Security hardening
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/home/dev/nisystem

[Install]
WantedBy=multi-user.target
