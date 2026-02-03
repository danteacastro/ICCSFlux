#!/usr/bin/env python3
"""
Node Deployment Tool for NISystem

Command-line utility for deploying configurations and code to remote nodes:
- cRIO (NI CompactRIO running Linux RT)
- Opto22 (groov EPIC/RIO)

Usage:
    python node_deploy.py deploy crio          # Deploy crio_node.py to cRIO
    python node_deploy.py deploy opto22        # Deploy opto22_node.py to Opto22
    python node_deploy.py deploy all           # Deploy to all nodes
    python node_deploy.py status crio          # Check cRIO status
    python node_deploy.py restart crio         # Restart cRIO service
    python node_deploy.py logs crio            # View cRIO logs
    python node_deploy.py config               # Show/edit node configuration
"""

import argparse
import configparser
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field, asdict

# ANSI colors for terminal output
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

def colored(text: str, color: str) -> str:
    """Apply color to text if terminal supports it"""
    if sys.platform == 'win32':
        # Enable ANSI on Windows
        os.system('')
    return f"{color}{text}{Colors.ENDC}"

def success(msg: str) -> None:
    print(colored(f"[OK] {msg}", Colors.GREEN))

def error(msg: str) -> None:
    print(colored(f"[ERROR] {msg}", Colors.RED))

def warning(msg: str) -> None:
    print(colored(f"[WARN] {msg}", Colors.YELLOW))

def info(msg: str) -> None:
    print(colored(f"[INFO] {msg}", Colors.CYAN))

def header(msg: str) -> None:
    print(colored(f"\n{'='*60}", Colors.BLUE))
    print(colored(f"  {msg}", Colors.BOLD))
    print(colored(f"{'='*60}", Colors.BLUE))


@dataclass
class NodeConfig:
    """Configuration for a remote node"""
    name: str
    host: str
    user: str = 'admin'
    password: str = ''
    port: int = 22
    deploy_path: str = '/home/admin/nisystem'
    service_name: str = ''
    log_path: str = '/var/log'
    node_type: str = 'crio'  # crio or opto22
    mqtt_broker: str = ''

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'NodeConfig':
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class DeployConfig:
    """Deployment configuration"""
    nodes: Dict[str, NodeConfig] = field(default_factory=dict)
    local_crio_path: str = ''
    local_opto22_path: str = ''
    mqtt_broker: str = 'localhost'
    mqtt_port: int = 1883

    def save(self, path: Path) -> None:
        """Save configuration to JSON file"""
        data = {
            'mqtt_broker': self.mqtt_broker,
            'mqtt_port': self.mqtt_port,
            'local_crio_path': self.local_crio_path,
            'local_opto22_path': self.local_opto22_path,
            'nodes': {name: asdict(node) for name, node in self.nodes.items()}
        }
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)

    @classmethod
    def load(cls, path: Path) -> 'DeployConfig':
        """Load configuration from JSON file"""
        if not path.exists():
            return cls()

        with open(path) as f:
            data = json.load(f)

        config = cls(
            mqtt_broker=data.get('mqtt_broker', 'localhost'),
            mqtt_port=data.get('mqtt_port', 1883),
            local_crio_path=data.get('local_crio_path', ''),
            local_opto22_path=data.get('local_opto22_path', '')
        )

        for name, node_data in data.get('nodes', {}).items():
            config.nodes[name] = NodeConfig.from_dict(node_data)

        return config


