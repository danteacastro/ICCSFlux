"""
Reset-on-read (totalizer) counter tests.

The reset-on-read flag makes a count-mode counter report the edges accrued
since the previous read_all() instead of the running total. The delta is
computed in software at the single read_all() consumption point — the
hardware/simulated counter keeps free-running, so no edges are lost.

These tests exercise the delta transform directly (HardwareSimulator's
_apply_counter_reset_on_read) with controlled totals, so they're
deterministic — no dependence on time-based counter accumulation. The
simulator transform is byte-for-byte the same algorithm as
HardwareReader._apply_counter_reset_on_read.
"""

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "daq_service"))

from config_parser import (  # noqa: E402
    ChannelConfig, ChannelType, NISystemConfig, SystemConfig,
    ChassisConfig, ModuleConfig, DataViewerConfig,
)
from simulator import HardwareSimulator  # noqa: E402


def _config(**counter_kwargs):
    """Minimal config: one reset-on-read counter, one accumulate counter,
    one frequency counter, plus a voltage channel to prove non-counters are
    never touched."""
    return NISystemConfig(
        system=SystemConfig(
            mqtt_broker="localhost", mqtt_port=1883, mqtt_base_topic="t",
            scan_rate_hz=1.0, publish_rate_hz=1.0, simulation_mode=True,
            log_directory="./logs",
        ),
        dataviewer=DataViewerConfig(),
        chassis={"main": ChassisConfig(name="main", chassis_type="cDAQ-9188")},
        modules={"mod1": ModuleConfig(name="mod1", module_type="NI-9361",
                                      chassis="main", slot=1)},
        channels={
            "totalizer": ChannelConfig(
                name="totalizer", module="mod1", physical_channel="ctr0",
                channel_type=ChannelType.COUNTER,
                counter_mode="count", counter_reset_on_read=True),
            "accumulator": ChannelConfig(
                name="accumulator", module="mod1", physical_channel="ctr1",
                channel_type=ChannelType.COUNTER,
                counter_mode="count", counter_reset_on_read=False),
            "freq": ChannelConfig(
                name="freq", module="mod1", physical_channel="ctr2",
                channel_type=ChannelType.FREQUENCY_INPUT,
                counter_mode="frequency", counter_reset_on_read=True),
            "voltage": ChannelConfig(
                name="voltage", module="mod1", physical_channel="ai0",
                channel_type=ChannelType.VOLTAGE_INPUT),
        },
        safety_actions={},
    )


@pytest.fixture
def sim():
    return HardwareSimulator(_config())


def _apply(sim, **totals):
    """Run the reset-on-read transform over a controlled values dict."""
    values = dict(totals)
    sim._apply_counter_reset_on_read(values)
    return values


class TestResetOnRead:
    def test_first_read_returns_zero(self, sim):
        """Baseline seeds to the current total, so the first sample is 0 —
        no acquisition-start spike."""
        out = _apply(sim, totalizer=1234.0)
        assert out["totalizer"] == 0.0

    def test_subsequent_reads_return_increments(self, sim):
        _apply(sim, totalizer=1000.0)          # seed baseline
        assert _apply(sim, totalizer=1005.0)["totalizer"] == 5.0
        assert _apply(sim, totalizer=1012.0)["totalizer"] == 7.0
        assert _apply(sim, totalizer=1012.0)["totalizer"] == 0.0  # no new edges

    def test_accumulate_counter_untouched(self, sim):
        """reset_on_read=False → running total passes through unchanged."""
        assert _apply(sim, accumulator=500.0)["accumulator"] == 500.0
        assert _apply(sim, accumulator=750.0)["accumulator"] == 750.0

    def test_frequency_counter_untouched(self, sim):
        """Frequency/period are instantaneous; reset_on_read is ignored even
        though the flag is set."""
        assert _apply(sim, freq=50.0)["freq"] == 50.0
        assert _apply(sim, freq=52.0)["freq"] == 52.0

    def test_non_counter_untouched(self, sim):
        assert _apply(sim, voltage=3.3)["voltage"] == 3.3

    def test_nan_passes_through_without_advancing_baseline(self, sim):
        """A failed read (NaN) is passed through and must NOT move the baseline,
        so the next good read still counts edges accrued across the gap."""
        _apply(sim, totalizer=100.0)                     # baseline = 100
        out = _apply(sim, totalizer=float("nan"))
        assert math.isnan(out["totalizer"])
        # Counter kept running to 130 during the gap; delta spans the whole gap.
        assert _apply(sim, totalizer=130.0)["totalizer"] == 30.0

    def test_absent_channel_is_skipped(self, sim):
        """If the counter isn't in the values dict this read, nothing raises
        and the baseline is left intact."""
        _apply(sim, totalizer=100.0)                     # baseline = 100
        out = _apply(sim, accumulator=5.0)               # totalizer absent
        assert "totalizer" not in out
        assert _apply(sim, totalizer=110.0)["totalizer"] == 10.0


class TestReadAllIntegration:
    def test_read_all_applies_transform_to_totalizer(self, sim):
        """End-to-end through read_all(): the reset-on-read counter yields a
        small per-read delta while the plain accumulator keeps growing."""
        first = sim.read_all()
        assert first["totalizer"] == 0.0            # seeded baseline
        # After more reads the totalizer stays a per-interval delta (bounded),
        # never the full running total.
        for _ in range(5):
            out = sim.read_all()
        assert out["totalizer"] < out["accumulator"] + 1  # delta << total
        assert math.isfinite(out["totalizer"])
