#!/usr/bin/env python3
"""Process supervisor for NISystem services.

Replaces start.bat's "fire and forget" approach with monitored processes
that are automatically restarted on failure with exponential backoff.

Usage:
    python scripts/supervisor.py                    # Start all services
    python scripts/supervisor.py --no-frontend      # Skip Vite dev server
    python scripts/supervisor.py --service daq      # Start only DAQ service

Services managed:
    - mosquitto (MQTT broker)
    - daq_service (main DAQ backend)
    - watchdog (safety watchdog)
    - frontend (Vite dev server, optional)
"""

import argparse
import json
import logging
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [SUPERVISOR] %(levelname)s %(message)s'
)
logger = logging.getLogger('Supervisor')


@dataclass
class ServiceConfig:
    """Configuration for a supervised service."""
    name: str
    command: List[str]
    working_dir: str
    env: Optional[Dict[str, str]] = None
    max_restarts: int = 10
    restart_delay_base: float = 2.0
    restart_delay_max: float = 60.0
    critical: bool = False
    enabled: bool = True


@dataclass
class ServiceState:
    """Runtime state for a supervised service."""
    config: ServiceConfig
    process: Optional[subprocess.Popen] = None
    restart_count: int = 0
    last_start_time: float = 0.0
    last_crash_time: float = 0.0
    status: str = "stopped"


class Supervisor:
    """Process supervisor with automatic restart and exponential backoff."""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.services: Dict[str, ServiceState] = {}
        self._shutdown = False

    def add_service(self, config: ServiceConfig):
        """Register a service to be supervised."""
        self.services[config.name] = ServiceState(config=config)

    def start_all(self):
        """Start all enabled services in registration order."""
        for name, state in self.services.items():
            if state.config.enabled:
                self._start_service(state)
                time.sleep(1.0)  # Stagger startup

    def _start_service(self, state: ServiceState) -> bool:
        """Start a single service. Returns True on success."""
        config = state.config
        logger.info(f"[{config.name}] Starting: {' '.join(config.command)}")

        env = os.environ.copy()
        if config.env:
            env.update(config.env)

        try:
            log_dir = self.project_root / "logs"
            log_dir.mkdir(exist_ok=True)
            stdout_log = open(log_dir / f"{config.name}.log", "a")

            state.process = subprocess.Popen(
                config.command,
                cwd=config.working_dir,
                env=env,
                stdout=stdout_log,
                stderr=subprocess.STDOUT,
                creationflags=(
                    subprocess.CREATE_NEW_PROCESS_GROUP
                    if sys.platform == "win32" else 0
                ),
            )
            state.status = "running"
            state.last_start_time = time.time()
            logger.info(f"[{config.name}] Started (PID {state.process.pid})")
            return True
        except Exception as e:
            logger.error(f"[{config.name}] Failed to start: {e}")
            state.status = "failed"
            return False

    def monitor_loop(self):
        """Main loop: check service health and restart as needed."""
        logger.info("Supervisor monitoring started")
        while not self._shutdown:
            for name, state in self.services.items():
                if state.status == "running" and state.process:
                    retcode = state.process.poll()
                    if retcode is not None:
                        logger.error(f"[{name}] Exited with code {retcode}")
                        state.last_crash_time = time.time()
                        self._handle_restart(state)
            time.sleep(2.0)

    def _handle_restart(self, state: ServiceState):
        """Handle service restart with exponential backoff."""
        config = state.config

        if state.restart_count >= config.max_restarts:
            logger.critical(
                f"[{config.name}] Max restarts ({config.max_restarts}) "
                f"exceeded — giving up"
            )
            state.status = "failed"
            if config.critical:
                logger.critical(
                    f"[{config.name}] Critical service failed — "
                    f"initiating shutdown"
                )
                self.stop_all()
            return

        # Reset restart count if service ran for > 5 minutes
        if (state.last_start_time and
                state.last_crash_time - state.last_start_time > 300):
            state.restart_count = 0

        delay = min(
            config.restart_delay_base * (2 ** state.restart_count),
            config.restart_delay_max
        )
        state.restart_count += 1

        logger.info(
            f"[{config.name}] Restarting in {delay:.1f}s "
            f"(attempt {state.restart_count}/{config.max_restarts})"
        )
        time.sleep(delay)

        if not self._shutdown:
            state.status = "restarting"
            self._start_service(state)

    def stop_all(self):
        """Stop all services gracefully."""
        self._shutdown = True
        logger.info("Stopping all services...")

        for name, state in reversed(list(self.services.items())):
            if state.process and state.process.poll() is None:
                logger.info(f"[{name}] Stopping (PID {state.process.pid})...")
                try:
                    if sys.platform == "win32":
                        state.process.terminate()
                    else:
                        state.process.send_signal(signal.SIGTERM)
                    state.process.wait(timeout=10)
                    logger.info(f"[{name}] Stopped")
                except subprocess.TimeoutExpired:
                    logger.warning(f"[{name}] Force killing...")
                    state.process.kill()
                except Exception as e:
                    logger.error(f"[{name}] Error stopping: {e}")
                state.status = "stopped"

    def status_summary(self) -> str:
        """Get human-readable status of all services."""
        lines = ["Service Status:"]
        for name, state in self.services.items():
            pid = (state.process.pid
                   if state.process and state.process.poll() is None
                   else "-")
            lines.append(
                f"  {name:20s} {state.status:12s} "
                f"PID={pid}  restarts={state.restart_count}"
            )
        return "\n".join(lines)