class NodeDeployer:
    """Handles deployment operations to remote nodes"""

    def __init__(self, config: DeployConfig):
        self.config = config
        self.script_dir = Path(__file__).parent

    def _run_ssh(self, node: NodeConfig, command: str, timeout: int = 30) -> tuple[bool, str]:
        """Run SSH command on remote node"""
        ssh_cmd = ['ssh']

        # Allow password prompts, skip host key verification
        ssh_cmd.extend(['-o', 'StrictHostKeyChecking=no'])
        ssh_cmd.extend(['-o', f'ConnectTimeout={timeout}'])

        ssh_cmd.append(f'{node.user}@{node.host}')
        ssh_cmd.append(command)

        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            output = result.stdout + result.stderr
            return result.returncode == 0, output
        except subprocess.TimeoutExpired:
            return False, "SSH command timed out"
        except Exception as e:
            return False, str(e)

    def _run_scp(self, node: NodeConfig, local_path: Path, remote_path: str) -> tuple[bool, str]:
        """Copy file to remote node via SCP"""
        scp_cmd = ['scp']
        scp_cmd.extend(['-o', 'StrictHostKeyChecking=no'])
        scp_cmd.append(str(local_path))
        scp_cmd.append(f'{node.user}@{node.host}:{remote_path}')

        try:
            result = subprocess.run(
                scp_cmd,
                capture_output=True,
                text=True,
                timeout=60
            )
            return result.returncode == 0, result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            return False, "SCP timed out"
        except Exception as e:
            return False, str(e)

    def check_connectivity(self, node: NodeConfig) -> bool:
        """Check if node is reachable"""
        info(f"Checking connectivity to {node.name} ({node.host})...")

        # Ping first
        ping_cmd = ['ping', '-n' if sys.platform == 'win32' else '-c', '1', node.host]
        try:
            result = subprocess.run(ping_cmd, capture_output=True, timeout=5)
            if result.returncode != 0:
                error(f"Cannot ping {node.host}")
                return False
        except (subprocess.TimeoutExpired, OSError) as e:
            error(f"Ping failed for {node.host}: {e}")
            return False

        # Try SSH
        ok, output = self._run_ssh(node, 'echo "connected"', timeout=10)
        if ok and 'connected' in output:
            success(f"Connected to {node.name}")
            return True
        else:
            error(f"SSH connection failed: {output}")
            return False

    def get_status(self, node: NodeConfig) -> Dict[str, Any]:
        """Get node status"""
        status = {
            'reachable': False,
            'service_running': False,
            'pid': None,
            'uptime': None,
            'mqtt_connected': False
        }

        if not self.check_connectivity(node):
            return status

        status['reachable'] = True

        # Check if service is running
        script_names = {
            'crio': 'crio_node.py',
            'opto22': 'opto22_node.py',
            'cfp': 'cfp_node.py'
        }
        script_name = script_names.get(node.node_type, f'{node.node_type}_node.py')
        ok, output = self._run_ssh(node, f'pgrep -f {script_name}')
        if ok and output.strip():
            status['service_running'] = True
            status['pid'] = output.strip().split('\n')[0]

        # Check recent log for MQTT status
        log_file = f'{node.log_path}/{node.node_type}_node.log'
        ok, output = self._run_ssh(node, f'tail -50 {log_file} 2>/dev/null | grep -i "mqtt\\|connected"')
        if ok:
            if 'Connected to MQTT' in output or 'MQTT connected' in output.lower():
                status['mqtt_connected'] = True

        return status

    def deploy_crio(self, node: NodeConfig) -> bool:
        """Deploy cRIO node code and config"""
        header(f"Deploying to cRIO: {node.name} ({node.host})")

        if not self.check_connectivity(node):
            return False

        # Determine local paths
        crio_node_path = self.script_dir / 'crio_node' / 'crio_node.py'
        requirements_path = self.script_dir / 'crio_node' / 'requirements.txt'

        if self.config.local_crio_path:
            crio_node_path = Path(self.config.local_crio_path)

        if not crio_node_path.exists():
            error(f"crio_node.py not found at {crio_node_path}")
            return False

        # Create remote directory if needed
        info("Ensuring remote directory exists...")
        self._run_ssh(node, f'mkdir -p {node.deploy_path}')

        # Copy crio_node.py
        info(f"Copying crio_node.py ({crio_node_path.stat().st_size / 1024:.1f} KB)...")
        ok, output = self._run_scp(node, crio_node_path, f'{node.deploy_path}/crio_node.py')
        if not ok:
            error(f"Failed to copy crio_node.py: {output}")
            return False
        success("Copied crio_node.py")

        # Copy requirements.txt if exists
        if requirements_path.exists():
            info("Copying requirements.txt...")
            ok, output = self._run_scp(node, requirements_path, f'{node.deploy_path}/requirements.txt')
            if ok:
                success("Copied requirements.txt")

        # Make executable
        self._run_ssh(node, f'chmod +x {node.deploy_path}/crio_node.py')

        # Create startup script
        self._setup_autostart(node)

        # Verify deployment
        info("Verifying deployment...")
        ok, output = self._run_ssh(node, f'ls -la {node.deploy_path}/crio_node.py')
        if ok:
            success(f"Deployment verified: {output.strip()}")

        return True

    def _setup_autostart(self, node: NodeConfig) -> None:
        """Setup autostart script for the node service"""
        script_names = {
            'crio': 'crio_node.py',
            'opto22': 'opto22_node.py',
            'cfp': 'cfp_node.py'
        }
        script_name = script_names.get(node.node_type, f'{node.node_type}_node.py')
        log_file = f'{node.log_path}/{node.node_type}_node.log'
        broker_arg = f'--broker {node.mqtt_broker}' if node.mqtt_broker else f'--broker {self.config.mqtt_broker}'

        # Create startup script
        startup_script = f'''#!/bin/bash
# NISystem {node.node_type} node startup script
cd {node.deploy_path}
python3 {script_name} {broker_arg} >> {log_file} 2>&1 &
'''
        info("Creating startup script...")
        # Use echo with heredoc to create the script
        cmd = f'''cat > {node.deploy_path}/start_node.sh << 'STARTUP_EOF'
{startup_script}
STARTUP_EOF
chmod +x {node.deploy_path}/start_node.sh'''
        self._run_ssh(node, cmd)

        # Add to rc.local or crontab for autostart
        info("Configuring autostart on boot...")
        # Try rc.local first (common on NI Linux RT)
        rc_line = f'{node.deploy_path}/start_node.sh'
        self._run_ssh(node, f'grep -q "start_node.sh" /etc/rc.local 2>/dev/null || echo "{rc_line}" >> /etc/rc.local 2>/dev/null')
        # Also try crontab as fallback
        self._run_ssh(node, f'(crontab -l 2>/dev/null | grep -v start_node.sh; echo "@reboot {rc_line}") | crontab - 2>/dev/null')
        success("Autostart configured")

    def deploy_opto22(self, node: NodeConfig) -> bool:
        """Deploy Opto22 node code and config"""
        header(f"Deploying to Opto22: {node.name} ({node.host})")

        if not self.check_connectivity(node):
            return False

        # Determine local path
        opto22_node_path = self.script_dir / 'opto22_node' / 'opto22_node.py'
        requirements_path = self.script_dir / 'opto22_node' / 'requirements.txt'

        if self.config.local_opto22_path:
            opto22_node_path = Path(self.config.local_opto22_path)

        if not opto22_node_path.exists():
            error(f"opto22_node.py not found at {opto22_node_path}")
            return False

        # Create remote directory
        info("Ensuring remote directory exists...")
        self._run_ssh(node, f'mkdir -p {node.deploy_path}')

        # Copy opto22_node.py
        info(f"Copying opto22_node.py ({opto22_node_path.stat().st_size / 1024:.1f} KB)...")
        ok, output = self._run_scp(node, opto22_node_path, f'{node.deploy_path}/opto22_node.py')
        if not ok:
            error(f"Failed to copy opto22_node.py: {output}")
            return False
        success("Copied opto22_node.py")

        # Copy requirements.txt if exists
        if requirements_path.exists():
            info("Copying requirements.txt...")
            ok, output = self._run_scp(node, requirements_path, f'{node.deploy_path}/requirements.txt')
            if ok:
                success("Copied requirements.txt")

        # Make executable
        self._run_ssh(node, f'chmod +x {node.deploy_path}/opto22_node.py')

        # Create startup script
        self._setup_autostart(node)

        return True

    def deploy_cfp(self, node: NodeConfig) -> bool:
        """Deploy cFP node code and config"""
        header(f"Deploying to cFP host: {node.name} ({node.host})")

        if not self.check_connectivity(node):
            return False

        # Determine local paths
        cfp_node_path = self.script_dir / 'cfp_node' / 'cfp_node.py'
        cfp_config_path = self.script_dir / 'cfp_node' / 'cfp_config.json'
        requirements_path = self.script_dir / 'cfp_node' / 'requirements.txt'

        if not cfp_node_path.exists():
            error(f"cfp_node.py not found at {cfp_node_path}")
            return False

        # Create remote directory
        info("Ensuring remote directory exists...")
        self._run_ssh(node, f'mkdir -p {node.deploy_path}')

        # Copy cfp_node.py
        info(f"Copying cfp_node.py ({cfp_node_path.stat().st_size / 1024:.1f} KB)...")
        ok, output = self._run_scp(node, cfp_node_path, f'{node.deploy_path}/cfp_node.py')
        if not ok:
            error(f"Failed to copy cfp_node.py: {output}")
            return False
        success("Copied cfp_node.py")

        # Copy config if exists
        if cfp_config_path.exists():
            info("Copying cfp_config.json...")
            ok, output = self._run_scp(node, cfp_config_path, f'{node.deploy_path}/cfp_config.json')
            if ok:
                success("Copied cfp_config.json")

        # Copy requirements.txt if exists
        if requirements_path.exists():
            info("Copying requirements.txt...")
            ok, output = self._run_scp(node, requirements_path, f'{node.deploy_path}/requirements.txt')
            if ok:
                success("Copied requirements.txt")

        # Make executable
        self._run_ssh(node, f'chmod +x {node.deploy_path}/cfp_node.py')

        # Create startup script
        self._setup_autostart(node)

        return True

    def restart_service(self, node: NodeConfig) -> bool:
        """Restart node service"""
        header(f"Restarting service on {node.name}")

        if not self.check_connectivity(node):
            return False

        # Determine script name based on node type
        script_names = {
            'crio': 'crio_node.py',
            'opto22': 'opto22_node.py',
            'cfp': 'cfp_node.py'
        }
        script_name = script_names.get(node.node_type, f'{node.node_type}_node.py')
        log_file = f'{node.log_path}/{node.node_type}_node.log'

        # Stop existing process
        info("Stopping existing service...")
        self._run_ssh(node, f'pkill -f {script_name}')
        time.sleep(2)

        # Start new process
        info("Starting service...")
        broker_arg = f'--broker {node.mqtt_broker}' if node.mqtt_broker else f'--broker {self.config.mqtt_broker}'

        start_cmd = f'cd {node.deploy_path} && nohup python3 {script_name} {broker_arg} > {log_file} 2>&1 &'
        ok, output = self._run_ssh(node, start_cmd)

        # Wait and verify
        time.sleep(3)
        ok, output = self._run_ssh(node, f'pgrep -f {script_name}')
        if ok and output.strip():
            success(f"Service started (PID: {output.strip().split()[0]})")
            return True
        else:
            error("Service failed to start")
            return False

    def view_logs(self, node: NodeConfig, lines: int = 50, follow: bool = False) -> None:
        """View node logs"""
        log_file = f'{node.log_path}/{node.node_type}_node.log'

        if follow:
            info(f"Following logs from {node.name} (Ctrl+C to stop)...")
            cmd = f'tail -f {log_file}'
        else:
            info(f"Last {lines} lines from {node.name}:")
            cmd = f'tail -{lines} {log_file}'

        # For follow mode, we need to run interactively
        if follow:
            ssh_cmd = ['ssh', f'{node.user}@{node.host}', cmd]
            try:
                subprocess.run(ssh_cmd)
            except KeyboardInterrupt:
                print("\nStopped following logs")
        else:
            ok, output = self._run_ssh(node, cmd, timeout=10)
            if ok:
                print(output)
            else:
                error(f"Failed to read logs: {output}")

    def install_requirements(self, node: NodeConfig) -> bool:
        """Install Python requirements on node"""
        header(f"Installing requirements on {node.name}")

        if not self.check_connectivity(node):
            return False

        info("Installing Python packages...")
        ok, output = self._run_ssh(
            node,
            f'cd {node.deploy_path} && pip3 install -r requirements.txt',
            timeout=120
        )

        if ok:
            success("Requirements installed")
            print(output)
            return True
        else:
            error(f"Failed to install requirements: {output}")
            return False


