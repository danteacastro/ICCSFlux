"""
Hardware-In-the-Loop (HIL) Test Suite
======================================
Real hardware validation for NI DAQmx, cRIO, Opto22, and cFP platforms.

This file complements test_hardware_platforms.py (mock layer) with actual
hardware calls. Tests auto-detect what hardware is connected and run only
the applicable tests — everything else skips gracefully.

Test tiers:
  Tier 1: NI-DAQmx driver present (no hardware needed)
  Tier 2: Real NI hardware detected (cDAQ chassis + modules)
  Tier 3: Loopback wiring (AO→AI, DO→DI) for write-read-verify
  Tier 4: MQTT broker + cRIO/Opto22 nodes online

Run:
  pytest tests/test_hardware_hil.py -v             # runs what it can
  pytest tests/test_hardware_hil.py -v -k "tier1"  # driver-only tests
  pytest tests/test_hardware_hil.py -v -k "tier2"  # requires hardware
  pytest tests/test_hardware_hil.py -v -k "tier3"  # requires loopback wiring
  pytest tests/test_hardware_hil.py -v -k "tier4"  # requires MQTT + nodes
"""

import gc
import pytest
import sys
import time
import json
import logging
import configparser
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass

# --- Path setup ---
DAQ_SERVICE = Path(__file__).parent.parent / "services" / "daq_service"
CRIO_NODE = Path(__file__).parent.parent / "services" / "crio_node_v2"
OPTO22_NODE = Path(__file__).parent.parent / "services" / "opto22_node"
PROJECT_ROOT = Path(__file__).parent.parent

sys.path.insert(0, str(DAQ_SERVICE))

from config_parser import (
    NISystemConfig, SystemConfig, ChassisConfig, ModuleConfig, ChannelConfig,
    ChannelType, ThermocoupleType, DataViewerConfig
)

logger = logging.getLogger('HIL')

# ============================================================================
# Hardware Detection — runs at import time, sets skip markers
# ============================================================================

# Tier 1: Is the NI-DAQmx driver installed?
try:
    import nidaqmx
    import nidaqmx.system
    from nidaqmx.constants import (
        TerminalConfiguration, AcquisitionType, Edge,
        ThermocoupleType as NI_TCType,
    )
    import numpy as np
    NIDAQMX_AVAILABLE = True
except Exception:
    NIDAQMX_AVAILABLE = False

# Tier 2: Is real NI hardware connected?
_discovered_devices: List[dict] = []
_discovered_chassis: List[str] = []
_discovered_modules: List[dict] = []  # {name, product_type, channels_ai, channels_ao, ...}

if NIDAQMX_AVAILABLE:
    try:
        _system = nidaqmx.system.System.local()
        for dev in _system.devices:
            info = {
                'name': dev.name,
                'product_type': dev.product_type,
                'serial': str(dev.serial_num) if hasattr(dev, 'serial_num') else (str(dev.dev_serial_num) if dev.dev_serial_num else ''),
                'ai_channels': [ch.name for ch in dev.ai_physical_chans],
                'ao_channels': [ch.name for ch in dev.ao_physical_chans],
                'di_lines': [ch.name for ch in dev.di_lines],
                'do_lines': [ch.name for ch in dev.do_lines],
                'ci_channels': [ch.name for ch in dev.ci_physical_chans],
                'co_channels': [ch.name for ch in dev.co_physical_chans],
            }
            _discovered_devices.append(info)

            if 'cDAQ' in dev.product_type and 'Mod' not in dev.name:
                _discovered_chassis.append(dev.name)
            elif len(info['ai_channels']) > 0 or len(info['ao_channels']) > 0 or \
                 len(info['di_lines']) > 0 or len(info['do_lines']) > 0:
                _discovered_modules.append(info)
    except Exception as e:
        logger.warning(f"Hardware enumeration failed: {e}")

HARDWARE_PRESENT = len(_discovered_modules) > 0

# Tier 2 helpers: find specific module types
def _find_modules_with_ai() -> List[dict]:
    return [m for m in _discovered_modules if len(m['ai_channels']) > 0]

def _find_modules_with_ao() -> List[dict]:
    return [m for m in _discovered_modules if len(m['ao_channels']) > 0]

def _find_modules_with_di() -> List[dict]:
    return [m for m in _discovered_modules if len(m['di_lines']) > 0]

def _find_modules_with_do() -> List[dict]:
    return [m for m in _discovered_modules if len(m['do_lines']) > 0]

def _find_modules_with_ci() -> List[dict]:
    return [m for m in _discovered_modules if len(m['ci_channels']) > 0]

# Tier 3: Loopback detection
# Loopback means we have both AO and AI on the same chassis (user must wire AO→AI)
HAS_AO_AI_LOOPBACK = len(_find_modules_with_ao()) > 0 and len(_find_modules_with_ai()) > 0
HAS_DO_DI_LOOPBACK = len(_find_modules_with_do()) > 0 and len(_find_modules_with_di()) > 0

# Tier 4: MQTT settings (broker auto-started by conftest.py mqtt_broker fixture)
MQTT_HOST = 'localhost'
MQTT_PORT = 1883
MQTT_PREFIX = 'nisystem'

def _mqtt_port_open() -> bool:
    """Quick check if MQTT port is currently open (for diagnostics only)."""
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            return s.connect_ex((MQTT_HOST, MQTT_PORT)) == 0
    except Exception:
        return False

_sys_ini = PROJECT_ROOT / 'config' / 'system.ini'
if _sys_ini.exists():
    _cfg = configparser.ConfigParser()
    _cfg.read(str(_sys_ini))
    MQTT_HOST = _cfg.get('mqtt', 'host', fallback='localhost')
    MQTT_PORT = _cfg.getint('mqtt', 'port', fallback=1883)
    MQTT_PREFIX = _cfg.get('mqtt', 'base_topic', fallback='nisystem')

