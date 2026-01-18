#!/bin/bash
# CZFlux Stop Script
# Cleanly stops all services

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="/tmp/nisystem-daq.pid"
DASHBOARD_PID_FILE="/tmp/nisystem-dashboard.pid"

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }

log_info "Stopping CZFlux services..."

# Stop DAQ service via PID file
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        kill "$PID"
        log_info "Sent SIGTERM to DAQ service (PID: $PID)"
        sleep 2
    fi
    rm -f "$PID_FILE"
fi

# Stop dashboard via PID file
if [ -f "$DASHBOARD_PID_FILE" ]; then
    PID=$(cat "$DASHBOARD_PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        kill "$PID"
        log_info "Sent SIGTERM to Dashboard (PID: $PID)"
    fi
    rm -f "$DASHBOARD_PID_FILE"
fi

# Clean up any remaining processes
pkill -f "daq_service.py" 2>/dev/null || true
pkill -f "vite.*dashboard" 2>/dev/null || true

# Force kill if needed
if pgrep -f "daq_service.py" > /dev/null; then
    pkill -9 -f "daq_service.py" 2>/dev/null || true
fi

log_info "CZFlux stopped"
