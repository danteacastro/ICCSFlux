"""
Build ICCSFlux as compiled Windows executables using PyInstaller.

This creates a self-contained folder with native .exe files that can run
on any Windows PC without installing Python, Node.js, or Mosquitto system-wide.

Usage:
    python build_exe.py           # Build with PyInstaller compilation
    python build_exe.py --quick   # Skip recompilation if .exe exists

Output: dist/ICCSFlux-Portable/

Requirements:
- Python 3.8+ with PyInstaller installed
- Node.js + npm (to build the dashboard)
- All Python dependencies installed (for PyInstaller to bundle)
"""

import os
import sys
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

# Spec files for PyInstaller (built from main venv)
SPEC_FILES = {
    "DAQService": SPEC_DIR / "daq_service.spec",
    "ICCSFlux": SPEC_DIR / "iccsflux.spec",
}

# Azure spec (built from isolated venv with paho-mqtt 1.x)
AZURE_SPEC = ("AzureUploader", SPEC_DIR / "azure_uploader.spec")


def log(msg, level="INFO"):
    prefix = {"INFO": "[BUILD]", "WARN": "[WARN]", "ERROR": "[ERROR]", "OK": "[  OK ]"}
    print(f"{prefix.get(level, '[    ]')} {msg}")


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
        try:
            shutil.rmtree(BUILD_DIR)
        except PermissionError as e:
            log(f"Could not fully clean build dir: {e}", "WARN")
            log("Trying to clean individual files...", "WARN")
            # Try to at least clean what we can
            for item in BUILD_DIR.iterdir():
                if item.is_file():
                    try:
                        item.unlink()
                    except PermissionError:
                        pass
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

    if config_dest.exists():
        shutil.rmtree(config_dest)

    shutil.copytree(
        config_src,
        config_dest,
        ignore=shutil.ignore_patterns(
            '*.log', '*.tmp',
            'mqtt_credentials.json',  # Auto-generated at runtime
            'mosquitto_passwd',       # Auto-generated at runtime
            'mosquitto_secure.conf',  # Superseded by mosquitto.conf
        )
    )

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
            shutil.rmtree(dashboard_dest)
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
    """Create simple batch file launchers."""
    log("Creating launchers...")

    # Main launcher - improved with error handling
    bat_content = '''@echo off
title ICCSFlux
cd /d "%~dp0"

REM Check if ICCSFlux.exe exists
if not exist "ICCSFlux.exe" (
    echo.
    echo ERROR: ICCSFlux.exe not found!
    echo.
    echo Make sure you're running this from the ICCSFlux-Portable folder.
    echo.
    pause
    exit /b 1
)

REM Start ICCSFlux
echo.
echo Starting ICCSFlux...
echo.
echo Dashboard will open at: http://localhost:5173
echo Press Ctrl+C to stop
echo.

ICCSFlux.exe

REM If ICCSFlux exits with error, pause so user can see the error
if errorlevel 1 (
    echo.
    echo ICCSFlux exited with an error.
    echo Check data\\logs\\ for details.
    echo.
    pause
)
'''
    (BUILD_DIR / "ICCSFlux.bat").write_text(bat_content)

    # Service install script - installs all services
    service_install = '''@echo off
cd /d "%~dp0"
echo ============================================================
echo    ICCSFlux Windows Service Installation
echo ============================================================
echo.
echo This will install ICCSFlux as Windows services:
echo   - ICCSFlux-MQTT   (Mosquitto MQTT broker)
echo   - ICCSFlux-DAQ    (Data acquisition service)
echo   - ICCSFlux-Azure  (Azure IoT Hub uploader)
echo   - ICCSFlux-Web    (Dashboard web server)
echo.
echo NOTE: Run this script as Administrator!
echo.
pause

echo.
echo [0/4] Setting up MQTT credentials...
"%~dp0ICCSFlux.exe" --setup
echo     Done.

echo.
echo [1/4] Installing Mosquitto MQTT Broker...
nssm\\nssm.exe install ICCSFlux-MQTT "%~dp0mosquitto\\mosquitto.exe" -c "%~dp0config\\mosquitto.conf"
nssm\\nssm.exe set ICCSFlux-MQTT AppDirectory "%~dp0"
nssm\\nssm.exe set ICCSFlux-MQTT Description "ICCSFlux MQTT Broker"
nssm\\nssm.exe set ICCSFlux-MQTT Start SERVICE_AUTO_START
nssm\\nssm.exe set ICCSFlux-MQTT AppStdout "%~dp0data\\logs\\mosquitto.log"
nssm\\nssm.exe set ICCSFlux-MQTT AppStderr "%~dp0data\\logs\\mosquitto.log"
nssm\\nssm.exe set ICCSFlux-MQTT AppRotateFiles 1
nssm\\nssm.exe set ICCSFlux-MQTT AppRotateBytes 10485760
REM Auto-restart on failure (industrial-grade reliability)
nssm\\nssm.exe set ICCSFlux-MQTT AppExit Default Restart
nssm\\nssm.exe set ICCSFlux-MQTT AppRestartDelay 5000
nssm\\nssm.exe set ICCSFlux-MQTT AppThrottle 10000
echo     Done.

echo.
echo [2/4] Installing DAQ Service...
nssm\\nssm.exe install ICCSFlux-DAQ "%~dp0DAQService.exe" -c "%~dp0config\\system.ini"
nssm\\nssm.exe set ICCSFlux-DAQ AppDirectory "%~dp0"
nssm\\nssm.exe set ICCSFlux-DAQ Description "ICCSFlux Data Acquisition"
nssm\\nssm.exe set ICCSFlux-DAQ Start SERVICE_AUTO_START
nssm\\nssm.exe set ICCSFlux-DAQ DependOnService ICCSFlux-MQTT
nssm\\nssm.exe set ICCSFlux-DAQ AppStdout "%~dp0data\\logs\\daq_service.log"
nssm\\nssm.exe set ICCSFlux-DAQ AppStderr "%~dp0data\\logs\\daq_service.log"
nssm\\nssm.exe set ICCSFlux-DAQ AppRotateFiles 1
nssm\\nssm.exe set ICCSFlux-DAQ AppRotateBytes 10485760
REM Auto-restart on failure (industrial-grade reliability)
nssm\\nssm.exe set ICCSFlux-DAQ AppExit Default Restart
nssm\\nssm.exe set ICCSFlux-DAQ AppRestartDelay 5000
nssm\\nssm.exe set ICCSFlux-DAQ AppThrottle 10000
echo     Done.

echo.
echo [3/4] Installing Azure IoT Hub Uploader...
if exist "%~dp0AzureUploader.exe" (
    nssm\\nssm.exe install ICCSFlux-Azure "%~dp0AzureUploader.exe" --host localhost --port 1883
    nssm\\nssm.exe set ICCSFlux-Azure AppDirectory "%~dp0"
    nssm\\nssm.exe set ICCSFlux-Azure Description "ICCSFlux Azure IoT Hub Uploader"
    nssm\\nssm.exe set ICCSFlux-Azure Start SERVICE_AUTO_START
    nssm\\nssm.exe set ICCSFlux-Azure DependOnService ICCSFlux-MQTT
    nssm\\nssm.exe set ICCSFlux-Azure AppStdout "%~dp0data\\logs\\azure_uploader.log"
    nssm\\nssm.exe set ICCSFlux-Azure AppStderr "%~dp0data\\logs\\azure_uploader.log"
    nssm\\nssm.exe set ICCSFlux-Azure AppRotateFiles 1
    nssm\\nssm.exe set ICCSFlux-Azure AppRotateBytes 10485760
    REM Auto-restart on failure (industrial-grade reliability)
    nssm\\nssm.exe set ICCSFlux-Azure AppExit Default Restart
    nssm\\nssm.exe set ICCSFlux-Azure AppRestartDelay 5000
    nssm\\nssm.exe set ICCSFlux-Azure AppThrottle 10000
    echo     Done.
) else (
    echo     Skipped - Azure uploader not installed
)

echo.
echo [4/4] Installing Dashboard Web Server...
nssm\\nssm.exe install ICCSFlux-Web "%~dp0ICCSFlux.exe" --no-browser
nssm\\nssm.exe set ICCSFlux-Web AppDirectory "%~dp0"
nssm\\nssm.exe set ICCSFlux-Web Description "ICCSFlux Dashboard Web Server"
nssm\\nssm.exe set ICCSFlux-Web Start SERVICE_AUTO_START
nssm\\nssm.exe set ICCSFlux-Web DependOnService ICCSFlux-DAQ
nssm\\nssm.exe set ICCSFlux-Web AppStdout "%~dp0data\\logs\\web_server.log"
nssm\\nssm.exe set ICCSFlux-Web AppStderr "%~dp0data\\logs\\web_server.log"
nssm\\nssm.exe set ICCSFlux-Web AppRotateFiles 1
nssm\\nssm.exe set ICCSFlux-Web AppRotateBytes 10485760
REM Auto-restart on failure (industrial-grade reliability)
nssm\\nssm.exe set ICCSFlux-Web AppExit Default Restart
nssm\\nssm.exe set ICCSFlux-Web AppRestartDelay 5000
nssm\\nssm.exe set ICCSFlux-Web AppThrottle 10000
echo     Done.

echo.
echo ============================================================
echo Starting services...
net start ICCSFlux-MQTT
timeout /t 2 /nobreak >nul
net start ICCSFlux-DAQ
timeout /t 2 /nobreak >nul
if exist "%~dp0AzureUploader.exe" net start ICCSFlux-Azure
timeout /t 1 /nobreak >nul
net start ICCSFlux-Web
echo.
echo ============================================================
echo All services installed and started!
echo.
echo Dashboard: http://localhost:5173
echo ============================================================
pause
'''
    (BUILD_DIR / "Install-Service.bat").write_text(service_install)

    # Service uninstall script
    service_uninstall = '''@echo off
cd /d "%~dp0"
echo ============================================================
echo    ICCSFlux Windows Service Removal
echo ============================================================
echo.
echo This will remove all ICCSFlux Windows services.
echo NOTE: Run this script as Administrator!
echo.
pause

echo.
echo Stopping services...
net stop ICCSFlux-Web 2>nul
net stop ICCSFlux-Azure 2>nul
net stop ICCSFlux-DAQ 2>nul
net stop ICCSFlux-MQTT 2>nul

echo.
echo Removing services...
nssm\\nssm.exe remove ICCSFlux-Web confirm
nssm\\nssm.exe remove ICCSFlux-Azure confirm 2>nul
nssm\\nssm.exe remove ICCSFlux-DAQ confirm
nssm\\nssm.exe remove ICCSFlux-MQTT confirm

echo.
echo ============================================================
echo All ICCSFlux services removed.
echo ============================================================
pause
'''
    (BUILD_DIR / "Uninstall-Service.bat").write_text(service_uninstall)

    log("Launchers created", "OK")
    return True


