"""
Unit tests for CODESYS register map and ST code generator.

Tests:
  - Register allocation and address math
  - No register overlaps
  - Tag map generation
  - Serialization/deserialization round-trip
  - ST code generation (with Jinja2)
  - PID loop and interlock config parsing
  - Condition-to-ST conversion

Run: python -m pytest tests/test_codesys_codegen.py -v
"""

import json
import os
import sys
import tempfile

import pytest

# Add project root to path so we can import from services
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'services', 'opto22_node'))

from codesys.register_map import (
    RegisterMap,
    PIDRegisterBlock,
    InterlockRegisterBlock,
    ChannelRegisterBlock,
    OutputRegisterBlock,
    HOLD_PID_SP_BASE,
    HOLD_PID_TUNING_BASE,
    HOLD_INTERLOCK_CMD_BASE,
    HOLD_OUTPUT_OVERRIDE_BASE,
    HOLD_SYSTEM_CMD_BASE,
    INPUT_PID_CV_BASE,
    INPUT_PV_BASE,
    INPUT_INTERLOCK_STATUS_BASE,
    INPUT_SYSTEM_STATUS_BASE,
    COIL_PID_ENABLE_BASE,
    COIL_PID_MANUAL_BASE,
    COIL_INTERLOCK_ARM_BASE,
    COIL_INTERLOCK_BYPASS_BASE,
    DISC_INTERLOCK_TRIPPED_BASE,
    MAX_PID_LOOPS,
    MAX_INTERLOCKS,
    MAX_CHANNELS,
    MAX_OUTPUTS,
)
from codesys.st_codegen import (
    STCodeGenerator,
    PIDLoopConfig,
    InterlockConfig,
    ChannelInfo,
    _operator_to_st,
    _format_real,
)

# =============================================================================
# RegisterMap Tests
# =============================================================================

class TestRegisterMapAllocation:
    """Test register address allocation."""

    def test_allocate_single_pid_loop(self):
        rmap = RegisterMap()
        rmap.allocate_pid_loops(['PID_Zone1'])

        regs = rmap.get_pid_registers('PID_Zone1')
        assert regs is not None
        assert regs.index == 0
        assert regs.sp_address == HOLD_PID_SP_BASE  # 40001
        assert regs.kp_address == HOLD_PID_TUNING_BASE  # 40101
        assert regs.ki_address == HOLD_PID_TUNING_BASE + 2
        assert regs.kd_address == HOLD_PID_TUNING_BASE + 4
        assert regs.cv_address == INPUT_PID_CV_BASE  # 30001
        assert regs.enable_coil == COIL_PID_ENABLE_BASE  # 1
        assert regs.manual_coil == COIL_PID_MANUAL_BASE  # 51

    def test_allocate_multiple_pid_loops(self):
        rmap = RegisterMap()
        rmap.allocate_pid_loops(['PID_Z1', 'PID_Z2', 'PID_Z3'])

        # Verify sequential allocation
        for i, loop_id in enumerate(['PID_Z1', 'PID_Z2', 'PID_Z3']):
            regs = rmap.get_pid_registers(loop_id)
            assert regs.index == i
            assert regs.sp_address == HOLD_PID_SP_BASE + (i * 2)
            assert regs.kp_address == HOLD_PID_TUNING_BASE + (i * 6)
            assert regs.cv_address == INPUT_PID_CV_BASE + (i * 2)

    def test_allocate_interlocks(self):
        rmap = RegisterMap()
        rmap.allocate_interlocks(['ILK_OverTemp', 'ILK_Pressure'])

        regs0 = rmap.get_interlock_registers('ILK_OverTemp')
        regs1 = rmap.get_interlock_registers('ILK_Pressure')

        assert regs0.index == 0
        assert regs0.cmd_address == HOLD_INTERLOCK_CMD_BASE
        assert regs0.status_address == INPUT_INTERLOCK_STATUS_BASE
        assert regs0.arm_coil == COIL_INTERLOCK_ARM_BASE
        assert regs0.bypass_coil == COIL_INTERLOCK_BYPASS_BASE
        assert regs0.tripped_discrete == DISC_INTERLOCK_TRIPPED_BASE

        assert regs1.index == 1
        assert regs1.cmd_address == HOLD_INTERLOCK_CMD_BASE + 2
        assert regs1.status_address == INPUT_INTERLOCK_STATUS_BASE + 2

    def test_allocate_channels(self):
        rmap = RegisterMap()
        rmap.allocate_channels(['TC_Feed', 'PT_Inlet', 'FT_Main'])

        for i, name in enumerate(['TC_Feed', 'PT_Inlet', 'FT_Main']):
            regs = rmap.get_channel_registers(name)
            assert regs.index == i
            assert regs.name == name
            assert regs.pv_address == INPUT_PV_BASE + (i * 2)

    def test_allocate_outputs(self):
        rmap = RegisterMap()
        rmap.allocate_outputs(['Heater_01', 'Valve_01'])

        regs0 = rmap.get_output_registers('Heater_01')
        regs1 = rmap.get_output_registers('Valve_01')

        assert regs0.override_address == HOLD_OUTPUT_OVERRIDE_BASE
        assert regs1.override_address == HOLD_OUTPUT_OVERRIDE_BASE + 2

    def test_nonexistent_lookup_returns_none(self):
        rmap = RegisterMap()
        assert rmap.get_pid_registers('NOPE') is None
        assert rmap.get_interlock_registers('NOPE') is None
        assert rmap.get_channel_registers('NOPE') is None
        assert rmap.get_output_registers('NOPE') is None

