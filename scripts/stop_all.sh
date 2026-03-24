#!/bin/bash
#
# NISystem Stop All Services Script
#

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}Stopping NISystem services...${NC}"
echo ""

# Stop DAQ Service
if [ -f "$PROJECT_DIR/logs/daq_service.pid" ]; then
    PID=$(cat "$PROJECT_DIR/logs/daq_service.pid")
    if kill -0 "$PID" 2>/dev/null; then
        echo "Stopping DAQ Service (PID: $PID)..."
        kill "$PID"
        rm "$PROJECT_DIR/logs/daq_service.pid"
        echo -e "${GREEN}DAQ Service stopped${NC}"
    fi
else
    # Try to find and kill by process name
    pkill -f "daq_service.py" 2>/dev/null && echo -e "${GREEN}DAQ Service stopped${NC}" || echo "DAQ Service not running"
fi

# Optionally stop Mosquitto (commented out as it may be used by other services)
# echo "Stopping Mosquitto..."
# sudo systemctl stop mosquitto

echo ""
echo -e "${GREEN}All NISystem services stopped${NC}"