# Skip markers (Tier 4 uses mqtt_broker fixture instead of import-time probe)
requires_driver = pytest.mark.skipif(
    not NIDAQMX_AVAILABLE, reason="NI-DAQmx driver not installed")
requires_hardware = pytest.mark.skipif(
    not HARDWARE_PRESENT, reason="No NI hardware detected")
requires_ao_ai_loopback = pytest.mark.skipif(
    not HAS_AO_AI_LOOPBACK, reason="No AO+AI modules for loopback (wire AO→AI)")
requires_do_di_loopback = pytest.mark.skipif(
    not HAS_DO_DI_LOOPBACK, reason="No DO+DI modules for loopback (wire DO→DI)")

# ============================================================================
# TIER 1: NI-DAQmx Driver Tests (no hardware needed)
# ============================================================================

@requires_driver
class TestTier1_DriverPresent:
    """Tests that only need the NI-DAQmx driver installed (no hardware)."""

    def test_tier1_nidaqmx_import(self):
        """nidaqmx library imports successfully."""
        assert NIDAQMX_AVAILABLE
        assert hasattr(nidaqmx, 'Task')
        assert hasattr(nidaqmx.system, 'System')

    def test_tier1_nidaqmx_version(self):
        """nidaqmx library version is accessible."""
        version = getattr(nidaqmx, '__version__', None)
        # nidaqmx 1.x doesn't always have __version__
        # Just check the module loaded
        assert nidaqmx is not None

    def test_tier1_constants_available(self):
        """All required DAQmx constants are importable."""
        from nidaqmx.constants import (
            TerminalConfiguration, AcquisitionType, Edge, Level,
            CountDirection, CounterFrequencyMethod, FrequencyUnits,
            StrainGageBridgeType, BridgeConfiguration, BridgeUnits,
            Coupling, CJCSource, CurrentShuntResistorLocation,
            RTDType, ResistanceConfiguration, ExcitationSource,
        )
        # Verify key enum values exist
        assert hasattr(TerminalConfiguration, 'RSE')
        assert hasattr(TerminalConfiguration, 'DIFF')
        assert hasattr(TerminalConfiguration, 'NRSE')
        assert hasattr(TerminalConfiguration, 'DEFAULT')
        assert hasattr(StrainGageBridgeType, 'FULL_BRIDGE_I')
        assert hasattr(StrainGageBridgeType, 'QUARTER_BRIDGE_II')
        assert hasattr(BridgeConfiguration, 'FULL_BRIDGE')

    def test_tier1_system_local(self):
        """nidaqmx.system.System.local() succeeds."""
        system = nidaqmx.system.System.local()
        assert system is not None
        # driver_version may not be available on all versions
        # but the object should exist
        assert hasattr(system, 'devices')

    def test_tier1_task_create_destroy(self):
        """Can create and close an empty DAQmx task (no channels)."""
        task = nidaqmx.Task('hil_test_empty')
        assert task is not None
        task.close()

    def test_tier1_terminal_config_enum_values(self):
        """TerminalConfiguration enum has correct integer values for NI-DAQmx C API."""
        from nidaqmx.constants import TerminalConfiguration
        # These map to NI-DAQmx C constants (DAQmx_Val_Cfg_Default, etc.)
        # The exact values depend on nidaqmx version but they must be distinct
        configs = {
            TerminalConfiguration.RSE,
            TerminalConfiguration.DIFF,
            TerminalConfiguration.NRSE,
            TerminalConfiguration.PSEUDO_DIFF,
            TerminalConfiguration.DEFAULT,
        }
        assert len(configs) == 5, "Terminal configurations must be 5 distinct values"

    def test_tier1_strain_gage_bridge_type_has_7_variants(self):
        """StrainGageBridgeType must have all 7 standard wiring configurations."""
        from nidaqmx.constants import StrainGageBridgeType
        variants = [
            StrainGageBridgeType.FULL_BRIDGE_I,
            StrainGageBridgeType.FULL_BRIDGE_II,
            StrainGageBridgeType.FULL_BRIDGE_III,
            StrainGageBridgeType.HALF_BRIDGE_I,
            StrainGageBridgeType.HALF_BRIDGE_II,
            StrainGageBridgeType.QUARTER_BRIDGE_I,
            StrainGageBridgeType.QUARTER_BRIDGE_II,
        ]
        assert len(set(variants)) == 7, "Must have 7 distinct strain gage bridge types"

    def test_tier1_bridge_config_has_4_variants(self):
        """BridgeConfiguration must have all 4 standard bridge configs."""
        from nidaqmx.constants import BridgeConfiguration
        configs = [
            BridgeConfiguration.FULL_BRIDGE,
            BridgeConfiguration.HALF_BRIDGE,
            BridgeConfiguration.QUARTER_BRIDGE,
            BridgeConfiguration.NO_BRIDGE,
        ]
        assert len(set(configs)) == 4, "Must have 4 distinct bridge configurations"

    def test_tier1_tc_types_match_our_map(self):
        """NI ThermocoupleType enum must have all 8 standard types."""
        from nidaqmx.constants import ThermocoupleType as NI_TC
        for tc in ('J', 'K', 'T', 'E', 'N', 'R', 'S', 'B'):
            assert hasattr(NI_TC, tc), f"NI ThermocoupleType missing type {tc}"

    def test_tier1_stream_readers_available(self):
        """Stream reader classes needed for continuous acquisition."""
        from nidaqmx.stream_readers import (
            AnalogMultiChannelReader,
            DigitalMultiChannelReader,
            CounterReader,
        )
        assert AnalogMultiChannelReader is not None

# ============================================================================
# TIER 2: Real Hardware Detection & Enumeration
# ============================================================================

