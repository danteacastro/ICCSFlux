#!/bin/bash
# CZFlux Startup Script
# Ensures clean state and starts all services in correct order

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_PYTHON="$PROJECT_DIR/venv/bin/python"
DAQ_SERVICE="$PROJECT_DIR/services/daq_service/daq_service.py"
DASHBOARD_DIR="$PROJECT_DIR/dashboard"
CONFIG_FILE="$PROJECT_DIR/config/system.ini"
PID_FILE="/tmp/nisystem-daq.pid"
DASHBOARD_PID_FILE="/tmp/nisystem-dashboard.pid"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Stop any existing services
stop_services() {
    log_info "Stopping existing services..."

    # Stop DAQ service
    if [ -f "$PID_FILE" ]; then
        OLD_PID=$(cat "$PID_FILE")
        if kill -0 "$OLD_PID" 2>/dev/null; then
            kill "$OLD_PID" 2>/dev/null || true
            sleep 1
        fi
        rm -f "$PID_FILE"
    fi

    # Stop dashboard
    if [ -f "$DASHBOARD_PID_FILE" ]; then
        OLD_PID=$(cat "$DASHBOARD_PID_FILE")
        if kill -0 "$OLD_PID" 2>/dev/null; then
            kill "$OLD_PID" 2>/dev/null || true
        fi
        rm -f "$DASHBOARD_PID_FILE"
    fi

    # Kill any orphaned processes
    pkill -f "daq_service.py" 2>/dev/null || true
    pkill -f "vite.*dashboard" 2>/dev/null || true
    sleep 1

    # Force kill if still running
    if pgrep -f "daq_service.py" > /dev/null; then
        pkill -9 -f "daq_service.py" 2>/dev/null || true
        sleep 1
    fi
}

# Check prerequisites
check_prerequisites() {
    log_info "Checking prerequisites..."

    # Check Python venv
    if [ ! -f "$VENV_PYTHON" ]; then
        log_error "Python venv not found at $VENV_PYTHON"
        exit 1
    fi

    # Check config file
    if [ ! -f "$CONFIG_FILE" ]; then
        log_error "Config file not found at $CONFIG_FILE"
        exit 1
    fi

    # Check MQTT broker
    if ! pgrep -x "mosquitto" > /dev/null; then
        log_warn "Mosquitto not running, attempting to start..."
        sudo systemctl start mosquitto 2>/dev/null || mosquitto -d 2>/dev/null || {
            log_error "Failed to start Mosquitto broker"
            exit 1
        }
        sleep 1
    fi

    log_info "Prerequisites OK"
}

# Start DAQ service
start_daq_service() {
    log_info "Starting DAQ service..."

    cd "$PROJECT_DIR/services/daq_service"

    # Start in background and save PID
    nohup "$VENV_PYTHON" "$DAQ_SERVICE" -c "$CONFIG_FILE" > /tmp/nisystem-daq.log 2>&1 &
    echo $! > "$PID_FILE"

    # Wait for service to initialize
    sleep 2

    # Verify it's running
    if ! kill -0 $(cat "$PID_FILE") 2>/dev/null; then
        log_error "DAQ service failed to start. Check /tmp/nisystem-daq.log"
        cat /tmp/nisystem-daq.log | tail -20
        exit 1
    fi

    log_info "DAQ service started (PID: $(cat $PID_FILE))"
}

# Start dashboard
start_dashboard() {
    log_info "Starting dashboard..."

    cd "$DASHBOARD_DIR"

    # Start Vite dev server in background
    nohup npm run dev > /tmp/nisystem-dashboard.log 2>&1 &
    echo $! > "$DASHBOARD_PID_FILE"

    # Wait for dashboard to be ready
    for i in {1..10}; do
        if curl -s http://localhost:5173 > /dev/null 2>&1; then
            log_info "Dashboard started (PID: $(cat $DASHBOARD_PID_FILE))"
            return 0
        fi
        sleep 1
    done

    log_warn "Dashboard may still be starting..."
}

# Verify system is operational
verify_system() {
    log_info "Verifying system..."

    # Check MQTT connectivity and wait for status
    for i in {1..5}; do
        STATUS=$(timeout 2 mosquitto_sub -h localhost -t "nisystem/status/system" -C 1 2>/dev/null || echo "")
        if [ -n "$STATUS" ]; then
            log_info "System online and publishing"
            return 0
        fi
        sleep 1
    done

    log_warn "Could not verify MQTT status (service may still be initializing)"
}

# Main
main() {
    echo "========================================"
    echo "  CZFlux Startup"
    echo "========================================"

    stop_services
    check_prerequisites
    start_daq_service
    start_dashboard
    verify_system

    echo "========================================"
    log_info "CZFlux ready"
    echo "  DAQ Service PID: $(cat $PID_FILE)"
    echo "  Dashboard PID: $(cat $DASHBOARD_PID_FILE 2>/dev/null || echo 'N/A')"
    echo "  DAQ Log: /tmp/nisystem-daq.log"
    echo "  Dashboard Log: /tmp/nisystem-dashboard.log"
    echo "  Dashboard URL: http://localhost:5173"
    echo "========================================"
}

main "$@"
