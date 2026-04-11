"""
ProjectContext — Holds all per-project state for multi-project concurrent support.

Each loaded project gets its own ProjectContext with isolated manager instances
for recording, alarms, safety, scripts, sequences, triggers, variables, PID, etc.
The DAQ service maintains a dict of active ProjectContexts keyed by project_id.
"""

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, Set

from config_parser import NISystemConfig, ChannelConfig
from state_machine import DAQStateMachine, DAQState
from recording_manager import RecordingManager
from alarm_manager import AlarmManager
from safety_manager import SafetyManager
from script_manager import ScriptManager
from sequence_manager import SequenceManager
from trigger_engine import TriggerEngine
from watchdog_engine import WatchdogEngine
from user_variables import UserVariableManager
from pid_engine import PIDEngine

logger = logging.getLogger('DAQService')


@dataclass
class ProjectContext:
    """Holds all per-project state for concurrent multi-project operation.

    Each project loaded into the station gets its own context with independent:
    - State machine (acquisition lifecycle)
    - Recording manager (separate directory)
    - Alarm manager
    - Safety manager (interlocks)
    - Script manager
    - Sequence manager
    - Trigger engine
    - Watchdog engine
    - User variable manager
    - PID engine
    - Channel values (filtered to this project's channels)
    """
    # Identity
    project_id: str
    project_path: Path
    project_data: Dict[str, Any]
    project_name: str = ""
    color_index: int = 0  # For frontend visual differentiation (0-7)

    # Configuration (parsed from project JSON)
    config: Optional[NISystemConfig] = None

    # Per-project state machine
    state_machine: Optional[DAQStateMachine] = None

    # Per-project managers (initialized by DAQ service)
    recording_manager: Optional[RecordingManager] = None
    alarm_manager: Optional[AlarmManager] = None
    safety_manager: Optional[SafetyManager] = None
    script_manager: Optional[ScriptManager] = None
    sequence_manager: Optional[SequenceManager] = None
    trigger_engine: Optional[TriggerEngine] = None
    watchdog_engine: Optional[WatchdogEngine] = None
    user_variables: Optional[UserVariableManager] = None
    pid_engine: Optional[PIDEngine] = None

    # Per-project channel values (populated during scan loop)
    channel_values: Dict[str, Any] = field(default_factory=dict)
    channel_timestamps: Dict[str, float] = field(default_factory=dict)
    channel_acquisition_ts_us: Dict[str, int] = field(default_factory=dict)

    # Per-project safety state
    safety_triggered: Dict[str, bool] = field(default_factory=dict)
    alarms_active: Dict[str, str] = field(default_factory=dict)

    # Thread safety
    values_lock: threading.Lock = field(default_factory=threading.Lock)
    safety_lock: threading.Lock = field(default_factory=threading.Lock)

    # Metadata
    loaded_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        if not self.project_name:
            self.project_name = self.project_data.get('name', self.project_id)
        if self.state_machine is None:
            self.state_machine = DAQStateMachine(DAQState.STOPPED)

    @property
    def channel_names(self) -> Set[str]:
        """Get the set of channel names belonging to this project."""
        if self.config and self.config.channels:
            return set(self.config.channels.keys())
        return set()

    @property
    def acquiring(self) -> bool:
        """Whether this project is currently acquiring data."""
        return self.state_machine.state == DAQState.RUNNING if self.state_machine else False

    @property
    def recording(self) -> bool:
        """Whether this project is currently recording data."""
        return self.recording_manager.recording if self.recording_manager else False

    def get_channel_conflicts(self, other_contexts: 'Dict[str, ProjectContext]') -> Dict[str, list]:
        """Detect physical channel conflicts with other loaded projects.

        Returns:
            Dict mapping physical_channel -> list of project_ids that also use it
        """
        conflicts: Dict[str, list] = {}
        if not self.config or not self.config.channels:
            return conflicts

        my_physicals: Dict[str, str] = {}  # physical_channel -> channel_name
        for name, ch in self.config.channels.items():
            phys = getattr(ch, 'physical_channel', None)
            if phys:
                my_physicals[phys] = name

        for other_id, other_ctx in other_contexts.items():
            if other_id == self.project_id:
                continue
            if not other_ctx.config or not other_ctx.config.channels:
                continue
            for other_name, other_ch in other_ctx.config.channels.items():
                other_phys = getattr(other_ch, 'physical_channel', None)
                if other_phys and other_phys in my_physicals:
                    if other_phys not in conflicts:
                        conflicts[other_phys] = []
                    conflicts[other_phys].append(other_id)

        return conflicts

    def teardown(self):
        """Stop all managers and clean up resources for this project."""
        logger.info(f"Tearing down project context: {self.project_id}")

        # Stop acquisition if running
        if self.state_machine and self.state_machine.state != DAQState.STOPPED:
            self.state_machine.force_state(DAQState.STOPPED)

        # Stop recording
        if self.recording_manager and self.recording_manager.recording:
            try:
                self.recording_manager.stop()
            except Exception as e:
                logger.warning(f"Error stopping recording for {self.project_id}: {e}")

        # Stop scripts
        if self.script_manager:
            try:
                self.script_manager.stop_all_scripts()
            except Exception as e:
                logger.warning(f"Error stopping scripts for {self.project_id}: {e}")

        # Stop sequences
        if self.sequence_manager:
            try:
                self.sequence_manager.stop_all()
            except Exception as e:
                logger.warning(f"Error stopping sequences for {self.project_id}: {e}")

        # Clear safety
        if self.safety_manager:
            try:
                self.safety_manager.clear_all()
            except Exception as e:
                logger.warning(f"Error clearing safety for {self.project_id}: {e}")

        # Clear alarms
        if self.alarm_manager:
            try:
                self.alarm_manager.clear_all(clear_configs=True)
            except Exception as e:
                logger.warning(f"Error clearing alarms for {self.project_id}: {e}")

        logger.info(f"Project context torn down: {self.project_id}")

    def to_summary(self) -> Dict[str, Any]:
        """Return a summary dict for MQTT publishing / station management UI."""
        conflicts = {}  # populated by caller with other contexts
        return {
            'projectId': self.project_id,
            'projectName': self.project_name,
            'projectPath': str(self.project_path),
            'status': self.state_machine.state.name if self.state_machine else 'unknown',
            'acquiring': self.acquiring,
            'recording': self.recording,
            'channelCount': len(self.channel_names),
            'channelConflicts': conflicts,
            'colorIndex': self.color_index,
            'loadedAt': self.loaded_at.isoformat(),
        }
