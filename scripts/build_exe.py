"""
Build ICCSFlux as compiled Windows executables using PyInstaller.

This creates a self-contained folder with native .exe files that can run
on any Windows PC without installing Python, Node.js, or Mosquitto system-wide.

Usage:
    python build_exe.py               # Build with PyInstaller compilation
    python build_exe.py --quick       # Skip recompilation if .exe exists
    python build_exe.py --sign        # Sign executables after build
    python build_exe.py --no-sbom     # Skip SBOM/vulnerability audit

Output: dist/ICCSFlux-Portable/

Build artifacts include:
- VERSION.txt               Git commit hash, branch, build timestamp
- SHA256SUMS.txt            SHA-256 hashes of all executables
- SOURCE_MANIFEST.json      SHA-256 hashes of all source files (for build diffs)
- sbom.json                 CycloneDX Software Bill of Materials
- vulnerability-audit.json  pip-audit vulnerability scan results
- requirements-lock.txt     Pinned dependency versions

Requirements:
- Python 3.8+ with PyInstaller installed
- Node.js + npm (to build the dashboard)
- All Python dependencies installed (for PyInstaller to bundle)

Optional (for code signing):
- Windows SDK (signtool.exe)
- Code signing certificate (.pfx file)
- Set env vars: CODE_SIGN_PFX=path/to/cert.pfx CODE_SIGN_PASSWORD=password
"""

import os
import sys
import hashlib
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
import argparse

# Paths
PROJECT_ROOT = Path(__file__).parent.parent
BUILD_DIR = PROJECT_ROOT / "dist" / "ICCSFlux-Portable"
EXE_DIR = PROJECT_ROOT / "dist" / "exe"
VENDOR_DIR = PROJECT_ROOT / "vendor"
SPEC_DIR = PROJECT_ROOT / "scripts"
AZURE_VENV_DIR = PROJECT_ROOT / "build" / "azure-venv"
SYSTEM_MOSQUITTO_DIR = Path("C:/Program Files/mosquitto")

# DLLs mosquitto.exe (2.x) requires at startup. Missing any one makes the broker
# die immediately with a "<dll> was not found" dialog, which cascades into the
# DAQ service failing to reach the MQTT broker. Verified after the copy so a
# stale/incomplete vendor folder can never silently ship a broken broker.
REQUIRED_MOSQUITTO_DLLS = [
    "mosquitto.dll",
    "libcrypto-3-x64.dll",
    "libssl-3-x64.dll",
    "cjson.dll",
    "libmicrohttpd-dll.dll",
    "pthreadVC3.dll",
]

# Spec files for PyInstaller (built from main venv)
SPEC_FILES = {
    "DAQService": SPEC_DIR / "daq_service.spec",
    "ICCSFlux": SPEC_DIR / "iccsflux.spec",
}

# Exes built as ONEDIR (exe + _internal folder) rather than onefile. ICCSFlux is
# the windowed launcher: onefile self-extracts to _runtime\_MEI#### each launch
# and pops a "Failed to remove temporary directory" warning when exit-cleanup is
# blocked. Onedir avoids the extraction entirely. Its output is a folder
# (EXE_DIR/<name>/), handled specially in copy_executables().
ONEDIR_EXES = {"ICCSFlux"}

# Standalone tool specs (built from main venv, deployed to tools/ subfolder)
TOOL_SPEC_FILES = {
    "ModbusTool": SPEC_DIR / "modbus_tool.spec",
}

# Azure spec (built from isolated venv with paho-mqtt 1.x)
AZURE_SPEC = ("AzureUploader", SPEC_DIR / "azure_uploader.spec")

def log(msg, level="INFO"):
    prefix = {"INFO": "[BUILD]", "WARN": "[WARN]", "ERROR": "[ERROR]", "OK": "[  OK ]"}
    print(f"{prefix.get(level, '[    ]')} {msg}")

def _rm_onerror(func, path, _exc):
    """rmtree error handler: clear the read-only bit and retry once.

    Building into a OneDrive-synced tree leaves files marked read-only or as
    cloud placeholders, so the next build's rmtree hits WinError 5 on them.
    Clearing the attribute and retrying clears the common case; a genuine
    open-handle lock still raises, which the caller can catch.
    """
    import stat
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        raise

def robust_rmtree(path):
    """shutil.rmtree that recovers from read-only files (Windows/OneDrive)."""
    # Python 3.12 renamed the keyword onerror -> onexc; support both.
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=lambda func, p, exc: _rm_onerror(func, p, exc))
    else:
        shutil.rmtree(path, onerror=lambda func, p, exc: _rm_onerror(func, p, exc))

# Executables that, when running, hold open files inside the build tree (the
# Mosquitto broker in particular keeps config\mosquitto_passwd open because
# config/mosquitto.conf sets `password_file config/mosquitto_passwd`).
_BUILD_LOCKING_EXES = [
    "mosquitto.exe", "ICCSFlux.exe", "DAQService.exe",
    "AzureUploader.exe", "ModbusTool.exe",
]

def _clear_readonly(p):
    """Clear the read-only attribute so a file/dir can be deleted. Windows refuses
    to delete read-only files AND refuses to rmdir read-only DIRECTORIES."""
    import stat
    try:
        os.chmod(p, stat.S_IWRITE)
    except OSError:
        pass

def _grant_full_control(p):
    """Rewrite a file/dir ACL to grant the current user full control.

    Used when a delete hits 'Access is denied' (WinError 5) NOT because of a lock
    or the read-only bit, but because the object has a restrictive ACL with no
    Delete right. config\\mosquitto_passwd is created exactly this way: Mosquitto
    writes it with an owner-only Read/Write ACL (no Delete) and inheritance broken,
    so os.unlink() can't remove it. As the OWNER we always hold WRITE_DAC, so this
    grant succeeds and the subsequent delete works.
    """
    import getpass
    try:
        subprocess.run(["icacls", str(p), "/grant", f"{getpass.getuser()}:F", "/Q"],
                       capture_output=True, timeout=15)
    except Exception:
        pass

def _try_remove(p, remove):
    """Remove p via `remove` (unlink or rmdir), clearing the read-only bit first
    and — on Access Denied — granting the current user rights and retrying.
    Returns True if the object is gone."""
    try:
        _clear_readonly(p)
        remove(p)
        return True
    except OSError:
        pass
    # Fall back to fixing the ACL (delete-less/restrictive) then retry.
    _grant_full_control(p)
    try:
        remove(p)
        return True
    except OSError:
        return False

def _remove_tree_pass(path):
    """One bottom-up delete pass. Returns the paths that could NOT be removed."""
    failed = []
    # Bottom-up so files go before the dirs that contain them.
    for root, dirs, files in os.walk(path, topdown=False):
        for name in files:
            p = Path(root) / name
            if not _try_remove(p, lambda x: x.unlink()):
                failed.append(p)
        for name in dirs:
            p = Path(root) / name
            if not _try_remove(p, lambda x: x.rmdir()):  # succeeds only if now empty
                failed.append(p)
    if not _try_remove(path, lambda x: x.rmdir()):
        if path.exists():
            failed.append(path)
    return failed

def remove_tree_best_effort(path, attempts=6, delay=0.3):
    """Delete as much of `path` as possible, clearing read-only bits along the way.

    Returns the list of paths that could NOT be removed after `attempts` passes.
    Unlike rmtree, one stubborn file doesn't abort the whole delete. Retries with an
    ESCALATING backoff because most build-tree "locks" on Windows are TRANSIENT — a
    real-time antivirus scan (Defender) or a file-watcher grabbing a file for a
    split second right as we delete it, and a delete attempt can itself re-trigger
    the scan. Growing the wait (0.3s, 0.6s, 0.9s, …) gives the scanner time to fully
    release before the next pass. A clean tree returns on pass 1 with no delay, so
    the extra time is only spent when something is actually contended.
    """
    import time
    if not path.exists():
        return []
    failed = []
    for attempt in range(attempts):
        failed = _remove_tree_pass(path)
        if not failed or not path.exists():
            return failed
        if attempt < attempts - 1:
            time.sleep(delay * (attempt + 1))  # 0.3, 0.6, 0.9, 1.2, 1.5 → ~4.5s max
    return failed