class TestRegisterMapNoOverlaps:
    """Verify no register address overlaps."""

    def test_no_overlaps_typical_project(self):
        """A typical project with 3 PID loops, 2 interlocks, 8 channels, 3 outputs."""
        rmap = RegisterMap()
        rmap.allocate_pid_loops(['PID_Z1', 'PID_Z2', 'PID_Z3'])
        rmap.allocate_interlocks(['ILK_OverTemp', 'ILK_Pressure'])
        rmap.allocate_channels([f'CH_{i}' for i in range(8)])
        rmap.allocate_outputs(['OUT_0', 'OUT_1', 'OUT_2'])

        errors = rmap.validate()
        assert errors == [], f"Overlaps found: {errors}"

    def test_no_overlaps_max_capacity(self):
        """Max capacity: 50 PID loops, 50 interlocks, 100 channels, 50 outputs."""
        rmap = RegisterMap()
        rmap.allocate_pid_loops([f'PID_{i}' for i in range(MAX_PID_LOOPS)])
        rmap.allocate_interlocks([f'ILK_{i}' for i in range(MAX_INTERLOCKS)])
        rmap.allocate_channels([f'CH_{i}' for i in range(MAX_CHANNELS)])
        rmap.allocate_outputs([f'OUT_{i}' for i in range(MAX_OUTPUTS)])

        errors = rmap.validate()
        assert errors == [], f"Overlaps at max capacity: {errors}"

    def test_holding_regions_dont_overlap(self):
        """Verify that PID SP, PID tuning, interlock cmd, output override, and system cmd
        regions don't overlap at their boundaries."""
        # Check that base addresses maintain separation
        assert HOLD_PID_SP_BASE + MAX_PID_LOOPS * 2 <= HOLD_PID_TUNING_BASE
        assert HOLD_PID_TUNING_BASE + MAX_PID_LOOPS * 6 <= HOLD_INTERLOCK_CMD_BASE
        assert HOLD_INTERLOCK_CMD_BASE + MAX_INTERLOCKS * 2 <= HOLD_OUTPUT_OVERRIDE_BASE
        assert HOLD_OUTPUT_OVERRIDE_BASE + MAX_OUTPUTS * 2 <= HOLD_SYSTEM_CMD_BASE

    def test_input_regions_dont_overlap(self):
        """Verify input register regions maintain separation."""
        assert INPUT_PID_CV_BASE + MAX_PID_LOOPS * 2 <= INPUT_PV_BASE
        assert INPUT_PV_BASE + MAX_CHANNELS * 2 <= INPUT_INTERLOCK_STATUS_BASE
        assert INPUT_INTERLOCK_STATUS_BASE + MAX_INTERLOCKS * 2 <= INPUT_SYSTEM_STATUS_BASE

