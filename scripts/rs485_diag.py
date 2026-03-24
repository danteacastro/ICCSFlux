"""RS-485 adapter diagnostics: loopback test + passive sniffer."""
import serial
import time

PORT = "COM12"

print("=== Adapter loopback test ===")
print("Waveshare USB-RS485 echoes TX in half-duplex — no wiring change needed.")
try:
    s = serial.Serial(PORT, 9600, timeout=0.5)
    s.reset_input_buffer()
    test_bytes = b"\x01\x03\x00\x00\x00\x0A\xC5\xCD"  # FC3: read 10 holding regs from addr 1
    s.write(test_bytes)
    time.sleep(0.5)
    rx = s.read_all()
    s.close()
    print(f"Sent    ({len(test_bytes)} bytes): {test_bytes.hex()}")
    print(f"Received ({len(rx)} bytes): {rx.hex() if rx else '(empty)'}")
    if rx == test_bytes:
        print("=> TX echo seen — adapter + driver working, no device response")
    elif len(rx) > len(test_bytes):
        print("=> Got MORE bytes than sent — device responded!")
        extra = rx[len(test_bytes):]
        print(f"   Device reply bytes: {extra.hex()}")
    elif rx:
        print("=> Got different bytes — investigate further")
    else:
        print("=> No echo and no response — adapter may not be working OR driver issue")
except Exception as e:
    print(f"Error: {e}")

print()
print("=== Passive bus sniffer (2 sec per baud rate) ===")
for baud in [9600, 19200, 4800, 38400, 115200]:
    try:
        s = serial.Serial(PORT, baud, timeout=0.1)
        s.reset_input_buffer()
        data = b""
        t0 = time.time()
        while time.time() - t0 < 2.0:
            chunk = s.read(128)
            if chunk:
                data += chunk
        s.close()
        if data:
            print(f"  {baud:6d} baud: {len(data)} bytes  => {data.hex()}")
        else:
            print(f"  {baud:6d} baud: (silence)")
    except Exception as e:
        print(f"  {baud:6d} baud: error — {e}")

print()
print("=== Modbus broadcast ping (addr 0) ===")
# Some devices respond to broadcast address 0
for baud in [9600, 19200]:
    try:
        s = serial.Serial(PORT, baud, timeout=0.5)
        s.reset_input_buffer()
        # FC3 read 1 holding register from addr 0 (broadcast)
        pkt = b"\x00\x03\x00\x00\x00\x01\x85\xDB"
        s.write(pkt)
        time.sleep(0.3)
        rx = s.read_all()
        s.close()
        if rx and rx != pkt:
            print(f"  {baud} baud addr 0: response {rx.hex()}")
        else:
            print(f"  {baud} baud addr 0: (no response)")
    except Exception as e:
        print(f"  {baud} baud addr 0: error — {e}")
