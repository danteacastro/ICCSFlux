"""Generate a cDAQ-9189-DHWSIM soak test project for 72-hour terminal testing.

Maps all 6 modules in the DHWSIM chassis:
  Mod1: NI 9213 — 16-ch Thermocouple (K-type)
  Mod2: NI 9205 — 32 SE / 16 DIFF Voltage Input
  Mod3: NI 9203 — 8-ch ±20 mA Current Input
  Mod4: NI 9375 — 16 DI
  Mod5: NI 9375 — 16 DO
  Mod6: NI 9264 — 16-ch ±10 V Analog Output

Run:
  python scripts/create_dhwsim_soak_project.py
"""

import json
import uuid
from datetime import datetime
from pathlib import Path


def wid():
    return str(uuid.uuid4())[:8]


CH = "cDAQ-9189-DHWSIM"

project = {
    "type": "nisystem-project",
    "version": "2.0",
    "name": "DHWSIM 72h Soak Test",
    "created": datetime.now().isoformat(),
    "modified": datetime.now().isoformat(),
    "system": {
        "mqtt_broker": "localhost",
        "mqtt_port": 1883,
        "mqtt_base_topic": "nisystem",
        "scan_rate_hz": 10,
        "publish_rate_hz": 4,
        "simulation_mode": False,
        "log_directory": "./logs",
        "system_name": "DHWSIM 72h Soak Test",
        "system_id": "DHWSIM-SOAK-001",
        "device_name": "cDAQ-9189-DHWSIM",
        "datalog_rate_ms": 1000,
    },
    "service": {
        "heartbeat_interval_sec": 2,
        "health_timeout_sec": 10,
        "shutdown_timeout_sec": 10,
        "command_ack_timeout_sec": 5,
    },
    "channels": {},
    "alarms": {},
    "interlocks": [],
    "pythonScripts": {},
    "calculatedParams": [],
    "sequences": [],
    "triggers": [],
    "pidLoops": [],
    "userVariables": [],
    "recording": {
        "config": {
            "format": "csv",
            "interval_ms": 1000,
            "rotation_mode": "size",
            "rotation_size_mb": 50,
            "max_files": 100,
        },
        "selectedChannels": [],
    },
    "safety": {
        "alarmConfigs": {},
        "interlocks": [],
        "safetyActions": {},
        "safeStateConfig": {},
        "autoExecuteSafetyActions": False,
    },
    "notebook": {"entries": [], "experiments": []},
    "pages": [],
    "widgets": [],
}


def add_channel(
    name, phys, ctype, unit, group, desc,
    visible=True, chartable=True, log=True,
    tc_type=None, hi=None, lo=None, hiw=None, low=None,
    scale_type="none", four_twenty=False,
    eu_min=None, eu_max=None,
    pre_min=None, pre_max=None, sc_min=None, sc_max=None,
):
    project["channels"][name] = {
        "name": name,
        "physical_channel": phys,
        "channel_type": ctype,
        "unit": unit,
        "group": group,
        "description": desc,
        "visible": visible,
        "chartable": chartable,
        "log": log,
        "log_interval_ms": 1000,
        "low_limit": lo,
        "high_limit": hi,
        "low_warning": low,
        "high_warning": hiw,
        "scale_slope": 1,
        "scale_offset": 0,
        "scale_type": scale_type,
        "four_twenty_scaling": four_twenty,
        "eng_units_min": eu_min,
        "eng_units_max": eu_max,
        "pre_scaled_min": pre_min,
        "pre_scaled_max": pre_max,
        "scaled_min": sc_min,
        "scaled_max": sc_max,
        "thermocouple_type": tc_type,
        "cjc_source": "internal" if tc_type else None,
        "voltage_range": 10,
        "current_range_ma": 20,
        "invert": False,
        "default_state": False,
        "default_value": 0,
        "safety_action": None,
        "safety_interlock": None,
        "source_type": "cdaq",
        "node_id": "",
    }


# =============================================================================
# MODULE 1: NI 9213 — 16-ch Thermocouple (Slot 1)
# =============================================================================
for i in range(16):
    add_channel(
        f"TC_M1_ch{i:02d}",
        f"{CH}Mod1/ai{i}",
        "thermocouple", "degC", "Mod1_TC",
        f"NI 9213 Slot 1 — TC ch{i}",
        tc_type="K",
    )

