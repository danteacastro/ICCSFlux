#!/usr/bin/env python
"""Quick script to check what NI devices are visible to nidaqmx"""

import nidaqmx.system

system = nidaqmx.system.System.local()
devices = list(system.devices)

print("=" * 60)
print("NI Devices visible to NI-DAQmx on this PC:")
print("=" * 60)

if not devices:
    print("\nNo devices found!")
    print("\nThis means your cRIO is NOT visible to NI-DAQmx from this PC.")
    print("\nOptions:")
    print("  1. Install NI CompactRIO drivers and configure cRIO as remote target in NI MAX")
    print("  2. Use MQTT-based approach (cRIO reads its own hardware, sends via MQTT)")
else:
    for device in devices:
        print(f"\nDevice: {device.name}")
        print(f"  Type: {device.product_type}")
        print(f"  Serial: {device.dev_serial_num}")

        # Show some channels
        ai = list(device.ai_physical_chans)
        if ai:
            print(f"  AI channels: {len(ai)} (e.g., {ai[0].name})")

        di = list(device.di_lines)
        if di:
            print(f"  DI lines: {len(di)} (e.g., {di[0].name})")

        do = list(device.do_lines)
        if do:
            print(f"  DO lines: {len(do)} (e.g., {do[0].name})")

print("\n" + "=" * 60)
