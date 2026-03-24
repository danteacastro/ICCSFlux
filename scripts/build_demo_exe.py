"""
Build ICCSFlux Demo as a self-contained Windows executable.

The demo build:
  - Builds the Vue dashboard normally (standard npm run build)
  - Compiles a minimal launcher (iccsflux_demo.py) with PyInstaller
      -> No MQTT broker, no DAQ service, just an HTTP server
      -> Injects window.ICCSFLUX_DEMO_MODE=true into index.html at runtime
         so demo mode is controlled by the server, not the build
  - Outputs to dist/ICCSFlux-Demo/

Usage:
    python scripts/build_demo_exe.py

Output: dist/ICCSFlux-Demo/
"""

import sys
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
DEMO_DIR = PROJECT_ROOT / "dist" / "ICCSFlux-Demo"
EXE_DIR = PROJECT_ROOT / "dist" / "exe"
DASHBOARD_DIR = PROJECT_ROOT / "dashboard"
DASHBOARD_DIST = DASHBOARD_DIR / "dist"
LAUNCHER_SCRIPT = PROJECT_ROOT / "scripts" / "iccsflux_demo.py"

def log(msg, level="INFO"):
    prefix = {"INFO": "[BUILD]", "WARN": "[WARN]", "ERROR": "[ERROR]", "OK": "[  OK ]"}
    print(f"{prefix.get(level, '[    ]')} {msg}")

def check_prerequisites():
    try:
        result = subprocess.run("npm --version", capture_output=True, text=True, shell=True)
        if result.returncode != 0:
            log("npm not found", "ERROR")
            return False
        log(f"  npm: v{result.stdout.strip()}")
    except Exception as e:
        log(f"npm check failed: {e}", "ERROR")
        return False

    try:
        import PyInstaller
        log(f"  PyInstaller: v{PyInstaller.__version__}")
    except ImportError:
        log("PyInstaller not found (pip install pyinstaller)", "ERROR")
        return False

    if not LAUNCHER_SCRIPT.exists():
        log(f"Demo launcher not found: {LAUNCHER_SCRIPT}", "ERROR")
        return False

    return True

def build_dashboard():
    """Build the Vue dashboard with the standard production build."""
    log("Building dashboard (standard production build)...")

    env_local = DASHBOARD_DIR / ".env.local"
    env_local_backup = DASHBOARD_DIR / ".env.local.build-backup"
    if env_local.exists():
        log("  Temporarily removing .env.local")
        env_local.rename(env_local_backup)

    try:
        subprocess.run(
            "npm run build",
            cwd=DASHBOARD_DIR,
            check=True,
            capture_output=True,
            shell=True,
        )
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode() if e.stderr else str(e)
        log(f"Dashboard build failed:\n{stderr}", "ERROR")
        return False
    finally:
        if env_local_backup.exists():
            env_local_backup.rename(env_local)

    if not (DASHBOARD_DIST / "index.html").exists():
        log("dashboard/dist/index.html not found after build", "ERROR")
        return False

    log("Dashboard built", "OK")
    return True

