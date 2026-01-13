"""
Test script to read from Waveshare Modbus RTU Relay on COM6
Based on the Waveshare Modbus RTU Relay specifications
"""

import sys
import time
from pymodbus.client import ModbusSerialClient

def test_waveshare_relay():
    """Test connection and read relay states"""

    # Waveshare default settings
    config = {
        'port': 'COM6',
        'baudrate': 9600,
        'parity': 'N',  # None
        'stopbits': 1,
        'bytesize': 8,
        'timeout': 1.0
    }

    print(f"Connecting to Waveshare Modbus RTU Relay...")
    print(f"  Port: {config['port']}")
    print(f"  Baudrate: {config['baudrate']}")
    print(f"  Parity: {config['parity']}")
    print()

    # Create Modbus RTU client
    client = ModbusSerialClient(
        port=config['port'],
        baudrate=config['baudrate'],
        parity=config['parity'],
        stopbits=config['stopbits'],
        bytesize=config['bytesize'],
        timeout=config['timeout']
    )

    try:
        # Connect
        if not client.connect():
            print("ERROR: Failed to connect to COM6")
            print("Check:")
            print("  1. Device is plugged in")
            print("  2. COM6 is the correct port")
            print("  3. No other program is using COM6")
            return False

        print("[OK] Connected successfully!")
        print()

        slave_id = 1  # Default slave ID for Waveshare devices

        # Test 1: Read coils (relay states)
        print("Test 1: Reading relay coil states (addresses 0-7)...")
        try:
            result = client.read_coils(address=0, count=8, device_id=slave_id)
            if result.isError():
                print(f"  ERROR: {result}")
            else:
                print(f"  Relay states: {result.bits[:8]}")
                for i, state in enumerate(result.bits[:8]):
                    print(f"    Relay {i+1}: {'ON' if state else 'OFF'}")
        except Exception as e:
            print(f"  ERROR reading coils: {e}")

        print()

        # Test 2: Read holding registers (device info)
        print("Test 2: Reading holding registers (addresses 0-9)...")
        try:
            result = client.read_holding_registers(address=0, count=10, device_id=slave_id)
            if result.isError():
                print(f"  ERROR: {result}")
            else:
                print(f"  Registers: {result.registers}")
                for i, value in enumerate(result.registers):
                    print(f"    Register {i}: {value} (0x{value:04X})")
        except Exception as e:
            print(f"  ERROR reading registers: {e}")

        print()

        # Test 3: Read input registers
        print("Test 3: Reading input registers (addresses 0-9)...")
        try:
            result = client.read_input_registers(address=0, count=10, device_id=slave_id)
            if result.isError():
                print(f"  ERROR: {result}")
            else:
                print(f"  Input registers: {result.registers}")
                for i, value in enumerate(result.registers):
                    print(f"    Input {i}: {value} (0x{value:04X})")
        except Exception as e:
            print(f"  ERROR reading input registers: {e}")

        print()

        # Test 4: Try to write to a coil (toggle relay 1)
        print("Test 4: Testing relay control (optional - will toggle relay 1)...")
        response = input("  Do you want to test relay control? (y/n): ")
        if response.lower() == 'y':
            print("  Turning relay 1 ON...")
            result = client.write_coil(address=0, value=True, device_id=slave_id)
            if result.isError():
                print(f"    ERROR: {result}")
            else:
                print("    [OK] Relay 1 turned ON")
                time.sleep(1)

                print("  Turning relay 1 OFF...")
                result = client.write_coil(address=0, value=False, device_id=slave_id)
                if result.isError():
                    print(f"    ERROR: {result}")
                else:
                    print("    [OK] Relay 1 turned OFF")

        print()
        print("=" * 60)
        print("Test completed successfully!")
        return True

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        client.close()
        print("Connection closed.")


if __name__ == "__main__":
    print("=" * 60)
    print("Waveshare Modbus RTU Relay Test")
    print("=" * 60)
    print()

    # Check if pymodbus is available
    try:
        import pymodbus
        print(f"pymodbus version: {pymodbus.__version__}")
        print()
    except ImportError:
        print("ERROR: pymodbus not installed")
        print("Install with: pip install pymodbus")
        sys.exit(1)

    test_waveshare_relay()
