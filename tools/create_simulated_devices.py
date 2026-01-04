#!/usr/bin/env python
"""
NI MAX Simulated Device Creator for DHW Test System
====================================================

This script creates simulated NI-DAQmx devices in NI MAX that match
the DHW (Domestic Hot Water) test system configuration.

Hardware Configuration:
- cDAQ-9189 chassis (8-slot Ethernet/USB CompactDAQ)
- Slot 1: NI-9217 (4-ch RTD)
- Slot 2: NI-9213 (16-ch Thermocouple)
- Slot 7: NI-9203 (8-ch Current Input)
- Slot 8: NI-9472 (8-ch Digital Output)

Usage:
    python create_simulated_devices.py [--remove] [--list]

Options:
    --remove    Remove existing simulated devices before creating new ones
    --list      List all devices and exit
    --help      Show this help message

Requirements:
    - NI-DAQmx driver installed
    - nidaqmx Python package (pip install nidaqmx)

Author: NISystem Project
"""

import argparse
import sys
import time

try:
    import nidaqmx
    from nidaqmx.system import System
    from nidaqmx.system.device import Device
    NIDAQMX_AVAILABLE = True
except ImportError:
    NIDAQMX_AVAILABLE = False
    print("ERROR: nidaqmx package not installed.")
    print("Install with: pip install nidaqmx")
    sys.exit(1)


# DHW Test System Hardware Configuration
DHW_CHASSIS = {
    "name": "cDAQ9189-DHW",
    "product_type": "cDAQ-9189",
    "description": "DHW Test System - 8-Slot CompactDAQ Chassis"
}

DHW_MODULES = [
    {
        "slot": 1,
        "product_type": "NI 9217",
        "name_suffix": "Mod1",
        "description": "RTD Temperature Module (4ch)",
        "channels": ["ai0", "ai1", "ai2", "ai3"]
    },
    {
        "slot": 2,
        "product_type": "NI 9213",
        "name_suffix": "Mod2",
        "description": "Thermocouple Module (16ch)",
        "channels": [f"ai{i}" for i in range(16)]
    },
    {
        "slot": 7,
        "product_type": "NI 9203",
        "name_suffix": "Mod7",
        "description": "Analog Current Input Module (8ch)",
        "channels": [f"ai{i}" for i in range(8)]
    },
    {
        "slot": 8,
        "product_type": "NI 9472",
        "name_suffix": "Mod8",
        "description": "Digital Output Module (8ch)",
        "channels": [f"port0/line{i}" for i in range(8)]
    }
]


def get_system():
    """Get the local NI-DAQmx system instance."""
    return System.local()


def list_devices():
    """List all NI-DAQmx devices."""
    system = get_system()

    print("\n" + "=" * 60)
    print("NI-DAQmx Devices")
    print("=" * 60)

    if not system.devices:
        print("No devices found.")
        return

    for device in system.devices:
        sim_status = " [SIMULATED]" if device.is_simulated else ""
        print(f"\n  Device: {device.name}{sim_status}")
        print(f"    Product Type: {device.product_type}")
        print(f"    Serial Number: {device.serial_num}")

        # Show channel counts
        try:
            ai_count = len(device.ai_physical_chans)
            ao_count = len(device.ao_physical_chans)
            di_count = len(device.di_lines)
            do_count = len(device.do_lines)
            print(f"    Channels: AI={ai_count}, AO={ao_count}, DI={di_count}, DO={do_count}")
        except Exception:
            pass

    print("\n" + "=" * 60)


def remove_simulated_devices(name_pattern: str = "cDAQ9189-DHW"):
    """Remove simulated devices matching the pattern."""
    system = get_system()

    removed = []
    for device in list(system.devices):
        if device.is_simulated and name_pattern in device.name:
            print(f"  Removing: {device.name}")
            try:
                device.delete()
                removed.append(device.name)
                time.sleep(0.5)  # Give system time to process
            except Exception as e:
                print(f"    WARNING: Could not remove {device.name}: {e}")

    return removed


def create_simulated_chassis():
    """
    Create a simulated cDAQ-9189 chassis with modules.

    Note: NI-DAQmx creates the chassis and modules as a single unit.
    The product_type for the chassis determines what slots are available.
    """
    system = get_system()

    # Check if already exists
    for device in system.devices:
        if DHW_CHASSIS["name"] in device.name:
            print(f"  Device already exists: {device.name}")
            return device.name

    print(f"\nCreating simulated chassis: {DHW_CHASSIS['name']}")
    print(f"  Product Type: {DHW_CHASSIS['product_type']}")

    try:
        # Create the simulated chassis
        # NI-DAQmx will create it with all available slots
        device_name = system.create_simulated_device(
            device_name=DHW_CHASSIS["name"],
            product_type=DHW_CHASSIS["product_type"]
        )

        print(f"  Created: {device_name}")
        return device_name

    except nidaqmx.errors.DaqError as e:
        if "already exists" in str(e).lower():
            print(f"  Device already exists")
            return DHW_CHASSIS["name"]
        else:
            print(f"  ERROR: {e}")
            return None


