"""
Module Capabilities — discovery-driven NI module description.

Stage 3 deliverable: replace per-quirk static lookup tables with a single
unified ``ModuleCapabilities`` dataclass. Where NI exposes the truth via
the ``nidaqmx`` Device API (channel counts, term configs, max rates,
supported measurement types, voltage ranges), we read it directly. Where
NI does NOT expose the truth (default ADC timing mode, open-TC detection
support, internal CJC sensor presence, etc.), we maintain a small static
table — but the table only contains "quirk-only" fields, not facts already
on the device.

Pattern adapted from labscript-suite/labscript-devices' ``get_capabilities.py``.

Usage::

    # Live device (preferred) — runtime introspection
    import nidaqmx.system
    sys = nidaqmx.system.System.local()
    dev = sys.devices["cDAQ1Mod1"]
    cap = ModuleCapabilities.from_device(dev)

    # No device available (simulator path, or pre-acquisition validation):
    cap = ModuleCapabilities.from_static("NI 9213")

    # Either way, derived helpers behave consistently:
    cap.needs_high_speed_adc_override   # True for 9207/9208/9209/9211–14/9217/9219
    cap.has_internal_cjc                # True for TC modules with onboard CJC
    cap.has_open_tc_detect              # True for TC modules with detect support
    cap.is_universal                    # 9218, 9219
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, FrozenSet, Optional, Tuple

logger = logging.getLogger("Capabilities")


# ============================================================================
# Constants
# ============================================================================

# Canonical terminal config strings (lowercase, matching terminal_config.py).
DIFFERENTIAL = "differential"
RSE = "rse"
NRSE = "nrse"
PSEUDODIFFERENTIAL = "pseudodifferential"

# Measurement type strings (lowercase). Mirrors nidaqmx UsageType enum names
# but kept as strings for cross-version safety.
VOLTAGE = "voltage"
CURRENT = "current"
THERMOCOUPLE = "thermocouple"
RTD = "rtd"
RESISTANCE = "resistance"
STRAIN = "strain"
BRIDGE = "bridge"
IEPE = "iepe"


def _normalize_product_type(s: Optional[str]) -> str:
    """Canonicalize an NI module type string.

    Accepts: ``'NI-9213'``, ``'NI 9213'``, ``'ni-9213'``, ``'9213'``, etc.
    Returns: ``'NI-9213'`` (canonical) or ``''`` if input is None/empty.

    Mirrors the normalization in ``terminal_config.is_module_differential_only``
    and ``hardware_reader._module_needs_high_speed_adc`` so all three layers
    agree on what "the same module" looks like.
    """
    if not s:
        return ""
    n = s.strip()
    if not n:
        # All-whitespace input — treat as empty rather than letting it
        # collapse to a bare "NI-" prefix below.
        return ""
    n = n.upper().replace(" ", "-").replace("_", "-")
    while "--" in n:
        n = n.replace("--", "-")
    if not n.startswith("NI-"):
        n = f"NI-{n}"
    return n


# ============================================================================
# Dataclass
# ============================================================================

@dataclass(frozen=True)
class ModuleCapabilities:
    """Single source of truth for what an NI module can do.

    Field naming intentionally mirrors ``nidaqmx.system.Device`` attribute
    names (``ai_max_single_chan_rate``, ``ai_voltage_rngs``, etc.) so a
    developer reading both can navigate by name.

    Fields populated only by ``from_device(dev)`` (runtime introspection)
    are zero/empty when constructed via ``from_static`` — that's
    intentional, because we want callers to know the difference between
    "queried the hardware" and "looked up our static table."
    """

    product_type: str  # canonical, e.g. "NI-9213"; "" if unknown.

    # ---- Topology (from nidaqmx Device introspection) ------------------
    num_ai: int = 0
    num_ao: int = 0
    num_di_lines: int = 0
    num_do_lines: int = 0
    num_ci: int = 0  # counter inputs

    # Supported measurement types per AI channel (lowercase strings).
    # Empty if the module has no AI channels OR if not introspected.
    ai_meas_types: FrozenSet[str] = frozenset()

    # Supported terminal configurations per AI channel.
    # Empty if not introspected.
    ai_term_cfgs: FrozenSet[str] = frozenset()

    ai_max_single_chan_rate: float = 0.0
    ai_max_multi_chan_rate: float = 0.0
    ai_simultaneous: bool = False
    ai_voltage_rngs: Tuple[Tuple[float, float], ...] = ()
    ai_current_rngs: Tuple[Tuple[float, float], ...] = ()

    ao_max_rate: Optional[float] = None
    ao_voltage_rngs: Tuple[Tuple[float, float], ...] = ()

    do_max_rate: Optional[float] = None

    # ---- Quirks NOT exposed by Device introspection --------------------
    # Sourced from STATIC_QUIRKS below. See per-entry comments for citations.

    #: Module's default ADC timing mode is the slow HR mode (~1 S/s
    #: aggregate); override to HIGH_SPEED required at any task rate above
    #: ~1 Hz. Source: NI KB kA00Z000000P8jtSAC. The Stage 1 stuck-at-zero
    #: fix used this flag.
    needs_high_speed_adc_override: bool = False

    #: Module has an onboard CJC sensor (so ``CJCSource.BUILT_IN`` is
    #: meaningful). True for 9211/9212/9213/9214 thermocouple modules.
    has_internal_cjc: bool = False

    #: Module supports ``ai_open_thrmcpl_detect_enable`` on TC channels.
    has_open_tc_detect: bool = False

    #: Universal module — measurement type is configured per-channel
    #: rather than fixed at the module level. NI 9218, NI 9219.
    is_universal: bool = False

    #: Free-form notes for documentation / debugging.
    notes: str = ""

    # ---- Derived helpers ----------------------------------------------

    @property
    def is_differential_only(self) -> bool:
        """True iff ``ai_term_cfgs == {DIFFERENTIAL}``.

        Returns False if ``ai_term_cfgs`` is empty (i.e. no introspection
        data available). Callers that need a static fallback should
        consult ``terminal_config._DIFFERENTIAL_ONLY_MODULES`` separately
        — we don't merge them here to keep the contract clean: this
        property reflects DEVICE TRUTH only.
        """
        if not self.ai_term_cfgs:
            return False
        return self.ai_term_cfgs == frozenset({DIFFERENTIAL})

    # ---- Factories -----------------------------------------------------

    @classmethod
    def from_static(cls, product_type: Optional[str]) -> "ModuleCapabilities":
        """Build from the static ``STATIC_QUIRKS`` table (no live device).

        Use when nidaqmx is unavailable or the device is not yet open.
        Returns capabilities with quirk fields populated but topology
        fields empty — we don't know channel counts / rates / ranges
        without probing the hardware.
        """
        canonical = _normalize_product_type(product_type)
        if not canonical:
            return cls(product_type="")
        return STATIC_QUIRKS.get(canonical, cls(product_type=canonical))

    @classmethod
    def from_device(cls, dev) -> "ModuleCapabilities":
        """Build from a live ``nidaqmx.system.Device`` — runtime introspection.

        Per-attribute try/except mirrors the labscript-suite pattern: not
        every property is supported on every NI module / driver version,
        so missing attrs gracefully degrade rather than raise. Quirk
        fields (which NI does not expose) are still drawn from
        ``STATIC_QUIRKS`` keyed by ``dev.product_type``.

        On any catastrophic failure (``dev`` is None, broken nidaqmx),
        returns an empty ``ModuleCapabilities`` so callers can continue
        with safe defaults.
        """
        if dev is None:
            return cls(product_type="")

        def _safe(getter, default):
            try:
                return getter()
            except Exception:
                return default

        product_type_raw = _safe(lambda: dev.product_type, "")
        canonical = _normalize_product_type(product_type_raw)
        static = STATIC_QUIRKS.get(canonical, cls(product_type=canonical))

        ai_chans = _safe(lambda: list(dev.ai_physical_chans), [])
        num_ai = len(ai_chans)

        ai_meas: set = set()
        for mt in _safe(lambda: list(dev.ai_meas_types), []):
            try:
                ai_meas.add(mt.name.lower())
            except Exception:
                pass  # MeasurementType.name not exposed; skip silently.

        # Probe ai_term_cfgs from the FIRST physical channel — terminal
        # configs are uniform across a module's AI channels.
        term_cfgs: set = set()
        if ai_chans:
            for tc in _safe(lambda: list(ai_chans[0].ai_term_cfgs), []):
                try:
                    term_cfgs.add(tc.name.lower())
                except Exception:
                    pass

        # nidaqmx returns voltage/current ranges as a flat list:
        # [min0, max0, min1, max1, ...]. Pair them up into tuples.
        v_rngs_flat = _safe(lambda: list(dev.ai_voltage_rngs), [])
        v_rngs = tuple(zip(v_rngs_flat[::2], v_rngs_flat[1::2]))

        c_rngs_flat = _safe(lambda: list(dev.ai_current_rngs), [])
        c_rngs = tuple(zip(c_rngs_flat[::2], c_rngs_flat[1::2]))

        ao_chans = _safe(lambda: list(dev.ao_physical_chans), [])
        num_ao = len(ao_chans)
        ao_v_rngs_flat = _safe(lambda: list(dev.ao_voltage_rngs), [])
        ao_v_rngs = tuple(zip(ao_v_rngs_flat[::2], ao_v_rngs_flat[1::2]))

        return cls(
            product_type=canonical,
            num_ai=num_ai,
            num_ao=num_ao,
            num_di_lines=len(_safe(lambda: list(dev.di_lines), [])),
            num_do_lines=len(_safe(lambda: list(dev.do_lines), [])),
            num_ci=len(_safe(lambda: list(dev.ci_physical_chans), [])),
            ai_meas_types=frozenset(ai_meas),
            ai_term_cfgs=frozenset(term_cfgs),
            ai_max_single_chan_rate=_safe(lambda: dev.ai_max_single_chan_rate, 0.0),
            ai_max_multi_chan_rate=_safe(lambda: dev.ai_max_multi_chan_rate, 0.0),
            ai_simultaneous=_safe(lambda: dev.ai_simultaneous_sampling_supported, False),
            ai_voltage_rngs=v_rngs,
            ai_current_rngs=c_rngs,
            ao_max_rate=_safe(lambda: dev.ao_max_rate, None),
            ao_voltage_rngs=ao_v_rngs,
            do_max_rate=_safe(lambda: dev.do_max_rate, None),
            # Quirk fields preserved from the static table.
            needs_high_speed_adc_override=static.needs_high_speed_adc_override,
            has_internal_cjc=static.has_internal_cjc,
            has_open_tc_detect=static.has_open_tc_detect,
            is_universal=static.is_universal,
            notes=static.notes,
        )


# ============================================================================
# STATIC_QUIRKS — fields NOT exposed by nidaqmx Device introspection
# ============================================================================
#
# Only contains modules that have at least one quirk that must be set in
# code (not derivable from the device API). Modules that work entirely
# from runtime introspection (e.g. NI-9215, NI-9220 voltage SAR) don't
# need an entry here — ``from_device(dev)`` covers them with empty quirk
# fields, which is correct (no override needed).
#
# Sources cited per entry:
#   - NI KB kA00Z000000P8jtSAC: "Error -201208 / Repeated Samples from C
#     Series Module" — names the slow-sampled modules (9207/8/9, 9211–14,
#     9217, 9219) that need HIGH_SPEED ADC override.
#   - Per-module specifications from www.ni.com/docs.

STATIC_QUIRKS: Dict[str, ModuleCapabilities] = {
    # ------ Thermocouple modules ---------------------------------------
    # All four have onboard CJC, support open-TC detection, and default
    # to slow HIGH_RESOLUTION ADC mode.
    "NI-9211": ModuleCapabilities(
        product_type="NI-9211",
        needs_high_speed_adc_override=True,
        has_internal_cjc=True,
        has_open_tc_detect=True,
        notes="4-Ch TC, ±80 mV; HIGH_SPEED gives ~14 S/s aggregate",
    ),
    "NI-9212": ModuleCapabilities(
        product_type="NI-9212",
        needs_high_speed_adc_override=True,
        has_internal_cjc=True,
        has_open_tc_detect=True,
        notes="8-Ch isolated TC",
    ),
    "NI-9213": ModuleCapabilities(
        product_type="NI-9213",
        needs_high_speed_adc_override=True,
        has_internal_cjc=True,
        has_open_tc_detect=True,
        notes="16-Ch TC, ±78 mV; HIGH_SPEED gives ~75 S/s aggregate",
    ),
    "NI-9214": ModuleCapabilities(
        product_type="NI-9214",
        needs_high_speed_adc_override=True,
        has_internal_cjc=True,
        has_open_tc_detect=True,
        notes="16-Ch isolated TC",
    ),

    # ------ RTD module -------------------------------------------------
    "NI-9217": ModuleCapabilities(
        product_type="NI-9217",
        needs_high_speed_adc_override=True,
        notes="4-Ch RTD; HIGH_RES default 100 S/s, HIGH_SPEED 400 S/s",
    ),

    # ------ Combined V/I & current modules ----------------------------
    "NI-9207": ModuleCapabilities(
        product_type="NI-9207",
        needs_high_speed_adc_override=True,
        notes="16-Ch ±20 mA + V (multiplexed); HIGH_SPEED required for >1 Hz",
    ),
    "NI-9208": ModuleCapabilities(
        product_type="NI-9208",
        needs_high_speed_adc_override=True,
        notes="16-Ch ±20 mA, 24-bit; same HR-default trap as 9207",
    ),
    "NI-9209": ModuleCapabilities(
        product_type="NI-9209",
        needs_high_speed_adc_override=True,
        notes="16-Ch ±10 V, 24-bit slow-sampled",
    ),

    # ------ Universal modules (per-channel measurement type) ----------
    "NI-9219": ModuleCapabilities(
        product_type="NI-9219",
        needs_high_speed_adc_override=True,
        is_universal=True,
        notes="4-Ch universal (V/I/R/TC/RTD/bridge), per-ch meas type",
    ),
    "NI-9218": ModuleCapabilities(
        product_type="NI-9218",
        is_universal=True,
        # 9218 is delta-sigma, no HR-default trap; no override needed.
        notes="2-Ch universal bridge/IEPE/V (delta-sigma)",
    ),
}


# ============================================================================
# Public lookup entry point
# ============================================================================

def lookup(product_type: Optional[str] = None, dev=None) -> ModuleCapabilities:
    """Resolve module capabilities, preferring live introspection.

    If ``dev`` (a ``nidaqmx.system.Device``) is provided, build from the
    device. Otherwise fall back to the static quirks table keyed by
    ``product_type``. This is the recommended entry point for all
    callers: pass ``dev`` when you have one, omit it otherwise.

    Returns an empty ``ModuleCapabilities`` (with all quirk flags False)
    if both ``dev`` and ``product_type`` are missing — safe defaults that
    won't trigger any per-module-type behavior in callers.
    """
    if dev is not None:
        try:
            return ModuleCapabilities.from_device(dev)
        except Exception as e:
            logger.warning(f"from_device failed: {e}; falling back to static")
    return ModuleCapabilities.from_static(product_type)
