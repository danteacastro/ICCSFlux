"""
Modbus Register Map for CODESYS ↔ Python Communication

Defines the register address allocation contract between the CODESYS runtime
(PLC control layer) and the Python companion (intelligence layer) on groov EPIC.

Communication runs over Modbus TCP on localhost:502.

Register Regions:
    Holding Registers (4xxxx) — Python writes, CODESYS reads:
        40001-40100: PID setpoints (float32, 2 regs each → up to 50 loops)
        40101-40400: PID tuning (Kp, Ki, Kd triplets, float32 each → 50 loops)
        40401-40500: Interlock commands (arm/bypass/reset packed per interlock)
        40501-40600: Output override values (float32 → 50 outputs)
        40601-40610: System commands (E-stop, mode select, heartbeat counter)

    Input Registers (3xxxx) — CODESYS writes, Python reads:
        30001-30100: PID outputs / CV values (float32 → 50 loops)
        30101-30300: Process values from I/O (float32 → 100 channels)
        30301-30400: Interlock status (state + trip count per interlock)
        30401-30410: System status (scan time, error count, watchdog)

    Coils (0xxxx) — Python writes single bits:
        00001-00050: PID loop enable flags
        00051-00100: PID manual mode flags
        00101-00150: Interlock arm commands
        00151-00200: Interlock bypass flags

    Discrete Inputs (1xxxx) — CODESYS writes single bits:
        10001-10050: Interlock tripped flags
        10051-10100: PID loop active flags
        10101-10110: System health flags
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger('Opto22Node.CODESYS')

# =============================================================================
# REGISTER BASE ADDRESSES (Modbus convention: 4xxxx, 3xxxx, 0xxxx, 1xxxx)
# =============================================================================

# Holding registers — Python → CODESYS
HOLD_PID_SP_BASE = 40001          # Setpoints (float32 = 2 regs each)
HOLD_PID_TUNING_BASE = 40101     # Kp/Ki/Kd triplets (6 regs per loop)
HOLD_INTERLOCK_CMD_BASE = 40401  # Interlock commands (2 regs per interlock)
HOLD_OUTPUT_OVERRIDE_BASE = 40501  # Output override values (float32)
HOLD_SYSTEM_CMD_BASE = 40601     # System commands

# Input registers — CODESYS → Python
INPUT_PID_CV_BASE = 30001        # PID control variable outputs
INPUT_PV_BASE = 30101            # Process values (all channels)
INPUT_INTERLOCK_STATUS_BASE = 30301  # Interlock state + trip count
INPUT_SYSTEM_STATUS_BASE = 30401     # System diagnostics

# Coils — Python → CODESYS (single bits)
COIL_PID_ENABLE_BASE = 1         # PID loop enable flags
COIL_PID_MANUAL_BASE = 51        # PID manual mode flags
COIL_INTERLOCK_ARM_BASE = 101    # Interlock arm commands
COIL_INTERLOCK_BYPASS_BASE = 151  # Interlock bypass flags

# Discrete inputs — CODESYS → Python (single bits)
DISC_INTERLOCK_TRIPPED_BASE = 10001  # Interlock tripped state
DISC_PID_ACTIVE_BASE = 10051        # PID loop active
DISC_SYSTEM_HEALTH_BASE = 10101     # System health flags

# Limits
MAX_PID_LOOPS = 50
MAX_INTERLOCKS = 50
MAX_CHANNELS = 100
MAX_OUTPUTS = 50

# System command register offsets (from HOLD_SYSTEM_CMD_BASE)
SYSCMD_ESTOP = 0                 # Emergency stop (uint16: 0=normal, 1=estop)
SYSCMD_MODE = 1                  # Mode select (uint16: 0=auto, 1=manual, 2=safe)
SYSCMD_HEARTBEAT = 2             # Heartbeat counter (uint16, wraps at 65535)
SYSCMD_ACQUIRE = 3               # Acquisition state (uint16: 0=stop, 1=run)
SYSCMD_CONFIG_VERSION = 4        # Config version hash (uint16, lower 16 bits)

# System status register offsets (from INPUT_SYSTEM_STATUS_BASE)
SYSSTATUS_SCAN_TIME_US = 0       # Last scan time in microseconds (uint32, 2 regs)
SYSSTATUS_ERROR_COUNT = 2        # Cumulative error count (uint16)
SYSSTATUS_WATCHDOG = 3           # Watchdog counter (uint16, increments each scan)
SYSSTATUS_PID_COUNT = 4          # Active PID loop count
SYSSTATUS_INTERLOCK_COUNT = 5    # Active interlock count

@dataclass
class PIDRegisterBlock:
    """Register addresses for one PID loop."""
    index: int
    sp_address: int          # Setpoint (float32, 2 regs)
    kp_address: int          # Proportional gain (float32, 2 regs)
    ki_address: int          # Integral gain (float32, 2 regs)
    kd_address: int          # Derivative gain (float32, 2 regs)
    cv_address: int          # Control variable output (float32, 2 regs)
    enable_coil: int         # Enable flag (coil)
    manual_coil: int         # Manual mode flag (coil)
    active_discrete: int     # Active status (discrete input)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'index': self.index,
            'sp_address': self.sp_address,
            'kp_address': self.kp_address,
            'ki_address': self.ki_address,
            'kd_address': self.kd_address,
            'cv_address': self.cv_address,
            'enable_coil': self.enable_coil,
            'manual_coil': self.manual_coil,
            'active_discrete': self.active_discrete,
        }

@dataclass
class InterlockRegisterBlock:
    """Register addresses for one interlock."""
    index: int
    cmd_address: int          # Command register (uint16: packed bits)
    status_address: int       # Status register (uint16: state enum)
    trip_count_address: int   # Trip count (uint16)
    arm_coil: int             # Arm command (coil)
    bypass_coil: int          # Bypass flag (coil)
    tripped_discrete: int     # Tripped status (discrete input)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'index': self.index,
            'cmd_address': self.cmd_address,
            'status_address': self.status_address,
            'trip_count_address': self.trip_count_address,
            'arm_coil': self.arm_coil,
            'bypass_coil': self.bypass_coil,
            'tripped_discrete': self.tripped_discrete,
        }

@dataclass
class ChannelRegisterBlock:
    """Register addresses for one I/O channel process value."""
    index: int
    name: str
    pv_address: int           # Process value (float32, 2 regs in input registers)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'index': self.index,
            'name': self.name,
            'pv_address': self.pv_address,
        }

@dataclass
class OutputRegisterBlock:
    """Register addresses for one output override."""
    index: int
    name: str
    override_address: int     # Override value (float32, 2 regs in holding registers)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'index': self.index,
            'name': self.name,
            'override_address': self.override_address,
        }

class RegisterMap:
    """Manages Modbus register allocation for CODESYS ↔ Python communication.

    Given a project's PID loops, interlocks, and channels, allocates concrete
    register addresses and generates the tag map for CODESYSBridge.

    Usage:
        rmap = RegisterMap()
        rmap.allocate_pid_loops(['PID_Zone1', 'PID_Zone2'])
        rmap.allocate_interlocks(['ILK_OverTemp', 'ILK_Pressure'])
        rmap.allocate_channels(['TC_Feed', 'PT_Inlet', 'Valve_01'])
        rmap.allocate_outputs(['Heater_01', 'Valve_01'])

        # Get register block for a specific PID loop
        pid_regs = rmap.get_pid_registers('PID_Zone1')

        # Generate tag_map dict for CODESYSBridge
        tag_map = rmap.generate_tag_map()
    """

    def __init__(self):
        self._pid_loops: Dict[str, PIDRegisterBlock] = {}
        self._interlocks: Dict[str, InterlockRegisterBlock] = {}
        self._channels: Dict[str, ChannelRegisterBlock] = {}
        self._outputs: Dict[str, OutputRegisterBlock] = {}

    # =========================================================================
    # ALLOCATION
    # =========================================================================

    def allocate_pid_loops(self, loop_ids: List[str]):
        """Allocate registers for PID loops."""
        for i, loop_id in enumerate(loop_ids):
            if i >= MAX_PID_LOOPS:
                logger.warning(f"PID loop limit ({MAX_PID_LOOPS}) reached, skipping {loop_id}")
                break
            self._pid_loops[loop_id] = PIDRegisterBlock(
                index=i,
                sp_address=HOLD_PID_SP_BASE + (i * 2),
                kp_address=HOLD_PID_TUNING_BASE + (i * 6),
                ki_address=HOLD_PID_TUNING_BASE + (i * 6) + 2,
                kd_address=HOLD_PID_TUNING_BASE + (i * 6) + 4,
                cv_address=INPUT_PID_CV_BASE + (i * 2),
                enable_coil=COIL_PID_ENABLE_BASE + i,
                manual_coil=COIL_PID_MANUAL_BASE + i,
                active_discrete=DISC_PID_ACTIVE_BASE + i,
            )

    def allocate_interlocks(self, interlock_ids: List[str]):
        """Allocate registers for interlocks."""
        for i, ilk_id in enumerate(interlock_ids):
            if i >= MAX_INTERLOCKS:
                logger.warning(f"Interlock limit ({MAX_INTERLOCKS}) reached, skipping {ilk_id}")
                break
            self._interlocks[ilk_id] = InterlockRegisterBlock(
                index=i,
                cmd_address=HOLD_INTERLOCK_CMD_BASE + (i * 2),
                status_address=INPUT_INTERLOCK_STATUS_BASE + (i * 2),
                trip_count_address=INPUT_INTERLOCK_STATUS_BASE + (i * 2) + 1,
                arm_coil=COIL_INTERLOCK_ARM_BASE + i,
                bypass_coil=COIL_INTERLOCK_BYPASS_BASE + i,
                tripped_discrete=DISC_INTERLOCK_TRIPPED_BASE + i,
            )

    def allocate_channels(self, channel_names: List[str]):
        """Allocate input registers for channel process values."""
        for i, name in enumerate(channel_names):
            if i >= MAX_CHANNELS:
                logger.warning(f"Channel limit ({MAX_CHANNELS}) reached, skipping {name}")
                break
            self._channels[name] = ChannelRegisterBlock(
                index=i,
                name=name,
                pv_address=INPUT_PV_BASE + (i * 2),
            )

    def allocate_outputs(self, output_names: List[str]):
        """Allocate holding registers for output override values."""
        for i, name in enumerate(output_names):
            if i >= MAX_OUTPUTS:
                logger.warning(f"Output limit ({MAX_OUTPUTS}) reached, skipping {name}")
                break
            self._outputs[name] = OutputRegisterBlock(
                index=i,
                name=name,
                override_address=HOLD_OUTPUT_OVERRIDE_BASE + (i * 2),
            )

    # =========================================================================
    # LOOKUPS
    # =========================================================================

    def get_pid_registers(self, loop_id: str) -> Optional[PIDRegisterBlock]:
        return self._pid_loops.get(loop_id)

    def get_interlock_registers(self, ilk_id: str) -> Optional[InterlockRegisterBlock]:
        return self._interlocks.get(ilk_id)

    def get_channel_registers(self, name: str) -> Optional[ChannelRegisterBlock]:
        return self._channels.get(name)

    def get_output_registers(self, name: str) -> Optional[OutputRegisterBlock]:
        return self._outputs.get(name)

    @property
    def pid_loops(self) -> Dict[str, PIDRegisterBlock]:
        return dict(self._pid_loops)

    @property
    def interlocks(self) -> Dict[str, InterlockRegisterBlock]:
        return dict(self._interlocks)

    @property
    def channels(self) -> Dict[str, ChannelRegisterBlock]:
        return dict(self._channels)

    @property
    def outputs(self) -> Dict[str, OutputRegisterBlock]:
        return dict(self._outputs)

    # =========================================================================
    # TAG MAP GENERATION (for CODESYSBridge)
    # =========================================================================

    def generate_tag_map(self) -> Dict[str, Dict[str, Any]]:
        """Generate a tag_map dict compatible with CODESYSBridge.

        Returns a dict mapping tag names to Modbus register definitions:
            {'PID_Zone1_SP': {'register': 40001, 'type': 'float32', 'writable': True}, ...}
        """
        tag_map: Dict[str, Dict[str, Any]] = {}

        # PID setpoints (Python writes to CODESYS)
        for loop_id, regs in self._pid_loops.items():
            tag_map[f'{loop_id}_SP'] = {
                'register': regs.sp_address, 'type': 'float32', 'writable': True,
            }
            tag_map[f'{loop_id}_Kp'] = {
                'register': regs.kp_address, 'type': 'float32', 'writable': True,
            }
            tag_map[f'{loop_id}_Ki'] = {
                'register': regs.ki_address, 'type': 'float32', 'writable': True,
            }
            tag_map[f'{loop_id}_Kd'] = {
                'register': regs.kd_address, 'type': 'float32', 'writable': True,
            }
            # PID CV output (CODESYS writes, Python reads)
            tag_map[f'{loop_id}_CV'] = {
                'register': regs.cv_address, 'type': 'float32', 'writable': False,
            }

        # Interlock commands (Python writes)
        for ilk_id, regs in self._interlocks.items():
            tag_map[f'{ilk_id}_CMD'] = {
                'register': regs.cmd_address, 'type': 'uint16', 'writable': True,
            }
            # Interlock status (CODESYS writes)
            tag_map[f'{ilk_id}_STATE'] = {
                'register': regs.status_address, 'type': 'uint16', 'writable': False,
            }
            tag_map[f'{ilk_id}_TRIPS'] = {
                'register': regs.trip_count_address, 'type': 'uint16', 'writable': False,
            }

        # Channel process values (CODESYS writes)
        for name, regs in self._channels.items():
            tag_map[f'{name}_PV'] = {
                'register': regs.pv_address, 'type': 'float32', 'writable': False,
            }

        # Output overrides (Python writes)
        for name, regs in self._outputs.items():
            tag_map[f'{name}_OVR'] = {
                'register': regs.override_address, 'type': 'float32', 'writable': True,
            }

        # System commands (Python writes)
        tag_map['SYS_ESTOP'] = {
            'register': HOLD_SYSTEM_CMD_BASE + SYSCMD_ESTOP,
            'type': 'uint16', 'writable': True,
        }
        tag_map['SYS_MODE'] = {
            'register': HOLD_SYSTEM_CMD_BASE + SYSCMD_MODE,
            'type': 'uint16', 'writable': True,
        }
        tag_map['SYS_HEARTBEAT'] = {
            'register': HOLD_SYSTEM_CMD_BASE + SYSCMD_HEARTBEAT,
            'type': 'uint16', 'writable': True,
        }
        tag_map['SYS_ACQUIRE'] = {
            'register': HOLD_SYSTEM_CMD_BASE + SYSCMD_ACQUIRE,
            'type': 'uint16', 'writable': True,
        }

        # System status (CODESYS writes)
        tag_map['SYS_SCAN_TIME'] = {
            'register': INPUT_SYSTEM_STATUS_BASE + SYSSTATUS_SCAN_TIME_US,
            'type': 'int32', 'writable': False,
        }
        tag_map['SYS_ERRORS'] = {
            'register': INPUT_SYSTEM_STATUS_BASE + SYSSTATUS_ERROR_COUNT,
            'type': 'uint16', 'writable': False,
        }
        tag_map['SYS_WATCHDOG'] = {
            'register': INPUT_SYSTEM_STATUS_BASE + SYSSTATUS_WATCHDOG,
            'type': 'uint16', 'writable': False,
        }

        return tag_map

    # =========================================================================
    # VALIDATION
    # =========================================================================

    def validate(self) -> List[str]:
        """Check for register overlaps or allocation issues.

        Returns list of error messages (empty = valid).
        """
        errors = []

        # Collect all allocated holding register ranges
        holding_ranges = []
        for loop_id, regs in self._pid_loops.items():
            holding_ranges.append((regs.sp_address, regs.sp_address + 1, f'PID SP {loop_id}'))
            holding_ranges.append((regs.kp_address, regs.kp_address + 1, f'PID Kp {loop_id}'))
            holding_ranges.append((regs.ki_address, regs.ki_address + 1, f'PID Ki {loop_id}'))
            holding_ranges.append((regs.kd_address, regs.kd_address + 1, f'PID Kd {loop_id}'))
        for ilk_id, regs in self._interlocks.items():
            holding_ranges.append((regs.cmd_address, regs.cmd_address + 1, f'ILK CMD {ilk_id}'))
        for name, regs in self._outputs.items():
            holding_ranges.append((regs.override_address, regs.override_address + 1, f'OUT {name}'))

        # Check holding register overlaps
        for i, (start_a, end_a, label_a) in enumerate(holding_ranges):
            for j, (start_b, end_b, label_b) in enumerate(holding_ranges):
                if i >= j:
                    continue
                if start_a <= end_b and start_b <= end_a:
                    errors.append(f"Holding register overlap: {label_a} [{start_a}-{end_a}] "
                                  f"vs {label_b} [{start_b}-{end_b}]")

        # Collect input register ranges
        input_ranges = []
        for loop_id, regs in self._pid_loops.items():
            input_ranges.append((regs.cv_address, regs.cv_address + 1, f'PID CV {loop_id}'))
        for name, regs in self._channels.items():
            input_ranges.append((regs.pv_address, regs.pv_address + 1, f'CH PV {name}'))
        for ilk_id, regs in self._interlocks.items():
            input_ranges.append((regs.status_address, regs.status_address, f'ILK STATE {ilk_id}'))
            input_ranges.append((regs.trip_count_address, regs.trip_count_address, f'ILK TRIPS {ilk_id}'))

        # Check input register overlaps
        for i, (start_a, end_a, label_a) in enumerate(input_ranges):
            for j, (start_b, end_b, label_b) in enumerate(input_ranges):
                if i >= j:
                    continue
                if start_a <= end_b and start_b <= end_a:
                    errors.append(f"Input register overlap: {label_a} [{start_a}-{end_a}] "
                                  f"vs {label_b} [{start_b}-{end_b}]")

        return errors

    # =========================================================================
    # SERIALIZATION
    # =========================================================================

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the register map for config push or storage."""
        return {
            'version': '1.0',
            'pid_loops': {k: v.to_dict() for k, v in self._pid_loops.items()},
            'interlocks': {k: v.to_dict() for k, v in self._interlocks.items()},
            'channels': {k: v.to_dict() for k, v in self._channels.items()},
            'outputs': {k: v.to_dict() for k, v in self._outputs.items()},
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'RegisterMap':
        """Deserialize a register map from config."""
        rmap = cls()
        for loop_id, d in data.get('pid_loops', {}).items():
            rmap._pid_loops[loop_id] = PIDRegisterBlock(**d)
        for ilk_id, d in data.get('interlocks', {}).items():
            rmap._interlocks[ilk_id] = InterlockRegisterBlock(**d)
        for name, d in data.get('channels', {}).items():
            rmap._channels[name] = ChannelRegisterBlock(**d)
        for name, d in data.get('outputs', {}).items():
            rmap._outputs[name] = OutputRegisterBlock(**d)
        return rmap