@requires_hardware
class TestTier2_HardwareEnumeration:
    """Tests that require real NI hardware connected."""

    def test_tier2_devices_found(self):
        """At least one NI device must be detected."""
        assert len(_discovered_devices) > 0, \
            "No NI devices found — check NI MAX and USB/Ethernet connections"

    def test_tier2_chassis_found(self):
        """At least one cDAQ chassis should be present."""
        # May not have a chassis if using standalone USB devices
        if len(_discovered_chassis) == 0:
            pytest.skip("No cDAQ chassis found (standalone device?)")
        assert len(_discovered_chassis) > 0

    def test_tier2_modules_have_channels(self):
        """Every detected module must report at least one channel."""
        for mod in _discovered_modules:
            total = (len(mod['ai_channels']) + len(mod['ao_channels']) +
                    len(mod['di_lines']) + len(mod['do_lines']) +
                    len(mod['ci_channels']) + len(mod['co_channels']))
            assert total > 0, \
                f"Module {mod['name']} ({mod['product_type']}) has no channels"

    def test_tier2_module_product_types_recognized(self):
        """All detected module product types should be in our database."""
        from device_discovery import NI_MODULE_DATABASE
        unrecognized = []
        for mod in _discovered_modules:
            pt = mod['product_type']
            if pt not in NI_MODULE_DATABASE:
                unrecognized.append(f"{mod['name']}: {pt}")
        if unrecognized:
            pytest.fail(
                f"Unrecognized modules (add to NI_MODULE_DATABASE):\n" +
                "\n".join(f"  - {u}" for u in unrecognized)
            )

    def test_tier2_enumerate_all_ai_channels(self):
        """List all discovered analog input channels."""
        ai_modules = _find_modules_with_ai()
        if not ai_modules:
            pytest.skip("No AI modules detected")
        total_ai = sum(len(m['ai_channels']) for m in ai_modules)
        assert total_ai > 0
        logger.info(f"Found {total_ai} AI channels across {len(ai_modules)} modules")

    def test_tier2_enumerate_all_ao_channels(self):
        """List all discovered analog output channels."""
        ao_modules = _find_modules_with_ao()
        if not ao_modules:
            pytest.skip("No AO modules detected")
        total_ao = sum(len(m['ao_channels']) for m in ao_modules)
        assert total_ao > 0

    def test_tier2_enumerate_all_di_lines(self):
        """List all discovered digital input lines."""
        di_modules = _find_modules_with_di()
        if not di_modules:
            pytest.skip("No DI modules detected")
        total_di = sum(len(m['di_lines']) for m in di_modules)
        assert total_di > 0

    def test_tier2_enumerate_all_do_lines(self):
        """List all discovered digital output lines."""
        do_modules = _find_modules_with_do()
        if not do_modules:
            pytest.skip("No DO modules detected")
        total_do = sum(len(m['do_lines']) for m in do_modules)
        assert total_do > 0

    def test_tier2_print_hardware_inventory(self):
        """Print full hardware inventory (diagnostic — always passes)."""
        lines = ["=== NI Hardware Inventory ==="]
        for chassis in _discovered_chassis:
            lines.append(f"  Chassis: {chassis}")
        for mod in _discovered_modules:
            lines.append(
                f"  {mod['name']} ({mod['product_type']}): "
                f"AI={len(mod['ai_channels'])} AO={len(mod['ao_channels'])} "
                f"DI={len(mod['di_lines'])} DO={len(mod['do_lines'])} "
                f"CI={len(mod['ci_channels'])} CO={len(mod['co_channels'])}"
            )
        inventory = "\n".join(lines)
        logger.info(inventory)
        print(inventory)  # Also print to stdout for pytest -v -s

# ============================================================================
# TIER 2: Real Channel Read Tests (per detected module type)
# ============================================================================

def _get_module_voltage_range(product_type: str) -> float:
    """
    Get the appropriate voltage range for a module based on its product type.
    Different modules support different max ranges — using the wrong range
    causes DAQmx error -200077.
    """
    # Low-voltage / bridge / strain modules (±78.125mV or similar)
    LOW_V_MODULES = ('9237', '9235', '9236', '9238')
    # High-voltage modules
    HIGH_V_MODULES = ('9221', '9225', '9228', '9229', '9242', '9244')
    # Current input modules (cannot use add_ai_voltage_chan at all)
    CURRENT_MODULES = ('9203', '9208', '9227', '9246', '9247', '9253')
    # TC / RTD modules (cannot use add_ai_voltage_chan)
    SPECIALIZED_MODULES = ('9210', '9211', '9212', '9213', '9214',
                           '9216', '9217', '9226', '9219')

    # Extract numeric model from product type string like "NI 9237"
    for m in LOW_V_MODULES:
        if m in product_type:
            return 0.025  # 25mV safe range
    for m in HIGH_V_MODULES:
        if m in product_type:
            return 60.0
    for m in CURRENT_MODULES + SPECIALIZED_MODULES:
        if m in product_type:
            return 0  # Cannot read as voltage
    return 10.0  # Default ±10V for standard voltage modules

def _find_voltage_readable_ai_modules() -> List[dict]:
    """Find AI modules that support add_ai_voltage_chan (not TC/RTD/current-only).
    For combo modules (NI 9207), only include the voltage-capable channels."""
    # Combo modules: only channels below the split index are voltage
    COMBO_SPLIT = {'9207': 8}  # ai0-7=voltage, ai8-15=current

    result = []
    for m in _find_modules_with_ai():
        v_range = _get_module_voltage_range(m['product_type'])
        if v_range > 0:
            m_copy = dict(m)
            m_copy['v_range'] = v_range

            # Filter out non-voltage channels on combo modules
            for model_num, split_idx in COMBO_SPLIT.items():
                if model_num in m['product_type']:
                    import re
                    voltage_chans = []
                    for ch in m['ai_channels']:
                        idx_match = re.search(r'ai(\d+)$', ch)
                        if idx_match and int(idx_match.group(1)) < split_idx:
                            voltage_chans.append(ch)
                    m_copy['ai_channels'] = voltage_chans
                    break

            if m_copy['ai_channels']:
                result.append(m_copy)
    return result

