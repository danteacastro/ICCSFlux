"""Focused scan: 19200 baud, 8N, try 1 and 2 stop bits, addr 0-247."""
import serial
import struct
import time

PORT = "COM12"
BAUD = 19200
TIMEOUT = 0.5

def crc16(data: bytes) -> bytes:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return struct.pack("<H", crc)

def build_request(addr, fc, start_reg, count):
    pkt = struct.pack(">BBHH", addr, fc, start_reg, count)
    return pkt + crc16(pkt)

def raw_query(port_obj, pkt, wait=TIMEOUT):
    port_obj.reset_input_buffer()
    port_obj.write(pkt)
    time.sleep(wait)
    return port_obj.read_all()

def check_crc(data: bytes) -> bool:
    if len(data) < 4:
        return False
    return crc16(data[:-2]) == data[-2:]

def try_addr(port_obj, addr):
    """Try FC1/2/3/4 at given address. Returns (fc, raw_bytes) or None."""
    for fc in (3, 4, 1, 2):
        count = 1 if fc in (1, 2) else 1
        pkt = build_request(addr, fc, 0, count)
        rx = raw_query(port_obj, pkt)
        # Strip echo if present (adapter may echo TX bytes)
        if rx[:len(pkt)] == pkt:
            rx = rx[len(pkt):]
        if len(rx) >= 4 and rx[0] == addr and check_crc(rx):
            return fc, rx
        if len(rx) >= 3 and rx[0] == addr and rx[1] == (fc | 0x80):
            # Exception response — device exists but rejected the request
            return fc, rx
    return None, None

for stopbits in (1, 2):
    label = f"19200/8N{stopbits}"
    print(f"\n{'='*50}")
    print(f"Scanning {PORT} @ {label} — addresses 0-247")
    print(f"{'='*50}")
    try:
        s = serial.Serial(PORT, BAUD, bytesize=8, parity='N',
                          stopbits=stopbits, timeout=TIMEOUT)
    except Exception as e:
        print(f"  Cannot open port: {e}")
        continue

    found = []
    for addr in range(0, 248):
        fc, rx = try_addr(s, addr)
        if fc is not None:
            is_exception = len(rx) >= 2 and rx[1] == (fc | 0x80)
            label2 = "EXCEPTION" if is_exception else "VALID"
            print(f"  [{label2}] addr={addr}  FC{fc}  raw={rx.hex()}")
            found.append(addr)
        if addr % 50 == 0 and addr > 0:
            print(f"  ... scanned up to addr {addr}")

    s.close()
    if found:
        print(f"\n  => Found devices at addresses: {found}")
    else:
        print(f"\n  => Nothing found at {label}")
