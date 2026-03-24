#!/usr/bin/env python3
"""
Test script for RecordingManager with new file management options
"""

import os
import sys
import time
import tempfile
import shutil
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from recording_manager import RecordingManager, RecordingConfig

def test_basic_recording():
    """Test basic recording functionality"""
    print("\n=== Test: Basic Recording ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        manager = RecordingManager(tmpdir)

        # Configure with defaults - must set base_path explicitly
        manager.configure({
            'base_path': tmpdir,
            'sample_interval': 1.0,
            'sample_interval_unit': 'seconds',
            'rotation_mode': 'single',
            'write_mode': 'immediate'
        })

        # Start recording
        assert manager.start(), "Failed to start recording"
        print(f"  Started recording to: {manager.current_file}")

        # Write some samples
        for i in range(5):
            manager.write_sample(
                {'temperature': 25.0 + i, 'pressure': 100.0 + i * 0.5},
                {'temperature': {'units': 'C'}, 'pressure': {'units': 'PSI'}}
            )

        # Check status
        status = manager.get_status()
        print(f"  Samples written: {status['recording_samples']}")
        assert status['recording_samples'] == 5, f"Expected 5 samples, got {status['recording_samples']}"

        # Stop recording
        assert manager.stop(), "Failed to stop recording"

        # Verify file exists
        files = manager.list_files()
        assert len(files) == 1, f"Expected 1 file, got {len(files)}"
        print(f"  File created: {files[0]['name']}")

        # Read and verify content
        with open(files[0]['path'], 'r') as f:
            content = f.read()
            assert 'temperature' in content
            assert 'pressure' in content
            print("  File content verified!")

        print("  PASSED!")

def test_sample_interval_milliseconds():
    """Test millisecond interval configuration"""
    print("\n=== Test: Millisecond Intervals ===")

    config = RecordingConfig()
    config.sample_interval = 100
    config.sample_interval_unit = 'milliseconds'
    config.decimation = 1

    rate = config.effective_sample_rate_hz
    print(f"  100ms interval = {rate} Hz")
    assert abs(rate - 10.0) < 0.001, f"Expected 10 Hz, got {rate}"

    config.decimation = 2
    rate = config.effective_sample_rate_hz
    print(f"  100ms interval with decimation=2 = {rate} Hz")
    assert abs(rate - 5.0) < 0.001, f"Expected 5 Hz, got {rate}"

    print("  PASSED!")

def test_naming_patterns():
    """Test different naming patterns"""
    print("\n=== Test: Naming Patterns ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        manager = RecordingManager(tmpdir)

        # Test timestamp naming
        manager.configure({
            'base_path': tmpdir,
            'naming_pattern': 'timestamp',
            'include_date': True,
            'include_time': True,
            'file_prefix': 'test'
        })
        manager.start()
        filename1 = manager.current_file.name
        manager.stop()
        print(f"  Timestamp naming: {filename1}")
        assert 'test_' in filename1

        # Test sequential naming
        manager.configure({
            'base_path': tmpdir,
            'naming_pattern': 'sequential',
            'sequential_start': 1,
            'sequential_padding': 3,
            'file_prefix': 'data'
        })
        manager.start()
        filename2 = manager.current_file.name
        manager.stop()
        print(f"  Sequential naming: {filename2}")
        assert '001' in filename2

        # Second file should be 002
        manager.start()
        filename3 = manager.current_file.name
        manager.stop()
        print(f"  Sequential naming (2nd): {filename3}")
        assert '002' in filename3

        # Test custom suffix
        manager.configure({
            'base_path': tmpdir,
            'naming_pattern': 'custom',
            'file_prefix': 'experiment',
            'custom_suffix': 'run_A'
        })
        manager.start()
        filename4 = manager.current_file.name
        manager.stop()
        print(f"  Custom suffix: {filename4}")
        assert 'run_A' in filename4

        print("  PASSED!")

def test_directory_organization():
    """Test directory structure options"""
    print("\n=== Test: Directory Organization ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        manager = RecordingManager(tmpdir)

        # Test flat structure
        manager.configure({'directory_structure': 'flat', 'base_path': tmpdir})
        manager.start()
        path1 = manager.current_file.parent
        manager.stop()
        print(f"  Flat: {path1}")
        assert str(path1) == tmpdir

        # Test daily structure
        manager.configure({'directory_structure': 'daily', 'base_path': tmpdir})
        manager.start()
        path2 = manager.current_file.parent
        manager.stop()
        print(f"  Daily: {path2}")
        # Should have YYYY/MM/DD structure
        parts = path2.relative_to(tmpdir).parts
        assert len(parts) == 3, f"Expected 3 levels, got {parts}"

        # Test monthly structure
        manager.configure({'directory_structure': 'monthly', 'base_path': tmpdir})
        manager.start()
        path3 = manager.current_file.parent
        manager.stop()
        print(f"  Monthly: {path3}")
        parts = path3.relative_to(tmpdir).parts
        assert len(parts) == 2, f"Expected 2 levels, got {parts}"

        # Test experiment structure
        manager.configure({
            'directory_structure': 'experiment',
            'experiment_name': 'exp_001',
            'base_path': tmpdir
        })
        manager.start()
        path4 = manager.current_file.parent
        manager.stop()
        print(f"  Experiment: {path4}")
        assert 'exp_001' in str(path4)

        print("  PASSED!")

def test_buffered_writing():
    """Test buffered write mode"""
    print("\n=== Test: Buffered Writing ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        manager = RecordingManager(tmpdir)

        manager.configure({
            'base_path': tmpdir,
            'write_mode': 'buffered',
            'buffer_size': 5,
            'flush_interval_s': 10.0  # Long interval to test buffer-based flush
        })

        manager.start()

        # Write 3 samples (less than buffer size)
        for i in range(3):
            manager.write_sample({'value': i}, {})

        status = manager.get_status()
        print(f"  After 3 samples: buffer_pending={status['recording_buffer_pending']}")
        assert status['recording_buffer_pending'] == 3, "Buffer should have 3 pending"

        # Write 2 more to trigger flush (buffer size = 5)
        for i in range(2):
            manager.write_sample({'value': i + 3}, {})

        status = manager.get_status()
        print(f"  After 5 samples: buffer_pending={status['recording_buffer_pending']}")
        assert status['recording_buffer_pending'] == 0, "Buffer should be flushed"

        manager.stop()

        # Verify all samples were written
        files = manager.list_files()
        with open(files[0]['path'], 'r') as f:
            lines = [l for l in f.readlines() if not l.startswith('#') and l.strip()]
            # First line is header, then 5 data lines
            assert len(lines) == 6, f"Expected 6 lines (1 header + 5 data), got {len(lines)}"

        print("  PASSED!")

def test_rotation_by_samples():
    """Test file rotation based on sample count"""
    print("\n=== Test: Rotation by Sample Count ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        manager = RecordingManager(tmpdir)

        manager.configure({
            'base_path': tmpdir,
            'rotation_mode': 'samples',
            'max_file_samples': 5,
            'on_limit_reached': 'new_file',
            'write_mode': 'immediate'
        })

        manager.start()

        # Write 12 samples (should create 3 files: 5 + 5 + 2)
        for i in range(12):
            manager.write_sample({'value': i}, {})

        status = manager.get_status()
        print(f"  File count: {status['recording_file_count']}")
        print(f"  Current file samples: {status['recording_file_samples']}")

        manager.stop()

        files = manager.list_files()
        print(f"  Total files created: {len(files)}")
        assert len(files) == 3, f"Expected 3 files, got {len(files)}"

        print("  PASSED!")

def test_rotation_stop_mode():
    """Test rotation with stop mode"""
    print("\n=== Test: Rotation with Stop Mode ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        manager = RecordingManager(tmpdir)

        manager.configure({
            'base_path': tmpdir,
            'rotation_mode': 'samples',
            'max_file_samples': 5,
            'on_limit_reached': 'stop',
            'write_mode': 'immediate'
        })

        manager.start()

        # Write 7 samples - should stop after 5
        for i in range(7):
            manager.write_sample({'value': i}, {})
            if not manager.recording:
                break

        status = manager.get_status()
        print(f"  Recording stopped after {status['recording_samples']} samples")
        assert status['recording_samples'] == 5, "Should have stopped at 5 samples"
        assert not manager.recording, "Recording should be stopped"

        print("  PASSED!")

def test_circular_rotation():
    """Test circular file rotation"""
    print("\n=== Test: Circular Rotation ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        manager = RecordingManager(tmpdir)

        manager.configure({
            'base_path': tmpdir,
            'rotation_mode': 'samples',
            'max_file_samples': 3,
            'on_limit_reached': 'circular',
            'circular_max_files': 2,  # Keep only 2 files
            'write_mode': 'immediate'
        })

        manager.start()

        # Write 15 samples (creates 5 files, but should only keep 2)
        for i in range(15):
            manager.write_sample({'value': i}, {})

        manager.stop()

        files = manager.list_files()
        print(f"  Files remaining: {len(files)}")
        for f in files:
            print(f"    - {f['name']}")

        # Should have 2 files (last 2)
        assert len(files) == 2, f"Expected 2 files, got {len(files)}"

        print("  PASSED!")

def test_immediate_vs_buffered_write():
    """Compare immediate vs buffered write performance"""
    print("\n=== Test: Immediate vs Buffered Write Performance ===")

    sample_count = 100

    with tempfile.TemporaryDirectory() as tmpdir:
        # Test immediate mode
        manager = RecordingManager(tmpdir)
        manager.configure({'base_path': tmpdir, 'write_mode': 'immediate', 'file_prefix': 'immediate'})

        manager.start()
        start = time.time()
        for i in range(sample_count):
            manager.write_sample({'value': i, 'data': 'x' * 100}, {})
        manager.stop()
        immediate_time = time.time() - start
        print(f"  Immediate mode: {immediate_time*1000:.1f}ms for {sample_count} samples")

        # Test buffered mode
        manager.configure({
            'base_path': tmpdir,
            'write_mode': 'buffered',
            'buffer_size': 50,
            'file_prefix': 'buffered'
        })

        manager.start()
        start = time.time()
        for i in range(sample_count):
            manager.write_sample({'value': i, 'data': 'x' * 100}, {})
        manager.stop()
        buffered_time = time.time() - start
        print(f"  Buffered mode: {buffered_time*1000:.1f}ms for {sample_count} samples")

        if buffered_time < immediate_time:
            print(f"  Buffered is {immediate_time/buffered_time:.1f}x faster")
        else:
            print("  (Buffered may be slower for small sample counts)")

        print("  PASSED!")

def run_all_tests():
    """Run all tests"""
    print("=" * 50)
    print("Recording Manager Tests")
    print("=" * 50)

    try:
        test_basic_recording()
        test_sample_interval_milliseconds()
        test_naming_patterns()
        test_directory_organization()
        test_buffered_writing()
        test_rotation_by_samples()
        test_rotation_stop_mode()
        test_circular_rotation()
        test_immediate_vs_buffered_write()

        print("\n" + "=" * 50)
        print("ALL TESTS PASSED!")
        print("=" * 50)
        return 0

    except AssertionError as e:
        print(f"\n  FAILED: {e}")
        return 1
    except Exception as e:
        print(f"\n  ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == '__main__':
    sys.exit(run_all_tests())
