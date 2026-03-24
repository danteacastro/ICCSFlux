#!/bin/bash
#
# NISystem Dependency Installation Script
# Installs all required dependencies for the NISystem stack on Linux
#

set -e

echo "=============================================="
echo "NISystem Dependency Installation"
echo "=============================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if running as root for system packages
check_sudo() {
    if [ "$EUID" -ne 0 ]; then
        echo -e "${YELLOW}Note: Some installations may require sudo password${NC}"
    fi
}

# Detect package manager
detect_package_manager() {
    if command -v pacman &> /dev/null; then
        PKG_MANAGER="pacman"
        PKG_INSTALL="sudo pacman -S --noconfirm"
    elif command -v apt &> /dev/null; then
        PKG_MANAGER="apt"
        PKG_INSTALL="sudo apt install -y"
        sudo apt update
    elif command -v dnf &> /dev/null; then
        PKG_MANAGER="dnf"
        PKG_INSTALL="sudo dnf install -y"
    elif command -v yum &> /dev/null; then
        PKG_MANAGER="yum"
        PKG_INSTALL="sudo yum install -y"
    else
        echo -e "${RED}Could not detect package manager${NC}"
        exit 1
    fi
    echo -e "${GREEN}Detected package manager: $PKG_MANAGER${NC}"
}

# Install Node.js and npm
install_nodejs() {
    echo ""
    echo "----------------------------------------"
    echo "Installing Node.js and npm..."
    echo "----------------------------------------"

    if command -v node &> /dev/null; then
        NODE_VERSION=$(node --version)
        echo -e "${GREEN}Node.js already installed: $NODE_VERSION${NC}"
    else
        case $PKG_MANAGER in
            pacman)
                $PKG_INSTALL nodejs npm
                ;;
            apt)
                # Install Node.js 18.x LTS
                curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
                sudo apt install -y nodejs
                ;;
            dnf|yum)
                curl -fsSL https://rpm.nodesource.com/setup_18.x | sudo bash -
                $PKG_INSTALL nodejs
                ;;
        esac
        echo -e "${GREEN}Node.js installed: $(node --version)${NC}"
    fi
}

# Install Mosquitto MQTT Broker
install_mosquitto() {
    echo ""
    echo "----------------------------------------"
    echo "Installing Mosquitto MQTT Broker..."
    echo "----------------------------------------"

    if command -v mosquitto &> /dev/null; then
        echo -e "${GREEN}Mosquitto already installed${NC}"
    else
        case $PKG_MANAGER in
            pacman)
                $PKG_INSTALL mosquitto
                ;;
            apt)
                $PKG_INSTALL mosquitto mosquitto-clients
                ;;
            dnf|yum)
                $PKG_INSTALL mosquitto
                ;;
        esac
        echo -e "${GREEN}Mosquitto installed${NC}"
    fi

    # Enable and start mosquitto service
    echo "Enabling Mosquitto service..."
    sudo systemctl enable mosquitto
    sudo systemctl start mosquitto || true
    echo -e "${GREEN}Mosquitto service started${NC}"
}

# Install Python dependencies
install_python() {
    echo ""
    echo "----------------------------------------"
    echo "Installing Python dependencies..."
    echo "----------------------------------------"

    # Check for Python 3
    if command -v python3 &> /dev/null; then
        PYTHON_VERSION=$(python3 --version)
        echo -e "${GREEN}Python3 found: $PYTHON_VERSION${NC}"
    else
        case $PKG_MANAGER in
            pacman)
                $PKG_INSTALL python python-pip
                ;;
            apt)
                $PKG_INSTALL python3 python3-pip python3-venv
                ;;
            dnf|yum)
                $PKG_INSTALL python3 python3-pip
                ;;
        esac
    fi

    # Get script directory
    SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
    PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

    # Create virtual environment
    echo "Creating Python virtual environment..."
    python3 -m venv "$PROJECT_DIR/venv"

    # Activate and install requirements
    source "$PROJECT_DIR/venv/bin/activate"
    pip install --upgrade pip
    pip install -r "$PROJECT_DIR/services/daq_service/requirements.txt"

    echo -e "${GREEN}Python dependencies installed${NC}"
}

