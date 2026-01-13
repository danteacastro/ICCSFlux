"""
Quick test to toggle a relay and verify state changes
"""
import time
from pymodbus.client import ModbusSerialClient

# Connect to relay
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

print("Testing Relay 1 Toggle with State Verification")
print("=" * 50)

# Read initial state
result = client.read_coils(address=0, count=1, device_id=slave_id)
initial_state = result.bits[0] if not result.isError() else None
print(f"Initial state: {'ON' if initial_state else 'OFF'}")

# Turn ON
print("\nTurning relay ON...")
result = client.write_coil(address=0, value=True, device_id=slave_id)
if result.isError():
    print(f"  Write ERROR: {result}")
else:
    print("  Write command sent")

time.sleep(0.5)

# Read back
result = client.read_coils(address=0, count=1, device_id=slave_id)
on_state = result.bits[0] if not result.isError() else None
print(f"  State after ON command: {'ON' if on_state else 'OFF'}")

# Turn OFF
print("\nTurning relay OFF...")
result = client.write_coil(address=0, value=False, device_id=slave_id)
if result.isError():
    print(f"  Write ERROR: {result}")
else:
    print("  Write command sent")

time.sleep(0.5)

# Read back
result = client.read_coils(address=0, count=1, device_id=slave_id)
off_state = result.bits[0] if not result.isError() else None
print(f"  State after OFF command: {'ON' if off_state else 'OFF'}")

print("\n" + "=" * 50)
print(f"Result: Initial={initial_state}, After ON={on_state}, After OFF={off_state}")

if initial_state == False and on_state == True and off_state == False:
    print("SUCCESS: Relay is responding correctly!")
elif on_state == True and off_state == False:
    print("SUCCESS: Toggle worked (initial state was already ON)")
else:
    print("WARNING: Relay may not be responding to commands")
    print("Check physical relay for LED indicators")

client.close()
