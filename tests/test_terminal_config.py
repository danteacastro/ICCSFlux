"""
Terminal Configuration Tests

Verifies that terminal_config is correctly validated and coerced for every
channel type and module configuration. The wrong terminal config causes
incorrect hardware readings — this test suite ensures the system enforces
correct values everywhere they could be set.

Background: NI-9203 (4-20mA current input) with terminal_config=RSE causes
the ADC to read shunt voltage instead of current, producing values like
127 mA instead of the actual 4-20 mA. This was Mike's original bug.
"""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "daq_service"))

import terminal_config as tc
from config_parser import ChannelType, ChannelConfig


# ===================================================================
# 1. Normalization — case-insensitive, alias handling
# ===================================================================

class TestNormalize:

    def test_canonical_lowercase(self):
        assert tc.normalize("differential") == "differential"
        assert tc.normalize("rse") == "rse"
        assert tc.normalize("nrse") == "nrse"
        assert tc.normalize("pseudodifferential") == "pseudodifferential"

    def test_uppercase(self):
        assert tc.normalize("DIFFERENTIAL") == "differential"
        assert tc.normalize("RSE") == "rse"
        assert tc.normalize("NRSE") == "nrse"
        assert tc.normalize("PSEUDODIFFERENTIAL") == "pseudodifferential"

    def test_mixed_case(self):
        assert tc.normalize("Differential") == "differential"
        assert tc.normalize("Rse") == "rse"

    def test_whitespace(self):
        assert tc.normalize("  differential  ") == "differential"
        assert tc.normalize("\tRSE\n") == "rse"

    def test_nidaqmx_aliases(self):
        """NI-DAQmx uses DIFF and PSEUDO_DIFF — should map correctly."""
        assert tc.normalize("DIFF") == "differential"
        assert tc.normalize("diff") == "differential"
        assert tc.normalize("PSEUDO_DIFF") == "pseudodifferential"
        assert tc.normalize("pseudo_diff") == "pseudodifferential"

    def test_legacy_default(self):
        """Legacy 'DEFAULT' value should map to 'differential' (safest)."""
        assert tc.normalize("DEFAULT") == "differential"
        assert tc.normalize("default") == "differential"

    def test_empty_returns_differential(self):
        assert tc.normalize(None) == "differential"
        assert tc.normalize("") == "differential"
        assert tc.normalize("   ") == "differential"

    def test_unknown_returns_differential(self):
        """Unknown values are coerced to 'differential' (safest)."""
        assert tc.normalize("UNKNOWN") == "differential"
        assert tc.normalize("foo") == "differential"
        assert tc.normalize("bipolar") == "differential"


# ===================================================================
# 2. allowed_for() — per-channel-type compatibility
# ===================================================================

