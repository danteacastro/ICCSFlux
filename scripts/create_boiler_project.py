"""Generate a realistic cDAQ boiler combustion research project file."""
import json
import uuid
from datetime import datetime
from pathlib import Path

def wid():
    return str(uuid.uuid4())[:8]

CH = 'cDAQ-9189-DHWSIM'

project = {
    'type': 'nisystem-project',
    'version': '2.0',
    'name': 'Boiler Combustion Research',
    'created': datetime.now().isoformat(),
    'modified': datetime.now().isoformat(),
    'system': {
        'mqtt_broker': 'localhost',
        'mqtt_port': 1883,
        'mqtt_base_topic': 'nisystem',
        'scan_rate_hz': 10,
        'publish_rate_hz': 4,
        'simulation_mode': False,
        'log_directory': './logs',
        'system_name': 'Boiler Combustion Research',
        'system_id': 'CDAQ-BOILER-001',
        'device_name': 'cDAQ-9189-DHWSIM',
        'datalog_rate_ms': 1000
    },
    'service': {
        'heartbeat_interval_sec': 2,
        'health_timeout_sec': 10,
        'shutdown_timeout_sec': 10,
        'command_ack_timeout_sec': 5
    },
    'channels': {},
    'layout': {
        'gridColumns': 24,
        'rowHeight': 30,
        'pages': [],
        'currentPageId': 'overview'
    },
    'scripts': {
        'calculatedParams': [],
        'sequences': [],
        'schedules': [],
        'alarms': [],
        'transformations': [],
        'triggers': [],
        'pythonScripts': [],
        'functionBlocks': [],
        'drawPatterns': {},
        'watchdogs': [],
        'stateMachines': [],
        'reportTemplates': [],
        'scheduledReports': []
    },
    'recording': {
        'config': {'format': 'csv', 'interval_ms': 1000},
        'selectedChannels': []
    },
    'safety': {
        'alarmConfigs': {},
        'interlocks': [],
        'safetyActions': {},
        'safeStateConfig': {},
        'autoExecuteSafetyActions': False
    },
    'notebook': {'entries': [], 'experiments': []}
}

def add_channel(name, phys, ctype, unit, group, desc, visible=True, chartable=True,
                hi=None, lo=None, hiw=None, low=None,
                scale_type='none', four_twenty=False, eu_min=None, eu_max=None,
                pre_min=None, pre_max=None, sc_min=None, sc_max=None,
                tc_type=None, rtd_type=None, safety_action=None):
    project['channels'][name] = {
        'name': name,
        'physical_channel': phys,
        'channel_type': ctype,
        'unit': unit,
        'group': group,
        'description': desc,
        'visible': visible,
        'low_limit': lo,
        'high_limit': hi,
        'low_warning': low,
        'high_warning': hiw,
        'chartable': chartable,
        'scale_slope': 1,
        'scale_offset': 0,
        'scale_type': scale_type,
        'four_twenty_scaling': four_twenty,
        'eng_units_min': eu_min,
        'eng_units_max': eu_max,
        'pre_scaled_min': pre_min,
        'pre_scaled_max': pre_max,
        'scaled_min': sc_min,
        'scaled_max': sc_max,
        'thermocouple_type': tc_type,
        'rtd_type': rtd_type,
        'cjc_source': 'internal' if tc_type or rtd_type else None,
        'voltage_range': 10,
        'current_range_ma': 20,
        'invert': False,
        'default_state': False,
        'default_value': 0,
        'safety_action': safety_action,
        'safety_interlock': None,
        'log': True,
        'log_interval_ms': 1000,
        'source_type': 'cdaq',
        'node_id': ''
    }

