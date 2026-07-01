"""
Analog-input task topology planner.

Decides how to distribute analog-input channels across hardware-timed
NI-DAQmx tasks on a CompactDAQ chassis, staying within the chassis's
limited number of AI timing engines.

Why this exists
---------------
A cDAQ chassis exposes only a handful of AI timing engines. Creating one
hardware-timed AI task per *module* blows that budget the moment the
chassis is populated with several different AI module types — the Nth
task fails at reservation with "Resource requested by this task has
already been reserved by a different task" (DAQmx -50103 / -88709), the
reader aborts, and the service falls back to the simulator. The symptom
the user sees is "all values are bad" — because they are no longer
reading real hardware at all.

The fix: put as many channels as possible into a *single* task. On a
cDAQ chassis a single hardware-timed AI task may span MANY modules and
still consume only ONE timing engine — provided every module in the task
is **multiplexed** (its channels are scanned off a shared sample clock).

The one hard rule DAQmx enforces:
  - **Multiplexed (scanning) modules** — most C Series AI modules,
    including the 9211/9212/9213/9214 (TC), 9217 (RTD), 9207/9208/9209
    (V/I), 9219 (universal). Any number of them, mixing any measurement
    types, share ONE task and ONE timing engine.
  - **Simultaneous-sampling (delta-sigma) modules** — IEPE/sound-vibration
    (9232/9234/9250), bridge (9218/9236/9237). Each owns its own timing
    and CANNOT share the multiplexed scan clock, so each gets its OWN task.

Sample rate is a single global value in this system, so there is never a
per-function rate conflict that would force a multiplexed split — all
multiplexed channels can always coalesce.

This module is deliberately hardware-free (no ``nidaqmx`` import) so the
grouping logic is unit-testable without a device. The caller supplies an
``is_simultaneous(module_name) -> bool`` classifier (backed by live
device introspection or the static capabilities table).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Sequence


@dataclass
class AnalogTaskPlan:
    """One hardware-timed AI task to create.

    label:           task-name label (``{label}_analog`` becomes the task name).
    channels:        channel configs to add to this task, in caller order.
    module_names:    modules contributing channels to this task.
    is_simultaneous: True if this is a dedicated task for a single
                     simultaneous-sampling module; False for the shared
                     multiplexed task.
    """
    label: str
    channels: List[Any]
    module_names: List[str] = field(default_factory=list)
    is_simultaneous: bool = False


def _common_module_prefix(module_names: Sequence[str]) -> str:
    """Longest shared prefix of the module names, trimmed at the ``Mod``
    slot suffix so a merged label reads like the chassis, not a half-word.

    ``['cDAQ-9188-1A2Mod1', 'cDAQ-9188-1A2Mod3']`` -> ``'cDAQ-9188-1A2'``.
    Falls back to ``'combined'`` when there is no usable shared prefix.
    """
    if not module_names:
        return "combined"
    if len(module_names) == 1:
        return module_names[0]

    s1 = min(module_names)
    s2 = max(module_names)
    i = 0
    while i < len(s1) and i < len(s2) and s1[i] == s2[i]:
        i += 1
    prefix = s1[:i]

    # Trim a trailing partial "Mod" fragment (e.g. "...Mod" or "...Mo").
    mod_idx = prefix.rfind("Mod")
    if mod_idx != -1:
        prefix = prefix[:mod_idx]
    prefix = prefix.rstrip("-_ ")
    return prefix or "combined"


def plan_analog_tasks(
    analog_by_module: Mapping[str, Sequence[Any]],
    is_simultaneous: Callable[[str], bool],
) -> List[AnalogTaskPlan]:
    """Group analog-input channels into the fewest DAQmx-valid AI tasks.

    Args:
        analog_by_module: module name -> its analog-input channel configs.
            Only modules that actually have analog-input channels should
            appear here.
        is_simultaneous: classifier returning True for simultaneous-sampling
            (delta-sigma) modules, which each need their own task.

    Returns:
        Deterministically ordered list of task plans:
          1. the single shared multiplexed task (if any multiplexed channels
             exist), labelled after the common chassis prefix;
          2. one task per simultaneous module, sorted by module name.

        Module order within the multiplexed task and channel order within
        each module are preserved from the input.
    """
    mux_modules: List[str] = []
    mux_channels: List[Any] = []
    simul_plans: List[AnalogTaskPlan] = []

    # Sort module names for deterministic, reproducible task layout.
    for module_name in sorted(analog_by_module.keys()):
        channels = list(analog_by_module[module_name])
        if not channels:
            continue
        if is_simultaneous(module_name):
            simul_plans.append(AnalogTaskPlan(
                label=module_name,
                channels=channels,
                module_names=[module_name],
                is_simultaneous=True,
            ))
        else:
            mux_modules.append(module_name)
            mux_channels.extend(channels)

    plans: List[AnalogTaskPlan] = []
    if mux_channels:
        label = _common_module_prefix(mux_modules)
        # Distinguish the merged multi-module task from a single-module one
        # so its task name is unambiguous in logs.
        if len(mux_modules) > 1:
            label = f"{label}_mux"
        plans.append(AnalogTaskPlan(
            label=label,
            channels=mux_channels,
            module_names=list(mux_modules),
            is_simultaneous=False,
        ))

    plans.extend(simul_plans)
    return plans
