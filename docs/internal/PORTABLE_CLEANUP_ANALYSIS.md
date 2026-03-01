# ICCSFlux Portable - Size Optimization Analysis

## Current Size: ~327 MB

### Breakdown by Component:
- **python/** - 249 MB (main Python environment)
- **azure_uploader/** - 50 MB (Azure Python environment)
- **www/** - 16 MB (dashboard - needed)
- **mosquitto/** - 6.3 MB (MQTT broker - needed)
- **services/** - 4.1 MB (backend services - needed)
- **config/** - 1.5 MB (configuration - needed)
- **nssm/** - 324 KB (service manager - needed)
- **docs/** - 164 KB (documentation - needed)
- **launcher/** - 8 KB (utilities - needed)

---

## OPTIMIZATION OPPORTUNITIES

### 1. Remove pip and setuptools (~44 MB savings)
**Status:** Not needed at runtime

Both Python environments include pip and setuptools:
- Main Python: 13 MB (pip) + 8.8 MB (setuptools) = 21.8 MB
- Azure Python: 13 MB (pip) + 8.8 MB (setuptools) = 21.8 MB
- **Total savings: ~44 MB**

These are only needed during build to install packages. After build completes, they serve no purpose.

**Action:** Delete after building:
```
dist/ICCSFlux-Portable/python/Lib/site-packages/pip/
dist/ICCSFlux-Portable/python/Lib/site-packages/setuptools/
dist/ICCSFlux-Portable/python/Scripts/pip*.exe
dist/ICCSFlux-Portable/azure_uploader/python/Lib/site-packages/pip/
dist/ICCSFlux-Portable/azure_uploader/python/Lib/site-packages/setuptools/
dist/ICCSFlux-Portable/azure_uploader/python/Scripts/pip*.exe
```

### 2. Remove test directories (~20-30 MB savings)
**Status:** Not needed in production

Numpy and scipy include extensive test suites:
- numpy/_core/tests - 8 MB
- numpy/lib/tests - 2.3 MB
- numpy (other test dirs) - ~5 MB
- scipy (various test dirs) - ~10-15 MB
- Other packages - ~3 MB
- **Total savings: ~25-30 MB**

**Action:** Delete all `tests/` and `testing/` directories:
```bash
find dist/ICCSFlux-Portable -type d -name "tests" -exec rm -rf {} +
find dist/ICCSFlux-Portable -type d -name "test" -exec rm -rf {} +
find dist/ICCSFlux-Portable -type d -name "testing" -exec rm -rf {} +
```

### 3. Remove distlib stub executables (~1.5 MB savings)
**Status:** Not needed (pip vendor stubs)

These are bundled with pip and only used for creating Python executables:
- 6 .exe files in pip/_vendor/distlib/ per Python environment
- **Total savings: ~1.5 MB**

**Action:** Delete (but only after removing pip itself)

### 4. Remove setuptools CLI stubs (~1 MB savings)
**Status:** Not needed at runtime

Setuptools includes CLI stub executables:
- cli-32.exe, cli-64.exe, cli-arm64.exe, cli.exe
- gui-32.exe, gui-64.exe, gui-arm64.exe, gui.exe
- **Total savings: ~1 MB**

**Action:** Delete (but only after removing setuptools itself)

### 5. Clean up Python bytecode cache (~5-10 MB savings)
**Status:** Regenerated on first run

281 `__pycache__` directories containing .pyc files:
- **Estimated savings: ~5-10 MB**

**Note:** These will be regenerated on first run, so this is optional.

**Action:**
```bash
find dist/ICCSFlux-Portable -type d -name "__pycache__" -exec rm -rf {} +
find dist/ICCSFlux-Portable -name "*.pyc" -delete
```

### 6. Remove wheel package (~1 MB savings per env)
**Status:** Only needed for pip install

The `wheel` package is only used by pip for installing .whl files.
- **Total savings: ~1-2 MB**

**Action:** Delete after build:
```
dist/ICCSFlux-Portable/python/Lib/site-packages/wheel/
dist/ICCSFlux-Portable/python/Scripts/wheel.exe
dist/ICCSFlux-Portable/azure_uploader/python/Lib/site-packages/wheel/
dist/ICCSFlux-Portable/azure_uploader/python/Scripts/wheel.exe
```

---

## REQUIRED EXECUTABLES

### Root Directory:
- `ICCSFlux.bat` - Main launcher
- `ICCSFlux.py` - Main launcher script
- `ICCSFlux-Hidden.vbs` - Background launcher
- `ICCSFlux-Service.bat` - Service manager
- `Start-Background.bat` - Quick start
- `Stop-ICCSFlux.bat` - Quick stop
- `Install-AutoStart.bat` - Auto-start installer
- `Uninstall-AutoStart.bat` - Auto-start remover
- `Install-Service.bat` - Windows service installer
- `Uninstall-Service.bat` - Windows service remover
- `README.txt` - User documentation

### Python Environment:
- `python/python.exe` - Python interpreter (REQUIRED)
- `python/pythonw.exe` - Python without console (REQUIRED)
- `python/*.pyd` - Extension modules (REQUIRED)
- `python/*.dll` - Runtime libraries (REQUIRED)
- `python/Lib/` - Standard library (REQUIRED)
- `python/Lib/site-packages/` - Installed packages (REQUIRED, except pip/setuptools)
- ~~`python/Scripts/pip*.exe`~~ - NOT NEEDED after build
- ~~`python/Scripts/wheel.exe`~~ - NOT NEEDED after build
- `python/Scripts/f2py.exe` - Numpy Fortran compiler (MAY BE NEEDED)
- `python/Scripts/httpx.exe` - HTTPX CLI (MAY BE NEEDED)
- `python/Scripts/pymodbus.simulator.exe` - Modbus simulator (MAY BE NEEDED)
- `python/Scripts/pyserial-*.exe` - Serial port tools (MAY BE NEEDED)
- `python/Scripts/numpy-config.exe` - Numpy config (MAY BE NEEDED)

### Azure Uploader Environment:
- `azure_uploader/python/python.exe` - Python interpreter (REQUIRED)
- `azure_uploader/python/pythonw.exe` - Python without console (REQUIRED)
- `azure_uploader/python/*.pyd` - Extension modules (REQUIRED)
- `azure_uploader/python/*.dll` - Runtime libraries (REQUIRED)
- `azure_uploader/python/Lib/` - Standard library (REQUIRED)
- `azure_uploader/python/Lib/site-packages/` - Installed packages (REQUIRED, except pip/setuptools)
- ~~`azure_uploader/python/Scripts/pip*.exe`~~ - NOT NEEDED after build
- ~~`azure_uploader/python/Scripts/wheel.exe`~~ - NOT NEEDED after build
- `azure_uploader/python/Scripts/normalizer.exe` - Unicode normalizer (PROBABLY NOT NEEDED)

### Mosquitto:
- `mosquitto/mosquitto.exe` - MQTT broker (REQUIRED)
- `mosquitto/mosquitto_passwd.exe` - Password utility (REQUIRED)
- `mosquitto/*.dll` - Runtime libraries (REQUIRED)
- `mosquitto/mosquitto.conf` - Configuration (REQUIRED)

### NSSM:
- `nssm/nssm.exe` - Service manager (REQUIRED for Windows service mode)

### Other Directories:
- `services/` - Backend services (REQUIRED)
- `config/` - Configuration files (REQUIRED)
- `www/` - Dashboard (REQUIRED)
- `data/` - Runtime data directory (REQUIRED)
- `docs/` - User documentation (REQUIRED)
- `launcher/` - Launcher utilities (REQUIRED)

---

## RECOMMENDED CLEANUP SCRIPT

### Total Estimated Savings: ~70-80 MB (25-30% reduction)

After build completes, run this cleanup:

```bash
cd dist/ICCSFlux-Portable

# Remove pip and setuptools (44 MB)
rm -rf python/Lib/site-packages/pip/
rm -rf python/Lib/site-packages/setuptools/
rm -rf python/Lib/site-packages/pkg_resources/
rm -f python/Scripts/pip*.exe

rm -rf azure_uploader/python/Lib/site-packages/pip/
rm -rf azure_uploader/python/Lib/site-packages/setuptools/
rm -rf azure_uploader/python/Lib/site-packages/pkg_resources/
rm -f azure_uploader/python/Scripts/pip*.exe

# Remove wheel (2 MB)
rm -rf python/Lib/site-packages/wheel/
rm -f python/Scripts/wheel.exe
rm -rf azure_uploader/python/Lib/site-packages/wheel/
rm -f azure_uploader/python/Scripts/wheel.exe

# Remove test directories (25-30 MB)
find . -type d -name "tests" -exec rm -rf {} + 2>/dev/null
find . -type d -name "test" -exec rm -rf {} + 2>/dev/null
find . -type d -name "testing" -exec rm -rf {} + 2>/dev/null

# Remove .dist-info metadata (optional, ~5 MB)
# NOTE: Some tools check these, so be careful
# find . -type d -name "*.dist-info" -exec rm -rf {} + 2>/dev/null

# Remove pycache (optional, ~5-10 MB, will regenerate)
# find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
# find . -name "*.pyc" -delete
```

---

## FINAL STRUCTURE SHOULD BE:

```
ICCSFlux-Portable/
├── ICCSFlux.bat                    # Main launcher
├── ICCSFlux.py                     # Launcher script
├── ICCSFlux-Hidden.vbs             # Background launcher
├── ICCSFlux-Service.bat            # Service manager
├── Start-Background.bat            # Quick start
├── Stop-ICCSFlux.bat               # Quick stop
├── Install-AutoStart.bat           # Auto-start installer
├── Uninstall-AutoStart.bat         # Auto-start remover
├── Install-Service.bat             # Service installer
├── Uninstall-Service.bat           # Service remover
├── README.txt                      # Documentation
│
├── python/                         # Main Python (~180 MB after cleanup)
│   ├── python.exe
│   ├── pythonw.exe
│   ├── *.pyd, *.dll
│   ├── Lib/
│   └── Scripts/                    # Only keep utility scripts, not pip
│
├── azure_uploader/                 # Azure Python (~25 MB after cleanup)
│   ├── python/
│   ├── azure_uploader_service.py
│   └── azure_uploader.ini.example
│
├── mosquitto/                      # MQTT broker (6.3 MB)
│   ├── mosquitto.exe
│   ├── mosquitto_passwd.exe
│   ├── *.dll
│   └── mosquitto.conf
│
├── nssm/                           # Service manager (324 KB)
│   └── nssm.exe
│
├── services/                       # Backend services (4.1 MB)
├── config/                         # Configuration (1.5 MB)
├── www/                            # Dashboard (16 MB)
├── data/                           # Runtime data (empty initially)
├── docs/                           # User docs (164 KB)
└── launcher/                       # Utilities (8 KB)
```

**Final size estimate:** ~250-260 MB (down from 327 MB)