class TestRegisterMapTagMap:
    """Test tag map generation for CODESYSBridge."""

    def test_tag_map_pid(self):
        rmap = RegisterMap()
        rmap.allocate_pid_loops(['PID_Zone1'])

        tag_map = rmap.generate_tag_map()

        assert 'PID_Zone1_SP' in tag_map
        assert tag_map['PID_Zone1_SP']['register'] == HOLD_PID_SP_BASE
        assert tag_map['PID_Zone1_SP']['type'] == 'float32'
        assert tag_map['PID_Zone1_SP']['writable'] is True

        assert 'PID_Zone1_CV' in tag_map
        assert tag_map['PID_Zone1_CV']['register'] == INPUT_PID_CV_BASE
        assert tag_map['PID_Zone1_CV']['writable'] is False

    def test_tag_map_interlocks(self):
        rmap = RegisterMap()
        rmap.allocate_interlocks(['ILK_Safety'])

        tag_map = rmap.generate_tag_map()

        assert 'ILK_Safety_CMD' in tag_map
        assert tag_map['ILK_Safety_CMD']['writable'] is True
        assert 'ILK_Safety_STATE' in tag_map
        assert tag_map['ILK_Safety_STATE']['writable'] is False

    def test_tag_map_system_registers(self):
        rmap = RegisterMap()
        tag_map = rmap.generate_tag_map()

        assert 'SYS_ESTOP' in tag_map
        assert 'SYS_HEARTBEAT' in tag_map
        assert 'SYS_SCAN_TIME' in tag_map
        assert 'SYS_WATCHDOG' in tag_map

    def test_tag_map_channels_and_outputs(self):
        rmap = RegisterMap()
        rmap.allocate_channels(['TC_Zone1'])
        rmap.allocate_outputs(['Heater_01'])

        tag_map = rmap.generate_tag_map()

        assert 'TC_Zone1_PV' in tag_map
        assert tag_map['TC_Zone1_PV']['writable'] is False
        assert 'Heater_01_OVR' in tag_map
        assert tag_map['Heater_01_OVR']['writable'] is True

class TestRegisterMapSerialization:
    """Test to_dict / from_dict round-trip."""

    def test_round_trip(self):
        rmap = RegisterMap()
        rmap.allocate_pid_loops(['PID_Z1', 'PID_Z2'])
        rmap.allocate_interlocks(['ILK_Safety'])
        rmap.allocate_channels(['TC_Feed', 'PT_Inlet'])
        rmap.allocate_outputs(['Heater_01'])

        data = rmap.to_dict()
        assert data['version'] == '1.0'
        assert len(data['pid_loops']) == 2
        assert len(data['interlocks']) == 1
        assert len(data['channels']) == 2
        assert len(data['outputs']) == 1

        # Round-trip
        rmap2 = RegisterMap.from_dict(data)
        data2 = rmap2.to_dict()
        assert data == data2

    def test_json_serializable(self):
        rmap = RegisterMap()
        rmap.allocate_pid_loops(['PID_Z1'])
        rmap.allocate_channels(['TC_Feed'])

        data = rmap.to_dict()
        json_str = json.dumps(data)
        parsed = json.loads(json_str)
        rmap2 = RegisterMap.from_dict(parsed)

        assert rmap2.get_pid_registers('PID_Z1').sp_address == HOLD_PID_SP_BASE

    def test_empty_round_trip(self):
        rmap = RegisterMap()
        data = rmap.to_dict()
        rmap2 = RegisterMap.from_dict(data)
        assert rmap2.to_dict() == data

class TestRegisterBlockDataclasses:
    """Test individual register block dataclasses."""

    def test_pid_register_block_to_dict(self):
        block = PIDRegisterBlock(
            index=0, sp_address=40001, kp_address=40101,
            ki_address=40103, kd_address=40105, cv_address=30001,
            enable_coil=1, manual_coil=51, active_discrete=10051,
        )
        d = block.to_dict()
        assert d['sp_address'] == 40001
        assert d['cv_address'] == 30001

    def test_interlock_register_block_to_dict(self):
        block = InterlockRegisterBlock(
            index=0, cmd_address=40251, status_address=30301,
            trip_count_address=30302, arm_coil=101,
            bypass_coil=151, tripped_discrete=10001,
        )
        d = block.to_dict()
        assert d['arm_coil'] == 101
        assert d['tripped_discrete'] == 10001

# =============================================================================
# ST Code Generator Tests
# =============================================================================