# ===== MODULE 1: NI 9213 - 16-ch Thermocouple (Slot 1) =====
add_channel('TT_101', f'{CH}Mod1/ai0', 'thermocouple', 'degC', 'Combustion', 'Furnace gas temperature', hi=950, hiw=800, tc_type='K')
add_channel('TT_102', f'{CH}Mod1/ai1', 'thermocouple', 'degC', 'Exhaust', 'Flue gas exit temperature', hi=600, hiw=500, tc_type='K')
add_channel('TT_103', f'{CH}Mod1/ai2', 'thermocouple', 'degC', 'Water Loop', 'Economizer inlet water temp', tc_type='K')
add_channel('TT_104', f'{CH}Mod1/ai3', 'thermocouple', 'degC', 'Water Loop', 'Economizer outlet water temp', tc_type='K')
add_channel('TT_105', f'{CH}Mod1/ai4', 'thermocouple', 'degC', 'Exhaust', 'Stack exhaust temperature', hi=300, hiw=250, tc_type='K')
add_channel('TT_106', f'{CH}Mod1/ai5', 'thermocouple', 'degC', 'Air System', 'Combustion air preheat temp', tc_type='K')
add_channel('TT_107', f'{CH}Mod1/ai6', 'thermocouple', 'degC', 'Steam', 'Superheater outlet temp', hi=500, hiw=450, tc_type='K')
add_channel('TT_108', f'{CH}Mod1/ai7', 'thermocouple', 'degC', 'Water Loop', 'Feedwater inlet temp', tc_type='K')
add_channel('TT_109', f'{CH}Mod1/ai8', 'thermocouple', 'degC', 'Steam', 'Steam drum temperature', hi=300, hiw=260, tc_type='K')
add_channel('TT_110', f'{CH}Mod1/ai9', 'thermocouple', 'degC', 'Combustion', 'Burner flame temperature', hi=1100, hiw=1000, tc_type='K')

# ===== MODULE 2: NI 9205 - Voltage Inputs (Slot 2) =====
add_channel('PT_201', f'{CH}Mod2/ai0', 'voltage_input', 'inH2O', 'Combustion', 'Furnace draft pressure', scale_type='map', pre_min=0, pre_max=10, sc_min=-5, sc_max=5)
add_channel('PT_202', f'{CH}Mod2/ai1', 'voltage_input', 'psig', 'Steam', 'Steam header pressure', hi=280, hiw=250, scale_type='map', pre_min=0, pre_max=10, sc_min=0, sc_max=300)
add_channel('PT_203', f'{CH}Mod2/ai2', 'voltage_input', 'psig', 'Water Loop', 'Feedwater pressure', scale_type='map', pre_min=0, pre_max=10, sc_min=0, sc_max=400)
add_channel('PT_204', f'{CH}Mod2/ai3', 'voltage_input', 'psig', 'Fuel', 'Natural gas supply pressure', lo=2, low=3, scale_type='map', pre_min=0, pre_max=10, sc_min=0, sc_max=15)
add_channel('LT_205', f'{CH}Mod2/ai4', 'voltage_input', '%', 'Water Loop', 'Drum water level', lo=20, hi=90, low=30, hiw=80, scale_type='map', pre_min=0, pre_max=10, sc_min=0, sc_max=100)
add_channel('AT_206', f'{CH}Mod2/ai5', 'voltage_input', '%', 'Exhaust', 'O2 analyzer (flue gas)', low=2, hiw=8, scale_type='map', pre_min=0, pre_max=10, sc_min=0, sc_max=25)
add_channel('AT_207', f'{CH}Mod2/ai6', 'voltage_input', 'ppm', 'Exhaust', 'CO analyzer (flue gas)', hi=500, hiw=200, scale_type='map', pre_min=0, pre_max=10, sc_min=0, sc_max=1000)
add_channel('PT_208', f'{CH}Mod2/ai7', 'voltage_input', 'inH2O', 'Air System', 'Combustion air pressure', scale_type='map', pre_min=0, pre_max=10, sc_min=0, sc_max=30)

# ===== MODULE 3: NI 9203 - 8-ch Current Inputs (Slot 3) =====
add_channel('FT_301', f'{CH}Mod3/ai0', 'current_input', 'SCFH', 'Fuel', 'Natural gas flow rate', four_twenty=True, eu_min=0, eu_max=10000)
add_channel('FT_302', f'{CH}Mod3/ai1', 'current_input', 'GPM', 'Water Loop', 'Feedwater flow rate', four_twenty=True, eu_min=0, eu_max=500)
add_channel('FT_303', f'{CH}Mod3/ai2', 'current_input', 'lb/hr', 'Steam', 'Steam flow rate', four_twenty=True, eu_min=0, eu_max=50000)
add_channel('FT_304', f'{CH}Mod3/ai3', 'current_input', 'SCFM', 'Air System', 'Combustion air flow', four_twenty=True, eu_min=0, eu_max=5000)
add_channel('FT_305', f'{CH}Mod3/ai4', 'current_input', 'GPM', 'Water Loop', 'Blowdown flow rate', four_twenty=True, eu_min=0, eu_max=50)
add_channel('FT_306', f'{CH}Mod3/ai5', 'current_input', 'GPM', 'Water Loop', 'Condensate return flow', four_twenty=True, eu_min=0, eu_max=200)

