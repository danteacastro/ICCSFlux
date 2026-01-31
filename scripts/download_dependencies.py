"""
Download all dependencies for offline builds.

Run this script once on a machine with internet access to populate the vendor/ folder.
Then builds can be done completely offline.

Usage: python download_dependencies.py

Output: vendor/
    ├── python/
    │   ├── python-3.11.7-embed-amd64.zip
    │   └── get-pip.py
    ├── python-packages/
    │   └── *.whl (all wheel files)
    ├── mosquitto/
    │   └── (copy manually or from system install)
    └── dashboard-dist/
        └── (pre-built dashboard - optional)
"""

import os
import sys
import subprocess
import urllib.request
import shutil
from pathlib import Path

# Configuration - keep in sync with build_portable.py
PYTHON_VERSION = "3.11.7"
PYTHON_EMBED_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip"
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"

# Python packages - must match build_portable.py
PYTHON_PACKAGES = [
    "paho-mqtt>=1.6.0",
    "pymodbus>=3.0.0",
    "pyserial>=3.5",
    "numpy>=1.21.0",
    "scipy>=1.7.0",
    "python-dateutil>=2.8.0",
    "psutil>=5.9.0",
    "requests>=2.28.0",
    "opcua>=0.98.0",
    "pycomm3>=1.2.0",
]

# Paths
PROJECT_ROOT = Path(__file__).parent.parent
VENDOR_DIR = PROJECT_ROOT / "vendor"


def log(msg, level="INFO"):
    prefix = {"INFO": "[DOWN]", "WARN": "[WARN]", "ERROR": "[ERROR]", "OK": "[  OK ]"}
    print(f"{prefix.get(level, '[    ]')} {msg}")


def download_file(url, dest, desc=None):
    """Download a file with progress indication."""
    filename = desc or url.split('/')[-1]
    log(f"Downloading {filename}...")
    try:
        urllib.request.urlretrieve(url, dest)
        size_mb = os.path.getsize(dest) / (1024 * 1024)
        log(f"  Downloaded {size_mb:.1f} MB", "OK")
        return True
    except Exception as e:
        log(f"Failed to download {filename}: {e}", "ERROR")
        return False


def download_python_embed():
    """Download Python embeddable package."""
    log("Downloading Python embeddable...")
    python_dir = VENDOR_DIR / "python"
    python_dir.mkdir(parents=True, exist_ok=True)

    # Download embedded Python zip
    zip_path = python_dir / f"python-{PYTHON_VERSION}-embed-amd64.zip"
    if zip_path.exists():
        log(f"  Already exists: {zip_path.name}")
    else:
        if not download_file(PYTHON_EMBED_URL, str(zip_path), f"Python {PYTHON_VERSION}"):
            return False

    # Download get-pip.py
    pip_path = python_dir / "get-pip.py"
    if pip_path.exists():
        log(f"  Already exists: {pip_path.name}")
    else:
        if not download_file(GET_PIP_URL, str(pip_path)):
            return False

    return True


