#!/bin/bash
# =============================================================================
# cRIO Deployment Script
# =============================================================================
# Deploys the cRIO Service to an NI cRIO-905x Linux RT system
#
# Usage:
#   ./scripts/deploy_crio.sh <crio-ip> [username]
#
# Examples:
#   ./scripts/deploy_crio.sh 192.168.1.50
#   ./scripts/deploy_crio.sh 192.168.1.50 admin
#
# Prerequisites:
#   - SSH access to the cRIO
#   - Python 3 installed on cRIO (opkg install python3 python3-pip)
#   - paho-mqtt installed (pip3 install paho-mqtt)
# =============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
CRIO_IP="${1:-}"
CRIO_USER="${2:-admin}"
CRIO_DEPLOY_DIR="/home/${CRIO_USER}/nisystem"
LOCAL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Files to deploy
SERVICE_FILES=(
    "services/crio_service/crio_service.py"
    "services/crio_service/__init__.py"
    "services/crio_service/crio_service.service"
)

CONFIG_FILES=(
    "config/crio_service.ini"
)

# =============================================================================
# Functions
# =============================================================================

print_header() {
    echo -e "${GREEN}=============================================${NC}"
    echo -e "${GREEN}  cRIO Service Deployment${NC}"
    echo -e "${GREEN}=============================================${NC}"
}