# ===== MODULE 4: NI 9375 - 16 DI (Slot 4) =====
add_channel('XS_401', f'{CH}Mod4/port0/line0', 'digital_input', '', 'Safety', 'E-Stop status', chartable=False)
add_channel('XS_402', f'{CH}Mod4/port0/line1', 'digital_input', '', 'Safety', 'Flame scanner - main', chartable=False)
add_channel('XS_403', f'{CH}Mod4/port0/line2', 'digital_input', '', 'Safety', 'Flame scanner - pilot', chartable=False)
add_channel('XS_404', f'{CH}Mod4/port0/line3', 'digital_input', '', 'Safety', 'High steam pressure switch', chartable=False)
add_channel('XS_405', f'{CH}Mod4/port0/line4', 'digital_input', '', 'Safety', 'Low water cutoff', chartable=False)
add_channel('XS_406', f'{CH}Mod4/port0/line5', 'digital_input', '', 'Safety', 'High gas pressure switch', chartable=False)
add_channel('XS_407', f'{CH}Mod4/port0/line6', 'digital_input', '', 'Safety', 'Low gas pressure switch', chartable=False)
add_channel('XS_408', f'{CH}Mod4/port0/line7', 'digital_input', '', 'Safety', 'Air flow switch', chartable=False)
add_channel('ZS_409', f'{CH}Mod4/port0/line8', 'digital_input', '', 'Fuel', 'Gas valve - closed', chartable=False)
add_channel('ZS_410', f'{CH}Mod4/port0/line9', 'digital_input', '', 'Fuel', 'Gas valve - open', chartable=False)
add_channel('ZS_411', f'{CH}Mod4/port0/line10', 'digital_input', '', 'Air System', 'FD fan running', chartable=False)
add_channel('ZS_412', f'{CH}Mod4/port0/line11', 'digital_input', '', 'Exhaust', 'ID fan running', chartable=False)
add_channel('ZS_413', f'{CH}Mod4/port0/line12', 'digital_input', '', 'Water Loop', 'Feed pump running', chartable=False)
add_channel('ZS_414', f'{CH}Mod4/port0/line13', 'digital_input', '', 'Water Loop', 'Blowdown valve open', chartable=False)

# ===== MODULE 5: NI 9375 - 16 DO (Slot 5) =====
add_channel('XY_501', f'{CH}Mod5/port0/line0', 'digital_output', '', 'Fuel', 'Main gas shutoff valve', chartable=False)
add_channel('XY_502', f'{CH}Mod5/port0/line1', 'digital_output', '', 'Fuel', 'Pilot gas valve', chartable=False)
add_channel('XY_503', f'{CH}Mod5/port0/line2', 'digital_output', '', 'Combustion', 'Ignition transformer', chartable=False)
add_channel('XY_504', f'{CH}Mod5/port0/line3', 'digital_output', '', 'Air System', 'FD fan start/stop', chartable=False)
add_channel('XY_505', f'{CH}Mod5/port0/line4', 'digital_output', '', 'Exhaust', 'ID fan start/stop', chartable=False)
add_channel('XY_506', f'{CH}Mod5/port0/line5', 'digital_output', '', 'Water Loop', 'Feed pump start/stop', chartable=False)
add_channel('XY_507', f'{CH}Mod5/port0/line6', 'digital_output', '', 'Water Loop', 'Blowdown valve', chartable=False)
add_channel('XY_508', f'{CH}Mod5/port0/line7', 'digital_output', '', 'Safety', 'Alarm horn', chartable=False)