# =============================================================================
# MODULE 2: NI 9205 — Voltage Inputs (Slot 2), use 16 DIFF channels
# =============================================================================
for i in range(16):
    add_channel(
        f"AI_M2_ch{i:02d}",
        f"{CH}Mod2/ai{i}",
        "voltage_input", "V", "Mod2_AI",
        f"NI 9205 Slot 2 — Voltage ch{i}",
        scale_type="none",
    )

# =============================================================================
# MODULE 3: NI 9203 — 8-ch Current Input (Slot 3)
# =============================================================================
for i in range(8):
    add_channel(
        f"CI_M3_ch{i:02d}",
        f"{CH}Mod3/ai{i}",
        "current_input", "mA", "Mod3_CI",
        f"NI 9203 Slot 3 — Current ch{i}",
    )

# =============================================================================
# MODULE 4: NI 9375 — 16 DI (Slot 4)
# =============================================================================
for i in range(16):
    add_channel(
        f"DI_M4_ch{i:02d}",
        f"{CH}Mod4/port0/line{i}",
        "digital_input", "", "Mod4_DI",
        f"NI 9375 Slot 4 — DI line{i}",
        chartable=False,
    )

# =============================================================================
# MODULE 5: NI 9375 — 16 DO (Slot 5)
# =============================================================================
for i in range(16):
    add_channel(
        f"DO_M5_ch{i:02d}",
        f"{CH}Mod5/port0/line{i}",
        "digital_output", "", "Mod5_DO",
        f"NI 9375 Slot 5 — DO line{i}",
        chartable=False,
    )

# =============================================================================
# MODULE 6: NI 9264 — 16-ch Analog Output (Slot 6)
# =============================================================================
for i in range(16):
    add_channel(
        f"AO_M6_ch{i:02d}",
        f"{CH}Mod6/ao{i}",
        "voltage_output", "V", "Mod6_AO",
        f"NI 9264 Slot 6 — AO ch{i}",
    )

# Auto-select all loggable channels for recording
project["recording"]["selectedChannels"] = [
    name for name, c in project["channels"].items() if c.get("log", True)
]

# =============================================================================
# Alarm configs — canary alarms for soak monitoring
# =============================================================================
# Hi alarm on first TC channel to catch open-circuit / runaway
project["alarms"]["TC_M1_ch00_Hi"] = {
    "name": "TC_M1_ch00_Hi",
    "channel": "TC_M1_ch00",
    "type": "Hi",
    "setpoint": 500,
    "deadband": 5,
    "severity": "WARNING",
    "enabled": True,
}
# LoLo on first TC to catch disconnected sensor
project["alarms"]["TC_M1_ch00_LoLo"] = {
    "name": "TC_M1_ch00_LoLo",
    "channel": "TC_M1_ch00",
    "type": "LoLo",
    "setpoint": -100,
    "deadband": 5,
    "severity": "CRITICAL",
    "enabled": True,
}

# =============================================================================
# Dashboard pages — soak monitoring layout
# =============================================================================

# --- Page 1: Soak Overview ---
p1 = [
    {"id": wid(), "type": "title", "x": 0, "y": 0, "w": 24, "h": 2,
     "label": "DHWSIM 72h Soak Test — Overview", "style": {"fontSize": 18}},
    {"id": wid(), "type": "system_status", "x": 0, "y": 2, "w": 8, "h": 5,
     "label": "System Status"},
    {"id": wid(), "type": "clock", "x": 8, "y": 2, "w": 4, "h": 3,
     "label": "Elapsed"},
    # TC sparklines (first 4 channels)
    {"id": wid(), "type": "sparkline", "x": 12, "y": 2, "w": 3, "h": 3,
     "channel": "TC_M1_ch00", "label": "TC ch0"},
    {"id": wid(), "type": "sparkline", "x": 15, "y": 2, "w": 3, "h": 3,
     "channel": "TC_M1_ch01", "label": "TC ch1"},
    {"id": wid(), "type": "sparkline", "x": 18, "y": 2, "w": 3, "h": 3,
     "channel": "TC_M1_ch02", "label": "TC ch2"},
    {"id": wid(), "type": "sparkline", "x": 21, "y": 2, "w": 3, "h": 3,
     "channel": "TC_M1_ch03", "label": "TC ch3"},
    # Long-duration trend — all 16 TCs
    {"id": wid(), "type": "trend", "x": 0, "y": 7, "w": 24, "h": 9,
     "channels": [f"TC_M1_ch{i:02d}" for i in range(16)],
     "label": "Thermocouple Trend (all 16)", "duration": 3600},
]

