"""Test the system's device discovery against NI MAX simulated devices."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'services', 'daq_service'))

from device_discovery import DeviceDiscovery
import json

dd = DeviceDiscovery()
result = dd.scan()

print(f"Discovery success: {result.success}")
print(f"Message: {result.message}")
print(f"Simulation mode: {result.simulation_mode}")
print(f"Total channels: {result.total_channels}")
print()

for chassis in result.chassis:
    print(f"CHASSIS: {chassis.name} ({chassis.product_type})")
    print(f"  Serial: {chassis.serial_number}")
    print(f"  Slots: {chassis.slot_count}")
    for mod in chassis.modules:
        print(f"  MODULE [{mod.slot}]: {mod.name} ({mod.product_type}) - {mod.category}")
        print(f"    Channels: {len(mod.channels)}")
        for ch in mod.channels[:4]:
            print(f"      {ch.name} [{ch.channel_type}]")
        if len(mod.channels) > 4:
            print(f"      ... and {len(mod.channels) - 4} more")
    print()

# Test config template generation
print("=" * 60)
print("Config template for first 5 channels:")
print("=" * 60)
channels = dd.get_available_channels(result)
for ch in channels[:5]:
    print(f"  {ch['name']} -> type={ch.get('suggested_type', 'unknown')}, category={ch.get('category', 'unknown')}")