# ===== MODULE 6: NI 9264 - Analog Outputs (Slot 6) =====
add_channel('FCV_601', f'{CH}Mod6/ao0', 'voltage_output', '%', 'Fuel', 'Gas control valve position', scale_type='map', pre_min=0, pre_max=10, sc_min=0, sc_max=100)
add_channel('FCV_602', f'{CH}Mod6/ao1', 'voltage_output', '%', 'Air System', 'Air damper position', scale_type='map', pre_min=0, pre_max=10, sc_min=0, sc_max=100)
add_channel('FCV_603', f'{CH}Mod6/ao2', 'voltage_output', '%', 'Water Loop', 'Feedwater control valve', scale_type='map', pre_min=0, pre_max=10, sc_min=0, sc_max=100)
add_channel('FCV_604', f'{CH}Mod6/ao3', 'voltage_output', '%', 'Steam', 'Steam pressure control valve', scale_type='map', pre_min=0, pre_max=10, sc_min=0, sc_max=100)

# Auto-select chartable channels for recording
project['recording']['selectedChannels'] = [
    name for name, c in project['channels'].items() if c.get('chartable', True)
]

# ========================================================================
# BUILD 4 PAGES WITH WIDGETS
# ========================================================================

# --- Page 1: Overview ---
p1 = [
    {'id': wid(), 'type': 'title', 'x': 0, 'y': 0, 'w': 24, 'h': 2, 'label': 'Boiler Combustion Research - Overview', 'style': {'fontSize': 18}},
    {'id': wid(), 'type': 'numeric', 'x': 0, 'y': 2, 'w': 4, 'h': 3, 'channel': 'TT_101', 'label': 'Furnace Temp', 'precision': 1},
    {'id': wid(), 'type': 'numeric', 'x': 4, 'y': 2, 'w': 4, 'h': 3, 'channel': 'TT_102', 'label': 'Flue Gas Temp', 'precision': 1},
    {'id': wid(), 'type': 'numeric', 'x': 8, 'y': 2, 'w': 4, 'h': 3, 'channel': 'TT_107', 'label': 'Steam Temp', 'precision': 1},
    {'id': wid(), 'type': 'numeric', 'x': 12, 'y': 2, 'w': 4, 'h': 3, 'channel': 'PT_202', 'label': 'Steam Pressure', 'precision': 1},
    {'id': wid(), 'type': 'gauge', 'x': 16, 'y': 2, 'w': 4, 'h': 5, 'channel': 'LT_205', 'label': 'Drum Level', 'min': 0, 'max': 100},
    {'id': wid(), 'type': 'gauge', 'x': 20, 'y': 2, 'w': 4, 'h': 5, 'channel': 'AT_206', 'label': 'O2 %', 'min': 0, 'max': 25},
    {'id': wid(), 'type': 'numeric', 'x': 0, 'y': 5, 'w': 4, 'h': 3, 'channel': 'FT_301', 'label': 'Gas Flow', 'precision': 0},
    {'id': wid(), 'type': 'numeric', 'x': 4, 'y': 5, 'w': 4, 'h': 3, 'channel': 'FT_304', 'label': 'Air Flow', 'precision': 0},
    {'id': wid(), 'type': 'numeric', 'x': 8, 'y': 5, 'w': 4, 'h': 3, 'channel': 'FT_303', 'label': 'Steam Flow', 'precision': 0},
    {'id': wid(), 'type': 'numeric', 'x': 12, 'y': 5, 'w': 4, 'h': 3, 'channel': 'FT_302', 'label': 'Feedwater Flow', 'precision': 1},
    {'id': wid(), 'type': 'trend', 'x': 0, 'y': 8, 'w': 16, 'h': 8, 'channels': ['TT_101', 'TT_102', 'TT_107', 'TT_105'], 'label': 'Temperature Trend', 'duration': 300},
    {'id': wid(), 'type': 'led', 'x': 16, 'y': 7, 'w': 2, 'h': 2, 'channel': 'XS_401', 'label': 'E-Stop'},
    {'id': wid(), 'type': 'led', 'x': 18, 'y': 7, 'w': 2, 'h': 2, 'channel': 'XS_402', 'label': 'Flame Main'},
    {'id': wid(), 'type': 'led', 'x': 20, 'y': 7, 'w': 2, 'h': 2, 'channel': 'XS_403', 'label': 'Flame Pilot'},
    {'id': wid(), 'type': 'led', 'x': 22, 'y': 7, 'w': 2, 'h': 2, 'channel': 'XS_405', 'label': 'Low Water'},
    {'id': wid(), 'type': 'bar', 'x': 16, 'y': 9, 'w': 2, 'h': 7, 'channel': 'FCV_601', 'label': 'Gas Vlv', 'min': 0, 'max': 100},
    {'id': wid(), 'type': 'bar', 'x': 18, 'y': 9, 'w': 2, 'h': 7, 'channel': 'FCV_602', 'label': 'Air Dmpr', 'min': 0, 'max': 100},
    {'id': wid(), 'type': 'bar', 'x': 20, 'y': 9, 'w': 2, 'h': 7, 'channel': 'FCV_603', 'label': 'FW Vlv', 'min': 0, 'max': 100},
    {'id': wid(), 'type': 'bar', 'x': 22, 'y': 9, 'w': 2, 'h': 7, 'channel': 'FCV_604', 'label': 'Stm Vlv', 'min': 0, 'max': 100},
]