# --- Page 2: Analog I/O ---
p2 = [
    {"id": wid(), "type": "title", "x": 0, "y": 0, "w": 24, "h": 2,
     "label": "Analog I/O — Voltage & Current"},
    {"id": wid(), "type": "trend", "x": 0, "y": 2, "w": 12, "h": 7,
     "channels": [f"AI_M2_ch{i:02d}" for i in range(8)],
     "label": "Voltage Inputs ch0-7", "duration": 600},
    {"id": wid(), "type": "trend", "x": 12, "y": 2, "w": 12, "h": 7,
     "channels": [f"AI_M2_ch{i:02d}" for i in range(8, 16)],
     "label": "Voltage Inputs ch8-15", "duration": 600},
    {"id": wid(), "type": "trend", "x": 0, "y": 9, "w": 12, "h": 7,
     "channels": [f"CI_M3_ch{i:02d}" for i in range(8)],
     "label": "Current Inputs (all 8)", "duration": 600},
    {"id": wid(), "type": "trend", "x": 12, "y": 9, "w": 12, "h": 7,
     "channels": [f"AO_M6_ch{i:02d}" for i in range(8)],
     "label": "Analog Outputs ch0-7", "duration": 600},
]

# --- Page 3: Digital I/O ---
p3 = [
    {"id": wid(), "type": "title", "x": 0, "y": 0, "w": 24, "h": 2,
     "label": "Digital I/O Status"},
]
# DI LEDs — 16 channels in 2 rows
for i in range(16):
    row = 2 if i < 8 else 4
    col = (i % 8) * 3
    p3.append({"id": wid(), "type": "led", "x": col, "y": row, "w": 3, "h": 2,
               "channel": f"DI_M4_ch{i:02d}", "label": f"DI {i}"})
# DO toggles — 16 channels in 2 rows
for i in range(16):
    row = 7 if i < 8 else 9
    col = (i % 8) * 3
    p3.append({"id": wid(), "type": "toggle", "x": col, "y": row, "w": 3, "h": 2,
               "channel": f"DO_M5_ch{i:02d}", "label": f"DO {i}",
               "onLabel": "ON", "offLabel": "OFF"})

# --- Page 4: Soak Diagnostics ---
p4 = [
    {"id": wid(), "type": "title", "x": 0, "y": 0, "w": 24, "h": 2,
     "label": "Soak Diagnostics & Recording"},
    {"id": wid(), "type": "system_status", "x": 0, "y": 2, "w": 8, "h": 6,
     "label": "System Health"},
    {"id": wid(), "type": "alarm_summary", "x": 8, "y": 2, "w": 8, "h": 6,
     "label": "Alarm Summary"},
    {"id": wid(), "type": "recording_status", "x": 16, "y": 2, "w": 8, "h": 6,
     "label": "Recording Status"},
    {"id": wid(), "type": "status_messages", "x": 0, "y": 8, "w": 24, "h": 8,
     "label": "System Log"},
]

project["pages"] = [
    {"id": "soak-overview", "name": "Soak Overview", "widgets": p1, "order": 0},
    {"id": "analog-io", "name": "Analog I/O", "widgets": p2, "order": 1},
    {"id": "digital-io", "name": "Digital I/O", "widgets": p3, "order": 2},
    {"id": "diagnostics", "name": "Diagnostics", "widgets": p4, "order": 3},
]

# Flatten widgets for backward compat
project["widgets"] = []
for page in project["pages"]:
    for w in page["widgets"]:
        w["page"] = page["id"]
    project["widgets"].extend(page["widgets"])

# =============================================================================
# Write
# =============================================================================
out_path = Path(__file__).parent.parent / "config" / "projects" / "_DhwSimSoakTest.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(project, f, indent=2)

# Summary
ch_count = len(project["channels"])
groups = {}
for n, c in project["channels"].items():
    groups.setdefault(c["group"], []).append(n)

print(f"Created: {out_path.name}")
print(f"  Channels: {ch_count}")
print(f"  Pages: {len(project['pages'])}")
print(f"  Total widgets: {len(project['widgets'])}")
print(f"  Recording channels: {len(project['recording']['selectedChannels'])}")
print(f"  Alarms: {len(project['alarms'])}")
print()
for g in sorted(groups):
    print(f"  {g}: {len(groups[g])} channels")
for p in project["pages"]:
    print(f'  Page "{p["name"]}": {len(p["widgets"])} widgets')