def _running_build_lockers():
    """Return the subset of _BUILD_LOCKING_EXES currently running (best effort)."""
    try:
        out = subprocess.run(["tasklist"], capture_output=True, text=True).stdout.lower()
    except Exception:
        return []
    return [name for name in _BUILD_LOCKING_EXES if name.lower() in out]

def _processes_locking(paths):
    """Ask Windows which processes hold a handle on any of ``paths``.

    Uses the Restart Manager API (rstrtmgr.dll): register the files as resources,
    then RmGetList returns every process with an open handle to them. This is the
    same mechanism the Windows installer uses for "the following apps are using
    this file" — so it names the ACTUAL locker (image name + PID) instead of us
    guessing from a hardcoded process list.

    Returns a list of "name.exe (PID n)" strings, or [] on any failure / non-
    Windows. Best-effort diagnostics only: never raises.
    """
    if sys.platform != "win32":
        return []
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return []

    # Only real, existing files can be registered. Directories aren't valid RM
    # resources; register the files inside them so the handle-holder still shows.
    files = []
    for p in paths:
        try:
            if p.is_file():
                files.append(str(p))
            elif p.is_dir():
                for sub in p.rglob("*"):
                    if sub.is_file():
                        files.append(str(sub))
                        if len(files) >= 64:  # cap: enough to find the culprit
                            break
        except OSError:
            continue
    if not files:
        return []

    RM_SESSION_KEY_LEN = 32  # sizeof(GUID) as hex chars
    CCH_RM_SESSION_KEY = RM_SESSION_KEY_LEN * 2

    class RM_UNIQUE_PROCESS(ctypes.Structure):
        _fields_ = [("dwProcessId", wintypes.DWORD),
                    ("ProcessStartTime", wintypes.FILETIME)]

    RM_APP_TYPE = ctypes.c_int
    CCH_RM_MAX_APP_NAME = 255
    CCH_RM_MAX_SVC_NAME = 63

    class RM_PROCESS_INFO(ctypes.Structure):
        _fields_ = [
            ("Process", RM_UNIQUE_PROCESS),
            ("strAppName", wintypes.WCHAR * (CCH_RM_MAX_APP_NAME + 1)),
            ("strServiceShortName", wintypes.WCHAR * (CCH_RM_MAX_SVC_NAME + 1)),
            ("ApplicationType", RM_APP_TYPE),
            ("AppStatus", wintypes.ULONG),
            ("TSSessionId", wintypes.DWORD),
            ("bRestartable", wintypes.BOOL),
        ]

    try:
        rm = ctypes.WinDLL("rstrtmgr")
    except Exception:
        return []

    session = wintypes.DWORD(0)
    key = ctypes.create_unicode_buffer(CCH_RM_SESSION_KEY + 1)
    if rm.RmStartSession(ctypes.byref(session), 0, key) != 0:
        return []
    try:
        arr = (ctypes.c_wchar_p * len(files))(*files)
        if rm.RmRegisterResources(session, len(files), arr,
                                  0, None, 0, None) != 0:
            return []
        results = []
        # RmGetList: call once to learn the count, then again with a buffer.
        n_needed = wintypes.UINT(0)
        n_have = wintypes.UINT(0)
        reason = wintypes.DWORD(0)
        ERROR_MORE_DATA = 234
        rc = rm.RmGetList(session, ctypes.byref(n_needed), ctypes.byref(n_have),
                          None, ctypes.byref(reason))
        if rc not in (0, ERROR_MORE_DATA) or n_needed.value == 0:
            return []
        count = n_needed.value
        infos = (RM_PROCESS_INFO * count)()
        n_have = wintypes.UINT(count)
        rc = rm.RmGetList(session, ctypes.byref(n_needed), ctypes.byref(n_have),
                          infos, ctypes.byref(reason))
        if rc != 0:
            return []
        seen = set()
        for i in range(n_have.value):
            pi = infos[i]
            pid = pi.Process.dwProcessId
            name = pi.strAppName or "unknown"
            tag = f"{name} (PID {pid})"
            if tag not in seen:
                seen.add(tag)
                results.append(tag)
        return results
    finally:
        try:
            rm.RmEndSession(session)
        except Exception:
            pass

def _warn_locked_files(failed):
    """Explain WHY items in the build tree are locked and how to get a clean wipe."""
    shown = ", ".join(p.name for p in failed[:4])
    log(f"Could not remove {len(failed)} item(s) still in use: {shown}", "WARN")

    # Ask the OS who actually holds the handle — real evidence, not a guess.
    holders = _processes_locking(failed)
    if holders:
        log("Locked by (Restart Manager): " + ", ".join(holders), "WARN")
        log("Close the process(es) above (or exclude dist\\ from AV) and rebuild "
            "for a fully-clean wipe. The build continues by overlaying fresh files.", "WARN")
        return

    running = _running_build_lockers()
    if running:
        log("Held open by running process(es): " + ", ".join(running), "WARN")
        if "mosquitto.exe" in running:
            log("A running Mosquitto broker keeps config\\mosquitto_passwd open "
                "(config/mosquitto.conf sets `password_file config/mosquitto_passwd`).", "WARN")
        log("The build continues by overlaying fresh files. For a fully-clean wipe, "
            "stop them first — e.g.  net stop mosquitto  (this is NOT a OneDrive issue).", "WARN")
    else:
        # No ICCSFlux/broker process, and we already retried several times — so a
        # handle is being held by something else. On Windows the usual culprits are
        # a real-time AV scan, a file-watcher, an open Explorer window, or a terminal
        # whose current directory is inside the build tree.
        log("No ICCSFlux/Mosquitto process is running and the delete was already "
            "retried — so something else briefly held these. Usual causes: antivirus "
            "(Defender) scanning files as they're deleted, VSCode's file watcher, an "
            "open File Explorer window, or a terminal sitting in dist\\ICCSFlux-Portable "
            "(e.g. config\\). Add an AV exclusion for dist\\ or close the window/terminal, "
            "then rebuild for a fully clean output.", "WARN")
        log("Administrator does NOT help here — this is a file-in-use lock, not a "
            "permissions problem. The build continues by overlaying fresh files.", "WARN")

def _is_admin():
    """True if the current process has Administrator rights."""
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False

def _service_running(service_name):
    """True if a Windows service by this name exists and is RUNNING."""
    try:
        out = subprocess.run(["sc", "query", service_name],
                             capture_output=True, text=True)
        return out.returncode == 0 and "RUNNING" in out.stdout.upper()
    except Exception:
        return False

