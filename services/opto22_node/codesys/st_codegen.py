"""
Structured Text Code Generator for CODESYS

Generates IEC 61131-3 Structured Text programs from ICCSFlux project
configuration. Output is human-readable, AI-debuggable ST code that
runs on the groov EPIC CODESYS runtime.

Usage:
    codegen = STCodeGenerator()
    codegen.add_pid_loops(pid_config)
    codegen.add_interlocks(interlock_config)
    codegen.add_channels(channel_config)
    files = codegen.generate()
    # files = {'Main.st': '...', 'FB_PID_Loop.st': '...', 'GVL_Registers.st': '...'}
"""

import hashlib
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .register_map import (
    RegisterMap,
    HOLD_SYSTEM_CMD_BASE, INPUT_SYSTEM_STATUS_BASE,
)

logger = logging.getLogger('Opto22Node.CODESYS')

TEMPLATE_DIR = Path(__file__).parent / 'templates'

# Try Jinja2 for template rendering; fall back to string formatting
try:
    import jinja2
    JINJA2_AVAILABLE = True
except ImportError:
    JINJA2_AVAILABLE = False
    logger.info("Jinja2 not available — using built-in template rendering")


@dataclass
class PIDLoopConfig:
    """PID loop configuration for ST code generation."""
    id: str
    name: str
    pv_channel: str
    cv_channel: Optional[str] = None
    description: str = ""
    kp: float = 1.0
    ki: float = 0.1
    kd: float = 0.0
    output_min: float = 0.0
    output_max: float = 100.0
    reverse_action: bool = False
    deadband: float = 0.0

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PIDLoopConfig':
        loop_id = data.get('id') or data.get('name', 'unnamed')
        return cls(
            id=loop_id,
            name=data.get('name', loop_id),
            pv_channel=data.get('pv_channel', ''),
            cv_channel=data.get('cv_channel'),
            description=data.get('description', ''),
            kp=data.get('kp', 1.0),
            ki=data.get('ki', 0.1),
            kd=data.get('kd', 0.0),
            output_min=data.get('output_min', 0.0),
            output_max=data.get('output_max', 100.0),
            reverse_action=data.get('reverse_action', False),
            deadband=data.get('deadband', 0.0),
        )


@dataclass
class InterlockConfig:
    """Interlock configuration for ST code generation."""
    id: str
    name: str
    description: str = ""
    conditions: List[Dict[str, Any]] = field(default_factory=list)
    controlled_outputs: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'InterlockConfig':
        controls = data.get('controls', [])
        outputs = []
        for ctrl in controls:
            ch = ctrl.get('channel') or ctrl.get('channelName', '')
            if ch:
                outputs.append(ch)
        ilk_id = data.get('id') or data.get('name', 'unnamed')
        return cls(
            id=ilk_id,
            name=data.get('name', ilk_id),
            description=data.get('description', ''),
            conditions=data.get('conditions', []),
            controlled_outputs=outputs,
        )

    def condition_to_st(self, channel_pv_map: Dict[str, str]) -> str:
        """Convert interlock conditions to a Structured Text boolean expression.

        Args:
            channel_pv_map: Maps channel names to their GVL PV variable name
                            e.g. {'TC_Feed': 'GVL_Registers.PV_TC_Feed'}
        """
        if not self.conditions:
            return 'TRUE'  # No conditions = always safe

        parts = []
        for cond in self.conditions:
            cond_type = cond.get('type', cond.get('conditionType', ''))
            channel = cond.get('channel', cond.get('channelName', ''))
            operator = cond.get('operator', '<')
            value = cond.get('value', cond.get('threshold', 0))

            if cond_type in ('channel_value', 'channelValue'):
                pv_var = channel_pv_map.get(channel, f'GVL_Registers.PV_{channel}')
                st_op = _operator_to_st(operator)
                parts.append(f'({pv_var} {st_op} {_format_real(value)})')
            elif cond_type == 'digital_input':
                pv_var = channel_pv_map.get(channel, f'GVL_Registers.PV_{channel}')
                expected = cond.get('expectedState', True)
                if expected:
                    parts.append(f'({pv_var} > 0.5)')
                else:
                    parts.append(f'({pv_var} < 0.5)')
            else:
                # Condition types not expressible in ST (alarm_active, mqtt_connected, etc.)
                # These stay in the Python layer — use TRUE as placeholder
                parts.append('TRUE')

        logic = cond.get('logic', 'AND') if self.conditions else 'AND'
        # Default to AND logic (all conditions must be met for "safe")
        joiner = ' AND '
        return joiner.join(parts) if parts else 'TRUE'


