"""
Test for digital inputs on Waveshare Modbus RTU Relay
"""
from pymodbus.client import ModbusSerialClient

client = ModbusSerialClient(
    port='COM6',
    baudrate=9600,
    parity='N',
    stopbits=1,
    bytesize=8,
    timeout=1.0
)

if not client.connect():
    print("ERROR: Could not connect to COM6")
    exit(1)

slave_id = 1

print("Testing Digital Inputs on Waveshare Modbus RTU Relay")
print("=" * 60)

# Test 1: Read Discrete Inputs (Function Code 2) - Common for digital inputs
print("\n1. Testing Discrete Inputs (Function Code 2)...")
for count in [1, 2, 4, 8, 16]:
    print(f"\n  Trying to read {count} discrete input(s) starting at address 0:")
    result = client.read_discrete_inputs(address=0, count=count, device_id=slave_id)
    if result.isError():
        print(f"    ERROR: {result}")
    else:
        print(f"    SUCCESS! Found {count} discrete inputs")
        print(f"    States: {result.bits[:count]}")
        for i, state in enumerate(result.bits[:count]):
            print(f"      Input {i}: {'HIGH' if state else 'LOW'}")
        break

# Test 2: Try different starting addresses
print("\n2. Testing different discrete input addresses...")
for addr in [0, 10, 100, 1000]:
    result = client.read_discrete_inputs(address=addr, count=8, device_id=slave_id)
    if not result.isError():
        print(f"  Address {addr}: Found inputs - {result.bits[:8]}")

# Test 3: Read Input Registers (Function Code 4) - Sometimes used for digital inputs
print("\n3. Testing Input Registers (Function Code 4)...")
for count in [1, 2, 4, 8]:
    result = client.read_input_registers(address=0, count=count, device_id=slave_id)
    if not result.isError():
        print(f"  SUCCESS! Found {count} input register(s)")
        print(f"  Values: {result.registers}")
        break
    else:
        if count == 1:
            print(f"  Address 0: {result}")

# Test 4: Try reading holding registers at higher addresses (some devices map inputs there)
print("\n4. Testing Holding Registers at various addresses...")
test_addresses = [0, 10, 100, 256, 1000]
for addr in test_addresses:
    result = client.read_holding_registers(address=addr, count=1, device_id=slave_id)
    if not result.isError():
        print(f"  Address {addr}: Value = {result.registers[0]} (0x{result.registers[0]:04X})")

print("\n" + "=" * 60)

# Test 5: Try reading coils at higher addresses (maybe inputs are mapped as coils)
print("\n5. Testing Coils at higher addresses (0-255)...")
found_ranges = []
for addr in [0, 8, 16, 32, 64, 128, 256]:
    result = client.read_coils(address=addr, count=8, device_id=slave_id)
    if not result.isError():
        print(f"  Coils {addr}-{addr+7}: {result.bits[:8]}")
        found_ranges.append(addr)

print("\n" + "=" * 60)
print("SUMMARY:")
print("  Relay outputs (coils): Addresses 0-7 (confirmed working)")
print("  Check Waveshare documentation for digital input specs")

client.close()
