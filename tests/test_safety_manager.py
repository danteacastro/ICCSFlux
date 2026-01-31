"""
Tests for safety_manager.py
Covers safety interlocks, latch state management, and trip system functionality.
This is critical safety code - tests must be comprehensive.
"""

import pytest
import tempfile
import json
import time
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock, MagicMock, patch

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "daq_service"))

from safety_manager import (
    SafetyManager, LatchState, ConditionOperator,
    InterlockCondition, InterlockControl, Interlock,
    InterlockStatus, SafeStateConfig, InterlockHistoryEntry
)


class TestLatchState:
    """Tests for LatchState enum"""

    def test_latch_states(self):
        """Test all latch states are defined"""
        assert LatchState.SAFE.value == "safe"
        assert LatchState.ARMED.value == "armed"
        assert LatchState.TRIPPED.value == "tripped"


class TestConditionOperator:
    """Tests for ConditionOperator enum"""

    def test_operators(self):
        """Test all comparison operators are defined"""
        assert ConditionOperator.LT.value == "<"
        assert ConditionOperator.LE.value == "<="
        assert ConditionOperator.GT.value == ">"
        assert ConditionOperator.GE.value == ">="
        assert ConditionOperator.EQ.value == "="
        assert ConditionOperator.NE.value == "!="


class TestInterlockCondition:
    """Tests for InterlockCondition dataclass"""

    def test_to_dict(self):
        """Test conversion to dictionary"""
        condition = InterlockCondition(
            id="cond-1",
            condition_type="channel_value",
            channel="temp_1",
            operator=">",
            value=100.0,
            invert=False,
            delay_s=2.0
        )

        d = condition.to_dict()
        assert d['id'] == "cond-1"
        assert d['type'] == "channel_value"
        assert d['channel'] == "temp_1"
        assert d['operator'] == ">"
        assert d['value'] == 100.0
        assert d['delay_s'] == 2.0

    def test_from_dict(self):
        """Test creation from dictionary"""
        d = {
            'id': 'cond-2',
            'type': 'digital_input',
            'channel': 'switch_1',
            'value': True,
            'invert': True
        }

        condition = InterlockCondition.from_dict(d)
        assert condition.id == "cond-2"
        assert condition.condition_type == "digital_input"
        assert condition.channel == "switch_1"
        assert condition.value is True
        assert condition.invert is True


class TestInterlockControl:
    """Tests for InterlockControl dataclass"""

    def test_to_dict(self):
        """Test conversion to dictionary"""
        control = InterlockControl(
            control_type="set_digital_output",
            channel="heater",
            set_value=0
        )

        d = control.to_dict()
        assert d['type'] == "set_digital_output"
        assert d['channel'] == "heater"
        assert d['setValue'] == 0

    def test_from_dict(self):
        """Test creation from dictionary"""
        d = {
            'type': 'stop_session',
            'channel': None
        }

        control = InterlockControl.from_dict(d)
        assert control.control_type == "stop_session"


class TestInterlock:
    """Tests for Interlock dataclass"""

    def test_basic_interlock(self):
        """Test creating a basic interlock"""
        interlock = Interlock(
            id="int-1",
            name="Temperature Limit",
            description="Prevents overheating",
            enabled=True,
            conditions=[
                InterlockCondition(
                    id="c1",
                    condition_type="channel_value",
                    channel="temp",
                    operator="<",
                    value=200.0
                )
            ],
            controls=[
                InterlockControl(
                    control_type="set_digital_output",
                    channel="heater",
                    set_value=0
                )
            ]
        )

        assert interlock.name == "Temperature Limit"
        assert len(interlock.conditions) == 1
        assert len(interlock.controls) == 1

    def test_to_dict(self):
        """Test conversion to dictionary"""
        interlock = Interlock(
            id="int-1",
            name="Test",
            enabled=True,
            bypass_allowed=True
        )

        d = interlock.to_dict()
        assert d['id'] == "int-1"
        assert d['name'] == "Test"
        assert d['enabled'] is True
        assert d['bypassAllowed'] is True

    def test_from_dict(self):
        """Test creation from dictionary"""
        d = {
            'id': 'int-2',
            'name': 'Safety Interlock',
            'description': 'Critical safety check',
            'enabled': True,
            'conditions': [
                {'id': 'c1', 'type': 'channel_value', 'channel': 'pressure', 'operator': '<', 'value': 100}
            ],
            'controls': [
                {'type': 'stop_session'}
            ],
            'bypassAllowed': False
        }

        interlock = Interlock.from_dict(d)
        assert interlock.id == "int-2"
        assert interlock.name == "Safety Interlock"
        assert len(interlock.conditions) == 1
        assert len(interlock.controls) == 1