# --- Page 2: Combustion ---
p2 = [
    {'id': wid(), 'type': 'title', 'x': 0, 'y': 0, 'w': 24, 'h': 2, 'label': 'Combustion & Fuel System'},
    {'id': wid(), 'type': 'gauge', 'x': 0, 'y': 2, 'w': 4, 'h': 5, 'channel': 'TT_101', 'label': 'Furnace', 'min': 0, 'max': 1000},
    {'id': wid(), 'type': 'gauge', 'x': 4, 'y': 2, 'w': 4, 'h': 5, 'channel': 'TT_110', 'label': 'Flame', 'min': 0, 'max': 1200},
    {'id': wid(), 'type': 'numeric', 'x': 8, 'y': 2, 'w': 4, 'h': 3, 'channel': 'PT_201', 'label': 'Furnace Draft', 'precision': 2},
    {'id': wid(), 'type': 'numeric', 'x': 12, 'y': 2, 'w': 4, 'h': 3, 'channel': 'PT_204', 'label': 'Gas Pressure', 'precision': 1},
    {'id': wid(), 'type': 'numeric', 'x': 16, 'y': 2, 'w': 4, 'h': 3, 'channel': 'FT_301', 'label': 'Gas Flow', 'precision': 0},
    {'id': wid(), 'type': 'setpoint', 'x': 20, 'y': 2, 'w': 4, 'h': 3, 'channel': 'FCV_601', 'label': 'Gas Valve %', 'min': 0, 'max': 100, 'step': 1},
    {'id': wid(), 'type': 'toggle', 'x': 8, 'y': 5, 'w': 3, 'h': 2, 'channel': 'XY_501', 'label': 'Main Gas', 'onLabel': 'OPEN', 'offLabel': 'CLOSED', 'confirmOn': True},
    {'id': wid(), 'type': 'toggle', 'x': 11, 'y': 5, 'w': 3, 'h': 2, 'channel': 'XY_502', 'label': 'Pilot Gas', 'onLabel': 'OPEN', 'offLabel': 'CLOSED', 'confirmOn': True},
    {'id': wid(), 'type': 'toggle', 'x': 14, 'y': 5, 'w': 3, 'h': 2, 'channel': 'XY_503', 'label': 'Igniter', 'onLabel': 'ON', 'offLabel': 'OFF', 'confirmOn': True},
    {'id': wid(), 'type': 'led', 'x': 17, 'y': 5, 'w': 2, 'h': 2, 'channel': 'ZS_409', 'label': 'Vlv Closed'},
    {'id': wid(), 'type': 'led', 'x': 19, 'y': 5, 'w': 2, 'h': 2, 'channel': 'ZS_410', 'label': 'Vlv Open'},
    {'id': wid(), 'type': 'numeric', 'x': 0, 'y': 7, 'w': 4, 'h': 3, 'channel': 'TT_106', 'label': 'Air Preheat', 'precision': 1},
    {'id': wid(), 'type': 'numeric', 'x': 4, 'y': 7, 'w': 4, 'h': 3, 'channel': 'FT_304', 'label': 'Air Flow', 'precision': 0},
    {'id': wid(), 'type': 'numeric', 'x': 8, 'y': 7, 'w': 4, 'h': 3, 'channel': 'PT_208', 'label': 'Air Pressure', 'precision': 1},
    {'id': wid(), 'type': 'setpoint', 'x': 12, 'y': 7, 'w': 4, 'h': 3, 'channel': 'FCV_602', 'label': 'Air Damper %', 'min': 0, 'max': 100, 'step': 1},
    {'id': wid(), 'type': 'toggle', 'x': 16, 'y': 7, 'w': 3, 'h': 2, 'channel': 'XY_504', 'label': 'FD Fan', 'onLabel': 'RUN', 'offLabel': 'STOP'},
    {'id': wid(), 'type': 'led', 'x': 19, 'y': 7, 'w': 2, 'h': 2, 'channel': 'ZS_411', 'label': 'FD Running'},
    {'id': wid(), 'type': 'trend', 'x': 0, 'y': 10, 'w': 12, 'h': 6, 'channels': ['AT_206', 'AT_207'], 'label': 'Flue Gas Analysis', 'duration': 300},
    {'id': wid(), 'type': 'trend', 'x': 12, 'y': 10, 'w': 12, 'h': 6, 'channels': ['TT_101', 'TT_110', 'TT_102', 'TT_105'], 'label': 'Combustion Temperatures', 'duration': 300},
]