def create_readme(version: dict = None):
    """Create README file with optional build version info."""
    readme = '''ICCSFlux Portable - Industrial Data Acquisition System
=========================================================

QUICK START
-----------
1. Double-click ICCSFlux.bat
2. Dashboard opens automatically at http://localhost:5173
3. Press Ctrl+C in the console window to stop

WHAT'S INCLUDED
---------------
ICCSFlux.exe        - Main launcher (8 MB)
DAQService.exe      - Data acquisition backend (24 MB)
AzureUploader.exe   - Azure IoT Hub integration (11 MB)

mosquitto/          - MQTT broker for messaging
www/                - Dashboard web interface
config/             - Configuration files
data/               - Runtime data, logs, recordings

RUNNING OPTIONS
---------------

Option 1: Interactive Mode (recommended for testing)
  - Double-click: ICCSFlux.bat
  - Shows startup messages
  - Opens browser automatically
  - Press Ctrl+C to stop

Option 2: Windows Services (recommended for production)
  - Run as Administrator: Install-Service.bat
  - Services auto-start on boot
  - Run even when logged out
  - Auto-restart on failure

  To uninstall services:
  - Run as Administrator: Uninstall-Service.bat

SERVICES INSTALLED
------------------
When using Install-Service.bat, you get 4 Windows services:

  ICCSFlux-MQTT   - MQTT broker (port 1883, 9001)
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
  - Verify ports 1883, 5173, 9001 are not in use
  - Run Install-Service.bat as Administrator

Problem: Dashboard not loading
  - Check if ICCSFlux.exe is running
  - Try http://localhost:5173 directly in browser
  - Check data/logs/web_server.log

Problem: Port conflicts
  - Default ports: 1883 (MQTT), 5173 (Dashboard), 9001 (MQTT WebSocket)
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

    clean_build()

    print()
    if not build_dashboard():
        return 1

    print()
    if not compile_executables(quick_mode=args.quick):
        return 1

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

    size_mb = get_build_size()
    dirty = " (dirty)" if version["git_dirty"] else ""

    print()
    print("=" * 60)
    log("Build complete!", "OK")
    print()
    print(f"  Output:  {BUILD_DIR}")
    print(f"  Size:    {size_mb:.1f} MB")
    print(f"  Version: {version['git_hash_short']}{dirty}")
    print(f"  Built:   {version['build_time']}")
    print()
    print("  To run: Double-click ICCSFlux.bat")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
