"""
CJC Source Validation Tests

Cold Junction Compensation source applies only to thermocouple channels.
The wrong CJC source produces a temperature offset (wrong reading by the
amount the cold junction differs from what's assumed).

The frontend uses 'internal' / 'constant' / 'channel' but NI-DAQmx uses
BUILT_IN / CONSTANT_USER_VALUE / SCANNABLE_CHANNEL. We need to handle
both name systems and aliases.
"""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "daq_service"))

import cjc_source as cjc
from config_parser import ChannelType, ChannelConfig, ThermocoupleType


# ===================================================================
# 1. Normalization
# ===================================================================

class TestNormalize:

    def test_canonical(self):
        assert cjc.normalize("internal") == "internal"
        assert cjc.normalize("constant") == "constant"
        assert cjc.normalize("channel") == "channel"

    def test_uppercase(self):
        assert cjc.normalize("INTERNAL") == "internal"
        assert cjc.normalize("CONSTANT") == "constant"
        assert cjc.normalize("CHANNEL") == "channel"

    def test_mixed_case(self):
        assert cjc.normalize("Internal") == "internal"
        assert cjc.normalize("Channel") == "channel"

    def test_whitespace(self):
        assert cjc.normalize("  internal  ") == "internal"
        assert cjc.normalize("\tCHANNEL\n") == "channel"

    def test_nidaqmx_aliases(self):
        """NI-DAQmx uses different names than our frontend."""
        assert cjc.normalize("BUILT_IN") == "internal"
        assert cjc.normalize("built_in") == "internal"
        assert cjc.normalize("builtin") == "internal"
        assert cjc.normalize("CONST_VAL") == "constant"
        assert cjc.normalize("CONSTANT_USER_VALUE") == "constant"
        assert cjc.normalize("SCANNABLE_CHANNEL") == "channel"
        assert cjc.normalize("EXTERNAL") == "channel"
        assert cjc.normalize("ext") == "channel"

    def test_empty_returns_internal(self):
        """Most NI thermocouple modules have built-in CJC, so 'internal' is safest."""
        assert cjc.normalize(None) == "internal"
        assert cjc.normalize("") == "internal"
        assert cjc.normalize("   ") == "internal"

    def test_unknown_returns_internal(self):
        assert cjc.normalize("garbage") == "internal"
        assert cjc.normalize("auto") == "internal"


# ===================================================================
# 2. Relevance check
# ===================================================================

class TestIsRelevant:

    def test_thermocouple_relevant(self):
        assert cjc.is_relevant(ChannelType.THERMOCOUPLE)

    @pytest.mark.parametrize("ct", [
        ChannelType.RTD,
        ChannelType.VOLTAGE_INPUT,
        ChannelType.CURRENT_INPUT,
        ChannelType.STRAIN,
        ChannelType.IEPE,
        ChannelType.DIGITAL_INPUT,
        ChannelType.MODBUS_REGISTER,
    ])
    def test_other_types_not_relevant(self, ct):
        """CJC is only meaningful for thermocouples."""
        assert not cjc.is_relevant(ct)


# ===================================================================
# 3. Validation
# ===================================================================

class TestValidate:

    def test_valid_internal_for_thermocouple(self):
        valid, err = cjc.validate(ChannelType.THERMOCOUPLE, "internal")
        assert valid
        assert err == ""

    def test_valid_constant_for_thermocouple(self):
        valid, err = cjc.validate(ChannelType.THERMOCOUPLE, "constant")
        assert valid

    def test_valid_channel_for_thermocouple(self):
        valid, err = cjc.validate(ChannelType.THERMOCOUPLE, "channel")
        assert valid

    def test_aliases_valid(self):
        for alias in ["BUILT_IN", "CONST_VAL", "EXTERNAL", "SCANNABLE_CHANNEL"]:
            valid, _ = cjc.validate(ChannelType.THERMOCOUPLE, alias)
            assert valid

    def test_non_thermocouple_anything_valid(self):
        """CJC is ignored for non-TC channels — always valid."""
        for cfg in ["internal", "garbage", "", None]:
            valid, _ = cjc.validate(ChannelType.VOLTAGE_INPUT, cfg)
            assert valid


# ===================================================================
# 4. Coercion
# ===================================================================

class TestCoerce:

    def test_thermocouple_preserves_valid(self):
        assert cjc.coerce(ChannelType.THERMOCOUPLE, "internal") == "internal"
        assert cjc.coerce(ChannelType.THERMOCOUPLE, "constant") == "constant"
        assert cjc.coerce(ChannelType.THERMOCOUPLE, "channel") == "channel"

    def test_thermocouple_normalizes_aliases(self):
        assert cjc.coerce(ChannelType.THERMOCOUPLE, "BUILT_IN") == "internal"
        assert cjc.coerce(ChannelType.THERMOCOUPLE, "CONSTANT_USER_VALUE") == "constant"
        assert cjc.coerce(ChannelType.THERMOCOUPLE, "SCANNABLE_CHANNEL") == "channel"
        assert cjc.coerce(ChannelType.THERMOCOUPLE, "ext") == "channel"

    def test_thermocouple_unknown_returns_internal(self):
        assert cjc.coerce(ChannelType.THERMOCOUPLE, "garbage") == "internal"
        assert cjc.coerce(ChannelType.THERMOCOUPLE, None) == "internal"
        assert cjc.coerce(ChannelType.THERMOCOUPLE, "") == "internal"

    def test_non_thermocouple_returns_internal(self):
        """CJC is ignored for non-TC channels — return canonical default."""
        assert cjc.coerce(ChannelType.VOLTAGE_INPUT, "garbage") == "internal"
        assert cjc.coerce(ChannelType.RTD, "BUILT_IN") == "internal"
        assert cjc.coerce(ChannelType.DIGITAL_INPUT, "channel") == "internal"


# ===================================================================
# 5. End-to-end channel update flow
# ===================================================================

class TestChannelUpdateFlow:

    def test_user_sets_built_in_normalized(self):
        """User picks 'BUILT_IN' (NI alias) → backend stores 'internal' (canonical)."""
        ch = ChannelConfig(
            name="tc1",
            module="cDAQ1Mod1",
            physical_channel="cDAQ1Mod1/ai0",
            channel_type=ChannelType.THERMOCOUPLE,
            thermocouple_type=ThermocoupleType.K,
        )
        coerced = cjc.coerce(ch.channel_type, "BUILT_IN")
        ch.cjc_source = coerced
        assert ch.cjc_source == "internal"

    def test_user_sets_external_alias(self):
        """User picks 'external' (alternative term for channel-based CJC)."""
        coerced = cjc.coerce(ChannelType.THERMOCOUPLE, "external")
        assert coerced == "channel"

    def test_legacy_config_const_val(self):
        """Loading old config with 'CONST_VAL' gets normalized."""
        coerced = cjc.coerce(ChannelType.THERMOCOUPLE, "CONST_VAL")
        assert coerced == "constant"


# ===================================================================
# 6. All channel types — gap check
# ===================================================================

class TestAllChannelTypes:

    @pytest.mark.parametrize("ct", list(ChannelType))
    def test_every_type_has_defined_behavior(self, ct):
        """No channel type should fall through with undefined behavior."""
        # is_relevant returns bool
        assert isinstance(cjc.is_relevant(ct), bool)
        # validate returns (bool, str)
        valid, err = cjc.validate(ct, "internal")
        assert isinstance(valid, bool)
        assert isinstance(err, str)
        # coerce returns a known value
        result = cjc.coerce(ct, "anything")
        assert result in cjc.ALL_CJC_SOURCES


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
