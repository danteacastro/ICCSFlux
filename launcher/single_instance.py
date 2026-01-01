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
            lockfile = Path(os.environ.get('TEMP', '.')) / "nisystem_manager.lock"
            try:
                # Try to create lock file exclusively
                self._lockfile_path = lockfile
                if lockfile.exists():
                    # Check if process is still running
                    try:
                        with open(lockfile, 'r') as f:
                            old_pid = int(f.read().strip())
                        # Check if process exists
                        import ctypes
                        kernel32 = ctypes.windll.kernel32
                        handle = kernel32.OpenProcess(0x0001, False, old_pid)
                        if handle:
                            kernel32.CloseHandle(handle)
                            return False  # Process still running
                    except (ValueError, OSError):
                        pass  # Stale lock file

                # Write our PID
                with open(lockfile, 'w') as f:
                    f.write(str(os.getpid()))
                self._acquired = True
                atexit.register(self.release)
                return True
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