def load_mqtt_credentials(project_root: Path) -> Dict[str, str]:
    """Load MQTT credentials from config file."""
    cred_file = project_root / "config" / "mqtt_credentials.json"
    if cred_file.exists():
        with open(cred_file) as f:
            creds = json.load(f)
            return {
                "MQTT_USERNAME": creds.get("username", ""),
                "MQTT_PASSWORD": creds.get("password", ""),
            }
    return {}


def build_service_configs(
    project_root: Path,
    include_frontend: bool = True,
) -> List[ServiceConfig]:
    """Build service configurations for NISystem."""
    root = str(project_root)
    python = sys.executable
    mqtt_env = load_mqtt_credentials(project_root)

    configs = [
        ServiceConfig(
            name="mosquitto",
            command=[
                "mosquitto", "-c",
                str(project_root / "config" / "mosquitto.conf"), "-v",
            ],
            working_dir=root,
            critical=True,
            max_restarts=5,
        ),
        ServiceConfig(
            name="daq_service",
            command=[python, "-m", "services.daq_service.daq_service"],
            working_dir=root,
            env=mqtt_env,
            critical=True,
        ),
        ServiceConfig(
            name="watchdog",
            command=[python, "-m", "services.daq_service.watchdog"],
            working_dir=root,
            env=mqtt_env,
        ),
    ]

    if include_frontend:
        configs.append(ServiceConfig(
            name="frontend",
            command=["npm", "run", "dev"],
            working_dir=str(project_root / "dashboard"),
            critical=False,
            max_restarts=3,
        ))

    return configs


def main():
    parser = argparse.ArgumentParser(
        description="NISystem Process Supervisor"
    )
    parser.add_argument(
        "--no-frontend", action="store_true",
        help="Skip starting the Vite dev server",
    )
    parser.add_argument(
        "--service", type=str, default=None,
        help="Start only a specific service",
    )
    args = parser.parse_args()

    # Determine project root
    project_root = Path(__file__).resolve().parent.parent

    logger.info(f"NISystem Supervisor starting (root: {project_root})")

    supervisor = Supervisor(project_root)

    # Register services
    include_frontend = not args.no_frontend
    for config in build_service_configs(project_root, include_frontend):
        if args.service and config.name != args.service:
            config.enabled = False
        supervisor.add_service(config)

    # Handle graceful shutdown
    def signal_handler(sig, frame):
        logger.info(f"Received signal {sig} — shutting down")
        supervisor.stop_all()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    if sys.platform == "win32":
        signal.signal(signal.SIGBREAK, signal_handler)

    # Start and monitor
    supervisor.start_all()
    logger.info(supervisor.status_summary())

    try:
        supervisor.monitor_loop()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt — shutting down")
    finally:
        supervisor.stop_all()
        logger.info("Supervisor stopped")


if __name__ == "__main__":
    main()
