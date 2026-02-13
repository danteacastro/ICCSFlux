"""
Unit tests for GCScheduler — priority queue for GC analysis runs.

Covers: config parsing, add/batch/cancel/clear, priority ordering,
run lifecycle, auto-insertion of blanks/cals, reorder, status, MQTT commands.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from services.gc_node.gc_scheduler import (
    GCScheduler, SchedulerConfig, QueuedRun, RunType, RunStatus,
)


def _make_scheduler(**overrides) -> GCScheduler:
    defaults = dict(enabled=True, auto_blank_interval=5, auto_cal_interval=10,
                    auto_blank_method='blank_method', auto_cal_method='cal_method',
                    max_queue_size=50)
    defaults.update(overrides)
    return GCScheduler(SchedulerConfig.from_dict(defaults))


class TestSchedulerConfig:
    def test_from_dict_defaults(self):
        cfg = SchedulerConfig.from_dict({})
        assert isinstance(cfg.auto_blank_interval, int)
        assert isinstance(cfg.auto_cal_interval, int)
        assert isinstance(cfg.max_queue_size, int)

    def test_from_dict_custom_values(self):
        cfg = SchedulerConfig.from_dict(dict(
            enabled=False, auto_blank_interval=3, auto_cal_interval=7,
            auto_blank_method='my_blank', auto_cal_method='my_cal', max_queue_size=100,
        ))
        assert cfg.enabled is False
        assert cfg.auto_blank_interval == 3
        assert cfg.auto_cal_interval == 7
        assert cfg.auto_blank_method == 'my_blank'
        assert cfg.auto_cal_method == 'my_cal'
        assert cfg.max_queue_size == 100


class TestAddRun:
    def test_add_single_run(self):
        sched = _make_scheduler()
        run = sched.add_run(sample_id='S001', run_type=RunType.SAMPLE, method_name='default')
        assert run is not None
        assert isinstance(run, QueuedRun)
        q = sched.get_queue()
        assert len(q) == 1 and q[0]['sample_id'] == 'S001'

    def test_add_run_auto_generates_id(self):
        sched = _make_scheduler()
        run = sched.add_run(sample_id='S002', run_type=RunType.SAMPLE, method_name='default')
        assert isinstance(run.run_id, str) and len(run.run_id) > 0

    def test_add_run_with_string_type(self):
        sched = _make_scheduler()
        run = sched.add_run(sample_id='S003', run_type='sample', method_name='default')
        assert run.run_type == RunType.SAMPLE

    def test_priority_ordering_cal_before_sample(self):
        sched = _make_scheduler()
        sched.add_run(sample_id='sample1', run_type=RunType.SAMPLE, method_name='m')
        sched.add_run(sample_id='cal1', run_type=RunType.CALIBRATION, method_name='m')
        nxt = sched.get_next_run()
        assert nxt is not None and nxt.run_type == RunType.CALIBRATION

    def test_queue_depth_limit(self):
        sched = _make_scheduler(max_queue_size=3)
        for i in range(3):
            run = sched.add_run(sample_id=f'S{i}', run_type=RunType.SAMPLE, method_name='m')
            assert run is not None
        with pytest.raises(ValueError):
            sched.add_run(sample_id='overflow', run_type=RunType.SAMPLE, method_name='m')
        assert len(sched.get_queue()) == 3


class TestBatchAdd:
    def test_add_batch_multiple(self):
        sched = _make_scheduler()
        batch = [{'sample_id': f'B{i}', 'run_type': t, 'method_name': 'meth'}
                 for i, t in enumerate(['sample', 'sample', 'blank'])]
        added = sched.add_batch(batch)
        assert len(added) == 3 and len(sched.get_queue()) == 3

    def test_batch_respects_priority(self):
        sched = _make_scheduler()
        sched.add_batch([
            {'sample_id': 'S1', 'run_type': 'sample', 'method_name': 'meth'},
            {'sample_id': 'BL1', 'run_type': 'blank', 'method_name': 'meth'},
        ])
        nxt = sched.get_next_run()
        assert nxt is not None and nxt.run_type == RunType.BLANK


class TestCancelAndClear:
    def test_cancel_run_removes_pending(self):
        sched = _make_scheduler()
        run = sched.add_run(sample_id='X1', run_type=RunType.SAMPLE, method_name='m')
        assert sched.cancel_run(run.run_id) is True
        assert len(sched.get_queue()) == 0

    def test_cancel_nonexistent_returns_false(self):
        assert _make_scheduler().cancel_run('no-such-id') is False

    def test_clear_queue_empties_all_pending(self):
        sched = _make_scheduler()
        for i in range(5):
            sched.add_run(sample_id=f'C{i}', run_type=RunType.SAMPLE, method_name='m')
        count = sched.clear_queue()
        assert count == 5
        assert len(sched.get_queue()) == 0


class TestRunLifecycle:
    def test_get_next_run_returns_highest_priority(self):
        sched = _make_scheduler()
        sched.add_run(sample_id='S1', run_type=RunType.SAMPLE, method_name='m')
        sched.add_run(sample_id='CS1', run_type=RunType.CHECK_STANDARD, method_name='m')
        nxt = sched.get_next_run()
        assert nxt is not None and nxt.run_type == RunType.CHECK_STANDARD

    def test_get_next_run_marks_as_running(self):
        sched = _make_scheduler()
        sched.add_run(sample_id='R1', run_type=RunType.SAMPLE, method_name='m')
        nxt = sched.get_next_run()
        assert nxt is not None and nxt.status == RunStatus.RUNNING

    def test_complete_current_run_success(self):
        sched = _make_scheduler()
        sched.add_run(sample_id='OK1', run_type=RunType.SAMPLE, method_name='m')
        sched.get_next_run()
        completed = sched.complete_current_run(success=True, result={'peaks': 5})
        assert completed is not None
        assert completed.status == RunStatus.COMPLETED
        assert sched.get_status()['completed_count'] >= 1

    def test_complete_current_run_failure(self):
        sched = _make_scheduler()
        sched.add_run(sample_id='FAIL1', run_type=RunType.SAMPLE, method_name='m')
        sched.get_next_run()
        completed = sched.complete_current_run(success=False, result={'error': 'timeout'})
        assert completed is not None
        assert completed.status == RunStatus.FAILED

    def test_complete_with_no_active_run_returns_none(self):
        sched = _make_scheduler()
        assert sched.complete_current_run() is None

    def test_get_next_run_while_active_returns_none(self):
        sched = _make_scheduler()
        sched.add_run(sample_id='A1', run_type=RunType.SAMPLE, method_name='m')
        sched.add_run(sample_id='A2', run_type=RunType.SAMPLE, method_name='m')
        sched.get_next_run()  # A1 now running
        assert sched.get_next_run() is None  # Can't get another while one is active


class TestAutoInserts:
    def _run_n_samples(self, sched, n):
        """Run n sample runs to completion (to trigger auto-insert counters)."""
        for i in range(n):
            sched.add_run(sample_id=f'AUTO{i}', run_type=RunType.SAMPLE, method_name='m')
            sched.get_next_run()
            sched.complete_current_run(success=True, result={})

    def test_auto_blank_after_n_samples(self):
        sched = _make_scheduler(auto_blank_interval=3, auto_cal_interval=0)
        self._run_n_samples(sched, 3)
        # Next get_next_run should return an auto-inserted blank
        nxt = sched.get_next_run()
        assert nxt is not None
        assert nxt.run_type == RunType.BLANK
        assert nxt.auto_inserted is True

    def test_auto_cal_after_n_samples(self):
        sched = _make_scheduler(auto_cal_interval=4, auto_blank_interval=0)
        self._run_n_samples(sched, 4)
        nxt = sched.get_next_run()
        assert nxt is not None
        assert nxt.run_type == RunType.CHECK_STANDARD
        assert nxt.auto_inserted is True

    def test_auto_blank_resets_counter(self):
        sched = _make_scheduler(auto_blank_interval=2, auto_cal_interval=0)
        self._run_n_samples(sched, 2)
        # Get and complete the auto-blank
        blank = sched.get_next_run()
        assert blank is not None and blank.run_type == RunType.BLANK
        sched.complete_current_run(success=True)
        assert sched.get_status()['sample_count_since_blank'] == 0

    def test_auto_insert_disabled_when_interval_zero(self):
        sched = _make_scheduler(auto_blank_interval=0, auto_cal_interval=0)
        self._run_n_samples(sched, 20)
        # No auto-inserts, queue should be empty
        assert sched.get_next_run() is None


class TestReorder:
    def test_move_run_to_new_position(self):
        sched = _make_scheduler()
        runs = [sched.add_run(sample_id=f'R{i}', run_type=RunType.SAMPLE, method_name='m')
                for i in range(3)]
        assert sched.reorder(runs[2].run_id, 0) is True
        assert sched.get_queue()[0]['run_id'] == runs[2].run_id

    def test_reorder_nonexistent_returns_false(self):
        assert _make_scheduler().reorder('ghost-id', 0) is False


class TestQueueGetStatus:
    def test_get_queue_returns_serializable_list(self):
        sched = _make_scheduler()
        sched.add_run(sample_id='Q1', run_type=RunType.SAMPLE, method_name='m')
        q = sched.get_queue()
        assert isinstance(q, list)
        for entry in q:
            assert isinstance(entry, dict)
            assert 'run_id' in entry and 'sample_id' in entry

    def test_get_status_has_correct_fields(self):
        status = _make_scheduler().get_status()
        for key in ('queue_depth', 'completed_count', 'current_run', 'enabled',
                     'total_runs', 'sample_count_since_blank', 'sample_count_since_cal'):
            assert key in status

    def test_queue_depth_property(self):
        sched = _make_scheduler()
        assert sched.queue_depth == 0
        sched.add_run(sample_id='QD1', run_type=RunType.SAMPLE, method_name='m')
        assert sched.queue_depth == 1

    def test_is_running_property(self):
        sched = _make_scheduler()
        assert sched.is_running is False
        sched.add_run(sample_id='IR1', run_type=RunType.SAMPLE, method_name='m')
        sched.get_next_run()
        assert sched.is_running is True


class TestMqttCommands:
    def test_handle_queue_add(self):
        sched = _make_scheduler()
        resp = sched.handle_command('queue_add', {
            'sample_id': 'MQTT1', 'run_type': 'sample', 'method_name': 'default'})
        assert resp['ok'] is True
        assert len(sched.get_queue()) == 1

    def test_handle_queue_batch(self):
        sched = _make_scheduler()
        resp = sched.handle_command('queue_batch', {'runs': [
            {'sample_id': 'MB1', 'run_type': 'sample', 'method_name': 'm'},
            {'sample_id': 'MB2', 'run_type': 'blank', 'method_name': 'm'},
        ]})
        assert resp['ok'] is True
        assert len(sched.get_queue()) == 2

    def test_handle_queue_cancel(self):
        sched = _make_scheduler()
        run = sched.add_run(sample_id='DEL1', run_type=RunType.SAMPLE, method_name='m')
        resp = sched.handle_command('queue_cancel', {'run_id': run.run_id})
        assert resp['ok'] is True
        assert len(sched.get_queue()) == 0

    def test_handle_queue_clear(self):
        sched = _make_scheduler()
        for i in range(3):
            sched.add_run(sample_id=f'CLR{i}', run_type=RunType.SAMPLE, method_name='m')
        resp = sched.handle_command('queue_clear', {})
        assert resp['ok'] is True
        assert len(sched.get_queue()) == 0

    def test_handle_queue_get(self):
        sched = _make_scheduler()
        sched.add_run(sample_id='GET1', run_type=RunType.SAMPLE, method_name='m')
        resp = sched.handle_command('queue_get', {})
        assert resp['ok'] is True
        assert 'queue' in resp and 'status' in resp

    def test_handle_unknown_command(self):
        sched = _make_scheduler()
        resp = sched.handle_command('queue_unknown', {})
        assert resp['ok'] is False

    def test_handle_queue_reorder(self):
        sched = _make_scheduler()
        runs = [sched.add_run(sample_id=f'RO{i}', run_type=RunType.SAMPLE, method_name='m')
                for i in range(3)]
        resp = sched.handle_command('queue_reorder', {
            'run_id': runs[2].run_id, 'position': 0})
        assert resp['ok'] is True
