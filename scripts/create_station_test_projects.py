"""Generate station test projects for cDAQ-9189-DHWSIM multi-project testing.

Creates two projects that split the DHWSIM chassis by channel range,
sharing modules (realistic scenario — same module, different channels):

  Project A — "Zone 1"
    Mod1 ch0-7   (8 TCs)
    Mod2 ch0-7   (8 voltage inputs)
    Mod3 ch0-3   (4 current inputs)
    Mod4 ch0-7   (8 DI)
    Mod6 ch0-7   (8 AO)
    = 36 channels

  Project B — "Zone 2"
    Mod1 ch8-15  (8 TCs)
    Mod2 ch8-15  (8 voltage inputs)
    Mod3 ch4-7   (4 current inputs)
    Mod4 ch8-15  (8 DI)
    Mod5 ch0-15  (16 DO — only B controls outputs)
    Mod6 ch8-15  (8 AO)
    = 52 channels

Both projects share Mod1, Mod2, Mod3, Mod4, and Mod6 but use DIFFERENT
channels on each module (no physical channel conflicts). This exercises:
- Shared-module concurrent acquisition from one hardware reader
- Per-project channel isolation on the same module
- Union channel set across shared modules
- Per-project alarm/safety evaluation
- No conflicts despite shared modules

Run:
  python scripts/create_station_test_projects.py
"""

import json
from datetime import datetime
from pathlib import Path


def make_project(name, system_id, channels, alarms=None):
    """Build a minimal project JSON."""
    return {
        "type": "nisystem-project",
        "version": "2.0",
        "name": name,
        "created": datetime.now().isoformat(),
        "modified": datetime.now().isoformat(),
        "system": {
            "mqtt_broker": "localhost",
            "mqtt_port": 1883,
            "mqtt_base_topic": "nisystem",
            "scan_rate_hz": 10,
            "publish_rate_hz": 4,
            "simulation_mode": True,
            "log_directory": "./logs",
            "system_name": name,
            "system_id": system_id,
            "device_name": "cDAQ-9189-DHWSIM",
            "datalog_rate_ms": 1000,
        },
        "service": {
            "heartbeat_interval_sec": 2,
            "health_timeout_sec": 10,
            "shutdown_timeout_sec": 10,
            "command_ack_timeout_sec": 5,
        },
        "channels": channels,
        "alarms": alarms or {},
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
            },
            "selectedChannels": list(channels.keys()),
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


CH = "cDAQ-9189-DHWSIM"


