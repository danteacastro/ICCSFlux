"""
Unit tests for GC Node orchestration — the data path from raw serial
voltage to GCAnalysisEngine and back to MQTT publishing.

Tests cover:
  - AnalysisSourceConfig creation and from_dict
  - State machine ANALYZING state and transitions
  - SerialSource streaming mode (voltage extraction, inject marker detection)
  - GCNodeService run lifecycle (inject → start_run → add_point → finish_run → publish)
  - Run timeout handling
  - Auto-run timer
  - Threshold inject detection
  - MQTT commands: start_run, stop_run, push_method, get_chromatogram
  - Config persistence with analysis_source section
"""

import json
import math
import os
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch, PropertyMock

# ======================================================================
# Config tests
# ======================================================================

from services.gc_node.config import (
    AnalysisSourceConfig,
    NodeConfig,
    load_config,
    save_config,
)

class TestAnalysisSourceConfig(unittest.TestCase):
    """Test AnalysisSourceConfig dataclass."""

    def test_defaults(self):
        cfg = AnalysisSourceConfig()
        self.assertFalse(cfg.enabled)
        self.assertEqual(cfg.mode, 'streaming')
        self.assertEqual(cfg.sample_rate_hz, 10.0)
        self.assertEqual(cfg.inject_trigger, 'mqtt')
        self.assertEqual(cfg.inject_marker, 'INJECT')
        self.assertEqual(cfg.run_duration_s, 300.0)
        self.assertTrue(cfg.publish_raw_chromatogram)

    def test_from_dict(self):
        data = {
            'enabled': True,
            'mode': 'parsed',
            'sample_rate_hz': 50,
            'method_file': '/path/to/method.json',
            'run_duration_s': 600,
            'inject_trigger': 'serial_marker',
            'inject_marker': 'START',
            'inject_threshold_v': 0.5,
            'auto_run_interval_s': 3600,
        }
        cfg = AnalysisSourceConfig.from_dict(data)
        self.assertTrue(cfg.enabled)
        self.assertEqual(cfg.mode, 'parsed')
        self.assertEqual(cfg.sample_rate_hz, 50.0)
        self.assertEqual(cfg.method_file, '/path/to/method.json')
        self.assertEqual(cfg.run_duration_s, 600.0)
        self.assertEqual(cfg.inject_trigger, 'serial_marker')
        self.assertEqual(cfg.inject_marker, 'START')
        self.assertEqual(cfg.inject_threshold_v, 0.5)
        self.assertEqual(cfg.auto_run_interval_s, 3600.0)

    def test_from_dict_empty(self):
        cfg = AnalysisSourceConfig.from_dict({})
        self.assertFalse(cfg.enabled)
        self.assertEqual(cfg.mode, 'streaming')

