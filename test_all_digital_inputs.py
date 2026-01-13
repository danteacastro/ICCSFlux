"""
Complete test of all 8 digital inputs on Waveshare Modbus RTU Relay
"""
import time
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

print("Waveshare Modbus RTU Relay - Digital Input Monitor")
print("=" * 60)
print("Reading all 8 digital inputs in real-time...")
print("Press Ctrl+C to stop\n")

try:
    while True:
        # Read all 8 discrete inputs
        result = client.read_discrete_inputs(address=0, count=8, device_id=slave_id)

        if result.isError():
            print(f"ERROR: {result}")
            break

        # Display states
        states = result.bits[:8]
        print(f"\r", end="")
        for i, state in enumerate(states):
            status = "HIGH" if state else "LOW "
            print(f"IN{i+1}:{status} ", end="")
        print(f"  [All: {states}]", end="", flush=True)

        time.sleep(0.2)  # Update 5 times per second

except KeyboardInterrupt:
    print("\n\nStopped.")

finally:
    client.close()
    print("\nDigital Input Summary:")
    print("  8 digital inputs available")
    print("  Addresses: 0-7 (discrete inputs)")
    print("  Function Code: 2 (Read Discrete Inputs)")
    print("  States: LOW=False/0, HIGH=True/1")
