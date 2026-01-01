#!/bin/bash
# NISystem Status Script
# Shows current state of all services

PID_FILE="/tmp/nisystem-daq.pid"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "========================================"
echo "  NISystem Status"
echo "========================================"

# Check Mosquitto
if pgrep -x "mosquitto" > /dev/null; then
    echo -e "MQTT Broker:    ${GREEN}RUNNING${NC}"
else
    echo -e "MQTT Broker:    ${RED}STOPPED${NC}"
fi

# Check DAQ Service
if [ -f "$PID_FILE" ] && kill -0 $(cat "$PID_FILE") 2>/dev/null; then
    echo -e "DAQ Service:    ${GREEN}RUNNING${NC} (PID: $(cat $PID_FILE))"
else
    # Check for orphaned process
    ORPHAN_PID=$(pgrep -f "daq_service.py" | head -1)
    if [ -n "$ORPHAN_PID" ]; then
        echo -e "DAQ Service:    ${YELLOW}ORPHANED${NC} (PID: $ORPHAN_PID)"
    else
        echo -e "DAQ Service:    ${RED}STOPPED${NC}"
    fi
fi

# Check MQTT status
echo ""
echo "System Status (via MQTT):"
STATUS=$(timeout 2 mosquitto_sub -h localhost -t "nisystem/status/system" -C 1 2>/dev/null || echo "")
if [ -n "$STATUS" ]; then
    ACQUIRING=$(echo "$STATUS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('acquiring', False))" 2>/dev/null)
    SIM_MODE=$(echo "$STATUS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('simulation_mode', False))" 2>/dev/null)
    CHANNELS=$(echo "$STATUS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('channel_count', 0))" 2>/dev/null)

    echo -e "  Acquiring:    $([ "$ACQUIRING" = "True" ] && echo "${GREEN}YES${NC}" || echo "${YELLOW}NO${NC}")"
    echo -e "  Simulation:   $([ "$SIM_MODE" = "True" ] && echo "${YELLOW}YES${NC}" || echo "NO")"
    echo -e "  Channels:     $CHANNELS"
else
    echo -e "  ${RED}Unable to get status from MQTT${NC}"
fi

echo "========================================"