def stop_conflicting_broker():
    """Stop any Mosquitto broker that is already running.

    Two reasons this matters:
      1. A broker launched from the dist folder holds config\\mosquitto_passwd
         open, which blocks a clean wipe of the build tree.
      2. More importantly, when you RUN the freshly-built portable, its Service
         Manager tries to start its OWN broker on port 1883. If a system-wide
         Mosquitto service is already on that port, the portable attaches to it
         as 'ext' — with the wrong config/credentials — and the dashboard can't
         authenticate ("Connection Lost").

    So we proactively stop the service and any stray process. Requires
    Administrator to touch a Windows service; degrades to a clear message.
    """
    svc_running = _service_running("mosquitto")
    proc_running = "mosquitto.exe" in _running_build_lockers()
    if not svc_running and not proc_running:
        # Nothing to stop — a plain build needs no elevation.
        log("No conflicting Mosquitto broker running (no admin needed).", "OK")
        return True

    # A broker IS running and must be stopped — which needs Administrator. Rather
    # than half-build and fail at runtime, stop now with a clear message.
    if not _is_admin():
        log("A Mosquitto broker is already running and must be stopped before "
            "building.", "ERROR")
        log("Otherwise the portable attaches to this external broker with the "
            "wrong config and the dashboard shows 'Connection Lost'.", "ERROR")
        log("Stopping it requires Administrator.", "ERROR")
        log(">> Re-run build.bat from an elevated terminal (Run as administrator),", "ERROR")
        log("   or pass  --keep-broker  to build without touching the broker.", "ERROR")
        return False

    log("A Mosquitto broker is already running — stopping it so the portable "
        "build can own port 1883 (not attach to this external broker)...", "WARN")
    ok = True

    # 1) Stop the Windows service (the usual culprit: the system installer's
    #    'mosquitto' service). Needs Administrator.
    if svc_running:
        res = subprocess.run(["net", "stop", "mosquitto"],
                             capture_output=True, text=True)
        if res.returncode == 0 and not _service_running("mosquitto"):
            log("  Stopped Windows service 'mosquitto'.", "OK")
            # Prevent it auto-returning on the next boot and re-conflicting. This is
            # safe: the portable ships its own broker, and dev's start_services.py
            # launches mosquitto.exe as a plain process (not via this service).
            cfg = subprocess.run(["sc", "config", "mosquitto", "start=", "disabled"],
                                 capture_output=True, text=True)
            if cfg.returncode == 0:
                log("  Disabled 'mosquitto' service auto-start (won't return on boot). "
                    "Re-enable any time with:  sc config mosquitto start= auto", "OK")
            else:
                log("  Stopped it, but could not disable auto-start (it may return on "
                    "reboot). Run as admin:  sc config mosquitto start= disabled", "WARN")
        else:
            ok = False
            blob = (res.stdout + res.stderr).lower()
            if "access is denied" in blob or res.returncode == 2:
                log("  Cannot stop the 'mosquitto' service — needs Administrator.", "ERROR")
                log("  Re-run build.bat as Administrator, or manually run:  net stop mosquitto", "ERROR")
            else:
                log(f"  Failed to stop 'mosquitto' service: "
                    f"{(res.stdout or res.stderr).strip()}", "ERROR")

    # 2) Kill any stray (non-service) mosquitto.exe still holding the port.
    if "mosquitto.exe" in _running_build_lockers():
        subprocess.run(["taskkill", "/F", "/IM", "mosquitto.exe"],
                       capture_output=True, text=True)
        if "mosquitto.exe" in _running_build_lockers():
            ok = False
            log("  A mosquitto.exe is still running (likely a SYSTEM service — "
                "needs Administrator to stop).", "WARN")
        else:
            log("  Stopped stray mosquitto.exe process(es).", "OK")

    if ok:
        log("Mosquitto broker stopped — port 1883 is free for the portable build.", "OK")
    else:
        log("A Mosquitto broker is STILL running. The portable will attach to it as "
            "external and may fail to authenticate. Stop it as Administrator "
            "(net stop mosquitto) before running the distro.", "WARN")
    return ok

def get_build_version() -> dict:
    """Capture build version info from git and system metadata."""
    version = {
        "build_time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "git_hash": "unknown",
        "git_hash_short": "unknown",
        "git_dirty": False,
        "git_branch": "unknown",
        "git_tag": None,
    }

    try:
        # Short and full hash
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, cwd=PROJECT_ROOT,
        )
        if result.returncode == 0:
            version["git_hash"] = result.stdout.strip()
            version["git_hash_short"] = version["git_hash"][:8]

        # Branch name
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, cwd=PROJECT_ROOT,
        )
        if result.returncode == 0:
            version["git_branch"] = result.stdout.strip()

        # Dirty working tree?
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, cwd=PROJECT_ROOT,
        )
        if result.returncode == 0:
            version["git_dirty"] = bool(result.stdout.strip())

        # Latest tag (if any)
        result = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0"],
            capture_output=True, text=True, cwd=PROJECT_ROOT,
        )
        if result.returncode == 0 and result.stdout.strip():
            version["git_tag"] = result.stdout.strip()

    except FileNotFoundError:
        log("git not found — version info will be incomplete", "WARN")

    return version

def setup_reproducible_env():
    """Set environment variables for reproducible (deterministic) builds.

    PYTHONHASHSEED=1 fixes Python's dict/set ordering randomization.
    SOURCE_DATE_EPOCH fixes PE header timestamps to the git commit time.

    Without these, every build produces a different SHA-256 hash even
    when the source code is identical.  See docs/IT_Security_and_Compliance_Guide.md.
    """
    os.environ["PYTHONHASHSEED"] = "1"

    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%ct"],
            capture_output=True, text=True, cwd=PROJECT_ROOT,
        )
        if result.returncode == 0 and result.stdout.strip():
            os.environ["SOURCE_DATE_EPOCH"] = result.stdout.strip()
            log(f"Reproducible build: PYTHONHASHSEED=1, SOURCE_DATE_EPOCH={result.stdout.strip()}")
        else:
            os.environ["SOURCE_DATE_EPOCH"] = "0"
            log("Reproducible build: PYTHONHASHSEED=1 (git timestamp unavailable)", "WARN")
    except FileNotFoundError:
        os.environ["SOURCE_DATE_EPOCH"] = "0"
        log("Reproducible build: PYTHONHASHSEED=1 (git not found)", "WARN")

def write_version_file(version: dict):
    """Write VERSION.txt to the build output directory."""
    tag_line = version["git_tag"] or "none"
    dirty = " (uncommitted changes)" if version["git_dirty"] else ""
    lines = [
        f"ICCSFlux Portable Build",
        f"=======================",
        f"Build time:  {version['build_time']}",
        f"Git commit:  {version['git_hash_short']}{dirty}",
        f"Full hash:   {version['git_hash']}",
        f"Branch:      {version['git_branch']}",
        f"Tag:         {tag_line}",
    ]
    version_path = BUILD_DIR / "VERSION.txt"
    version_path.write_text("\n".join(lines) + "\n")
    log(f"Version file written ({version['git_hash_short']}{dirty})", "OK")

def check_prerequisites():
    """Check that required tools are available."""
    log("Checking prerequisites...")

    # Check npm (use shell=True on Windows for proper PATH resolution)
    try:
        result = subprocess.run(
            "npm --version",
            capture_output=True,
            text=True,
            shell=True
        )
        if result.returncode == 0:
            log(f"  npm: v{result.stdout.strip()}")
        else:
            log("npm not found. Install Node.js to build the dashboard.", "ERROR")
            return False
    except Exception as e:
        log(f"npm check failed: {e}", "ERROR")
        return False

    # Check PyInstaller
    try:
        import PyInstaller
        log(f"  PyInstaller: v{PyInstaller.__version__}")
    except ImportError:
        log("PyInstaller not found. Install with: pip install pyinstaller", "ERROR")
        return False

    return True

def clean_build():
    """Clean previous build artifacts."""
    log("Cleaning previous build...")

    if BUILD_DIR.exists():
        # Best-effort recursive delete: a single locked file (typically a
        # runtime-generated mosquitto_passwd held open by a running broker) no
        # longer aborts the clean — everything else is still removed, and the
        # later copy_* steps overlay fresh files on top of whatever remained.
        failed = remove_tree_best_effort(BUILD_DIR)
        if failed:
            _warn_locked_files(failed)
    BUILD_DIR.mkdir(parents=True, exist_ok=True)

def build_dashboard():
    """Build the Vue dashboard."""
    log("Building Vue dashboard...")

    dashboard_dir = PROJECT_ROOT / "dashboard"
    if not dashboard_dir.exists():
        log("Dashboard directory not found", "ERROR")
        return False

    # Check if already built
    dist_index = dashboard_dir / "dist" / "index.html"

    # Temporarily remove .env.local to prevent dev credentials from being
    # baked into the portable build (credentials are generated at runtime)
    env_local = dashboard_dir / ".env.local"
    env_local_backup = dashboard_dir / ".env.local.build-backup"
    if env_local.exists():
        log("  Temporarily removing .env.local (credentials are runtime-generated)")
        env_local.rename(env_local_backup)

    log("Running npm build...")
    try:
        subprocess.run(
            "npm run build",
            cwd=dashboard_dir,
            check=True,
            capture_output=True,
            shell=True
        )
    except subprocess.CalledProcessError as e:
        log(f"Dashboard build failed: {e.stderr.decode() if e.stderr else e}", "ERROR")
        return False
    finally:
        # Restore .env.local if it was backed up
        if env_local_backup.exists():
            env_local_backup.rename(env_local)

    log("Dashboard built successfully", "OK")
    return True

