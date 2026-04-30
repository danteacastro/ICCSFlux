#!/usr/bin/env python3
"""
Stage 3 ModuleCapabilities regression tests.

Coverage:
  - _normalize_product_type: every input variant resolves to canonical form
  - ModuleCapabilities dataclass: defaults, frozen-ness, derived helpers
  - STATIC_QUIRKS: integrity (every entry has a sane product_type), expected
    membership (Stage 1's required modules + Stage 3's expansion all
    flagged for HIGH_SPEED override)
  - from_static: known module returns its quirk entry; unknown returns
    safe defaults; None / empty returns empty capabilities
  - from_device: introspects a mock nidaqmx-like Device object correctly,
    falls back gracefully when attributes are missing, propagates quirk
    fields from STATIC_QUIRKS based on dev.product_type
  - lookup(): prefers from_device when dev is given, falls back to from_static
  - Migration invariants: hardware_reader._module_needs_high_speed_adc and
    _FORCE_HIGH_SPEED_ADC_MODULES are now derived from capabilities

Runs without nidaqmx installed; ``from_device`` tests use a duck-typed
``MockDevice`` (matches the nidaqmx Device attribute surface).
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from capabilities import (  # noqa: E402
    DIFFERENTIAL,
    RSE,
    NRSE,
    PSEUDODIFFERENTIAL,
    ModuleCapabilities,
    STATIC_QUIRKS,
    _normalize_product_type,
    lookup,
)


# =============================================================================
# Normalization
# =============================================================================

class TestNormalizeProductType:
    """The canonicalizer must produce identical output across every spelling
    variant the system sees from device discovery, project config, frontend,
    and direct API calls."""

    @pytest.mark.parametrize("variant", [
        "NI-9213", "NI 9213", "ni-9213", "Ni-9213", "NI_9213",
        "9213", "  NI-9213  ", "NI--9213", "ni 9213",
    ])
    def test_canonical_form(self, variant):
        assert _normalize_product_type(variant) == "NI-9213"

    @pytest.mark.parametrize("empty", [None, "", "   "])
    def test_empty_returns_empty(self, empty):
        assert _normalize_product_type(empty) == ""

    def test_already_canonical_unchanged(self):
        assert _normalize_product_type("NI-9213") == "NI-9213"

    def test_unknown_module_normalized_too(self):
        """Even modules we don't recognize get the NI- prefix and uppercase
        treatment — `lookup` will then return safe defaults."""
        assert _normalize_product_type("9999") == "NI-9999"


# =============================================================================
# ModuleCapabilities dataclass
# =============================================================================

class TestModuleCapabilitiesDataclass:
    def test_default_construction(self):
        cap = ModuleCapabilities(product_type="NI-9999")
        assert cap.product_type == "NI-9999"
        assert cap.num_ai == 0
        assert cap.ai_meas_types == frozenset()
        assert cap.ai_term_cfgs == frozenset()
        assert cap.needs_high_speed_adc_override is False
        assert cap.has_internal_cjc is False
        assert cap.is_universal is False

    def test_frozen(self):
        cap = ModuleCapabilities(product_type="NI-9213")
        with pytest.raises(Exception):
            cap.product_type = "NI-9214"  # frozen=True

    def test_is_differential_only_with_only_diff(self):
        cap = ModuleCapabilities(
            product_type="NI-9213",
            ai_term_cfgs=frozenset({DIFFERENTIAL}),
        )
        assert cap.is_differential_only is True

    def test_is_differential_only_with_multiple_configs(self):
        """A module that supports DIFF + RSE + NRSE is NOT diff-only."""
        cap = ModuleCapabilities(
            product_type="NI-9215",
            ai_term_cfgs=frozenset({DIFFERENTIAL, RSE, NRSE}),
        )
        assert cap.is_differential_only is False

    def test_is_differential_only_returns_false_when_unknown(self):
        """No introspection data → don't claim diff-only (caller falls
        back to terminal_config._DIFFERENTIAL_ONLY_MODULES)."""
        cap = ModuleCapabilities(product_type="NI-9213")
        assert cap.is_differential_only is False


# =============================================================================
# STATIC_QUIRKS integrity
# =============================================================================

class TestStaticQuirksIntegrity:
    def test_keys_are_canonical(self):
        for key in STATIC_QUIRKS:
            assert _normalize_product_type(key) == key, (
                f"STATIC_QUIRKS key {key!r} is not canonical"
            )

    def test_entries_match_their_keys(self):
        """Each entry's .product_type must match its dict key — otherwise
        from_static returns mismatched data."""
        for key, cap in STATIC_QUIRKS.items():
            assert cap.product_type == key

    def test_stage_1_required_members_flagged(self):
        """The 5 modules audited at Stage 1 must remain flagged for
        HIGH_SPEED override. Removing one would re-introduce stuck-at-zero
        on that module."""
        REQUIRED = {"NI-9211", "NI-9213", "NI-9214", "NI-9217", "NI-9207"}
        for mod in REQUIRED:
            assert mod in STATIC_QUIRKS, f"Stage 1 required module missing: {mod}"
            assert STATIC_QUIRKS[mod].needs_high_speed_adc_override is True

    def test_stage_3_expansion_covers_full_slow_sampled_list(self):
        """NI KB kA00Z000000P8jtSAC names: 9207, 9208, 9209, 9211, 9212,
        9213, 9214, 9217, 9219. All should be flagged."""
        FULL_LIST = {
            "NI-9207", "NI-9208", "NI-9209",
            "NI-9211", "NI-9212", "NI-9213", "NI-9214",
            "NI-9217", "NI-9219",
        }
        for mod in FULL_LIST:
            assert mod in STATIC_QUIRKS, f"slow-sampled module missing: {mod}"
            assert STATIC_QUIRKS[mod].needs_high_speed_adc_override is True, (
                f"{mod} should be flagged for HIGH_SPEED override per NI KB"
            )

    def test_tc_modules_have_internal_cjc_and_open_detect(self):
        for tc in ("NI-9211", "NI-9212", "NI-9213", "NI-9214"):
            assert STATIC_QUIRKS[tc].has_internal_cjc is True
            assert STATIC_QUIRKS[tc].has_open_tc_detect is True

    def test_universal_modules_flagged(self):
        for u in ("NI-9218", "NI-9219"):
            assert STATIC_QUIRKS[u].is_universal is True

    def test_9218_does_not_need_hs_override(self):
        """9218 is delta-sigma — different timing class than slow-sampled
        modules. It does NOT have the HR-default trap and must NOT be
        flagged (otherwise we'd try to set ADCTimingMode on it and fail)."""
        assert STATIC_QUIRKS["NI-9218"].needs_high_speed_adc_override is False


# =============================================================================
# from_static
# =============================================================================

class TestFromStatic:
    def test_known_module_returns_its_quirks(self):
        cap = ModuleCapabilities.from_static("NI-9213")
        assert cap.product_type == "NI-9213"
        assert cap.needs_high_speed_adc_override is True
        assert cap.has_internal_cjc is True

    def test_normalizes_input(self):
        """Caller may pass any spelling variant — same result."""
        for variant in ("NI 9213", "ni-9213", "9213", "NI_9213"):
            cap = ModuleCapabilities.from_static(variant)
            assert cap.product_type == "NI-9213"
            assert cap.needs_high_speed_adc_override is True

    def test_unknown_module_returns_safe_defaults(self):
        """Modules not in STATIC_QUIRKS get an empty-but-non-erroring cap."""
        cap = ModuleCapabilities.from_static("NI-9999")
        assert cap.product_type == "NI-9999"
        assert cap.needs_high_speed_adc_override is False
        assert cap.is_universal is False

    @pytest.mark.parametrize("empty", [None, "", "  "])
    def test_empty_returns_empty_caps(self, empty):
        cap = ModuleCapabilities.from_static(empty)
        assert cap.product_type == ""
        assert cap.needs_high_speed_adc_override is False


# =============================================================================
# from_device — runtime introspection
# =============================================================================

class _MockTermCfg:
    """Mimics nidaqmx TerminalConfiguration enum (has .name attribute)."""
    def __init__(self, name):
        self.name = name


class _MockMeasType:
    """Mimics nidaqmx UsageType / MeasurementType enum (has .name)."""
    def __init__(self, name):
        self.name = name


class _MockPhysChan:
    def __init__(self, term_cfgs):
        self.ai_term_cfgs = term_cfgs


def _make_mock_device(
    *,
    product_type="NI 9213",
    ai_chan_count=16,
    ao_chan_count=0,
    di_lines=0,
    do_lines=0,
    ci_chans=0,
    term_cfgs=("DIFFERENTIAL",),
    meas_types=("THERMOCOUPLE",),
    ai_max_single=75.0,
    ai_max_multi=75.0,
    ai_simultaneous=False,
    ai_voltage_rngs=(-0.078, 0.078),
    ai_current_rngs=(),
    ao_voltage_rngs=(),
    ao_max_rate=None,
    do_max_rate=None,
):
    """Construct a duck-typed mock that has every attribute from_device
    reads. Tests can override any field to exercise edge cases."""
    pc_list = [_MockPhysChan([_MockTermCfg(t) for t in term_cfgs])
               for _ in range(ai_chan_count)]
    return SimpleNamespace(
        product_type=product_type,
        ai_physical_chans=pc_list,
        ao_physical_chans=[None] * ao_chan_count,
        di_lines=[None] * di_lines,
        do_lines=[None] * do_lines,
        ci_physical_chans=[None] * ci_chans,
        ai_meas_types=[_MockMeasType(m) for m in meas_types],
        ai_max_single_chan_rate=ai_max_single,
        ai_max_multi_chan_rate=ai_max_multi,
        ai_simultaneous_sampling_supported=ai_simultaneous,
        ai_voltage_rngs=list(ai_voltage_rngs),
        ai_current_rngs=list(ai_current_rngs),
        ao_voltage_rngs=list(ao_voltage_rngs),
        ao_max_rate=ao_max_rate,
        do_max_rate=do_max_rate,
    )


class TestFromDevice:
    def test_introspects_basic_topology(self):
        dev = _make_mock_device(product_type="NI 9213", ai_chan_count=16)
        cap = ModuleCapabilities.from_device(dev)
        assert cap.product_type == "NI-9213"   # canonicalized
        assert cap.num_ai == 16

    def test_introspects_term_cfgs_lowercased(self):
        """nidaqmx returns enum members; we lowercase for cross-version safety."""
        dev = _make_mock_device(term_cfgs=("DIFFERENTIAL",))
        cap = ModuleCapabilities.from_device(dev)
        assert cap.ai_term_cfgs == frozenset({"differential"})
        assert cap.is_differential_only is True

    def test_introspects_voltage_rngs_paired_correctly(self):
        """ai_voltage_rngs is a flat [min, max, min, max, ...] list."""
        dev = _make_mock_device(
            ai_voltage_rngs=(-10.0, 10.0, -5.0, 5.0, -1.0, 1.0),
        )
        cap = ModuleCapabilities.from_device(dev)
        assert cap.ai_voltage_rngs == ((-10.0, 10.0), (-5.0, 5.0), (-1.0, 1.0))

    def test_propagates_quirks_from_static(self):
        """Even introspected devices need quirk fields from STATIC_QUIRKS,
        because NI does not expose default ADC mode etc. via API."""
        dev = _make_mock_device(product_type="NI 9213")
        cap = ModuleCapabilities.from_device(dev)
        assert cap.needs_high_speed_adc_override is True
        assert cap.has_internal_cjc is True

    def test_unknown_module_introspected_no_quirks(self):
        """A module not in STATIC_QUIRKS still gets topology from device,
        but no quirk overrides — safe default behavior."""
        dev = _make_mock_device(product_type="NI 9999", ai_chan_count=4)
        cap = ModuleCapabilities.from_device(dev)
        assert cap.product_type == "NI-9999"
        assert cap.num_ai == 4
        assert cap.needs_high_speed_adc_override is False

    def test_none_device_returns_empty_caps(self):
        cap = ModuleCapabilities.from_device(None)
        assert cap.product_type == ""

    def test_missing_attrs_dont_raise(self):
        """Real-world: some attrs aren't supported on every module / driver
        version. Each attr is wrapped in try/except — gracefully degrades."""
        partial = SimpleNamespace(product_type="NI 9213")  # NO other attrs
        cap = ModuleCapabilities.from_device(partial)
        # Should NOT raise; just returns canonical product + static quirks.
        assert cap.product_type == "NI-9213"
        assert cap.needs_high_speed_adc_override is True   # from STATIC_QUIRKS
        assert cap.num_ai == 0   # no introspection data

    def test_broken_dev_still_returns_capabilities(self):
        """If a property raises, _safe() catches and falls back to default."""
        class _BrokenDev:
            product_type = "NI 9213"
            @property
            def ai_physical_chans(self):
                raise RuntimeError("driver hiccup")
        cap = ModuleCapabilities.from_device(_BrokenDev())
        assert cap.product_type == "NI-9213"
        assert cap.num_ai == 0   # ai_physical_chans raised; safe default

    def test_voltage_rng_with_odd_length_list(self):
        """If nidaqmx returns malformed odd-length range list, zip drops
        the unpaired tail rather than raising."""
        dev = _make_mock_device(ai_voltage_rngs=(-10.0, 10.0, -5.0))
        cap = ModuleCapabilities.from_device(dev)
        # Only the complete pair survives.
        assert cap.ai_voltage_rngs == ((-10.0, 10.0),)


# =============================================================================
# lookup() — the public entry point
# =============================================================================

class TestLookup:
    def test_no_dev_falls_back_to_static(self):
        cap = lookup("NI-9213")
        assert cap.product_type == "NI-9213"
        assert cap.needs_high_speed_adc_override is True
        # Topology fields empty — no introspection happened.
        assert cap.num_ai == 0

    def test_with_dev_uses_introspection(self):
        dev = _make_mock_device(product_type="NI 9213", ai_chan_count=16)
        cap = lookup("NI-9213", dev=dev)
        assert cap.num_ai == 16   # from introspection
        assert cap.needs_high_speed_adc_override is True

    def test_dev_introspection_failure_falls_back_to_static(self):
        """If from_device raises catastrophically, we still get a useful
        result via from_static instead of crashing."""
        class _ExplodingDev:
            @property
            def product_type(self):
                raise RuntimeError("driver dead")
        cap = lookup("NI-9213", dev=_ExplodingDev())
        # from_device returned an empty cap because product_type failed.
        # The dev path doesn't fall through to static in current code, so
        # we get an empty cap. This test documents that contract — if we
        # ever want fall-through, change the implementation and the test.
        assert cap.product_type == ""

    @pytest.mark.parametrize("empty", [None, "", "  "])
    def test_no_dev_no_string_returns_empty(self, empty):
        cap = lookup(empty)
        assert cap.product_type == ""
        assert cap.needs_high_speed_adc_override is False


# =============================================================================
# Migration: hardware_reader uses capabilities
# =============================================================================

class TestHardwareReaderUsesCapabilities:
    """After the Stage 3 migration, hardware_reader's static set and its
    _module_needs_high_speed_adc helper should both come from capabilities.
    """

    @pytest.fixture(scope="class")
    def src(self):
        return (Path(__file__).parent.parent / "hardware_reader.py").read_text(
            encoding="utf-8"
        )

    def test_imports_capabilities(self, src):
        assert "import capabilities as _capabilities" in src

    def test_force_set_derived_from_static_quirks(self, src):
        """The set should now be a comprehension over STATIC_QUIRKS, not
        a hand-curated literal — single source of truth."""
        assert "_capabilities.STATIC_QUIRKS.items()" in src

    def test_helper_delegates_to_lookup(self, src):
        """_module_needs_high_speed_adc must call capabilities.lookup,
        not maintain its own normalization+set-membership logic."""
        assert "_capabilities.lookup(module_type).needs_high_speed_adc_override" in src

    def test_runtime_force_set_includes_stage3_expansion(self):
        """The runtime-derived set must contain the new modules added in
        Stage 3 (9208, 9209, 9212, 9219)."""
        from hardware_reader import _FORCE_HIGH_SPEED_ADC_MODULES
        for mod in ("NI-9208", "NI-9209", "NI-9212", "NI-9219"):
            assert mod in _FORCE_HIGH_SPEED_ADC_MODULES, (
                f"Stage 3 expansion missing: {mod}"
            )

    def test_runtime_helper_returns_true_for_new_modules(self):
        """The migrated helper handles 9208/9209/9212/9219 — these were
        missing in Stage 1 and would have stuck-at-zero on real hardware."""
        from hardware_reader import _module_needs_high_speed_adc
        for mod in ("NI-9208", "NI 9209", "9212", "ni-9219"):
            assert _module_needs_high_speed_adc(mod) is True