class TestAllowedFor:

    @pytest.mark.parametrize("ct", [
        ChannelType.CURRENT_OUTPUT,
        ChannelType.THERMOCOUPLE,
        ChannelType.RTD,
        ChannelType.STRAIN,
        ChannelType.STRAIN_INPUT,
        ChannelType.BRIDGE_INPUT,
        ChannelType.RESISTANCE,
        ChannelType.RESISTANCE_INPUT,
        ChannelType.IEPE,
        ChannelType.IEPE_INPUT,
    ])
    def test_differential_only_types(self, ct):
        """These types only support DIFFERENTIAL — anything else causes wrong readings.

        CURRENT_INPUT is intentionally NOT in this set: see
        test_current_input_rse_required_modules below for the per-module rule.
        """
        allowed = tc.allowed_for(ct)
        assert allowed == {tc.DIFFERENTIAL}

    def test_current_input_unknown_module(self):
        """Without a module hint, CURRENT_INPUT is permissive — caller may
        not know which module their physical_channel resolves to. The
        coerce() helper picks RSE as the safe default in this branch."""
        allowed = tc.allowed_for(ChannelType.CURRENT_INPUT)
        assert allowed == tc.ALL_TERMINAL_CONFIGS

    @pytest.mark.parametrize("module_type", [
        "NI-9203", "NI-9207", "NI 9208", "NI-9227", "NI-9246",
        "NI-9247", "NI-9253",
    ])
    def test_current_input_rse_required_modules(self, module_type):
        """add_ai_current_chan(terminal_config=DIFF) on these modules raises
        DaqError -200077. The validator must restrict to RSE."""
        allowed = tc.allowed_for(ChannelType.CURRENT_INPUT, module_type)
        assert allowed == {tc.RSE}

    @pytest.mark.parametrize("ct", [
        ChannelType.VOLTAGE_INPUT,
        ChannelType.VOLTAGE_OUTPUT,
    ])
    def test_voltage_types_allow_all(self, ct):
        """Voltage channels can use any of the four configs."""
        allowed = tc.allowed_for(ct)
        assert allowed == tc.ALL_TERMINAL_CONFIGS
        assert tc.DIFFERENTIAL in allowed
        assert tc.RSE in allowed
        assert tc.NRSE in allowed
        assert tc.PSEUDODIFFERENTIAL in allowed

    @pytest.mark.parametrize("ct", [
        ChannelType.DIGITAL_INPUT,
        ChannelType.DIGITAL_OUTPUT,
        ChannelType.MODBUS_REGISTER,
        ChannelType.MODBUS_COIL,
        ChannelType.COUNTER,
        ChannelType.COUNTER_INPUT,
        ChannelType.COUNTER_OUTPUT,
        ChannelType.PULSE_OUTPUT,
        ChannelType.FREQUENCY_INPUT,
    ])
    def test_no_terminal_types(self, ct):
        """These types don't use terminal_config at all."""
        allowed = tc.allowed_for(ct)
        assert allowed == set()


# ===================================================================
# 3. validate() — returns clear error messages
# ===================================================================

class TestValidate:

    def test_current_input_valid_without_module(self):
        """Without a module hint, the validator is permissive — caller may
        not know which physical module the channel maps to yet."""
        for cfg in ["differential", "rse", "nrse", "pseudodifferential"]:
            valid, err = tc.validate(ChannelType.CURRENT_INPUT, cfg)
            assert valid, f"{cfg} should be valid for CURRENT_INPUT without module: {err}"

    def test_current_input_diff_rejected_on_rse_required_module(self):
        """The real bug — DIFF on a 9208's current channel raises DaqError
        -200077. Validator must reject and explain why."""
        valid, err = tc.validate(
            ChannelType.CURRENT_INPUT, "differential", "NI 9208")
        assert not valid
        assert "rse" in err.lower()
        assert "200077" in err

    def test_current_input_rse_accepted_on_rse_required_module(self):
        valid, err = tc.validate(
            ChannelType.CURRENT_INPUT, "rse", "NI 9208")
        assert valid, err

    def test_voltage_input_all_valid(self):
        for cfg in ["differential", "rse", "nrse", "pseudodifferential"]:
            valid, err = tc.validate(ChannelType.VOLTAGE_INPUT, cfg)
            assert valid, f"{cfg} should be valid for voltage_input: {err}"

    def test_thermocouple_only_differential(self):
        valid, _ = tc.validate(ChannelType.THERMOCOUPLE, "differential")
        assert valid
        valid, _ = tc.validate(ChannelType.THERMOCOUPLE, "RSE")
        assert not valid

    def test_rtd_only_differential(self):
        valid, _ = tc.validate(ChannelType.RTD, "differential")
        assert valid
        valid, _ = tc.validate(ChannelType.RTD, "NRSE")
        assert not valid

    def test_strain_only_differential(self):
        valid, _ = tc.validate(ChannelType.STRAIN, "differential")
        assert valid
        valid, _ = tc.validate(ChannelType.STRAIN, "RSE")
        assert not valid

    def test_iepe_only_differential(self):
        valid, _ = tc.validate(ChannelType.IEPE, "differential")
        assert valid
        valid, _ = tc.validate(ChannelType.IEPE, "RSE")
        assert not valid

    def test_digital_input_anything_valid(self):
        """Digital channels don't use terminal_config — always valid."""
        for cfg in ["differential", "RSE", "NRSE", "anything", "", None]:
            valid, _ = tc.validate(ChannelType.DIGITAL_INPUT, cfg)
            assert valid, f"Digital input should accept any value, rejected {cfg}"

    def test_legacy_default_for_current_input(self):
        """Legacy 'DEFAULT' string should be accepted for current_input
        (it normalizes to 'differential')."""
        valid, _ = tc.validate(ChannelType.CURRENT_INPUT, "DEFAULT")
        assert valid

    def test_case_insensitive(self):
        """Validation should be case-insensitive."""
        assert tc.validate(ChannelType.VOLTAGE_INPUT, "DIFFERENTIAL")[0]
        assert tc.validate(ChannelType.VOLTAGE_INPUT, "differential")[0]
        assert tc.validate(ChannelType.VOLTAGE_INPUT, "Differential")[0]


