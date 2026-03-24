# ICCSFlux Quick Reference Card

## Control Bar

| Button | Function |
|--------|----------|
| **START** | Begin data acquisition |
| **STOP** | End data acquisition |
| **RECORD** | Start/stop data recording |
| **SESSION** | Enable/disable automation |

## Dashboard Tabs

| Tab | Purpose |
|-----|---------|
| Overview | Live dashboard with widgets |
| Config | Channel setup (Operator+) |
| Scripts | Automation (Supervisor+) |
| Data | Recording management (Operator+) |
| Safety | Alarms & interlocks (Supervisor+) |
| Notes | Documentation |
| Admin | User management (Supervisor+) |

## Common Tasks

### Start a Test
1. Click **START** to begin acquisition
2. Verify data is updating on widgets
3. Click **RECORD** when ready to save data
4. Toggle **SESSION** to enable automation

### Stop a Test
1. Click **STOP** to end acquisition
2. Recording stops automatically
3. Data file saved with timestamp

### Acknowledge an Alarm
1. Go to **Safety** tab
2. Find alarm in Active Alarms list
3. Click **Acknowledge** button
4. Enter comment if required

### Add a Widget
1. Click **Edit** to enable edit mode
2. Click **+ Widget** button
3. Select widget type
4. Choose channel if required
5. Click **Add**
6. Drag to position

### Export Data
1. Go to **Data** tab
2. Select recording file
3. Click **Download** or **Export**
4. Choose format (CSV/Excel)

## Script Helper Classes

| Class | Use For |
|-------|---------|
| `Counter(mode='rate')` | Totalizing rate signals (Hz, GPM) |
| `Counter(mode='cumulative')` | Tracking hardware edge counts |
| `RateCalculator(window)` | Rate of change over time window |
| `Accumulator(initial)` | Cumulative totals |
| `EdgeDetector(threshold)` | Rising/falling edge detection |
| `RollingStats(window_size)` | Running mean/min/max/std |
| `Scheduler()` | Timed recurring tasks |
| `StateMachine(initial)` | Sequences and batch recipes |

## Notifications

| Channel | Setup Location |
|---------|---------------|
| SMS (Twilio) | Config → System Settings → SMS Notifications |
| Email (SMTP) | Config → System Settings → Email Notifications |

Filtering: event type → severity → group → alarm selection → cooldown → daily limit → quiet hours

## Alarm Priorities

| Level | Color | Response |
|-------|-------|----------|
| Critical | Red | Immediate action |
| High | Orange | Prompt attention |
| Medium | Yellow | Review soon |
| Low | Blue | Informational |

## Interlock Status

| Status | Meaning |
|--------|---------|
| SATISFIED | All conditions met |
| BLOCKED | Condition(s) failed |
| BYPASSED | Override active |

## User Roles

| Role | Can Do |
|------|--------|
| Guest | View only (monitoring) |
| Operator | Run tests, control outputs, record |
| Supervisor | Edit sequences, safety config |
| Admin | Full access + user management |

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| Ctrl+S | Save project |
| Ctrl+E | Toggle edit mode |
| Escape | Close dialog |
| F5 | Refresh |
| F11 | Fullscreen |

## Physical Channel Formats

| Hardware | Format | Example |
|----------|--------|---------|
| cDAQ | `cDAQ{#}Mod{#}/{type}{#}` | `cDAQ1Mod1/ai0` |
| cRIO | `Mod{#}/{type}{#}` | `Mod1/ai0` |
| Opto22 | `{ioType}/{module}/ch{#}` | `analogInputs/0/ch0` |

## Remote Node Commands

### cRIO Node (SSH to cRIO)

| Command | Description |
|---------|-------------|
| `systemctl status crio_node` | Check service status |
| `journalctl -u crio_node -f` | View live logs |
| `systemctl restart crio_node` | Restart service |
| `./install.sh <PC_IP>` | Install/reinstall |

### Opto22 Node (SSH to groov EPIC)

| Command | Description |
|---------|-------------|
| `systemctl status opto22_node` | Check service status |
| `journalctl -u opto22_node -f` | View live logs |
| `systemctl restart opto22_node` | Restart service |
| `./install.sh <PC_IP>` | Install/reinstall |

## Node Status Indicators

| Color | Meaning |
|-------|---------|
| Green ● | Online (heartbeat OK) |
| Yellow ● | Warning (data may be stale) |
| Red ● | Offline (no heartbeat) |

## Need Help?

- Full manual: `docs/ICCSFlux_User_Manual.md`
- Remote nodes: `docs/ICCSFlux_Remote_Nodes_Guide.md`
- Login: Contact your system administrator for credentials
- Support: Contact your system administrator
