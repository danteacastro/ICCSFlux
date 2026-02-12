"""Quick script to check NI DAQmx devices visible to the system."""
import sys
try:
    import nidaqmx
    from nidaqmx.system import System
except ImportError:
    print("ERROR: nidaqmx not installed")
    sys.exit(1)

system = System.local()
devices = list(system.devices)

if not devices:
    print("No NI devices found. Check NI MAX.")
    sys.exit(0)

print(f"Found {len(devices)} device(s):\n")

chassis_map = {}  # chassis_name -> [modules]

for dev in devices:
    name = dev.name
    product = dev.product_type
    serial = dev.dev_serial_num
    is_simulated = dev.dev_is_simulated

    # Detect chassis vs module
    if "cDAQ" in product and "Mod" not in name:
        chassis_map[name] = {"product": product, "serial": serial, "sim": is_simulated, "modules": []}
        print(f"CHASSIS: {name}")
        print(f"  Product: {product}")
        print(f"  Serial:  {serial}")
        print(f"  Simulated: {is_simulated}")
    else:
        # Find parent chassis
        parent = None
        for cname in chassis_map:
            if name.startswith(cname):
                parent = cname
                break

        ai_count = len(dev.ai_physical_chans) if hasattr(dev, 'ai_physical_chans') else 0
        ao_count = len(dev.ao_physical_chans) if hasattr(dev, 'ao_physical_chans') else 0
        di_count = len(dev.di_lines) if hasattr(dev, 'di_lines') else 0
        do_count = len(dev.do_lines) if hasattr(dev, 'do_lines') else 0
        ci_count = len(dev.ci_physical_chans) if hasattr(dev, 'ci_physical_chans') else 0

        print(f"\n  MODULE: {name}")
        print(f"    Product: {product}")
        print(f"    Serial:  {serial}")
        print(f"    Simulated: {is_simulated}")
        print(f"    AI: {ai_count}, AO: {ao_count}, DI: {di_count}, DO: {do_count}, CI: {ci_count}")

        if ai_count > 0:
            chans = [str(ch) for ch in dev.ai_physical_chans]
            print(f"    AI channels: {', '.join(chans[:4])}{'...' if ai_count > 4 else ''}")
        if ao_count > 0:
            chans = [str(ch) for ch in dev.ao_physical_chans]
            print(f"    AO channels: {', '.join(chans[:4])}{'...' if ao_count > 4 else ''}")
        if di_count > 0:
            lines = [str(l) for l in dev.di_lines]
            print(f"    DI lines: {', '.join(lines[:4])}{'...' if di_count > 4 else ''}")
        if do_count > 0:
            lines = [str(l) for l in dev.do_lines]
            print(f"    DO lines: {', '.join(lines[:4])}{'...' if do_count > 4 else ''}")

        if parent:
            chassis_map[parent]["modules"].append(name)

print(f"\n{'='*60}")
print("Discovery complete.")