def compile_executables(quick_mode=False):
    """Compile Python services to executables using PyInstaller."""
    log("Compiling executables with PyInstaller...")

    # Create exe output directory
    EXE_DIR.mkdir(parents=True, exist_ok=True)

    for name, spec_file in SPEC_FILES.items():
        exe_path = EXE_DIR / f"{name}.exe"

        if quick_mode and exe_path.exists():
            log(f"  {name}.exe exists, skipping (--quick mode)")
            continue

        if not spec_file.exists():
            log(f"Spec file not found: {spec_file}", "ERROR")
            return False

        log(f"  Compiling {name}...")
        try:
            subprocess.run(
                [
                    sys.executable, "-m", "PyInstaller",
                    str(spec_file),
                    "--distpath", str(EXE_DIR),
                    "--workpath", str(PROJECT_ROOT / "build" / "pyinstaller"),
                    "--noconfirm",
                ],
                cwd=PROJECT_ROOT,
                check=True,
                capture_output=True,
            )
            log(f"  {name}.exe compiled successfully")
        except subprocess.CalledProcessError as e:
            log(f"Failed to compile {name}: {e.stderr.decode() if e.stderr else e}", "ERROR")
            return False

    log("All executables compiled", "OK")
    return True

def compile_tools(quick_mode=False):
    """Compile standalone tool executables using PyInstaller."""
    if not TOOL_SPEC_FILES:
        return True

    log("Compiling standalone tools...")

    EXE_DIR.mkdir(parents=True, exist_ok=True)

    for name, spec_file in TOOL_SPEC_FILES.items():
        exe_path = EXE_DIR / f"{name}.exe"

        if quick_mode and exe_path.exists():
            log(f"  {name}.exe exists, skipping (--quick mode)")
            continue

        if not spec_file.exists():
            log(f"Tool spec file not found: {spec_file}", "WARN")
            continue

        log(f"  Compiling {name}...")
        try:
            subprocess.run(
                [
                    sys.executable, "-m", "PyInstaller",
                    str(spec_file),
                    "--distpath", str(EXE_DIR),
                    "--workpath", str(PROJECT_ROOT / "build" / "pyinstaller"),
                    "--noconfirm",
                ],
                cwd=PROJECT_ROOT,
                check=True,
                capture_output=True,
            )
            log(f"  {name}.exe compiled successfully")
        except subprocess.CalledProcessError as e:
            log(f"Failed to compile {name}: {e.stderr.decode() if e.stderr else e}", "WARN")

    log("Standalone tools compiled", "OK")
    return True

def copy_tools():
    """Copy compiled tool executables to build directory tools/ subfolder."""
    if not TOOL_SPEC_FILES:
        return True

    log("Copying standalone tools...")

    tools_dest = BUILD_DIR / "tools"
    tools_dest.mkdir(exist_ok=True)

    for name in TOOL_SPEC_FILES.keys():
        exe_src = EXE_DIR / f"{name}.exe"
        if exe_src.exists():
            shutil.copy2(exe_src, tools_dest / f"{name}.exe")
            log(f"  Copied {name}.exe -> tools/")
        else:
            log(f"  {name}.exe not found (tool will be unavailable)", "WARN")

    log("Standalone tools copied", "OK")
    return True

