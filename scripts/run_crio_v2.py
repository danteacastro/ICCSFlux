#!/usr/bin/env python3
"""
cRIO Node V2 Runner Script

This script runs on the cRIO to start the V2 node service.
It handles configuration loading and service lifecycle.

Usage:
    python3 run_crio_v2.py [options]

Options:
    --config FILE    Path to configuration file (JSON)
    --broker HOST    MQTT broker hostname (default: from config or 192.168.1.100)
    --port PORT      MQTT broker port (default: 1883)
    --node-id ID     Node ID (default: crio-001)
    --mock           Use mock hardware (for testing without NI-DAQmx)
    --daemon         Run as daemon (detach from terminal)
    --log-level LVL  Logging level (DEBUG, INFO, WARNING, ERROR)
"""

import argparse
import json
import logging
import os
import sys
import signal
import time

# Add parent directory to path for imports
sys.path.insert(0, '/home/admin/nisystem')

from crio_node_v2 import CRIONodeV2, NodeConfig, load_config, find_config_file


def setup_logging(level: str = 'INFO', log_file: str = None):
    """Configure logging."""
    log_level = getattr(logging, level.upper(), logging.INFO)

    handlers = [logging.StreamHandler(sys.stdout)]

    if log_file:
        handlers.append(logging.FileHandler(log_file))

    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=handlers
    )

    return logging.getLogger('cRIONode')


def daemonize():
    """Detach from terminal and run as daemon."""
    # First fork
    try:
        pid = os.fork()
        if pid > 0:
            # Parent exits - give child time to set up
            time.sleep(0.1)
            sys.exit(0)
    except OSError as e:
        sys.stderr.write(f"Fork #1 failed: {e}\n")
        sys.exit(1)

    # Decouple from parent - stay in working directory (don't chdir to /)
    # This ensures relative paths and imports still work
    os.setsid()
    os.umask(0o022)

    # Second fork
    try:
        pid = os.fork()
        if pid > 0:
            sys.exit(0)
    except OSError as e:
        sys.stderr.write(f"Fork #2 failed: {e}\n")
        sys.exit(1)

    # Redirect standard file descriptors
    sys.stdout.flush()
    sys.stderr.flush()

    with open('/dev/null', 'r') as devnull:
        os.dup2(devnull.fileno(), sys.stdin.fileno())

    # Redirect stdout/stderr to log file
    log_file = '/var/log/crio_node_v2.log'
    try:
        with open(log_file, 'a+') as f:
            os.dup2(f.fileno(), sys.stdout.fileno())
            os.dup2(f.fileno(), sys.stderr.fileno())
    except Exception:
        # Fall back to home directory if /var/log isn't writable
        log_file = '/home/admin/crio_node_v2.log'
        with open(log_file, 'a+') as f:
            os.dup2(f.fileno(), sys.stdout.fileno())
            os.dup2(f.fileno(), sys.stderr.fileno())

    # Write PID file
    pid_file = '/var/run/crio_node_v2.pid'
    try:
        with open(pid_file, 'w') as f:
            f.write(str(os.getpid()))
    except Exception:
        # PID file not critical, continue anyway
        pass


def ensure_log_directory(log_file: str) -> bool:
    """Ensure log file directory exists and is writable."""
    if not log_file:
        return True
    try:
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
        # Test write access
        with open(log_file, 'a') as f:
            pass
        return True
    except Exception as e:
        sys.stderr.write(f"Cannot write to log file {log_file}: {e}\n")
        return False


def main():
    parser = argparse.ArgumentParser(description='cRIO Node V2 Service')
    parser.add_argument('--config', '-c', help='Configuration file (JSON)')
    parser.add_argument('--broker', help='MQTT broker host')
    parser.add_argument('--port', type=int, help='MQTT broker port')
    parser.add_argument('--node-id', help='Node ID')
    parser.add_argument('--mock', action='store_true', help='Use mock hardware')
    parser.add_argument('--daemon', '-d', action='store_true', help='Run as daemon')
    parser.add_argument('--log-level', default='INFO', help='Logging level')
    parser.add_argument('--log-file', help='Log file path')
    args = parser.parse_args()

    # Determine log file early
    log_file = args.log_file
    if args.daemon and not log_file:
        log_file = '/var/log/crio_node_v2.log'

    # Ensure log directory exists before daemonizing
    if log_file and not ensure_log_directory(log_file):
        # Fall back to home directory
        log_file = '/home/admin/crio_node_v2.log'
        if not ensure_log_directory(log_file):
            sys.stderr.write("Warning: Could not create log file, logging to stderr only\n")
            log_file = None

    # Daemonize if requested
    if args.daemon:
        daemonize()
        args.log_file = log_file

    # Setup logging
    logger = setup_logging(args.log_level, log_file or args.log_file)
    logger.info("=" * 60)
    logger.info("cRIO Node V2 Starting")
    logger.info("=" * 60)

    # Load configuration
    config_file = args.config or find_config_file()
    if config_file:
        logger.info(f"Loading config from: {config_file}")
        config = load_config(config_file)
    else:
        logger.info("No config file found, using defaults")
        config = NodeConfig()

    # Apply command-line overrides
    if args.broker:
        config.mqtt_broker = args.broker
    if args.port:
        config.mqtt_port = args.port
    if args.node_id:
        config.node_id = args.node_id
    if args.mock:
        config.use_mock_hardware = True

    # Log configuration
    logger.info(f"Node ID: {config.node_id}")
    logger.info(f"MQTT Broker: {config.mqtt_broker}:{config.mqtt_port}")
    logger.info(f"Scan Rate: {config.scan_rate_hz} Hz")
    logger.info(f"Publish Rate: {config.publish_rate_hz} Hz")
    logger.info(f"Channels: {len(config.channels)}")
    logger.info(f"Mock Hardware: {config.use_mock_hardware}")

    # Create and run service
    node = CRIONodeV2(config)

    # Handle signals
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        node.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    # Run
    try:
        node.run()
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