# --- Page 3: Water & Steam ---
p3 = [
    {'id': wid(), 'type': 'title', 'x': 0, 'y': 0, 'w': 24, 'h': 2, 'label': 'Water Loop & Steam System'},
    {'id': wid(), 'type': 'gauge', 'x': 0, 'y': 2, 'w': 6, 'h': 5, 'channel': 'LT_205', 'label': 'Drum Level', 'min': 0, 'max': 100},
    {'id': wid(), 'type': 'numeric', 'x': 6, 'y': 2, 'w': 4, 'h': 3, 'channel': 'PT_202', 'label': 'Steam Press', 'precision': 1},
    {'id': wid(), 'type': 'numeric', 'x': 10, 'y': 2, 'w': 4, 'h': 3, 'channel': 'TT_107', 'label': 'Steam Temp', 'precision': 1},
    {'id': wid(), 'type': 'numeric', 'x': 14, 'y': 2, 'w': 4, 'h': 3, 'channel': 'FT_303', 'label': 'Steam Flow', 'precision': 0},
    {'id': wid(), 'type': 'setpoint', 'x': 18, 'y': 2, 'w': 6, 'h': 3, 'channel': 'FCV_604', 'label': 'Steam Valve %', 'min': 0, 'max': 100, 'step': 1},
    {'id': wid(), 'type': 'numeric', 'x': 6, 'y': 5, 'w': 4, 'h': 3, 'channel': 'TT_109', 'label': 'Drum Temp', 'precision': 1},
    {'id': wid(), 'type': 'numeric', 'x': 10, 'y': 5, 'w': 4, 'h': 3, 'channel': 'TT_108', 'label': 'FW Inlet', 'precision': 1},
    {'id': wid(), 'type': 'numeric', 'x': 14, 'y': 5, 'w': 4, 'h': 3, 'channel': 'PT_203', 'label': 'FW Pressure', 'precision': 1},
    {'id': wid(), 'type': 'numeric', 'x': 18, 'y': 5, 'w': 3, 'h': 3, 'channel': 'FT_302', 'label': 'FW Flow', 'precision': 1},
    {'id': wid(), 'type': 'setpoint', 'x': 21, 'y': 5, 'w': 3, 'h': 3, 'channel': 'FCV_603', 'label': 'FW Valve', 'min': 0, 'max': 100, 'step': 1},
    {'id': wid(), 'type': 'toggle', 'x': 0, 'y': 8, 'w': 3, 'h': 2, 'channel': 'XY_506', 'label': 'Feed Pump', 'onLabel': 'RUN', 'offLabel': 'STOP'},
    {'id': wid(), 'type': 'led', 'x': 3, 'y': 8, 'w': 2, 'h': 2, 'channel': 'ZS_413', 'label': 'Pump Run'},
    {'id': wid(), 'type': 'toggle', 'x': 5, 'y': 8, 'w': 3, 'h': 2, 'channel': 'XY_507', 'label': 'Blowdown', 'onLabel': 'OPEN', 'offLabel': 'CLOSED'},
    {'id': wid(), 'type': 'led', 'x': 8, 'y': 8, 'w': 2, 'h': 2, 'channel': 'ZS_414', 'label': 'BD Open'},
    {'id': wid(), 'type': 'numeric', 'x': 10, 'y': 8, 'w': 4, 'h': 3, 'channel': 'FT_305', 'label': 'Blowdown Flow', 'precision': 1},
    {'id': wid(), 'type': 'numeric', 'x': 14, 'y': 8, 'w': 4, 'h': 3, 'channel': 'TT_103', 'label': 'Econ Inlet', 'precision': 1},
    {'id': wid(), 'type': 'numeric', 'x': 18, 'y': 8, 'w': 3, 'h': 3, 'channel': 'TT_104', 'label': 'Econ Outlet', 'precision': 1},
    {'id': wid(), 'type': 'numeric', 'x': 21, 'y': 8, 'w': 3, 'h': 3, 'channel': 'FT_306', 'label': 'Cond Return', 'precision': 1},
    {'id': wid(), 'type': 'trend', 'x': 0, 'y': 11, 'w': 12, 'h': 6, 'channels': ['LT_205', 'FT_302', 'FT_305'], 'label': 'Water Level & Flow', 'duration': 300},
    {'id': wid(), 'type': 'trend', 'x': 12, 'y': 11, 'w': 12, 'h': 6, 'channels': ['PT_202', 'FT_303'], 'label': 'Steam Pressure & Flow', 'duration': 300},
]

