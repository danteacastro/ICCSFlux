"""Find valid register start addresses on devices 101/102/103."""
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

def query(s, pkt, timeout=0.4):
    s.reset_input_buffer()
    s.write(pkt)
    time.sleep(timeout)
    rx = s.read_all()
    if rx[:len(pkt)] == pkt:
        rx = rx[len(pkt):]
    return rx

def check_crc(data):
    return len(data) >= 4 and crc16(data[:-2]) == data[-2:]

s = serial.Serial(PORT, BAUD, bytesize=8, parity='N', stopbits=1, timeout=0.4)

# Common register base addresses used by industrial devices
# Standard: 0x0000, 1-based: 0x0001, 40001-style: 0x0000 (FC3 implies 4xxxx)
# Many sensors start at 0x0000, 0x0001, 0x0064 (100), 0x0100, 0x1000, 0x2000, 0x3000

STARTS = list(range(0, 50)) + [100, 200, 256, 512, 1000, 4096, 8192, 0x1000, 0x2000, 0x3000, 0x4000]

for addr in ADDRS:
    print(f"\n{'='*50}")
    print(f"Device addr {addr} — scanning register start addresses")
    print(f"{'='*50}")
    found_any = False
    for start in STARTS:
        pkt = build(addr, 3, start, 1)
        rx = query(s, pkt)
        if not rx:
            continue
        is_exc = len(rx) >= 2 and rx[1] == (3 | 0x80)
        if is_exc:
            exc = rx[2] if len(rx) > 2 else '?'
            if exc == 2:
                pass  # illegal address, keep scanning
            else:
                print(f"  reg {start:5d} (0x{start:04X}): exception {exc}")
        elif check_crc(rx) and rx[0] == addr and rx[1] == 3:
            byte_count = rx[2]
            raw = rx[3:3+byte_count]
            regs = [struct.unpack(">H", raw[i:i+2])[0] for i in range(0, len(raw)-1, 2)]
            print(f"  reg {start:5d} (0x{start:04X}): OK  => {regs}  raw={rx.hex()}")
            found_any = True
        else:
            print(f"  reg {start:5d} (0x{start:04X}): unexpected: {rx.hex()}")

    if not found_any:
        print(f"  No readable registers found — trying FC3 read of 1 reg from start 0 with count sweep...")
        # Try reading different counts from register 0
        for count in [1, 2, 4, 8, 16, 32, 64]:
            pkt = build(addr, 3, 0, count)
            rx = query(s, pkt)
            if rx and not (len(rx) >= 2 and rx[1] == 0x83):
                print(f"    count={count}: {rx.hex()}")

s.close()
print("\nDone.")