@dataclass
class ChannelInfo:
    """Channel information for ST code generation."""
    name: str
    channel_type: str
    description: str = ""
    io_path: str = ""  # groov I/O variable path (e.g., GRV_EPIC_PR1.Slot01.Ch00)
    groov_module_index: Optional[int] = None
    groov_channel_index: Optional[int] = None
    safe_value: float = 0.0
    pid_cv: Optional[str] = None  # PID loop ID if this output is driven by a PID

    @property
    def is_output(self) -> bool:
        return self.channel_type in (
            'voltage_output', 'current_output', 'digital_output',
            'analog_output',
        )

    def get_io_path(self) -> str:
        """Get the CODESYS I/O variable path for this channel."""
        if self.io_path:
            return self.io_path
        # Generate a default path from module/channel indices
        if self.groov_module_index is not None and self.groov_channel_index is not None:
            return f'GRV_EPIC_PR1.Slot{self.groov_module_index:02d}.Ch{self.groov_channel_index:02d}'
        return f'(* TODO: assign I/O path for {self.name} *) 0.0'


def _operator_to_st(op: str) -> str:
    """Convert Python operator string to ST operator."""
    return {
        '<': '<', '<=': '<=', '>': '>', '>=': '>=',
        '==': '=', '!=': '<>',
        'lt': '<', 'lte': '<=', 'gt': '>', 'gte': '>=',
        'eq': '=', 'ne': '<>',
    }.get(op, '<')


def _format_real(value: float) -> str:
    """Format a float for ST code (always include decimal point)."""
    s = f'{value:.4f}'.rstrip('0').rstrip('.')
    if '.' not in s:
        s += '.0'
    return s