def create_azure_venv():
    """Create an isolated venv with paho-mqtt 1.x + azure-iot-device for AzureUploader build.

    The Azure IoT SDK requires paho-mqtt<2, which conflicts with the main project's
    paho-mqtt>=2.0.0.  We solve this by building AzureUploader.exe in its own venv.
    """
    log("Creating isolated Azure build environment...")

    azure_packages_dir = VENDOR_DIR / "azure-packages"
    has_vendor_packages = azure_packages_dir.exists() and any(azure_packages_dir.glob("*.whl"))

    # Create venv
    AZURE_VENV_DIR.parent.mkdir(parents=True, exist_ok=True)
    if AZURE_VENV_DIR.exists():
        log("  Removing previous Azure venv...")
        shutil.rmtree(AZURE_VENV_DIR, ignore_errors=True)

    log("  Creating venv...")
    try:
        subprocess.run(
            [sys.executable, "-m", "venv", str(AZURE_VENV_DIR)],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        log(f"Failed to create Azure venv: {e.stderr.decode() if e.stderr else e}", "ERROR")
        return None

    # Determine pip and python paths in the venv
    venv_python = AZURE_VENV_DIR / "Scripts" / "python.exe"
    if not venv_python.exists():
        # Linux/macOS fallback
        venv_python = AZURE_VENV_DIR / "bin" / "python"

    if not venv_python.exists():
        log(f"Venv python not found at {venv_python}", "ERROR")
        return None

    # Install PyInstaller
    log("  Installing PyInstaller in Azure venv...")
    try:
        subprocess.run(
            [str(venv_python), "-m", "pip", "install", "pyinstaller>=6.0.0", "--quiet"],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        log(f"Failed to install PyInstaller: {e.stderr.decode() if e.stderr else e}", "ERROR")
        return None

    # Install Azure packages from vendor wheels (no internet required)
    log("  Installing azure-iot-device + paho-mqtt 1.x...")
    pip_args = [
        str(venv_python), "-m", "pip", "install",
        "paho-mqtt>=1.6.0,<2.0.0",
        "azure-iot-device>=2.12.0",
        "--quiet",
    ]
    if has_vendor_packages:
        pip_args.extend(["--find-links", str(azure_packages_dir), "--no-index"])

    try:
        subprocess.run(pip_args, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        log(f"Failed to install Azure packages: {e.stderr.decode() if e.stderr else e}", "ERROR")
        return None

    log("  Azure build environment ready", "OK")
    return venv_python

def compile_azure_exe(venv_python, quick_mode=False):
    """Compile AzureUploader.exe using the isolated Azure venv."""
    name, spec_file = AZURE_SPEC
    exe_path = EXE_DIR / f"{name}.exe"

    if quick_mode and exe_path.exists():
        log(f"  {name}.exe exists, skipping (--quick mode)")
        return True

    if not spec_file.exists():
        log(f"Spec file not found: {spec_file}", "ERROR")
        return False

    log(f"  Compiling {name} (isolated Azure venv)...")
    try:
        subprocess.run(
            [
                str(venv_python), "-m", "PyInstaller",
                str(spec_file),
                "--distpath", str(EXE_DIR),
                "--workpath", str(PROJECT_ROOT / "build" / "pyinstaller"),
                "--noconfirm",
            ],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
        )
        log(f"  {name}.exe compiled successfully")
        return True
    except subprocess.CalledProcessError as e:
        log(f"Failed to compile {name}: {e.stderr.decode() if e.stderr else e}", "ERROR")
        return False

def setup_mosquitto():
    """Copy Mosquitto MQTT broker from vendor directory."""
    log("Setting up Mosquitto MQTT broker...")

    mosquitto_vendor = VENDOR_DIR / "mosquitto"
    if not mosquitto_vendor.exists():
        log("Mosquitto not found in vendor/. Download it first.", "ERROR")
        return False

    mosquitto_dest = BUILD_DIR / "mosquitto"
    mosquitto_dest.mkdir(exist_ok=True)

    # Copy mosquitto executable only (config comes from config/ directory)
    src = mosquitto_vendor / "mosquitto.exe"
    if src.exists():
        shutil.copy2(src, mosquitto_dest / "mosquitto.exe")

    # Copy required DLLs
    for dll in mosquitto_vendor.glob("*.dll"):
        shutil.copy2(dll, mosquitto_dest / dll.name)

    # Self-heal: if the vendor folder is stale/incomplete (e.g. populated before
    # Mosquitto gained the cjson/libmicrohttpd/pthread DLLs), top up any missing
    # critical DLL from the system install so the build never ships a broker that
    # dies with "<dll> was not found".
    missing = [d for d in REQUIRED_MOSQUITTO_DLLS
               if not (mosquitto_dest / d).exists()]
    if missing and SYSTEM_MOSQUITTO_DIR.exists():
        for src in [*SYSTEM_MOSQUITTO_DIR.glob("*.exe"),
                    *SYSTEM_MOSQUITTO_DIR.glob("*.dll")]:
            dst = mosquitto_dest / src.name
            if not dst.exists():
                shutil.copy2(src, dst)
                log(f"  Topped up missing Mosquitto file from system: {src.name}")
        missing = [d for d in REQUIRED_MOSQUITTO_DLLS
                   if not (mosquitto_dest / d).exists()]

    if missing:
        log(f"Mosquitto bundle is missing required DLLs: {', '.join(missing)}", "ERROR")
        log("The portable broker would fail to start. Re-run:", "ERROR")
        log("  python scripts\\download_dependencies.py", "ERROR")
        log("with Mosquitto 2.x installed at C:\\Program Files\\mosquitto", "ERROR")
        return False

    log("Mosquitto ready", "OK")
    return True

def setup_nssm():
    """Copy NSSM service manager from vendor directory."""
    log("Setting up NSSM service manager...")

    nssm_vendor = VENDOR_DIR / "nssm"
    if not nssm_vendor.exists():
        log("NSSM not found in vendor/", "WARN")
        return True  # Not critical

    nssm_dest = BUILD_DIR / "nssm"
    nssm_dest.mkdir(exist_ok=True)

    # Try multiple possible locations for nssm.exe
    nssm_locations = [
        nssm_vendor / "nssm.exe",           # Direct in vendor/nssm/
        nssm_vendor / "win64" / "nssm.exe", # In win64 subfolder
    ]

    for nssm_exe in nssm_locations:
        if nssm_exe.exists():
            shutil.copy2(nssm_exe, nssm_dest / "nssm.exe")
            log("NSSM ready", "OK")
            return True

    log("nssm.exe not found", "WARN")
    return True

def setup_azure_uploader():
    """Set up Azure IoT Hub uploader (now as compiled executable)."""
    log("Setting up Azure IoT Hub Uploader...")

    # Azure uploader is now compiled to AzureUploader.exe
    # No need for separate Python environment anymore!

    # Just create config directory for Azure
    azure_dest = BUILD_DIR / "azure"
    azure_dest.mkdir(exist_ok=True)

    # Copy example config if it exists
    azure_src = PROJECT_ROOT / "services" / "azure_uploader"
    if azure_src.exists():
        config_example = azure_src / "azure_uploader.ini.example"
        if config_example.exists():
            shutil.copy2(config_example, azure_dest / "azure_uploader.ini.example")

    log("Azure uploader directory created", "OK")
    return True

def copy_executables():
    """Copy compiled executables to build directory."""
    log("Copying executables...")

    # Core executables (required)
    for name in SPEC_FILES.keys():
        if name in ONEDIR_EXES:
            # onedir: PyInstaller emits EXE_DIR/<name>/{<name>.exe, _internal/}.
            # Copy the folder's CONTENTS so <name>.exe lands at the portable root
            # with its _internal alongside (no runtime self-extraction / _MEI popup).
            src_dir = EXE_DIR / name
            if not (src_dir / f"{name}.exe").exists():
                log(f"  {name}.exe not found (onedir output missing)!", "ERROR")
                return False
            for item in src_dir.iterdir():
                dest = BUILD_DIR / item.name
                if item.is_dir():
                    shutil.copytree(item, dest, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, dest)
            log(f"  Copied {name}.exe (+ _internal)")
        else:
            exe_src = EXE_DIR / f"{name}.exe"
            if exe_src.exists():
                shutil.copy2(exe_src, BUILD_DIR / f"{name}.exe")
                log(f"  Copied {name}.exe")
            else:
                log(f"  {name}.exe not found!", "ERROR")
                return False

    # Azure executable (optional -- build continues without it)
    azure_name = AZURE_SPEC[0]
    azure_src = EXE_DIR / f"{azure_name}.exe"
    if azure_src.exists():
        shutil.copy2(azure_src, BUILD_DIR / f"{azure_name}.exe")
        log(f"  Copied {azure_name}.exe")
    else:
        log(f"  {azure_name}.exe not found (Azure IoT Hub feature unavailable)", "WARN")

    log("Executables copied", "OK")
    return True

def copy_config():
    """Copy configuration files."""
    log("Copying configuration...")

    config_src = PROJECT_ROOT / "config"
    config_dest = BUILD_DIR / "config"

    # Remove the old config as far as we can. If something is still locked (almost
    # always the runtime-generated mosquitto_passwd, held open by a running
    # Mosquitto), don't fail the build — that file is in the ignore list below and
    # is never shipped anyway, so we just overlay the fresh config on top of it.
    overlay = False
    if config_dest.exists():
        failed = remove_tree_best_effort(config_dest)
        if failed:
            overlay = True
            _warn_locked_files(failed)

    shutil.copytree(
        config_src,
        config_dest,
        ignore=shutil.ignore_patterns(
            '*.log', '*.tmp',
            'mqtt_credentials.json',  # Auto-generated at runtime
            'mosquitto_passwd',       # Auto-generated at runtime
            'mosquitto_secure.conf',  # Superseded by mosquitto.conf
            'projects',              # Dev projects — portable starts clean
            'nisystem_settings.json', # Contains dev machine paths
        ),
        dirs_exist_ok=overlay,  # merge over whatever couldn't be deleted
    )

    # Create empty projects directory (with backups subdir)
    projects_dir = config_dest / "projects" / "backups"
    projects_dir.mkdir(parents=True, exist_ok=True)

    # Write clean settings file
    (config_dest / "nisystem_settings.json").write_text("{}")

    log("Configuration copied", "OK")
    return True

def copy_dashboard():
    """Copy built dashboard files."""
    log("Copying dashboard...")

    dashboard_src = PROJECT_ROOT / "dashboard" / "dist"
    dashboard_dest = BUILD_DIR / "www"

    if not dashboard_src.exists():
        log("Dashboard build not found", "ERROR")
        return False

    if dashboard_dest.exists():
        try:
            robust_rmtree(dashboard_dest)
        except PermissionError:
            log("Dashboard folder locked, updating files in place...", "WARN")
            # Copy files over existing ones
            for src_file in dashboard_src.rglob("*"):
                if src_file.is_file():
                    rel_path = src_file.relative_to(dashboard_src)
                    dest_file = dashboard_dest / rel_path
                    dest_file.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        shutil.copy2(src_file, dest_file)
                    except PermissionError:
                        pass
            log("Dashboard updated (some files may be stale)", "OK")
            return True

    shutil.copytree(dashboard_src, dashboard_dest)

    log("Dashboard copied", "OK")
    return True

def create_data_directories():
    """Create data directories."""
    log("Creating data directories...")

    data_dir = BUILD_DIR / "data"
    data_dir.mkdir(exist_ok=True)
    (data_dir / "recordings").mkdir(exist_ok=True)
    (data_dir / "logs").mkdir(exist_ok=True)
    (data_dir / "audit").mkdir(exist_ok=True)
    (data_dir / "historian").mkdir(exist_ok=True)

    log("Data directories created", "OK")
    return True

def copy_documentation():
    """Copy user documentation."""
    log("Copying documentation...")

    docs_dest = BUILD_DIR / "docs"
    docs_dest.mkdir(exist_ok=True)

    # Essential documentation for portable distribution
    user_docs = [
        ("README.md", "README.md"),
        ("INDUSTRIAL_BUILD_GUIDE.md", "Build_Guide.md"),
    ]

    count = 0
    for src_name, dest_name in user_docs:
        src = PROJECT_ROOT / src_name
        if src.exists():
            shutil.copy2(src, docs_dest / dest_name)
            count += 1

    log(f"Copied {count} documentation files", "OK")
    return True

def create_batch_launchers():
    """Create service install/uninstall batch scripts.

    Note: ICCSFlux.bat has been deprecated — ICCSFlux.exe is now a native
    desktop app (tkinter) that users launch directly.
    """
    log("Creating launchers...")
    # Legacy bat files are no longer shipped — service management is built into
    # ICCSFlux.exe (checkbox in UI, or --install-service / --uninstall-service CLI).
    # The bat templates above are kept for reference but not written to disk.
    log("Launchers created (service management built into ICCSFlux.exe)", "OK")
    return True

def create_readme(version: dict = None):
    """Create README file with optional build version info."""
    readme = '''ICCSFlux Portable - Industrial Data Acquisition System
=========================================================

QUICK START
-----------
1. Double-click ICCSFlux.exe
2. The launcher window opens showing service status
3. Click "Open Dashboard" to view the web interface
4. Close the launcher window to stop all services

WHAT'S INCLUDED
---------------
ICCSFlux.exe        - Launcher + service manager (native desktop app)
DAQService.exe      - Data acquisition backend (24 MB)
AzureUploader.exe   - Azure IoT Hub integration (11 MB)

mosquitto/          - MQTT broker for messaging
www/                - Dashboard web interface
config/             - Configuration files
data/               - Runtime data, logs, recordings

RUNNING OPTIONS
---------------

Option 1: Desktop Mode (recommended)
  - Double-click: ICCSFlux.exe
  - Native window with live service monitor
  - Click "Open Dashboard" for the web interface
  - Close the window to stop all services
  - Pin ICCSFlux.exe to your taskbar for quick access

Option 2: Windows Services (recommended for production)
  - Open ICCSFlux.exe
  - Check "Start automatically when this computer turns on"
  - You will be prompted for administrator permission
  - Services auto-start on boot, run even when logged out
  - Auto-restart on failure

  Or from the command line:
    ICCSFlux.exe --install-service
    ICCSFlux.exe --uninstall-service

  To disable auto-start:
  - Open ICCSFlux.exe
  - Uncheck "Start automatically when this computer turns on"

SERVICES INSTALLED
------------------
When auto-start is enabled, 4 Windows services are created:

  ICCSFlux-MQTT   - MQTT broker (port 1883, 9002)
  ICCSFlux-DAQ    - Data acquisition service
  ICCSFlux-Azure  - Azure uploader (if configured)
  ICCSFlux-Web    - Dashboard web server (port 5173)

All services are configured to:
  - Auto-start on Windows boot
  - Auto-restart on failure (5 second delay)
  - Rotate logs at 10 MB
  - Respect dependencies (MQTT starts first)

ACCESSING THE DASHBOARD
------------------------
Open your web browser to: http://localhost:5173

The dashboard can be accessed from:
  - The same PC
  - Any PC on the network (use the PC's IP address)
  - Tablets/phones on the same network

CONFIGURATION
-------------
Main configuration: config/system.ini
  - Channel definitions
  - Data acquisition settings
  - MQTT broker settings

Azure configuration: azure/azure_uploader.ini
  - Azure IoT Hub connection string
  - Upload settings
  - Only needed if using Azure

LOGS AND DATA
-------------
data/logs/          - Service logs
  - mosquitto.log     - MQTT broker
  - daq_service.log   - Data acquisition
  - azure_uploader.log - Azure uploader
  - web_server.log    - Dashboard server

data/recordings/    - Recorded data files
data/audit/         - Audit trail

TROUBLESHOOTING
---------------

Problem: Services won't start
  - Check logs in data/logs/
  - Verify ports 1883, 5173, 9002 are not in use
  - Try re-enabling auto-start from ICCSFlux.exe

Problem: Dashboard not loading
  - Check the launcher window for error messages
  - Try http://localhost:5173 directly in browser
  - Check data/logs/ for service logs

Problem: Port conflicts
  - Default ports: 1883 (MQTT), 5173 (Dashboard), 9002/9003 (MQTT WebSocket)
  - ICCSFlux will try to find alternative ports if defaults are busy

INDUSTRIAL FEATURES
-------------------
- Automatic service restart on failure
- Log rotation to prevent disk space issues
- Single instance lock (prevents conflicts)
- Service dependencies (correct startup order)
- All executables are self-contained (no Python installation needed)

REQUIREMENTS
------------
- Windows 10/11 (64-bit)
- For real hardware: NI-DAQmx drivers from ni.com
- Runs in simulation mode if no hardware detected

DOCUMENTATION
-------------
See docs/ folder for:
  - README.md          - Project overview
  - Build_Guide.md     - How to rebuild from source

SUPPORT
-------
For technical support, contact your system administrator.

VERSION INFORMATION
-------------------
Total size: ~65 MB
Build type: Compiled executables (PyInstaller)
Dashboard: Vue.js browser-based UI
MQTT: Eclipse Mosquitto 2.0.18

This is a self-contained, industrial-grade portable distribution.
'''
    # Append build version info if available
    if version:
        dirty = " (uncommitted changes)" if version.get("git_dirty") else ""
        tag = version.get("git_tag") or "none"
        version_block = f"""
Build Version
-------------
Build time:  {version['build_time']}
Git commit:  {version['git_hash_short']}{dirty}
Branch:      {version['git_branch']}
Tag:         {tag}
See VERSION.txt for full details.
"""
        readme += version_block

    (BUILD_DIR / "README.txt").write_text(readme)

    log("README created", "OK")
    return True

def generate_requirements_lock():
    """Freeze current environment to a lock file for reproducibility."""
    log("Generating requirements lock file...")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "freeze"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            lock_path = BUILD_DIR / "requirements-lock.txt"
            lock_path.write_text(result.stdout)
            count = len([l for l in result.stdout.strip().splitlines() if l and not l.startswith('#')])
            log(f"Requirements lock: {count} packages frozen", "OK")
            return True
    except Exception as e:
        log(f"Failed to freeze requirements: {e}", "WARN")
    return False

def generate_sbom():
    """Generate a CycloneDX SBOM (Software Bill of Materials) in JSON format.

    Requires: pip install cyclonedx-bom
    Falls back gracefully if not installed.
    """
    log("Generating SBOM (Software Bill of Materials)...")
    sbom_path = BUILD_DIR / "sbom.json"

    try:
        # cyclonedx-bom v7+ uses -o / --of flags
        result = subprocess.run(
            [sys.executable, "-m", "cyclonedx_py", "environment",
             "-o", str(sbom_path), "--of", "json",
             "--output-reproducible"],
            capture_output=True, text=True,
        )
        if result.returncode == 0 and sbom_path.exists():
            log("SBOM generated (CycloneDX JSON)", "OK")
            return True
        # Fallback for older cyclonedx-bom versions
        result = subprocess.run(
            [sys.executable, "-m", "cyclonedx_py", "environment",
             "--output", str(sbom_path), "--format", "json"],
            capture_output=True, text=True,
        )
        if result.returncode == 0 and sbom_path.exists():
            log("SBOM generated (CycloneDX JSON)", "OK")
            return True
    except Exception:
        pass

    log("cyclonedx-bom not installed — SBOM skipped (pip install cyclonedx-bom)", "WARN")
    return False

def run_vulnerability_audit():
    """Run pip-audit to check dependencies for known vulnerabilities.

    Requires: pip install pip-audit
    Falls back gracefully if not installed.
    """
    log("Running vulnerability audit (pip-audit)...")
    audit_path = BUILD_DIR / "vulnerability-audit.json"

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip_audit",
             "--format", "json", "--output", str(audit_path)],
            capture_output=True, text=True,
            timeout=120,
        )
        if audit_path.exists():
            if result.returncode == 0:
                log("Vulnerability audit: no known vulnerabilities", "OK")
            else:
                log("Vulnerability audit: findings detected — review vulnerability-audit.json", "WARN")
            return True
    except subprocess.TimeoutExpired:
        log("Vulnerability audit timed out (120s)", "WARN")
    except Exception:
        pass

    log("pip-audit not installed — vulnerability scan skipped (pip install pip-audit)", "WARN")
    return False

def sign_executables():
    """Sign all .exe files in the build directory with Authenticode.

    Requires:
    - Windows SDK (signtool.exe on PATH or in standard locations)
    - Environment variables:
      CODE_SIGN_PFX      — path to the .pfx certificate file
      CODE_SIGN_PASSWORD  — password for the .pfx file
    """
    pfx_path = os.environ.get("CODE_SIGN_PFX", "")
    pfx_password = os.environ.get("CODE_SIGN_PASSWORD", "")

    if not pfx_path:
        log("Code signing skipped — set CODE_SIGN_PFX and CODE_SIGN_PASSWORD to enable", "WARN")
        return False

    if not os.path.exists(pfx_path):
        log(f"Code signing certificate not found: {pfx_path}", "ERROR")
        return False

    # Find signtool.exe
    signtool = shutil.which("signtool")
    if not signtool:
        # Check standard Windows SDK locations
        sdk_base = Path(r"C:\Program Files (x86)\Windows Kits\10\bin")
        if sdk_base.exists():
            for version_dir in sorted(sdk_base.iterdir(), reverse=True):
                candidate = version_dir / "x64" / "signtool.exe"
                if candidate.exists():
                    signtool = str(candidate)
                    break

    if not signtool:
        log("signtool.exe not found — install Windows SDK or add to PATH", "ERROR")
        return False

    log(f"Signing executables with {Path(pfx_path).name}...")

    exe_files = list(BUILD_DIR.glob("*.exe"))
    # Also sign tools
    tools_dir = BUILD_DIR / "tools"
    if tools_dir.exists():
        exe_files.extend(tools_dir.glob("*.exe"))

    signed = 0
    for exe in exe_files:
        try:
            cmd = [
                signtool, "sign",
                "/f", pfx_path,
                "/fd", "SHA256",
                "/tr", "http://timestamp.digicert.com",
                "/td", "SHA256",
            ]
            if pfx_password:
                cmd.extend(["/p", pfx_password])
            cmd.extend(["/v", str(exe)])

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                log(f"  Signed {exe.name}")
                signed += 1
            else:
                log(f"  Failed to sign {exe.name}: {result.stderr.strip()}", "ERROR")
        except subprocess.TimeoutExpired:
            log(f"  Signing timed out for {exe.name}", "ERROR")
        except Exception as e:
            log(f"  Signing error for {exe.name}: {e}", "ERROR")

    if signed == len(exe_files):
        log(f"All {signed} executables signed", "OK")
        return True
    elif signed > 0:
        log(f"Signed {signed}/{len(exe_files)} executables", "WARN")
        return True
    else:
        log("No executables were signed", "ERROR")
        return False

def generate_hash_manifest():
    """Generate SHA256SUMS.txt with hashes of all executables."""
    log("Generating SHA-256 hash manifest...")

    exe_files = sorted(BUILD_DIR.glob("*.exe"))
    # Include tools
    tools_dir = BUILD_DIR / "tools"
    if tools_dir.exists():
        exe_files.extend(sorted(tools_dir.glob("*.exe")))

    manifest_lines = []
    for exe in exe_files:
        h = hashlib.sha256(exe.read_bytes()).hexdigest()
        # Relative path from BUILD_DIR
        rel = exe.relative_to(BUILD_DIR)
        manifest_lines.append(f"{h}  {rel}")

    manifest_path = BUILD_DIR / "SHA256SUMS.txt"
    manifest_path.write_text("\n".join(manifest_lines) + "\n")
    log(f"Hash manifest: {len(manifest_lines)} files", "OK")
    return True

def generate_audit_report(version: dict):
    """Generate a human-readable build audit report and archive it.

    Creates:
    - BUILD_DIR/BUILD_AUDIT_REPORT.txt         (ships with the build)
    - PROJECT_ROOT/audit_reports/<stamp>.txt    (permanent archive)
    """
    import json as _json

    log("Generating build audit report...")

    dirty = " (uncommitted changes)" if version.get("git_dirty") else ""
    tag = version.get("git_tag") or "none"
    signed = bool(os.environ.get("CODE_SIGN_PFX"))
    timestamp = version.get("build_time", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"))

    # ── Collect executable hashes ────────────────────────────────
    exe_hashes = []
    hash_file = BUILD_DIR / "SHA256SUMS.txt"
    if hash_file.exists():
        for line in hash_file.read_text().strip().splitlines():
            if line.strip():
                parts = line.split("  ", 1)
                if len(parts) == 2:
                    exe_hashes.append((parts[1], parts[0]))

    # ── Collect vulnerability findings ───────────────────────────
    vuln_summary = "Not scanned"
    vuln_details = []
    audit_file = BUILD_DIR / "vulnerability-audit.json"
    if audit_file.exists():
        try:
            data = _json.loads(audit_file.read_text())
            deps = data if isinstance(data, list) else data.get("dependencies", [])
            vulns = [d for d in deps if d.get("vulns")]
            if vulns:
                vuln_summary = f"{len(vulns)} package(s) with known vulnerabilities"
                for v in vulns:
                    for vuln in v.get("vulns", []):
                        vuln_details.append(
                            f"  - {v.get('name', '?')} {v.get('version', '?')}: "
                            f"{vuln.get('id', '?')} (fix: {', '.join(vuln.get('fix_versions', ['N/A']))})"
                        )
            else:
                vuln_summary = "No known vulnerabilities found"
        except Exception:
            vuln_summary = "Scan completed (see vulnerability-audit.json)"

    # ── Collect SBOM stats ───────────────────────────────────────
    sbom_summary = "Not generated"
    sbom_file = BUILD_DIR / "sbom.json"
    if sbom_file.exists():
        try:
            data = _json.loads(sbom_file.read_text())
            count = len(data.get("components", []))
            sbom_summary = f"{count} components cataloged (CycloneDX JSON)"
        except Exception:
            sbom_summary = "Generated (see sbom.json)"

    # ── Collect dependency count ─────────────────────────────────
    lock_file = BUILD_DIR / "requirements-lock.txt"
    dep_count = "N/A"
    if lock_file.exists():
        lines = [l for l in lock_file.read_text().strip().splitlines()
                 if l.strip() and not l.startswith('#')]
        dep_count = str(len(lines))

    # ── Build the report ─────────────────────────────────────────
    lines = [
        "=" * 70,
        "  ICCSFlux BUILD AUDIT REPORT",
        "=" * 70,
        "",
        "BUILD INFORMATION",
        "-" * 40,
        f"  Build time:       {timestamp}",
        f"  Git commit:       {version.get('git_hash', 'unknown')}{dirty}",
        f"  Branch:           {version.get('git_branch', 'unknown')}",
        f"  Tag:              {tag}",
        f"  Code signed:      {'Yes (Authenticode SHA-256)' if signed else 'No'}",
        f"  Reproducible:     Yes (PYTHONHASHSEED=1, SOURCE_DATE_EPOCH set)",
        "",
        "EXECUTABLE HASHES (SHA-256)",
        "-" * 40,
    ]
    if exe_hashes:
        for name, h in exe_hashes:
            lines.append(f"  {name:<30s} {h}")
    else:
        lines.append("  No executables found")

    lines += [
        "",
        "DEPENDENCY INVENTORY",
        "-" * 40,
        f"  Total packages:   {dep_count}",
        f"  SBOM:             {sbom_summary}",
        f"  Lock file:        {'requirements-lock.txt' if lock_file.exists() else 'Not generated'}",
        "",
        "VULNERABILITY SCAN",
        "-" * 40,
        f"  Result:           {vuln_summary}",
    ]
    if vuln_details:
        lines.append("  Findings:")
        lines.extend(vuln_details)

    lines += [
        "",
        "COMPLIANCE ARTIFACTS INCLUDED",
        "-" * 40,
    ]
    for artifact in ["VERSION.txt", "SHA256SUMS.txt", "SOURCE_MANIFEST.json",
                     "sbom.json", "vulnerability-audit.json",
                     "requirements-lock.txt", "BUILD_AUDIT_REPORT.txt"]:
        exists = (BUILD_DIR / artifact).exists() or artifact == "BUILD_AUDIT_REPORT.txt"
        status = "[x]" if exists else "[ ]"
        lines.append(f"  {status} {artifact}")

    lines += [
        "",
        "CHANGE MANAGEMENT",
        "-" * 40,
    ]
    # Include last 10 git commits for traceability
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "-10"],
            capture_output=True, text=True, cwd=PROJECT_ROOT,
        )
        if result.returncode == 0 and result.stdout.strip():
            lines.append("  Recent commits:")
            for commit_line in result.stdout.strip().splitlines():
                lines.append(f"    {commit_line}")
        else:
            lines.append("  Git log unavailable")
    except Exception:
        lines.append("  Git log unavailable")

    lines += [
        "",
        "=" * 70,
        f"  Report generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "=" * 70,
        "",
    ]

    report_text = "\n".join(lines)

    # Write to build directory (ships with the build)
    report_path = BUILD_DIR / "BUILD_AUDIT_REPORT.txt"
    report_path.write_text(report_text)

    # Archive to project audit_reports/ directory (permanent history)
    archive_dir = PROJECT_ROOT / "audit_reports"
    archive_dir.mkdir(exist_ok=True)

    short_hash = version.get("git_hash_short", "unknown")
    date_stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    archive_name = f"build_audit_{date_stamp}_{short_hash}.txt"
    archive_path = archive_dir / archive_name
    archive_path.write_text(report_text)

    log(f"Audit report: {report_path.name} (archived to audit_reports/{archive_name})", "OK")
    return True