# --- Page 4: Safety & Controls ---
p4 = [
    {'id': wid(), 'type': 'title', 'x': 0, 'y': 0, 'w': 24, 'h': 2, 'label': 'Safety System & Equipment Status'},
    {'id': wid(), 'type': 'led', 'x': 0, 'y': 2, 'w': 3, 'h': 2, 'channel': 'XS_401', 'label': 'E-Stop'},
    {'id': wid(), 'type': 'led', 'x': 3, 'y': 2, 'w': 3, 'h': 2, 'channel': 'XS_402', 'label': 'Flame Main'},
    {'id': wid(), 'type': 'led', 'x': 6, 'y': 2, 'w': 3, 'h': 2, 'channel': 'XS_403', 'label': 'Flame Pilot'},
    {'id': wid(), 'type': 'led', 'x': 9, 'y': 2, 'w': 3, 'h': 2, 'channel': 'XS_404', 'label': 'Hi Steam'},
    {'id': wid(), 'type': 'led', 'x': 12, 'y': 2, 'w': 3, 'h': 2, 'channel': 'XS_405', 'label': 'Low Water'},
    {'id': wid(), 'type': 'led', 'x': 15, 'y': 2, 'w': 3, 'h': 2, 'channel': 'XS_406', 'label': 'Hi Gas Press'},
    {'id': wid(), 'type': 'led', 'x': 18, 'y': 2, 'w': 3, 'h': 2, 'channel': 'XS_407', 'label': 'Lo Gas Press'},
    {'id': wid(), 'type': 'led', 'x': 21, 'y': 2, 'w': 3, 'h': 2, 'channel': 'XS_408', 'label': 'Air Flow Sw'},
    {'id': wid(), 'type': 'toggle', 'x': 0, 'y': 5, 'w': 4, 'h': 2, 'channel': 'XY_501', 'label': 'Main Gas Valve', 'onLabel': 'OPEN', 'offLabel': 'CLOSED', 'confirmOn': True},
    {'id': wid(), 'type': 'toggle', 'x': 4, 'y': 5, 'w': 4, 'h': 2, 'channel': 'XY_502', 'label': 'Pilot Gas Valve', 'onLabel': 'OPEN', 'offLabel': 'CLOSED', 'confirmOn': True},
    {'id': wid(), 'type': 'toggle', 'x': 8, 'y': 5, 'w': 4, 'h': 2, 'channel': 'XY_503', 'label': 'Ignition', 'onLabel': 'ON', 'offLabel': 'OFF', 'confirmOn': True},
    {'id': wid(), 'type': 'toggle', 'x': 12, 'y': 5, 'w': 4, 'h': 2, 'channel': 'XY_504', 'label': 'FD Fan', 'onLabel': 'RUN', 'offLabel': 'STOP'},
    {'id': wid(), 'type': 'toggle', 'x': 16, 'y': 5, 'w': 4, 'h': 2, 'channel': 'XY_505', 'label': 'ID Fan', 'onLabel': 'RUN', 'offLabel': 'STOP'},
    {'id': wid(), 'type': 'toggle', 'x': 20, 'y': 5, 'w': 4, 'h': 2, 'channel': 'XY_508', 'label': 'Alarm Horn', 'onLabel': 'ON', 'offLabel': 'OFF'},
    {'id': wid(), 'type': 'led', 'x': 0, 'y': 7, 'w': 3, 'h': 2, 'channel': 'ZS_409', 'label': 'Gas Closed'},
    {'id': wid(), 'type': 'led', 'x': 3, 'y': 7, 'w': 3, 'h': 2, 'channel': 'ZS_410', 'label': 'Gas Open'},
    {'id': wid(), 'type': 'led', 'x': 6, 'y': 7, 'w': 3, 'h': 2, 'channel': 'ZS_411', 'label': 'FD Fan Run'},
    {'id': wid(), 'type': 'led', 'x': 9, 'y': 7, 'w': 3, 'h': 2, 'channel': 'ZS_412', 'label': 'ID Fan Run'},
    {'id': wid(), 'type': 'led', 'x': 12, 'y': 7, 'w': 3, 'h': 2, 'channel': 'ZS_413', 'label': 'Pump Run'},
    {'id': wid(), 'type': 'led', 'x': 15, 'y': 7, 'w': 3, 'h': 2, 'channel': 'ZS_414', 'label': 'BD Valve'},
    {'id': wid(), 'type': 'interlock-status', 'x': 18, 'y': 7, 'w': 6, 'h': 3, 'label': 'Interlock Status'},
    {'id': wid(), 'type': 'setpoint', 'x': 0, 'y': 10, 'w': 6, 'h': 3, 'channel': 'FCV_601', 'label': 'Gas Control Valve', 'min': 0, 'max': 100, 'step': 1},
    {'id': wid(), 'type': 'setpoint', 'x': 6, 'y': 10, 'w': 6, 'h': 3, 'channel': 'FCV_602', 'label': 'Air Damper', 'min': 0, 'max': 100, 'step': 1},
    {'id': wid(), 'type': 'setpoint', 'x': 12, 'y': 10, 'w': 6, 'h': 3, 'channel': 'FCV_603', 'label': 'Feedwater Valve', 'min': 0, 'max': 100, 'step': 1},
    {'id': wid(), 'type': 'setpoint', 'x': 18, 'y': 10, 'w': 6, 'h': 3, 'channel': 'FCV_604', 'label': 'Steam Valve', 'min': 0, 'max': 100, 'step': 1},
]

