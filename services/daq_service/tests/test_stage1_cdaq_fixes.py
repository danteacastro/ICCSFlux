#!/usr/bin/env python3
"""
Stage 1 cDAQ regression tests.

These guard the surgical fixes that made real-hardware reads work on the
cDAQ after the "stuck-at-zero" incident. Run without nidaqmx installed
(no NI driver required), so they're safe for any CI runner.

Coverage:
  - _module_needs_high_speed_adc() normalizes module names and matches
    NI-9211/9213/9214/9217/9207 in any case/separator variant.
  - _FORCE_HIGH_SPEED_ADC_MODULES contains exactly the modules NI KB
    kA00Z000000P8jtSAC flags as defaulting to slow HIGH_RESOLUTION mode.
  - The .ini parser defaults simulation_mode to False (was True before
    Stage 1 — silent simulator was masking every hardware bug).
  - MIN_BUFFER_SAMPLES is at or above NI's auto-allocated tier floor.
  - Source-level invariants: the load-bearing one-liners in
    hardware_reader.py (HIGH_SPEED setter, OVERWRITE_UNREAD_SAMPLES setter,
    rate-driven buffer) are still present. These are blunt regression
    catchers for "someone refactored and forgot."
"""

import sys
from pathlib import Path

import pytest

# Add daq_service to import path
sys.path.insert(0, str(Path(__file__).parent.parent))

from hardware_reader import (
    _module_needs_high_speed_adc,
    _FORCE_HIGH_SPEED_ADC_MODULES,
    MIN_BUFFER_SAMPLES,
)


# =============================================================================
# Helper: discovery-driven module-type check
# =============================================================================

class TestModuleNeedsHighSpeedAdc:
    """The check that drives the HIGH_SPEED ADC mode override.

    Name normalization matters because module type strings come from
    different sources (NI device discovery, project config, frontend) and
    may use any of: 'NI-9213', 'NI 9213', 'ni-9213', '9213'. Missing any
    variant means a 9213 in some slot won't get the override and reads
    will silently freeze.
    """

    @pytest.mark.parametrize("name", [
        "NI-9211", "NI-9213", "NI-9214", "NI-9217", "NI-9207",
    ])
    def test_canonical_names_match(self, name):
        assert _module_needs_high_speed_adc(name) is True

    @pytest.mark.parametrize("variant", [
        "NI 9213",   # space separator (device_discovery format)
        "ni 9213",   # lowercase + space
        "ni-9213",   # lowercase + hyphen
        "Ni-9213",   # mixed case
        "NI_9213",   # underscore separator
        "9213",      # bare model number
        " NI-9213 ", # surrounding whitespace
        "NI--9213",  # double hyphen
    ])
    def test_format_variants_match(self, variant):
        assert _module_needs_high_speed_adc(variant) is True

    @pytest.mark.parametrize("non_member", [
        "NI-9215",   # SAR-HS simultaneous voltage — no HR mode to override
        "NI-9220",   # SAR-HS voltage
        "NI-9229",   # isolated voltage
        "NI-9234",   # delta-sigma IEPE
        "NI-9485",   # relay (digital)
        "NI-9203",   # current — has HR mode but isn't in our list (uncommon symptom)
    ])
    def test_non_members_do_not_match(self, non_member):
        assert _module_needs_high_speed_adc(non_member) is False

    @pytest.mark.parametrize("garbage", [
        None, "", "  ", "foo", "1234", "NI-XXXX",
    ])
    def test_garbage_does_not_match(self, garbage):
        assert _module_needs_high_speed_adc(garbage) is False


# =============================================================================
# The static set itself
# =============================================================================

