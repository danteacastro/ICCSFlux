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

# The portable bundle uses the EMBEDDED interpreter above, which may differ from
# the Python running this downloader. Wheels MUST be pinned to that target or
# C-extension packages (numpy, scipy, lxml, cryptography...) silently refuse to
# install into the embed. Keep these in sync with PYTHON_VERSION.
WHEEL_PLATFORM = "win_amd64"
WHEEL_PY_VERSION = "3.11"

# Python packages with binary wheels for the embed target.
# MUST match PYTHON_PACKAGES in build_portable.py.
PYTHON_PACKAGES = [
    "paho-mqtt>=2.0.0",
    "numpy>=1.21.0",
    "scipy>=1.7.0",
    "python-dateutil>=2.8.0",
    "psutil>=5.9.0",
    "bcrypt>=4.0.0",
    "pymodbus>=3.0.0",
    "pyserial>=3.5",
    "pycomm3>=1.2.0",
    "requests>=2.28.0",
    "httpx>=0.24.0",
]

# Packages that ship ONLY as a source dist (no wheel on PyPI). We build a wheel
# locally so they install offline without needing build backends from PyPI.
# opcua is pure-Python, so the built wheel is portable to the embed.
PYTHON_SOURCE_PACKAGES = [
    "opcua>=0.98.0",
]

# Binary-wheel dependencies of the source packages above that must also be
# vendored for the embed (opcua needs lxml/pytz; cryptography enables OPC-UA
# security/encryption).
PYTHON_SOURCE_DEPS = [
    "lxml",
    "pytz",
    "cryptography>=41.0.0",
]

# Azure IoT packages (separate venv due to paho-mqtt 1.x requirement).
# azure-iot-device has wheels; paho-mqtt<2 (1.6.x) is source-only -> built below.
AZURE_PACKAGES = [
    "azure-iot-device>=2.12.0",
]
AZURE_SOURCE_PACKAGES = [
    "paho-mqtt>=1.6.0,<2.0.0",
]