def make_channel(name, phys, ctype, unit, group, desc,
                 tc_type=None, chartable=True):
    return {
        "name": name,
        "physical_channel": phys,
        "channel_type": ctype,
        "unit": unit,
        "group": group,
        "description": desc,
        "visible": True,
        "chartable": chartable,
        "log": True,
        "log_interval_ms": 1000,
        "low_limit": None,
        "high_limit": None,
        "low_warning": None,
        "high_warning": None,
        "scale_slope": 1,
        "scale_offset": 0,
        "scale_type": "none",
        "four_twenty_scaling": False,
        "eng_units_min": None,
        "eng_units_max": None,
        "pre_scaled_min": None,
        "pre_scaled_max": None,
        "scaled_min": None,
        "scaled_max": None,
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


# =========================================================================
# PROJECT A — Thermal & Analog Zone 1
#   Mod1 ch0-7   (first 8 TCs)
#   Mod2 ch0-7   (first 8 voltage inputs)
#   Mod3 ch0-3   (first 4 current inputs)
#   Mod4 ch0-7   (first 8 DI)
#   Mod6 ch0-7   (first 8 AO)
# =========================================================================

proj_a_channels = {}

# Mod1: NI 9213 — first 8 TC channels
for i in range(8):
    name = f"TC_M1_ch{i:02d}"
    proj_a_channels[name] = make_channel(
        name, f"{CH}Mod1/ai{i}",
        "thermocouple", "degC", "Mod1_TC",
        f"NI 9213 Slot 1 — TC ch{i}", tc_type="K",
    )

# Mod2: NI 9205 — first 8 voltage channels
for i in range(8):
    name = f"AI_M2_ch{i:02d}"
    proj_a_channels[name] = make_channel(
        name, f"{CH}Mod2/ai{i}",
        "voltage_input", "V", "Mod2_AI",
        f"NI 9205 Slot 2 — Voltage ch{i}",
    )

# Mod3: NI 9203 — first 4 current channels
for i in range(4):
    name = f"CI_M3_ch{i:02d}"
    proj_a_channels[name] = make_channel(
        name, f"{CH}Mod3/ai{i}",
        "current_input", "mA", "Mod3_CI",
        f"NI 9203 Slot 3 — Current ch{i}",
    )

# Mod4: NI 9375 — first 8 DI
for i in range(8):
    name = f"DI_M4_ch{i:02d}"
    proj_a_channels[name] = make_channel(
        name, f"{CH}Mod4/port0/line{i}",
        "digital_input", "", "Mod4_DI",
        f"NI 9375 Slot 4 — DI line{i}", chartable=False,
    )

# Mod6: NI 9264 — first 8 AO
for i in range(8):
    name = f"AO_M6_ch{i:02d}"
    proj_a_channels[name] = make_channel(
        name, f"{CH}Mod6/ao{i}",
        "voltage_output", "V", "Mod6_AO",
        f"NI 9264 Slot 6 — AO ch{i}",
    )

proj_a_alarms = {
    "TC_M1_ch00_Hi": {
        "name": "TC_M1_ch00_Hi",
        "channel": "TC_M1_ch00",
        "type": "Hi",
        "setpoint": 500,
        "deadband": 5,
        "severity": "WARNING",
        "enabled": True,
    },
}

project_a = make_project(
    "Station Test — Zone 1",
    "STATION-TEST-A",
    proj_a_channels,
    proj_a_alarms,
)

# =========================================================================
# PROJECT B — Thermal & Analog Zone 2
#   Mod1 ch8-15  (last 8 TCs)
#   Mod2 ch8-15  (last 8 voltage inputs)
#   Mod3 ch4-7   (last 4 current inputs)
#   Mod4 ch8-15  (last 8 DI)
#   Mod5 ch0-15  (all 16 DO — only Project B controls outputs)
#   Mod6 ch8-15  (last 8 AO)
# =========================================================================

proj_b_channels = {}

# Mod1: NI 9213 — last 8 TC channels
for i in range(8, 16):
    name = f"TC_M1_ch{i:02d}"
    proj_b_channels[name] = make_channel(
        name, f"{CH}Mod1/ai{i}",
        "thermocouple", "degC", "Mod1_TC",
        f"NI 9213 Slot 1 — TC ch{i}", tc_type="K",
    )

# Mod2: NI 9205 — last 8 voltage channels
for i in range(8, 16):
    name = f"AI_M2_ch{i:02d}"
    proj_b_channels[name] = make_channel(
        name, f"{CH}Mod2/ai{i}",
        "voltage_input", "V", "Mod2_AI",
        f"NI 9205 Slot 2 — Voltage ch{i}",
    )

# Mod3: NI 9203 — last 4 current channels
for i in range(4, 8):
    name = f"CI_M3_ch{i:02d}"
    proj_b_channels[name] = make_channel(
        name, f"{CH}Mod3/ai{i}",
        "current_input", "mA", "Mod3_CI",
        f"NI 9203 Slot 3 — Current ch{i}",
    )

# Mod4: NI 9375 — last 8 DI
for i in range(8, 16):
    name = f"DI_M4_ch{i:02d}"
    proj_b_channels[name] = make_channel(
        name, f"{CH}Mod4/port0/line{i}",
        "digital_input", "", "Mod4_DI",
        f"NI 9375 Slot 4 — DI line{i}", chartable=False,
    )

# Mod5: NI 9375 — all 16 DO (only B controls outputs)
for i in range(16):
    name = f"DO_M5_ch{i:02d}"
    proj_b_channels[name] = make_channel(
        name, f"{CH}Mod5/port0/line{i}",
        "digital_output", "", "Mod5_DO",
        f"NI 9375 Slot 5 — DO line{i}", chartable=False,
    )

# Mod6: NI 9264 — last 8 AO
for i in range(8, 16):
    name = f"AO_M6_ch{i:02d}"
    proj_b_channels[name] = make_channel(
        name, f"{CH}Mod6/ao{i}",
        "voltage_output", "V", "Mod6_AO",
        f"NI 9264 Slot 6 — AO ch{i}",
    )

project_b = make_project(
    "Station Test — Zone 2",
    "STATION-TEST-B",
    proj_b_channels,
)

# =========================================================================
# Write project files
# =========================================================================

out_dir = Path(__file__).parent.parent / "config" / "projects"
out_dir.mkdir(parents=True, exist_ok=True)

for filename, proj in [
    ("_StationTest_Zone1.json", project_a),
    ("_StationTest_Zone2.json", project_b),
]:
    path = out_dir / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(proj, f, indent=2)
    ch_count = len(proj["channels"])
    groups = {}
    for n, c in proj["channels"].items():
        groups.setdefault(c["group"], []).append(n)
    print(f"Created: {filename}")
    print(f"  Channels: {ch_count}")
    for g in sorted(groups):
        print(f"    {g}: {len(groups[g])}")