def generate_source_manifest():
    """Capture SHA256 hashes of all source files for build-to-build diff comparison.

    Saves SOURCE_MANIFEST.json to the build directory. Use scripts/build_diff.py
    to compare the current working tree against a previous build's manifest.
    """
    import json as _json

    log("Generating source manifest...")

    source_patterns = [
        "services/**/*.py",
        "scripts/*.py",
        "dashboard/src/**/*.vue",
        "dashboard/src/**/*.ts",
        "dashboard/src/**/*.tsx",
        "config/*.json",
        "config/*.conf",
        "config/*.ini",
        "*.md",
        "*.bat",
    ]
    # Directories to exclude
    exclude_dirs = {"node_modules", "__pycache__", ".git", "dist", "build",
                    "venv", "azure-venv", ".venv", "vendor", "data"}

    manifest = {}
    for pattern in source_patterns:
        for filepath in PROJECT_ROOT.glob(pattern):
            if not filepath.is_file():
                continue
            # Skip excluded directories
            rel = filepath.relative_to(PROJECT_ROOT)
            if any(part in exclude_dirs for part in rel.parts):
                continue
            try:
                h = hashlib.sha256(filepath.read_bytes()).hexdigest()
                manifest[str(rel.as_posix())] = h
            except (OSError, PermissionError):
                continue

    output = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "file_count": len(manifest),
        "files": dict(sorted(manifest.items())),
    }

    manifest_path = BUILD_DIR / "SOURCE_MANIFEST.json"
    manifest_path.write_text(_json.dumps(output, indent=2))
    log(f"Source manifest: {len(manifest)} source files captured", "OK")
    return True

