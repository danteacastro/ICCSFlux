"""
Script Manager for DCFlux

Executes Python scripts server-side for headless operation.
Scripts have access to the same API as the browser Pyodide playground:
- tags.* - Read channel values
- outputs.set() - Control outputs
- publish() - Publish computed values
- session.* - Session control

Scripts run in isolated threads and can be controlled via MQTT.
"""

import json
import time
import asyncio
import threading
import logging
import traceback
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Callable, Set
from enum import Enum
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import queue

logger = logging.getLogger('ScriptManager')


class ScriptState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"


class ScriptRunMode(str, Enum):
    MANUAL = "manual"           # Started manually
    ACQUISITION = "acquisition"  # Auto-start with acquisition
    SESSION = "session"          # Auto-start with session


@dataclass
class Script:
    """A Python script definition"""
    id: str
    name: str
    code: str
    description: str = ""
    enabled: bool = True
    run_mode: ScriptRunMode = ScriptRunMode.MANUAL
    created_at: str = ""
    modified_at: str = ""

    # Runtime state (not persisted)
    state: ScriptState = field(default=ScriptState.IDLE, repr=False)
    started_at: Optional[float] = field(default=None, repr=False)
    iterations: int = field(default=0, repr=False)
    error_message: Optional[str] = field(default=None, repr=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "code": self.code,
            "description": self.description,
            "enabled": self.enabled,
            "runMode": self.run_mode.value if isinstance(self.run_mode, ScriptRunMode) else self.run_mode,
            "createdAt": self.created_at,
            "modifiedAt": self.modified_at,
            # Runtime state
            "state": self.state.value if isinstance(self.state, ScriptState) else self.state,
            "startedAt": self.started_at,
            "iterations": self.iterations,
            "errorMessage": self.error_message
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Script':
        run_mode = data.get("runMode", "manual")
        if isinstance(run_mode, str):
            try:
                run_mode = ScriptRunMode(run_mode)
            except ValueError:
                run_mode = ScriptRunMode.MANUAL

        return cls(
            id=data["id"],
            name=data["name"],
            code=data.get("code", ""),
            description=data.get("description", ""),
            enabled=data.get("enabled", True),
            run_mode=run_mode,
            created_at=data.get("createdAt", ""),
            modified_at=data.get("modifiedAt", "")
        )


class ScriptRuntime:
    """
    Runtime environment for a single script.
    Provides the nisystem API (tags, outputs, session, publish).
    """

    def __init__(self, script: Script, manager: 'ScriptManager'):
        self.script = script
        self.manager = manager
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._published_values: Dict[str, Any] = {}

    def start(self):
        """Start script execution in a new thread"""
        if self._thread and self._thread.is_alive():
            logger.warning(f"Script {self.script.name} already running")
            return False

        self._stop_event.clear()
        self.script.state = ScriptState.RUNNING
        self.script.started_at = time.time()
        self.script.iterations = 0
        self.script.error_message = None

        self._thread = threading.Thread(
            target=self._run,
            name=f"Script-{self.script.id}",
            daemon=True
        )
        self._thread.start()
        logger.info(f"Started script: {self.script.name}")
        return True

    def stop(self):
        """Stop script execution"""
        if not self._thread or not self._thread.is_alive():
            return

        self.script.state = ScriptState.STOPPING
        self._stop_event.set()

        # Wait for thread to finish (with timeout)
        self._thread.join(timeout=5.0)

        if self._thread.is_alive():
            logger.warning(f"Script {self.script.name} did not stop gracefully")

        self.script.state = ScriptState.IDLE
        logger.info(f"Stopped script: {self.script.name}")

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run(self):
        """Execute the script code"""
        try:
            # Build the execution namespace with nisystem API
            namespace = self._build_namespace()

            # Preprocess code: strip 'await' keywords for sync execution
            # This allows the same script to work in both Pyodide (async) and backend (sync)
            import re
            code = self.script.code
            # Replace 'await next_scan()' with 'next_scan()'
            # Replace 'await wait_for(...)' with 'wait_for(...)'
            # Replace 'await wait_until(...)' with 'wait_until(...)'
            code = re.sub(r'\bawait\s+(next_scan|wait_for|wait_until)\s*\(', r'\1(', code)

            # Compile and execute
            code_obj = compile(code, f"<script:{self.script.name}>", 'exec')
            exec(code_obj, namespace)

            # If script has a main loop, it should have exited by now
            self.script.state = ScriptState.IDLE
            logger.info(f"Script {self.script.name} completed normally")

        except StopScript:
            # Normal stop via stop_event
            self.script.state = ScriptState.IDLE
            logger.info(f"Script {self.script.name} stopped")

        except Exception as e:
            self.script.state = ScriptState.ERROR
            self.script.error_message = str(e)
            logger.error(f"Script {self.script.name} error: {e}")
            logger.debug(traceback.format_exc())

            # Notify manager of error
            self.manager._on_script_error(self.script, str(e))

    def _build_namespace(self) -> dict:
        """Build the execution namespace with nisystem API"""

        # Tags API - read channel values
        class TagsAPI:
            def __init__(self, runtime: ScriptRuntime):
                self._runtime = runtime

            def __getattr__(self, name: str) -> float:
                return self._runtime.manager.get_channel_value(name)

            def __getitem__(self, name: str) -> float:
                return self._runtime.manager.get_channel_value(name)

            def __contains__(self, name: str) -> bool:
                return self._runtime.manager.has_channel(name)

            def get(self, name: str, default: float = 0.0) -> float:
                if self._runtime.manager.has_channel(name):
                    return self._runtime.manager.get_channel_value(name)
                return default

            def keys(self) -> List[str]:
                return self._runtime.manager.get_channel_names()

            def age(self, name: str) -> float:
                """Get age of tag data in seconds"""
                ts = self._runtime.manager.get_channel_timestamp(name)
                if ts == 0:
                    return float('inf')
                return time.time() - ts

        # Outputs API - control outputs
        class OutputsAPI:
            def __init__(self, runtime: ScriptRuntime):
                self._runtime = runtime

            def set(self, channel: str, value) -> None:
                self._runtime.manager.set_output(channel, value)

            def __setitem__(self, name: str, value) -> None:
                self.set(name, value)

        # Session API - session state and control
        class SessionAPI:
            def __init__(self, runtime: ScriptRuntime):
                self._runtime = runtime

            @property
            def active(self) -> bool:
                # Check stop event first
                if self._runtime._stop_event.is_set():
                    raise StopScript()
                return self._runtime.manager.is_session_active()

            @property
            def elapsed(self) -> float:
                return self._runtime.manager.get_session_elapsed()

            @property
            def recording(self) -> bool:
                return self._runtime.manager.is_recording()

            def start(self) -> None:
                self._runtime.manager.start_acquisition()

            def stop(self) -> None:
                self._runtime.manager.stop_acquisition()

            def start_recording(self, filename: Optional[str] = None) -> None:
                self._runtime.manager.start_recording(filename)

            def stop_recording(self) -> None:
                self._runtime.manager.stop_recording()

            @staticmethod
            def now() -> float:
                """Current time in seconds (Unix timestamp)"""
                return time.time()

            @staticmethod
            def now_ms() -> int:
                """Current time in milliseconds"""
                return int(time.time() * 1000)

            @staticmethod
            def now_iso() -> str:
                """Current time as ISO string"""
                return datetime.now().isoformat()

        # Publish function - publish computed values
        def publish(name: str, value: float, units: str = '', description: str = '') -> None:
            self._published_values[name] = {
                'value': value,
                'units': units,
                'description': description,
                'timestamp': time.time()
            }
            self.manager.publish_value(self.script.id, name, value, units)

        # Sleep functions that respect stop event
        def next_scan() -> None:
            """Wait for next scan cycle (respects stop event)"""
            self.script.iterations += 1
            # Wait for scan interval or stop
            scan_rate = self.manager.get_scan_rate()
            interval = 1.0 / scan_rate if scan_rate > 0 else 0.1
            if self._stop_event.wait(interval):
                raise StopScript()

        def wait_for(seconds: float) -> None:
            """Wait for specified duration (respects stop event)"""
            if self._stop_event.wait(seconds):
                raise StopScript()

        def wait_until(condition_func, timeout: float = None) -> bool:
            """Wait until condition is true (respects stop event)"""
            start = time.time()
            while True:
                if self._stop_event.is_set():
                    raise StopScript()
                try:
                    if condition_func():
                        return True
                except:
                    pass
                if timeout and (time.time() - start) > timeout:
                    return False
                time.sleep(0.1)

        # Print function that logs to script output
        def script_print(*args, **kwargs):
            message = ' '.join(str(a) for a in args)
            self.manager.log_script_output(self.script.id, 'info', message)

        # Build namespace
        namespace = {
            # Core API
            'tags': TagsAPI(self),
            'outputs': OutputsAPI(self),
            'session': SessionAPI(self),
            'publish': publish,
            'next_scan': next_scan,
            'wait_for': wait_for,
            'wait_until': wait_until,

            # Overridden print
            'print': script_print,

            # Standard library (safe subset)
            'time': time,
            'math': __import__('math'),
            'datetime': __import__('datetime'),
            'json': __import__('json'),
            're': __import__('re'),
            'statistics': __import__('statistics'),

            # Built-ins (safe subset)
            'abs': abs,
            'all': all,
            'any': any,
            'bool': bool,
            'dict': dict,
            'enumerate': enumerate,
            'filter': filter,
            'float': float,
            'format': format,
            'frozenset': frozenset,
            'int': int,
            'isinstance': isinstance,
            'len': len,
            'list': list,
            'map': map,
            'max': max,
            'min': min,
            'pow': pow,
            'range': range,
            'reversed': reversed,
            'round': round,
            'set': set,
            'sorted': sorted,
            'str': str,
            'sum': sum,
            'tuple': tuple,
            'type': type,
            'zip': zip,

            # Helpers
            'True': True,
            'False': False,
            'None': None,
        }

        return namespace


class StopScript(Exception):
    """Raised to stop script execution gracefully"""
    pass


class ScriptManager:
    """
    Manages Python script execution server-side.

    Callbacks (set by DAQ service):
    - on_get_channel_value(channel): Get channel value
    - on_get_channel_timestamp(channel): Get channel timestamp
    - on_set_output(channel, value): Set output value
    - on_start_acquisition(): Start acquisition
    - on_stop_acquisition(): Stop acquisition
    - on_start_recording(filename): Start recording
    - on_stop_recording(): Stop recording
    - on_is_session_active(): Check if session is active
    - on_get_session_elapsed(): Get session elapsed time
    - on_is_recording(): Check if recording
    - on_publish_value(script_id, name, value, units): Publish computed value
    - on_script_event(event_type, script): Script state changed
    - on_script_output(script_id, type, message): Script logged output
    """

    def __init__(self):
        self.scripts: Dict[str, Script] = {}
        self.runtimes: Dict[str, ScriptRuntime] = {}

        # Callbacks (set by DAQ service)
        self.on_get_channel_value: Optional[Callable[[str], float]] = None
        self.on_get_channel_timestamp: Optional[Callable[[str], float]] = None
        self.on_get_channel_names: Optional[Callable[[], List[str]]] = None
        self.on_has_channel: Optional[Callable[[str], bool]] = None
        self.on_set_output: Optional[Callable[[str, Any], None]] = None
        self.on_start_acquisition: Optional[Callable[[], None]] = None
        self.on_stop_acquisition: Optional[Callable[[], None]] = None
        self.on_start_recording: Optional[Callable[[Optional[str]], None]] = None
        self.on_stop_recording: Optional[Callable[[], None]] = None
        self.on_is_session_active: Optional[Callable[[], bool]] = None
        self.on_get_session_elapsed: Optional[Callable[[], float]] = None
        self.on_is_recording: Optional[Callable[[], bool]] = None
        self.on_get_scan_rate: Optional[Callable[[], float]] = None
        self.on_publish_value: Optional[Callable[[str, str, float, str], None]] = None
        self.on_script_event: Optional[Callable[[str, Script], None]] = None
        self.on_script_output: Optional[Callable[[str, str, str], None]] = None

        self._lock = threading.Lock()

        # Track which outputs are controlled by scripts during active session
        # This allows selective lockout of only script-controlled channels
        self._controlled_outputs: Set[str] = set()

        logger.info("ScriptManager initialized")

    # =========================================================================
    # SCRIPT CRUD
    # =========================================================================

    def add_script(self, script: Script) -> bool:
        """Add or update a script"""
        with self._lock:
            # Stop if running
            if script.id in self.runtimes and self.runtimes[script.id].is_running():
                self.stop_script(script.id)

            self.scripts[script.id] = script
            logger.info(f"Added script: {script.name} ({script.id})")
            return True

    def add_script_from_dict(self, data: dict) -> bool:
        """Add a script from dictionary data.

        Why this method exists:
        - MQTT handlers receive script data as JSON (dict), not Script objects
        - This provides a clean one-liner for adding scripts from API calls
        - Handles both 'runMode' (frontend) and 'run_mode' (backend) field names
        - Centralizes dict->Script conversion so MQTT handlers stay simple

        Example:
            data = {'id': 'abc', 'name': 'My Script', 'code': 'x=1', 'run_mode': 'session'}
            script_manager.add_script_from_dict(data)
        """
        # Normalize run_mode field name (backend uses snake_case, frontend uses camelCase)
        if 'run_mode' in data and 'runMode' not in data:
            data['runMode'] = data['run_mode']

        script = Script.from_dict(data)
        return self.add_script(script)

    def update_script(self, script_id: str, updates: dict) -> bool:
        """Update an existing script with partial data.

        Why this method exists:
        - Allows partial updates without replacing the entire script
        - Common pattern: update just the code, or just enable/disable
        - Preserves fields not in the updates dict
        - Handles camelCase/snake_case field name variations

        Example:
            script_manager.update_script('my-script', {'name': 'New Name'})
            script_manager.update_script('my-script', {'enabled': False})
            script_manager.update_script('my-script', {'run_mode': 'session'})
        """
        with self._lock:
            script = self.scripts.get(script_id)
            if not script:
                logger.error(f"Script not found for update: {script_id}")
                return False

            # Stop if running before updating
            if script_id in self.runtimes and self.runtimes[script_id].is_running():
                self.stop_script(script_id)

            # Apply updates
            if 'name' in updates:
                script.name = updates['name']
            if 'code' in updates:
                script.code = updates['code']
            if 'description' in updates:
                script.description = updates['description']
            if 'enabled' in updates:
                script.enabled = updates['enabled']

            # Handle run_mode with both naming conventions
            run_mode = updates.get('runMode') or updates.get('run_mode')
            if run_mode:
                if isinstance(run_mode, str):
                    try:
                        script.run_mode = ScriptRunMode(run_mode)
                    except ValueError:
                        logger.warning(f"Invalid run_mode: {run_mode}")
                elif isinstance(run_mode, ScriptRunMode):
                    script.run_mode = run_mode

            script.modified_at = datetime.now().isoformat()
            logger.info(f"Updated script: {script.name} ({script_id})")
            return True

    def remove_script(self, script_id: str) -> bool:
        """Remove a script"""
        with self._lock:
            if script_id not in self.scripts:
                return False

            # Stop if running
            if script_id in self.runtimes:
                self.runtimes[script_id].stop()
                del self.runtimes[script_id]

            del self.scripts[script_id]
            logger.info(f"Removed script: {script_id}")
            return True

    def get_script(self, script_id: str) -> Optional[Script]:
        """Get a script by ID"""
        return self.scripts.get(script_id)

    def get_all_scripts(self) -> List[Script]:
        """Get all scripts"""
        return list(self.scripts.values())

    def load_scripts_from_project(self, project_data: dict) -> None:
        """Load scripts from project data

        Supports two formats:
        1. Nested: project_data['scripts']['pythonScripts'] (frontend format)
        2. Flat: project_data['scripts'] as array (legacy format)
        """
        # Stop all current scripts first
        self.stop_all_scripts()
        self.scripts.clear()
        self.runtimes.clear()

        # Try nested format first (frontend saves as scripts.pythonScripts)
        scripts_section = project_data.get('scripts', {})
        if isinstance(scripts_section, dict):
            scripts_data = scripts_section.get('pythonScripts', [])
        elif isinstance(scripts_section, list):
            # Legacy flat format
            scripts_data = scripts_section
        else:
            scripts_data = []

        # Load scripts
        for script_data in scripts_data:
            try:
                script = Script.from_dict(script_data)
                self.scripts[script.id] = script
                logger.debug(f"Loaded script: {script.name} (runMode={script.run_mode.value})")
            except Exception as e:
                logger.error(f"Failed to load script: {e}")

        logger.info(f"Loaded {len(self.scripts)} scripts from project")

    def export_scripts_for_project(self) -> List[dict]:
        """Export scripts for saving to project"""
        return [s.to_dict() for s in self.scripts.values()]

    # =========================================================================
    # SCRIPT EXECUTION
    # =========================================================================

    def start_script(self, script_id: str) -> bool:
        """Start a script"""
        script = self.scripts.get(script_id)
        if not script:
            logger.error(f"Script not found: {script_id}")
            return False

        if not script.enabled:
            logger.warning(f"Script is disabled: {script.name}")
            return False

        # Create runtime if needed
        if script_id not in self.runtimes:
            self.runtimes[script_id] = ScriptRuntime(script, self)

        runtime = self.runtimes[script_id]

        if runtime.is_running():
            logger.warning(f"Script already running: {script.name}")
            return False

        if runtime.start():
            self._emit_event('started', script)
            return True
        return False

    def stop_script(self, script_id: str) -> bool:
        """Stop a script"""
        if script_id not in self.runtimes:
            return False

        runtime = self.runtimes[script_id]
        script = self.scripts.get(script_id)

        runtime.stop()

        if script:
            self._emit_event('stopped', script)

        return True

    def stop_all_scripts(self) -> None:
        """Stop all running scripts"""
        for script_id in list(self.runtimes.keys()):
            self.stop_script(script_id)

    def is_script_running(self, script_id: str) -> bool:
        """Check if a script is running"""
        if script_id not in self.runtimes:
            return False
        return self.runtimes[script_id].is_running()

    def get_running_scripts(self) -> List[str]:
        """Get list of running script IDs"""
        return [sid for sid, rt in self.runtimes.items() if rt.is_running()]

    # =========================================================================
    # LIFECYCLE HOOKS
    # =========================================================================

    def on_acquisition_start(self) -> None:
        """Called when acquisition starts - auto-start acquisition scripts"""
        for script in self.scripts.values():
            if script.enabled and script.run_mode == ScriptRunMode.ACQUISITION:
                if not self.is_script_running(script.id):
                    logger.info(f"Auto-starting script with acquisition: {script.name}")
                    self.start_script(script.id)

    def on_acquisition_stop(self) -> None:
        """Called when acquisition stops - stop acquisition scripts"""
        for script in self.scripts.values():
            if script.run_mode == ScriptRunMode.ACQUISITION:
                if self.is_script_running(script.id):
                    logger.info(f"Auto-stopping script with acquisition: {script.name}")
                    self.stop_script(script.id)

    def on_session_start(self) -> None:
        """Called when session starts - auto-start session scripts"""
        for script in self.scripts.values():
            if script.enabled and script.run_mode == ScriptRunMode.SESSION:
                if not self.is_script_running(script.id):
                    logger.info(f"Auto-starting script with session: {script.name}")
                    self.start_script(script.id)

    def on_session_stop(self) -> None:
        """Called when session stops - stop session scripts"""
        for script in self.scripts.values():
            if script.run_mode == ScriptRunMode.SESSION:
                if self.is_script_running(script.id):
                    logger.info(f"Auto-stopping script with session: {script.name}")
                    self.stop_script(script.id)

    # =========================================================================
    # API IMPLEMENTATION (called by ScriptRuntime)
    # =========================================================================

    def get_channel_value(self, name: str) -> float:
        if self.on_get_channel_value:
            return self.on_get_channel_value(name)
        return 0.0

    def get_channel_timestamp(self, name: str) -> float:
        if self.on_get_channel_timestamp:
            return self.on_get_channel_timestamp(name)
        return 0.0

    def get_channel_names(self) -> List[str]:
        if self.on_get_channel_names:
            return self.on_get_channel_names()
        return []

    def has_channel(self, name: str) -> bool:
        if self.on_has_channel:
            return self.on_has_channel(name)
        return False

    def set_output(self, channel: str, value: Any) -> None:
        # Track this channel as script-controlled for session lockout
        self._controlled_outputs.add(channel)
        if self.on_set_output:
            self.on_set_output(channel, value)

    @property
    def controlled_outputs(self) -> Set[str]:
        """Direct access to the set of output channels controlled by scripts.

        Why this property exists:
        - Testing: Allows tests to inject controlled outputs without calling set_output()
        - Inspection: Lets external code check/modify the set directly
        - Consistency: Provides Pythonic property access alongside get_controlled_outputs()

        Note: Returns the actual set (not a copy) for direct manipulation.
        Use get_controlled_outputs() if you need a safe copy.
        """
        return self._controlled_outputs

    def get_controlled_outputs(self) -> Set[str]:
        """Get a COPY of the controlled outputs set (safe for iteration).
        Used by DAQ service to implement selective session lockout."""
        return self._controlled_outputs.copy()

    def clear_controlled_outputs(self) -> None:
        """Clear the controlled outputs tracking. Called when session ends."""
        self._controlled_outputs.clear()
        logger.debug("Cleared controlled outputs tracking")

    def start_acquisition(self) -> None:
        if self.on_start_acquisition:
            self.on_start_acquisition()

    def stop_acquisition(self) -> None:
        if self.on_stop_acquisition:
            self.on_stop_acquisition()

    def start_recording(self, filename: Optional[str] = None) -> None:
        if self.on_start_recording:
            self.on_start_recording(filename)

    def stop_recording(self) -> None:
        if self.on_stop_recording:
            self.on_stop_recording()

    def is_session_active(self) -> bool:
        if self.on_is_session_active:
            return self.on_is_session_active()
        return False

    def get_session_elapsed(self) -> float:
        if self.on_get_session_elapsed:
            return self.on_get_session_elapsed()
        return 0.0

    def is_recording(self) -> bool:
        if self.on_is_recording:
            return self.on_is_recording()
        return False

    def get_scan_rate(self) -> float:
        if self.on_get_scan_rate:
            return self.on_get_scan_rate()
        return 10.0  # Default 10 Hz

    def publish_value(self, script_id: str, name: str, value: float, units: str = '') -> None:
        if self.on_publish_value:
            self.on_publish_value(script_id, name, value, units)

    def log_script_output(self, script_id: str, output_type: str, message: str) -> None:
        if self.on_script_output:
            self.on_script_output(script_id, output_type, message)
        logger.debug(f"Script {script_id}: {message}")

    def _on_script_error(self, script: Script, error: str) -> None:
        """Called when a script encounters an error"""
        self._emit_event('error', script)

    def _emit_event(self, event_type: str, script: Script) -> None:
        """Emit a script event"""
        if self.on_script_event:
            try:
                self.on_script_event(event_type, script)
            except Exception as e:
                logger.error(f"Error in script event handler: {e}")

    # =========================================================================
    # STATUS
    # =========================================================================

    def get_status(self) -> dict:
        """Get script manager status"""
        running = self.get_running_scripts()
        return {
            "script_count": len(self.scripts),
            "running_count": len(running),
            "running_scripts": running,
            "scripts": {sid: s.to_dict() for sid, s in self.scripts.items()}
        }

    def shutdown(self) -> None:
        """Shutdown the script manager"""
        self.stop_all_scripts()
        logger.info("ScriptManager shutdown")
