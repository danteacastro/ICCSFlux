"""
GC Node — Gas Chromatograph VM Bridge Service

Runs inside a Hyper-V VM alongside legacy GC vendor software.
Bridges GC data to NISystem MQTT broker via:
- File watching (CSV/TXT results)
- Modbus TCP/RTU registers
- Serial COM port data

Read-only node: no hardware outputs, no scripts, no PID, no sessions.
"""

import json
import logging
import os
import queue
import signal
import socket
import sys
import threading
import time
from datetime import datetime
from typing import Any, Dict, Optional

from .config import NodeConfig, AnalysisSourceConfig, SchedulerConfig, load_config, save_config
from .state_machine import State, StateTransition
from .mqtt_interface import MQTTInterface, MQTTConfig
from .audit_trail import AuditTrail
from .file_watcher import FileWatcher
from .modbus_source import ModbusSource
from .serial_source import SerialSource

try:
    from .gc_analysis import GCAnalysisEngine, AnalysisMethod, PeakLibrary
    ANALYSIS_AVAILABLE = True
except ImportError:
    ANALYSIS_AVAILABLE = False
    AnalysisMethod = None
    PeakLibrary = None

try:
    from .gc_qc import SystemSuitabilityTest, SSTCriteria, QCTracker, QCLimits, MethodValidation
    QC_AVAILABLE = True
except ImportError:
    QC_AVAILABLE = False

try:
    from .gc_scheduler import GCScheduler
    SCHEDULER_AVAILABLE = True
except ImportError:
    SCHEDULER_AVAILABLE = False

logger = logging.getLogger('GCNode')

__version__ = '1.0.0'

