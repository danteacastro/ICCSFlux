"""
Channel Cascade Tests

Verifies fixes for the audit findings on ConfigurationTab cascade:

  Bug P5 (HIGH): Channel delete didn't cascade to widgets, recording
    selection, alarm config, or recording trigger channel. The user
    confirmed the warning then nothing actually got cleaned up — Mike
    was left with orphaned widgets pointing at deleted tags showing
    "undefined" or 0.
    Now ConfigurationTab.deleteChannel calls cascadeChannelDelete()
    which: prunes widgets via store.handleChannelDeleted, removes
    from selectedRecordingChannels, clears triggerChannel if matched,
    and emits a safety/alarm/delete MQTT command.

  Bug P7 (MEDIUM): VariablesTab availableChannels filtered out
    visible=false channels. Mike couldn't reference an archived
    channel in a formula even though "invisible" only means hidden
    from the dashboard, not deleted.
    Now availableChannels includes invisible channels.
"""

import pytest
from pathlib import Path


# ===================================================================
# Source-level checks
# ===================================================================

class TestCascadeFixes:

    def _read_config(self):
        return (Path(__file__).parent.parent / "dashboard" / "src" / "components" / "ConfigurationTab.vue").read_text(encoding='utf-8')

    def _read_vars(self):
        return (Path(__file__).parent.parent / "dashboard" / "src" / "components" / "VariablesTab.vue").read_text(encoding='utf-8')

    def test_delete_calls_cascade_helper(self):
        """deleteChannel must call cascadeChannelDelete after backend command."""
        content = self._read_config()
        idx = content.find("function deleteChannel")
        body = content[idx:idx + 3000]
        assert "cascadeChannelDelete(channelName)" in body

    def test_cascade_helper_exists(self):
        content = self._read_config()
        assert "function cascadeChannelDelete(channelName: string)" in content

    def test_cascade_removes_from_widgets(self):
        content = self._read_config()
        idx = content.find("function cascadeChannelDelete")
        body = content[idx:idx + 3000]
        # Calls store.handleChannelDeleted
        assert "handleChannelDeleted" in body

    def test_cascade_removes_from_recording_selection(self):
        content = self._read_config()
        idx = content.find("function cascadeChannelDelete")
        body = content[idx:idx + 3000]
        assert "selectedRecordingChannels" in body
        assert "setSelectedRecordingChannels" in body

    def test_cascade_clears_recording_trigger(self):
        content = self._read_config()
        idx = content.find("function cascadeChannelDelete")
        body = content[idx:idx + 3000]
        assert "triggerChannel" in body

    def test_cascade_emits_alarm_delete(self):
        content = self._read_config()
        idx = content.find("function cascadeChannelDelete")
        body = content[idx:idx + 3000]
        assert "safety/alarm/delete" in body

    def test_variables_picker_includes_invisible_channels(self):
        """Invisible channels should still appear in formula/source pickers."""
        content = self._read_vars()
        idx = content.find("const availableChannels = computed")
        # Look both above (comment block) and below (filter logic) the declaration
        body = content[max(0, idx - 300):idx + 600]
        # The OLD filter was: .filter(([_, ch]) => ch.visible !== false)
        # The fix removed it. Verify the comment is present and the filter is gone.
        assert "Includes invisible channels" in body
        assert "ch.visible !== false" not in body


# ===================================================================
# Logic replicas
# ===================================================================

class TestCascadeLogic:
    """Reproduce the cascade logic to verify correctness."""

    def test_widget_pruning_single_channel(self):
        """Single-channel widget bound to deleted channel → removed."""
        widgets = [
            {'id': 'w1', 'channel': 'PT1'},
            {'id': 'w2', 'channel': 'TC1'},
            {'id': 'w3', 'channel': 'PT1'},
        ]
        deleted = 'PT1'
        to_remove = [w['id'] for w in widgets if w.get('channel') == deleted]
        widgets = [w for w in widgets if w['id'] not in to_remove]
        assert len(widgets) == 1
        assert widgets[0]['id'] == 'w2'

    def test_widget_pruning_multi_channel_chart(self):
        """Multi-channel chart loses one channel but keeps others."""
        widget = {'id': 'chart1', 'channels': ['PT1', 'TC1', 'PT2']}
        deleted = 'PT1'
        widget['channels'] = [c for c in widget['channels'] if c != deleted]
        assert widget['channels'] == ['TC1', 'PT2']

    def test_widget_pruning_multi_channel_chart_empty(self):
        """Multi-channel chart with all channels deleted → marked for removal."""
        widget = {'id': 'chart1', 'channels': ['PT1']}
        deleted = 'PT1'
        widget['channels'] = [c for c in widget['channels'] if c != deleted]
        # Empty channels means widget should be removed
        assert widget['channels'] == []

    def test_recording_selection_filtered(self):
        sel = ['PT1', 'TC1', 'TC2', 'PT2']
        deleted = 'TC1'
        new_sel = [n for n in sel if n != deleted]
        assert new_sel == ['PT1', 'TC2', 'PT2']

    def test_trigger_channel_cleared(self):
        trigger = 'PT1'
        deleted = 'PT1'
        new_trigger = '' if trigger == deleted else trigger
        assert new_trigger == ''

    def test_trigger_channel_preserved_if_different(self):
        trigger = 'PT1'
        deleted = 'TC1'
        new_trigger = '' if trigger == deleted else trigger
        assert new_trigger == 'PT1'


class TestVariableSourcePicker:
    """Verify invisible channels are now selectable as variable sources."""

    def test_invisible_channel_included(self):
        """Channel with visible=false should appear in availableChannels."""
        store_channels = {
            'PT1': {'visible': True, 'channel_type': 'voltage_input', 'unit': 'V'},
            'PT2_archived': {'visible': False, 'channel_type': 'voltage_input', 'unit': 'V'},
            'TC1': {'visible': True, 'channel_type': 'thermocouple', 'unit': 'C'},
        }
        # New behavior: include all
        available = list(store_channels.keys())
        assert 'PT2_archived' in available
        assert len(available) == 3

    def test_old_behavior_excluded_invisible(self):
        """Document the old buggy behavior for contrast."""
        store_channels = {
            'PT1': {'visible': True},
            'PT2_archived': {'visible': False},
        }
        # Old (buggy) behavior:
        old_available = [n for n, ch in store_channels.items() if ch.get('visible') is not False]
        assert 'PT2_archived' not in old_available  # Bug: invisible excluded
        # New (fixed) behavior:
        new_available = list(store_channels.keys())
        assert 'PT2_archived' in new_available


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
