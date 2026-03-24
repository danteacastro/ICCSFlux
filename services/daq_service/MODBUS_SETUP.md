# Modbus Setup Guide for NISystem DAQ Service

## Quick Start

### 1. Install Dependencies

```bash
cd services/daq_service
pip install -r requirements.txt
```

This will install:
- `pymodbus>=3.0.0` - Modbus TCP and RTU support
- `pyserial>=3.5` - Serial port communication (for RTU)
- Other required packages

### 2. Verify Installation

```bash
python -c "from pymodbus.client import ModbusTcpClient, ModbusSerialClient; print('Modbus support: OK')"
```

Expected output:
```
Modbus support: OK
```

---

## Connection Types

### Modbus TCP (Ethernet)

**Requirements:**
- ✅ `pymodbus` only
- Network connectivity to device
- Device IP address and port (default: 502)

**Configuration:**
```python
from pymodbus.client import ModbusTcpClient

client = ModbusTcpClient(
    host='192.168.1.100',
    port=502,
    timeout=1.0
)
```

### Modbus RTU (Serial)

**Requirements:**
- ✅ `pymodbus` + `pyserial`
- Serial port (USB-to-RS485 adapter or native serial)
- Correct baud rate, parity, data/stop bits

**Configuration:**
```python
from pymodbus.client import ModbusSerialClient

client = ModbusSerialClient(
    port='/dev/ttyUSB0',  # or 'COM3' on Windows
    baudrate=9600,
    parity='E',
    stopbits=1,
    bytesize=8,
    timeout=1.0
)
```

---

## Serial Port Permissions (Linux)

If you get "Permission denied" errors when accessing serial ports:

```bash
# Add your user to the dialout group
sudo usermod -a -G dialout $USER

# Log out and log back in for changes to take effect
```

Or run the service with sudo (not recommended for production):
```bash
sudo python app.py
```

---

## Testing Connection

### Test Script for TCP

```python
# test_modbus_tcp.py
from pymodbus.client import ModbusTcpClient

client = ModbusTcpClient('192.168.1.100', port=502)

if client.connect():
    print("✅ Connected to Modbus TCP device")

    # Read holding registers 0-9
    result = client.read_holding_registers(0, 10, slave=1)
    if not result.isError():
        print(f"✅ Read successful: {result.registers}")
    else:
        print(f"❌ Read error: {result}")

    client.close()
else:
    print("❌ Connection failed")
```

Run:
```bash
python test_modbus_tcp.py
```

### Test Script for RTU

```python
# test_modbus_rtu.py
from pymodbus.client import ModbusSerialClient

client = ModbusSerialClient(
    port='/dev/ttyUSB0',  # or 'COM3'
    baudrate=9600,
    parity='E',
    stopbits=1,
    bytesize=8,
    timeout=1.0
)

if client.connect():
    print("✅ Connected to Modbus RTU device")

    # Read holding registers 0-9
    result = client.read_holding_registers(0, 10, slave=1)
    if not result.isError():
        print(f"✅ Read successful: {result.registers}")
    else:
        print(f"❌ Read error: {result}")

    client.close()
else:
    print("❌ Connection failed")
```

Run:
```bash
python test_modbus_rtu.py
```

---

## Common Issues

### Issue 1: ModuleNotFoundError: No module named 'pymodbus'

**Solution:**
```bash
pip install pymodbus>=3.0.0
```

### Issue 2: ModuleNotFoundError: No module named 'serial'

**Solution:**
```bash
pip install pyserial>=3.5
```

### Issue 3: Permission denied: '/dev/ttyUSB0'

**Solution:**
```bash
sudo usermod -a -G dialout $USER
# Then log out and log back in
```

Or check current permissions:
```bash
ls -l /dev/ttyUSB0
```

### Issue 4: "Port not found" on Windows

**Solution:**
1. Open Device Manager
2. Check "Ports (COM & LPT)"
3. Note the COM port number (e.g., COM3)
4. Use that port in configuration

### Issue 5: Connection timeout

**TCP:**
- Check firewall: `sudo ufw allow 502` (Linux)
- Test ping: `ping 192.168.1.100`
- Verify device is powered on and connected to network

**RTU:**
- Check baud rate matches device
- Check parity settings
- Check RS-485 wiring (A/B terminals)
- Check termination resistors (120Ω at each end)

---

## Hardware Examples

### Waveshare Modbus RTU Relay

**Connection:** USB-to-RS485 adapter
**Default Settings:**
- Baud rate: 9600
- Parity: None (N)
- Data bits: 8
- Stop bits: 1
- Slave ID: 1

**Configuration:**
```python
client = ModbusSerialClient(
    port='/dev/ttyUSB0',
    baudrate=9600,
    parity='N',
    stopbits=1,
    bytesize=8,
    timeout=1.0
)
```

### Allen-Bradley PLC (Modbus TCP)

**Connection:** Ethernet
**Default Settings:**
- Port: 502
- Slave ID: 1

**Configuration:**
```python
client = ModbusTcpClient(
    host='192.168.1.50',
    port=502,
    timeout=1.0
)
```

---

## Development Workflow

### 1. Add Modbus Device in UI

1. Open NISystem dashboard
2. Go to Configuration tab
3. Scroll to "Modbus Devices" section
4. Click "Add Device"
5. Fill in connection details (TCP or RTU)
6. Click "Add Device"

### 2. Add Modbus Channels

1. In Configuration tab, click "Add Channel"
2. Set:
   - Channel Type: `modbus_register` or `modbus_coil`
   - Modbus Address: Register/coil address
   - Data Type: `int16`, `uint16`, `int32`, `uint32`, `float32`, `float64`, `bool`
   - Register Type: `holding`, `input`, `coil`, `discrete`
3. Click "Add"

### 3. Test Connection

1. In "Modbus Devices" section, expand the device
2. Click "Test Connection"
3. Check status indicator (green = connected, gray = disconnected)

### 4. Verify Data Flow

1. Go to Overview tab
2. Check if channel values are updating
3. If not, check backend logs: `tail -f logs/daq_service.log | grep -i modbus`

---

## Logs and Debugging

### Enable Modbus Logging

In `daq_service.py`, set logging level:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Check Logs

```bash
tail -f logs/daq_service.log | grep -i modbus
```

Expected log entries:
```
[INFO] ModbusReader: Initialized Modbus TCP: PLC_Main -> 192.168.1.100:502
[INFO] ModbusReader: Configured channel MB_PRESSURE_01 - Address: 100, Type: float32
[DEBUG] ModbusReader: Reading holding register 100 (slave 1)
[DEBUG] ModbusReader: Read value: 453 (raw), Scaled: 45.3
```

---

## Production Checklist

- [ ] `pymodbus>=3.0.0` installed
- [ ] `pyserial>=3.5` installed (if using RTU)
- [ ] Serial port permissions configured (Linux)
- [ ] Devices added via UI
- [ ] Channels configured with correct addresses
- [ ] Connection status shows "Connected"
- [ ] Channel values updating in real-time
- [ ] Test connection successful
- [ ] Logs show no errors

---

**Last Updated**: January 9, 2026
**Status**: Production-ready