print_step() {
    echo -e "${YELLOW}>> $1${NC}"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

check_ssh() {
    print_step "Checking SSH connection to ${CRIO_IP}..."
    if ssh -o ConnectTimeout=5 -o BatchMode=yes "${CRIO_USER}@${CRIO_IP}" "echo ok" > /dev/null 2>&1; then
        print_success "SSH connection successful"
        return 0
    else
        print_error "Cannot connect to ${CRIO_USER}@${CRIO_IP}"
        echo "Make sure:"
        echo "  1. The cRIO is powered on and connected to the network"
        echo "  2. SSH is enabled on the cRIO"
        echo "  3. Your SSH key is authorized (or use ssh-copy-id)"
        return 1
    fi
}

check_python() {
    print_step "Checking Python on cRIO..."
    if ssh "${CRIO_USER}@${CRIO_IP}" "python3 --version" > /dev/null 2>&1; then
        PYTHON_VERSION=$(ssh "${CRIO_USER}@${CRIO_IP}" "python3 --version")
        print_success "Python found: ${PYTHON_VERSION}"
        return 0
    else
        print_error "Python 3 not found on cRIO"
        echo "Install with: opkg update && opkg install python3 python3-pip"
        return 1
    fi
}

check_dependencies() {
    print_step "Checking Python dependencies..."

    # Check paho-mqtt
    if ssh "${CRIO_USER}@${CRIO_IP}" "python3 -c 'import paho.mqtt.client'" > /dev/null 2>&1; then
        print_success "paho-mqtt found"
    else
        print_step "Installing paho-mqtt..."
        ssh "${CRIO_USER}@${CRIO_IP}" "pip3 install paho-mqtt"
        print_success "paho-mqtt installed"
    fi

    # Check if nidaqmx is available (optional - will run in simulation if not)
    if ssh "${CRIO_USER}@${CRIO_IP}" "python3 -c 'import nidaqmx'" > /dev/null 2>&1; then
        print_success "nidaqmx found"
    else
        echo -e "${YELLOW}  Note: nidaqmx not found - service will run in simulation mode${NC}"
        echo -e "${YELLOW}  Install with: pip3 install nidaqmx${NC}"
    fi
}

create_directories() {
    print_step "Creating directories on cRIO..."
    ssh "${CRIO_USER}@${CRIO_IP}" "mkdir -p ${CRIO_DEPLOY_DIR}/services/crio_service ${CRIO_DEPLOY_DIR}/config /var/log/crio_service"
    print_success "Directories created"
}

deploy_files() {
    print_step "Deploying service files..."

    for file in "${SERVICE_FILES[@]}"; do
        if [ -f "${LOCAL_DIR}/${file}" ]; then
            scp "${LOCAL_DIR}/${file}" "${CRIO_USER}@${CRIO_IP}:${CRIO_DEPLOY_DIR}/${file}"
            print_success "Deployed ${file}"
        else
            print_error "File not found: ${file}"
        fi
    done

    print_step "Deploying configuration files..."
    for file in "${CONFIG_FILES[@]}"; do
        if [ -f "${LOCAL_DIR}/${file}" ]; then
            scp "${LOCAL_DIR}/${file}" "${CRIO_USER}@${CRIO_IP}:${CRIO_DEPLOY_DIR}/${file}"
            print_success "Deployed ${file}"
        else
            print_error "File not found: ${file}"
        fi
    done
}

update_config() {
    print_step "Updating configuration for cRIO..."

    # Update MQTT broker IP to point to the main system
    # Get local IP that can reach the cRIO
    LOCAL_IP=$(ip route get "${CRIO_IP}" | awk '{print $5; exit}')

    if [ -n "${LOCAL_IP}" ]; then
        echo "Setting MQTT broker to ${LOCAL_IP} (this machine)"
        ssh "${CRIO_USER}@${CRIO_IP}" "sed -i 's/mqtt_broker = .*/mqtt_broker = ${LOCAL_IP}/' ${CRIO_DEPLOY_DIR}/config/crio_service.ini"
        print_success "Configuration updated"
    fi
}

install_service() {
    print_step "Installing systemd service..."

    # Copy service file to systemd directory
    ssh "${CRIO_USER}@${CRIO_IP}" "sudo cp ${CRIO_DEPLOY_DIR}/services/crio_service/crio_service.service /etc/systemd/system/"

    # Reload systemd
    ssh "${CRIO_USER}@${CRIO_IP}" "sudo systemctl daemon-reload"

    # Enable service to start on boot
    ssh "${CRIO_USER}@${CRIO_IP}" "sudo systemctl enable crio_service"

    print_success "Service installed and enabled"
}

start_service() {
    print_step "Starting cRIO service..."
    ssh "${CRIO_USER}@${CRIO_IP}" "sudo systemctl start crio_service"

    # Wait a moment and check status
    sleep 2

    if ssh "${CRIO_USER}@${CRIO_IP}" "systemctl is-active crio_service" | grep -q "active"; then
        print_success "Service started successfully"
    else
        print_error "Service failed to start"
        echo "Check logs with: ssh ${CRIO_USER}@${CRIO_IP} 'journalctl -u crio_service -n 50'"
        return 1
    fi
}

show_status() {
    echo ""
    echo -e "${GREEN}=============================================${NC}"
    echo -e "${GREEN}  Deployment Complete!${NC}"
    echo -e "${GREEN}=============================================${NC}"
    echo ""
    echo "Service Status:"
    ssh "${CRIO_USER}@${CRIO_IP}" "systemctl status crio_service --no-pager" || true
    echo ""
    echo "Useful commands:"
    echo "  View logs:     ssh ${CRIO_USER}@${CRIO_IP} 'journalctl -u crio_service -f'"
    echo "  Restart:       ssh ${CRIO_USER}@${CRIO_IP} 'sudo systemctl restart crio_service'"
    echo "  Stop:          ssh ${CRIO_USER}@${CRIO_IP} 'sudo systemctl stop crio_service'"
    echo "  Edit config:   ssh ${CRIO_USER}@${CRIO_IP} 'nano ${CRIO_DEPLOY_DIR}/config/crio_service.ini'"
    echo ""
    echo "MQTT Topics (on your main system):"
    echo "  Status:        mosquitto_sub -t 'nisystem/crio/status' -v"
    echo "  Heartbeat:     mosquitto_sub -t 'nisystem/crio/heartbeat' -v"
    echo "  Events:        mosquitto_sub -t 'nisystem/crio/events/#' -v"
    echo "  Set output:    mosquitto_pub -t 'nisystem/crio/do/set' -m '{\"heater_enable\": true}'"
}

# =============================================================================
# Main
# =============================================================================

main() {
    print_header

    # Check arguments
    if [ -z "${CRIO_IP}" ]; then
        echo "Usage: $0 <crio-ip> [username]"
        echo ""
        echo "Examples:"
        echo "  $0 192.168.1.50"
        echo "  $0 192.168.1.50 admin"
        exit 1
    fi

    echo "Deploying to: ${CRIO_USER}@${CRIO_IP}"
    echo ""

    # Run deployment steps
    check_ssh
    check_python
    check_dependencies
    create_directories
    deploy_files
    update_config
    install_service
    start_service
    show_status
}

main "$@"