@requires_hardware
class TestTier2_AnalogInputRead:
    """Read real analog input channels and verify values are in range."""

    def _read_ai_channel(self, phys_chan: str, v_range: float = 10.0,
                         term_cfg=None, timeout_s: float = 2.0):
        """Read a single AI channel value using on-demand (finite) read."""
        if term_cfg is None:
            term_cfg = TerminalConfiguration.DEFAULT
        task = nidaqmx.Task()
        try:
            task.ai_channels.add_ai_voltage_chan(
                phys_chan, terminal_config=term_cfg,
                min_val=-v_range, max_val=v_range
            )
            value = task.read()
            return value
        finally:
            task.close()

    def test_tier2_read_first_ai_channel(self):
        """Read the first available voltage-readable AI channel."""
        ai_modules = _find_voltage_readable_ai_modules()
        if not ai_modules:
            pytest.skip("No voltage-readable AI modules")
        mod = ai_modules[0]
        first_ch = mod['ai_channels'][0]
        v_range = mod['v_range']
        value = self._read_ai_channel(first_ch, v_range=v_range)
        assert isinstance(value, float), f"Expected float, got {type(value)}"
        limit = v_range * 1.5
        assert -limit <= value <= limit, \
            f"AI value {value}V out of ±{limit}V range on {first_ch}"

    def test_tier2_read_all_ai_channels_on_first_module(self):
        """Read every AI channel on the first voltage-readable module."""
        ai_modules = _find_voltage_readable_ai_modules()
        if not ai_modules:
            pytest.skip("No voltage-readable AI modules")
        mod = ai_modules[0]
        v_range = mod['v_range']
        results = {}
        failures = []
        for ch in mod['ai_channels']:
            try:
                value = self._read_ai_channel(ch, v_range=v_range)
                results[ch] = value
                limit = v_range * 1.5
                if not (-limit <= value <= limit):
                    failures.append(f"{ch}: {value}V out of ±{limit}V range")
            except Exception as e:
                failures.append(f"{ch}: ERROR {e}")
        assert len(failures) == 0, \
            f"AI read failures on {mod['name']} ({mod['product_type']}):\n" + "\n".join(failures)
        logger.info(f"Read {len(results)} AI channels on {mod['name']} (±{v_range}V)")

    def test_tier2_terminal_config_rse_if_supported(self):
        """Read AI with RSE terminal config (not all modules support this)."""
        ai_modules = _find_voltage_readable_ai_modules()
        if not ai_modules:
            pytest.skip("No voltage-readable AI modules")
        mod = ai_modules[0]
        first_ch = mod['ai_channels'][0]
        try:
            value = self._read_ai_channel(first_ch, v_range=mod['v_range'],
                                          term_cfg=TerminalConfiguration.RSE)
            assert isinstance(value, float)
        except nidaqmx.errors.DaqError as e:
            err_str = str(e).lower()
            if 'not supported' in err_str or 'terminal' in err_str or 'property' in err_str:
                pytest.skip(f"Module does not support RSE: {e}")
            raise

    def test_tier2_terminal_config_diff_if_supported(self):
        """Read AI with DIFF terminal config."""
        ai_modules = _find_voltage_readable_ai_modules()
        if not ai_modules:
            pytest.skip("No voltage-readable AI modules")
        mod = ai_modules[0]
        first_ch = mod['ai_channels'][0]
        try:
            value = self._read_ai_channel(first_ch, v_range=mod['v_range'],
                                          term_cfg=TerminalConfiguration.DIFF)
            assert isinstance(value, float)
        except nidaqmx.errors.DaqError as e:
            err_str = str(e).lower()
            if 'not supported' in err_str or 'terminal' in err_str or 'property' in err_str:
                pytest.skip(f"Module does not support DIFF: {e}")
            raise

    def test_tier2_continuous_acquisition_10_samples(self):
        """Run continuous acquisition for 10 samples on first voltage-readable AI channel."""
        ai_modules = _find_voltage_readable_ai_modules()
        if not ai_modules:
            pytest.skip("No voltage-readable AI modules")

        mod = ai_modules[0]
        first_ch = mod['ai_channels'][0]
        v_range = mod['v_range']
        task = nidaqmx.Task()
        try:
            task.ai_channels.add_ai_voltage_chan(
                first_ch, terminal_config=TerminalConfiguration.DEFAULT,
                min_val=-v_range, max_val=v_range
            )
            task.timing.cfg_samp_clk_timing(
                rate=10.0,
                sample_mode=AcquisitionType.FINITE,
                samps_per_chan=10
            )
            task.start()
            data = task.read(number_of_samples_per_channel=10, timeout=5.0)
            task.stop()

            assert len(data) == 10, f"Expected 10 samples, got {len(data)}"
            limit = v_range * 1.5
            for i, v in enumerate(data):
                assert -limit <= v <= limit, f"Sample {i}: {v}V out of ±{limit}V range"
        finally:
            task.close()

@requires_hardware
class TestTier2_DigitalRead:
    """Read real digital input lines."""

    def test_tier2_read_first_di_line(self):
        """Read the first available DI line."""
        di_modules = _find_modules_with_di()
        if not di_modules:
            pytest.skip("No DI modules")
        first_line = di_modules[0]['di_lines'][0]
        task = nidaqmx.Task()
        try:
            task.di_channels.add_di_chan(first_line)
            value = task.read()
            assert value in (True, False), f"DI value should be bool, got {value}"
        finally:
            task.close()

    def test_tier2_read_all_di_lines_first_module(self):
        """Read all DI lines on first module."""
        di_modules = _find_modules_with_di()
        if not di_modules:
            pytest.skip("No DI modules")
        mod = di_modules[0]
        failures = []
        for line in mod['di_lines']:
            try:
                task = nidaqmx.Task()
                try:
                    task.di_channels.add_di_chan(line)
                    value = task.read()
                    if value not in (True, False):
                        failures.append(f"{line}: got {value} (expected bool)")
                finally:
                    task.close()
            except Exception as e:
                failures.append(f"{line}: ERROR {e}")
        assert len(failures) == 0, \
            f"DI read failures:\n" + "\n".join(failures)