class TestNodeConfigWithAnalysis(unittest.TestCase):
    """Test NodeConfig includes analysis_source field."""

    def test_node_config_has_analysis_source(self):
        cfg = NodeConfig()
        self.assertIsInstance(cfg.analysis_source, AnalysisSourceConfig)
        self.assertFalse(cfg.analysis_source.enabled)

    def test_node_config_from_dict_with_analysis(self):
        data = {
            'system': {'node_id': 'gc-test'},
            'analysis_source': {
                'enabled': True,
                'mode': 'streaming',
                'inject_trigger': 'threshold',
                'inject_threshold_v': 0.2,
            },
        }
        cfg = NodeConfig.from_dict(data)
        self.assertEqual(cfg.node_id, 'gc-test')
        self.assertTrue(cfg.analysis_source.enabled)
        self.assertEqual(cfg.analysis_source.inject_trigger, 'threshold')
        self.assertEqual(cfg.analysis_source.inject_threshold_v, 0.2)

    def test_node_config_from_dict_without_analysis(self):
        data = {'system': {'node_id': 'gc-legacy'}}
        cfg = NodeConfig.from_dict(data)
        self.assertFalse(cfg.analysis_source.enabled)

    def test_save_load_roundtrip(self):
        cfg = NodeConfig(node_id='gc-round')
        cfg.analysis_source = AnalysisSourceConfig(
            enabled=True,
            mode='streaming',
            sample_rate_hz=25.0,
            inject_trigger='serial_marker',
            inject_marker='GO',
            run_duration_s=120.0,
        )

        with tempfile.NamedTemporaryFile(suffix='.json', delete=False, mode='w') as f:
            path = f.name

        try:
            save_config(cfg, path)
            loaded = NodeConfig.from_json_file(path)
            self.assertEqual(loaded.node_id, 'gc-round')
            self.assertTrue(loaded.analysis_source.enabled)
            self.assertEqual(loaded.analysis_source.sample_rate_hz, 25.0)
            self.assertEqual(loaded.analysis_source.inject_marker, 'GO')
            self.assertEqual(loaded.analysis_source.run_duration_s, 120.0)
        finally:
            os.unlink(path)

    def test_load_config_merge(self):
        existing = NodeConfig(node_id='gc-merge')
        existing.analysis_source = AnalysisSourceConfig(
            enabled=True, run_duration_s=300.0,
        )

        payload = {
            'system': {'node_name': 'Updated Name'},
            'analysis_source': {
                'enabled': True,
                'run_duration_s': 600.0,
            },
        }
        merged = load_config(payload, existing)
        self.assertEqual(merged.node_id, 'gc-merge')
        self.assertEqual(merged.node_name, 'Updated Name')
        self.assertTrue(merged.analysis_source.enabled)
        self.assertEqual(merged.analysis_source.run_duration_s, 600.0)

# ======================================================================
# State machine tests
# ======================================================================

from services.gc_node.state_machine import State, StateTransition, VALID_TRANSITIONS

class TestAnalyzingState(unittest.TestCase):
    """Test the ANALYZING state in the state machine."""

    def test_analyzing_state_exists(self):
        self.assertIn('ANALYZING', [s.name for s in State])

    def test_acquiring_to_analyzing(self):
        sm = StateTransition(State.ACQUIRING)
        self.assertTrue(sm.can_transition(State.ANALYZING))
        result = sm.to(State.ANALYZING)
        self.assertTrue(result)
        self.assertEqual(sm.state, State.ANALYZING)

    def test_analyzing_to_acquiring(self):
        sm = StateTransition(State.ANALYZING)
        self.assertTrue(sm.can_transition(State.ACQUIRING))
        result = sm.to(State.ACQUIRING)
        self.assertTrue(result)
        self.assertEqual(sm.state, State.ACQUIRING)

    def test_analyzing_to_error(self):
        sm = StateTransition(State.ANALYZING)
        result = sm.to(State.ERROR, {'error': 'test error'})
        self.assertTrue(result)
        self.assertEqual(sm.state, State.ERROR)
        self.assertEqual(sm.last_error, 'test error')

    def test_analyzing_to_idle(self):
        sm = StateTransition(State.ANALYZING)
        result = sm.to(State.IDLE)
        self.assertTrue(result)
        self.assertEqual(sm.state, State.IDLE)

    def test_idle_cannot_go_to_analyzing(self):
        sm = StateTransition(State.IDLE)
        self.assertFalse(sm.can_transition(State.ANALYZING))
        result = sm.to(State.ANALYZING)
        self.assertFalse(result)
        self.assertEqual(sm.state, State.IDLE)

    def test_is_analyzing_property(self):
        sm = StateTransition(State.ANALYZING)
        self.assertTrue(sm.is_analyzing)
        self.assertFalse(sm.is_acquiring)
        self.assertFalse(sm.is_error)

    def test_get_status_includes_analyzing(self):
        sm = StateTransition(State.ANALYZING)
        status = sm.get_status()
        self.assertEqual(status['state'], 'ANALYZING')
        self.assertTrue(status['analyzing'])
        self.assertFalse(status['acquiring'])

    def test_analyzing_callback_fired(self):
        sm = StateTransition(State.ACQUIRING)
        entered = []
        sm.on_enter(State.ANALYZING, lambda old, new, p: entered.append(True))
        sm.to(State.ANALYZING)
        self.assertEqual(len(entered), 1)

