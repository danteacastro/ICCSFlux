"""Read registers one-at-a-time from devices 101/102/103 at 19200 8N1."""
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

for addr in ADDRS:
    print(f"\n{'='*60}")
    print(f"  Device {addr} — single-register scan")
    print(f"{'='*60}")
    valid = {}
    consecutive_misses = 0
    for reg in range(0, 200):
        pkt = build(addr, 3, reg, 1)
        rx = query(s, pkt)
        if not rx:
            consecutive_misses += 1
            if consecutive_misses > 10:
                break
            continue
        is_exc = len(rx) >= 2 and rx[1] == 0x83
        if is_exc:
            exc = rx[2] if len(rx) > 2 else '?'
            if exc == 2:
                consecutive_misses += 1
                if consecutive_misses > 10 and reg > 10:
                    break
                continue
        elif check_crc(rx) and rx[0] == addr and rx[1] == 3 and len(rx) >= 7:
            consecutive_misses = 0
            u = struct.unpack(">H", rx[3:5])[0]
            s16 = struct.unpack(">h", rx[3:5])[0]
            valid[reg] = (u, s16, rx.hex())

    if not valid:
        print("  No readable registers found.")
    else:
        print(f"  Found {len(valid)} readable register(s):")
        for reg, (u, s16, raw) in sorted(valid.items()):
            print(f"    reg {reg:4d}: uint={u:6d}  int={s16:6d}  /10={u/10:8.1f}  /100={u/100:8.2f}  hex=0x{u:04X}  raw={raw}")

    # Also find max block size the device accepts
    print(f"  Max block read test (from first valid reg):")
    if valid:
        first_reg = min(valid.keys())
        for count in [1, 2, 4, 8, 16, 32]:
            pkt = build(addr, 3, first_reg, count)
            rx = query(s, pkt)
            if rx and check_crc(rx) and rx[0] == addr and rx[1] == 3:
                got = rx[2] // 2
                print(f"    count={count:3d}: OK (got {got} regs)")
            elif rx and len(rx) >= 2 and rx[1] == 0x83:
                print(f"    count={count:3d}: exception {rx[2] if len(rx)>2 else '?'}")
            else:
                print(f"    count={count:3d}: no response / bad")

s.close()
print("\nDone.")