def compile_demo_launcher():
    """Compile iccsflux_demo.py into ICCSFluxDemo.exe using PyInstaller."""
    log("Compiling ICCSFluxDemo.exe...")

    EXE_DIR.mkdir(parents=True, exist_ok=True)

    try:
        subprocess.run(
            [
                sys.executable, "-m", "PyInstaller",
                str(LAUNCHER_SCRIPT),
                "--name", "ICCSFluxDemo",
                "--onedir",
                "--windowed",
                "--hidden-import", "tkinter",
                "--hidden-import", "tkinter.messagebox",
                "--hidden-import", "tkinter.font",
                "--distpath", str(EXE_DIR),
                "--workpath", str(PROJECT_ROOT / "build" / "pyinstaller-demo"),
                "--noconfirm",
                "--clean",
            ],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode() if e.stderr else str(e)
        log(f"PyInstaller failed:\n{stderr}", "ERROR")
        return False

    exe = EXE_DIR / "ICCSFluxDemo" / "ICCSFluxDemo.exe"
    if not exe.exists():
        log("ICCSFluxDemo.exe not found after compile", "ERROR")
        return False

    log(f"ICCSFluxDemo.exe compiled ({exe.stat().st_size // 1024 // 1024} MB)", "OK")
    return True

def assemble_demo():
    """Assemble the demo folder: launcher + dashboard + readme."""
    log("Assembling demo build...")

    if DEMO_DIR.exists():
        try:
            shutil.rmtree(DEMO_DIR)
        except PermissionError as e:
            log(f"Could not fully clean demo dir: {e}", "WARN")
    DEMO_DIR.mkdir(parents=True, exist_ok=True)

    # Copy compiled launcher folder (onedir layout — all DLLs alongside exe)
    src_dir = EXE_DIR / "ICCSFluxDemo"
    if not src_dir.exists():
        log("ICCSFluxDemo/ folder not found", "ERROR")
        return False
    for item in src_dir.iterdir():
        dest = DEMO_DIR / item.name
        if item.is_dir():
            if dest.exists():
                shutil.rmtree(dest, ignore_errors=True)
            shutil.copytree(item, dest)
        else:
            shutil.copy2(item, dest)
    log("  Copied ICCSFluxDemo launcher")

    # Copy dashboard build as www/
    www_dest = DEMO_DIR / "www"
    if not DASHBOARD_DIST.exists():
        log("dashboard/dist not found", "ERROR")
        return False
    if www_dest.exists():
        try:
            shutil.rmtree(www_dest)
        except PermissionError:
            log("www/ locked — updating files in place...", "WARN")
            for src_file in DASHBOARD_DIST.rglob("*"):
                if src_file.is_file():
                    rel = src_file.relative_to(DASHBOARD_DIST)
                    dst = www_dest / rel
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        shutil.copy2(src_file, dst)
                    except PermissionError:
                        pass
            log("  Updated dashboard -> www/")
            return True
    shutil.copytree(DASHBOARD_DIST, www_dest)
    log("  Copied dashboard -> www/")

    # Write readme
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, cwd=PROJECT_ROOT,
        )
        git_hash = result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        git_hash = "unknown"

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    readme = f"""\
ICCSFlux Demo
=============
Build:   {git_hash}  ({ts})
Mode:    Demo (no backend required)

QUICK START
-----------
1. Double-click ICCSFluxDemo.exe
2. Browser opens automatically to http://localhost:5173
3. Browse all tabs — no hardware or services needed
4. Close the launcher window to stop

WHAT THIS DEMO SHOWS
--------------------
- Full dashboard UI with all tabs and configuration panels
- Admin access enabled — all features visible
- No live data (no acquisition running)
- Connection overlay suppressed

To return to production mode, use the regular ICCSFlux.exe build.
"""
    (DEMO_DIR / "README.txt").write_text(readme)
    log("  README.txt written")

    log(f"Demo build assembled at: {DEMO_DIR}", "OK")
    return True

def main():
    log("=" * 50)
    log("ICCSFlux Demo Build")
    log("=" * 50)

    if not check_prerequisites():
        sys.exit(1)

    steps = [
        ("Build dashboard", build_dashboard),
        ("Compile demo launcher", compile_demo_launcher),
        ("Assemble demo folder", assemble_demo),
    ]

    for desc, fn in steps:
        log(f"\n--- {desc} ---")
        if not fn():
            log(f"FAILED at: {desc}", "ERROR")
            sys.exit(1)

    total = sum(f.stat().st_size for f in DEMO_DIR.rglob("*") if f.is_file())
    log(f"\nDemo build complete: {DEMO_DIR}")
    log(f"Total size: {total // 1024 // 1024} MB")
    log("Run: dist/ICCSFlux-Demo/ICCSFluxDemo.exe")

if __name__ == "__main__":
    main()