# ======================================================================
# SerialSource streaming mode tests
# ======================================================================

from services.gc_node.serial_source import SerialSource
from services.gc_node.config import SerialSourceConfig

class TestSerialSourceStreaming(unittest.TestCase):
    """Test SerialSource streaming mode (voltage extraction + inject markers)."""

    def _make_source(self, analysis_enabled=True, inject_trigger='mqtt',
                     inject_marker='INJECT', mode='streaming'):
        serial_cfg = SerialSourceConfig(
            enabled=True, port='COM99', protocol='line',
        )
        analysis_cfg = AnalysisSourceConfig(
            enabled=analysis_enabled,
            mode=mode,
            inject_trigger=inject_trigger,
            inject_marker=inject_marker,
        )
        self.frame_callback = MagicMock()
        self.raw_sample_callback = MagicMock()
        self.inject_callback = MagicMock()

        source = SerialSource(
            config=serial_cfg,
            on_new_frame=self.frame_callback,
            analysis_config=analysis_cfg if analysis_enabled else None,
            on_raw_sample=self.raw_sample_callback if analysis_enabled else None,
            on_inject_marker=self.inject_callback if analysis_enabled else None,
        )
        return source

    def test_streaming_mode_flag(self):
        source = self._make_source(analysis_enabled=True, mode='streaming')
        self.assertTrue(source._streaming_mode)

    def test_non_streaming_mode_flag(self):
        source = self._make_source(analysis_enabled=True, mode='parsed')
        self.assertFalse(source._streaming_mode)

    def test_disabled_analysis_no_streaming(self):
        source = self._make_source(analysis_enabled=False)
        self.assertFalse(source._streaming_mode)

    def test_voltage_extraction_plain_number(self):
        source = self._make_source()
        v = source._try_extract_voltage("0.4523")
        self.assertAlmostEqual(v, 0.4523)

    def test_voltage_extraction_labeled(self):
        source = self._make_source()
        self.assertAlmostEqual(source._try_extract_voltage("V=1.234"), 1.234)
        self.assertAlmostEqual(source._try_extract_voltage("voltage:0.567"), 0.567)

    def test_voltage_extraction_csv(self):
        source = self._make_source()
        v = source._try_extract_voltage("1234.5,0.789")
        self.assertAlmostEqual(v, 0.789)

    def test_voltage_extraction_non_numeric(self):
        source = self._make_source()
        v = source._try_extract_voltage("INJECT")
        self.assertIsNone(v)

    def test_inject_marker_detection(self):
        source = self._make_source(inject_marker='INJECT')
        # Simulate dispatching a frame that matches the marker
        source._dispatch_frame(b'INJECT')
        self.inject_callback.assert_called_once()
        # Should NOT call raw sample or frame callback
        self.raw_sample_callback.assert_not_called()
        self.frame_callback.assert_not_called()

    def test_inject_marker_case_insensitive(self):
        source = self._make_source(inject_marker='START')
        source._dispatch_frame(b'start run 1')
        self.inject_callback.assert_called_once()

    def test_streaming_dispatches_raw_sample(self):
        source = self._make_source()
        source._dispatch_frame(b'0.5432')
        self.raw_sample_callback.assert_called_once()
        args = self.raw_sample_callback.call_args[0]
        self.assertAlmostEqual(args[1], 0.5432)
        # Should NOT call the frame callback
        self.frame_callback.assert_not_called()

    def test_streaming_elapsed_time(self):
        source = self._make_source()
        source._dispatch_frame(b'0.1')
        t1 = self.raw_sample_callback.call_args[0][0]
        time.sleep(0.05)
        source._dispatch_frame(b'0.2')
        t2 = self.raw_sample_callback.call_args[0][0]
        self.assertGreater(t2, t1)

    def test_reset_stream_timer(self):
        source = self._make_source()
        source._stream_start_time = 100.0
        source._raw_samples_sent = 50
        source.reset_stream_timer()
        self.assertEqual(source._stream_start_time, 0.0)
        self.assertEqual(source._raw_samples_sent, 0)

    def test_non_streaming_dispatches_frame(self):
        source = self._make_source(analysis_enabled=True, mode='parsed')
        source._dispatch_frame(b'some,data,here')
        self.frame_callback.assert_called_once()
        self.raw_sample_callback.assert_not_called()

    def test_get_status_streaming(self):
        source = self._make_source()
        status = source.get_status()
        self.assertTrue(status['streaming_mode'])
        self.assertEqual(status['raw_samples_sent'], 0)

    def test_get_status_no_streaming(self):
        source = self._make_source(analysis_enabled=False)
        status = source.get_status()
        self.assertNotIn('streaming_mode', status)

