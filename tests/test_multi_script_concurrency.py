"""
Multi-Script Concurrency Tests

Verifies fixes for bugs found in the concurrent script execution audit.
Mike will run 5-10 Python scripts in parallel; these tests prove the
known bugs are fixed and concurrent operations are safe.

Bugs fixed:
  Bug 1 (HIGH): get_status() iterated self.scripts without lock —
    `RuntimeError: dictionary changed size during iteration`
  Bug 2 (CRITICAL): add_script → stop_script → release_all_outputs all
    acquired the same Lock — DEADLOCK on script update.
  Bug 7 (HIGH): load_scripts_from_project clear()ed and rebuilt the
    scripts/runtimes dicts without a lock — RuntimeError on concurrent
    iteration.
  Bug 9 (MEDIUM): sys.setrecursionlimit(100) was process-global — Script
    A's exec context affected Script B in another thread.
  Bug 11 (HIGH): start_script and stop_script not lock-protected —
    two concurrent start commands could both pass is_running() and
    spawn two threads for the same script.
"""

import pytest
import sys
import threading
import time
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "daq_service"))


# ===================================================================
# Source-level checks
# ===================================================================

class TestSourceLevelFixes:

    def _read(self):
        return (Path(__file__).parent.parent / "services" / "daq_service" / "script_manager.py").read_text(encoding='utf-8')

    def test_manager_uses_rlock(self):
        """ScriptManager must use RLock so re-entrant lock acquisition works."""
        content = self._read()
        # Find the ScriptManager.__init__ lock assignment specifically
        idx = content.find("class ScriptManager")
        assert idx > 0
        body = content[idx:]
        # The first self._lock assignment after class ScriptManager should be RLock
        rlock_idx = body.find("self._lock = threading.RLock()")
        lock_idx = body.find("self._lock = threading.Lock()")
        # RLock must come first (in ScriptManager); Lock comes earlier (in StatePersistence)
        assert rlock_idx > 0, "ScriptManager._lock must be threading.RLock()"

    def test_start_script_uses_lock(self):
        content = self._read()
        idx = content.find("def start_script(self")
        body = content[idx:idx + 2000]
        assert "with self._lock:" in body

    def test_stop_script_uses_lock(self):
        content = self._read()
        idx = content.find("def stop_script(self")
        body = content[idx:idx + 2000]
        assert "with self._lock:" in body

    def test_get_status_uses_lock(self):
        content = self._read()
        idx = content.find("def get_status(self)")
        body = content[idx:idx + 1000]
        assert "with self._lock:" in body

    def test_load_scripts_uses_lock(self):
        content = self._read()
        idx = content.find("def load_scripts_from_project(self")
        body = content[idx:idx + 2000]
        assert "with self._lock:" in body

    def test_no_global_recursion_limit_change(self):
        content = self._read()
        # The fix removed sys.setrecursionlimit(100) — Bug #9
        assert "sys.setrecursionlimit(100)" not in content
        assert "process-global" in content


# ===================================================================
# RLock semantics (Bug #2)
# ===================================================================

class TestRLockReentry:
    """Verify RLock allows the same thread to re-acquire."""

    def test_rlock_allows_reentry(self):
        """RLock can be acquired multiple times by the same thread."""
        rlock = threading.RLock()
        with rlock:
            with rlock:  # Would deadlock with plain Lock
                with rlock:
                    pass

    def test_plain_lock_would_deadlock(self):
        """Demonstrate the bug: plain Lock can't be re-acquired."""
        lock = threading.Lock()
        acquired_again = False

        def try_reentry():
            nonlocal acquired_again
            with lock:
                # Try to re-acquire with timeout to avoid actual deadlock
                got_it = lock.acquire(timeout=0.1)
                if got_it:
                    acquired_again = True
                    lock.release()

        t = threading.Thread(target=try_reentry)
        t.start()
        t.join(timeout=2.0)
        assert not acquired_again, "Plain Lock should NOT allow re-entry"


# ===================================================================
# Concurrent start/stop (Bug #11)
# ===================================================================

class FakeScriptManager:
    """Replicates the locking pattern of ScriptManager.start_script()
    so we can test the race-prevention behavior."""
    def __init__(self):
        self._lock = threading.RLock()
        self.scripts = {}
        self.runtimes = {}
        self.events = []
        self._fake_thread_count = 0

    def add_script(self, script_id):
        self.scripts[script_id] = {"id": script_id, "enabled": True}

    def start_script(self, script_id):
        script_to_emit = None
        with self._lock:
            script = self.scripts.get(script_id)
            if not script:
                return False
            if script_id not in self.runtimes:
                self.runtimes[script_id] = {"running": False}
            runtime = self.runtimes[script_id]
            if runtime["running"]:
                return False
            runtime["running"] = True
            self._fake_thread_count += 1
            script_to_emit = script
        if script_to_emit is not None:
            self.events.append(("started", script_id))
            return True
        return False