def create_default_config(config_path: Path) -> DeployConfig:
    """Create default configuration interactively"""
    print("\n" + "="*60)
    print("  Node Deployment Configuration Setup")
    print("="*60 + "\n")

    config = DeployConfig()

    # MQTT broker
    broker = input("MQTT Broker IP [192.168.1.100]: ").strip() or '192.168.1.100'
    config.mqtt_broker = broker

    # cRIO configuration
    print("\n--- cRIO Configuration ---")
    add_crio = input("Add cRIO node? [Y/n]: ").strip().lower() != 'n'

    if add_crio:
        crio_host = input("cRIO IP address [192.168.1.20]: ").strip() or '192.168.1.20'
        crio_name = input("cRIO name [crio-001]: ").strip() or 'crio-001'

        config.nodes['crio'] = NodeConfig(
            name=crio_name,
            host=crio_host,
            user='admin',
            deploy_path='/home/admin/nisystem',
            log_path='/var/log',
            node_type='crio',
            mqtt_broker=broker
        )

    # Opto22 configuration
    print("\n--- Opto22 Configuration ---")
    add_opto22 = input("Add Opto22 node? [y/N]: ").strip().lower() == 'y'

    if add_opto22:
        opto22_host = input("Opto22 IP address: ").strip()
        opto22_name = input("Opto22 name [opto22-001]: ").strip() or 'opto22-001'

        if opto22_host:
            config.nodes['opto22'] = NodeConfig(
                name=opto22_name,
                host=opto22_host,
                user='admin',
                deploy_path='/home/admin/nisystem',
                log_path='/var/log',
                node_type='opto22',
                mqtt_broker=broker
            )

    # cFP configuration (runs on a Linux host that connects to cFP via Modbus)
    print("\n--- cFP (CompactFieldPoint) Configuration ---")
    print("Note: cFP node runs on a Linux host that connects to cFP via Modbus TCP")
    add_cfp = input("Add cFP node? [y/N]: ").strip().lower() == 'y'

    if add_cfp:
        cfp_host = input("cFP host IP address (Linux host running cfp_node.py): ").strip()
        cfp_name = input("cFP node name [cfp-001]: ").strip() or 'cfp-001'

        if cfp_host:
            config.nodes['cfp'] = NodeConfig(
                name=cfp_name,
                host=cfp_host,
                user='admin',
                deploy_path='/home/admin/nisystem',
                log_path='/var/log',
                node_type='cfp',
                mqtt_broker=broker
            )

    # Save configuration
    config.save(config_path)
    success(f"Configuration saved to {config_path}")

    return config


