#!/bin/bash
#
# NISystem Quick Test Script
# Tests the system without installing all dependencies
# Uses Python directly with minimal requirements
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
echo "NISystem Quick Test"
echo -e "==============================================${NC}"
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Python 3 is required but not installed.${NC}"
    exit 1
fi
echo -e "${GREEN}Python: $(python3 --version)${NC}"

# Check if paho-mqtt is installed
if ! python3 -c "import paho.mqtt.client" 2>/dev/null; then
    echo -e "${YELLOW}Installing paho-mqtt...${NC}"
    pip3 install --user paho-mqtt
fi

# Check if mosquitto is running
check_mqtt() {
    if command -v mosquitto_pub &> /dev/null; then
        mosquitto_pub -h localhost -t "test" -m "test" 2>/dev/null && return 0
    fi
    python3 -c "
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    s.connect(('localhost', 1883))
    s.close()
    exit(0)
except:
    exit(1)
" && return 0
    return 1
}

if ! check_mqtt; then
    echo -e "${YELLOW}MQTT broker not running. Starting mosquitto...${NC}"

    if command -v mosquitto &> /dev/null; then
        mosquitto -d 2>/dev/null || sudo systemctl start mosquitto 2>/dev/null || {
            echo -e "${RED}Could not start MQTT broker. Please install mosquitto:${NC}"
            echo "  Arch: sudo pacman -S mosquitto"
            echo "  Ubuntu/Debian: sudo apt install mosquitto"
            echo "  Fedora: sudo dnf install mosquitto"
            exit 1
        }
    else
        echo -e "${RED}Mosquitto not installed. Please install it first.${NC}"
        exit 1
    fi
    sleep 1
fi
echo -e "${GREEN}MQTT broker: Running on localhost:1883${NC}"

echo ""
echo -e "${YELLOW}Testing configuration parser...${NC}"
cd "$PROJECT_DIR/services/daq_service"
python3 config_parser.py

echo ""
echo -e "${YELLOW}Testing simulator...${NC}"
python3 simulator.py

echo ""
echo -e "${GREEN}=============================================="
echo "All tests passed!"
echo -e "==============================================${NC}"
echo ""
echo "To run the full DAQ service:"
echo "  cd $PROJECT_DIR/services/daq_service"
echo "  python3 daq_service.py"
echo ""
echo "To monitor MQTT messages (in another terminal):"
echo "  mosquitto_sub -h localhost -t 'nisystem/#' -v"
echo ""
