"""
Cross-platform single instance enforcement.
Uses Windows Named Mutex on Windows, file locks on POSIX.
"""

import sys
import os
import atexit
from pathlib import Path

if sys.platform == 'win32':
    try:
        import win32event
        import win32api
        import winerror
        HAS_WIN32 = True
    except ImportError:
        HAS_WIN32 = False

    class SingleInstance:
        """Enforce single instance using Windows Named Mutex"""

        def __init__(self, name: str = "NISystemServiceManager"):
            self.name = f"Global\\{name}_Mutex"
            self.mutex = None
            self._acquired = False

        def acquire(self) -> bool:
            """Try to acquire the mutex. Returns True if this is the primary instance."""
            if not HAS_WIN32:
                # Fall back to file-based lock on Windows without pywin32
                return self._acquire_file_lock()

            try:
                self.mutex = win32event.CreateMutex(None, True, self.name)
                self._acquired = win32api.GetLastError() != winerror.ERROR_ALREADY_EXISTS

                if self._acquired:
                    atexit.register(self.release)
                return self._acquired
            except Exception:
                # Fall back to file-based lock
                return self._acquire_file_lock()

        def _acquire_file_lock(self) -> bool:
            """File-based fallback for Windows without pywin32"""
            # Use service name in lock file path for isolation
            safe_name = self.name.replace("\\", "_").replace("/", "_")
            lockfile = Path(os.environ.get('TEMP', '.')) / f"{safe_name}.lock"
            try:
                # Try to create lock file exclusively
                self._lockfile_path = lockfile
                if lockfile.exists():
                    # Check if process is still running AND is actually our service
                    try:
                        with open(lockfile, 'r') as f:
                            content = f.read().strip()

                        # Parse lock file - format: "PID:service_name"
                        if ':' in content:
                            old_pid, old_name = content.split(':', 1)
                            old_pid = int(old_pid)
                        else:
                            # Legacy format - just PID
                            old_pid = int(content)
                            old_name = None

                        # Verify process is actually our service (not a reused PID)
                        if self._is_our_process(old_pid, old_name):
                            return False  # Our service is actually running
                        # Otherwise, stale lock - continue to acquire
                    except (ValueError, OSError):
                        pass  # Stale/corrupt lock file

                # Write our PID and service name
                with open(lockfile, 'w') as f:
                    f.write(f"{os.getpid()}:{self.name}")
                self._acquired = True
                atexit.register(self.release)
                return True
            except Exception:
                return False

        def _is_our_process(self, pid: int, expected_name: str = None) -> bool:
            """Check if PID is actually running our service (not a reused PID)"""
            try:
                import psutil
                proc = psutil.Process(pid)
                cmdline = ' '.join(proc.cmdline()).lower()
                # Check if it's a Python process running our service
                if 'python' in proc.name().lower():
                    # Check for service-specific identifiers in command line
                    if 'daq_service' in cmdline or 'nisystem' in cmdline:
                        return True
                return False
            except ImportError:
                # psutil not available - fall back to basic check
                pass
            except Exception:
                return False  # Process doesn't exist or can't be accessed

            # Fallback: just check if process exists (less reliable)
            try:
                import ctypes
                kernel32 = ctypes.windll.kernel32
                # PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                handle = kernel32.OpenProcess(0x1000, False, pid)
                if handle:
                    kernel32.CloseHandle(handle)
                    # Process exists but we can't verify it's ours
                    # Be conservative - assume it might be stale after 1 hour
                    if self._lockfile_path and self._lockfile_path.exists():
                        import time
                        age = time.time() - self._lockfile_path.stat().st_mtime
                        if age > 3600:  # Lock file older than 1 hour
                            return False  # Assume stale
                    return True  # Assume running
                return False
            except Exception:
                return False

        def release(self):
            """Release the mutex"""
            if HAS_WIN32 and self.mutex and self._acquired:
                try:
                    win32event.ReleaseMutex(self.mutex)
                    win32api.CloseHandle(self.mutex)
                except Exception:
                    pass
                self.mutex = None
                self._acquired = False
            elif hasattr(self, '_lockfile_path') and self._lockfile_path:
                try:
                    self._lockfile_path.unlink()
                except Exception:
                    pass

        def is_primary(self) -> bool:
            """Check if this is the primary instance"""
            return self._acquired

else:
    # POSIX (Linux/macOS)
    import fcntl

    class SingleInstance:
        """Enforce single instance using file lock on POSIX"""

        def __init__(self, name: str = "nisystem"):
            self.lockfile = Path(f"/tmp/{name}.lock")
            self.fp = None
            self._acquired = False

        def acquire(self) -> bool:
            """Try to acquire the lock. Returns True if this is the primary instance."""
            try:
                self.fp = open(self.lockfile, 'w')
                fcntl.flock(self.fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.fp.write(str(os.getpid()))
                self.fp.flush()
                self._acquired = True
                atexit.register(self.release)
                return True
            except (IOError, OSError):
                if self.fp:
                    self.fp.close()
                return False

        def release(self):
            """Release the file lock"""
            if self.fp:
                try:
                    fcntl.flock(self.fp, fcntl.LOCK_UN)
                    self.fp.close()
                except Exception:
                    pass
                try:
                    self.lockfile.unlink()
                except Exception:
                    pass
                self._acquired = False

        def is_primary(self) -> bool:
            """Check if this is the primary instance"""
            return self._acquired