def main():
    parser = argparse.ArgumentParser(
        description='NISystem Node Deployment Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s deploy crio --host 192.168.1.20      Deploy to cRIO at specific IP
  %(prog)s deploy crio-001                      Deploy to named node from config
  %(prog)s deploy crio --host 192.168.1.20 -r   Deploy and restart
  %(prog)s deploy all                           Deploy to all configured nodes
  %(prog)s status crio-001                      Check node status
  %(prog)s restart crio --host 192.168.1.20     Restart service on specific IP
  %(prog)s logs crio-001                        View node logs
  %(prog)s logs crio --host 192.168.1.20 -f     Follow logs on specific IP
  %(prog)s config                               Show configuration
  %(prog)s config --setup                       Run configuration setup
  %(prog)s config --add crio-002 192.168.1.21   Add a node to config
        """
    )

    subparsers = parser.add_subparsers(dest='command', help='Command to run')

    # Deploy command
    deploy_parser = subparsers.add_parser('deploy', help='Deploy code to node(s)')
    deploy_parser.add_argument('target', help='Node type (crio/opto22/cfp), node name, or "all"')
    deploy_parser.add_argument('--host', '-H', help='Target IP address (overrides config)')
    deploy_parser.add_argument('--user', '-u', default='admin', help='SSH username (default: admin)')
    deploy_parser.add_argument('--restart', '-r', action='store_true', help='Restart service after deploy')
    deploy_parser.add_argument('--install', '-i', action='store_true', help='Install requirements')

    # Status command
    status_parser = subparsers.add_parser('status', help='Check node status')
    status_parser.add_argument('target', help='Node type, node name, or "all"')
    status_parser.add_argument('--host', '-H', help='Target IP address (overrides config)')

    # Restart command
    restart_parser = subparsers.add_parser('restart', help='Restart node service')
    restart_parser.add_argument('target', help='Node type, node name, or "all"')
    restart_parser.add_argument('--host', '-H', help='Target IP address (overrides config)')

    # Logs command
    logs_parser = subparsers.add_parser('logs', help='View node logs')
    logs_parser.add_argument('target', help='Node type or node name')
    logs_parser.add_argument('--host', '-H', help='Target IP address (overrides config)')
    logs_parser.add_argument('-n', '--lines', type=int, default=50, help='Number of lines')
    logs_parser.add_argument('-f', '--follow', action='store_true', help='Follow log output')

    # Config command
    config_parser = subparsers.add_parser('config', help='Manage configuration')
    config_parser.add_argument('--setup', action='store_true', help='Run setup wizard')
    config_parser.add_argument('--show', action='store_true', help='Show current config')
    config_parser.add_argument('--add', nargs=2, metavar=('NAME', 'IP'), help='Add a node: --add crio-002 192.168.1.21')
    config_parser.add_argument('--type', choices=['crio', 'opto22', 'cfp'], default='crio', help='Node type for --add')
    config_parser.add_argument('--remove', metavar='NAME', help='Remove a node by name')

    # Install command
    install_parser = subparsers.add_parser('install', help='Install requirements on node')
    install_parser.add_argument('target', help='Node type, node name, or "all"')
    install_parser.add_argument('--host', '-H', help='Target IP address (overrides config)')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # Configuration file path
    script_dir = Path(__file__).parent
    config_path = script_dir / 'node_deploy.json'

    # Handle config command
    if args.command == 'config':
        if args.setup:
            config = create_default_config(config_path)
        elif args.add:
            # Add a node: --add crio-002 192.168.1.21 --type crio
            node_name, node_ip = args.add
            node_type = args.type

            config = DeployConfig.load(config_path) if config_path.exists() else DeployConfig()

            config.nodes[node_name] = NodeConfig(
                name=node_name,
                host=node_ip,
                user='admin',
                deploy_path='/home/admin/nisystem',
                log_path='/var/log',
                node_type=node_type,
                mqtt_broker=config.mqtt_broker
            )
            config.save(config_path)
            success(f"Added node '{node_name}' ({node_type}) at {node_ip}")
        elif args.remove:
            # Remove a node by name
            config = DeployConfig.load(config_path) if config_path.exists() else DeployConfig()
            if args.remove in config.nodes:
                del config.nodes[args.remove]
                config.save(config_path)
                success(f"Removed node '{args.remove}'")
            else:
                error(f"Node '{args.remove}' not found in configuration")
        else:
            if config_path.exists():
                config = DeployConfig.load(config_path)
                print("\nCurrent Configuration:")
                print("-" * 40)
                print(f"MQTT Broker: {config.mqtt_broker}:{config.mqtt_port}")
                print(f"\nNodes:")
                for name, node in config.nodes.items():
                    print(f"  {name}:")
                    print(f"    Host: {node.host}")
                    print(f"    User: {node.user}")
                    print(f"    Deploy Path: {node.deploy_path}")
                    print(f"    Type: {node.node_type}")
                print("\nTo add more nodes:")
                print("  device config --add <name> <ip> --type <crio|opto22|cfp>")
                print("  Example: device config --add crio-002 192.168.1.21 --type crio")
            else:
                warning(f"No configuration found at {config_path}")
                print("Run: python node_deploy.py config --setup")
        return

    # Load configuration
    if not config_path.exists():
        warning("No configuration found. Running setup...")
        config = create_default_config(config_path)
    else:
        config = DeployConfig.load(config_path)

    deployer = NodeDeployer(config)

    # Determine node type from target string
    def infer_node_type(target: str) -> str:
        """Infer node type from target name or type string"""
        target_lower = target.lower()
        if target_lower.startswith('crio') or target_lower == 'crio':
            return 'crio'
        elif target_lower.startswith('opto') or target_lower == 'opto22':
            return 'opto22'
        elif target_lower.startswith('cfp') or target_lower == 'cfp':
            return 'cfp'
        return 'crio'  # default

    # Get target nodes (supports --host override, named nodes, or type-based lookup)
    def get_targets(target: str, host: Optional[str] = None, user: str = 'admin') -> List[NodeConfig]:
        # If --host is provided, create an ephemeral node config
        if host:
            node_type = infer_node_type(target)
            return [NodeConfig(
                name=f'{node_type}-{host}',
                host=host,
                user=user,
                deploy_path='/home/admin/nisystem',
                log_path='/var/log',
                node_type=node_type,
                mqtt_broker=config.mqtt_broker
            )]

        # "all" returns all configured nodes
        if target == 'all':
            if not config.nodes:
                warning("No nodes configured. Use: device config --add <name> <ip> --type <type>")
            return list(config.nodes.values())

        # Check if target is a configured node name
        if target in config.nodes:
            return [config.nodes[target]]

        # Check if target is a node type - return all nodes of that type
        node_type = infer_node_type(target)
        matching = [n for n in config.nodes.values() if n.node_type == node_type]
        if matching:
            return matching

        # Not found
        error(f"Node '{target}' not found in configuration")
        print(f"Configured nodes: {', '.join(config.nodes.keys()) if config.nodes else '(none)'}")
        print(f"\nOptions:")
        print(f"  1. Add to config: device config --add {target} <ip> --type {node_type}")
        print(f"  2. Use --host:    device deploy {target} --host <ip>")
        return []

    # Execute commands
    if args.command == 'deploy':
        host = getattr(args, 'host', None)
        user = getattr(args, 'user', 'admin')
        targets = get_targets(args.target, host, user)
        for node in targets:
            if node.node_type == 'crio':
                ok = deployer.deploy_crio(node)
            elif node.node_type == 'opto22':
                ok = deployer.deploy_opto22(node)
            elif node.node_type == 'cfp':
                ok = deployer.deploy_cfp(node)
            else:
                warning(f"Unknown node type: {node.node_type}")
                ok = False

            if ok:
                if args.install:
                    deployer.install_requirements(node)
                if args.restart:
                    deployer.restart_service(node)

    elif args.command == 'status':
        host = getattr(args, 'host', None)
        targets = get_targets(args.target, host)
        for node in targets:
            header(f"Status: {node.name} ({node.host})")
            status = deployer.get_status(node)

            print(f"  Reachable:      {'Yes' if status['reachable'] else 'No'}")
            print(f"  Service Running: {'Yes' if status['service_running'] else 'No'}")
            if status['pid']:
                print(f"  PID:            {status['pid']}")
            print(f"  MQTT Connected: {'Yes' if status['mqtt_connected'] else 'Unknown'}")

    elif args.command == 'restart':
        host = getattr(args, 'host', None)
        targets = get_targets(args.target, host)
        for node in targets:
            deployer.restart_service(node)

    elif args.command == 'logs':
        host = getattr(args, 'host', None)
        targets = get_targets(args.target, host)
        if not targets:
            return
        node = targets[0]  # Logs only work on one node at a time
        deployer.view_logs(node, args.lines, args.follow)

    elif args.command == 'install':
        host = getattr(args, 'host', None)
        targets = get_targets(args.target, host)
        for node in targets:
            deployer.install_requirements(node)


if __name__ == '__main__':
    main()