# ======================================================================
# GCNodeService orchestration tests (mocked MQTT + hardware)
# ======================================================================

class MockMQTT:
    """Minimal mock for MQTTInterface."""
    def __init__(self):
        self.published = []
        self.on_message = None
        self.on_connection_change = None

    def connect(self):
        return True

    def disconnect(self):
        pass

    def wait_for_connection(self, timeout=10):
        return True

    def setup_standard_subscriptions(self):
        pass

    def topic(self, *parts):
        return '/'.join(['nisystem', 'nodes', 'gc-test'] + list(parts))

    def publish(self, topic, payload):
        self.published.append(('publish', topic, payload))

    def publish_critical(self, topic, payload, retain=False):
        self.published.append(('publish_critical', topic, payload))

class MockAnalysisEngine:
    """Minimal mock for GCAnalysisEngine."""
    def __init__(self):
        self.run_active = False
        self.points = []
        self.run_count = 0
        self._method = None

    def start_run(self, port=None):
        self.run_active = True
        self.points = []
        self.run_count += 1

    def add_point(self, t, v):
        if self.run_active:
            self.points.append((t, v))

    def finish_run(self):
        self.run_active = False
        return {
            'timestamp': '2026-01-15T10:00:00',
            'run_number': self.run_count,
            'components': {
                'Methane': {'concentration': 94.5, 'area_pct': 85.2, 'unit': '%'},
                'Ethane': {'concentration': 2.3, 'area_pct': 12.1, 'unit': '%'},
            },
            'total_area': 1000.0,
            'chromatogram_points': len(self.points),
        }

class MockAuditTrail:
    """Minimal mock for AuditTrail."""
    def __init__(self):
        self.events = []

    def log_event(self, event_type, details=None):
        self.events.append((event_type, details or {}))

def _make_test_service():
    """Create a GCNodeService configured for testing (no real MQTT/hardware)."""
    config = NodeConfig(
        node_id='gc-test',
        node_name='Test GC',
        gc_type='Agilent 7890',
        analysis_source=AnalysisSourceConfig(
            enabled=True,
            mode='streaming',
            inject_trigger='mqtt',
            run_duration_s=10.0,
            progress_interval_s=1.0,
            inject_debounce_s=0.5,
        ),
    )

    # Patch imports and create service with mocks
    with patch('services.gc_node.gc_node.MQTTInterface') as MockMQTTCls, \
         patch('services.gc_node.gc_node.AuditTrail') as MockAuditCls, \
         patch('services.gc_node.gc_node.ANALYSIS_AVAILABLE', True):

        mock_mqtt = MockMQTT()
        MockMQTTCls.return_value = mock_mqtt
        MockAuditCls.return_value = MockAuditTrail()

        # Temporarily make GCAnalysisEngine import not fail
        from services.gc_node.gc_node import GCNodeService
        service = GCNodeService(config)

    # Replace with our mocks
    service._mqtt = mock_mqtt
    service._audit = MockAuditTrail()
    service._analysis_engine = MockAnalysisEngine()
    service._analysis_method = MagicMock(name='test_method')
    service.state = StateTransition(State.ACQUIRING)

    return service

