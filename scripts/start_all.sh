#!/bin/bash
#
# NISystem Start All Services Script
# Starts MQTT broker and DAQ service
#

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}=============================================="
echo "NISystem - Starting All Services"
echo -e "==============================================${NC}"
echo ""

# Check if running in foreground or background mode
FOREGROUND=false
if [ "$1" == "-f" ] || [ "$1" == "--foreground" ]; then
    FOREGROUND=true
fi

# Function to check if a service is running
check_service() {
    if systemctl is-active --quiet "$1" 2>/dev/null; then
        return 0
    fi
    return 1
}

# Function to check if a port is in use
check_port() {
    if command -v ss &> /dev/null; then
        ss -tuln | grep -q ":$1 " && return 0
    elif command -v netstat &> /dev/null; then
        netstat -tuln | grep -q ":$1 " && return 0
    fi
    return 1
}

# Start Mosquitto MQTT Broker
start_mosquitto() {
    echo -e "${YELLOW}Starting Mosquitto MQTT Broker...${NC}"

    if check_port 1883; then
        echo -e "${GREEN}MQTT broker already running on port 1883${NC}"
    else
        if check_service mosquitto; then
            echo -e "${GREEN}Mosquitto service already running${NC}"
        else
            sudo systemctl start mosquitto || {
                echo -e "${YELLOW}Systemd service not available, starting manually...${NC}"
                mosquitto -d -c /etc/mosquitto/mosquitto.conf 2>/dev/null || mosquitto -d
            }
        fi

        # Wait for MQTT to be ready
        for i in {1..10}; do
            if check_port 1883; then
                echo -e "${GREEN}MQTT broker started successfully${NC}"
                break
            fi
            sleep 0.5
        done
    fi
}

# Start DAQ Service
start_daq_service() {
    echo -e "${YELLOW}Starting DAQ Service...${NC}"

    # Activate virtual environment
    if [ -d "$PROJECT_DIR/venv" ]; then
        source "$PROJECT_DIR/venv/bin/activate"
    else
        echo -e "${RED}Virtual environment not found. Run install_dependencies.sh first.${NC}"
        exit 1
    fi

    cd "$PROJECT_DIR/services/daq_service"

    if [ "$FOREGROUND" = true ]; then
        echo -e "${GREEN}Starting DAQ Service in foreground...${NC}"
        python daq_service.py -c "$PROJECT_DIR/config/system.ini"
    else
        # Check if already running
        if pgrep -f "daq_service.py" > /dev/null; then
            echo -e "${GREEN}DAQ Service already running${NC}"
        else
            nohup python daq_service.py -c "$PROJECT_DIR/config/system.ini" > "$PROJECT_DIR/logs/daq_service.log" 2>&1 &
            echo $! > "$PROJECT_DIR/logs/daq_service.pid"
            echo -e "${GREEN}DAQ Service started (PID: $!)${NC}"
        fi
    fi
}

# Create logs directory
mkdir -p "$PROJECT_DIR/logs"

# Main startup sequence
start_mosquitto
echo ""
start_daq_service

echo ""
echo -e "${BLUE}=============================================="
echo "NISystem Started"
echo -e "==============================================${NC}"
echo ""
echo "Services:"
echo "  - MQTT Broker:    localhost:1883"
echo "  - DAQ Service:    Running (simulation mode)"
echo ""
echo "Logs:"
echo "  - DAQ Service:    $PROJECT_DIR/logs/daq_service.log"
echo ""
echo "To stop all services: ./scripts/stop_all.sh"
echo ""
