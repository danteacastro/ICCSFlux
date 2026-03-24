#!/usr/bin/env python3
"""
Station Manager — manages multiple DAQ service instances via MQTT commands.

Shared module used by both the portable launcher (ICCSFlux_exe.py) and
the dev launcher (start_services.py). Communicates with the dashboard
via MQTT topics:
  - nisystem/station/create   (dashboard → manager)
  - nisystem/station/stop     (dashboard → manager)
  - nisystem/station/list     (dashboard → manager)
  - nisystem/station/registry (manager → dashboard, retained)
  - nisystem/station/response (manager → dashboard)
  - nisystem/nodes/+/channels/claimed (DAQ service → manager)
"""

import configparser
import json
import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, List, Optional, Tuple

try:
    import paho.mqtt.client as paho_mqtt
    HAS_PAHO = True
except ImportError:
    HAS_PAHO = False

logger = logging.getLogger("StationManager")

class StationProcess:
    """Lightweight wrapper around a DAQ service subprocess."""

    def __init__(self, proc: subprocess.Popen, node_id: str, node_name: str,
                 project: str, config_path: str):
        self.proc = proc
        self.node_id = node_id
        self.node_name = node_name
        self.project = project
        self.config_path = config_path
        self.start_time = time.time()

    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    @property
    def pid(self) -> Optional[int]:
        return self.proc.pid if self.proc else None

    def terminate(self, timeout: float = 10.0):
        if not self.proc:
            return
        try:
            self.proc.terminate()
            self.proc.wait(timeout=timeout)
        except (OSError, subprocess.TimeoutExpired):
            try:
                self.proc.kill()
                self.proc.wait(timeout=3)
            except Exception:
                pass