class TestGCNodeRunLifecycle(unittest.TestCase):
    """Test the inject → start_run → add_point → finish_run → publish pipeline."""

    def test_inject_trigger_starts_run(self):
        service = _make_test_service()
        service._on_inject_trigger()

        self.assertTrue(service._run_active)
        self.assertEqual(service._run_number, 1)
        self.assertEqual(service.state.state, State.ANALYZING)
        self.assertTrue(service._analysis_engine.run_active)

    def test_inject_trigger_debounce(self):
        service = _make_test_service()
        service._on_inject_trigger()
        # Immediately trigger again — should be debounced
        service._run_active = False  # Pretend run finished
        service.state.to(State.ACQUIRING)
        service._on_inject_trigger()
        # Should NOT have started a second run (debounce)
        self.assertEqual(service._run_number, 1)

    def test_inject_trigger_blocked_during_run(self):
        service = _make_test_service()
        service._on_inject_trigger()
        self.assertEqual(service._run_number, 1)

        # Wait past debounce
        service._last_inject_time = 0
        service._on_inject_trigger()
        # Still run 1 — blocked because run is active
        self.assertEqual(service._run_number, 1)

    def test_raw_sample_feeds_engine(self):
        service = _make_test_service()
        service._on_inject_trigger()

        service._on_raw_sample(1.0, 0.5)
        service._on_raw_sample(2.0, 1.2)
        service._on_raw_sample(3.0, 0.3)

        self.assertEqual(len(service._analysis_engine.points), 3)
        self.assertEqual(len(service._chromatogram_times), 3)
        self.assertEqual(len(service._chromatogram_values), 3)

    def test_raw_sample_no_run_ignores(self):
        service = _make_test_service()
        # No run active
        service._on_raw_sample(1.0, 0.5)
        self.assertEqual(len(service._analysis_engine.points), 0)

    def test_finish_run_publishes_results(self):
        service = _make_test_service()
        service._on_inject_trigger()
        service._on_raw_sample(1.0, 0.5)
        service._on_raw_sample(2.0, 1.0)

        service._finish_run(reason='command')

        self.assertFalse(service._run_active)
        self.assertEqual(service.state.state, State.ACQUIRING)

        # Check chromatogram was published
        chromatogram_published = any(
            'chromatogram' in msg[1] for msg in service._mqtt.published
        )
        self.assertTrue(chromatogram_published)

        # Check analysis result was published
        analysis_published = any(
            'analysis' in msg[1] for msg in service._mqtt.published
        )
        self.assertTrue(analysis_published)

    def test_finish_run_audit_logged(self):
        service = _make_test_service()
        service._on_inject_trigger()
        service._finish_run(reason='timeout')

        events = [e[0] for e in service._audit.events]
        self.assertIn('gc_run_started', events)
        self.assertIn('gc_run_finished', events)

        # Check finish details
        finish_evt = [e for e in service._audit.events if e[0] == 'gc_run_finished'][0]
        self.assertEqual(finish_evt[1]['reason'], 'timeout')

    def test_run_timeout(self):
        service = _make_test_service()
        service.config.analysis_source.run_duration_s = 0.1  # Very short
        service._on_inject_trigger()

        # Simulate elapsed time
        service._run_start_time = time.time() - 1.0  # 1 second ago
        service._check_run_timeout()

        self.assertFalse(service._run_active)
        self.assertEqual(service.state.state, State.ACQUIRING)

    def test_run_progress_published(self):
        service = _make_test_service()
        service.config.analysis_source.progress_interval_s = 0.0  # Immediate
        service._on_inject_trigger()
        service._on_raw_sample(1.0, 0.5)

        service._last_progress_time = 0  # Force progress publish
        service._check_run_progress()

        progress_published = any(
            'run_progress' in msg[1] for msg in service._mqtt.published
        )
        self.assertTrue(progress_published)

    def test_stop_run_during_active(self):
        service = _make_test_service()
        service._on_inject_trigger()
        self.assertTrue(service._run_active)

        # Simulate stop command
        service._handle_gc_command('/commands/gc', {'command': 'stop_run'})
        self.assertFalse(service._run_active)

    def test_start_run_mqtt_command(self):
        service = _make_test_service()
        service._handle_gc_command('/commands/gc', {'command': 'start_run'})
        self.assertTrue(service._run_active)
        self.assertEqual(service._run_number, 1)

    def test_get_chromatogram_command(self):
        service = _make_test_service()
        service._on_inject_trigger()
        service._on_raw_sample(1.0, 0.5)
        service._on_raw_sample(2.0, 1.0)
        service._finish_run(reason='command')

        # Clear published and request chromatogram
        service._mqtt.published.clear()
        service._handle_gc_command('/commands/gc', {'command': 'get_chromatogram'})

        chromatogram_published = any(
            'chromatogram' in msg[1] for msg in service._mqtt.published
        )
        self.assertTrue(chromatogram_published)

    def test_service_stop_finishes_run(self):
        service = _make_test_service()
        service._on_inject_trigger()
        self.assertTrue(service._run_active)

        service.stop()
        self.assertFalse(service._run_active)

        finish_events = [e for e in service._audit.events if e[0] == 'gc_run_finished']
        self.assertEqual(len(finish_events), 1)
        self.assertEqual(finish_events[0][1]['reason'], 'service_stop')