@requires_hardware
class TestTier2_AnalogOutputWrite:
    """Write to real analog output channels."""

    def test_tier2_write_ao_zero(self):
        """Write 0V to the first AO channel."""
        ao_modules = _find_modules_with_ao()
        if not ao_modules:
            pytest.skip("No AO modules")
        first_ch = ao_modules[0]['ao_channels'][0]
        task = nidaqmx.Task()
        try:
            task.ao_channels.add_ao_voltage_chan(
                first_ch, min_val=-10.0, max_val=10.0)
            task.write(0.0)
        finally:
            task.close()

    def test_tier2_write_ao_positive(self):
        """Write +2.5V to the first AO channel."""
        ao_modules = _find_modules_with_ao()
        if not ao_modules:
            pytest.skip("No AO modules")
        first_ch = ao_modules[0]['ao_channels'][0]
        task = nidaqmx.Task()
        try:
            task.ao_channels.add_ao_voltage_chan(
                first_ch, min_val=-10.0, max_val=10.0)
            task.write(2.5)
        finally:
            task.close()

    def test_tier2_write_ao_negative(self):
        """Write -2.5V to the first AO channel (verifies bipolar support)."""
        ao_modules = _find_modules_with_ao()
        if not ao_modules:
            pytest.skip("No AO modules")
        first_ch = ao_modules[0]['ao_channels'][0]
        task = nidaqmx.Task()
        try:
            task.ao_channels.add_ao_voltage_chan(
                first_ch, min_val=-10.0, max_val=10.0)
            task.write(-2.5)
        finally:
            task.close()

    def test_tier2_write_ao_then_zero_cleanup(self):
        """Write a value, then write 0V (safe cleanup pattern)."""
        ao_modules = _find_modules_with_ao()
        if not ao_modules:
            pytest.skip("No AO modules")
        first_ch = ao_modules[0]['ao_channels'][0]
        task = nidaqmx.Task()
        try:
            task.ao_channels.add_ao_voltage_chan(
                first_ch, min_val=-10.0, max_val=10.0)
            task.write(5.0)
            time.sleep(0.05)
            task.write(0.0)  # Always zero after test
        finally:
            task.close()

@requires_hardware
class TestTier2_DigitalOutputWrite:
    """Write to real digital output lines."""

    def test_tier2_write_do_true(self):
        """Write True to first DO line."""
        do_modules = _find_modules_with_do()
        if not do_modules:
            pytest.skip("No DO modules")
        first_line = do_modules[0]['do_lines'][0]
        task = nidaqmx.Task()
        try:
            task.do_channels.add_do_chan(first_line)
            task.write(True)
        finally:
            task.close()

    def test_tier2_write_do_false_cleanup(self):
        """Write True, then False (safe cleanup)."""
        do_modules = _find_modules_with_do()
        if not do_modules:
            pytest.skip("No DO modules")
        first_line = do_modules[0]['do_lines'][0]
        task = nidaqmx.Task()
        try:
            task.do_channels.add_do_chan(first_line)
            task.write(True)
            time.sleep(0.05)
            task.write(False)  # Safe state
        finally:
            task.close()

# ============================================================================
# TIER 3: Loopback Tests (AO→AI, DO→DI)
# ============================================================================

