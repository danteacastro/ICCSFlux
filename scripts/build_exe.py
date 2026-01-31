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
from pathlib import Path
import argparse

# Paths
PROJECT_ROOT = Path(__file__).parent.parent
BUILD_DIR = PROJECT_ROOT / "dist" / "ICCSFlux-Portable"
EXE_DIR = PROJECT_ROOT / "dist" / "exe"
VENDOR_DIR = PROJECT_ROOT / "vendor"
SPEC_DIR = PROJECT_ROOT / "scripts"

# Spec files for PyInstaller
SPEC_FILES = {
    "DAQService": SPEC_DIR / "daq_service.spec",
    "ICCSFlux": SPEC_DIR / "iccsflux.spec",
}


def log(msg, level="INFO"):
    prefix = {"INFO": "[BUILD]", "WARN": "[WARN]", "ERROR": "[ERROR]", "OK": "[  OK ]"}
    print(f"{prefix.get(level, '[    ]')} {msg}")


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


def setup_mosquitto():
    """Copy Mosquitto MQTT broker from vendor directory."""
    log("Setting up Mosquitto MQTT broker...")

    mosquitto_vendor = VENDOR_DIR / "mosquitto"
    if not mosquitto_vendor.exists():
        log("Mosquitto not found in vendor/. Download it first.", "ERROR")
        return False

    mosquitto_dest = BUILD_DIR / "mosquitto"
    mosquitto_dest.mkdir(exist_ok=True)

    # Copy mosquitto files
    for file in ["mosquitto.exe", "mosquitto.conf"]:
        src = mosquitto_vendor / file
        if src.exists():
            shutil.copy2(src, mosquitto_dest / file)

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
    """Set up Azure IoT Hub uploader with its own Python environment.

    Azure uploader needs paho-mqtt 1.x (not 2.x like main system),
    so it runs in a separate Python environment.
    """
    import zipfile

    log("Setting up Azure IoT Hub Uploader...")

    azure_src = PROJECT_ROOT / "services" / "azure_uploader"
    if not azure_src.exists():
        log("Azure uploader source not found, skipping", "WARN")
        return True

    azure_dest = BUILD_DIR / "azure_uploader"
    azure_dest.mkdir(exist_ok=True)
    python_dest = azure_dest / "python"

    # Check for pre-built Azure Python environment in vendor
    azure_python_vendor = VENDOR_DIR / "azure-python"

    if azure_python_vendor.exists():
        # Use pre-built Azure Python from vendor
        log("  Using pre-built Azure Python environment...")
        shutil.copytree(azure_python_vendor, python_dest, dirs_exist_ok=True)
    else:
        # Extract embedded Python and install Azure packages
        python_vendor = VENDOR_DIR / "python"
        if not python_vendor.exists():
            log("  No embedded Python found for Azure uploader", "WARN")
            log("  Azure IoT Hub streaming will not be available", "WARN")
            return True

        # Find and extract the embeddable Python zip
        python_zip = None
        for f in python_vendor.glob("python-*.zip"):
            python_zip = f
            break

        if not python_zip:
            log("  No embedded Python zip found in vendor/python/", "WARN")
            return True

        log(f"  Extracting {python_zip.name}...")
        python_dest.mkdir(exist_ok=True)
        with zipfile.ZipFile(python_zip, 'r') as zf:
            zf.extractall(python_dest)

        python_exe = python_dest / "python.exe"
        if not python_exe.exists():
            log("  python.exe not found after extraction", "ERROR")
            return False

        # Enable pip for embedded Python by modifying python311._pth
        # (embeddable Python has pip disabled by default)
        pth_files = list(python_dest.glob("python*._pth"))
        for pth_file in pth_files:
            content = pth_file.read_text()
            if "#import site" in content:
                log("  Enabling pip support in embedded Python...")
                content = content.replace("#import site", "import site")
                pth_file.write_text(content)

        # Install pip using get-pip.py
        get_pip = python_vendor / "get-pip.py"
        if get_pip.exists():
            log("  Installing pip...")
            try:
                subprocess.run(
                    [str(python_exe), str(get_pip), "--no-warn-script-location"],
                    capture_output=True,
                    check=True
                )
            except subprocess.CalledProcessError as e:
                log(f"  Failed to install pip: {e.stderr.decode() if e.stderr else e}", "WARN")
                return True

        # Install Azure-compatible packages
        azure_packages = VENDOR_DIR / "azure-packages"
        if azure_packages.exists():
            log("  Installing Azure packages...")
            try:
                subprocess.run(
                    [
                        str(python_exe), "-m", "pip", "install",
                        "--no-index",
                        f"--find-links={azure_packages}",
                        "paho-mqtt",
                        "azure-iot-device",
                        "--no-warn-script-location"
                    ],
                    capture_output=True,
                    check=True
                )
                log("  Azure packages installed successfully")
            except subprocess.CalledProcessError as e:
                stderr = e.stderr.decode() if e.stderr else str(e)
                log(f"  Failed to install Azure packages: {stderr}", "WARN")

    # Copy Azure uploader service script
    azure_service = azure_src / "azure_uploader_service.py"
    if azure_service.exists():
        shutil.copy2(azure_service, azure_dest / "azure_uploader_service.py")

    log("Azure uploader ready", "OK")
    return True