def create_simulated_module(chassis_name: str, module_config: dict):
    """
    Create a simulated module in a chassis slot.

    Note: For CompactDAQ, modules are created separately and associated
    with chassis slots.
    """
    system = get_system()

    slot = module_config["slot"]
    product_type = module_config["product_type"]
    suffix = module_config["name_suffix"]

    # Module name format: chassisName/Mod#
    module_name = f"{chassis_name}{suffix}"

    print(f"\n  Creating module in Slot {slot}: {product_type}")
    print(f"    Name: {module_name}")

    try:
        device_name = system.create_simulated_device(
            device_name=module_name,
            product_type=product_type
        )
        print(f"    Created: {device_name}")
        return device_name

    except nidaqmx.errors.DaqError as e:
        if "already exists" in str(e).lower():
            print(f"    Module already exists")
            return module_name
        else:
            print(f"    ERROR: {e}")
            return None


def create_dhw_system():
    """Create the complete DHW test system simulated hardware."""

    print("\n" + "=" * 60)
    print("Creating DHW Test System Simulated Devices")
    print("=" * 60)

    system = get_system()

    # Check if create_simulated_device is available (newer nidaqmx versions)
    if not hasattr(system, 'create_simulated_device'):
        print("\n  NOTE: Programmatic device creation not available.")
        print("  The nidaqmx Python library doesn't support create_simulated_device.")
        print("\n  Please create devices manually in NI MAX:")
        print("  See: tools/NI_MAX_SIMULATION_SETUP.md for instructions")
        print("\n  Or use software simulation mode (simulation_mode = true)")
        return []

    created_devices = []

    for module in DHW_MODULES:
        module_name = f"DHW_{module['name_suffix']}"
        product_type = module["product_type"]

        print(f"\nCreating: {module_name} ({product_type})")
        print(f"  Description: {module['description']}")

        # Check if exists
        exists = False
        for device in system.devices:
            if module_name == device.name:
                print(f"  Already exists: {device.name}")
                created_devices.append(device.name)
                exists = True
                break

        if exists:
            continue

        try:
            device_name = system.create_simulated_device(
                device_name=module_name,
                product_type=product_type
            )
            print(f"  Created: {device_name}")
            created_devices.append(device_name)
            time.sleep(0.5)

        except nidaqmx.errors.DaqError as e:
            print(f"  ERROR: {e}")
        except AttributeError:
            print(f"  ERROR: create_simulated_device not available")
            break

    return created_devices


def print_channel_mapping():
    """Print the channel mapping for the DHW system."""

    print("\n" + "=" * 60)
    print("DHW Test System Channel Mapping")
    print("=" * 60)

    print("""
After creating the simulated devices, update your dhw_test_system.ini
to use these device names:

SIMULATED DEVICE MAPPING:
-------------------------

RTD Channels (DHW_Mod1 / NI-9217):
  RTD_in   -> DHW_Mod1/ai0
  RTD_out  -> DHW_Mod1/ai1

Thermocouple Channels (DHW_Mod2 / NI-9213):
  TC_in    -> DHW_Mod2/ai0
  TC_out   -> DHW_Mod2/ai1
  Tank_1   -> DHW_Mod2/ai2
  Tank_2   -> DHW_Mod2/ai3
  Tank_3   -> DHW_Mod2/ai4
  Tank_4   -> DHW_Mod2/ai5
  Tank_5   -> DHW_Mod2/ai6
  Tank_6   -> DHW_Mod2/ai7
  Tank_7   -> DHW_Mod2/ai8
  Tank_8   -> DHW_Mod2/ai9
  T_gas    -> DHW_Mod2/ai10
  T_amb    -> DHW_Mod2/ai11
  T_flu    -> DHW_Mod2/ai12
  T_ex1    -> DHW_Mod2/ai13
  T_ex2    -> DHW_Mod2/ai14
  T_ex3    -> DHW_Mod2/ai15

Current Input Channels (DHW_Mod7 / NI-9203):
  RH_rm    -> DHW_Mod7/ai1
  T_rm     -> DHW_Mod7/ai2
  RH_W     -> DHW_Mod7/ai3
  T_W      -> DHW_Mod7/ai4
  RH_E     -> DHW_Mod7/ai5
  T_E      -> DHW_Mod7/ai6
  Ifm      -> DHW_Mod7/ai0  (Note: original was ai8, remapped)
  NGin     -> DHW_Mod7/ai7  (Note: original was ai9, remapped)

Digital Output Channels (DHW_Mod8 / NI-9472):
  SV1      -> DHW_Mod8/port0/line0
  SV2      -> DHW_Mod8/port0/line1
  SV3      -> DHW_Mod8/port0/line2
""")


