"""
Cleanup script for ICCSFlux Portable build.

Removes unnecessary files from the portable distribution to reduce size:
- pip and setuptools (only needed during build)
- wheel package (only needed for pip install)
- test directories (not needed in production)
- .dist-info metadata (optional)
- __pycache__ directories (optional, will regenerate)

Run this AFTER build_portable.py completes.

Usage:
    python cleanup_portable.py                  # Safe cleanup
    python cleanup_portable.py --aggressive     # Aggressive cleanup (includes dist-info)
    python cleanup_portable.py --pycache        # Also remove pycache (regenerates on first run)
"""

import shutil
import argparse
from pathlib import Path

def log(msg, level="INFO"):
    prefix = {"INFO": "[CLEAN]", "WARN": "[WARN]", "OK": "[  OK ]"}
    print(f"{prefix.get(level, '[    ]')} {msg}")

def get_dir_size(path):
    """Calculate directory size in MB"""
    total = sum(f.stat().st_size for f in path.rglob('*') if f.is_file())
    return total / (1024 * 1024)

def remove_dir(path, desc=None):
    """Remove directory and report size saved"""
    if not path.exists():
        return 0

    size_mb = get_dir_size(path)
    shutil.rmtree(path)

    if desc:
        log(f"Removed {desc}: {size_mb:.1f} MB")
    else:
        log(f"Removed {path.name}: {size_mb:.1f} MB")

    return size_mb

def remove_file(path, silent=False):
    """Remove file"""
    if not path.exists():
        return 0

    size_mb = path.stat().st_size / (1024 * 1024)
    path.unlink()

    if not silent:
        log(f"Removed {path.name}")

    return size_mb

def cleanup_python_env(python_dir, env_name="Python"):
    """Clean up a Python environment"""
    log(f"Cleaning {env_name} environment...")

    site_packages = python_dir / "Lib" / "site-packages"
    scripts_dir = python_dir / "Scripts"

    saved = 0.0

    # Remove pip
    pip_dir = site_packages / "pip"
    if pip_dir.exists():
        saved += remove_dir(pip_dir, "pip")

    # Remove setuptools
    setuptools_dir = site_packages / "setuptools"
    if setuptools_dir.exists():
        saved += remove_dir(setuptools_dir, "setuptools")

    # Remove pkg_resources (part of setuptools)
    pkg_resources = site_packages / "pkg_resources"
    if pkg_resources.exists():
        saved += remove_dir(pkg_resources, "pkg_resources")

    # Remove wheel
    wheel_dir = site_packages / "wheel"
    if wheel_dir.exists():
        saved += remove_dir(wheel_dir, "wheel")

    # Remove pip/wheel executables
    if scripts_dir.exists():
        for exe in scripts_dir.glob("pip*.exe"):
            saved += remove_file(exe, silent=True)
        for exe in scripts_dir.glob("wheel*.exe"):
            saved += remove_file(exe, silent=True)

    log(f"{env_name} environment cleaned: {saved:.1f} MB saved", "OK")
    return saved

def remove_test_directories(root_dir):
    """Remove all test directories"""
    log("Removing test directories...")

    saved = 0.0
    count = 0

    # Find all test directories
    test_dirs = []
    for pattern in ["tests", "test", "testing"]:
        test_dirs.extend(root_dir.rglob(pattern))

    # Only process directories
    test_dirs = [d for d in test_dirs if d.is_dir()]

    for test_dir in test_dirs:
        try:
            saved += remove_dir(test_dir)
            count += 1
        except Exception as e:
            log(f"Failed to remove {test_dir}: {e}", "WARN")

    log(f"Removed {count} test directories: {saved:.1f} MB saved", "OK")
    return saved

def remove_dist_info(root_dir):
    """Remove .dist-info directories (metadata)"""
    log("Removing .dist-info metadata...")

    saved = 0.0
    count = 0

    for dist_info in root_dir.rglob("*.dist-info"):
        if dist_info.is_dir():
            try:
                saved += remove_dir(dist_info)
                count += 1
            except Exception as e:
                log(f"Failed to remove {dist_info}: {e}", "WARN")

    log(f"Removed {count} .dist-info directories: {saved:.1f} MB saved", "OK")
    return saved

def remove_pycache(root_dir):
    """Remove __pycache__ directories and .pyc files"""
    log("Removing __pycache__ directories...")

    saved = 0.0
    count = 0

    # Remove __pycache__ directories
    for pycache in root_dir.rglob("__pycache__"):
        if pycache.is_dir():
            try:
                saved += remove_dir(pycache)
                count += 1
            except Exception as e:
                log(f"Failed to remove {pycache}: {e}", "WARN")

    # Remove .pyc files
    for pyc in root_dir.rglob("*.pyc"):
        if pyc.is_file():
            try:
                saved += remove_file(pyc, silent=True)
            except Exception as e:
                log(f"Failed to remove {pyc}: {e}", "WARN")

    log(f"Removed {count} __pycache__ directories: {saved:.1f} MB saved", "OK")
    log("NOTE: .pyc files will regenerate on first run", "WARN")
    return saved

def main():
    parser = argparse.ArgumentParser(description="Cleanup ICCSFlux Portable build")
    parser.add_argument('--aggressive', action='store_true',
                        help='Remove .dist-info metadata (may break some tools)')
    parser.add_argument('--pycache', action='store_true',
                        help='Remove __pycache__ (will regenerate on first run)')
    parser.add_argument('--build-dir', type=Path,
                        help='Custom build directory (default: dist/ICCSFlux-Portable)')
    args = parser.parse_args()

    # Determine build directory
    if args.build_dir:
        build_dir = args.build_dir
    else:
        script_dir = Path(__file__).parent
        project_root = script_dir.parent
        build_dir = project_root / "dist" / "ICCSFlux-Portable"

    if not build_dir.exists():
        log(f"Build directory not found: {build_dir}", "ERROR")
        log("Run build_portable.py first!", "ERROR")
        return 1

    print()
    print("=" * 60)
    print("       ICCSFlux Portable Cleanup")
    print("=" * 60)
    print()

    # Get initial size
    initial_size = get_dir_size(build_dir)
    log(f"Initial size: {initial_size:.1f} MB")
    print()

    total_saved = 0.0

    # Clean main Python environment
    python_dir = build_dir / "python"
    if python_dir.exists():
        total_saved += cleanup_python_env(python_dir, "Main Python")
        print()

    # Clean Azure uploader Python environment
    azure_python_dir = build_dir / "azure_uploader" / "python"
    if azure_python_dir.exists():
        total_saved += cleanup_python_env(azure_python_dir, "Azure Python")
        print()

    # Remove test directories
    total_saved += remove_test_directories(build_dir)
    print()

    # Aggressive cleanup
    if args.aggressive:
        log("Aggressive mode: removing .dist-info metadata", "WARN")
        total_saved += remove_dist_info(build_dir)
        print()

    # Remove pycache
    if args.pycache:
        log("Removing __pycache__ (will regenerate on first run)", "WARN")
        total_saved += remove_pycache(build_dir)
        print()

    # Final size
    final_size = get_dir_size(build_dir)

    print()
    print("=" * 60)
    log("Cleanup complete!", "OK")
    print()
    print(f"  Initial size:  {initial_size:.1f} MB")
    print(f"  Final size:    {final_size:.1f} MB")
    print(f"  Space saved:   {total_saved:.1f} MB ({total_saved/initial_size*100:.1f}%)")
    print()
    print(f"  Build directory: {build_dir}")
    print("=" * 60)
    print()

    return 0

if __name__ == "__main__":
    import sys
    sys.exit(main())