class GCNodeService:
    """Main GC node service."""

    def __init__(self, config: NodeConfig):
        self.config = config
        self.state = StateTransition()

        # Command queue for MQTT messages (non-blocking dispatch)
        self._command_queue = queue.Queue(maxsize=100)

        # Channel values (last known)
        self._channel_values: Dict[str, Dict[str, Any]] = {}
        self._values_lock = threading.Lock()

        # Analysis tracking
        self._analysis_count = 0
        self._last_analysis_time = 0.0

        # GC run lifecycle (streaming mode)
        self._run_active = False
        self._run_number = 0
        self._run_start_time = 0.0
        self._last_progress_time = 0.0
        self._last_inject_time = 0.0  # For debounce
        self._last_auto_run_time = 0.0  # For timer-based auto-run
        self._last_voltage = 0.0  # For threshold inject detection
        self._chromatogram_times: list = []
        self._chromatogram_values: list = []

        # Timing
        self._last_publish_time = 0.0
        self._last_heartbeat_time = 0.0
        self._last_status_time = 0.0

        # Shutdown
        self._shutdown = threading.Event()

        # MQTT
        mqtt_config = MQTTConfig(
            broker_host=config.mqtt_broker,
            broker_port=config.mqtt_port,
            username=config.mqtt_username,
            password=config.mqtt_password,
            client_id=config.node_id,
            base_topic=config.mqtt_base_topic,
            node_id=config.node_id,
            tls_enabled=config.mqtt_tls_enabled,
            tls_ca_cert=config.mqtt_tls_ca_cert,
        )
        self._mqtt = MQTTInterface(mqtt_config)
        self._mqtt.on_message = self._on_mqtt_message
        self._mqtt.on_connection_change = self._on_connection_change

        # Audit trail
        audit_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'audit')
        self._audit = AuditTrail(audit_dir=audit_dir, node_id=config.node_id)

        # Data sources (created on start)
        self._file_watcher: Optional[FileWatcher] = None
        self._modbus_source: Optional[ModbusSource] = None
        self._serial_source: Optional[SerialSource] = None

        # Analysis engine + peak library
        self._analysis_engine: Optional[object] = None
        self._peak_library: Optional[object] = None
        self._analysis_method: Optional[object] = None
        if ANALYSIS_AVAILABLE:
            self._load_peak_library()
            self._init_analysis_engine()

        # QC tracking (SST + QC samples + method validation)
        self._sst: Optional[object] = None
        self._qc_tracker: Optional[object] = None
        self._method_validation: Optional[object] = None
        if QC_AVAILABLE:
            self._sst = SystemSuitabilityTest(SSTCriteria())
            self._qc_tracker = QCTracker(QCLimits())
            logger.info("QC tracking initialized (SST + QC samples)")

        # Run scheduler (Phase 5)
        self._scheduler: Optional[object] = None
        if SCHEDULER_AVAILABLE and hasattr(config, 'scheduler') and config.scheduler.enabled:
            self._scheduler = GCScheduler(config.scheduler)
            logger.info("Run scheduler initialized")

    def _load_peak_library(self):
        """Load peak identification library from libraries/ directory."""
        lib_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'libraries')
        lib_file = os.path.join(lib_dir, 'process_gas.json')

        if not os.path.exists(lib_file):
            logger.debug(f"No peak library at {lib_file}")
            return

        try:
            self._peak_library = PeakLibrary()
            self._peak_library.load_json(lib_file)
            logger.info(f"Loaded peak library: {self._peak_library.size} compounds from {lib_file}")
        except Exception as e:
            logger.warning(f"Failed to load peak library: {e}")
            self._peak_library = None

    def _init_analysis_engine(self):
        """Initialize GCAnalysisEngine if analysis source is enabled."""
        if not ANALYSIS_AVAILABLE or not self.config.analysis_source.enabled:
            return

        try:
            # Load method from file if configured
            method = AnalysisMethod()
            method_file = self.config.analysis_source.method_file
            if method_file and os.path.exists(method_file):
                with open(method_file, 'r') as f:
                    method_data = json.load(f)
                method = AnalysisMethod.from_dict(method_data)
                logger.info(f"Loaded analysis method from {method_file}")

            self._analysis_method = method
            self._analysis_engine = GCAnalysisEngine(
                method=method,
                library=self._peak_library,
            )
            logger.info("GC analysis engine initialized")

            # Load library from config path if specified
            lib_file = self.config.analysis_source.library_file
            if lib_file and os.path.exists(lib_file) and self._peak_library is None:
                self._peak_library = PeakLibrary()
                self._peak_library.load_json(lib_file)
                self._analysis_engine._library = self._peak_library
                logger.info(f"Loaded peak library from {lib_file}")

        except Exception as e:
            logger.error(f"Failed to initialize analysis engine: {e}")
            self._analysis_engine = None

    def start(self) -> bool:
        """Start the GC node service."""
        logger.info(f"GC Node {self.config.node_id} v{__version__} starting...")
        logger.info(f"  Node name: {self.config.node_name}")
        logger.info(f"  GC type: {self.config.gc_type or '(not specified)'}")
        logger.info(f"  MQTT broker: {self.config.mqtt_broker}:{self.config.mqtt_port}")

        # Connect to MQTT
        if not self._mqtt.connect():
            logger.error("Failed to initiate MQTT connection")
            return False

        # Set up subscriptions
        self._mqtt.setup_standard_subscriptions()

        # Wait for MQTT connection
        if not self._mqtt.wait_for_connection(timeout=15.0):
            logger.warning("MQTT connection timeout — will retry in background")

        # Start data sources
        self._start_data_sources()

        # Transition to ACQUIRING
        self.state.to(State.ACQUIRING)

        self._audit.log_event('service_start', details={
            'version': __version__,
            'node_id': self.config.node_id,
            'gc_type': self.config.gc_type,
        })

        logger.info(f"GC Node {self.config.node_id} started successfully")
        return True

    def stop(self):
        """Stop the GC node service."""
        logger.info(f"GC Node {self.config.node_id} stopping...")
        self._shutdown.set()

        # Finish any active run
        if self._run_active:
            self._finish_run(reason='service_stop')

        # Stop data sources
        self._stop_data_sources()

        # Transition to IDLE
        self.state.to(State.IDLE)

        # Disconnect MQTT
        self._mqtt.disconnect()

        self._audit.log_event('service_stop')
        logger.info(f"GC Node {self.config.node_id} stopped")

    def run(self):
        """Main blocking loop."""
        if not self.start():
            logger.error("Failed to start GC Node service")
            return

        try:
            while not self._shutdown.is_set():
                loop_start = time.time()

                # 1. Process pending MQTT commands
                self._process_commands()

                # 2. Publish values at configured rate
                now = time.time()
                publish_interval = 1.0 / max(0.01, self.config.publish_rate_hz)
                if now - self._last_publish_time >= publish_interval:
                    self._publish_values()
                    self._last_publish_time = now

                # 3. Publish heartbeat
                if now - self._last_heartbeat_time >= self.config.heartbeat_interval_s:
                    self._publish_heartbeat()
                    self._last_heartbeat_time = now

                # 4. GC analysis run checks
                if self.config.analysis_source.enabled and ANALYSIS_AVAILABLE:
                    self._check_run_timeout()
                    self._check_run_progress()
                    self._check_auto_run_timer()

                # 5. Publish full status every 30s
                if now - self._last_status_time >= 30.0:
                    self._publish_status()
                    self._last_status_time = now

                # 6. Sleep remainder of loop cycle (target ~1s for GC data)
                elapsed = time.time() - loop_start
                sleep_time = max(0.1, 1.0 - elapsed)
                self._shutdown.wait(timeout=sleep_time)

        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received")
        finally:
            self.stop()

    # ------------------------------------------------------------------
    # Data source management
    # ------------------------------------------------------------------

    def _start_data_sources(self):
        """Start enabled data sources."""
        # File watcher
        if self.config.file_watcher.enabled:
            try:
                self._file_watcher = FileWatcher(
                    config=self.config.file_watcher,
                    on_new_file=self._on_new_analysis,
                )
                self._file_watcher.start()
                logger.info("File watcher source started")
            except Exception as e:
                logger.error(f"Failed to start file watcher: {e}")
                self.state.to(State.ERROR, {'error': f'File watcher: {e}'})

        # Modbus source
        if self.config.modbus_source.enabled:
            try:
                self._modbus_source = ModbusSource(
                    config=self.config.modbus_source,
                    on_new_data=self._on_modbus_data,
                )
                self._modbus_source.start()
                logger.info("Modbus source started")
            except Exception as e:
                logger.error(f"Failed to start Modbus source: {e}")
                self.state.to(State.ERROR, {'error': f'Modbus source: {e}'})

        # Serial source
        if self.config.serial_source.enabled:
            try:
                analysis_cfg = self.config.analysis_source if self.config.analysis_source.enabled else None
                self._serial_source = SerialSource(
                    config=self.config.serial_source,
                    on_new_frame=self._on_new_analysis,
                    analysis_config=analysis_cfg,
                    on_raw_sample=self._on_raw_sample if analysis_cfg else None,
                    on_inject_marker=self._on_inject_trigger if analysis_cfg else None,
                )
                self._serial_source.start()
                logger.info(f"Serial source started (streaming={analysis_cfg is not None})")
            except Exception as e:
                logger.error(f"Failed to start serial source: {e}")
                self.state.to(State.ERROR, {'error': f'Serial source: {e}'})

        sources = []
        if self.config.file_watcher.enabled: sources.append('file')
        if self.config.modbus_source.enabled: sources.append('modbus')
        if self.config.serial_source.enabled: sources.append('serial')

        if not sources:
            logger.warning("No data sources enabled!")
        else:
            logger.info(f"Active data sources: {', '.join(sources)}")

    def _stop_data_sources(self):
        """Stop all data sources."""
        if self._file_watcher:
            try:
                self._file_watcher.stop()
            except Exception as e:
                logger.error(f"Error stopping file watcher: {e}")
            self._file_watcher = None

        if self._modbus_source:
            try:
                self._modbus_source.stop()
            except Exception as e:
                logger.error(f"Error stopping Modbus source: {e}")
            self._modbus_source = None

        if self._serial_source:
            try:
                self._serial_source.stop()
            except Exception as e:
                logger.error(f"Error stopping serial source: {e}")
            self._serial_source = None

    # ------------------------------------------------------------------
    # Data source callbacks
    # ------------------------------------------------------------------

    def _on_new_analysis(self, analysis: dict):
        """Handle new GC analysis result from file watcher or serial source."""
        self._analysis_count += 1
        self._last_analysis_time = time.time()

        source = analysis.get('_source', 'unknown')

        # Extract component values and update channel_values
        # The analysis dict has 'components' with {name: {concentration/value, unit}}
        components = analysis.get('components', analysis.get('values', {}))

        with self._values_lock:
            for name, data in components.items():
                if isinstance(data, dict):
                    value = data.get('concentration', data.get('value'))
                else:
                    value = data

                if value is not None:
                    # Map to configured channels
                    channel_name = self._resolve_channel(name)
                    if channel_name:
                        ch_config = self.config.channels.get(channel_name)
                        if ch_config:
                            value = float(value) * ch_config.scale + ch_config.offset
                        self._channel_values[channel_name] = {
                            'value': value,
                            'timestamp': time.time(),
                            'unit': data.get('unit', '') if isinstance(data, dict) else '',
                            'quality': 'good',
                        }

        # Feed to SST for system suitability tracking
        if self._sst and QC_AVAILABLE:
            self._sst.add_replicate(analysis)

        # Publish full analysis result to MQTT
        self._publish_analysis(analysis)

        # Audit log
        self._audit.log_event('analysis_complete', details={
            'source': source,
            'components': len(components),
            'analysis_count': self._analysis_count,
        })

        logger.info(
            f"Analysis #{self._analysis_count} from {source}: "
            f"{len(components)} component(s)"
        )

    def _on_modbus_data(self, data: dict):
        """Handle new data from Modbus source."""
        # Modbus returns {name: {value, unit, raw}} per register
        with self._values_lock:
            for name, reg_data in data.items():
                if name.startswith('_'):
                    continue  # Skip metadata keys

                if isinstance(reg_data, dict) and reg_data.get('value') is not None:
                    channel_name = self._resolve_channel(name)
                    if channel_name:
                        ch_config = self.config.channels.get(channel_name)
                        value = reg_data['value']
                        if ch_config:
                            value = float(value) * ch_config.scale + ch_config.offset
                        self._channel_values[channel_name] = {
                            'value': value,
                            'timestamp': time.time(),
                            'unit': reg_data.get('unit', ''),
                            'quality': 'good',
                        }

    def _resolve_channel(self, source_name: str) -> Optional[str]:
        """Resolve a source field name to a configured channel name."""
        # Direct match
        if source_name in self.config.channels:
            return source_name

        # Check source_field mapping
        for ch_name, ch_config in self.config.channels.items():
            if ch_config.source_field == source_name:
                return ch_name

        # No mapping — use raw name if no channels configured
        # (auto-discover mode)
        if not self.config.channels:
            return source_name

        return None

    # ------------------------------------------------------------------
    # GC run lifecycle (streaming analysis)
    # ------------------------------------------------------------------

    def _on_inject_trigger(self):
        """Handle inject trigger (serial marker, MQTT command, threshold, or timer).

        Starts a new analysis run if one is not already active.
        """
        now = time.time()
        cfg = self.config.analysis_source

        # Debounce
        if now - self._last_inject_time < cfg.inject_debounce_s:
            logger.debug("Inject trigger debounced")
            return
        self._last_inject_time = now

        if self._run_active:
            logger.warning("Inject trigger ignored — run already active")
            return

        if not self._analysis_engine or not ANALYSIS_AVAILABLE:
            logger.error("Inject trigger ignored — analysis engine not available")
            return

        self._start_run()

    def _start_run(self, port: Optional[int] = None):
        """Start a new GC analysis run."""
        self._run_number += 1
        self._run_active = True
        self._run_start_time = time.time()
        self._last_progress_time = self._run_start_time
        self._chromatogram_times = []
        self._chromatogram_values = []

        # Reset serial stream timer
        if self._serial_source and hasattr(self._serial_source, 'reset_stream_timer'):
            self._serial_source.reset_stream_timer()

        # Start the analysis engine run
        self._analysis_engine.start_run(port=port)

        # Transition state
        self.state.to(State.ANALYZING)

        # Publish run started
        run_info = {
            'run_number': self._run_number,
            'method': getattr(self._analysis_method, 'name', 'default'),
            'port': self.config.serial_source.port if self.config.serial_source.enabled else '',
            'trigger': self.config.analysis_source.inject_trigger,
            'timestamp': self._run_start_time,
        }
        self._mqtt.publish_critical(
            self._mqtt.topic("gc", "run_started"), run_info,
        )

        self._audit.log_event('gc_run_started', details={
            'run_number': self._run_number,
            'trigger': self.config.analysis_source.inject_trigger,
        })

        logger.info(f"GC run #{self._run_number} started")

    def _on_raw_sample(self, time_s: float, voltage: float):
        """Handle a raw detector sample from serial streaming mode.

        Called by SerialSource for each voltage reading during a run.
        Also handles threshold-based inject detection when no run is active.
        """
        self._last_voltage = voltage

        # Threshold inject detection (when not in a run)
        if not self._run_active and self.config.analysis_source.inject_trigger == 'threshold':
            if voltage >= self.config.analysis_source.inject_threshold_v:
                logger.info(f"Threshold inject: voltage {voltage:.4f} >= {self.config.analysis_source.inject_threshold_v}")
                self._on_inject_trigger()

        # Feed to analysis engine if run is active
        if self._run_active and self._analysis_engine:
            try:
                self._analysis_engine.add_point(time_s, voltage)
                self._chromatogram_times.append(time_s)
                self._chromatogram_values.append(voltage)
            except Exception as e:
                logger.error(f"Error adding point to analysis engine: {e}")

    def _check_run_timeout(self):
        """Check if the current run has exceeded its max duration."""
        if not self._run_active:
            return

        elapsed = time.time() - self._run_start_time
        max_duration = self.config.analysis_source.run_duration_s

        if elapsed >= max_duration:
            logger.info(f"GC run #{self._run_number} timed out after {elapsed:.1f}s")
            self._finish_run(reason='timeout')

    def _check_run_progress(self):
        """Publish run progress at configured interval."""
        if not self._run_active:
            return

        now = time.time()
        if now - self._last_progress_time < self.config.analysis_source.progress_interval_s:
            return
        self._last_progress_time = now

        elapsed = now - self._run_start_time
        progress = {
            'run_number': self._run_number,
            'elapsed_s': round(elapsed, 1),
            'points': len(self._chromatogram_times),
            'max_voltage': max(self._chromatogram_values) if self._chromatogram_values else 0.0,
            'last_voltage': self._last_voltage,
        }
        self._mqtt.publish(self._mqtt.topic("gc", "run_progress"), progress)

    def _check_auto_run_timer(self):
        """Start a run automatically at configured interval."""
        cfg = self.config.analysis_source
        if not cfg.enabled or cfg.inject_trigger != 'timer':
            return
        if cfg.auto_run_interval_s <= 0:
            return
        if self._run_active:
            return

        now = time.time()
        if now - self._last_auto_run_time >= cfg.auto_run_interval_s:
            self._last_auto_run_time = now
            logger.info("Auto-run timer triggered")
            self._on_inject_trigger()

    def _finish_run(self, reason: str = 'command'):
        """Finish the current GC analysis run and publish results."""
        if not self._run_active:
            return

        self._run_active = False
        elapsed = time.time() - self._run_start_time

        logger.info(
            f"GC run #{self._run_number} finished ({reason}) — "
            f"{len(self._chromatogram_times)} points, {elapsed:.1f}s"
        )

        # Finish the analysis engine run → get full result
        result = None
        if self._analysis_engine:
            try:
                result = self._analysis_engine.finish_run()
            except Exception as e:
                logger.error(f"Analysis engine finish_run error: {e}")

        # Transition back to ACQUIRING
        self.state.to(State.ACQUIRING)

        # Publish chromatogram raw data
        if self.config.analysis_source.publish_raw_chromatogram:
            self._publish_chromatogram()

        # Publish analysis result (through existing pipeline)
        if result is not None:
            result_dict = result if isinstance(result, dict) else {'result': str(result)}
            result_dict['run_number'] = self._run_number
            result_dict['run_duration_s'] = round(elapsed, 2)
            result_dict['finish_reason'] = reason
            result_dict['_source'] = 'analysis_engine'

            # Route through existing analysis handler
            self._on_new_analysis(result_dict)

        self._audit.log_event('gc_run_finished', details={
            'run_number': self._run_number,
            'reason': reason,
            'points': len(self._chromatogram_times),
            'duration_s': round(elapsed, 2),
        })

        # Scheduler: complete current run and start next queued run
        if self._scheduler is not None:
            try:
                self._scheduler.complete_current_run(
                    result=result_dict if result is not None else None,
                    success=(reason != 'error'),
                )
                next_run = self._scheduler.get_next_run()
                if next_run is not None:
                    logger.info(
                        f"Scheduler: starting next run {next_run.run_id} "
                        f"({next_run.run_type.name}, sample={next_run.sample_id!r})"
                    )
                    # Load method if specified
                    if next_run.method_name:
                        method_data = self._load_method(next_run.method_name)
                        if method_data and self._analysis_engine:
                            method = AnalysisMethod.from_dict(method_data)
                            self._analysis_engine._method = method
                    self._start_run(port=next_run.port or None)
                else:
                    # Publish queue update
                    self._mqtt.publish(
                        self._mqtt.topic('gc', 'queue_status'),
                        self._scheduler.get_status(),
                    )
            except Exception as e:
                logger.error(f"Scheduler run lifecycle error: {e}")

    def _publish_chromatogram(self):
        """Publish raw chromatogram data (times + voltages) to MQTT."""
        if not self._chromatogram_times:
            return

        chromatogram = {
            'run_number': self._run_number,
            'node_id': self.config.node_id,
            'times': self._chromatogram_times,
            'values': self._chromatogram_values,
            'points': len(self._chromatogram_times),
            'duration_s': self._chromatogram_times[-1] if self._chromatogram_times else 0,
            'timestamp': time.time(),
        }

        topic = self._mqtt.topic("gc", "chromatogram")
        self._mqtt.publish_critical(topic, chromatogram, retain=True)
        logger.info(
            f"Published chromatogram: {len(self._chromatogram_times)} points, "
            f"{chromatogram['duration_s']:.1f}s"
        )

    # ------------------------------------------------------------------
    # MQTT callbacks
    # ------------------------------------------------------------------

    def _on_mqtt_message(self, topic: str, payload: dict):
        """Queue incoming MQTT message for processing."""
        try:
            self._command_queue.put_nowait((topic, payload))
        except queue.Full:
            logger.warning("Command queue full, dropping message")

    def _on_connection_change(self, connected: bool):
        """Handle MQTT connection state change."""
        if connected:
            logger.info("MQTT connected — publishing initial status")
            self._publish_status()
        else:
            logger.warning("MQTT disconnected")

    def _process_commands(self):
        """Process all pending MQTT commands."""
        processed = 0
        while processed < 20:  # Cap per loop iteration
            try:
                topic, payload = self._command_queue.get_nowait()
            except queue.Empty:
                break

            processed += 1
            self._handle_command(topic, payload)

    def _handle_command(self, topic: str, payload: dict):
        """Route an MQTT command to the appropriate handler."""
        # Config push
        if '/config/push' in topic:
            self._handle_config_push(payload)
        elif '/config/get' in topic:
            self._handle_config_get(payload)
        elif '/commands/' in topic:
            self._handle_gc_command(topic, payload)
        elif '/discovery/ping' in topic:
            self._handle_discovery_ping(payload)

    def _handle_config_push(self, payload: dict):
        """Handle configuration update from DAQ service."""
        logger.info("Received config push")

        try:
            new_config = load_config(payload, self.config)

            # Stop current sources
            self._stop_data_sources()

            # Apply new config
            self.config = new_config

            # Save config to disk
            config_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                'config.json'
            )
            save_config(self.config, config_path)

            # Restart sources with new config
            self._start_data_sources()

            self._audit.log_event('config_change', details={
                'source': 'mqtt_push',
            })

            logger.info("Config updated and sources restarted")

            # Publish updated status
            self._publish_status()

        except Exception as e:
            logger.error(f"Config push failed: {e}")
            self.state.to(State.ERROR, {'error': f'Config push: {e}'})

    def _handle_config_get(self, payload: dict):
        """Handle config request — publish current config."""
        config_topic = self._mqtt.topic("config", "current")
        self._mqtt.publish_critical(config_topic, {
            'node_id': self.config.node_id,
            'node_name': self.config.node_name,
            'gc_type': self.config.gc_type,
            'file_watcher': {
                'enabled': self.config.file_watcher.enabled,
                'watch_directory': self.config.file_watcher.watch_directory,
                'file_pattern': self.config.file_watcher.file_pattern,
            },
            'modbus_source': {
                'enabled': self.config.modbus_source.enabled,
                'connection_type': self.config.modbus_source.connection_type,
            },
            'serial_source': {
                'enabled': self.config.serial_source.enabled,
                'port': self.config.serial_source.port,
            },
            'analysis_source': {
                'enabled': self.config.analysis_source.enabled,
                'mode': self.config.analysis_source.mode,
                'inject_trigger': self.config.analysis_source.inject_trigger,
            },
            'channels': list(self.config.channels.keys()),
        }, retain=True)

    def _handle_gc_command(self, topic: str, payload: dict):
        """Handle GC-specific commands."""
        command = payload.get('command', '')

        if command == 'start_run':
            # Manual inject trigger via MQTT
            self._on_inject_trigger()

        elif command == 'stop_run':
            # Manual stop of current run
            if self._run_active:
                self._finish_run(reason='manual_stop')
            else:
                logger.warning("stop_run: no active run")

        elif command == 'push_method':
            # Update analysis method from MQTT payload
            method_data = payload.get('method', {})
            if method_data and ANALYSIS_AVAILABLE and AnalysisMethod is not None:
                try:
                    self._analysis_method = AnalysisMethod.from_dict(method_data)
                    if self._analysis_engine:
                        self._analysis_engine._method = self._analysis_method
                    logger.info(f"Analysis method updated: {getattr(self._analysis_method, 'name', 'unnamed')}")
                    self._audit.log_event('method_updated', details={
                        'method_name': getattr(self._analysis_method, 'name', 'unnamed'),
                    })
                except Exception as e:
                    logger.error(f"Failed to load method: {e}")

        elif command == 'get_chromatogram':
            # Return last chromatogram data
            self._publish_chromatogram()

        elif command == 'reprocess_files':
            # Re-scan and process existing files
            if self._file_watcher:
                self._file_watcher.clear_processed()
                logger.info("File watcher: cleared processed files, will re-process")

        elif command == 'get_analysis_count':
            self._mqtt.publish(
                self._mqtt.topic("gc", "analysis_count"),
                {'count': self._analysis_count, 'last_time': self._last_analysis_time}
            )

        elif command == 'load_library':
            # Load/update peak library from payload
            library_data = payload.get('library', {})
            if library_data and ANALYSIS_AVAILABLE and PeakLibrary is not None:
                self._peak_library = PeakLibrary()
                self._peak_library.load_dict(library_data)
                logger.info(f"Peak library updated: {self._peak_library.size} compounds")

        elif command == 'sst_evaluate':
            # Evaluate system suitability from accumulated replicates
            if self._sst and QC_AVAILABLE:
                result = self._sst.evaluate()
                self._mqtt.publish_critical(
                    self._mqtt.topic("gc", "sst_result"),
                    result.to_dict(), retain=True,
                )
                self._audit.log_event('sst_evaluation', details={
                    'passed': result.passed,
                    'failures': result.failures,
                })

        elif command == 'sst_clear':
            # Clear SST replicates
            if self._sst and QC_AVAILABLE:
                self._sst.clear()

        elif command == 'qc_check_standard':
            # Evaluate a check standard
            expected = payload.get('expected_values', {})
            result_data = payload.get('result', {})
            if self._qc_tracker and QC_AVAILABLE and expected:
                qc = self._qc_tracker.evaluate_check_standard(result_data, expected)
                self._mqtt.publish_critical(
                    self._mqtt.topic("gc", "qc_result"),
                    qc.to_dict(), retain=True,
                )

        elif command == 'qc_blank':
            # Evaluate a blank run
            result_data = payload.get('result', {})
            if self._qc_tracker and QC_AVAILABLE:
                qc = self._qc_tracker.evaluate_blank(result_data)
                self._mqtt.publish_critical(
                    self._mqtt.topic("gc", "qc_result"),
                    qc.to_dict(), retain=True,
                )

        elif command == 'get_qc_summary':
            # Return QC program summary
            if self._qc_tracker and QC_AVAILABLE:
                self._mqtt.publish_critical(
                    self._mqtt.topic("gc", "qc_summary"),
                    self._qc_tracker.get_summary(), retain=True,
                )

        elif command == 'load_method_validation':
            # Load method validation data
            if QC_AVAILABLE:
                self._method_validation = MethodValidation.from_dict(payload.get('validation', {}))
                logger.info(f"Method validation loaded: {self._method_validation.method_name}")

        elif command == 'save_method':
            # Save a method to the methods directory
            method_data = payload.get('method', {})
            method_name = method_data.get('name', '')
            if method_name:
                self._save_method(method_name, method_data)

        elif command == 'list_methods':
            # Return list of saved methods
            methods = self._list_methods()
            self._mqtt.publish_critical(
                self._mqtt.topic("gc", "methods_list"),
                {'methods': methods}, retain=False
            )

        elif command == 'get_method':
            # Return a specific method by name
            method_name = payload.get('name', '')
            method_data = self._load_method(method_name)
            self._mqtt.publish_critical(
                self._mqtt.topic("gc", "method_data"),
                {'name': method_name, 'method': method_data}, retain=False
            )

        elif command == 'delete_method':
            # Delete a saved method
            method_name = payload.get('name', '')
            success = self._delete_method(method_name)
            self._mqtt.publish(
                self._mqtt.topic("gc", "method_deleted"),
                {'name': method_name, 'success': success}
            )

        # --- Scheduler commands (Phase 5) ---
        elif command.startswith('queue_'):
            if hasattr(self, '_scheduler') and self._scheduler:
                response = self._scheduler.handle_command(command, payload)
                self._mqtt.publish(
                    self._mqtt.topic("gc", "scheduler_response"),
                    response
                )

    def _handle_discovery_ping(self, payload: dict):
        """Respond to discovery ping with status."""
        self._publish_status()

    # ------------------------------------------------------------------
    # MQTT publishing
    # ------------------------------------------------------------------

    def _publish_values(self):
        """Publish current channel values as batch."""
        with self._values_lock:
            if not self._channel_values:
                return

            batch = {}
            for name, data in self._channel_values.items():
                batch[name] = {
                    'value': data['value'],
                    'timestamp': data['timestamp'],
                    'unit': data.get('unit', ''),
                    'quality': data.get('quality', 'good'),
                }

        topic = self._mqtt.topic("channels", "batch")
        self._mqtt.publish(topic, batch)

    def _publish_status(self):
        """Publish full system status."""
        # Build source status
        sources = {}
        if self._file_watcher:
            sources['file_watcher'] = self._file_watcher.get_status()
        if self._modbus_source:
            sources['modbus'] = self._modbus_source.get_status()
        if self._serial_source:
            sources['serial'] = self._serial_source.get_status()

        status = {
            'node_id': self.config.node_id,
            'node_name': self.config.node_name,
            'node_type': 'gc',
            'gc_type': self.config.gc_type,
            'status': 'online',
            'version': __version__,
            'state': self.state.state.name,
            'ip_address': self._get_local_ip(),
            'hostname': socket.gethostname(),
            'channels': len(self.config.channels) or len(self._channel_values),
            'analysis_count': self._analysis_count,
            'last_analysis': self._last_analysis_time,
            'sources': sources,
            'uptime': time.time() - getattr(self, '_start_time', time.time()),
            'product_type': 'GC Analyzer',
            'qc_available': QC_AVAILABLE,
            'analysis_engine_available': self._analysis_engine is not None,
            'analysis_source_enabled': self.config.analysis_source.enabled,
            'run_active': self._run_active,
            'run_number': self._run_number,
        }

        if self._run_active:
            status['run_elapsed_s'] = round(time.time() - self._run_start_time, 1)
            status['run_points'] = len(self._chromatogram_times)

        # Include QC summary if available
        if self._qc_tracker and QC_AVAILABLE:
            status['qc_summary'] = self._qc_tracker.get_summary()
        if self._method_validation and QC_AVAILABLE:
            status['method_validation'] = {
                'method_name': self._method_validation.method_name,
                'status': self._method_validation.status,
                'validated_date': self._method_validation.validated_date,
            }

        if self.state.is_error:
            status['last_error'] = self.state.last_error

        topic = self._mqtt.topic("status", "system")
        self._mqtt.publish_critical(topic, status, retain=True)

    def _publish_heartbeat(self):
        """Publish lightweight heartbeat."""
        heartbeat = {
            'node_id': self.config.node_id,
            'node_type': 'gc',
            'status': 'online',
            'channels': len(self.config.channels) or len(self._channel_values),
            'state': self.state.state.name,
            'ip_address': self._get_local_ip(),
            'product_type': 'GC Analyzer',
            'analysis_count': self._analysis_count,
            'timestamp': time.time(),
        }

        topic = self._mqtt.topic("heartbeat")
        self._mqtt.publish(topic, heartbeat)

    def _publish_analysis(self, analysis: dict):
        """Publish full GC analysis result."""
        # Remove internal metadata keys
        clean = {k: v for k, v in analysis.items() if not k.startswith('_')}
        clean['analysis_number'] = self._analysis_count
        clean['node_id'] = self.config.node_id

        topic = self._mqtt.topic("gc", "analysis")
        self._mqtt.publish_critical(topic, clean, retain=True)

    # ------------------------------------------------------------------
    # Method Storage
    # ------------------------------------------------------------------

    def _get_methods_dir(self) -> str:
        """Get or create the methods directory."""
        base = os.path.dirname(os.path.abspath(__file__))
        methods_dir = os.path.join(base, 'methods')
        os.makedirs(methods_dir, exist_ok=True)
        return methods_dir

    def _save_method(self, name: str, method_data: dict) -> bool:
        """Save a method to disk as JSON."""
        try:
            safe_name = "".join(c for c in name if c.isalnum() or c in ('_', '-', ' ')).strip()
            if not safe_name:
                logger.error("save_method: invalid method name")
                return False
            filepath = os.path.join(self._get_methods_dir(), f"{safe_name}.json")
            with open(filepath, 'w') as f:
                json.dump(method_data, f, indent=2)
            logger.info(f"Method saved: {safe_name}")
            self._audit.log_event('method_saved', details={'name': safe_name})
            return True
        except Exception as e:
            logger.error(f"Failed to save method '{name}': {e}")
            return False

    def _load_method(self, name: str) -> Optional[dict]:
        """Load a method from disk by name."""
        try:
            safe_name = "".join(c for c in name if c.isalnum() or c in ('_', '-', ' ')).strip()
            filepath = os.path.join(self._get_methods_dir(), f"{safe_name}.json")
            if not os.path.exists(filepath):
                return None
            with open(filepath, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load method '{name}': {e}")
            return None

    def _list_methods(self) -> list:
        """List all saved methods."""
        methods = []
        methods_dir = self._get_methods_dir()
        try:
            for f in sorted(os.listdir(methods_dir)):
                if f.endswith('.json'):
                    name = f[:-5]
                    filepath = os.path.join(methods_dir, f)
                    try:
                        with open(filepath, 'r') as fp:
                            data = json.load(fp)
                        methods.append({
                            'name': name,
                            'description': data.get('description', ''),
                            'components': len(data.get('components', [])),
                            'modified': os.path.getmtime(filepath),
                        })
                    except Exception:
                        methods.append({'name': name, 'description': '(error reading)', 'components': 0})
        except Exception as e:
            logger.error(f"Failed to list methods: {e}")
        return methods

    def _delete_method(self, name: str) -> bool:
        """Delete a saved method."""
        try:
            safe_name = "".join(c for c in name if c.isalnum() or c in ('_', '-', ' ')).strip()
            filepath = os.path.join(self._get_methods_dir(), f"{safe_name}.json")
            if os.path.exists(filepath):
                os.remove(filepath)
                logger.info(f"Method deleted: {safe_name}")
                self._audit.log_event('method_deleted', details={'name': safe_name})
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to delete method '{name}': {e}")
            return False

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    _cached_ip = None
    _ip_cache_time = 0.0

    def _get_local_ip(self) -> str:
        """Get local IP address (cached for 60s)."""
        now = time.time()
        if self._cached_ip and now - self._ip_cache_time < 60.0:
            return self._cached_ip

        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((self.config.mqtt_broker, 1883))
            ip = s.getsockname()[0]
            s.close()
            self.__class__._cached_ip = ip
            self.__class__._ip_cache_time = now
            return ip
        except Exception:
            return '127.0.0.1'

def main():
    """Entry point for gc_node service."""
    import argparse

    parser = argparse.ArgumentParser(description='GC Node - Gas Chromatograph VM Bridge')
    parser.add_argument('--config', '-c', default='config.json',
                        help='Path to config JSON file')
    parser.add_argument('--broker', '-b', default=None,
                        help='MQTT broker address (overrides config)')
    parser.add_argument('--node-id', '-n', default=None,
                        help='Node ID (overrides config)')
    parser.add_argument('--log-level', '-l', default='INFO',
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                        help='Log level')
    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )

    # Load config
    config_path = args.config
    if not os.path.isabs(config_path):
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), config_path)

    if os.path.exists(config_path):
        logger.info(f"Loading config from {config_path}")
        config = NodeConfig.from_json_file(config_path)
    else:
        logger.info(f"No config file found at {config_path}, using defaults")
        config = NodeConfig()

    # Apply command-line overrides
    if args.broker:
        config.mqtt_broker = args.broker
    if args.node_id:
        config.node_id = args.node_id

    # Register signal handlers for graceful shutdown
    service = GCNodeService(config)
    service._start_time = time.time()

    def signal_handler(sig, frame):
        logger.info(f"Signal {sig} received, shutting down...")
        service._shutdown.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Run the service
    service.run()