class TestForceHighSpeedAdcSet:
    """The modules that need ADCTimingMode.HIGH_SPEED override.

    Source: NI KB kA00Z000000P8jtSAC. The set is now derived from
    capabilities.STATIC_QUIRKS (Stage 3) — the Stage 1 hand-curated set
    was a subset of NI's full slow-sampled list. Adding/removing entries
    in STATIC_QUIRKS should be a deliberate, reviewed change.
    """

    # Stage 1 audit identified these as the minimum required set —
    # empirically validated stuck-at-zero cases on real hardware.
    # They MUST always remain in the set regardless of how it grows.
    STAGE_1_REQUIRED = {"NI-9211", "NI-9213", "NI-9214", "NI-9217", "NI-9207"}

    def test_set_contains_stage_1_required_members(self):
        """The 5 modules that triggered the original stuck-at-zero fix
        must always remain in the override set. Removing one would
        re-introduce the symptom on that module type."""
        assert self.STAGE_1_REQUIRED.issubset(_FORCE_HIGH_SPEED_ADC_MODULES), (
            f"Stage 1 required members missing: "
            f"{self.STAGE_1_REQUIRED - _FORCE_HIGH_SPEED_ADC_MODULES}"
        )

    def test_no_simultaneous_modules(self):
        """Simultaneous-sampling modules (9215/9220/etc.) don't expose a
        HIGH_RESOLUTION mode. Setting ai_adc_timing_mode on them would
        either silently no-op or raise — neither is desirable."""
        for sim_mod in ("NI-9215", "NI-9220", "NI-9229", "NI-9239"):
            assert sim_mod not in _FORCE_HIGH_SPEED_ADC_MODULES


# =============================================================================
# .ini parser default for simulation_mode
# =============================================================================

class TestSimulationModeDefault:
    """The .ini parser default for simulation_mode must remain 'false'.

    Before Stage 1 it was 'true', meaning any project config without an
    explicit simulation_mode key silently ran the simulator and showed
    fake values to the dashboard — masking every real hardware bug.

    We assert against the source string rather than going through
    load_config(), because load_config requires many other sections to
    succeed and we want a focused regression check that fails loudly the
    instant someone flips the default back.
    """

    def test_default_in_parser_is_false(self):
        src = (Path(__file__).parent.parent / "config_parser.py").read_text(
            encoding="utf-8"
        )
        # Stage 1 fix: this default was 'true' and silently masked
        # every hardware failure mode behind synthetic simulator values.
        assert "sys_section.get('simulation_mode', 'false')" in src, (
            "config_parser default for simulation_mode must be 'false' — "
            "see Stage 1 commit and the comment block above the assignment."
        )
        # Belt-and-suspenders: ensure the old default is gone.
        assert "sys_section.get('simulation_mode', 'true')" not in src, (
            "old simulation_mode default 'true' is back — silent simulator "
            "will mask every hardware bug; revert this change."
        )


# =============================================================================
# Buffer sizing
# =============================================================================

class TestBufferSizeFloor:
    """MIN_BUFFER_SAMPLES floors samps_per_chan so a 1 Hz scan still
    gets a usable on-board software buffer.

    NI auto-allocates 1,000 samples for 0–100 S/s rates per
    KB kA00Z000000P9PkSAK. Our floor must equal-or-exceed that or the
    floor adds nothing.
    """

    def test_floor_at_or_above_ni_default(self):
        assert MIN_BUFFER_SAMPLES >= 1000

    @pytest.mark.parametrize("rate, expected", [
        (1,    1000),    # floor wins
        (10,   1000),    # floor wins
        (100,  1000),    # floor == rate*10, tie
        (101,  1010),    # rate*10 wins
        (200,  2000),
        (1000, 10000),
        (10000, 100000),
    ])
    def test_buffer_sizing_formula(self, rate, expected):
        """Replicates the per-instance calculation from
        HardwareReader.__init__ — kept in sync with that line."""
        actual = max(MIN_BUFFER_SAMPLES, int(rate * 10))
        assert actual == expected


# =============================================================================
# Source-level invariants (regression catchers)
# =============================================================================