# ===================================================================
# 4. coerce() — always returns a valid value
# ===================================================================

class TestCoerce:

    def test_current_input_rse_module_always_rse(self):
        """For RSE-required modules (9203/9207-current/9208/9227/9246/9247/
        9253), coerce must return 'rse' regardless of caller input — DAQmx
        rejects DIFF with -200077."""
        for raw in ["differential", "DIFFERENTIAL", "rse", "RSE", "garbage",
                    None, "", "DEFAULT"]:
            assert tc.coerce(ChannelType.CURRENT_INPUT, raw, "NI 9208") == "rse"

    def test_current_input_unknown_module_defaults_rse(self):
        """Without a module hint we default to 'rse' (the most common DAQmx
        requirement for current modules) but still respect a valid caller
        choice if they provide one."""
        assert tc.coerce(ChannelType.CURRENT_INPUT, None) == "rse"
        assert tc.coerce(ChannelType.CURRENT_INPUT, "") == "rse"
        # Caller's valid choice is preserved when module is unknown
        assert tc.coerce(ChannelType.CURRENT_INPUT, "differential") == "differential"

    def test_voltage_input_preserves_valid(self):
        """Voltage input keeps whatever valid value the user picked."""
        assert tc.coerce(ChannelType.VOLTAGE_INPUT, "differential") == "differential"
        assert tc.coerce(ChannelType.VOLTAGE_INPUT, "rse") == "rse"
        assert tc.coerce(ChannelType.VOLTAGE_INPUT, "nrse") == "nrse"
        assert tc.coerce(ChannelType.VOLTAGE_INPUT, "pseudodifferential") == "pseudodifferential"

    def test_voltage_input_normalizes_case(self):
        assert tc.coerce(ChannelType.VOLTAGE_INPUT, "RSE") == "rse"
        assert tc.coerce(ChannelType.VOLTAGE_INPUT, "DIFFERENTIAL") == "differential"

    def test_voltage_input_coerces_unknown(self):
        """Unknown value on voltage input → differential (safest)."""
        assert tc.coerce(ChannelType.VOLTAGE_INPUT, "garbage") == "differential"
        assert tc.coerce(ChannelType.VOLTAGE_INPUT, None) == "differential"

    @pytest.mark.parametrize("ct", [
        ChannelType.THERMOCOUPLE,
        ChannelType.RTD,
        ChannelType.STRAIN,
        ChannelType.IEPE,
        ChannelType.RESISTANCE,
    ])
    def test_other_differential_only_always_differential(self, ct):
        """All differential-only types coerce to 'differential' regardless of input."""
        assert tc.coerce(ct, "RSE") == "differential"
        assert tc.coerce(ct, "anything") == "differential"

    def test_digital_returns_differential(self):
        """Digital types return 'differential' (won't be used anyway)."""
        assert tc.coerce(ChannelType.DIGITAL_INPUT, "anything") == "differential"