def get_build_size():
    """Calculate total build size."""
    total = 0
    for path in BUILD_DIR.rglob("*"):
        if path.is_file():
            total += path.stat().st_size
    return total / (1024 * 1024)  # MB

def main():
    parser = argparse.ArgumentParser(description="Build ICCSFlux portable package")
    parser.add_argument("--quick", action="store_true", help="Skip recompilation if executables exist")
    parser.add_argument("--sign", action="store_true", help="Sign executables (requires CODE_SIGN_PFX env var)")
    parser.add_argument("--no-sbom", action="store_true", help="Skip SBOM generation and vulnerability audit")
    parser.add_argument("--keep-broker", action="store_true",
                        help="Do NOT stop a running Mosquitto broker (default: stop it so the "
                             "built portable can own port 1883)")
    args = parser.parse_args()

    print()
    print("=" * 60)
    print("       ICCSFlux Portable Builder (PyInstaller Edition)")
    print("=" * 60)
    print()

    # Capture build version early (before any git changes from build process)
    version = get_build_version()
    dirty = " (dirty)" if version["git_dirty"] else ""
    log(f"Build version: {version['git_hash_short']}{dirty} ({version['git_branch']})")

    if not check_prerequisites():
        return 1

    # Set reproducible build environment (fixes hash randomization + PE timestamps)
    setup_reproducible_env()

    # Stop any already-running Mosquitto broker BEFORE cleaning: it frees the file
    # lock on config\mosquitto_passwd and, crucially, leaves port 1883 free so the
    # portable build you run next starts its OWN broker instead of attaching to a
    # mis-configured external one. Admin is required ONLY when a broker is actually
    # running (stopping a service needs it) — a plain build needs no elevation.
    # Opt out with --keep-broker.
    if not args.keep_broker:
        if not stop_conflicting_broker():
            return 1

    clean_build()

    print()
    if not build_dashboard():
        return 1

    print()
    if not compile_executables(quick_mode=args.quick):
        return 1

    # Build standalone tools (ModbusTool, etc.)
    print()
    compile_tools(quick_mode=args.quick)

    # Build AzureUploader in isolated venv (paho-mqtt 1.x + azure-iot-device)
    print()
    log("Building Azure IoT Hub Uploader...")
    azure_python = create_azure_venv()
    if azure_python:
        if not compile_azure_exe(azure_python, quick_mode=args.quick):
            log("AzureUploader.exe build failed (Azure feature will be unavailable)", "WARN")
    else:
        log("Azure venv creation failed (Azure feature will be unavailable)", "WARN")

    print()
    if not setup_mosquitto():
        return 1

    setup_nssm()
    setup_azure_uploader()

    print()
    if not copy_executables():
        return 1

    copy_tools()

    if not copy_config():
        return 1

    if not copy_dashboard():
        return 1

    if not create_data_directories():
        return 1

    copy_documentation()
    create_batch_launchers()
    create_readme(version)
    write_version_file(version)

    # ── Compliance artifacts ──────────────────────────────────────
    print()
    log("Generating compliance artifacts...")
    generate_requirements_lock()

    if not args.no_sbom:
        generate_sbom()
        run_vulnerability_audit()

    if args.sign or os.environ.get("CODE_SIGN_PFX"):
        print()
        sign_executables()

    # Hash manifest (always generated, must come AFTER signing so hashes
    # reflect the signed binaries, not the unsigned ones)
    generate_hash_manifest()

    # Source manifest (captures SHA256 of every source file for build-to-build diffs)
    generate_source_manifest()

    # Audit report (human-readable summary + permanent archive)
    generate_audit_report(version)

    size_mb = get_build_size()
    dirty = " (dirty)" if version["git_dirty"] else ""

    # Remove the intermediate PyInstaller exe output (dist/exe) now that everything
    # is assembled into the portable folder — keeps dist/ to just the deliverable.
    # Skipped under --quick, which reuses those exes as a recompile cache.
    if not args.quick and EXE_DIR.exists():
        remove_tree_best_effort(EXE_DIR)
        log(f"Removed intermediate build output: {EXE_DIR.relative_to(PROJECT_ROOT)}", "OK")

    print()
    print("=" * 60)
    log("Build complete!", "OK")
    print()
    print(f"  Output:  {BUILD_DIR}")
    print(f"  Size:    {size_mb:.1f} MB")
    print(f"  Version: {version['git_hash_short']}{dirty}")
    print(f"  Built:   {version['build_time']}")
    print()
    # Summarize compliance artifacts
    artifacts = []
    if (BUILD_DIR / "SHA256SUMS.txt").exists():
        artifacts.append("SHA256SUMS.txt")
    if (BUILD_DIR / "sbom.json").exists():
        artifacts.append("sbom.json")
    if (BUILD_DIR / "vulnerability-audit.json").exists():
        artifacts.append("vulnerability-audit.json")
    if (BUILD_DIR / "requirements-lock.txt").exists():
        artifacts.append("requirements-lock.txt")
    if (BUILD_DIR / "SOURCE_MANIFEST.json").exists():
        artifacts.append("SOURCE_MANIFEST.json")
    if (BUILD_DIR / "BUILD_AUDIT_REPORT.txt").exists():
        artifacts.append("BUILD_AUDIT_REPORT.txt")
    if artifacts:
        print(f"  Compliance: {', '.join(artifacts)}")
    if os.environ.get("CODE_SIGN_PFX"):
        print("  Signed:  Yes (Authenticode SHA-256)")
    else:
        print("  Signed:  No (set CODE_SIGN_PFX to enable)")
    print()
    print("  To run: Double-click ICCSFlux.exe")
    print("=" * 60)

    return 0

if __name__ == "__main__":
    sys.exit(main())