class TestSafeStateConfig:
    """Tests for SafeStateConfig dataclass"""

    def test_defaults(self):
        """Test default values"""
        config = SafeStateConfig()
        assert config.reset_digital_outputs is True
        assert config.reset_analog_outputs is True
        assert config.stop_session is True
        assert config.analog_safe_value == 0.0

    def test_to_dict(self):
        """Test conversion to dictionary"""
        config = SafeStateConfig(
            reset_digital_outputs=True,
            reset_analog_outputs=False,
            digital_output_channels=['do1', 'do2']
        )

        d = config.to_dict()
        assert d['resetDigitalOutputs'] is True
        assert d['resetAnalogOutputs'] is False
        assert d['digitalOutputChannels'] == ['do1', 'do2']

    def test_from_dict(self):
        """Test creation from dictionary"""
        d = {
            'resetDigitalOutputs': False,
            'stopSession': False,
            'analogSafeValue': 5.0
        }

        config = SafeStateConfig.from_dict(d)
        assert config.reset_digital_outputs is False
        assert config.stop_session is False
        assert config.analog_safe_value == 5.0


class TestSafetyManager:
    """Tests for SafetyManager class"""

    @pytest.fixture
    def data_dir(self):
        """Create a temporary directory for safety data"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def channel_values(self):
        """Mock channel values"""
        return {
            'temp_1': 75.0,
            'pressure_1': 50.0,
            'switch_1': 1,
            'valve_open': 1,
            'heater': 0
        }

    @pytest.fixture
    def safety_manager(self, data_dir, channel_values):
        """Create a SafetyManager instance with mocked callbacks"""
        def get_channel_value(name):
            return channel_values.get(name)

        def get_channel_type(name):
            if 'switch' in name or 'valve' in name or 'heater' in name:
                return 'digital_input'
            return 'voltage_input'

        def get_all_channels():
            return {
                'heater': {'channel_type': 'digital_output'},
                'valve': {'channel_type': 'digital_output'},
                'setpoint': {'channel_type': 'analog_output'}
            }

        manager = SafetyManager(
            data_dir=data_dir,
            get_channel_value=get_channel_value,
            get_channel_type=get_channel_type,
            get_all_channels=get_all_channels,
            publish_callback=Mock(),
            set_output_callback=Mock(),
            stop_session_callback=Mock(),
            get_system_state=lambda: {'status': 'online', 'acquiring': True},
            get_alarm_state=lambda: {'active_count': 0}
        )

        return manager

    def test_initialization(self, safety_manager):
        """Test manager initialization"""
        assert safety_manager.latch_state == LatchState.SAFE
        assert safety_manager.is_tripped is False
        assert len(safety_manager.interlocks) == 0

    def test_add_interlock(self, safety_manager):
        """Test adding an interlock"""
        interlock = Interlock(
            id="test-int",
            name="Test Interlock",
            enabled=True,
            conditions=[
                InterlockCondition(
                    id="c1",
                    condition_type="channel_value",
                    channel="temp_1",
                    operator="<",
                    value=100.0
                )
            ]
        )

        result = safety_manager.add_interlock(interlock)

        assert result == "test-int"
        assert "test-int" in safety_manager.interlocks
        assert len(safety_manager.history) > 0

    def test_remove_interlock(self, safety_manager):
        """Test removing an interlock"""
        interlock = Interlock(id="to-remove", name="Remove Me")
        safety_manager.add_interlock(interlock)

        safety_manager.remove_interlock("to-remove")

        assert "to-remove" not in safety_manager.interlocks

    def test_update_interlock(self, safety_manager):
        """Test updating an interlock"""
        interlock = Interlock(id="to-update", name="Original", enabled=True)
        safety_manager.add_interlock(interlock)

        safety_manager.update_interlock("to-update", {'name': 'Updated', 'enabled': False})

        updated = safety_manager.get_interlock("to-update")
        assert updated.name == "Updated"
        assert updated.enabled is False

    def test_bypass_interlock(self, safety_manager):
        """Test bypassing an interlock"""
        interlock = Interlock(
            id="bypassable",
            name="Bypassable",
            bypass_allowed=True
        )
        safety_manager.add_interlock(interlock)

        result = safety_manager.bypass_interlock(
            "bypassable",
            bypass=True,
            user="admin",
            reason="Maintenance"
        )

        assert result is True
        bypassed = safety_manager.get_interlock("bypassable")
        assert bypassed.bypassed is True
        assert bypassed.bypassed_by == "admin"
        assert bypassed.bypass_reason == "Maintenance"

    def test_bypass_not_allowed(self, safety_manager):
        """Test that bypass fails when not allowed"""
        interlock = Interlock(
            id="no-bypass",
            name="No Bypass",
            bypass_allowed=False
        )
        safety_manager.add_interlock(interlock)

        result = safety_manager.bypass_interlock("no-bypass", True, "admin")

        assert result is False
        assert safety_manager.get_interlock("no-bypass").bypassed is False

    def test_evaluate_channel_value_condition_satisfied(self, safety_manager):
        """Test evaluating a satisfied channel value condition"""
        # temp_1 = 75.0, condition is < 100.0, should be satisfied
        condition = InterlockCondition(
            id="c1",
            condition_type="channel_value",
            channel="temp_1",
            operator="<",
            value=100.0
        )

        result = safety_manager._evaluate_condition_raw(condition)

        assert result['satisfied'] is True
        assert result['current_value'] == 75.0

    def test_evaluate_channel_value_condition_not_satisfied(self, safety_manager):
        """Test evaluating a not satisfied channel value condition"""
        # temp_1 = 75.0, condition is < 50.0, should NOT be satisfied
        condition = InterlockCondition(
            id="c1",
            condition_type="channel_value",
            channel="temp_1",
            operator="<",
            value=50.0
        )

        result = safety_manager._evaluate_condition_raw(condition)

        assert result['satisfied'] is False

    def test_evaluate_digital_input_condition(self, safety_manager, channel_values):
        """Test evaluating a digital input condition"""
        # switch_1 = 1 (ON), expected True
        condition = InterlockCondition(
            id="c1",
            condition_type="digital_input",
            channel="switch_1",
            value=True
        )

        result = safety_manager._evaluate_condition_raw(condition)

        assert result['satisfied'] is True

    def test_evaluate_digital_input_inverted(self, safety_manager):
        """Test evaluating an inverted digital input condition"""
        condition = InterlockCondition(
            id="c1",
            condition_type="digital_input",
            channel="switch_1",
            value=False,  # Expect OFF
            invert=True   # But invert logic
        )

        result = safety_manager._evaluate_condition_raw(condition)
        # switch_1 = 1 (ON), inverted = OFF, expected OFF = satisfied
        assert result['satisfied'] is True

    def test_evaluate_mqtt_connected_condition(self, safety_manager):
        """Test evaluating MQTT connected condition"""
        condition = InterlockCondition(
            id="c1",
            condition_type="mqtt_connected"
        )

        result = safety_manager._evaluate_condition_raw(condition)

        # Backend always considers itself connected
        assert result['satisfied'] is True

    def test_evaluate_no_active_alarms_condition(self, safety_manager):
        """Test evaluating no active alarms condition"""
        condition = InterlockCondition(
            id="c1",
            condition_type="no_active_alarms"
        )

        result = safety_manager._evaluate_condition_raw(condition)

        # Mock returns active_count: 0
        assert result['satisfied'] is True

    def test_compare_values(self, safety_manager):
        """Test value comparison operators"""
        assert safety_manager._compare_values(50, '<', 100) is True
        assert safety_manager._compare_values(100, '<', 100) is False
        assert safety_manager._compare_values(100, '<=', 100) is True
        assert safety_manager._compare_values(150, '>', 100) is True
        assert safety_manager._compare_values(100, '>=', 100) is True
        assert safety_manager._compare_values(100, '=', 100) is True
        assert safety_manager._compare_values(100, '==', 100) is True
        assert safety_manager._compare_values(50, '!=', 100) is True

    def test_evaluate_interlock_all_conditions_satisfied(self, safety_manager):
        """Test evaluating an interlock with all conditions satisfied"""
        interlock = Interlock(
            id="test",
            name="Test",
            enabled=True,
            conditions=[
                InterlockCondition(id="c1", condition_type="channel_value",
                                   channel="temp_1", operator="<", value=100),
                InterlockCondition(id="c2", condition_type="channel_value",
                                   channel="pressure_1", operator="<", value=100)
            ],
            condition_logic="AND"
        )

        status = safety_manager.evaluate_interlock(interlock)

        assert status.satisfied is True
        assert len(status.failed_conditions) == 0

    def test_evaluate_interlock_one_condition_failed(self, safety_manager):
        """Test evaluating an interlock with one condition failed"""
        interlock = Interlock(
            id="test",
            name="Test",
            enabled=True,
            conditions=[
                InterlockCondition(id="c1", condition_type="channel_value",
                                   channel="temp_1", operator="<", value=100),  # 75 < 100 = OK
                InterlockCondition(id="c2", condition_type="channel_value",
                                   channel="temp_1", operator="<", value=50)   # 75 < 50 = FAIL
            ],
            condition_logic="AND"
        )

        status = safety_manager.evaluate_interlock(interlock)

        assert status.satisfied is False
        assert len(status.failed_conditions) == 1

    def test_evaluate_interlock_or_logic(self, safety_manager):
        """Test evaluating an interlock with OR logic"""
        interlock = Interlock(
            id="test",
            name="Test",
            enabled=True,
            conditions=[
                InterlockCondition(id="c1", condition_type="channel_value",
                                   channel="temp_1", operator="<", value=50),   # FAIL
                InterlockCondition(id="c2", condition_type="channel_value",
                                   channel="temp_1", operator="<", value=100)  # OK
            ],
            condition_logic="OR"
        )

        status = safety_manager.evaluate_interlock(interlock)

        # With OR logic, one satisfied condition is enough
        assert status.satisfied is True

    def test_evaluate_disabled_interlock(self, safety_manager):
        """Test evaluating a disabled interlock"""
        interlock = Interlock(
            id="test",
            name="Disabled",
            enabled=False,
            conditions=[
                InterlockCondition(id="c1", condition_type="channel_value",
                                   channel="temp_1", operator="<", value=50)  # Would fail
            ]
        )

        status = safety_manager.evaluate_interlock(interlock)

        # Disabled interlocks are always satisfied
        assert status.satisfied is True
        assert status.enabled is False

    def test_evaluate_bypassed_interlock(self, safety_manager):
        """Test evaluating a bypassed interlock"""
        interlock = Interlock(
            id="test",
            name="Bypassed",
            enabled=True,
            bypass_allowed=True,
            bypassed=True,
            bypassed_by="admin",
            conditions=[
                InterlockCondition(id="c1", condition_type="channel_value",
                                   channel="temp_1", operator="<", value=50)  # Would fail
            ]
        )

        status = safety_manager.evaluate_interlock(interlock)

        # Bypassed interlocks are satisfied
        assert status.satisfied is True
        assert status.bypassed is True

    def test_arm_latch_success(self, safety_manager):
        """Test arming the safety latch"""
        result = safety_manager.arm_latch("operator")

        assert result is True
        assert safety_manager.latch_state == LatchState.ARMED

    def test_arm_latch_with_failed_interlock(self, safety_manager):
        """Test that latch cannot be armed with failed interlocks"""
        # Add a failing interlock
        interlock = Interlock(
            id="failing",
            name="Failing",
            enabled=True,
            conditions=[
                InterlockCondition(id="c1", condition_type="channel_value",
                                   channel="temp_1", operator="<", value=50)  # Will fail
            ]
        )
        safety_manager.add_interlock(interlock)

        result = safety_manager.arm_latch("operator")

        assert result is False
        assert safety_manager.latch_state == LatchState.SAFE

    def test_disarm_latch(self, safety_manager):
        """Test disarming the safety latch"""
        safety_manager.arm_latch("operator")
        safety_manager.disarm_latch("operator")

        assert safety_manager.latch_state == LatchState.SAFE

    def test_trip_system(self, safety_manager):
        """Test system trip"""
        safety_manager.trip_system("Test trip reason")

        assert safety_manager.is_tripped is True
        assert safety_manager.latch_state == LatchState.TRIPPED
        assert safety_manager.last_trip_reason == "Test trip reason"
        assert safety_manager.last_trip_time is not None

        # Verify callbacks were called
        safety_manager._stop_session.assert_called_once()

    def test_reset_trip_with_clear_interlocks(self, safety_manager):
        """Test resetting trip when interlocks are clear"""
        safety_manager.trip_system("Test")

        result = safety_manager.reset_trip("operator")

        assert result is True
        assert safety_manager.is_tripped is False
        assert safety_manager.latch_state == LatchState.SAFE

    def test_reset_trip_with_failed_interlocks(self, safety_manager):
        """Test that trip cannot be reset with failed interlocks"""
        # Add a failing interlock
        interlock = Interlock(
            id="failing",
            name="Failing",
            enabled=True,
            conditions=[
                InterlockCondition(id="c1", condition_type="channel_value",
                                   channel="temp_1", operator="<", value=50)
            ]
        )
        safety_manager.add_interlock(interlock)

        safety_manager.trip_system("Test")

        result = safety_manager.reset_trip("operator")

        assert result is False
        assert safety_manager.is_tripped is True

    def test_evaluate_all(self, safety_manager):
        """Test evaluating all interlocks"""
        # Add some interlocks
        safety_manager.add_interlock(Interlock(
            id="int1",
            name="Interlock 1",
            enabled=True,
            conditions=[
                InterlockCondition(id="c1", condition_type="channel_value",
                                   channel="temp_1", operator="<", value=100)
            ]
        ))

        result = safety_manager.evaluate_all()

        assert 'latchState' in result
        assert 'isTripped' in result
        assert 'interlockStatuses' in result
        assert len(result['interlockStatuses']) == 1

    def test_auto_trip_on_interlock_failure(self, safety_manager, channel_values):
        """Test automatic trip when interlock fails while armed"""
        # Add an interlock that will fail when temp > 80
        interlock = Interlock(
            id="temp-limit",
            name="Temperature Limit",
            enabled=True,
            conditions=[
                InterlockCondition(id="c1", condition_type="channel_value",
                                   channel="temp_1", operator="<", value=80)  # Will fail when temp = 75 < 80 = OK initially
            ]
        )
        safety_manager.add_interlock(interlock)

        # Arm the latch (should succeed since 75 < 80)
        assert safety_manager.arm_latch("operator") is True

        # Now update channel value to cause failure
        channel_values['temp_1'] = 85.0  # Now 85 < 80 = FAIL

        # Evaluate all should trigger trip
        safety_manager.evaluate_all()

        assert safety_manager.is_tripped is True
        assert safety_manager.latch_state == LatchState.TRIPPED

    def test_is_output_blocked(self, safety_manager):
        """Test checking if output is blocked by interlock"""
        interlock = Interlock(
            id="block-heater",
            name="Block Heater",
            enabled=True,
            conditions=[
                InterlockCondition(id="c1", condition_type="channel_value",
                                   channel="temp_1", operator="<", value=50)  # Will fail
            ],
            controls=[
                InterlockControl(control_type="digital_output", channel="heater")
            ]
        )
        safety_manager.add_interlock(interlock)

        result = safety_manager.is_output_blocked("heater")

        assert result['blocked'] is True
        assert len(result['blockedBy']) > 0

    def test_execute_interlock_actions(self, safety_manager):
        """Test executing interlock control actions"""
        interlock = Interlock(
            id="action-test",
            name="Action Test",
            controls=[
                InterlockControl(control_type="set_digital_output", channel="heater", set_value=0),
                InterlockControl(control_type="stop_session")
            ]
        )

        safety_manager.execute_interlock_actions(interlock)

        # Verify set_output was called
        safety_manager._set_output.assert_called()
        # Verify stop_session was called
        safety_manager._stop_session.assert_called()

    def test_history_recording(self, safety_manager):
        """Test that events are recorded to history"""
        initial_history = len(safety_manager.history)

        interlock = Interlock(id="hist-test", name="History Test")
        safety_manager.add_interlock(interlock, user="testuser")

        assert len(safety_manager.history) > initial_history

    def test_get_history(self, safety_manager):
        """Test getting history with filters"""
        interlock = Interlock(id="hist-test", name="History Test")
        safety_manager.add_interlock(interlock, user="admin")

        history = safety_manager.get_history(limit=10)

        assert len(history) > 0
        assert 'timestamp' in history[0]
        assert 'event' in history[0]

    def test_persistence(self, data_dir, channel_values):
        """Test that interlocks persist across restarts"""
        def get_val(name):
            return channel_values.get(name)

        # Create first instance and add interlock
        manager1 = SafetyManager(
            data_dir=data_dir,
            get_channel_value=get_val,
            get_channel_type=lambda x: 'voltage_input',
            get_all_channels=lambda: {}
        )

        interlock = Interlock(id="persist-test", name="Persistence Test")
        manager1.add_interlock(interlock)
        manager1.save_all()

        # Create second instance
        manager2 = SafetyManager(
            data_dir=data_dir,
            get_channel_value=get_val,
            get_channel_type=lambda x: 'voltage_input',
            get_all_channels=lambda: {}
        )

        # Interlock should be loaded
        assert "persist-test" in manager2.interlocks

    def test_condition_delay(self, safety_manager):
        """Test condition delay logic"""
        condition = InterlockCondition(
            id="delayed",
            condition_type="channel_value",
            channel="temp_1",
            operator="<",
            value=100,
            delay_s=0.5  # 500ms delay
        )

        # First evaluation - starts the timer
        result1 = safety_manager._evaluate_condition(condition)
        assert result1['satisfied'] is False  # Not satisfied yet, waiting for delay

        # Wait for delay
        time.sleep(0.6)

        # Second evaluation - delay elapsed
        result2 = safety_manager._evaluate_condition(condition)
        assert result2['satisfied'] is True

    def test_clear_all(self, safety_manager):
        """Test clearing all safety state"""
        interlock = Interlock(id="clear-test", name="Clear Test")
        safety_manager.add_interlock(interlock)
        safety_manager.arm_latch()

        safety_manager.clear_all()

        assert len(safety_manager.interlocks) == 0
        assert len(safety_manager.history) == 0
        assert safety_manager.latch_state == LatchState.SAFE
        assert safety_manager.is_tripped is False


class TestInterlockStatus:
    """Tests for InterlockStatus dataclass"""

    def test_to_dict(self):
        """Test conversion to dictionary"""
        status = InterlockStatus(
            id="int-1",
            name="Test Interlock",
            satisfied=True,
            enabled=True,
            bypassed=False,
            failed_conditions=[]
        )

        d = status.to_dict()
        assert d['id'] == "int-1"
        assert d['name'] == "Test Interlock"
        assert d['satisfied'] is True
        assert d['enabled'] is True
        assert d['bypassed'] is False


class TestBypassExpiration:
    """Tests for bypass time expiration"""

    @pytest.fixture
    def data_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_bypass_expires(self, data_dir):
        """Test that bypass expires after max duration"""
        manager = SafetyManager(
            data_dir=data_dir,
            get_channel_value=lambda x: 50,
            get_channel_type=lambda x: 'voltage_input',
            get_all_channels=lambda: {}
        )

        interlock = Interlock(
            id="expire-test",
            name="Expiring Bypass",
            enabled=True,
            bypass_allowed=True,
            max_bypass_duration=0.5,  # 500ms
            conditions=[
                InterlockCondition(id="c1", condition_type="channel_value",
                                   channel="temp", operator="<", value=100)
            ]
        )
        manager.add_interlock(interlock)

        # Bypass the interlock
        manager.bypass_interlock("expire-test", True, "admin", "Testing")
        assert manager.get_interlock("expire-test").bypassed is True

        # Wait for expiration
        time.sleep(0.6)

        # Evaluate should clear the bypass
        manager.evaluate_interlock(manager.get_interlock("expire-test"))

        # Bypass should be removed
        assert manager.get_interlock("expire-test").bypassed is False
