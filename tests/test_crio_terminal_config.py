"""
cRIO Terminal Config Tests

The cRIO node is deployed to the controller as a self-contained bundle,
so it has its own copy of the validation logic (it can't import from
daq_service). These tests verify:

  1. The cRIO source no longer hardcodes TerminalConfiguration.DEFAULT
  2. Current/TC/RTD/strain channels get DIFFERENTIAL via _resolve_terminal_config
  3. Voltage channels respect the user's choice
  4. Legacy 'DEFAULT' is coerced to DIFF
  5. The legacy crio_node default is no longer 'RSE'

Without these tests, a cRIO user would hit Mike's 126 mA bug.
"""

import pytest
import sys
import re
from pathlib import Path
from unittest.mock import MagicMock

CRIO_HARDWARE = Path(__file__).parent.parent / "services" / "crio_node_v2" / "hardware.py"
CRIO_NODE_V1 = Path(__file__).parent.parent / "services" / "crio_node" / "crio_node.py"
CRIO_NODE_V2 = Path(__file__).parent.parent / "services" / "crio_node_v2" / "crio_node.py"


# ===================================================================
# 1. Source-level checks — verify the bug is actually fixed in the file
# ===================================================================

class TestCrioSourceFixed:

    def test_crio_v2_no_hardcoded_default_anywhere(self):
        """The cRIO source must no longer contain TerminalConfiguration.DEFAULT.
        The validator uses .DIFF as the safe default."""
        content = CRIO_HARDWARE.read_text(encoding='utf-8')
        # Should NOT contain TerminalConfiguration.DEFAULT anywhere
        assert "TerminalConfiguration.DEFAULT" not in content, (
            "cRIO hardware.py still contains TerminalConfiguration.DEFAULT — "
            "this causes the 126 mA bug on current input modules"
        )

    def test_crio_v2_uses_resolver_at_call_sites(self):
        """The add_ai_current_chan and add_ai_voltage_chan calls should use
        _resolve_terminal_config to get their terminal_config value."""
        content = CRIO_HARDWARE.read_text(encoding='utf-8')
        # Count uses of _resolve_terminal_config — should be at least 2
        # (one for current_input, one for voltage)
        uses = content.count("_resolve_terminal_config(")
        # Subtract 1 for the function definition itself
        call_uses = uses - 1
        assert call_uses >= 2, (
            f"_resolve_terminal_config called only {call_uses} times outside "
            f"its definition — expected at least 2 (current_input, voltage)"
        )

    def test_crio_v2_has_resolve_terminal_config(self):
        """The _resolve_terminal_config helper must exist."""
        content = CRIO_HARDWARE.read_text(encoding='utf-8')
        assert "def _resolve_terminal_config" in content
        assert "_DIFFERENTIAL_ONLY_TYPES" in content
        assert "current_input" in content
        assert "thermocouple" in content

    def test_crio_v2_push_default_is_differential(self):
        """The cRIO config push (in crio_node.py) should default to
        'differential', not 'RSE'."""
        content = CRIO_NODE_V2.read_text(encoding='utf-8')
        # Find: 'terminal_config': getattr(ch, 'terminal_config', 'X')
        match = re.search(
            r"'terminal_config':\s*getattr\(ch,\s*'terminal_config',\s*'(\w+)'",
            content
        )
        assert match, "Could not find terminal_config default in cRIO push"
        default = match.group(1).lower()
        assert default in ('differential', 'diff'), (
            f"cRIO config push defaults terminal_config to '{default}' — "
            f"should be 'differential'"
        )

    def test_legacy_crio_default_is_diff_not_rse(self):
        """Old crio_node had terminal_config: str = 'RSE' — wrong for current."""
        content = CRIO_NODE_V1.read_text(encoding='utf-8')
        match = re.search(
            r"terminal_config:\s*str\s*=\s*'(\w+)'", content
        )
        assert match, "Could not find terminal_config dataclass default"
        default = match.group(1).upper()
        assert default in ('DIFF', 'DIFFERENTIAL'), (
            f"Legacy crio_node defaults terminal_config to '{default}' — "
            f"should be 'DIFF'"
        )

    def test_crio_v2_has_cjc_aliases(self):
        """The cRIO CJC map must accept all aliases (CONST_VAL, EXTERNAL, etc.)."""
        content = CRIO_HARDWARE.read_text(encoding='utf-8')
        # Find the cjc_map definition
        match = re.search(r"cjc_map\s*=\s*\{([^}]+)\}", content, re.DOTALL)
        assert match, "Could not find cjc_map"
        cjc_block = match.group(1)
        # Required aliases
        required_aliases = ['INTERNAL', 'BUILT_IN', 'CONSTANT', 'CONST_VAL',
                            'CHANNEL', 'EXTERNAL']
        for alias in required_aliases:
            assert f"'{alias}'" in cjc_block, (
                f"cRIO cjc_map is missing alias '{alias}' — "
                f"frontend may send this value"
            )


