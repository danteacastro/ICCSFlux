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

        # Add options for non-interactive
        ssh_cmd.extend(['-o', 'BatchMode=yes'])
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
        scp_cmd.extend(['-o', 'BatchMode=yes'])
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
        except:
            error(f"Ping failed for {node.host}")
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
        if node.node_type == 'crio':
            ok, output = self._run_ssh(node, 'pgrep -f crio_node.py')
            if ok and output.strip():
                status['service_running'] = True
                status['pid'] = output.strip().split('\n')[0]
        elif node.node_type == 'opto22':
            ok, output = self._run_ssh(node, 'pgrep -f opto22_node.py')
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

        # Verify deployment
        info("Verifying deployment...")
        ok, output = self._run_ssh(node, f'ls -la {node.deploy_path}/crio_node.py')
        if ok:
            success(f"Deployment verified: {output.strip()}")

        return True

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

        return True

    def restart_service(self, node: NodeConfig) -> bool:
        """Restart node service"""
        header(f"Restarting service on {node.name}")

        if not self.check_connectivity(node):
            return False

        script_name = 'crio_node.py' if node.node_type == 'crio' else 'opto22_node.py'
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
  %(prog)s deploy crio          Deploy code to cRIO
  %(prog)s deploy opto22        Deploy code to Opto22
  %(prog)s deploy all           Deploy to all configured nodes
  %(prog)s status crio          Check cRIO status
  %(prog)s restart crio         Restart cRIO service
  %(prog)s logs crio            View cRIO logs
  %(prog)s logs crio -f         Follow cRIO logs
  %(prog)s config               Show configuration
  %(prog)s config --setup       Run configuration setup
        """
    )

    subparsers = parser.add_subparsers(dest='command', help='Command to run')

    # Deploy command
    deploy_parser = subparsers.add_parser('deploy', help='Deploy code to node(s)')
    deploy_parser.add_argument('target', choices=['crio', 'opto22', 'all'], help='Target node(s)')
    deploy_parser.add_argument('--restart', '-r', action='store_true', help='Restart service after deploy')
    deploy_parser.add_argument('--install', '-i', action='store_true', help='Install requirements')

    # Status command
    status_parser = subparsers.add_parser('status', help='Check node status')
    status_parser.add_argument('target', choices=['crio', 'opto22', 'all'], help='Target node(s)')

    # Restart command
    restart_parser = subparsers.add_parser('restart', help='Restart node service')
    restart_parser.add_argument('target', choices=['crio', 'opto22', 'all'], help='Target node(s)')

    # Logs command
    logs_parser = subparsers.add_parser('logs', help='View node logs')
    logs_parser.add_argument('target', choices=['crio', 'opto22'], help='Target node')
    logs_parser.add_argument('-n', '--lines', type=int, default=50, help='Number of lines')
    logs_parser.add_argument('-f', '--follow', action='store_true', help='Follow log output')

    # Config command
    config_parser = subparsers.add_parser('config', help='Manage configuration')
    config_parser.add_argument('--setup', action='store_true', help='Run setup wizard')
    config_parser.add_argument('--show', action='store_true', help='Show current config')

    # Install command
    install_parser = subparsers.add_parser('install', help='Install requirements on node')
    install_parser.add_argument('target', choices=['crio', 'opto22', 'all'], help='Target node(s)')

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

    # Get target nodes
    def get_targets(target: str) -> List[NodeConfig]:
        if target == 'all':
            return list(config.nodes.values())
        elif target in config.nodes:
            return [config.nodes[target]]
        else:
            error(f"Node '{target}' not configured")
            return []

    # Execute commands
    if args.command == 'deploy':
        targets = get_targets(args.target)
        for node in targets:
            if node.node_type == 'crio':
                ok = deployer.deploy_crio(node)
            else:
                ok = deployer.deploy_opto22(node)

            if ok:
                if args.install:
                    deployer.install_requirements(node)
                if args.restart:
                    deployer.restart_service(node)

    elif args.command == 'status':
        targets = get_targets(args.target)
        for node in targets:
            header(f"Status: {node.name} ({node.host})")
            status = deployer.get_status(node)

            print(f"  Reachable:      {'Yes' if status['reachable'] else 'No'}")
            print(f"  Service Running: {'Yes' if status['service_running'] else 'No'}")
            if status['pid']:
                print(f"  PID:            {status['pid']}")
            print(f"  MQTT Connected: {'Yes' if status['mqtt_connected'] else 'Unknown'}")

    elif args.command == 'restart':
        targets = get_targets(args.target)
        for node in targets:
            deployer.restart_service(node)

    elif args.command == 'logs':
        if args.target not in config.nodes:
            error(f"Node '{args.target}' not configured")
            return
        node = config.nodes[args.target]
        deployer.view_logs(node, args.lines, args.follow)

    elif args.command == 'install':
        targets = get_targets(args.target)
        for node in targets:
            deployer.install_requirements(node)


if __name__ == '__main__':
    main()