class STCodeGenerator:
    """Generates IEC 61131-3 Structured Text from ICCSFlux project config.

    The generated code includes:
    - FB_PID_Loop.st: PID controller function block
    - FB_Interlock.st: IEC 61511 interlock function block
    - FB_SafeState.st: Safe state manager
    - GVL_Registers.st: Global variable list with Modbus mapping
    - Main.st: Main program wiring I/O → PID → interlocks → outputs
    """

    def __init__(self, project_name: str = "ICCSFlux Project"):
        self.project_name = project_name
        self._pid_loops: List[PIDLoopConfig] = []
        self._interlocks: List[InterlockConfig] = []
        self._channels: List[ChannelInfo] = []
        self._register_map = RegisterMap()

    def add_pid_loops(self, loops: List[Dict[str, Any]]):
        """Add PID loop configurations."""
        for data in loops:
            self._pid_loops.append(PIDLoopConfig.from_dict(data))

    def add_interlocks(self, interlocks: List[Dict[str, Any]]):
        """Add interlock configurations."""
        for data in interlocks:
            self._interlocks.append(InterlockConfig.from_dict(data))

    def add_channels(self, channels: Dict[str, Dict[str, Any]]):
        """Add channel configurations.

        Args:
            channels: Dict mapping channel name to config dict
        """
        for name, data in channels.items():
            ch = ChannelInfo(
                name=name,
                channel_type=data.get('channel_type', 'voltage_input'),
                description=data.get('description', ''),
                io_path=data.get('io_path', ''),
                groov_module_index=data.get('groov_module_index'),
                groov_channel_index=data.get('groov_channel_index'),
                safe_value=data.get('safe_value', data.get('default_value', 0.0)),
            )
            # Check if any PID loop outputs to this channel
            for loop in self._pid_loops:
                if loop.cv_channel == name:
                    ch.pid_cv = loop.id
            self._channels.append(ch)

    def _allocate_registers(self):
        """Allocate register map from current configuration."""
        self._register_map = RegisterMap()
        self._register_map.allocate_pid_loops([l.id for l in self._pid_loops])
        self._register_map.allocate_interlocks([i.id for i in self._interlocks])
        self._register_map.allocate_channels([c.name for c in self._channels])
        output_names = [c.name for c in self._channels if c.is_output]
        self._register_map.allocate_outputs(output_names)

    def _config_hash(self) -> str:
        """Generate a short hash of the configuration for version tracking."""
        data = f"{self.project_name}:{len(self._pid_loops)}:{len(self._interlocks)}:{len(self._channels)}"
        for l in self._pid_loops:
            data += f":{l.id}:{l.pv_channel}"
        return hashlib.md5(data.encode()).hexdigest()[:8]

    def get_register_map(self) -> RegisterMap:
        """Get the allocated register map."""
        if not self._register_map.pid_loops and self._pid_loops:
            self._allocate_registers()
        return self._register_map

    def generate(self) -> Dict[str, str]:
        """Generate all ST files.

        Returns dict mapping filename to file contents:
            {'Main.st': '...', 'FB_PID_Loop.st': '...', ...}
        """
        self._allocate_registers()
        now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        config_hash = self._config_hash()

        files = {}

        # Static function blocks (read from templates directory)
        for fb_name in ['fb_pid_loop', 'fb_interlock', 'fb_safe_state']:
            template_path = TEMPLATE_DIR / f'{fb_name}.st.j2'
            if template_path.exists():
                files[f'{_fb_filename(fb_name)}.st'] = template_path.read_text(encoding='utf-8')

        # GVL_Registers (templated with register allocations)
        files['GVL_Registers.st'] = self._render_gvl(now, config_hash)

        # Main program (templated with project-specific wiring)
        files['Main.st'] = self._render_main(now, config_hash)

        return files

    def generate_to_dir(self, output_dir: str) -> List[str]:
        """Generate ST files and write to a directory.

        Returns list of written file paths.
        """
        os.makedirs(output_dir, exist_ok=True)
        files = self.generate()
        written = []
        for filename, content in files.items():
            path = os.path.join(output_dir, filename)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            written.append(path)
            logger.info(f"Generated: {path}")
        return written

    # =========================================================================
    # TEMPLATE RENDERING
    # =========================================================================

    def _render_gvl(self, timestamp: str, config_hash: str) -> str:
        """Render the GVL_Registers template."""
        pid_data = []
        for loop in self._pid_loops:
            regs = self._register_map.get_pid_registers(loop.id)
            if not regs:
                continue
            pid_data.append({
                'id': loop.id,
                'name': loop.name,
                'kp': loop.kp, 'ki': loop.ki, 'kd': loop.kd,
                'sp_address': regs.sp_address,
                'sp_offset': (regs.sp_address - 40001) * 2,
                'kp_address': regs.kp_address,
                'kp_offset': (regs.kp_address - 40001) * 2,
                'ki_address': regs.ki_address,
                'ki_offset': (regs.ki_address - 40001) * 2,
                'kd_address': regs.kd_address,
                'kd_offset': (regs.kd_address - 40001) * 2,
                'cv_address': regs.cv_address,
                'cv_offset': (regs.cv_address - 30001) * 2,
            })

        ch_data = []
        for ch in self._channels:
            regs = self._register_map.get_channel_registers(ch.name)
            if not regs:
                continue
            ch_data.append({
                'name': ch.name,
                'description': ch.description or ch.channel_type,
                'pv_address': regs.pv_address,
                'pv_offset': (regs.pv_address - 30001) * 2,
            })

        ilk_data = []
        for ilk in self._interlocks:
            regs = self._register_map.get_interlock_registers(ilk.id)
            if not regs:
                continue
            ilk_data.append({
                'id': ilk.id,
                'arm_coil': regs.arm_coil,
                'arm_byte': (regs.arm_coil - 1) // 8,
                'arm_bit': (regs.arm_coil - 1) % 8,
                'bypass_coil': regs.bypass_coil,
                'bypass_byte': (regs.bypass_coil - 1) // 8,
                'bypass_bit': (regs.bypass_coil - 1) % 8,
                'status_address': regs.status_address,
                'status_offset': (regs.status_address - 30001) * 2,
                'trip_count_address': regs.trip_count_address,
                'trips_offset': (regs.trip_count_address - 30001) * 2,
                'tripped_discrete': regs.tripped_discrete,
                'tripped_byte': (regs.tripped_discrete - 10001) // 8,
                'tripped_bit': (regs.tripped_discrete - 10001) % 8,
            })

        out_data = []
        for ch in self._channels:
            if not ch.is_output:
                continue
            regs = self._register_map.get_output_registers(ch.name)
            if not regs:
                continue
            out_data.append({
                'name': ch.name,
                'override_address': regs.override_address,
                'override_offset': (regs.override_address - 40001) * 2,
            })

        sys_cmd_offset = (HOLD_SYSTEM_CMD_BASE - 40001) * 2
        sys_status_offset = (INPUT_SYSTEM_STATUS_BASE - 30001) * 2

        context = {
            'project_name': self.project_name,
            'timestamp': timestamp,
            'config_hash': config_hash,
            'pid_loops': pid_data,
            'channels': ch_data,
            'interlocks': ilk_data,
            'outputs': out_data,
            'sys_cmd_offset': sys_cmd_offset,
            'sys_status_offset': sys_status_offset,
        }

        return self._render_template('gvl_registers.st.j2', context)

    def _render_main(self, timestamp: str, config_hash: str) -> str:
        """Render the Main program template."""
        # Build channel PV variable map for interlock condition conversion
        ch_pv_map = {}
        for ch in self._channels:
            ch_pv_map[ch.name] = f'GVL_Registers.PV_{ch.name}'

        pid_data = []
        for loop in self._pid_loops:
            pid_data.append({
                'id': loop.id,
                'name': loop.name,
                'description': loop.description,
                'pv_channel': loop.pv_channel,
                'output_min': _format_real(loop.output_min),
                'output_max': _format_real(loop.output_max),
                'reverse_action': loop.reverse_action,
                'deadband': _format_real(loop.deadband),
            })

        ilk_data = []
        for ilk in self._interlocks:
            ilk_data.append({
                'id': ilk.id,
                'name': ilk.name,
                'description': ilk.description,
                'condition_st': ilk.condition_to_st(ch_pv_map),
                'controlled_outputs': ilk.controlled_outputs,
            })

        input_channels = [ch for ch in self._channels if not ch.is_output]
        output_channels = [ch for ch in self._channels if ch.is_output]

        input_data = [{
            'name': ch.name,
            'description': ch.description or ch.channel_type,
            'io_path': ch.get_io_path(),
        } for ch in input_channels]

        output_data = [{
            'name': ch.name,
            'description': ch.description or ch.channel_type,
            'io_path': ch.get_io_path(),
            'safe_value': _format_real(ch.safe_value),
            'pid_cv': ch.pid_cv,
        } for ch in output_channels]

        context = {
            'project_name': self.project_name,
            'timestamp': timestamp,
            'config_hash': config_hash,
            'pid_loops': pid_data,
            'interlocks': ilk_data,
            'input_channels': input_data,
            'output_channels': output_data,
        }

        return self._render_template('main_program.st.j2', context)

    def _render_template(self, template_name: str, context: Dict[str, Any]) -> str:
        """Render a Jinja2 template with the given context.

        Falls back to built-in string replacement if Jinja2 is not available.
        """
        template_path = TEMPLATE_DIR / template_name
        if not template_path.exists():
            logger.error(f"Template not found: {template_path}")
            return f'(* ERROR: Template {template_name} not found *)'

        if JINJA2_AVAILABLE:
            env = jinja2.Environment(
                loader=jinja2.FileSystemLoader(str(TEMPLATE_DIR)),
                trim_blocks=True,
                lstrip_blocks=True,
                keep_trailing_newline=True,
            )
            template = env.get_template(template_name)
            return template.render(**context)
        else:
            return self._render_template_builtin(template_path, context)

    def _render_template_builtin(self, template_path: Path, context: Dict[str, Any]) -> str:
        """Minimal template rendering without Jinja2.

        Handles basic {{ var }} substitution and {% for %} loops.
        Good enough for generating readable ST code without dependencies.
        """
        content = template_path.read_text(encoding='utf-8')

        # Simple variable substitution for non-loop context
        for key, value in context.items():
            if isinstance(value, (str, int, float)):
                content = content.replace('{{ ' + key + ' }}', str(value))

        # For complex templates with loops, generate the output sections manually
        # This is a simplified renderer — Jinja2 is preferred for production
        if '{% for' in content:
            logger.warning(f"Template {template_path.name} uses loops but Jinja2 is not available. "
                           "Install jinja2 for full template support: pip install jinja2")
            # Return a stub with header info
            header = (
                f"(* ICCSFlux CODESYS Program\n"
                f"   Project: {context.get('project_name', 'Unknown')}\n"
                f"   Generated: {context.get('timestamp', 'Unknown')}\n"
                f"   NOTE: Install jinja2 for full code generation *)\n"
            )
            return header

        return content


def _fb_filename(template_name: str) -> str:
    """Convert template name to CODESYS file name."""
    return {
        'fb_pid_loop': 'FB_PID_Loop',
        'fb_interlock': 'FB_Interlock',
        'fb_safe_state': 'FB_SafeState',
    }.get(template_name, template_name)