class TestThresholdInjectDetection(unittest.TestCase):
    """Test threshold-based inject trigger via raw samples."""

    def test_threshold_triggers_run(self):
        service = _make_test_service()
        service.config.analysis_source.inject_trigger = 'threshold'
        service.config.analysis_source.inject_threshold_v = 0.5

        # Below threshold — no run
        service._on_raw_sample(1.0, 0.3)
        self.assertFalse(service._run_active)

        # At/above threshold — triggers run
        service._on_raw_sample(2.0, 0.5)
        self.assertTrue(service._run_active)

    def test_threshold_no_retrigger_during_run(self):
        service = _make_test_service()
        service.config.analysis_source.inject_trigger = 'threshold'
        service.config.analysis_source.inject_threshold_v = 0.5

        service._on_raw_sample(1.0, 0.6)  # Triggers
        self.assertTrue(service._run_active)
        self.assertEqual(service._run_number, 1)

        # More points above threshold during run — should not start new run
        service._on_raw_sample(2.0, 0.8)
        self.assertEqual(service._run_number, 1)

class TestAutoRunTimer(unittest.TestCase):
    """Test timer-based auto-run trigger."""

    def test_auto_run_triggers(self):
        service = _make_test_service()
        service.config.analysis_source.inject_trigger = 'timer'
        service.config.analysis_source.auto_run_interval_s = 0.1

        # Set last auto-run far in the past
        service._last_auto_run_time = time.time() - 10
        service._check_auto_run_timer()

        self.assertTrue(service._run_active)

    def test_auto_run_disabled_when_zero_interval(self):
        service = _make_test_service()
        service.config.analysis_source.inject_trigger = 'timer'
        service.config.analysis_source.auto_run_interval_s = 0.0

        service._last_auto_run_time = time.time() - 10
        service._check_auto_run_timer()

        self.assertFalse(service._run_active)

    def test_auto_run_skipped_during_active_run(self):
        service = _make_test_service()
        service.config.analysis_source.inject_trigger = 'timer'
        service.config.analysis_source.auto_run_interval_s = 0.1

        service._on_inject_trigger()  # Start a run
        self.assertEqual(service._run_number, 1)

        service._last_auto_run_time = time.time() - 10
        service._check_auto_run_timer()

        # Should still be run 1 — not re-triggered
        self.assertEqual(service._run_number, 1)

    def test_auto_run_wrong_trigger_mode_ignored(self):
        service = _make_test_service()
        service.config.analysis_source.inject_trigger = 'mqtt'  # Not timer
        service.config.analysis_source.auto_run_interval_s = 0.1

        service._last_auto_run_time = time.time() - 10
        service._check_auto_run_timer()

        self.assertFalse(service._run_active)