def download_python_packages():
    """Download Python packages as wheels."""
    log("Downloading Python packages...")
    packages_dir = VENDOR_DIR / "python-packages"
    packages_dir.mkdir(parents=True, exist_ok=True)

    # Create requirements file for pip download
    req_file = packages_dir / "requirements.txt"
    req_file.write_text("\n".join(PYTHON_PACKAGES))

    # Download wheels for Windows x64
    log("  Downloading wheels for Windows x64...")
    result = subprocess.run(
        [
            sys.executable, "-m", "pip", "download",
            "-r", str(req_file),
            "-d", str(packages_dir),
            "--platform", "win_amd64",
            "--python-version", "3.11",
            "--only-binary", ":all:",
        ],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        # Some packages might not have wheels, try with source
        log("  Some wheels not available, trying with source packages...", "WARN")
        result = subprocess.run(
            [
                sys.executable, "-m", "pip", "download",
                "-r", str(req_file),
                "-d", str(packages_dir),
            ],
            capture_output=True,
            text=True
        )

    # Count downloaded packages
    wheels = list(packages_dir.glob("*.whl"))
    tarballs = list(packages_dir.glob("*.tar.gz"))
    total = len(wheels) + len(tarballs)

    if total > 0:
        log(f"  Downloaded {len(wheels)} wheels, {len(tarballs)} source packages", "OK")
        return True
    else:
        log("  No packages downloaded!", "ERROR")
        print(result.stderr)
        return False


def download_npm_packages():
    """Cache npm packages for offline dashboard build."""
    log("Caching npm packages...")
    dashboard_dir = PROJECT_ROOT / "dashboard"

    if not dashboard_dir.exists():
        log("  Dashboard directory not found!", "WARN")
        return False

    # Check if node_modules exists
    node_modules = dashboard_dir / "node_modules"
    if not node_modules.exists():
        log("  Running npm install to populate node_modules...")
        result = subprocess.run(
            "npm install",
            shell=True,
            cwd=dashboard_dir,
            capture_output=True
        )
        if result.returncode != 0:
            log("  npm install failed!", "ERROR")
            print(result.stderr.decode())
            return False

    # Create npm cache in vendor
    npm_cache = VENDOR_DIR / "npm-cache"
    npm_cache.mkdir(parents=True, exist_ok=True)

    # Copy package-lock.json for reproducible builds
    lock_file = dashboard_dir / "package-lock.json"
    if lock_file.exists():
        shutil.copy(lock_file, npm_cache / "package-lock.json")
        log("  Cached package-lock.json", "OK")

    # Option: Create npm tarball cache
    log("  Creating npm offline cache...")
    result = subprocess.run(
        f'npm cache clean --force && npm cache add --cache "{npm_cache}" .',
        shell=True,
        cwd=dashboard_dir,
        capture_output=True
    )

    log("  npm packages cached", "OK")
    return True


def prebuild_dashboard():
    """Pre-build dashboard for fully offline deployment."""
    log("Pre-building dashboard (optional)...")
    dashboard_dir = PROJECT_ROOT / "dashboard"

    if not dashboard_dir.exists():
        log("  Dashboard directory not found!", "WARN")
        return False

    # Run npm build
    log("  Running npm run build...")
    result = subprocess.run(
        "npm run build",
        shell=True,
        cwd=dashboard_dir,
        capture_output=True
    )

    if result.returncode != 0:
        log("  npm build failed!", "WARN")
        print(result.stderr.decode())
        return False

    # Copy built dashboard to vendor
    dashboard_dist = dashboard_dir / "dist"
    vendor_dist = VENDOR_DIR / "dashboard-dist"

    if dashboard_dist.exists():
        if vendor_dist.exists():
            shutil.rmtree(vendor_dist)
        shutil.copytree(dashboard_dist, vendor_dist)
        log("  Dashboard pre-built and cached", "OK")
        return True

    return False


def setup_mosquitto():
    """Setup Mosquitto in vendor folder."""
    log("Setting up Mosquitto...")
    mosquitto_dir = VENDOR_DIR / "mosquitto"
    mosquitto_dir.mkdir(parents=True, exist_ok=True)

    # Check system installation
    system_mosquitto = Path("C:/Program Files/mosquitto")

    if system_mosquitto.exists() and (system_mosquitto / "mosquitto.exe").exists():
        log("  Found system Mosquitto, copying...")

        files_to_copy = [
            "mosquitto.exe",
            "mosquitto.dll",
            "mosquitto_dynamic_security.dll",
            "libcrypto-3-x64.dll",
            "libssl-3-x64.dll",
            "mosquitto_passwd.exe",
        ]

        copied = 0
        for filename in files_to_copy:
            src = system_mosquitto / filename
            if src.exists():
                shutil.copy(src, mosquitto_dir / filename)
                copied += 1

        log(f"  Copied {copied} Mosquitto files", "OK")
        return True
    else:
        log("  System Mosquitto not found", "WARN")
        log("  Download from: https://mosquitto.org/download/", "WARN")
        log(f"  Copy mosquitto.exe and DLLs to: {mosquitto_dir}", "WARN")

        # Create placeholder README
        readme = mosquitto_dir / "README.txt"
        readme.write_text("""Mosquitto MQTT Broker

Download Mosquitto from: https://mosquitto.org/download/

Copy these files here:
- mosquitto.exe
- mosquitto.dll
- mosquitto_dynamic_security.dll (optional)
- libcrypto-3-x64.dll
- libssl-3-x64.dll
- mosquitto_passwd.exe (optional)
""")
        return False


def setup_nssm():
    """Setup NSSM (Non-Sucking Service Manager) in vendor folder."""
    log("Setting up NSSM...")
    nssm_dir = VENDOR_DIR / "nssm"
    nssm_dir.mkdir(parents=True, exist_ok=True)

    nssm_exe = nssm_dir / "nssm.exe"

    if nssm_exe.exists():
        log("  NSSM already present", "OK")
        return True

    # Try to download NSSM
    nssm_url = "https://nssm.cc/release/nssm-2.24.zip"
    zip_path = nssm_dir / "nssm.zip"

    log("  Downloading NSSM 2.24...")
    if download_file(nssm_url, str(zip_path), "NSSM"):
        import zipfile
        with zipfile.ZipFile(zip_path, 'r') as zf:
            # Extract just the 64-bit exe
            for name in zf.namelist():
                if name.endswith('win64/nssm.exe'):
                    with zf.open(name) as src, open(nssm_exe, 'wb') as dst:
                        dst.write(src.read())
                    break
        zip_path.unlink()  # Remove zip after extraction

        if nssm_exe.exists():
            log("  NSSM extracted successfully", "OK")
            return True

    # Fallback: create README with download instructions
    log("  NSSM download failed", "WARN")
    log("  Download from: https://nssm.cc/download", "WARN")
    log(f"  Copy nssm.exe (64-bit) to: {nssm_dir}", "WARN")

    readme = nssm_dir / "README.txt"
    readme.write_text("""NSSM - Non-Sucking Service Manager

Download from: https://nssm.cc/download

Extract and copy nssm.exe (from the win64 folder) here.
""")
    return False


def create_manifest():
    """Create a manifest of all vendored dependencies."""
    log("Creating manifest...")

    manifest = {
        "python_version": PYTHON_VERSION,
        "packages": PYTHON_PACKAGES,
        "files": []
    }

    # List all files in vendor
    for path in VENDOR_DIR.rglob("*"):
        if path.is_file():
            rel_path = path.relative_to(VENDOR_DIR)
            size = path.stat().st_size
            manifest["files"].append({
                "path": str(rel_path),
                "size": size
            })

    # Write manifest
    import json
    manifest_path = VENDOR_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    log(f"  Manifest created with {len(manifest['files'])} files", "OK")


def main():
    print()
    print("=" * 60)
    print("       ICCSFlux Dependency Downloader")
    print("=" * 60)
    print()
    print(f"  Vendor directory: {VENDOR_DIR}")
    print()

    # Create vendor directory
    VENDOR_DIR.mkdir(parents=True, exist_ok=True)

    success = True

    # Download Python
    if not download_python_embed():
        success = False
    print()

    # Download Python packages
    if not download_python_packages():
        success = False
    print()

    # Cache npm packages
    download_npm_packages()
    print()

    # Pre-build dashboard
    prebuild_dashboard()
    print()

    # Setup Mosquitto
    setup_mosquitto()
    print()

    # Setup NSSM
    setup_nssm()
    print()

    # Create manifest
    create_manifest()

    # Calculate total size
    total_size = sum(f.stat().st_size for f in VENDOR_DIR.rglob('*') if f.is_file())
    size_mb = total_size / (1024 * 1024)

    print()
    print("=" * 60)
    if success:
        log("Dependencies downloaded successfully!", "OK")
    else:
        log("Some downloads failed - check warnings above", "WARN")
    print()
    print(f"  Vendor folder: {VENDOR_DIR}")
    print(f"  Total size:    {size_mb:.1f} MB")
    print()
    print("  Next steps:")
    print("  1. Verify Mosquitto files are in vendor/mosquitto/")
    print("  2. Run: python scripts/build_portable.py --offline")
    print("=" * 60)
    print()

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