# DLLs that mosquitto.exe (2.x) requires at startup. If any of these is absent
# from the bundle the broker dies immediately with a "<dll> was not found"
# system-error dialog. Used to validate the vendor copy and the final build.
REQUIRED_MOSQUITTO_DLLS = [
    "mosquitto.dll",
    "libcrypto-3-x64.dll",
    "libssl-3-x64.dll",
    "cjson.dll",
    "libmicrohttpd-dll.dll",
    "pthreadVC3.dll",
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

def download_wheels(packages, dest, desc, find_links=None):
    """Download binary wheels pinned to the embed target (win_amd64 / 3.11).

    Pinning is mandatory: this script may run under a different Python than the
    one being bundled, so an unpinned download would fetch incompatible wheels.
    We deliberately do NOT fall back to an unconstrained download.

    find_links lets the resolver satisfy a dependency from a locally built wheel
    (e.g. a source-only package built earlier) so the rest of the graph can be
    fetched as binaries.
    """
    if not packages:
        return True
    log(f"  Downloading {desc} wheels for {WHEEL_PLATFORM} / py{WHEEL_PY_VERSION}...")
    cmd = [
        sys.executable, "-m", "pip", "download",
        *packages,
        "-d", str(dest),
        "--platform", WHEEL_PLATFORM,
        "--python-version", WHEEL_PY_VERSION,
        "--only-binary", ":all:",
    ]
    if find_links:
        cmd += ["--find-links", str(find_links)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log(f"  Failed to download {desc} wheels", "ERROR")
        print(result.stderr)
        return False
    return True


def build_source_wheels(packages, dest, desc):
    """Build wheels locally for source-only packages so they install offline.

    These packages have no wheel on PyPI; without a pre-built wheel, an offline
    `pip install` would try to fetch build backends from PyPI and fail. The
    packages here are pure-Python, so the locally built wheel is portable.
    """
    if not packages:
        return True
    for pkg in packages:
        log(f"  Building wheel for {desc} package: {pkg}")
        result = subprocess.run(
            [
                sys.executable, "-m", "pip", "wheel",
                pkg, "--no-deps",
                "-w", str(dest),
            ],
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            log(f"  Failed to build wheel for {pkg}", "ERROR")
            print(result.stderr)
            return False
    return True


def download_python_packages():
    """Download/build all main Python packages as wheels for the embed target."""
    log("Downloading Python packages...")
    packages_dir = VENDOR_DIR / "python-packages"
    packages_dir.mkdir(parents=True, exist_ok=True)

    # Record the intended package set for reference.
    req_file = packages_dir / "requirements.txt"
    req_file.write_text("\n".join(PYTHON_PACKAGES + PYTHON_SOURCE_PACKAGES))

    ok = download_wheels(
        PYTHON_PACKAGES + PYTHON_SOURCE_DEPS, packages_dir, "Python"
    )
    ok = build_source_wheels(PYTHON_SOURCE_PACKAGES, packages_dir, "Python") and ok

    wheels = list(packages_dir.glob("*.whl"))
    tarballs = list(packages_dir.glob("*.tar.gz"))

    if ok and wheels:
        log(f"  Downloaded {len(wheels)} wheels, {len(tarballs)} source packages", "OK")
        return True
    else:
        log("  Python package download incomplete!", "ERROR")
        return False

def download_azure_packages():
    """Download Azure IoT packages (paho-mqtt 1.x + azure-iot-device) into separate directory."""
    log("Downloading Azure IoT packages...")
    azure_dir = VENDOR_DIR / "azure-packages"
    azure_dir.mkdir(parents=True, exist_ok=True)

    # paho-mqtt 1.6.x is source-only -> build a wheel FIRST so it installs
    # offline AND so the resolver below can satisfy azure-iot-device's
    # paho-mqtt<2 dependency from this local wheel.
    ok = build_source_wheels(AZURE_SOURCE_PACKAGES, azure_dir, "Azure IoT")
    # Pin to the embed target like the main packages: the Azure uploader runs on
    # its own copy of the SAME embedded Python, so wheels must be cp311/win_amd64.
    # Pass the source packages too so the resolver pins them to the local wheel.
    ok = download_wheels(
        AZURE_PACKAGES + AZURE_SOURCE_PACKAGES, azure_dir, "Azure IoT",
        find_links=azure_dir,
    ) and ok

    wheels = list(azure_dir.glob("*.whl"))
    tarballs = list(azure_dir.glob("*.tar.gz"))
    total = len(wheels) + len(tarballs)
    if ok and wheels:
        log(f"  Downloaded {total} packages ({len(wheels)} wheels, {len(tarballs)} source)", "OK")
        return True
    log("  Azure package download incomplete!", "ERROR")
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

    # Run the portable build (Vite only). The default `npm run build` also runs
    # `vue-tsc` type-checking, which aborts on pre-existing type errors that do
    # not affect the runtime bundle. build:portable skips that gate.
    log("  Running npm run build:portable...")
    result = subprocess.run(
        "npm run build:portable",
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

        # Copy EVERY .exe and .dll from the system install. Mosquitto 2.x links
        # mosquitto.exe against a growing set of DLLs (cjson, libmicrohttpd,
        # pthreadVC3, sqlite3, ...) that varies by version. A hardcoded file
        # list silently drops the new ones and the broker fails to start with
        # "<dll> was not found". Globbing is version-proof.
        copied = 0
        for src in [*system_mosquitto.glob("*.exe"), *system_mosquitto.glob("*.dll")]:
            shutil.copy(src, mosquitto_dir / src.name)
            copied += 1

        # Sanity-check that mosquitto.exe's critical runtime DLLs made it in.
        missing = [d for d in REQUIRED_MOSQUITTO_DLLS
                   if not (mosquitto_dir / d).exists()]
        if missing:
            log(f"  Mosquitto copied but missing critical DLLs: {', '.join(missing)}", "WARN")
            log("  Update your system Mosquitto install or copy these manually.", "WARN")

        log(f"  Copied {copied} Mosquitto files", "OK")
        return not missing
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

    # Download Azure IoT packages (separate due to paho-mqtt version conflict)
    if not download_azure_packages():
        log("Azure packages download failed (Azure IoT Hub feature will be unavailable)", "WARN")
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
