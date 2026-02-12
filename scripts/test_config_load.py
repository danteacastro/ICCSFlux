"""Test loading the DHW Test System project JSON and verify channel parsing."""
import sys
import os
import json

project_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'projects', 'DHW Test System.json')

try:
    with open(project_path, 'r', encoding='utf-8') as f:
        project = json.load(f)

    print(f"Project type: {project.get('type')}")
    print(f"Project version: {project.get('version')}")
    print(f"Project name: {project.get('name')}")
    print()

    # Check channels
    channels = project.get('channels', {})
    print(f"Total channels: {len(channels)}")

    # Count by type
    type_counts = {}
    for name, ch in channels.items():
        ct = ch.get('channel_type', 'unknown')
        type_counts[ct] = type_counts.get(ct, 0) + 1

    print("\nChannel type breakdown:")
    for ct, count in sorted(type_counts.items()):
        print(f"  {ct}: {count}")

    # Count by module (from physical_channel)
    module_counts = {}
    for name, ch in channels.items():
        phys = ch.get('physical_channel', '')
        if '/' in phys:
            mod = phys.split('/')[0]
        else:
            mod = 'unknown'
        module_counts[mod] = module_counts.get(mod, 0) + 1

    print("\nChannels per module:")
    for mod, count in sorted(module_counts.items()):
        print(f"  {mod}: {count}")

    # Show sample channels
    print("\nSample channels (first 8):")
    for i, (name, ch) in enumerate(channels.items()):
        if i >= 8:
            break
        print(f"  {name}: {ch.get('physical_channel')} [{ch.get('channel_type')}] "
              f"unit={ch.get('unit')} group={ch.get('group')}")

    # Verify all channel types are valid
    print("\n--- VALIDATION ---")
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'services', 'daq_service'))
    from config_parser import ChannelType

    valid_types = set(ct.value for ct in ChannelType)
    print(f"Valid channel types: {sorted(valid_types)}")

    invalid = []
    for name, ch in channels.items():
        ct = ch.get('channel_type', '')
        if ct not in valid_types:
            invalid.append((name, ct))

    if invalid:
        print(f"\nINVALID channel types found ({len(invalid)}):")
        for name, ct in invalid:
            print(f"  {name}: '{ct}'")
    else:
        print(f"\nAll {len(channels)} channels have valid types")

    # Check for alarms/safety config
    alarms = project.get('alarms', {})
    safety = project.get('safety', {})
    interlocks = project.get('interlocks', [])
    print(f"\nAlarm configs: {len(alarms)}")
    print(f"Safety configs: {len(safety)}")
    print(f"Interlocks: {len(interlocks)}")

    # Check system section
    system = project.get('system', {})
    print(f"\nSystem settings:")
    for k, v in system.items():
        print(f"  {k}: {v}")

    # Check for digital outputs (needed for safety actions)
    do_channels = [(n, ch) for n, ch in channels.items() if ch.get('channel_type') == 'digital_output']
    print(f"\nDigital output channels: {len(do_channels)}")
    for n, ch in do_channels:
        print(f"  {n}: {ch.get('physical_channel')}")

    print("\n=== PROJECT LOAD TEST: PASSED ===")

except Exception as e:
    print(f"ERROR loading project: {e}")
    import traceback
    traceback.print_exc()
    print("\n=== PROJECT LOAD TEST: FAILED ===")
