# NISystem Project Instructions

## Architecture Overview

- **Backend**: Python DAQ service (`services/daq_service/daq_service.py`, ~13k lines) — reads NI hardware (or simulation), publishes over MQTT
- **Frontend**: Vue 3 + TypeScript dashboard (`dashboard/`) — connects via WebSocket to MQTT
- **Broker**: Mosquitto MQTT — TCP 1883 (authenticated, for services + cRIO) and WebSocket 9002 (localhost-only, anonymous, for dashboard)
- **cRIO**: Python node (`services/crio_node_v2/`) deployed to NI cRIO hardware over SSH
- **Azure**: Separate `AzureUploader` exe uploads to Azure IoT Hub (external process, not part of main DAQ service)
- **Portable build**: PyInstaller compiles to `dist/ICCSFlux-Portable/` — runs on any Windows PC without Python/Node installed

## Running .bat Files (Claude Code)

This project runs on Windows. The Bash tool uses a Unix-style shell, so `.bat` files must be invoked via PowerShell:

```powershell
powershell.exe -NoProfile -Command "Set-Location 'c:\Users\User\Documents\Projects\NISystem'; & '.\venv\Scripts\python.exe' scripts\build_exe.py 2>&1"
```

General pattern for running any `.bat` or Windows command and capturing output:

```powershell
powershell.exe -NoProfile -Command "<commands here> 2>&1"
```

Do NOT use `cmd.exe /c` — it often swallows output. Do NOT call `.bat` files directly — they are not recognized by the Unix shell. Use PowerShell for all Windows-specific invocations.

## Portable Build

```cmd
build.bat                    # Full build (requires PyInstaller, npm, vendor/mosquitto)
python scripts/build_exe.py  # Direct invocation (preferred from Claude Code — see above)
```

- Azure uploader builds in an **isolated venv** (`build/azure-venv/`) because it requires paho-mqtt <2.0 while the main project uses paho-mqtt >=2.0
- Offline builds use `--no-index --find-links vendor/azure-packages/` — no internet required
- `scripts/download_dependencies.py` populates `vendor/` with all offline dependencies
- Build output includes `VERSION.txt` with git hash, branch, and timestamp

## cRIO Deployment

**ALWAYS use `deploy_crio_v2.bat` when deploying changes to the cRIO.**

```cmd
deploy_crio_v2.bat [crio_host] [broker_host]
```

Default values:
- crio_host: 192.168.1.20
- broker_host: 192.168.1.1

**DO NOT manually scp individual files** — use the deploy script to ensure all files are deployed together and the service is properly restarted.

## Device CLI

Use `device.bat` for device management operations (NOT for starting services):
- `device scan` — Discover devices
- `device deploy crio --host <ip> -r` — Deploy to cRIO
- `device logs crio --host <ip> -f` — Follow cRIO logs

The DAQ service runs on the PC and is started separately (not via device.bat).

## cRIO Hardware Notes

- cRIO modules require DIFFERENTIAL terminal configuration (not RSE)
- Use `TerminalConfiguration.DEFAULT` to let DAQmx auto-select
- Thermocouple channels need `channel_type == 'thermocouple'` check before using thermocouple setup

## MQTT Security Decisions

- Port 1883 binds to 0.0.0.0 (NOT 127.0.0.1) — required for cRIO communication over USB Ethernet
- Authentication + ACL is enforced on TCP listener — credentials auto-generated at first run
- TLS is not enabled — acceptable because traffic stays on isolated plant network or direct USB Ethernet link
- WebSocket 9002 is localhost-only and anonymous — dashboard uses app-level auth (useAuth.ts)
- Data only leaves the machine via Azure IoT Hub (HTTPS) or local SQL Server — never through MQTT

## Script Sandbox

User scripts run via `exec()` with AST-based validation (not process isolation). The sandbox blocks:
- All imports and `__import__`
- Dangerous dunders (`__subclasses__`, `__globals__`, `__code__`, `__mro__`, etc.)
- Dangerous builtins (`eval`, `exec`, `compile`, `open`, `getattr`, `vars`, `dir`, `globals`, `locals`)
- Module access (`os`, `sys`, `subprocess`, `ctypes`, `socket`, etc.)
- `type()` is removed from safe_builtins (prevents `type([]).__bases__[0].__subclasses__()` escape)

Both `services/daq_service/script_manager.py` and `services/crio_node_v2/script_engine.py` share the same blocked lists — keep them in sync when modifying.

## Testing

- **Unit tests**: `python -m pytest tests/test_daq_orchestration.py` — 68 tests, no external deps required
- **Integration tests**: `python -m pytest tests/` — requires running MQTT broker + DAQ service on localhost
- Test helpers in `tests/test_helpers.py` (MQTTTestHarness)
- Dashboard must pass `vue-tsc` strict type checking before build (`npm run build` in `dashboard/`)

## Key Design Decisions

- DAQ service uses a **state machine** (`state_machine.py`) for acquisition lifecycle: STOPPED → INITIALIZING → RUNNING → STOPPING → STOPPED
- Critical MQTT commands (acquire start/stop, recording, session, safe-state) use **per-topic callbacks** that bypass the command queue for low latency
- Recording uses **OS-level file locking** (msvcrt on Windows, fcntl on Unix) and **fsync after flush** for crash safety
- Admin password is written to `data/initial_admin_password.txt` (chmod 600), never logged to console
- Script code payloads are limited to 256 KB, script names to 256 chars