class StationManager:
    """Manages multiple DAQ service instances via MQTT commands.

    Args:
        root: Project root directory
        daq_command_fn: Callable that returns the DAQ service command list
                        given a config path, e.g. ["python", "daq_service.py", "-c", path]
        credential_fn: Callable returning (username, password) for MQTT
        log_fn: Optional logging function(tag, message, level). Falls back to stdlib logging.
        creation_flags: subprocess creation flags (0 for dev, _NO_WINDOW for portable)
        process_tracker: Optional list to append spawned processes to (for shutdown cleanup)
    """

    MAX_STATIONS = 3

    def __init__(
        self,
        root: Path,
        daq_command_fn: Callable[[str], List[str]],
        credential_fn: Callable[[], Tuple[Optional[str], Optional[str]]],
        log_fn: Optional[Callable] = None,
        creation_flags: int = 0,
        process_tracker: Optional[list] = None,
    ):
        self.root = root
        self._daq_command_fn = daq_command_fn
        self._credential_fn = credential_fn
        self._log = log_fn or self._default_log
        self._creation_flags = creation_flags
        self._process_tracker = process_tracker

        self.stations: dict[str, StationProcess] = {}
        self._mqtt = None
        self._running = False
        self._thread = None
        self._claimed_channels: dict[str, list] = {}

        # Paths
        self._stations_dir = root / "config" / "stations"
        self._state_file = root / "config" / "station_state.json"
        self._data_dir = root / "data"
        self._cred_file = root / "config" / "mqtt_credentials.json"

    @staticmethod
    def _default_log(tag, message, level="info"):
        log_level = {"ok": logging.INFO, "info": logging.INFO,
                     "warn": logging.WARNING, "error": logging.ERROR}.get(level, logging.INFO)
        logger.log(log_level, "[%-10s] %s", tag, message)

    def start(self):
        """Start the station manager MQTT listener in a background thread."""
        if not HAS_PAHO:
            self._log("STATION", "paho-mqtt not available — station mode disabled", "warn")
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, name="StationManager", daemon=True)
        self._thread.start()
        self._log("STATION", "Station manager started", "ok")

    def stop(self):
        """Stop all stations and disconnect MQTT."""
        self._running = False
        for node_id in list(self.stations.keys()):
            self._stop_station(node_id)
        if self._mqtt:
            try:
                self._mqtt.disconnect()
            except Exception:
                pass

    def _run(self):
        """Main MQTT listener loop."""
        mqtt_user, mqtt_pass = self._credential_fn()
        self._mqtt = paho_mqtt.Client(
            paho_mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"station-manager-{os.getpid()}"
        )
        if mqtt_user and mqtt_pass:
            self._mqtt.username_pw_set(mqtt_user, mqtt_pass)
        self._mqtt.on_connect = self._on_connect
        self._mqtt.on_message = self._on_message

        while self._running:
            try:
                self._mqtt.connect("localhost", 1883, keepalive=30)
                self._mqtt.loop_forever()
            except Exception as e:
                if self._running:
                    self._log("STATION", f"MQTT connection error: {e}", "warn")
                    time.sleep(5)

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        client.subscribe("nisystem/station/create", qos=1)
        client.subscribe("nisystem/station/stop", qos=1)
        client.subscribe("nisystem/station/list", qos=1)
        client.subscribe("nisystem/nodes/+/channels/claimed", qos=1)
        self._log("STATION", "Connected to MQTT broker", "ok")
        self._restore_stations()
        self._publish_registry()

    def _on_message(self, client, userdata, msg):
        try:
            topic = msg.topic
            payload = json.loads(msg.payload.decode()) if msg.payload else {}

            if topic == "nisystem/station/create":
                self._handle_create(payload)
            elif topic == "nisystem/station/stop":
                self._handle_stop(payload)
            elif topic == "nisystem/station/list":
                self._publish_registry()
            elif "/channels/claimed" in topic:
                parts = topic.split("/")
                if len(parts) >= 4:
                    node_id = parts[2]
                    if msg.payload:
                        self._claimed_channels[node_id] = payload.get("channels", [])
                    else:
                        self._claimed_channels.pop(node_id, None)
        except Exception as e:
            self._log("STATION", f"Error handling message: {e}", "error")

    def _handle_create(self, payload):
        """Create a new station: generate config, spawn DAQ service."""
        project = payload.get("project", "")
        node_name = payload.get("name", "")
        node_id = payload.get("node_id", "")

        if not project:
            self._respond(False, "Missing 'project' in payload")
            return

        if not node_id:
            idx = len(self.stations) + 1
            node_id = f"station-{idx:03d}"

        if not node_name:
            node_name = f"Station {len(self.stations) + 1}"

        if node_id in self.stations:
            self._respond(False, f"Station '{node_id}' already exists")
            return

        if len(self.stations) >= self.MAX_STATIONS:
            self._respond(False, f"Maximum {self.MAX_STATIONS} stations allowed")
            return

        # Resolve project path
        project_path = self.root / "config" / "projects" / project
        if not project_path.exists():
            self._respond(False, f"Project not found: {project}")
            return

        # Check channel overlap
        try:
            with open(project_path, 'r', encoding='utf-8') as f:
                project_data = json.load(f)
            new_channels = []
            for ch in project_data.get("channels", {}).values():
                phys = ch.get("physical_channel", "")
                if phys:
                    new_channels.append(phys)

            conflicts = []
            for other_id, other_channels in self._claimed_channels.items():
                overlap = set(new_channels) & set(other_channels)
                if overlap:
                    conflicts.append(f"{other_id}: {', '.join(overlap)}")
            if conflicts:
                self._respond(False, f"Channel conflicts: {'; '.join(conflicts)}")
                return
        except Exception as e:
            self._respond(False, f"Error reading project: {e}")
            return

        # Generate per-station config
        self._stations_dir.mkdir(parents=True, exist_ok=True)
        config_path = self._stations_dir / f"{node_id}.ini"
        station_data_dir = self._data_dir / "stations" / node_id
        station_data_dir.mkdir(parents=True, exist_ok=True)
        (station_data_dir / "logs").mkdir(exist_ok=True)
        (station_data_dir / "recordings").mkdir(exist_ok=True)

        cfg = configparser.ConfigParser()
        cfg["system"] = {
            "node_id": node_id,
            "node_name": node_name,
            "mqtt_broker": "localhost",
            "mqtt_port": "1883",
            "mqtt_base_topic": "nisystem",
            "scan_rate_hz": "4",
            "publish_rate_hz": "4",
            "simulation_mode": "false",
            "log_directory": str(station_data_dir / "logs"),
            "default_project": str(project_path),
            "project_mode": "CDAQ",
        }
        cfg["logging"] = {"level": "INFO"}

        with open(config_path, 'w') as f:
            cfg.write(f)

        # Spawn DAQ service process
        env = os.environ.copy()
        env["ICCSFLUX_DATA_DIR"] = str(station_data_dir)
        mqtt_user, mqtt_pass = self._credential_fn()
        if mqtt_user and mqtt_pass:
            env["MQTT_USERNAME"] = mqtt_user
            env["MQTT_PASSWORD"] = mqtt_pass

        try:
            daq_cmd = self._daq_command_fn(str(config_path))
            proc = subprocess.Popen(
                daq_cmd,
                cwd=str(self.root), env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                creationflags=self._creation_flags,
            )
            if self._process_tracker is not None:
                self._process_tracker.append(proc)

            station = StationProcess(proc, node_id, node_name, project, str(config_path))
            self.stations[node_id] = station

            self._save_state()
            self._publish_registry()

            self._log("STATION",
                      f"Created station '{node_name}' ({node_id}) — project: {project}, PID: {proc.pid}",
                      "ok")
            self._respond(True, f"Station '{node_name}' created", node_id=node_id)

        except Exception as e:
            self._log("STATION", f"Failed to start station: {e}", "error")
            self._respond(False, f"Failed to start: {e}")

    def _handle_stop(self, payload):
        """Stop a station and clean up."""
        station_id = payload.get("station_id", "")
        if not station_id:
            self._respond(False, "Missing 'station_id'")
            return
        if station_id not in self.stations:
            self._respond(False, f"Station '{station_id}' not found")
            return
        self._stop_station(station_id)
        self._respond(True, f"Station '{station_id}' stopped")

    def _stop_station(self, node_id):
        """Stop a station's DAQ service process."""
        station = self.stations.pop(node_id, None)
        if not station:
            return
        station.terminate()
        self._claimed_channels.pop(node_id, None)
        self._save_state()
        self._publish_registry()
        self._log("STATION", f"Stopped station '{node_id}'", "info")

    def _publish_registry(self):
        """Publish the current station registry as a retained MQTT message."""
        if not self._mqtt:
            return
        registry = {}
        for node_id, station in self.stations.items():
            registry[node_id] = {
                "nodeId": node_id,
                "nodeName": station.node_name,
                "project": station.project,
                "status": "running" if station.alive else "stopped",
                "pid": station.pid,
                "channels": self._claimed_channels.get(node_id, []),
            }
        payload = json.dumps({"stations": registry})
        self._mqtt.publish("nisystem/station/registry", payload, retain=True, qos=1)

    def _respond(self, success, message, **extra):
        """Publish a response to station commands."""
        if not self._mqtt:
            return
        payload = {"success": success, "message": message}
        payload.update(extra)
        payload["stations"] = {
            nid: {
                "nodeId": nid,
                "nodeName": s.node_name,
                "project": s.project,
                "status": "running" if s.alive else "stopped",
            }
            for nid, s in self.stations.items()
        }
        self._mqtt.publish("nisystem/station/response", json.dumps(payload), qos=1)

    def _save_state(self):
        """Persist active stations to disk for restart recovery."""
        state = {}
        for node_id, station in self.stations.items():
            state[node_id] = {
                "project": station.project,
                "node_name": station.node_name,
                "config_path": station.config_path,
            }
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._state_file, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            self._log("STATION", f"Failed to save state: {e}", "warn")

    def _restore_stations(self):
        """Restore stations from persisted state on startup."""
        if not self._state_file.exists():
            return
        try:
            with open(self._state_file) as f:
                state = json.load(f)
            for node_id, info in state.items():
                if not isinstance(info, dict):
                    continue
                config_path = info.get("config_path", "")
                if config_path and Path(config_path).exists():
                    self._log("STATION", f"Restoring station '{node_id}'...", "info")
                    self._handle_create({
                        "project": info.get("project", ""),
                        "name": info.get("node_name", ""),
                        "node_id": node_id,
                    })
        except Exception as e:
            self._log("STATION", f"Failed to restore state: {e}", "warn")

    def check_stations(self):
        """Check health of all station processes. Restart crashed ones."""
        for node_id, station in list(self.stations.items()):
            if not station.alive:
                self._log("STATION", f"Station '{node_id}' crashed — restarting", "warn")
                config_path = station.config_path
                if config_path and Path(config_path).exists():
                    env = os.environ.copy()
                    station_data_dir = self._data_dir / "stations" / node_id
                    env["ICCSFLUX_DATA_DIR"] = str(station_data_dir)
                    mqtt_user, mqtt_pass = self._credential_fn()
                    if mqtt_user and mqtt_pass:
                        env["MQTT_USERNAME"] = mqtt_user
                        env["MQTT_PASSWORD"] = mqtt_pass
                    try:
                        daq_cmd = self._daq_command_fn(config_path)
                        proc = subprocess.Popen(
                            daq_cmd,
                            cwd=str(self.root), env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            creationflags=self._creation_flags,
                        )
                        if self._process_tracker is not None:
                            self._process_tracker.append(proc)
                        station.proc = proc
                        station.start_time = time.time()
                        self._log("STATION",
                                  f"Restarted station '{node_id}' (PID {proc.pid})", "ok")
                    except Exception as e:
                        self._log("STATION",
                                  f"Failed to restart '{node_id}': {e}", "error")
        self._publish_registry()
