"""Probe known Modbus addresses 101/102/103 at 19200 8N1, read all register types."""
import serial
import struct
import time

PORT = "COM12"
BAUD = 19200
ADDRS = [101, 102, 103]

def crc16(data: bytes) -> bytes:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return struct.pack("<H", crc)

def build(addr, fc, start, count):
    pkt = struct.pack(">BBHH", addr, fc, start, count)
    return pkt + crc16(pkt)

def query(s, pkt, timeout=0.5):
    s.reset_input_buffer()
    s.write(pkt)
    time.sleep(timeout)
    rx = s.read_all()
    # Strip echo
    if rx[:len(pkt)] == pkt:
        rx = rx[len(pkt):]
    return rx

def check_crc(data):
    return len(data) >= 4 and crc16(data[:-2]) == data[-2:]

def decode_registers(rx, fc):
    if fc in (3, 4):
        if len(rx) >= 3:
            byte_count = rx[2]
            regs_raw = rx[3:3+byte_count]
            regs = [struct.unpack(">H", regs_raw[i:i+2])[0] for i in range(0, len(regs_raw)-1, 2)]
            return regs
    elif fc in (1, 2):
        if len(rx) >= 3:
            return list(rx[3:3+rx[2]])
    return []

for stopbits in (1, 2):
    print(f"\n{'='*55}")
    print(f"  19200 / 8N{stopbits} — probing addrs 101, 102, 103")
    print(f"{'='*55}")
    try:
        s = serial.Serial(PORT, BAUD, bytesize=8, parity='N',
                          stopbits=stopbits, timeout=0.5)
    except Exception as e:
        print(f"  Cannot open {PORT}: {e}")
        continue

    for addr in ADDRS:
        print(f"\n  -- Address {addr} --")
        for fc, label, start, count in [
            (3, "Holding regs 0-19",  0, 20),
            (4, "Input regs   0-19",  0, 20),
            (1, "Coils        0-15",  0, 16),
            (2, "Discrete in  0-15",  0, 16),
        ]:
            pkt = build(addr, fc, start, count)
            rx = query(s, pkt)
            if not rx:
                print(f"    FC{fc:02d} ({label}): (no response)")
                continue
            is_exc = len(rx) >= 2 and rx[1] == (fc | 0x80)
            if is_exc:
                exc_code = rx[2] if len(rx) > 2 else '?'
                print(f"    FC{fc:02d} ({label}): EXCEPTION code {exc_code} — device exists, rejected request")
            elif check_crc(rx) and rx[0] == addr:
                vals = decode_registers(rx, fc)
                print(f"    FC{fc:02d} ({label}): OK  {vals}")
                print(f"           raw: {rx.hex()}")
            else:
                print(f"    FC{fc:02d} ({label}): bad/partial: {rx.hex()}")

    s.close()
