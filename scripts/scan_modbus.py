"""Scan Modbus RTU bus — thorough version with parity combos."""
import sys
from pymodbus.client import ModbusSerialClient

PORTS = ["COM12"]
BAUD_RATES = [1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200]
PARITIES = [('N', 'None'), ('E', 'Even'), ('O', 'Odd')]
SCAN_RANGE = range(1, 248)

# Minimum timeout per baud rate: enough for a 25-byte reply + turnaround
BAUD_TIMEOUT = {
    1200: 1.5,
    2400: 0.8,
    4800: 0.5,
    9600: 0.3,
    19200: 0.2,
    38400: 0.15,
    57600: 0.15,
    115200: 0.1,
}

def try_read(client, addr):
    """Try multiple register types."""
    for attempt in range(2):  # retry once
        try:
            rr = client.read_holding_registers(0, 10, slave=addr)
            if not rr.isError():
                return "holding", rr.registers
        except Exception:
            pass
        
        try:
            rr = client.read_input_registers(0, 10, slave=addr)
            if not rr.isError():
                return "input", rr.registers
        except Exception:
            pass
        
        try:
            rr = client.read_coils(0, 8, slave=addr)
            if not rr.isError():
                return "coils", rr.bits[:8]
        except Exception:
            pass
        
        try:
            rr = client.read_discrete_inputs(0, 8, slave=addr)
            if not rr.isError():
                return "discrete", rr.bits[:8]
        except Exception:
            pass
    
    return None, None

def scan_port(port, baud, parity):
    """Scan a single port/baud/parity combo."""
    found = []
    try:
        client = ModbusSerialClient(
            port=port,
            baudrate=baud,
            parity=parity,
            stopbits=2 if parity == 'N' else 1,
            bytesize=8,
            timeout=BAUD_TIMEOUT.get(baud, 0.3),
        )
        if not client.connect():
            print(f"    Failed to open {port}")
            return found
        
        for addr in SCAN_RANGE:
            reg_type, values = try_read(client, addr)
            if reg_type:
                found.append((addr, reg_type, values))
                print(f"    ** FOUND ** Addr {addr:3d} ({reg_type}): {values}")
                sys.stdout.flush()
            
            if addr % 50 == 0:
                sys.stdout.flush()
        
        client.close()
    except Exception as e:
        print(f"    Error: {e}")
    
    return found

def main():
    all_found = {}
    
    for port in PORTS:
        print(f"\n{'='*60}")
        print(f"Scanning {port}")
        print(f"{'='*60}")
        
        for baud in BAUD_RATES:
            for parity, pname in PARITIES:
                stopbits = 2 if parity == 'N' else 1
                label = f"{baud}/{pname}/{stopbits}stop"
                print(f"\n  {label} — scanning 1-247...", end="", flush=True)
                found = scan_port(port, baud, parity)
                if found:
                    all_found.setdefault(port, []).append((label, found))
                    print(f"  => {len(found)} device(s)")
                else:
                    print(f"  (none)")
    
    print(f"\n{'='*60}")
    print(f"RESULTS")
    print(f"{'='*60}")
    
    if not all_found:
        print("\nNo Modbus RTU devices found on any port/baud/parity combo.")
        print("\nTroubleshooting:")
        print("  - Check RS485 A/B wiring (some hubs swap A/B)")
        print("  - Check termination resistors")  
        print("  - Verify devices have power")
        print("  - Try swapping A and B wires")
        print("  - Check if devices use ASCII mode instead of RTU")
    else:
        for port, results in all_found.items():
            for label, devices in results:
                print(f"\n{port} [{label}]:")
                for addr, reg_type, values in devices:
                    print(f"  Slave {addr:3d}: {reg_type} regs = {values}")

if __name__ == "__main__":
    main()