class TestPIDLoopConfig:
    """Test PIDLoopConfig parsing."""

    def test_from_dict_full(self):
        data = {
            'id': 'PID_Z1', 'name': 'Zone 1', 'pv_channel': 'TC_Z1',
            'cv_channel': 'HTR_Z1', 'description': 'Zone 1 heater',
            'kp': 2.5, 'ki': 0.05, 'kd': 0.01,
            'output_min': 0.0, 'output_max': 100.0,
            'reverse_action': True, 'deadband': 0.5,
        }
        loop = PIDLoopConfig.from_dict(data)
        assert loop.id == 'PID_Z1'
        assert loop.kp == 2.5
        assert loop.reverse_action is True
        assert loop.deadband == 0.5

    def test_from_dict_minimal(self):
        data = {'id': 'PID_X', 'pv_channel': 'TC_X'}
        loop = PIDLoopConfig.from_dict(data)
        assert loop.id == 'PID_X'
        assert loop.name == 'PID_X'  # Falls back to id
        assert loop.kp == 1.0  # Default
        assert loop.reverse_action is False

class TestInterlockConfig:
    """Test InterlockConfig parsing and condition conversion."""

    def test_from_dict_with_controls(self):
        data = {
            'id': 'ILK_OT', 'name': 'Over Temp',
            'conditions': [
                {'type': 'channel_value', 'channel': 'TC_Z1', 'operator': '<', 'value': 200},
            ],
            'controls': [
                {'channel': 'HTR_Z1'},
                {'channel': 'HTR_Z2'},
            ],
        }
        ilk = InterlockConfig.from_dict(data)
        assert ilk.id == 'ILK_OT'
        assert len(ilk.controlled_outputs) == 2
        assert 'HTR_Z1' in ilk.controlled_outputs

    def test_condition_to_st_channel_value(self):
        ilk = InterlockConfig(
            id='ILK_Test', name='Test',
            conditions=[
                {'type': 'channel_value', 'channel': 'TC_Z1', 'operator': '<', 'value': 200},
            ],
        )
        pv_map = {'TC_Z1': 'GVL_Registers.PV_TC_Z1'}
        st_expr = ilk.condition_to_st(pv_map)
        assert 'GVL_Registers.PV_TC_Z1' in st_expr
        assert '< 200' in st_expr

    def test_condition_to_st_multiple_and(self):
        ilk = InterlockConfig(
            id='ILK_Multi', name='Multi',
            conditions=[
                {'type': 'channel_value', 'channel': 'TC_Z1', 'operator': '<', 'value': 200},
                {'type': 'channel_value', 'channel': 'PT_Feed', 'operator': '<=', 'value': 50.0},
            ],
        )
        pv_map = {
            'TC_Z1': 'GVL_Registers.PV_TC_Z1',
            'PT_Feed': 'GVL_Registers.PV_PT_Feed',
        }
        st_expr = ilk.condition_to_st(pv_map)
        assert ' AND ' in st_expr
        assert 'PV_TC_Z1' in st_expr
        assert 'PV_PT_Feed' in st_expr

    def test_condition_to_st_digital_input(self):
        ilk = InterlockConfig(
            id='ILK_Door', name='Door',
            conditions=[
                {'type': 'digital_input', 'channel': 'DI_Door', 'expectedState': True},
            ],
        )
        pv_map = {'DI_Door': 'GVL_Registers.PV_DI_Door'}
        st_expr = ilk.condition_to_st(pv_map)
        assert '> 0.5' in st_expr

    def test_condition_to_st_unsupported_type(self):
        """DAQ-only conditions (alarm_active, mqtt_connected) become TRUE."""
        ilk = InterlockConfig(
            id='ILK_X', name='X',
            conditions=[
                {'type': 'mqtt_connected'},
            ],
        )
        st_expr = ilk.condition_to_st({})
        assert st_expr == 'TRUE'

    def test_condition_to_st_empty(self):
        ilk = InterlockConfig(id='ILK_Empty', name='Empty')
        st_expr = ilk.condition_to_st({})
        assert st_expr == 'TRUE'

class TestChannelInfo:
    """Test ChannelInfo helper."""

    def test_is_output_true(self):
        for ch_type in ('voltage_output', 'current_output', 'digital_output', 'analog_output'):
            ch = ChannelInfo(name='X', channel_type=ch_type)
            assert ch.is_output is True, f"{ch_type} should be output"

    def test_is_output_false(self):
        for ch_type in ('thermocouple', 'voltage_input', 'digital_input', 'current_input'):
            ch = ChannelInfo(name='X', channel_type=ch_type)
            assert ch.is_output is False, f"{ch_type} should not be output"

    def test_get_io_path_explicit(self):
        ch = ChannelInfo(name='TC_Z1', channel_type='thermocouple', io_path='GRV_EPIC_PR1.Slot01.Ch00')
        assert ch.get_io_path() == 'GRV_EPIC_PR1.Slot01.Ch00'

    def test_get_io_path_generated(self):
        ch = ChannelInfo(name='TC_Z1', channel_type='thermocouple',
                         groov_module_index=3, groov_channel_index=5)
        assert ch.get_io_path() == 'GRV_EPIC_PR1.Slot03.Ch05'

    def test_get_io_path_todo_fallback(self):
        ch = ChannelInfo(name='TC_Z1', channel_type='thermocouple')
        path = ch.get_io_path()
        assert 'TODO' in path