project['layout']['pages'] = [
    {'id': 'overview', 'name': 'Overview', 'widgets': p1, 'order': 0},
    {'id': 'combustion', 'name': 'Combustion & Fuel', 'widgets': p2, 'order': 1},
    {'id': 'water-steam', 'name': 'Water & Steam', 'widgets': p3, 'order': 2},
    {'id': 'safety', 'name': 'Safety & Controls', 'widgets': p4, 'order': 3},
]

# Write file
out_path = Path(__file__).parent.parent / 'config' / 'projects' / 'Boiler_Combustion_Research_cDAQ.json'
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(project, f, indent=2)

# Summary
ch_count = len(project['channels'])
page_count = len(project['layout']['pages'])
total_widgets = sum(len(p['widgets']) for p in project['layout']['pages'])
groups = {}
for n, c in project['channels'].items():
    groups.setdefault(c['group'], []).append(n)

print(f'Created: {out_path.name}')
print(f'  Channels: {ch_count}')
print(f'  Pages: {page_count}')
print(f'  Total widgets: {total_widgets}')
print(f'  Recording channels: {len(project["recording"]["selectedChannels"])}')
print()
for g in sorted(groups):
    print(f'  {g}: {len(groups[g])} channels')
for p in project['layout']['pages']:
    print(f'  Page "{p["name"]}": {len(p["widgets"])} widgets')
