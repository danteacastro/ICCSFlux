"""
Tests for CFP hardware discovery via Modbus slot probing.

Tests scan_cfp() in device_discovery.py which probes CompactFieldPoint
backplane slots by attempting Modbus reads at slot base addresses.
"""

import sys
import os
from unittest.mock import MagicMock, patch

# Ensure project root is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'services', 'daq_service'))

from device_discovery import DeviceDiscovery, CFP_BACKPLANES, CFP_SLOT_REGISTER_OFFSET


class MockModbusResponse:
    """Mock a successful pymodbus response."""
    def __init__(self, registers=None, bits=None, is_error=False):
        self.registers = registers or [0]
        self.bits = bits or [False]
        self._is_error = is_error

    def isError(self):
        return self._is_error


class MockModbusErrorResponse:
    """Mock a pymodbus error response (e.g., ILLEGAL_DATA_ADDRESS)."""
    def isError(self):
        return True


def _make_client_mock(slot_responses=None):
    """
    Create a mock ModbusTcpClient with per-slot response configuration.

    slot_responses: dict mapping slot number to register type that succeeds.
        e.g., {1: 'input', 3: 'coil'} means slot 1 has input registers, slot 3 has coils.
        Slots not listed return errors for all register types.
    """
    slot_responses = slot_responses or {}

    client = MagicMock()
    client.connect.return_value = True

    def _read_fn(register_type):
        def read(address, count=1, slave=1):
            slot_num = (address // CFP_SLOT_REGISTER_OFFSET) + 1
            if slot_responses.get(slot_num) == register_type:
                return MockModbusResponse()
            return MockModbusErrorResponse()
        return read

    client.read_input_registers = _read_fn('input')
    client.read_holding_registers = _read_fn('holding')
    client.read_discrete_inputs = _read_fn('discrete')
    client.read_coils = _read_fn('coil')

    return client


class TestCFPSlotProbing:
    """Tests for DeviceDiscovery.scan_cfp()"""

    def test_scan_cfp_populated_analog_input(self):
        """Slot with input registers is detected as analog_input."""
        discovery = DeviceDiscovery()
        mock_client = _make_client_mock({1: 'input'})

        with patch('device_discovery._PYMODBUS_AVAILABLE', True), \
             patch('device_discovery._CfpModbusTcpClient', return_value=mock_client):
            result = discovery.scan_cfp('192.168.1.30', backplane_model='cFP-1804')

        assert result['success'] is True
        assert len(result['slots']) == 4  # cFP-1804 has 4 slots
        assert result['slots'][0]['slot'] == 1
        assert result['slots'][0]['populated'] is True
        assert result['slots'][0]['category'] == 'analog_input'
        assert result['slots'][0]['register_type'] == 'input'

    def test_scan_cfp_populated_digital_output(self):
        """Slot with coils is detected as digital_output."""
        discovery = DeviceDiscovery()
        mock_client = _make_client_mock({2: 'coil'})

        with patch('device_discovery._PYMODBUS_AVAILABLE', True), \
             patch('device_discovery._CfpModbusTcpClient', return_value=mock_client):
            result = discovery.scan_cfp('192.168.1.30', backplane_model='cFP-1808')

        slot2 = result['slots'][1]
        assert slot2['populated'] is True
        assert slot2['category'] == 'digital_output'
        assert slot2['register_type'] == 'coil'

    def test_scan_cfp_populated_digital_input(self):
        """Slot with discrete inputs is detected as digital_input."""
        discovery = DeviceDiscovery()
        mock_client = _make_client_mock({3: 'discrete'})

        with patch('device_discovery._PYMODBUS_AVAILABLE', True), \
             patch('device_discovery._CfpModbusTcpClient', return_value=mock_client):
            result = discovery.scan_cfp('192.168.1.30', backplane_model='cFP-1808')

        slot3 = result['slots'][2]
        assert slot3['populated'] is True
        assert slot3['category'] == 'digital_input'

    def test_scan_cfp_populated_analog_output(self):
        """Slot with holding registers is detected as analog_output."""
        discovery = DeviceDiscovery()
        mock_client = _make_client_mock({1: 'holding'})

        with patch('device_discovery._PYMODBUS_AVAILABLE', True), \
             patch('device_discovery._CfpModbusTcpClient', return_value=mock_client):
            result = discovery.scan_cfp('192.168.1.30', backplane_model='cFP-1804')

        slot1 = result['slots'][0]
        assert slot1['populated'] is True
        assert slot1['category'] == 'analog_output'
        assert slot1['register_type'] == 'holding'

    def test_scan_cfp_empty_slot(self):
        """Slot with no responding registers is detected as empty."""
        discovery = DeviceDiscovery()
        mock_client = _make_client_mock({})  # No slots respond

        with patch('device_discovery._PYMODBUS_AVAILABLE', True), \
             patch('device_discovery._CfpModbusTcpClient', return_value=mock_client):
            result = discovery.scan_cfp('192.168.1.30', backplane_model='cFP-1804')

        assert result['success'] is True
        for slot in result['slots']:
            assert slot['populated'] is False
            assert slot['category'] == ''
        assert 'Found 0 populated slots out of 4' in result['message']

    def test_scan_cfp_connection_failure(self):
        """Connection failure returns success=False."""
        discovery = DeviceDiscovery()
        mock_client = MagicMock()
        mock_client.connect.return_value = False

        with patch('device_discovery._PYMODBUS_AVAILABLE', True), \
             patch('device_discovery._CfpModbusTcpClient', return_value=mock_client):
            result = discovery.scan_cfp('192.168.1.99')

        assert result['success'] is False
        assert 'Cannot connect' in result['message']
        assert result['slots'] == []

    def test_scan_cfp_mixed_backplane(self):
        """Multiple populated and empty slots detected correctly."""
        discovery = DeviceDiscovery()
        mock_client = _make_client_mock({
            1: 'input',      # AI module
            3: 'coil',       # DO module
            5: 'discrete',   # DI module
            7: 'holding',    # AO module
        })

        with patch('device_discovery._PYMODBUS_AVAILABLE', True), \
             patch('device_discovery._CfpModbusTcpClient', return_value=mock_client):
            result = discovery.scan_cfp('192.168.1.30', backplane_model='cFP-1808')

        assert result['success'] is True
        assert len(result['slots']) == 8

        populated = [s for s in result['slots'] if s['populated']]
        empty = [s for s in result['slots'] if not s['populated']]
        assert len(populated) == 4
        assert len(empty) == 4

        assert result['slots'][0]['category'] == 'analog_input'
        assert result['slots'][2]['category'] == 'digital_output'
        assert result['slots'][4]['category'] == 'digital_input'
        assert result['slots'][6]['category'] == 'analog_output'

        assert 'Found 4 populated slots out of 8' in result['message']

    def test_scan_cfp_no_pymodbus(self):
        """Graceful failure when pymodbus is not installed."""
        discovery = DeviceDiscovery()

        with patch('device_discovery._PYMODBUS_AVAILABLE', False):
            result = discovery.scan_cfp('192.168.1.30')

        assert result['success'] is False
        assert 'not available' in result['message'].lower()

    def test_scan_cfp_4_slot_backplane(self):
        """cFP-1804 probes only 4 slots."""
        discovery = DeviceDiscovery()
        mock_client = _make_client_mock({1: 'input', 4: 'coil'})

        with patch('device_discovery._PYMODBUS_AVAILABLE', True), \
             patch('device_discovery._CfpModbusTcpClient', return_value=mock_client):
            result = discovery.scan_cfp('192.168.1.30', backplane_model='cFP-1804')

        assert result['success'] is True
        assert len(result['slots']) == 4
        assert result['slots'][0]['populated'] is True
        assert result['slots'][3]['populated'] is True
        assert 'Found 2 populated slots out of 4' in result['message']

    def test_scan_cfp_unknown_backplane_defaults_to_8(self):
        """Unknown backplane model defaults to 8 slots."""
        discovery = DeviceDiscovery()
        mock_client = _make_client_mock({})

        with patch('device_discovery._PYMODBUS_AVAILABLE', True), \
             patch('device_discovery._CfpModbusTcpClient', return_value=mock_client):
            result = discovery.scan_cfp('192.168.1.30', backplane_model='cFP-UNKNOWN')

        assert result['success'] is True
        assert len(result['slots']) == 8

    def test_scan_cfp_result_metadata(self):
        """Result includes connection metadata."""
        discovery = DeviceDiscovery()
        mock_client = _make_client_mock({})

        with patch('device_discovery._PYMODBUS_AVAILABLE', True), \
             patch('device_discovery._CfpModbusTcpClient', return_value=mock_client):
            result = discovery.scan_cfp(
                '10.0.0.50', port=503, slave_id=2,
                backplane_model='cFP-2020', device_name='Furnace1'
            )

        assert result['ip_address'] == '10.0.0.50'
        assert result['port'] == 503
        assert result['backplane_model'] == 'cFP-2020'
        assert result['device_name'] == 'Furnace1'

    def test_scan_cfp_exception_during_probe(self):
        """Exceptions during individual reads don't crash the scan."""
        discovery = DeviceDiscovery()
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        # All reads raise exceptions
        mock_client.read_input_registers.side_effect = Exception("timeout")
        mock_client.read_holding_registers.side_effect = Exception("timeout")
        mock_client.read_discrete_inputs.side_effect = Exception("timeout")
        mock_client.read_coils.side_effect = Exception("timeout")

        with patch('device_discovery._PYMODBUS_AVAILABLE', True), \
             patch('device_discovery._CfpModbusTcpClient', return_value=mock_client):
            result = discovery.scan_cfp('192.168.1.30', backplane_model='cFP-1804')

        assert result['success'] is True
        for slot in result['slots']:
            assert slot['populated'] is False


class TestCFPBackplaneDatabase:
    """Tests for the CFP backplane database."""

    def test_all_backplanes_have_slots(self):
        """Every backplane in the database has a slots count."""
        for model, info in CFP_BACKPLANES.items():
            assert 'slots' in info, f"{model} missing 'slots'"
            assert info['slots'] in (4, 8), f"{model} has invalid slot count: {info['slots']}"

    def test_known_backplanes(self):
        """All four known backplane models are present."""
        assert 'cFP-1804' in CFP_BACKPLANES
        assert 'cFP-1808' in CFP_BACKPLANES
        assert 'cFP-2020' in CFP_BACKPLANES
        assert 'cFP-2120' in CFP_BACKPLANES

    def test_slot_register_offset(self):
        """Slot register offset is 100."""
        assert CFP_SLOT_REGISTER_OFFSET == 100