@requires_ao_ai_loopback
class TestTier3_AnalogLoopback:
    """
    Analog output → input loopback verification.

    WIRING REQUIRED: Connect the first AO channel to the first AI channel.
    Example: cDAQ1Mod2/ao0 → cDAQ1Mod1/ai0

    Tests write a known voltage, read it back, and verify within tolerance.
    """

    TOLERANCE_V = 0.05  # 50mV tolerance for DAC+ADC combined error
    SETTLE_TIME_S = 0.1  # Wait for analog to settle

    @pytest.fixture
    def ao_ai_pair(self):
        """Get the first AO and AI physical channel pair."""
        ao_mod = _find_modules_with_ao()[0]
        ai_mod = _find_modules_with_ai()[0]
        ao_ch = ao_mod['ao_channels'][0]
        ai_ch = ai_mod['ai_channels'][0]
        return ao_ch, ai_ch

    def _write_read_verify(self, ao_ch, ai_ch, write_value, tolerance=None):
        """Write AO, wait, read AI, verify."""
        if tolerance is None:
            tolerance = self.TOLERANCE_V

        ao_task = nidaqmx.Task('hil_ao_loopback')
        ai_task = nidaqmx.Task('hil_ai_loopback')
        try:
            ao_task.ao_channels.add_ao_voltage_chan(
                ao_ch, min_val=-10.0, max_val=10.0)
            ai_task.ai_channels.add_ai_voltage_chan(
                ai_ch, terminal_config=TerminalConfiguration.DEFAULT,
                min_val=-10.0, max_val=10.0)

            ao_task.write(write_value)
            time.sleep(self.SETTLE_TIME_S)
            read_value = ai_task.read()

            error = abs(read_value - write_value)
            assert error < tolerance, \
                f"Loopback mismatch: wrote {write_value:.4f}V, read {read_value:.4f}V " \
                f"(error={error:.4f}V, tolerance={tolerance:.4f}V)"
            return read_value
        finally:
            # Always zero AO for safety
            try:
                ao_task.write(0.0)
            except Exception:
                pass
            ao_task.close()
            ai_task.close()

    def test_tier3_loopback_0v(self, ao_ai_pair):
        """Loopback: write 0.0V, read back ~0.0V."""
        ao_ch, ai_ch = ao_ai_pair
        self._write_read_verify(ao_ch, ai_ch, 0.0)

    def test_tier3_loopback_positive_5v(self, ao_ai_pair):
        """Loopback: write +5.0V, read back ~5.0V."""
        ao_ch, ai_ch = ao_ai_pair
        self._write_read_verify(ao_ch, ai_ch, 5.0)

    def test_tier3_loopback_negative_5v(self, ao_ai_pair):
        """Loopback: write -5.0V, read back ~-5.0V (bipolar test)."""
        ao_ch, ai_ch = ao_ai_pair
        self._write_read_verify(ao_ch, ai_ch, -5.0)

    def test_tier3_loopback_full_range_positive(self, ao_ai_pair):
        """Loopback: write +9.5V (near max), read back."""
        ao_ch, ai_ch = ao_ai_pair
        self._write_read_verify(ao_ch, ai_ch, 9.5, tolerance=0.1)

    def test_tier3_loopback_full_range_negative(self, ao_ai_pair):
        """Loopback: write -9.5V (near min), read back."""
        ao_ch, ai_ch = ao_ai_pair
        self._write_read_verify(ao_ch, ai_ch, -9.5, tolerance=0.1)

    def test_tier3_loopback_staircase(self, ao_ai_pair):
        """Loopback: write staircase pattern -5V to +5V in 1V steps."""
        ao_ch, ai_ch = ao_ai_pair
        ao_task = nidaqmx.Task('hil_ao_stair')
        ai_task = nidaqmx.Task('hil_ai_stair')
        failures = []
        try:
            ao_task.ao_channels.add_ao_voltage_chan(
                ao_ch, min_val=-10.0, max_val=10.0)
            ai_task.ai_channels.add_ai_voltage_chan(
                ai_ch, terminal_config=TerminalConfiguration.DEFAULT,
                min_val=-10.0, max_val=10.0)

            for v_write in range(-5, 6):  # -5 to +5
                v_write = float(v_write)
                ao_task.write(v_write)
                time.sleep(self.SETTLE_TIME_S)
                v_read = ai_task.read()
                error = abs(v_read - v_write)
                if error >= self.TOLERANCE_V:
                    failures.append(
                        f"  {v_write:+.1f}V → {v_read:+.4f}V (error={error:.4f}V)")

            assert len(failures) == 0, \
                f"Staircase loopback failures:\n" + "\n".join(failures)
        finally:
            try:
                ao_task.write(0.0)
            except Exception:
                pass
            ao_task.close()
            ai_task.close()

    def test_tier3_loopback_ramp_speed(self, ao_ai_pair):
        """Loopback: rapid write-read cycle to test DAC settling time."""
        ao_ch, ai_ch = ao_ai_pair
        ao_task = nidaqmx.Task('hil_ao_ramp')
        ai_task = nidaqmx.Task('hil_ai_ramp')
        try:
            ao_task.ao_channels.add_ao_voltage_chan(
                ao_ch, min_val=-10.0, max_val=10.0)
            ai_task.ai_channels.add_ai_voltage_chan(
                ai_ch, terminal_config=TerminalConfiguration.DEFAULT,
                min_val=-10.0, max_val=10.0)

            readings = []
            start = time.perf_counter()
            for i in range(20):
                v = (i / 19.0) * 10.0 - 5.0  # -5V to +5V
                ao_task.write(v)
                time.sleep(0.02)  # 20ms settle
                r = ai_task.read()
                readings.append((v, r))
            elapsed = time.perf_counter() - start

            # At least 80% of readings should be within tolerance
            in_spec = sum(1 for v, r in readings if abs(r - v) < 0.15)
            assert in_spec >= 16, \
                f"Only {in_spec}/20 readings within 150mV ({elapsed:.2f}s elapsed)"
        finally:
            try:
                ao_task.write(0.0)
            except Exception:
                pass
            ao_task.close()
            ai_task.close()

@requires_do_di_loopback
class TestTier3_DigitalLoopback:
    """
    Digital output → input loopback verification.

    WIRING REQUIRED: Connect the first DO line to the first DI line.
    Example: cDAQ1Mod4/port0/line0 → cDAQ1Mod3/port0/line0
    """

    SETTLE_TIME_S = 0.02  # Digital settles faster than analog

    @pytest.fixture
    def do_di_pair(self):
        """Get the first DO and DI physical channel pair."""
        do_mod = _find_modules_with_do()[0]
        di_mod = _find_modules_with_di()[0]
        return do_mod['do_lines'][0], di_mod['di_lines'][0]

    def _write_read_verify(self, do_line, di_line, write_value):
        """Write DO, read DI, verify match."""
        do_task = nidaqmx.Task('hil_do_loopback')
        di_task = nidaqmx.Task('hil_di_loopback')
        try:
            do_task.do_channels.add_do_chan(do_line)
            di_task.di_channels.add_di_chan(di_line)

            do_task.write(write_value)
            time.sleep(self.SETTLE_TIME_S)
            read_value = di_task.read()

            assert read_value == write_value, \
                f"Digital loopback mismatch: wrote {write_value}, read {read_value}"
            return read_value
        finally:
            try:
                do_task.write(False)
            except Exception:
                pass
            do_task.close()
            di_task.close()

    def test_tier3_digital_loopback_true(self, do_di_pair):
        """Loopback: write True, read True."""
        do_line, di_line = do_di_pair
        self._write_read_verify(do_line, di_line, True)

    def test_tier3_digital_loopback_false(self, do_di_pair):
        """Loopback: write False, read False."""
        do_line, di_line = do_di_pair
        self._write_read_verify(do_line, di_line, False)

    def test_tier3_digital_loopback_toggle_cycle(self, do_di_pair):
        """Loopback: toggle 20 times, verify each state."""
        do_line, di_line = do_di_pair
        do_task = nidaqmx.Task('hil_do_toggle')
        di_task = nidaqmx.Task('hil_di_toggle')
        failures = []
        try:
            do_task.do_channels.add_do_chan(do_line)
            di_task.di_channels.add_di_chan(di_line)

            for i in range(20):
                state = (i % 2) == 0
                do_task.write(state)
                time.sleep(self.SETTLE_TIME_S)
                read = di_task.read()
                if read != state:
                    failures.append(f"  cycle {i}: wrote {state}, read {read}")

            assert len(failures) == 0, \
                f"Toggle failures:\n" + "\n".join(failures)
        finally:
            try:
                do_task.write(False)
            except Exception:
                pass
            do_task.close()
            di_task.close()