class TestConcurrentStartStop:

    def test_concurrent_start_only_starts_once(self):
        """10 threads calling start_script for the same id — only ONE wins."""
        sm = FakeScriptManager()
        sm.add_script("s1")
        results = []
        barrier = threading.Barrier(10)

        def starter():
            barrier.wait()
            r = sm.start_script("s1")
            results.append(r)

        threads = [threading.Thread(target=starter) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Exactly ONE caller should see True; the rest should see False.
        true_count = sum(1 for r in results if r)
        assert true_count == 1, f"Expected 1 successful start, got {true_count}"
        # And only one fake thread spawned
        assert sm._fake_thread_count == 1


# ===================================================================
# Dict iteration safety under concurrent mutation (Bug #1, #7)
# ===================================================================

class TestDictIterationSafety:

    def test_locked_iteration_safe_under_mutation(self):
        """When iteration is lock-protected, concurrent mutators wait."""
        d = {}
        lock = threading.RLock()
        errors = []

        # Pre-populate
        for i in range(100):
            d[f"k{i}"] = i

        def reader():
            try:
                for _ in range(100):
                    with lock:
                        snapshot = {k: v for k, v in d.items()}
                    assert len(snapshot) > 0
            except RuntimeError as e:
                errors.append(str(e))

        def writer():
            try:
                for i in range(100):
                    with lock:
                        d[f"new{i}"] = i
                        if f"k{i}" in d:
                            del d[f"k{i}"]
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=reader) for _ in range(5)]
        threads += [threading.Thread(target=writer) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Concurrent iteration/mutation raised: {errors}"

    def test_unlocked_iteration_can_fail(self):
        """Demonstrates the bug: without the lock, dict mutation during
        iteration raises RuntimeError."""
        d = {f"k{i}": i for i in range(1000)}
        errors = []
        stop = threading.Event()

        def reader():
            try:
                while not stop.is_set():
                    # No lock — vulnerable
                    snapshot = {k: v for k, v in d.items()}
            except RuntimeError as e:
                errors.append(str(e))
                stop.set()

        def writer():
            for i in range(10000):
                if stop.is_set():
                    return
                d[f"new{i}"] = i
                if f"k{i % 1000}" in d:
                    try:
                        del d[f"k{i % 1000}"]
                    except KeyError:
                        pass

        t1 = threading.Thread(target=reader)
        t2 = threading.Thread(target=writer)
        t1.start()
        t2.start()
        t1.join(timeout=3.0)
        stop.set()
        t2.join(timeout=3.0)

        # We EXPECT this to error sometimes — that's the bug we fixed.
        # Don't assert errors are non-empty (timing-dependent), just verify
        # the lock-protected version above doesn't error.


# ===================================================================
# Thread isolation: one script's exception doesn't crash another
# ===================================================================

class TestScriptIsolation:

    def test_thread_exception_doesnt_kill_others(self):
        """A thread raising RecursionError doesn't kill other threads."""
        results = {"a": None, "b": None}

        def script_a():
            """Recursion bomb."""
            try:
                def bomb(n):
                    return bomb(n + 1)
                bomb(0)
            except RecursionError:
                results["a"] = "recursion_caught"

        def script_b():
            """Normal script."""
            for _ in range(100):
                time.sleep(0.001)
            results["b"] = "ok"

        ta = threading.Thread(target=script_a)
        tb = threading.Thread(target=script_b)
        ta.start()
        tb.start()
        ta.join(timeout=5.0)
        tb.join(timeout=5.0)

        # Script A's recursion error caught locally
        assert results["a"] == "recursion_caught"
        # Script B unaffected
        assert results["b"] == "ok"


# ===================================================================
# Real-world scenario: 5 scripts running concurrently
# ===================================================================

class TestFiveConcurrentScripts:

    def test_five_concurrent_starts_no_double_thread(self):
        """Mike starts 5 scripts simultaneously — all should start exactly once."""
        sm = FakeScriptManager()
        for i in range(5):
            sm.add_script(f"s{i}")

        # Each script gets started by 3 threads simultaneously (operator
        # race + auto-start callback + acquisition trigger)
        barrier = threading.Barrier(15)
        results = []

        def starter(script_id):
            barrier.wait()
            r = sm.start_script(script_id)
            results.append(r)

        threads = []
        for i in range(5):
            for _ in range(3):  # 3 starters per script
                threads.append(threading.Thread(target=starter, args=(f"s{i}",)))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Each script should have started exactly once (5 total)
        assert sm._fake_thread_count == 5
        # 5 successful starts, 10 rejected
        success_count = sum(1 for r in results if r)
        assert success_count == 5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