class TestHelperFunctions:
    """Test utility functions."""

    def test_operator_to_st(self):
        assert _operator_to_st('<') == '<'
        assert _operator_to_st('<=') == '<='
        assert _operator_to_st('==') == '='
        assert _operator_to_st('!=') == '<>'
        assert _operator_to_st('gt') == '>'
        assert _operator_to_st('unknown') == '<'  # Default

    def test_format_real(self):
        assert _format_real(100.0) == '100.0'
        assert _format_real(0.0) == '0.0'
        assert _format_real(3.14159) == '3.1416'
        assert _format_real(1.0) == '1.0'

class TestSTCodeGenerator:
    """Test the ST code generator."""

    def _make_generator(self):
        """Create a generator with a typical 2-zone heater config."""
        gen = STCodeGenerator(project_name="Test Project")
        gen.add_pid_loops([
            {'id': 'PID_Z1', 'name': 'Zone 1', 'pv_channel': 'TC_Z1',
             'cv_channel': 'HTR_Z1', 'kp': 2.0, 'ki': 0.05, 'kd': 0.0,
             'output_min': 0.0, 'output_max': 100.0},
            {'id': 'PID_Z2', 'name': 'Zone 2', 'pv_channel': 'TC_Z2',
             'cv_channel': 'HTR_Z2', 'kp': 2.0, 'ki': 0.05, 'kd': 0.0},
        ])
        gen.add_interlocks([
            {'id': 'ILK_OT', 'name': 'Over Temp',
             'conditions': [
                 {'type': 'channel_value', 'channel': 'TC_Z1', 'operator': '<', 'value': 250},
             ],
             'controls': [{'channel': 'HTR_Z1'}, {'channel': 'HTR_Z2'}]},
        ])
        gen.add_channels({
            'TC_Z1': {'channel_type': 'thermocouple', 'groov_module_index': 1,
                      'groov_channel_index': 0, 'description': 'Zone 1 TC'},
            'TC_Z2': {'channel_type': 'thermocouple', 'groov_module_index': 1,
                      'groov_channel_index': 1, 'description': 'Zone 2 TC'},
            'HTR_Z1': {'channel_type': 'voltage_output', 'groov_module_index': 2,
                       'groov_channel_index': 0, 'safe_value': 0.0},
            'HTR_Z2': {'channel_type': 'voltage_output', 'groov_module_index': 2,
                       'groov_channel_index': 1, 'safe_value': 0.0},
        })
        return gen

    def test_register_map_generated(self):
        gen = self._make_generator()
        rmap = gen.get_register_map()

        assert rmap.get_pid_registers('PID_Z1') is not None
        assert rmap.get_pid_registers('PID_Z2') is not None
        assert rmap.get_interlock_registers('ILK_OT') is not None
        assert rmap.get_channel_registers('TC_Z1') is not None
        assert rmap.get_output_registers('HTR_Z1') is not None

    def test_register_map_no_overlaps(self):
        gen = self._make_generator()
        rmap = gen.get_register_map()
        errors = rmap.validate()
        assert errors == [], f"Overlaps: {errors}"

    def test_generate_returns_all_files(self):
        gen = self._make_generator()
        files = gen.generate()

        expected_files = ['FB_PID_Loop.st', 'FB_Interlock.st', 'FB_SafeState.st',
                          'GVL_Registers.st', 'Main.st']
        for fname in expected_files:
            assert fname in files, f"Missing: {fname}"

    def test_generate_fb_pid_loop_content(self):
        gen = self._make_generator()
        files = gen.generate()

        fb = files['FB_PID_Loop.st']
        assert 'FUNCTION_BLOCK FB_PID_Loop' in fb
        assert 'VAR_INPUT' in fb
        assert 'PV' in fb
        assert 'SP' in fb
        assert 'END_FUNCTION_BLOCK' in fb

    def test_generate_fb_interlock_content(self):
        gen = self._make_generator()
        files = gen.generate()

        fb = files['FB_Interlock.st']
        assert 'FUNCTION_BLOCK FB_Interlock' in fb
        assert 'ConditionOK' in fb
        assert 'TRIPPED' in fb

    def test_generate_gvl_has_register_addresses(self):
        gen = self._make_generator()
        files = gen.generate()

        gvl = files['GVL_Registers.st']
        assert 'SP_PID_Z1' in gvl
        assert 'CV_PID_Z1' in gvl
        assert 'PV_TC_Z1' in gvl
        assert 'Arm_ILK_OT' in gvl
        assert 'SYS_EStop' in gvl

    def test_generate_main_has_pid_wiring(self):
        gen = self._make_generator()
        files = gen.generate()

        main = files['Main.st']
        assert 'pid_PID_Z1' in main
        assert 'pid_PID_Z2' in main
        assert 'GVL_Registers.PV_TC_Z1' in main
        assert 'GVL_Registers.SP_PID_Z1' in main

    def test_generate_main_has_interlock_wiring(self):
        gen = self._make_generator()
        files = gen.generate()

        main = files['Main.st']
        assert 'ilk_ILK_OT' in main
        assert 'FB_Interlock' in main

    def test_generate_main_has_output_blocking(self):
        gen = self._make_generator()
        files = gen.generate()

        main = files['Main.st']
        assert 'blocked_HTR_Z1' in main
        assert 'blocked_HTR_Z2' in main

    def test_generate_main_has_heartbeat_watchdog(self):
        gen = self._make_generator()
        files = gen.generate()

        main = files['Main.st']
        assert 'heartbeatTimeout' in main
        assert '5000' in main

    def test_generate_to_dir(self):
        gen = self._make_generator()

        with tempfile.TemporaryDirectory() as tmpdir:
            written = gen.generate_to_dir(tmpdir)

            assert len(written) == 5
            for path in written:
                assert os.path.exists(path)
                content = open(path, encoding='utf-8').read()
                assert len(content) > 0

    def test_config_hash_deterministic(self):
        gen1 = self._make_generator()
        gen2 = self._make_generator()
        assert gen1._config_hash() == gen2._config_hash()

    def test_config_hash_changes_with_config(self):
        gen1 = STCodeGenerator(project_name="P1")
        gen1.add_pid_loops([{'id': 'PID_A', 'pv_channel': 'TC_A'}])

        gen2 = STCodeGenerator(project_name="P2")
        gen2.add_pid_loops([{'id': 'PID_B', 'pv_channel': 'TC_B'}])

        assert gen1._config_hash() != gen2._config_hash()

    def test_pid_cv_channel_linked_to_output(self):
        """When a PID loop's cv_channel matches an output, the output should reference pid_cv."""
        gen = self._make_generator()
        files = gen.generate()

        main = files['Main.st']
        # HTR_Z1 is driven by PID_Z1, so its normal output should be CV_PID_Z1
        assert 'CV_PID_Z1' in main

    def test_empty_project(self):
        """Generator should handle empty project without errors."""
        gen = STCodeGenerator(project_name="Empty")
        files = gen.generate()

        assert 'GVL_Registers.st' in files
        assert 'Main.st' in files
        # Static FBs should still be included
        assert 'FB_PID_Loop.st' in files

class TestSTCodeGeneratorEdgeCases:
    """Edge case tests."""

    def test_special_characters_in_names(self):
        """Channel names with underscores should work fine."""
        gen = STCodeGenerator()
        gen.add_channels({
            'TC_Zone_1_Inlet': {'channel_type': 'thermocouple'},
            'PT_2_Bar_Range': {'channel_type': 'voltage_input'},
        })
        files = gen.generate()
        gvl = files['GVL_Registers.st']
        assert 'PV_TC_Zone_1_Inlet' in gvl
        assert 'PV_PT_2_Bar_Range' in gvl

    def test_many_loops(self):
        """Generator should handle many PID loops."""
        gen = STCodeGenerator()
        gen.add_pid_loops([
            {'id': f'PID_{i}', 'pv_channel': f'TC_{i}'} for i in range(20)
        ])
        gen.add_channels({
            f'TC_{i}': {'channel_type': 'thermocouple'} for i in range(20)
        })
        files = gen.generate()

        rmap = gen.get_register_map()
        errors = rmap.validate()
        assert errors == []

        main = files['Main.st']
        assert 'pid_PID_0' in main
        assert 'pid_PID_19' in main