# ===================================================================
# 5. NI 9208 / 9203 / 9207-current — DAQmx-required RSE rule
# ===================================================================

class TestCurrentInputModuleRSERule:
    """The reverse of what an earlier diagnosis assumed.

    For NI's current-input modules (9203/9207-current/9208/9227/9246/9247/
    9253), the DAQmx software API requires terminal_config=RSE on
    add_ai_current_chan. Passing DIFF raises DaqError -200077 with
    "Possible Values: DAQmx_Val_RSE". Confirmed against real NI 9208
    hardware in this session.

    The "127 mA on a 4-20 mA loop" symptom an earlier note attributed to
    "RSE reads shunt voltage" was actually caused by passing DIFF and
    the task creation failing silently — the dashboard kept showing the
    last cached value (or scaled garbage from a partially-built task).
    """

    @pytest.mark.parametrize("module_type", [
        "NI-9203", "NI-9207", "NI 9208", "NI-9227", "NI-9246",
        "NI-9247", "NI-9253",
    ])
    def test_coerce_picks_rse_regardless_of_caller(self, module_type):
        """For RSE-required modules, coerce must return 'rse' even if the
        caller passes 'differential' / 'DEFAULT' / garbage."""
        for raw in ["differential", "DIFFERENTIAL", "DEFAULT", "garbage",
                    "rse", None, "", "  ", "????"]:
            assert tc.coerce(ChannelType.CURRENT_INPUT, raw, module_type) == "rse", \
                f"raw={raw!r} on {module_type} did not coerce to 'rse'"

    @pytest.mark.parametrize("module_type", [
        "NI-9208", "NI 9208", "ni-9208", "ni 9208", "9208",
    ])
    def test_validate_rejects_diff_on_9208(self, module_type):
        """The exact bug we fixed — DIFF on a 9208 current channel must be
        rejected by the validator before it reaches DAQmx."""
        valid, err = tc.validate(ChannelType.CURRENT_INPUT, "differential", module_type)
        assert not valid
        assert "rse" in err.lower()
        assert "200077" in err

    def test_validate_accepts_rse_on_rse_required_modules(self):
        valid, err = tc.validate(ChannelType.CURRENT_INPUT, "rse", "NI 9208")
        assert valid, err
        valid, err = tc.validate(ChannelType.CURRENT_INPUT, "RSE", "NI-9203")
        assert valid, err

    def test_voltage_section_of_9207_still_diff(self):
        """The 9207 has a voltage section (ai0..ai7) that IS DIFF-only by
        hardware. Per-channel-type rule must keep that intact."""
        assert tc.coerce(ChannelType.VOLTAGE_INPUT, "rse", "NI 9207") == "differential"
        valid, _ = tc.validate(ChannelType.VOLTAGE_INPUT, "differential", "NI 9207")
        assert valid

    def test_voltage_can_keep_rse_on_regular_module(self):
        """RSE is fine for voltage inputs on non-DIFF-only modules."""
        assert tc.coerce(ChannelType.VOLTAGE_INPUT, "RSE") == "rse"


# ===================================================================
# 6. Channel config integration — config_parser uses the right defaults
# ===================================================================

class TestChannelConfigDefaults:

    def test_default_terminal_config_is_differential(self):
        """ChannelConfig.terminal_config must default to 'differential'."""
        ch = ChannelConfig(
            name="test",
            module="m",
            physical_channel="ai0",
            channel_type=ChannelType.CURRENT_INPUT,
        )
        assert ch.terminal_config == "differential"

    def test_default_passes_validation_for_current(self):
        ch = ChannelConfig(
            name="test",
            module="m",
            physical_channel="ai0",
            channel_type=ChannelType.CURRENT_INPUT,
        )
        valid, _ = tc.validate(ch.channel_type, ch.terminal_config)
        assert valid

    def test_default_passes_validation_for_voltage(self):
        ch = ChannelConfig(
            name="test",
            module="m",
            physical_channel="ai0",
            channel_type=ChannelType.VOLTAGE_INPUT,
        )
        valid, _ = tc.validate(ch.channel_type, ch.terminal_config)
        assert valid


