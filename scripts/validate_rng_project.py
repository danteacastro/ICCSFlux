"""Validate the RNG/CNG Compression Station project JSON."""
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'services', 'daq_service'))
from config_parser import ChannelType

with open(os.path.join(os.path.dirname(__file__), '..', 'config', 'projects', 'RNG_CNG_Compression_Station.json')) as f:
    proj = json.load(f)

channels = proj['channels']
print(f'Project: {proj["name"]}')
print(f'Total channels: {len(channels)}')

errors = []
type_counts = {}
group_counts = {}
for name, ch in channels.items():
    ct = ch['channel_type']
    try:
        ChannelType(ct)
    except ValueError as e:
        errors.append(f'{name}: {e}')
    type_counts[ct] = type_counts.get(ct, 0) + 1
    g = ch.get('group', 'Ungrouped')
    group_counts[g] = group_counts.get(g, 0) + 1

if errors:
    print(f'\nERRORS ({len(errors)}):')
    for e in errors:
        print(f'  {e}')
else:
    print('All channel types VALID')

print(f'\nChannel types:')
for ct, count in sorted(type_counts.items()):
    print(f'  {ct}: {count}')

print(f'\nGroups:')
for g, count in sorted(group_counts.items()):
    print(f'  {g}: {count}')

safety = proj.get('safety', {})
il = safety.get('interlocks', [])
ac = safety.get('alarmConfigs', {})
sa = safety.get('safetyActions', {})
print(f'\nAlarm configs: {len(ac)}')
print(f'Interlocks: {len(il)}')
for i in il:
    print(f'  IL: {i["name"]} -> {i["action"]} (delay: {i["delay_ms"]}ms)')

print(f'\nSafety actions: {len(sa)}')
for name, action in sa.items():
    outputs = action.get('outputs', {})
    print(f'  {name}: {action["description"]} -> {len(outputs)} outputs')

scripts = proj.get('scripts', {}).get('pythonScripts', [])
print(f'\nPython scripts: {len(scripts)}')
for s in scripts:
    print(f'  {s["name"]} (runMode={s["runMode"]}, enabled={s["enabled"]})')

layout = proj.get('layout', {})
widgets = layout.get('widgets', [])
pages = layout.get('pages', [])
print(f'\nLayout: {len(widgets)} widgets, {len(pages)} pages (should be empty for tester project)')

rec = proj.get('recording', {}).get('selectedChannels', [])
print(f'Recording: {len(rec)} channels selected')

print('\n=== VALIDATION PASSED ===' if not errors else '\n=== VALIDATION FAILED ===')