class TestPushMethod(unittest.TestCase):
    """Test push_method MQTT command."""

    @patch('services.gc_node.gc_node.ANALYSIS_AVAILABLE', True)
    @patch('services.gc_node.gc_node.AnalysisMethod')
    def test_push_method_updates_engine(self, MockAM):
        service = _make_test_service()
        mock_method = MagicMock()
        mock_method.name = 'new_method'
        MockAM.from_dict.return_value = mock_method

        service._handle_gc_command('/commands/gc', {
            'command': 'push_method',
            'method': {'name': 'new_method', 'min_peak_height': 0.05},
        })

        MockAM.from_dict.assert_called_once()
        self.assertEqual(service._analysis_engine._method, mock_method)

class TestRunPublishContent(unittest.TestCase):
    """Test the content of published messages during a run."""

    def test_run_started_message(self):
        service = _make_test_service()
        service._on_inject_trigger()

        started_msgs = [
            msg for msg in service._mqtt.published
            if 'run_started' in msg[1]
        ]
        self.assertEqual(len(started_msgs), 1)
        payload = started_msgs[0][2]
        self.assertEqual(payload['run_number'], 1)
        self.assertEqual(payload['trigger'], 'mqtt')
        self.assertIn('timestamp', payload)

    def test_chromatogram_message_content(self):
        service = _make_test_service()
        service._on_inject_trigger()
        for i in range(10):
            service._on_raw_sample(i * 0.1, 0.5 + 0.1 * math.sin(i))
        service._finish_run(reason='command')

        chromatogram_msgs = [
            msg for msg in service._mqtt.published
            if 'chromatogram' in msg[1] and 'run_started' not in msg[1]
        ]
        self.assertTrue(len(chromatogram_msgs) >= 1)
        payload = chromatogram_msgs[0][2]
        self.assertEqual(payload['run_number'], 1)
        self.assertEqual(payload['points'], 10)
        self.assertEqual(len(payload['times']), 10)
        self.assertEqual(len(payload['values']), 10)

    def test_analysis_result_includes_components(self):
        service = _make_test_service()
        service._on_inject_trigger()
        service._on_raw_sample(1.0, 0.5)
        service._finish_run(reason='command')

        analysis_msgs = [
            msg for msg in service._mqtt.published
            if msg[1].endswith('analysis')
        ]
        self.assertTrue(len(analysis_msgs) >= 1)
        payload = analysis_msgs[0][2]
        self.assertIn('run_number', payload)
        self.assertIn('components', payload)

    def test_multiple_runs_increment_number(self):
        service = _make_test_service()

        service._on_inject_trigger()
        self.assertEqual(service._run_number, 1)
        service._finish_run(reason='command')

        # Wait past debounce
        service._last_inject_time = 0
        service._on_inject_trigger()
        self.assertEqual(service._run_number, 2)
        service._finish_run(reason='command')

        self.assertEqual(service._analysis_count, 2)

class TestStatusWithAnalysis(unittest.TestCase):
    """Test that status publishing includes analysis engine info."""

    def test_status_includes_analysis_fields(self):
        service = _make_test_service()
        service._publish_status()

        status_msgs = [
            msg for msg in service._mqtt.published
            if 'status' in msg[1]
        ]
        self.assertTrue(len(status_msgs) >= 1)
        payload = status_msgs[0][2]
        self.assertTrue(payload['analysis_engine_available'])
        self.assertTrue(payload['analysis_source_enabled'])
        self.assertFalse(payload['run_active'])
        self.assertEqual(payload['run_number'], 0)

    def test_status_during_active_run(self):
        service = _make_test_service()
        service._on_inject_trigger()
        service._on_raw_sample(1.0, 0.5)

        service._mqtt.published.clear()
        service._publish_status()

        status_msgs = [
            msg for msg in service._mqtt.published
            if 'status' in msg[1]
        ]
        payload = status_msgs[0][2]
        self.assertTrue(payload['run_active'])
        self.assertEqual(payload['run_number'], 1)
        self.assertIn('run_elapsed_s', payload)
        self.assertEqual(payload['run_points'], 1)

if __name__ == '__main__':
    unittest.main()