# ===================================================================
# 7. End-to-end: simulate the channel update flow
# ===================================================================

class TestChannelUpdateFlow:
    """Simulate what happens when the frontend sends a terminal_config update."""

    def test_user_sets_diff_on_current_9208_gets_coerced_to_rse(self):
        """User selects DIFFERENTIAL on a 9208 current channel — backend
        knows DAQmx will reject DIFF (-200077) and coerces to RSE."""
        ch = ChannelConfig(
            name="mA_sensor",
            module="cDAQ1Mod1",
            physical_channel="cDAQ1Mod1/ai0",
            channel_type=ChannelType.CURRENT_INPUT,
        )

        # Simulate the channel update handler logic with the module type
        # known (the real handler looks it up from self.config.modules).
        requested = "differential"
        coerced = tc.coerce(ch.channel_type, requested, module_type="NI 9208")
        ch.terminal_config = coerced

        assert ch.terminal_config == "rse"

    def test_user_sets_rse_on_voltage_preserved(self):
        """User selects RSE on voltage input → preserved as-is."""
        ch = ChannelConfig(
            name="v_sensor",
            module="cDAQ1Mod2",
            physical_channel="cDAQ1Mod2/ai0",
            channel_type=ChannelType.VOLTAGE_INPUT,
        )

        requested = "RSE"
        coerced = tc.coerce(ch.channel_type, requested)
        ch.terminal_config = coerced

        assert ch.terminal_config == "rse"

    def test_legacy_config_with_default_gets_fixed(self):
        """Loading an old project file with terminal_config='DEFAULT' on a
        current input should be auto-corrected to 'differential'."""
        ch = ChannelConfig(
            name="legacy_mA",
            module="cDAQ1Mod1",
            physical_channel="cDAQ1Mod1/ai0",
            channel_type=ChannelType.CURRENT_INPUT,
            terminal_config="DEFAULT",
        )

        # Simulate the coercion that happens at the NI-DAQmx call site
        coerced = tc.coerce(ch.channel_type, ch.terminal_config)
        assert coerced == "differential"


# ===================================================================
# 8. All channel types — comprehensive coverage
# ===================================================================

class TestAllChannelTypes:
    """Make sure every ChannelType has a defined behavior — no gaps."""

    @pytest.mark.parametrize("ct", list(ChannelType))
    def test_every_type_has_defined_behavior(self, ct):
        """No ChannelType should fall through with undefined behavior."""
        # allowed_for() must return a set (possibly empty)
        allowed = tc.allowed_for(ct)
        assert isinstance(allowed, set)

        # coerce() must return a valid string
        result = tc.coerce(ct, "anything")
        assert isinstance(result, str)
        assert result in tc.ALL_TERMINAL_CONFIGS

        # validate() must return (bool, str)
        valid, err = tc.validate(ct, "differential")
        assert isinstance(valid, bool)
        assert isinstance(err, str)


# ===================================================================
# 9. Per-module overrides (NI-9215 etc. are DIFF-only by hardware)
# ===================================================================