# Install InfluxDB (optional - for data logging)
install_influxdb() {
    echo ""
    echo "----------------------------------------"
    echo "Installing InfluxDB (optional)..."
    echo "----------------------------------------"

    if command -v influxd &> /dev/null; then
        echo -e "${GREEN}InfluxDB already installed${NC}"
    else
        case $PKG_MANAGER in
            pacman)
                $PKG_INSTALL influxdb
                ;;
            apt)
                # InfluxDB 2.x
                wget -q https://repos.influxdata.com/influxdata-archive_compat.key
                echo '393e8779c89ac8d958f81f942f9ad7fb82a25e133faddaf92e15b16e6ac9ce4c influxdata-archive_compat.key' | sha256sum -c && cat influxdata-archive_compat.key | gpg --dearmor | sudo tee /etc/apt/trusted.gpg.d/influxdata-archive_compat.gpg > /dev/null
                echo 'deb [signed-by=/etc/apt/trusted.gpg.d/influxdata-archive_compat.gpg] https://repos.influxdata.com/debian stable main' | sudo tee /etc/apt/sources.list.d/influxdata.list
                sudo apt update && sudo apt install -y influxdb2
                rm -f influxdata-archive_compat.key
                ;;
            dnf|yum)
                cat <<EOF | sudo tee /etc/yum.repos.d/influxdata.repo
[influxdata]
name = InfluxData Repository
baseurl = https://repos.influxdata.com/rhel/\$releasever/\$basearch/stable
enabled = 1
gpgcheck = 1
gpgkey = https://repos.influxdata.com/influxdata-archive_compat.key
EOF
                $PKG_INSTALL influxdb2
                ;;
        esac

        sudo systemctl enable influxdb || true
        sudo systemctl start influxdb || true
        echo -e "${GREEN}InfluxDB installed${NC}"
    fi
}

# Configure Mosquitto for local access
configure_mosquitto() {
    echo ""
    echo "----------------------------------------"
    echo "Configuring Mosquitto..."
    echo "----------------------------------------"

    # Create a simple config for local development
    MOSQUITTO_CONF="/etc/mosquitto/conf.d/nisystem.conf"

    if [ ! -f "$MOSQUITTO_CONF" ]; then
        echo "Creating Mosquitto configuration..."
        sudo tee "$MOSQUITTO_CONF" > /dev/null <<EOF
# NISystem MQTT Configuration
listener 1883
allow_anonymous true
persistence true
persistence_location /var/lib/mosquitto/

# WebSocket support for browser clients
listener 9001
protocol websockets
EOF
        sudo systemctl restart mosquitto
        echo -e "${GREEN}Mosquitto configured${NC}"
    else
        echo -e "${YELLOW}Mosquitto config already exists${NC}"
    fi
}

# Create systemd service files
create_services() {
    echo ""
    echo "----------------------------------------"
    echo "Creating systemd service files..."
    echo "----------------------------------------"

    SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
    PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

    # DAQ Service
    sudo tee /etc/systemd/system/nisystem-daq.service > /dev/null <<EOF
[Unit]
Description=NISystem DAQ Service
After=network.target mosquitto.service
Wants=mosquitto.service

[Service]
Type=simple
User=$USER
WorkingDirectory=$PROJECT_DIR
ExecStart=$PROJECT_DIR/venv/bin/python $PROJECT_DIR/services/daq_service/daq_service.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

    sudo systemctl daemon-reload
    echo -e "${GREEN}Systemd services created${NC}"
}

# Main installation
main() {
    check_sudo
    detect_package_manager

    install_nodejs
    install_mosquitto
    install_python
    configure_mosquitto
    create_services

    # Optional: InfluxDB
    read -p "Install InfluxDB for time-series data logging? (y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        install_influxdb
    fi

    echo ""
    echo "=============================================="
    echo -e "${GREEN}Installation Complete!${NC}"
    echo "=============================================="
    echo ""
    echo "To start the system:"
    echo "  1. Start MQTT:     sudo systemctl start mosquitto"
    echo "  2. Start DAQ:      sudo systemctl start nisystem-daq"
    echo ""
    echo "Or use the convenience script:"
    echo "  ./scripts/start_all.sh"
    echo ""
}

main "$@"
