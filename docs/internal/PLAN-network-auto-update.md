# Network Drive Auto-Update System

## Overview

Allow multiple portable ICCSFlux instances across a plant network to detect and apply software updates from a shared network drive, without interrupting active acquisition.

## User Flow

1. Developer builds portable package on dev machine
2. Drops build folder on network drive (e.g. `\\server\ICCSFlux-Updates\`)
3. Running instances poll that folder, compare `VERSION.txt`
4. Dashboard shows orange **"Update Available"** badge in control bar
5. Operator chooses when to apply:
   - Click "Update Now" (graceful stop → swap → restart)
   - Click "Update After Stop" (auto-applies when acquisition ends)
   - Dismiss (ignore this version)

## Components

### 1. Backend: `update_checker.py`

- Background thread, polls configurable UNC path every N minutes
- Compares remote `VERSION.txt` hash/version against local `VERSION.txt`
- Publishes to MQTT: `nisystem/system/update_available` with payload:
  ```json
  {
    "available": true,
    "current_version": "abc1234",
    "remote_version": "def5678",
    "remote_path": "\\\\server\\ICCSFlux-Updates",
    "changelog": "...",
    "timestamp": 1234567890
  }
  ```
- Handles network drive unavailable gracefully (log warning, skip, retry next interval)

### 2. Backend: `update_executor.py`

- Listens for MQTT command: `nisystem/system/apply_update`
- **Pre-stage**: Copy new build from network drive → local `_update_staging/` folder (can happen while acquiring)
- **Graceful stop**: Stop acquisition → flush recording buffers → close files → audit log entry
- **Swap**: Rename `ICCSFlux-Portable/` → `ICCSFlux-Portable.backup/`, rename `_update_staging/` → `ICCSFlux-Portable/`
- **Restart**: Launch new `ICCSFlux.exe`, exit old process
- **Rollback**: If new version fails to start within 30s, swap back to backup
- **Auto-apply mode**: If configured, automatically apply when acquisition stops

### 3. Config Settings

Add to system/project config:

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `update_path` | string | `""` | UNC path to check (empty = disabled) |
| `update_check_interval_min` | int | `5` | Polling interval in minutes |
| `auto_update_on_idle` | bool | `false` | Auto-apply when not acquiring |

### 4. Frontend: Dashboard UI

- **Orange badge** in control bar (same style as "modified" indicator)
- **Update dialog** on click:
  - Current version vs available version
  - Changelog (if `CHANGELOG.txt` exists on network drive)
  - Buttons: "Update Now" / "Update After Stop" / "Dismiss"
- **Progress indicator** during update (Copying... Stopping... Swapping... Restarting...)
- **Auto-reconnect** after restart (~10s WebSocket reconnect)

### 5. Build Changes

- `build_portable.py` already writes `VERSION.txt` with git hash + timestamp
- Add optional `CHANGELOG.txt` alongside `VERSION.txt` on network drive
- Version comparison uses git hash (exact match = no update needed)

## Safety Considerations

- Never interrupt active acquisition without operator consent
- Preserve `config/`, `data/`, `projects/` during swap (only replace executables + dashboard)
- Keep one backup version for rollback
- Audit trail entry for every update (who, when, from-version, to-version)
- If network drive goes offline mid-copy, abort cleanly (don't leave partial staging)

## File Layout on Network Drive

```
\\server\ICCSFlux-Updates\
├── VERSION.txt          # git hash + build timestamp
├── CHANGELOG.txt        # optional, human-readable
└── ICCSFlux-Portable/   # the full build
    ├── ICCSFlux.exe
    ├── mosquitto/
    ├── dashboard/
    └── ...
```