# ===================================================================
# 2. Logic replica — verify the algorithm produces the right results
# ===================================================================

# Reproduce the cRIO _resolve_terminal_config logic for testing.
# This must stay in sync with services/crio_node_v2/hardware.py.

_DIFFERENTIAL_ONLY_TYPES = {
    'current_input', 'current_output',
    'thermocouple', 'rtd',
    'strain', 'strain_input', 'bridge_input',
    'resistance', 'resistance_input',
    'iepe', 'iepe_input',
}

class FakeTC:
    DIFF = 'DIFF'
    RSE = 'RSE'
    NRSE = 'NRSE'
    PSEUDO_DIFF = 'PSEUDO_DIFF'

def _resolve_terminal_config_replica(channel_type, requested):
    """Replica of the function in crio_node_v2/hardware.py."""
    TC = FakeTC
    if channel_type in _DIFFERENTIAL_ONLY_TYPES:
        return TC.DIFF
    config_map = {
        'RSE': TC.RSE,
        'DIFF': TC.DIFF,
        'DIFFERENTIAL': TC.DIFF,
        'NRSE': TC.NRSE,
        'PSEUDO_DIFF': TC.PSEUDO_DIFF,
        'PSEUDODIFFERENTIAL': TC.PSEUDO_DIFF,
        'DEFAULT': TC.DIFF,
    }
    key = (requested or 'DIFFERENTIAL').upper().strip()
    return config_map.get(key, TC.DIFF)


class TestCrioLogicReplica:
    """Verify the algorithm — uses a local replica of the cRIO function."""

    @pytest.mark.parametrize("ct", [
        'current_input', 'current_output',
        'thermocouple', 'rtd',
        'strain', 'strain_input', 'bridge_input',
        'resistance', 'resistance_input',
        'iepe', 'iepe_input',
    ])
    def test_differential_only_types_always_diff(self, ct):
        """All differential-only types must coerce to DIFF regardless of input."""
        for bad in ['RSE', 'NRSE', 'PSEUDO_DIFF', 'DEFAULT', 'garbage', None, '']:
            assert _resolve_terminal_config_replica(ct, bad) == 'DIFF', \
                f"{ct} with '{bad}' did not coerce to DIFF"

    def test_voltage_input_respects_choice(self):
        assert _resolve_terminal_config_replica('voltage_input', 'RSE') == 'RSE'
        assert _resolve_terminal_config_replica('voltage_input', 'DIFF') == 'DIFF'
        assert _resolve_terminal_config_replica('voltage_input', 'NRSE') == 'NRSE'
        assert _resolve_terminal_config_replica('voltage_input', 'PSEUDO_DIFF') == 'PSEUDO_DIFF'

    def test_voltage_input_legacy_default_to_diff(self):
        """Legacy 'DEFAULT' on voltage input → safest (DIFF), not NI auto-pick."""
        assert _resolve_terminal_config_replica('voltage_input', 'DEFAULT') == 'DIFF'

    def test_voltage_input_unknown_to_diff(self):
        assert _resolve_terminal_config_replica('voltage_input', 'garbage') == 'DIFF'
        assert _resolve_terminal_config_replica('voltage_input', None) == 'DIFF'
        assert _resolve_terminal_config_replica('voltage_input', '') == 'DIFF'

    def test_case_insensitive(self):
        assert _resolve_terminal_config_replica('voltage_input', 'rse') == 'RSE'
        assert _resolve_terminal_config_replica('voltage_input', 'Rse') == 'RSE'

    def test_mike_126ma_scenario(self):
        """The exact bug: current_input + 'DEFAULT' → must give DIFF."""
        result = _resolve_terminal_config_replica('current_input', 'DEFAULT')
        assert result == 'DIFF'


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
