#!/usr/bin/env python3
"""
Build ICCSFlux Fleet Monitor as a portable package.

Creates: dist/FleetMonitor-Portable/
  ├── FleetMonitor.exe   (Python launcher)
  └── www/               (Vue SPA build)

Usage:
    python scripts/build_monitor.py
    python scripts/build_monitor.py --skip-npm   # Skip npm build (use existing dist/)
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
MONITOR_DIR = PROJECT_ROOT / "monitor"
MONITOR_DIST = MONITOR_DIR / "dist"
BUILD_DIR = PROJECT_ROOT / "dist" / "FleetMonitor-Portable"
EXE_DIR = PROJECT_ROOT / "dist" / "exe"
SPEC_FILE = PROJECT_ROOT / "scripts" / "fleet_monitor.spec"


def log(msg, level="INFO"):
    prefix = {"INFO": " ", "OK": "+", "ERROR": "!", "WARN": "~"}
    print(f"  [{prefix.get(level, ' ')}] {msg}")


def build_dashboard():
    """Build the Vue monitor SPA."""
    log("Building Fleet Monitor dashboard...")

    if not (MONITOR_DIR / "package.json").exists():
        log("monitor/package.json not found!", "ERROR")
        return False

    # Ensure dependencies are installed
    if not (MONITOR_DIR / "node_modules").exists():
        log("Installing npm dependencies...")
        result = subprocess.run(
            ["npm", "install"],
            cwd=MONITOR_DIR,
            shell=True,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            log(f"npm install failed: {result.stderr}", "ERROR")
            return False

    # Build
    result = subprocess.run(
        ["npm", "run", "build"],
        cwd=MONITOR_DIR,
        shell=True,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        log(f"npm run build failed:\n{result.stderr}", "ERROR")
        return False

    if not MONITOR_DIST.exists():
        log("Build output not found at monitor/dist/", "ERROR")
        return False

    log("Dashboard built successfully", "OK")
    return True


def compile_exe():
    """Compile the launcher with PyInstaller."""
    log("Compiling FleetMonitor.exe with PyInstaller...")

    EXE_DIR.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        [
            sys.executable, "-m", "PyInstaller",
            str(SPEC_FILE),
            "--distpath", str(EXE_DIR),
            "--workpath", str(PROJECT_ROOT / "build" / "pyinstaller-monitor"),
            "--noconfirm",
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        log(f"PyInstaller failed:\n{result.stderr}", "ERROR")
        return False

    exe_path = EXE_DIR / "FleetMonitor.exe"
    if not exe_path.exists():
        log("FleetMonitor.exe not found after compilation!", "ERROR")
        return False

    size_mb = exe_path.stat().st_size / (1024 * 1024)
    log(f"FleetMonitor.exe compiled ({size_mb:.1f} MB)", "OK")
    return True


def assemble_package():
    """Assemble the portable folder."""
    log("Assembling portable package...")

    # Clean previous build
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
    BUILD_DIR.mkdir(parents=True)

    # Copy exe
    exe_src = EXE_DIR / "FleetMonitor.exe"
    if exe_src.exists():
        shutil.copy2(exe_src, BUILD_DIR / "FleetMonitor.exe")
        log("Copied FleetMonitor.exe", "OK")
    else:
        log("FleetMonitor.exe not found — skipping", "WARN")

    # Copy dashboard
    www_dest = BUILD_DIR / "www"
    if MONITOR_DIST.exists():
        shutil.copytree(MONITOR_DIST, www_dest)
        log(f"Copied dashboard to www/ ({sum(1 for _ in www_dest.rglob('*') if _.is_file())} files)", "OK")
    else:
        log("monitor/dist/ not found — run npm build first", "ERROR")
        return False

    # Write version file
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%h %s"],
            capture_output=True, text=True, cwd=PROJECT_ROOT
        )
        commit = result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        commit = "unknown"

    # Compute SHA-256 hash of the exe (for SentinelOne / EDR whitelisting)
    import hashlib
    exe_path = BUILD_DIR / "FleetMonitor.exe"
    exe_hash = ""
    if exe_path.exists():
        sha = hashlib.sha256()
        with open(exe_path, 'rb') as f:
            for chunk in iter(lambda: f.read(65536), b''):
                sha.update(chunk)
        exe_hash = sha.hexdigest()
        log(f"SHA-256: {exe_hash}", "OK")

    from datetime import datetime, timezone
    version_text = (
        f"ICCSFlux Fleet Monitor\n"
        f"Build: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
        f"Commit: {commit}\n"
    )
    if exe_hash:
        version_text += f"SHA-256: {exe_hash}\n"
    (BUILD_DIR / "VERSION.txt").write_text(version_text)

    # Calculate total size
    total = sum(f.stat().st_size for f in BUILD_DIR.rglob('*') if f.is_file())
    log(f"Package assembled: {total / (1024 * 1024):.1f} MB total", "OK")
    return True


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Build ICCSFlux Fleet Monitor portable package")
    parser.add_argument("--skip-npm", action="store_true", help="Skip npm build (use existing monitor/dist/)")
    args = parser.parse_args()

    print()
    print("=" * 50)
    print("    ICCSFlux Fleet Monitor — Portable Builder")
    print("=" * 50)
    print()

    # 1. Build dashboard
    if not args.skip_npm:
        if not build_dashboard():
            return 1
    else:
        if not MONITOR_DIST.exists():
            log("monitor/dist/ not found — cannot skip npm build", "ERROR")
            return 1
        log("Skipping npm build (using existing monitor/dist/)")

    # 2. Compile exe
    if not compile_exe():
        return 1

    # 3. Assemble
    if not assemble_package():
        return 1

    print()
    print(f"  Output: {BUILD_DIR}")
    print(f"  Run:    FleetMonitor.exe")
    print()

    return 0


if __name__ == '__main__':
    sys.exit(main())
