#!/usr/bin/env python3
"""
Tests for task_topology.plan_analog_tasks — the AI task-grouping planner.

Coverage:
  - all-multiplexed modules coalesce into ONE task (the core cDAQ-9188 fix)
  - each simultaneous (delta-sigma) module gets its OWN task
  - mixed chassis: one multiplexed task + N simultaneous tasks
  - channel/module ordering is deterministic and input order preserved
  - merged-task label derived from the common chassis prefix
  - single-module and empty inputs behave sanely

Hardware-free: the planner takes an is_simultaneous() classifier callable,
so no nidaqmx device is needed.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))

from task_topology import (  # noqa: E402
    AnalogTaskPlan,
    plan_analog_tasks,
    _common_module_prefix,
)


def _ch(name, phys):
    """Minimal channel stand-in — planner only carries the object through."""
    return SimpleNamespace(name=name, physical_channel=phys)


# Simulated cDAQ-9188 module names (the reporting scenario).
CHASSIS = "cDAQ-9188-1A2B3C4"


def _mod(slot):
    return f"{CHASSIS}Mod{slot}"


# =============================================================================
# Core: multiplexed modules coalesce
# =============================================================================

class TestMultiplexedCoalesce:
    def test_all_multiplexed_into_one_task(self):
        """The cDAQ-9188 fix: 4 different multiplexed AI modules → ONE task."""
        by_module = {
            _mod(1): [_ch("tc_a", f"{_mod(1)}/ai0")],
            _mod(2): [_ch("i_a", f"{_mod(2)}/ai0")],
            _mod(3): [_ch("v_a", f"{_mod(3)}/ai0")],
            _mod(4): [_ch("rtd_a", f"{_mod(4)}/ai0")],
        }
        plans = plan_analog_tasks(by_module, is_simultaneous=lambda m: False)
        assert len(plans) == 1
        assert plans[0].is_simultaneous is False
        assert len(plans[0].channels) == 4
        assert set(plans[0].module_names) == {_mod(1), _mod(2), _mod(3), _mod(4)}

    def test_merged_label_uses_common_prefix_with_mux_suffix(self):
        by_module = {
            _mod(1): [_ch("a", f"{_mod(1)}/ai0")],
            _mod(5): [_ch("b", f"{_mod(5)}/ai0")],
        }
        plans = plan_analog_tasks(by_module, is_simultaneous=lambda m: False)
        assert len(plans) == 1
        assert plans[0].label == f"{CHASSIS}_mux"

    def test_channels_preserved_and_ordered_by_module(self):
        by_module = {
            _mod(2): [_ch("m2c0", f"{_mod(2)}/ai0"), _ch("m2c1", f"{_mod(2)}/ai1")],
            _mod(1): [_ch("m1c0", f"{_mod(1)}/ai0")],
        }
        plans = plan_analog_tasks(by_module, is_simultaneous=lambda m: False)
        names = [c.name for c in plans[0].channels]
        # Modules are processed in sorted order: Mod1 before Mod2.
        assert names == ["m1c0", "m2c0", "m2c1"]


# =============================================================================
# Simultaneous modules
# =============================================================================

class TestSimultaneous:
    def test_each_simultaneous_gets_own_task(self):
        by_module = {
            _mod(1): [_ch("iepe_a", f"{_mod(1)}/ai0")],
            _mod(2): [_ch("iepe_b", f"{_mod(2)}/ai0")],
        }
        plans = plan_analog_tasks(by_module, is_simultaneous=lambda m: True)
        assert len(plans) == 2
        assert all(p.is_simultaneous for p in plans)
        # Labelled by their own module name (own task).
        assert {p.label for p in plans} == {_mod(1), _mod(2)}

    def test_simultaneous_sorted_by_module_name(self):
        by_module = {
            _mod(3): [_ch("c", f"{_mod(3)}/ai0")],
            _mod(1): [_ch("a", f"{_mod(1)}/ai0")],
            _mod(2): [_ch("b", f"{_mod(2)}/ai0")],
        }
        plans = plan_analog_tasks(by_module, is_simultaneous=lambda m: True)
        assert [p.label for p in plans] == [_mod(1), _mod(2), _mod(3)]


# =============================================================================
# Mixed chassis
# =============================================================================

class TestMixedChassis:
    def test_multiplexed_task_first_then_simultaneous(self):
        """3 multiplexed modules share one task; the 2 delta-sigma modules
        each get their own. Multiplexed task is emitted first."""
        simul = {_mod(4), _mod(5)}
        by_module = {
            _mod(1): [_ch("tc", f"{_mod(1)}/ai0")],
            _mod(2): [_ch("i", f"{_mod(2)}/ai0")],
            _mod(3): [_ch("v", f"{_mod(3)}/ai0")],
            _mod(4): [_ch("iepe", f"{_mod(4)}/ai0")],
            _mod(5): [_ch("bridge", f"{_mod(5)}/ai0")],
        }
        plans = plan_analog_tasks(by_module, is_simultaneous=lambda m: m in simul)
        assert len(plans) == 3  # 1 mux + 2 simultaneous
        assert plans[0].is_simultaneous is False
        assert len(plans[0].channels) == 3
        assert [p.label for p in plans[1:]] == [_mod(4), _mod(5)]
        assert all(p.is_simultaneous for p in plans[1:])


# =============================================================================
# Edge cases
# =============================================================================

class TestEdgeCases:
    def test_empty_input(self):
        assert plan_analog_tasks({}, is_simultaneous=lambda m: False) == []

    def test_single_multiplexed_module_labelled_by_module(self):
        """One module → no _mux suffix; task named after the module."""
        by_module = {_mod(1): [_ch("a", f"{_mod(1)}/ai0")]}
        plans = plan_analog_tasks(by_module, is_simultaneous=lambda m: False)
        assert len(plans) == 1
        assert plans[0].label == _mod(1)

    def test_module_with_empty_channel_list_skipped(self):
        by_module = {
            _mod(1): [],
            _mod(2): [_ch("a", f"{_mod(2)}/ai0")],
        }
        plans = plan_analog_tasks(by_module, is_simultaneous=lambda m: False)
        assert len(plans) == 1
        assert plans[0].module_names == [_mod(2)]


# =============================================================================
# _common_module_prefix
# =============================================================================

class TestCommonModulePrefix:
    def test_trims_at_mod_suffix(self):
        assert _common_module_prefix([_mod(1), _mod(3)]) == CHASSIS

    def test_single_module_returns_itself(self):
        assert _common_module_prefix([_mod(1)]) == _mod(1)

    def test_empty_returns_combined(self):
        assert _common_module_prefix([]) == "combined"

    def test_no_shared_prefix_returns_combined(self):
        assert _common_module_prefix(["Alpha1Mod1", "Beta2Mod1"]) == "combined"