def copy_executables():
    """Copy compiled executables to build directory."""
    log("Copying executables...")

    for name in SPEC_FILES.keys():
        exe_src = EXE_DIR / f"{name}.exe"
        if exe_src.exists():
            shutil.copy2(exe_src, BUILD_DIR / f"{name}.exe")
            log(f"  Copied {name}.exe")
        else:
            log(f"  {name}.exe not found!", "ERROR")
            return False

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
        ignore=shutil.ignore_patterns('*.log', '*.tmp')
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

    user_docs = [
        ("USER_GUIDE.md", "01_Getting_Started.md"),
        ("ICCSFlux_Quick_Reference.md", "02_Quick_Reference.md"),
        ("ICCSFlux_User_Manual.md", "03_User_Manual.md"),
        ("ICCSFlux_Python_Scripting_Guide.md", "04_Python_Scripting.md"),
        ("Remote_Node_Setup.md", "05_Remote_Nodes.md"),
        ("ICCSFlux_Administrator_Guide.md", "06_Administrator_Guide.md"),
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

    # Main launcher
    bat_content = '''@echo off
cd /d "%~dp0"
start "" "ICCSFlux.exe"
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
echo [1/4] Installing Mosquitto MQTT Broker...
nssm\\nssm.exe install ICCSFlux-MQTT "%~dp0mosquitto\\mosquitto.exe" -c "%~dp0config\\mosquitto.conf"
nssm\\nssm.exe set ICCSFlux-MQTT AppDirectory "%~dp0mosquitto"
nssm\\nssm.exe set ICCSFlux-MQTT Description "ICCSFlux MQTT Broker"
nssm\\nssm.exe set ICCSFlux-MQTT Start SERVICE_AUTO_START
nssm\\nssm.exe set ICCSFlux-MQTT AppStdout "%~dp0data\\logs\\mosquitto.log"
nssm\\nssm.exe set ICCSFlux-MQTT AppStderr "%~dp0data\\logs\\mosquitto.log"
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
echo     Done.

echo.
echo [3/4] Installing Azure IoT Hub Uploader...
if exist "%~dp0azure_uploader\\python\\python.exe" (
    nssm\\nssm.exe install ICCSFlux-Azure "%~dp0azure_uploader\\python\\python.exe" "%~dp0azure_uploader\\azure_uploader_service.py" --host localhost --port 1883
    nssm\\nssm.exe set ICCSFlux-Azure AppDirectory "%~dp0azure_uploader"
    nssm\\nssm.exe set ICCSFlux-Azure Description "ICCSFlux Azure IoT Hub Uploader"
    nssm\\nssm.exe set ICCSFlux-Azure Start SERVICE_AUTO_START
    nssm\\nssm.exe set ICCSFlux-Azure DependOnService ICCSFlux-MQTT
    nssm\\nssm.exe set ICCSFlux-Azure AppStdout "%~dp0data\\logs\\azure_uploader.log"
    nssm\\nssm.exe set ICCSFlux-Azure AppStderr "%~dp0data\\logs\\azure_uploader.log"
    echo     Done.
) else (
    echo     Skipped - Azure uploader not installed
)

echo.
echo [4/4] Installing Dashboard Web Server...
nssm\\nssm.exe install ICCSFlux-Web "%~dp0ICCSFlux.exe"
nssm\\nssm.exe set ICCSFlux-Web AppDirectory "%~dp0"
nssm\\nssm.exe set ICCSFlux-Web Description "ICCSFlux Dashboard Web Server"
nssm\\nssm.exe set ICCSFlux-Web Start SERVICE_AUTO_START
nssm\\nssm.exe set ICCSFlux-Web DependOnService ICCSFlux-DAQ
nssm\\nssm.exe set ICCSFlux-Web AppStdout "%~dp0data\\logs\\web_server.log"
nssm\\nssm.exe set ICCSFlux-Web AppStderr "%~dp0data\\logs\\web_server.log"
echo     Done.

echo.
echo ============================================================
echo Starting services...
net start ICCSFlux-MQTT
timeout /t 2 /nobreak >nul
net start ICCSFlux-DAQ
timeout /t 2 /nobreak >nul
if exist "%~dp0azure_uploader\\python\\python.exe" net start ICCSFlux-Azure
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


def create_readme():
    """Create README file."""
    readme = '''ICCSFlux - Industrial Data Acquisition
======================================

Quick Start:
  1. Double-click ICCSFlux.bat to start
  2. Dashboard opens automatically at http://localhost:5173

Files:
  ICCSFlux.exe     - Main launcher (starts all services)
  DAQService.exe   - Data acquisition service
  ICCSFlux.bat     - Simple batch launcher

For Windows Service:
  Run Install-Service.bat (as Administrator)

Documentation:
  See the docs/ folder for user guides.

Support:
  Contact your system administrator.
'''
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

    if not check_prerequisites():
        return 1

    clean_build()

    print()
    if not build_dashboard():
        return 1

    print()
    if not compile_executables(quick_mode=args.quick):
        return 1

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
    create_readme()

    size_mb = get_build_size()

    print()
    print("=" * 60)
    log("Build complete!", "OK")
    print()
    print(f"  Output: {BUILD_DIR}")
    print(f"  Size:   {size_mb:.1f} MB")
    print()
    print("  To run: Double-click ICCSFlux.bat")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