class TestStage1SourceInvariants:
    """Blunt source-level checks that the load-bearing Stage 1 lines are
    still present. Catches the 'someone refactored and forgot' class of
    regression that wouldn't show up in unit tests.
    """

    @pytest.fixture(scope="class")
    def src(self):
        return (Path(__file__).parent.parent / "hardware_reader.py").read_text(
            encoding="utf-8"
        )

    def test_adc_timing_mode_setter_present(self, src):
        """Setting HIGH_SPEED on TC/V/I/RTD channels is THE fix.
        Should appear at least 4 times (TC, voltage, current, RTD)."""
        count = src.count("ai_adc_timing_mode = ADCTimingMode.HIGH_SPEED")
        assert count >= 4, (
            f"Expected ai_adc_timing_mode setter in >= 4 places "
            f"(TC, V, I, RTD), found {count}. The HIGH_SPEED ADC override "
            f"is the load-bearing stuck-at-zero fix."
        )

    def test_overwrite_oldest_setter_present(self, src):
        """OVERWRITE_UNREAD_SAMPLES (drop-oldest semantics) after every
        cfg_samp_clk_timing prevents -200279 errors when the consumer
        briefly stalls."""
        count = src.count("over_write = OverwriteMode.OVERWRITE_UNREAD_SAMPLES")
        assert count >= 1, (
            "task.in_stream.over_write = OVERWRITE_UNREAD_SAMPLES is missing — "
            "consumer stalls will crash the reader with -200279."
        )

    def test_module_helper_callsites(self, src):
        """The module-type-driven HIGH_SPEED setter is conditional on
        _module_needs_high_speed_adc(mod_type). Should be used in TC,
        voltage, current, and RTD branches (4 sites)."""
        count = src.count("_module_needs_high_speed_adc(mod_type)")
        assert count >= 4, (
            f"Expected _module_needs_high_speed_adc(mod_type) at 4 callsites "
            f"(TC/V/I/RTD), found {count}."
        )

    def test_no_terminal_config_kwarg_on_add_ai_current_chan(self, src):
        """Regression guard: add_ai_current_chan must NOT receive a
        terminal_config kwarg.

        DAQmx -200077 rejects DIFF on NI 9203/9207-current/9208/9227/9246/
        9247/9253 — the modules' current channels REQUIRE RSE in the API.
        Letting DAQmx pick the module-correct default (no kwarg) is the
        only path that works across the whole family. This test catches
        anyone who later adds 'terminal_config=' back to that call site
        thinking it's safe.
        """
        import re
        # Find every add_ai_current_chan(...) call (multi-line) and check
        # its argument list for 'terminal_config='. The non-greedy regex
        # captures from the call name through its matching close paren.
        offenders = []
        for m in re.finditer(r"add_ai_current_chan\((.*?)\n\s*\)", src,
                             re.DOTALL):
            args = m.group(1)
            if "terminal_config" in args:
                # Find approximate line number for diagnostics
                line_no = src[:m.start()].count("\n") + 1
                offenders.append(line_no)
        assert not offenders, (
            f"add_ai_current_chan() at line(s) {offenders} passes "
            f"terminal_config — DAQmx -200077 will reject DIFF on NI 9208 "
            f"and similar. Remove the kwarg; let DAQmx pick the default."
        )

    def test_dynamic_buffer_size(self, src):
        """samps_per_chan must come from self._buffer_size (rate-driven),
        not the old fixed BUFFER_SIZE constant."""
        assert "samps_per_chan=self._buffer_size" in src, (
            "samps_per_chan must use the rate-driven self._buffer_size; "
            "the old fixed-100 BUFFER_SIZE constant should be gone."
        )
        assert "samps_per_chan=BUFFER_SIZE" not in src, (
            "old fixed BUFFER_SIZE reference is back — buffer sizing is "
            "no longer rate-aware."
        )

    def test_lag_safety_net_present(self, src):
        """Driver-lag check is the only signal we have that
        OVERWRITE_UNREAD_SAMPLES is silently dropping samples."""
        assert "total_samp_per_chan_acquired" in src, (
            "Driver-lag detection is missing — under OVERWRITE_UNREAD_SAMPLES "
            "samples can drop silently with no log entry."
        )
        assert "approaching overflow" in src, (
            "Driver-lag warning text is missing or has been changed — "
            "operators rely on this string when triaging stuck reads."
        )

    def test_read_timeout_not_aggressive(self, src):
        """Stage 1 bumped read_many_sample timeout from 0.1s to 2.0s
        because real hardware can stall briefly under contention."""
        # Allow either a literal 2.0 or a more generous timeout, but
        # forbid the old 0.1 that swallowed real reads.
        assert "timeout=0.1  # Short timeout" not in src, (
            "Old aggressive 0.1s read_many_sample timeout is back — "
            "real hardware stalls will be reported as errors."
        )
