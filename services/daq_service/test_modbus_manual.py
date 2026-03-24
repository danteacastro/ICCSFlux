#!/usr/bin/env python3
"""
Manual Modbus Testing Tool for NISystem DAQ Service

This tool allows you to:
- Test Modbus TCP and RTU connections
- Read/write registers and coils
- Change connection parameters dynamically
- Validate published values
- Debug connection issues

Usage:
    python test_modbus_manual.py
"""

import sys
import time
from typing import Optional, List, Tuple
import struct

try:
    from pymodbus.client import ModbusTcpClient, ModbusSerialClient
    from pymodbus.exceptions import ModbusException, ConnectionException
    from pymodbus.pdu import ExceptionResponse
    PYMODBUS_AVAILABLE = True
except ImportError:
    PYMODBUS_AVAILABLE = False
    print("❌ ERROR: pymodbus not installed")
    print("Install with: pip install pymodbus pyserial")
    sys.exit(1)

class ModbusDebugger:
    """Interactive Modbus testing and debugging tool"""

    def __init__(self):
        self.client = None
        self.connection_type = None
        self.config = {}

    def print_header(self):
        """Print tool header"""
        print("\n" + "="*60)
        print("  NISystem Modbus Manual Test Tool")
        print("="*60)
        print()

    def print_menu(self):
        """Print main menu"""
        status = "✅ Connected" if self.client and self.client.is_socket_open() else "❌ Disconnected"
        conn_info = f" ({self.connection_type}: {self.get_connection_info()})" if self.connection_type else ""

        print(f"\nStatus: {status}{conn_info}")
        print("\n--- Main Menu ---")
        print("1. Connect to Modbus TCP device")
        print("2. Connect to Modbus RTU device")
        print("3. Read holding registers")
        print("4. Read input registers")
        print("5. Read coils")
        print("6. Read discrete inputs")
        print("7. Write single coil")
        print("8. Write single register")
        print("9. Change connection parameters")
        print("10. Test connection")
        print("11. Disconnect")
        print("0. Exit")
        print()

    def get_connection_info(self) -> str:
        """Get current connection info string"""
        if self.connection_type == 'tcp':
            return f"{self.config.get('host', '')}:{self.config.get('port', '')}"
        elif self.connection_type == 'rtu':
            return f"{self.config.get('port', '')} @ {self.config.get('baudrate', '')} baud"
        return ""

    def connect_tcp(self):
        """Connect to Modbus TCP device"""
        print("\n--- Modbus TCP Connection ---")
        host = input("IP Address [192.168.1.100]: ").strip() or "192.168.1.100"
        port = input("Port [502]: ").strip() or "502"
        timeout = input("Timeout (sec) [1.0]: ").strip() or "1.0"

        try:
            port = int(port)
            timeout = float(timeout)
        except ValueError:
            print("❌ Invalid port or timeout value")
            return

        print(f"\n🔌 Connecting to {host}:{port}...")

        try:
            self.client = ModbusTcpClient(host=host, port=port, timeout=timeout)

            if self.client.connect():
                self.connection_type = 'tcp'
                self.config = {'host': host, 'port': port, 'timeout': timeout}
                print(f"✅ Connected to {host}:{port}")
            else:
                print(f"❌ Failed to connect to {host}:{port}")
                self.client = None
        except Exception as e:
            print(f"❌ Connection error: {e}")
            self.client = None

    def connect_rtu(self):
        """Connect to Modbus RTU device"""
        print("\n--- Modbus RTU Connection ---")

        # Detect platform for default port
        import platform
        default_port = "COM3" if platform.system() == "Windows" else "/dev/ttyUSB0"

        port = input(f"Serial Port [{default_port}]: ").strip() or default_port
        baudrate = input("Baud Rate [9600]: ").strip() or "9600"
        parity = input("Parity (N/E/O) [E]: ").strip().upper() or "E"
        bytesize = input("Data Bits (7/8) [8]: ").strip() or "8"
        stopbits = input("Stop Bits (1/2) [1]: ").strip() or "1"
        timeout = input("Timeout (sec) [1.0]: ").strip() or "1.0"

        try:
            baudrate = int(baudrate)
            bytesize = int(bytesize)
            stopbits = int(stopbits)
            timeout = float(timeout)
        except ValueError:
            print("❌ Invalid parameter value")
            return

        print(f"\n🔌 Connecting to {port} @ {baudrate} baud...")

        try:
            self.client = ModbusSerialClient(
                port=port,
                baudrate=baudrate,
                parity=parity,
                stopbits=stopbits,
                bytesize=bytesize,
                timeout=timeout
            )

            if self.client.connect():
                self.connection_type = 'rtu'
                self.config = {
                    'port': port,
                    'baudrate': baudrate,
                    'parity': parity,
                    'bytesize': bytesize,
                    'stopbits': stopbits,
                    'timeout': timeout
                }
                print(f"✅ Connected to {port} @ {baudrate} baud ({bytesize}{parity}{stopbits})")
            else:
                print(f"❌ Failed to connect to {port}")
                self.client = None
        except Exception as e:
            print(f"❌ Connection error: {e}")
            self.client = None

    def check_connection(self) -> bool:
        """Check if connected"""
        if not self.client or not self.client.is_socket_open():
            print("❌ Not connected. Please connect first (option 1 or 2)")
            return False
        return True

    def read_holding_registers(self):
        """Read holding registers"""
        if not self.check_connection():
            return

        print("\n--- Read Holding Registers ---")
        address = input("Start Address [0]: ").strip() or "0"
        count = input("Number of Registers [10]: ").strip() or "10"
        slave = input("Slave ID [1]: ").strip() or "1"

        try:
            address = int(address)
            count = int(count)
            slave = int(slave)
        except ValueError:
            print("❌ Invalid parameter value")
            return

        print(f"\n📖 Reading {count} holding registers from address {address} (slave {slave})...")

        try:
            result = self.client.read_holding_registers(address, count, slave=slave)

            if result.isError():
                print(f"❌ Read error: {result}")
            else:
                print(f"✅ Read successful!")
                print(f"\nRaw registers: {result.registers}")
                print("\nDecoded values:")
                print(f"  {'Address':<10} {'Dec':<10} {'Hex':<10} {'Binary':<20}")
                print("  " + "-"*50)
                for i, value in enumerate(result.registers):
                    addr = address + i
                    print(f"  {addr:<10} {value:<10} 0x{value:04X}    {format(value, '016b')}")

                # Try to decode as float32 if we have at least 2 registers
                if len(result.registers) >= 2:
                    print("\n--- Decoded as Float32 (big endian) ---")
                    for i in range(0, len(result.registers) - 1, 2):
                        addr = address + i
                        raw_bytes = struct.pack('>HH', result.registers[i], result.registers[i+1])
                        float_val = struct.unpack('>f', raw_bytes)[0]
                        print(f"  Address {addr}-{addr+1}: {float_val:.6f}")

        except Exception as e:
            print(f"❌ Error: {e}")

    def read_input_registers(self):
        """Read input registers"""
        if not self.check_connection():
            return

        print("\n--- Read Input Registers ---")
        address = input("Start Address [0]: ").strip() or "0"
        count = input("Number of Registers [10]: ").strip() or "10"
        slave = input("Slave ID [1]: ").strip() or "1"

        try:
            address = int(address)
            count = int(count)
            slave = int(slave)
        except ValueError:
            print("❌ Invalid parameter value")
            return

        print(f"\n📖 Reading {count} input registers from address {address} (slave {slave})...")

        try:
            result = self.client.read_input_registers(address, count, slave=slave)

            if result.isError():
                print(f"❌ Read error: {result}")
            else:
                print(f"✅ Read successful!")
                print(f"\nRaw registers: {result.registers}")
                print("\nDecoded values:")
                print(f"  {'Address':<10} {'Dec':<10} {'Hex':<10} {'Binary':<20}")
                print("  " + "-"*50)
                for i, value in enumerate(result.registers):
                    addr = address + i
                    print(f"  {addr:<10} {value:<10} 0x{value:04X}    {format(value, '016b')}")

        except Exception as e:
            print(f"❌ Error: {e}")

    def read_coils(self):
        """Read coils"""
        if not self.check_connection():
            return

        print("\n--- Read Coils ---")
        address = input("Start Address [0]: ").strip() or "0"
        count = input("Number of Coils [10]: ").strip() or "10"
        slave = input("Slave ID [1]: ").strip() or "1"

        try:
            address = int(address)
            count = int(count)
            slave = int(slave)
        except ValueError:
            print("❌ Invalid parameter value")
            return

        print(f"\n📖 Reading {count} coils from address {address} (slave {slave})...")

        try:
            result = self.client.read_coils(address, count, slave=slave)

            if result.isError():
                print(f"❌ Read error: {result}")
            else:
                print(f"✅ Read successful!")
                print(f"\nCoil states: {result.bits[:count]}")
                print("\nDecoded values:")
                print(f"  {'Address':<10} {'State':<10}")
                print("  " + "-"*25)
                for i, state in enumerate(result.bits[:count]):
                    addr = address + i
                    state_str = "ON (1)" if state else "OFF (0)"
                    print(f"  {addr:<10} {state_str}")

        except Exception as e:
            print(f"❌ Error: {e}")

    def read_discrete_inputs(self):
        """Read discrete inputs"""
        if not self.check_connection():
            return

        print("\n--- Read Discrete Inputs ---")
        address = input("Start Address [0]: ").strip() or "0"
        count = input("Number of Inputs [10]: ").strip() or "10"
        slave = input("Slave ID [1]: ").strip() or "1"

        try:
            address = int(address)
            count = int(count)
            slave = int(slave)
        except ValueError:
            print("❌ Invalid parameter value")
            return

        print(f"\n📖 Reading {count} discrete inputs from address {address} (slave {slave})...")

        try:
            result = self.client.read_discrete_inputs(address, count, slave=slave)

            if result.isError():
                print(f"❌ Read error: {result}")
            else:
                print(f"✅ Read successful!")
                print(f"\nInput states: {result.bits[:count]}")
                print("\nDecoded values:")
                print(f"  {'Address':<10} {'State':<10}")
                print("  " + "-"*25)
                for i, state in enumerate(result.bits[:count]):
                    addr = address + i
                    state_str = "ON (1)" if state else "OFF (0)"
                    print(f"  {addr:<10} {state_str}")

        except Exception as e:
            print(f"❌ Error: {e}")

    def write_single_coil(self):
        """Write single coil"""
        if not self.check_connection():
            return

        print("\n--- Write Single Coil ---")
        address = input("Coil Address [0]: ").strip() or "0"
        value = input("Value (0/1 or ON/OFF) [1]: ").strip() or "1"
        slave = input("Slave ID [1]: ").strip() or "1"

        try:
            address = int(address)
            slave = int(slave)

            # Parse value
            if value.upper() in ('ON', '1', 'TRUE'):
                value = True
            elif value.upper() in ('OFF', '0', 'FALSE'):
                value = False
            else:
                print("❌ Invalid value. Use 0/1 or ON/OFF")
                return
        except ValueError:
            print("❌ Invalid parameter value")
            return

        state_str = "ON" if value else "OFF"
        print(f"\n✍️  Writing coil {address} = {state_str} (slave {slave})...")

        try:
            result = self.client.write_coil(address, value, slave=slave)

            if result.isError():
                print(f"❌ Write error: {result}")
            else:
                print(f"✅ Write successful! Coil {address} set to {state_str}")

        except Exception as e:
            print(f"❌ Error: {e}")

    def write_single_register(self):
        """Write single register"""
        if not self.check_connection():
            return

        print("\n--- Write Single Register ---")
        address = input("Register Address [0]: ").strip() or "0"
        value = input("Value (0-65535) [100]: ").strip() or "100"
        slave = input("Slave ID [1]: ").strip() or "1"

        try:
            address = int(address)
            value = int(value)
            slave = int(slave)

            if value < 0 or value > 65535:
                print("❌ Value must be 0-65535")
                return
        except ValueError:
            print("❌ Invalid parameter value")
            return

        print(f"\n✍️  Writing register {address} = {value} (slave {slave})...")

        try:
            result = self.client.write_register(address, value, slave=slave)

            if result.isError():
                print(f"❌ Write error: {result}")
            else:
                print(f"✅ Write successful! Register {address} set to {value} (0x{value:04X})")

        except Exception as e:
            print(f"❌ Error: {e}")

    def change_parameters(self):
        """Change connection parameters"""
        if self.connection_type == 'tcp':
            print("\n--- Change TCP Parameters ---")
            print("Current settings:")
            print(f"  Host: {self.config['host']}")
            print(f"  Port: {self.config['port']}")
            print(f"  Timeout: {self.config['timeout']}s")
            print("\nReconnect with new parameters:")
            self.disconnect()
            self.connect_tcp()

        elif self.connection_type == 'rtu':
            print("\n--- Change RTU Parameters ---")
            print("Current settings:")
            print(f"  Port: {self.config['port']}")
            print(f"  Baud: {self.config['baudrate']}")
            print(f"  Parity: {self.config['parity']}")
            print(f"  Data Bits: {self.config['bytesize']}")
            print(f"  Stop Bits: {self.config['stopbits']}")
            print(f"  Timeout: {self.config['timeout']}s")
            print("\nReconnect with new parameters:")
            self.disconnect()
            self.connect_rtu()
        else:
            print("❌ Not connected")

    def test_connection(self):
        """Test current connection"""
        if not self.check_connection():
            return

        print("\n--- Connection Test ---")
        print(f"Connection type: {self.connection_type.upper()}")
        print(f"Connection info: {self.get_connection_info()}")
        print("\nAttempting to read register 0...")

        try:
            result = self.client.read_holding_registers(0, 1, slave=1)
            if result.isError():
                print(f"❌ Test failed: {result}")
            else:
                print(f"✅ Connection OK! Read value: {result.registers[0]}")
        except Exception as e:
            print(f"❌ Test failed: {e}")

    def disconnect(self):
        """Disconnect from device"""
        if self.client:
            try:
                self.client.close()
                print("✅ Disconnected")
            except Exception as e:
                print(f"⚠️  Disconnect error: {e}")
            finally:
                self.client = None
                self.connection_type = None
                self.config = {}
        else:
            print("Already disconnected")

    def run(self):
        """Main loop"""
        self.print_header()

        while True:
            self.print_menu()
            choice = input("Select option: ").strip()

            if choice == '1':
                self.connect_tcp()
            elif choice == '2':
                self.connect_rtu()
            elif choice == '3':
                self.read_holding_registers()
            elif choice == '4':
                self.read_input_registers()
            elif choice == '5':
                self.read_coils()
            elif choice == '6':
                self.read_discrete_inputs()
            elif choice == '7':
                self.write_single_coil()
            elif choice == '8':
                self.write_single_register()
            elif choice == '9':
                self.change_parameters()
            elif choice == '10':
                self.test_connection()
            elif choice == '11':
                self.disconnect()
            elif choice == '0':
                print("\n👋 Goodbye!")
                if self.client:
                    self.disconnect()
                break
            else:
                print("❌ Invalid option")

            input("\nPress Enter to continue...")

if __name__ == '__main__':
    if not PYMODBUS_AVAILABLE:
        sys.exit(1)

    debugger = ModbusDebugger()
    try:
        debugger.run()
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        if debugger.client:
            debugger.disconnect()
        sys.exit(0)