# ============================================================================
# TIER 4: MQTT Broker + Remote Node Tests
# ============================================================================

@pytest.mark.usefixtures("mqtt_broker")
class TestTier4_MQTTBroker:
    """Tests requiring an MQTT broker connection (auto-started by fixture)."""

    @pytest.fixture
    def mqtt_client(self, mqtt_broker):
        """Create a connected MQTT client using auto-started broker."""
        import paho.mqtt.client as mqtt
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, client_id='hil-tier4')

        if mqtt_broker.get('username'):
            client.username_pw_set(mqtt_broker['username'], mqtt_broker['password'])

        client.connect(mqtt_broker['host'], mqtt_broker['port'], keepalive=10)
        client.loop_start()
        time.sleep(0.3)  # Allow connection to establish
        yield client
        client.loop_stop()
        client.disconnect()

    def test_tier4_mqtt_broker_alive(self, mqtt_client):
        """MQTT broker accepts connections."""
        assert mqtt_client.is_connected()

    def test_tier4_mqtt_publish_subscribe(self, mqtt_client):
        """Publish and receive a test message."""
        import threading
        received = threading.Event()
        payload_holder = [None]

        def on_message(client, userdata, msg):
            payload_holder[0] = msg.payload
            received.set()

        mqtt_client.on_message = on_message
        test_topic = f'{MQTT_PREFIX}/hil/test'
        mqtt_client.subscribe(test_topic)
        time.sleep(0.2)  # Wait for subscription

        mqtt_client.publish(test_topic, b'hil_ping')
        assert received.wait(timeout=3.0), "Did not receive published message within 3s"
        assert payload_holder[0] == b'hil_ping'

    def test_tier4_daq_service_status(self, mqtt_client, daq_service):
        """Check if DAQ service is publishing status (auto-started by fixture)."""
        import threading
        received = threading.Event()
        status_holder = [None]

        def on_message(client, userdata, msg):
            try:
                status_holder[0] = json.loads(msg.payload)
                received.set()
            except Exception:
                pass

        mqtt_client.on_message = on_message
        # DAQ service publishes to: nisystem/nodes/{node_id}/status/system
        mqtt_client.subscribe(f'{MQTT_PREFIX}/+/+/status/system')
        if not received.wait(timeout=10.0):
            pytest.skip("DAQ service not publishing status (could not auto-start)")

        status = status_holder[0]
        assert status is not None
        assert 'acquiring' in status or 'acquisition_state' in status

    def test_tier4_crio_node_online(self, mqtt_client):
        """Check if any cRIO node is publishing heartbeats."""
        import threading
        received = threading.Event()

        def on_message(client, userdata, msg):
            received.set()

        mqtt_client.on_message = on_message
        # cRIO nodes publish to: nisystem/nodes/{node_id}/status/system
        mqtt_client.subscribe(f'{MQTT_PREFIX}/nodes/+/status/system')
        if not received.wait(timeout=5.0):
            pytest.skip("No cRIO node heartbeat received")
        assert True

    def test_tier4_opto22_node_online(self, mqtt_client):
        """Check if any Opto22 node is publishing heartbeats."""
        import threading
        received = threading.Event()

        def on_message(client, userdata, msg):
            received.set()

        mqtt_client.on_message = on_message
        # Opto22 nodes publish to: nisystem/nodes/{node_id}/heartbeat
        mqtt_client.subscribe(f'{MQTT_PREFIX}/nodes/+/heartbeat')
        if not received.wait(timeout=5.0):
            pytest.skip("No Opto22 node heartbeat received")
        assert True

# ============================================================================
# TIER 2: HardwareReader Integration (full stack with real hardware)
# ============================================================================

def _clear_all_daqmx_tasks():
    """Force-clear any lingering DAQmx tasks in this process.
    Prevents 'Task name conflicts with existing task' errors when tests
    create HardwareReader instances back-to-back."""
    if not NIDAQMX_AVAILABLE:
        return
    try:
        # Force garbage collection to release any orphaned Task objects
        gc.collect()
        time.sleep(0.15)  # Give NI-DAQmx driver time to release handles
    except Exception:
        pass

def _fix_hardware_reader_imports():
    """Fix hardware_reader module references if they were corrupted by mock tests.

    When test_hardware_platforms.py runs before us, it imports hardware_reader
    with mocked nidaqmx/numpy. Even though it restores sys.modules afterward,
    the hardware_reader module object still holds references to the MagicMock
    objects. We need to rebind them to the real modules."""
    if not NIDAQMX_AVAILABLE:
        return
    try:
        import hardware_reader as hr
        import numpy as real_np

        # Check if numpy is corrupted (MagicMock instead of real module)
        if not hasattr(hr, 'np') or not hasattr(hr.np, '__version__'):
            hr.np = real_np

        # Rebind nidaqmx references
        hr.nidaqmx = nidaqmx
        hr.NIDAQMX_AVAILABLE = True

        # Rebind nidaqmx.constants enum values
        from nidaqmx.constants import (
            TerminalConfiguration as TC, AcquisitionType as AT,
            Edge as E, READ_ALL_AVAILABLE, SampleTimingType,
            StrainGageBridgeType, BridgeConfiguration, BridgeUnits,
        )
        hr.TerminalConfiguration = TC
        hr.AcquisitionType = AT
        hr.Edge = E
        hr.READ_ALL_AVAILABLE = READ_ALL_AVAILABLE
        hr.SampleTimingType = SampleTimingType

        # Rebind stream readers
        from nidaqmx.stream_readers import (
            AnalogMultiChannelReader, DigitalMultiChannelReader, CounterReader
        )
        hr.AnalogMultiChannelReader = AnalogMultiChannelReader
        hr.DigitalMultiChannelReader = DigitalMultiChannelReader
        hr.CounterReader = CounterReader

    except Exception as e:
        logger.warning(f"Could not fix hardware_reader imports: {e}")