class TestPerModuleOverride:
    """Some voltage modules are DIFF-only by physical design even though
    voltage_input would normally allow RSE/NRSE."""

    @pytest.mark.parametrize("module", [
        "NI-9215",  # 4-Ch Simultaneous ±10V
        "NI-9220",  # 16-Ch Simultaneous ±10V
        "NI-9229",  # 4-Ch Isolated ±60V
        "NI-9239",  # 4-Ch Isolated ±10V
    ])
    def test_simultaneous_voltage_modules_diff_only(self, module):
        """Simultaneous-sampling and isolated voltage modules are DIFF-only."""
        assert tc.is_module_differential_only(module)

    @pytest.mark.parametrize("module", [
        "NI-9201",  # 8-Ch ±10V (RSE/NRSE/DIFF configurable)
        "NI-9205",  # 32-Ch ±10V (RSE/NRSE/DIFF configurable)
        "NI-9221",  # 8-Ch ±60V
    ])
    def test_multimode_voltage_modules_not_diff_only(self, module):
        """Configurable voltage modules accept all terminal configs."""
        assert not tc.is_module_differential_only(module)

    def test_module_type_normalization(self):
        """Module names work with NI- prefix or bare model number."""
        assert tc.is_module_differential_only("NI-9215")
        assert tc.is_module_differential_only("ni-9215")
        assert tc.is_module_differential_only("9215")
        assert tc.is_module_differential_only("  NI-9215  ")

    def test_unknown_module_falls_back_to_channel_type(self):
        """Unknown module → no module-level restriction."""
        assert not tc.is_module_differential_only("NI-9999")
        assert not tc.is_module_differential_only("UNKNOWN")
        assert not tc.is_module_differential_only(None)
        assert not tc.is_module_differential_only("")

    def test_voltage_on_diff_only_module_coerced(self):
        """Voltage input on NI-9215 (DIFF-only) → forced to differential."""
        assert tc.coerce(ChannelType.VOLTAGE_INPUT, "RSE", "NI-9215") == "differential"
        assert tc.coerce(ChannelType.VOLTAGE_INPUT, "NRSE", "NI-9215") == "differential"

    def test_voltage_on_regular_module_preserves(self):
        """Voltage input on NI-9201 (configurable) → keeps user's choice."""
        assert tc.coerce(ChannelType.VOLTAGE_INPUT, "RSE", "NI-9201") == "rse"
        assert tc.coerce(ChannelType.VOLTAGE_INPUT, "NRSE", "NI-9201") == "nrse"

    def test_validate_rejects_rse_on_diff_only_module(self):
        """RSE on NI-9215 must be rejected with a clear error message."""
        valid, err = tc.validate(ChannelType.VOLTAGE_INPUT, "RSE", "NI-9215")
        assert not valid
        assert "NI-9215" in err
        assert "differential-only" in err.lower()

    def test_validate_accepts_diff_on_diff_only_module(self):
        valid, _ = tc.validate(ChannelType.VOLTAGE_INPUT, "differential", "NI-9215")
        assert valid

    def test_validate_accepts_rse_on_regular_module(self):
        valid, _ = tc.validate(ChannelType.VOLTAGE_INPUT, "RSE", "NI-9201")
        assert valid

    def test_allowed_for_diff_only_module(self):
        """allowed_for() returns only {differential} for DIFF-only modules."""
        allowed = tc.allowed_for(ChannelType.VOLTAGE_INPUT, "NI-9215")
        assert allowed == {"differential"}

    def test_allowed_for_regular_module(self):
        """allowed_for() returns all four for regular voltage modules."""
        allowed = tc.allowed_for(ChannelType.VOLTAGE_INPUT, "NI-9201")
        assert allowed == tc.ALL_TERMINAL_CONFIGS

    def test_allowed_for_no_module_uses_channel_type(self):
        """When module is unknown, fall back to channel-type rules."""
        allowed = tc.allowed_for(ChannelType.VOLTAGE_INPUT, None)
        assert allowed == tc.ALL_TERMINAL_CONFIGS
        # CURRENT_INPUT without module: permissive (we don't yet know
        # whether the channel resolves to an RSE-required module). The
        # coerce() helper picks RSE when the caller doesn't specify.
        allowed = tc.allowed_for(ChannelType.CURRENT_INPUT, None)
        assert allowed == tc.ALL_TERMINAL_CONFIGS


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
