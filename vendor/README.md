# Vendor Dependencies for Offline Builds

This folder contains pre-downloaded dependencies for building ICCSFlux without internet access.

## Folder Structure

```
vendor/
├── python/
│   ├── python-3.11.7-embed-amd64.zip  # Python embeddable
│   └── get-pip.py                      # pip installer
├── python-packages/
│   └── *.whl                           # Python wheel files
├── mosquitto/
│   ├── mosquitto.exe                   # MQTT broker
│   ├── mosquitto.dll
│   └── *.dll                           # Dependencies
├── dashboard-dist/
│   └── (pre-built dashboard files)     # Optional
├── manifest.json                       # Inventory of vendored files
└── README.md                           # This file
```

## Usage

### Populate Dependencies (Internet Required)

Run once on a machine with internet access:

```bash
python scripts/download_dependencies.py
```

This downloads:
- Python 3.11.7 embeddable (~25 MB)
- pip installer
- All Python packages as wheels (~150 MB)
- Pre-builds the dashboard

### Build Offline

Once `vendor/` is populated, build without internet:

```bash
python scripts/build_portable.py --offline
```

## What Gets Downloaded

| Component | Size | Source |
|-----------|------|--------|
| Python embed | ~25 MB | python.org |
| Python packages | ~150 MB | PyPI |
| Dashboard | ~5 MB | npm build |
| Mosquitto | ~5 MB | System or manual |

**Total: ~185 MB**

## Mosquitto

Mosquitto must be obtained separately:
1. Download from https://mosquitto.org/download/
2. Install on a Windows machine
3. Copy these files to `vendor/mosquitto/`:
   - `mosquitto.exe`
   - `mosquitto.dll`
   - `libcrypto-3-x64.dll`
   - `libssl-3-x64.dll`

Or the download script will copy from system installation if available.

## Git Considerations

This folder can be:
- **Committed** to have a fully self-contained repo
- **Ignored** via `.gitignore` to keep repo size small

If ignored, each build machine needs to run `download_dependencies.py` once.

## Updating Dependencies

To update vendored packages:
1. Delete the `vendor/` folder
2. Run `download_dependencies.py` again
3. Commit if tracked

## Package List

Current Python packages:
- paho-mqtt (MQTT client)
- pymodbus (Modbus TCP/RTU)
- pyserial (Serial communication)
- numpy (Scientific computing)
- scipy (Scientific computing)
- python-dateutil (Date utilities)
- psutil (Process utilities)
- requests (HTTP client)
- opcua (OPC-UA client)
- pycomm3 (Allen Bradley EtherNet/IP)
