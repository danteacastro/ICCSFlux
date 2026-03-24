#!/usr/bin/env python3
"""
Opto22 Node Runner Script

This script runs on the groov EPIC to start the Opto22 node service.
It handles configuration loading and service lifecycle.

Usage:
    python3 run_opto22.py [options]

Options:
    --config FILE    Path to configuration file (JSON)
    --broker HOST    MQTT broker hostname (default: from config or 192.168.1.1)
    --port PORT      MQTT broker port (default: 8883)
    --node-id ID     Node ID (default: opto22-001)
    --mqtt-user USER MQTT username
    --mqtt-pass PASS MQTT password
    --daemon         Run as daemon (detach from terminal)
    --log-level LVL  Logging level (DEBUG, INFO, WARNING, ERROR)
    --log-file FILE  Log file path
"""

import argparse
import json
import logging
import os
import sys
import signal
import time

# Add parent directory to path for imports
sys.path.insert(0, '/home/dev/nisystem')

from opto22_node.opto22_node import Opto22NodeService
from pathlib import Path

def setup_logging(level: str = 'INFO', log_file: str = None):
    """Configure logging with rotation to prevent disk exhaustion.

    Uses RotatingFileHandler: 5 MB per file, 3 backups = 20 MB max.
    """
    from logging.handlers import RotatingFileHandler

    log_level = getattr(logging, level.upper(), logging.INFO)
    fmt = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    handlers = [logging.StreamHandler(sys.stdout)]

    if log_file:
        rot = RotatingFileHandler(
            log_file,
            maxBytes=5 * 1024 * 1024,  # 5 MB
            backupCount=3,
        )
        rot.setFormatter(fmt)
        handlers.append(rot)

    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=handlers
    )

    return logging.getLogger('Opto22Node')

def ensure_log_directory(log_file: str) -> bool:
    """Ensure log file directory exists and is writable."""
    if not log_file:
        return True
    try:
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
        with open(log_file, 'a') as f:
            pass
        return True
    except Exception as e:
        sys.stderr.write(f"Cannot write to log file {log_file}: {e}\n")
        return False

CRED_FILE = '/home/dev/nisystem/mqtt_creds.json'
CONFIG_DIR = Path('/home/dev/nisystem')

def load_credential_file():
    """Load persistent credentials from deploy-time credential file.

    Returns dict with keys: mqtt_user, mqtt_pass, broker, node_id (all optional).
    """
    try:
        with open(CRED_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, PermissionError):
        return {}

def main():
    parser = argparse.ArgumentParser(description='Opto22 Node Service')
    parser.add_argument('--config', '-c', help='Configuration file (JSON)')
    parser.add_argument('--broker', help='MQTT broker host')
    parser.add_argument('--port', type=int, help='MQTT broker port')
    parser.add_argument('--node-id', help='Node ID')
    parser.add_argument('--mqtt-user', help='MQTT username')
    parser.add_argument('--mqtt-pass', help='MQTT password')
    parser.add_argument('--daemon', '-d', action='store_true', help='Run as daemon')
    parser.add_argument('--log-level', default='INFO', help='Logging level')
    parser.add_argument('--log-file', help='Log file path')
    args = parser.parse_args()

    # Load persistent credential file
    creds = load_credential_file()

    # Determine log file
    log_file = args.log_file
    if args.daemon and not log_file:
        log_file = '/home/dev/nisystem/logs/opto22_node.log'

    if log_file and not ensure_log_directory(log_file):
        log_file = '/home/dev/opto22_node.log'
        if not ensure_log_directory(log_file):
            sys.stderr.write("Warning: Could not create log file\n")
            log_file = None

    # Setup logging
    logger = setup_logging(args.log_level, log_file)
    logger.info("=" * 60)
    logger.info("Opto22 Node Starting")
    logger.info("=" * 60)

    # Create service with config directory
    config_dir = CONFIG_DIR
    if args.config:
        config_dir = Path(args.config).parent

    node = Opto22NodeService(config_dir=config_dir)

    # Apply credential overrides (CLI > credential file > config file)
    if node.config:
        if args.broker:
            node.config.mqtt_broker = args.broker
        elif creds.get('broker'):
            node.config.mqtt_broker = creds['broker']
        if args.port:
            node.config.mqtt_port = args.port
        elif creds.get('port'):
            node.config.mqtt_port = int(creds['port'])
        if args.node_id:
            node.config.node_id = args.node_id
        elif creds.get('node_id'):
            node.config.node_id = creds['node_id']
        if args.mqtt_user:
            node.config.mqtt_username = args.mqtt_user
        elif creds.get('mqtt_user'):
            node.config.mqtt_username = creds['mqtt_user']
        if args.mqtt_pass:
            node.config.mqtt_password = args.mqtt_pass
        elif creds.get('mqtt_pass'):
            node.config.mqtt_password = creds['mqtt_pass']
        if creds.get('tls_enabled') is not None:
            node.config.mqtt_tls_enabled = bool(creds['tls_enabled'])
        if creds.get('tls_ca_cert'):
            node.config.mqtt_tls_ca_cert = creds['tls_ca_cert']

    # Log configuration
    if node.config:
        cred_source = "CLI" if args.mqtt_user else ("credential file" if creds.get('mqtt_user') else "none")
        logger.info(f"Node ID: {node.config.node_id}")
        logger.info(f"MQTT Broker: {node.config.mqtt_broker}:{node.config.mqtt_port}")
        logger.info(f"MQTT TLS: {'enabled' if node.config.mqtt_tls_enabled else 'disabled'}")
        logger.info(f"MQTT Auth: {'yes' if node.config.mqtt_username else 'anonymous'} (source: {cred_source})")
        logger.info(f"Scan Rate: {node.config.scan_rate_hz} Hz")
        logger.info(f"Channels: {len(node.config.channels)}")
        logger.info(f"CODESYS: {'enabled' if node.config.codesys.enabled else 'disabled'}")

    # Signal handling
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, requesting shutdown...")
        node._running.clear()

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    # Run (blocks until shutdown)
    try:
        node.run()
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)

if __name__ == '__main__':
    main()