def verify_devices():
    """Verify the created devices can be accessed."""

    print("\n" + "=" * 60)
    print("Verifying Simulated Devices")
    print("=" * 60)

    system = get_system()
    dhw_devices = [d for d in system.devices if "DHW_" in d.name and d.is_simulated]

    if not dhw_devices:
        print("  No DHW simulated devices found!")
        return False

    all_ok = True
    for device in dhw_devices:
        print(f"\n  {device.name}:")
        print(f"    Product: {device.product_type}")
        print(f"    Simulated: {device.is_simulated}")

        # Try to read channel info
        try:
            ai_chans = list(device.ai_physical_chans)
            if ai_chans:
                print(f"    AI Channels: {len(ai_chans)}")
                print(f"      First: {ai_chans[0].name if ai_chans else 'N/A'}")
        except Exception:
            pass

        try:
            do_lines = list(device.do_lines)
            if do_lines:
                print(f"    DO Lines: {len(do_lines)}")
        except Exception:
            pass

    print("\n  Verification complete!")
    return all_ok


def print_manual_instructions():
    """Print step-by-step NI MAX instructions."""

    print("\n" + "=" * 60)
    print("MANUAL NI MAX SETUP INSTRUCTIONS")
    print("=" * 60)
    print("""
Follow these steps in NI MAX to create simulated devices:

STEP 1: Open NI MAX
  - Press Win+S, search for "NI MAX" or "Measurement & Automation Explorer"
  - Launch the application

STEP 2: Create Simulated Devices
  For EACH device below, repeat:
  a) In left panel, expand "My System"
  b) Right-click "Devices and Interfaces"
  c) Select "Create New..." > "Simulated NI-DAQmx Device"
  d) Find and select the product type
  e) Enter the device name EXACTLY as shown
  f) Click OK

DEVICES TO CREATE:
""")

    for module in DHW_MODULES:
        print(f"""
  Device #{DHW_MODULES.index(module) + 1}:
    Name:    DHW_{module['name_suffix']}
    Type:    {module['product_type']}
    Purpose: {module['description']}
""")

    print("""
STEP 3: Verify in NI MAX
  - Expand "Devices and Interfaces"
  - You should see all 4 DHW_* devices
  - Right-click each > "Self-Test" to verify

STEP 4: Run NISystem
  python services/daq_service/daq_service.py -c config/dhw_test_system_nimax_sim.ini
""")


def main():
    parser = argparse.ArgumentParser(
        description="Create simulated NI-DAQmx devices for DHW Test System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument("--remove", action="store_true",
                        help="Remove existing DHW simulated devices first")
    parser.add_argument("--list", action="store_true",
                        help="List all devices and exit")
    parser.add_argument("--verify", action="store_true",
                        help="Verify devices after creation")
    parser.add_argument("--mapping", action="store_true",
                        help="Show channel mapping and exit")
    parser.add_argument("--instructions", action="store_true",
                        help="Show manual NI MAX setup instructions")

    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("NI-DAQmx Simulated Device Creator")
    print("DHW Test System Configuration")
    print("=" * 60)

    # Check NI-DAQmx
    try:
        system = get_system()
        driver_version = system.driver_version
        print(f"\nNI-DAQmx Driver Version: {driver_version.major_version}."
              f"{driver_version.minor_version}.{driver_version.update_version}")
    except Exception as e:
        print(f"\nERROR: Cannot access NI-DAQmx: {e}")
        print("Make sure NI-DAQmx drivers are installed.")
        sys.exit(1)

    # Handle options
    if args.list:
        list_devices()
        return 0

    if args.mapping:
        print_channel_mapping()
        return 0

    if args.instructions:
        print_manual_instructions()
        return 0

    if args.remove:
        print("\nRemoving existing DHW simulated devices...")
        removed = remove_simulated_devices("DHW_")
        if removed:
            print(f"  Removed {len(removed)} device(s)")
            time.sleep(1)  # Wait for system to update
        else:
            print("  No devices to remove")

    # Create devices
    created = create_dhw_system()

    if created:
        print(f"\n  Created {len(created)} device(s)")

    # Verify if requested
    if args.verify or created:
        verify_devices()

    # Show channel mapping
    print_channel_mapping()

    print("\n" + "=" * 60)
    print("Setup Complete!")
    print("=" * 60)
    print("""
Next Steps:
1. Open NI MAX to see the simulated devices
2. Update dhw_test_system.ini to use simulated device names
3. Set simulation_mode = false to use real (simulated) hardware
4. Run the DAQ service to test

To use software simulation instead (no NI MAX devices):
  Set simulation_mode = true in the .ini file
""")

    return 0


if __name__ == "__main__":
    sys.exit(main())