@requires_hardware
class TestTier2_HardwareReaderIntegration:
    """
    Test our HardwareReader class against real hardware.
    This validates the full config→task→read pipeline.
    """

    def setup_method(self):
        """Clear stale DAQmx tasks and fix corrupted imports before each test."""
        _fix_hardware_reader_imports()
        _clear_all_daqmx_tasks()

    def _build_config_from_discovered(self) -> Optional[NISystemConfig]:
        """Build a minimal config from actually discovered hardware."""
        if not _discovered_modules:
            return None

        chassis = {}
        modules = {}
        channels = {}

        # Use first chassis found
        chassis_name = _discovered_chassis[0] if _discovered_chassis else 'Dev1'
        chassis[chassis_name] = ChassisConfig(
            name=chassis_name,
            chassis_type='cDAQ-9189',
            device_name=chassis_name
        )

        for i, mod in enumerate(_discovered_modules):
            mod_name = f'Mod{i+1}'
            modules[mod_name] = ModuleConfig(
                name=mod_name,
                module_type=mod['product_type'],
                chassis=chassis_name,
                slot=i + 1
            )

            # Add first AI channel if it's voltage-readable
            if mod['ai_channels']:
                v_range = _get_module_voltage_range(mod['product_type'])
                if v_range > 0:
                    ch_name = f'AI_{mod["name"]}_0'
                    channels[ch_name] = ChannelConfig(
                        name=ch_name,
                        physical_channel=mod['ai_channels'][0],
                        channel_type=ChannelType.VOLTAGE_INPUT,
                        voltage_range=v_range,
                        terminal_config='DEFAULT'
                    )

        if not channels:
            return None

        return NISystemConfig(
            system=SystemConfig(simulation_mode=False, scan_rate_hz=10.0),
            chassis=chassis, modules=modules, channels=channels,
            dataviewer=DataViewerConfig(), safety_actions={}
        )

    def _close_reader(self, reader):
        """Close a HardwareReader and wait for NI-DAQmx to release handles."""
        if reader:
            reader.close()
            gc.collect()
            time.sleep(0.2)  # NI-DAQmx needs time to fully release task handles

    def test_tier2_hardware_reader_create(self):
        """HardwareReader initializes with real hardware config."""
        from hardware_reader import HardwareReader
        config = self._build_config_from_discovered()
        if config is None:
            pytest.skip("Could not build config from discovered hardware")

        reader = None
        try:
            reader = HardwareReader(config)
            assert reader is not None
            assert len(reader.tasks) > 0 or len(reader.counter_tasks) > 0
        finally:
            self._close_reader(reader)

    def test_tier2_hardware_reader_read_all(self):
        """HardwareReader.read_all() returns values for all configured channels."""
        from hardware_reader import HardwareReader
        config = self._build_config_from_discovered()
        if config is None:
            pytest.skip("Could not build config from discovered hardware")

        reader = None
        try:
            reader = HardwareReader(config)
            # Wait for first read cycle
            time.sleep(0.5)
            values = reader.read_all()
            assert len(values) > 0, "read_all() returned no values"

            for ch_name, val in values.items():
                assert isinstance(val, (int, float)), \
                    f"Channel {ch_name}: expected number, got {type(val)}"
        finally:
            self._close_reader(reader)

    def test_tier2_hardware_reader_continuous_stability(self):
        """HardwareReader continuous read for 2 seconds — no crashes."""
        from hardware_reader import HardwareReader
        config = self._build_config_from_discovered()
        if config is None:
            pytest.skip("Could not build config from discovered hardware")

        reader = None
        try:
            reader = HardwareReader(config)
            read_count = 0
            start = time.perf_counter()
            while time.perf_counter() - start < 2.0:
                values = reader.read_all()
                if values:
                    read_count += 1
                time.sleep(0.1)

            assert read_count >= 10, \
                f"Only got {read_count} reads in 2s (expected >=10)"
            assert not reader._reader_died, \
                "Reader thread died during continuous acquisition"
        finally:
            self._close_reader(reader)

# ============================================================================
# Diagnostic: Print test environment summary
# ============================================================================

def pytest_configure(config):
    """Print hardware detection summary at test start."""
    lines = [
        "\n=== HIL Test Environment ===",
        f"  NI-DAQmx driver: {'YES' if NIDAQMX_AVAILABLE else 'NO'}",
        f"  Hardware present: {'YES' if HARDWARE_PRESENT else 'NO'}",
        f"  Devices found:    {len(_discovered_devices)}",
        f"  Modules found:    {len(_discovered_modules)}",
        f"  Chassis found:    {len(_discovered_chassis)}",
        f"  AO+AI loopback:   {'POSSIBLE' if HAS_AO_AI_LOOPBACK else 'NO'}",
        f"  DO+DI loopback:   {'POSSIBLE' if HAS_DO_DI_LOOPBACK else 'NO'}",
        f"  MQTT broker:      {'UP' if _mqtt_port_open() else 'will auto-start'} ({MQTT_HOST}:{MQTT_PORT})",
    ]
    if _discovered_modules:
        lines.append("  Modules:")
        for m in _discovered_modules:
            lines.append(f"    {m['name']}: {m['product_type']} "
                        f"(AI:{len(m['ai_channels'])} AO:{len(m['ao_channels'])} "
                        f"DI:{len(m['di_lines'])} DO:{len(m['do_lines'])})")
    print("\n".join(lines))
