# Modbus Debug & Manual Testing Guide

## Overview

This guide explains how to manually test and validate the Modbus system in NISystem, including connection testing, parameter adjustment, and value validation.

---

## Option 1: Standalone Testing Tool (Recommended)

### Manual Test CLI

Location: `services/daq_service/test_modbus_manual.py`

A standalone interactive tool for testing Modbus connections without running the full DAQ service.

### Usage

```bash
cd services/daq_service
python test_modbus_manual.py
```

### Features

```
=============================================================
  NISystem Modbus Manual Test Tool
=============================================================

Status: ❌ Disconnected

--- Main Menu ---
1. Connect to Modbus TCP device
2. Connect to Modbus RTU device
3. Read holding registers
4. Read input registers
5. Read coils
6. Read discrete inputs
7. Write single coil
8. Write single register
9. Change connection parameters
10. Test connection
11. Disconnect
0. Exit
```

### Example Workflow

#### Test TCP Connection

```
Select option: 1

--- Modbus TCP Connection ---
IP Address [192.168.1.100]: 192.168.1.50
Port [502]: 502
Timeout (sec) [1.0]: 1.0

🔌 Connecting to 192.168.1.50:502...
✅ Connected to 192.168.1.50:502
```

#### Read Holding Registers

```
Select option: 3

--- Read Holding Registers ---
Start Address [0]: 100
Number of Registers [10]: 5
Slave ID [1]: 1

📖 Reading 5 holding registers from address 100 (slave 1)...
✅ Read successful!

Raw registers: [453, 0, 1024, 2048, 512]

Decoded values:
  Address    Dec        Hex        Binary
  --------------------------------------------------
  100        453        0x01C5     0000000111000101
  101        0          0x0000     0000000000000000
  102        1024       0x0400     0000010000000000
  103        2048       0x0800     0000100000000000
  104        512        0x0200     0000001000000000

--- Decoded as Float32 (big endian) ---
  Address 100-101: 45.299999
  Address 102-103: 2.097152
```

#### Write Single Coil

```
Select option: 7

--- Write Single Coil ---
Coil Address [0]: 200
Value (0/1 or ON/OFF) [1]: ON
Slave ID [1]: 1

✍️  Writing coil 200 = ON (slave 1)...
✅ Write successful! Coil 200 set to ON
```

#### Change RTU Baud Rate

```
Select option: 9

--- Change RTU Parameters ---
Current settings:
  Port: COM3
  Baud: 9600
  Parity: E
  Data Bits: 8
  Stop Bits: 1
  Timeout: 1.0s

Reconnect with new parameters:

--- Modbus RTU Connection ---
Serial Port [COM3]: COM3
Baud Rate [9600]: 19200    <-- Change baud rate
Parity (N/E/O) [E]: N      <-- Change parity
Data Bits (7/8) [8]: 8
Stop Bits (1/2) [1]: 1
Timeout (sec) [1.0]: 1.0

🔌 Connecting to COM3 @ 19200 baud...
✅ Connected to COM3 @ 19200 baud (8N1)
```

---

## Option 2: MQTT Manual Commands

Test Modbus operations through MQTT while the DAQ service is running.

### Prerequisites

Install MQTT client (if testing from command line):
```bash
pip install paho-mqtt
```

Or use the NISystem dashboard UI.

### MQTT Topics for Manual Testing

#### Read Holding Registers

**Topic:** `nisystem/nodes/{node_id}/modbus/read`

**Payload:**
```json
{
  "device": "PLC_Main",
  "function": "read_holding",
  "address": 100,
  "count": 10,
  "slave": 1
}
```

**Response Topic:** `nisystem/nodes/{node_id}/modbus/read/result`

**Response Payload:**
```json
{
  "device": "PLC_Main",
  "address": 100,
  "values": [453, 0, 1024, 2048, 512, ...],
  "timestamp": 1704841200,
  "success": true
}
```

#### Write Single Coil

**Topic:** `nisystem/nodes/{node_id}/modbus/write`

**Payload:**
```json
{
  "device": "PLC_Main",
  "function": "write_coil",
  "address": 200,
  "value": true,
  "slave": 1
}
```

**Response Topic:** `nisystem/nodes/{node_id}/modbus/write/result`

**Response Payload:**
```json
{
  "device": "PLC_Main",
  "address": 200,
  "success": true,
  "timestamp": 1704841200
}
```

#### Update Connection Parameters

**Topic:** `nisystem/nodes/{node_id}/modbus/update_params`

**Payload (TCP):**
```json
{
  "device": "PLC_Main",
  "connection_type": "tcp",
  "host": "192.168.1.51",
  "port": 502,
  "timeout": 2.0
}
```

**Payload (RTU):**
```json
{
  "device": "PLC_RTU",
  "connection_type": "rtu",
  "port": "COM3",
  "baudrate": 19200,
  "parity": "N",
  "bytesize": 8,
  "stopbits": 1,
  "timeout": 1.5
}
```

#### Test Connection

**Topic:** `nisystem/nodes/{node_id}/modbus/test`

**Payload:**
```json
{
  "device": "PLC_Main"
}
```

**Response:**
```json
{
  "device": "PLC_Main",
  "connected": true,
  "connection_type": "tcp",
  "connection_info": "192.168.1.100:502",
  "test_result": "OK",
  "timestamp": 1704841200
}
```

---

## Option 3: Python Script for Automated Testing

### Quick Test Script

```python
# quick_test_modbus.py
from pymodbus.client import ModbusTcpClient

# Test TCP connection
client = ModbusTcpClient('192.168.1.100', port=502)

if client.connect():
    print("✅ Connected")

    # Read 10 holding registers
    result = client.read_holding_registers(0, 10, slave=1)
    if not result.isError():
        print(f"✅ Read: {result.registers}")

    # Write coil
    result = client.write_coil(200, True, slave=1)
    if not result.isError():
        print("✅ Write successful")

    client.close()
else:
    print("❌ Connection failed")
```

Run:
```bash
python quick_test_modbus.py
```

### Automated Baud Rate Scanner (RTU)

```python
# scan_baudrates.py
from pymodbus.client import ModbusSerialClient

baud_rates = [9600, 19200, 38400, 57600, 115200]
port = "/dev/ttyUSB0"  # or "COM3" on Windows

print(f"Scanning {port} for correct baud rate...")

for baud in baud_rates:
    print(f"\nTrying {baud} baud...", end=" ")

    client = ModbusSerialClient(
        port=port,
        baudrate=baud,
        parity='E',
        timeout=1.0
    )

    if client.connect():
        try:
            result = client.read_holding_registers(0, 1, slave=1)
            if not result.isError():
                print(f"✅ SUCCESS! Device responds at {baud} baud")
                print(f"   Read value: {result.registers[0]}")
                client.close()
                break
            else:
                print("❌ No response")
        except Exception as e:
            print(f"❌ Error: {e}")
        finally:
            client.close()
    else:
        print("❌ Connection failed")

print("\nScan complete")
```

---

## Validation Checklist

Use this checklist to validate Modbus functionality:

### Connection Testing

- [ ] TCP connection establishes successfully
- [ ] RTU connection establishes successfully
- [ ] Connection status visible in UI
- [ ] Test connection command works
- [ ] Automatic reconnection after disconnect

### Reading Operations

- [ ] Read holding registers (FC 3)
- [ ] Read input registers (FC 4)
- [ ] Read coils (FC 1)
- [ ] Read discrete inputs (FC 2)
- [ ] Values decode correctly (int16, uint16, float32, etc.)
- [ ] Byte order handled correctly
- [ ] Word order handled correctly

### Writing Operations

- [ ] Write single coil (FC 5)
- [ ] Write single register (FC 6)
- [ ] Values write correctly
- [ ] Write confirmation received

### Parameter Changes

- [ ] Change TCP IP address
- [ ] Change TCP port
- [ ] Change RTU baud rate
- [ ] Change RTU parity
- [ ] Change timeout
- [ ] Changes take effect immediately

### Data Publishing

- [ ] Values publish to MQTT
- [ ] Update rate correct (2-10 Hz)
- [ ] Scaling applied correctly
- [ ] Offset applied correctly
- [ ] Quality indicator correct

### Error Handling

- [ ] Timeout errors handled gracefully
- [ ] Connection loss detected
- [ ] Invalid address errors reported
- [ ] Retry logic works
- [ ] Error count increments

---

## Common Validation Scenarios

### Scenario 1: New TCP Device Setup

**Goal:** Verify new PLC responds correctly

**Steps:**
1. Run `python test_modbus_manual.py`
2. Connect to device (option 1)
3. Test connection (option 10)
4. Read registers 0-9 (option 3)
5. Verify values make sense
6. Write test coil (option 7)
7. Read back coil to confirm (option 5)

### Scenario 2: RTU Baud Rate Discovery

**Goal:** Find correct baud rate for unknown device

**Steps:**
1. Run `python scan_baudrates.py`
2. Script tries 9600, 19200, 38400, 57600, 115200
3. Note which baud rate responds
4. Update device configuration in UI

### Scenario 3: Data Type Validation

**Goal:** Verify float32 values decode correctly

**Steps:**
1. Write known value to device (e.g., 25.5)
2. Run `python test_modbus_manual.py`
3. Read registers containing float (option 3)
4. Check "Decoded as Float32" section
5. Verify value matches expected (25.5)
6. Adjust byte/word order if needed

### Scenario 4: Connection Parameter Tuning

**Goal:** Optimize timeout for slow device

**Steps:**
1. Start with default timeout (1.0s)
2. Monitor error count in UI
3. If timeouts occur, increase to 2.0s (option 9)
4. If errors persist, increase to 3.0s
5. If no errors with 3.0s, decrease gradually to find optimum

---

## Logging and Console Output

### Enable Debug Logging

In `daq_service.py`, set:

```python
import logging
logging.basicConfig(
    level=logging.DEBUG,  # Change from INFO to DEBUG
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
```

### View Modbus Logs

**Linux/macOS:**
```bash
tail -f logs/daq_service.log | grep -i modbus
```

**Windows:**
```powershell
Get-Content logs/daq_service.log -Tail 50 -Wait | Select-String -Pattern "modbus"
```

### Example Log Output

```
2026-01-09 10:15:30 - ModbusReader - INFO - Initialized Modbus TCP: PLC_Main -> 192.168.1.100:502
2026-01-09 10:15:31 - ModbusReader - DEBUG - Reading holding register 100 (slave 1)
2026-01-09 10:15:31 - ModbusReader - DEBUG - Read value: 453 (raw)
2026-01-09 10:15:31 - ModbusReader - DEBUG - Scaled value: 45.3
2026-01-09 10:15:31 - ModbusReader - INFO - Published MB_PRESSURE_01 = 45.3 bar
```

---

## Performance Monitoring

### Monitor Read Latency

```python
# monitor_latency.py
import time
from pymodbus.client import ModbusTcpClient

client = ModbusTcpClient('192.168.1.100', port=502)
client.connect()

latencies = []
for i in range(100):
    start = time.time()
    result = client.read_holding_registers(0, 10, slave=1)
    latency = (time.time() - start) * 1000  # Convert to ms
    latencies.append(latency)
    print(f"Read {i+1}/100: {latency:.2f}ms")

print(f"\nAverage latency: {sum(latencies)/len(latencies):.2f}ms")
print(f"Min: {min(latencies):.2f}ms")
print(f"Max: {max(latencies):.2f}ms")

client.close()
```

**Expected Results:**
- TCP: 10-50ms typical, 200ms acceptable
- RTU @ 9600: 50-200ms typical, 500ms acceptable
- RTU @ 115200: 10-50ms typical, 200ms acceptable

---

## Troubleshooting with Manual Tool

### Issue: Cannot Connect

```
Select option: 1
IP Address [192.168.1.100]: 192.168.1.50
Port [502]: 502
🔌 Connecting to 192.168.1.50:502...
❌ Failed to connect to 192.168.1.50:502
```

**Debug Steps:**
1. Ping device: `ping 192.168.1.50`
2. Check firewall: `sudo ufw status`
3. Verify port: `nmap 192.168.1.50 -p 502`
4. Try increasing timeout (option 9)

### Issue: Read Timeout

```
📖 Reading 10 holding registers from address 100 (slave 1)...
❌ Error: Modbus Error: [Timeout] No Response received from the remote unit
```

**Debug Steps:**
1. Increase timeout (option 9, set to 3.0)
2. Reduce register count (try reading 1 register)
3. Check slave ID is correct
4. Verify address exists on device

### Issue: Invalid Data

```
--- Decoded as Float32 (big endian) ---
  Address 100-101: 1.234567e+38  <-- Incorrect!
```

**Debug Steps:**
1. Check byte order (try little endian)
2. Check word order (try different combinations)
3. Verify data type (maybe it's int32 not float32)
4. Check device documentation

---

## Integration with DAQ Service

After manual validation, update the DAQ service configuration:

1. **Update Channel Config:**
   ```json
   {
     "name": "MB_PRESSURE_01",
     "channel_type": "modbus_register",
     "modbus_address": 100,
     "modbus_data_type": "float32",
     "modbus_byte_order": "big",
     "modbus_word_order": "big"
   }
   ```

2. **Restart DAQ Service:**
   ```bash
   cd services/daq_service
   python app.py
   ```

3. **Verify in Dashboard:**
   - Check Overview tab
   - Verify values updating
   - Check connection status (green dot)

---

## Summary

✅ **Standalone Tool** - Interactive CLI for manual testing
✅ **MQTT Commands** - Test within running DAQ service
✅ **Python Scripts** - Automated testing and validation
✅ **Console Output** - Real-time debugging feedback
✅ **Parameter Tuning** - Change baud rate, timeout, etc.
✅ **Value Validation** - Verify data types and scaling

**Recommended Workflow:**
1. Use standalone tool to validate connection and find correct parameters
2. Test specific scenarios with Python scripts
3. Integrate validated settings into DAQ service
4. Use MQTT commands for ongoing operational testing

---

**Last Updated**: January 9, 2026
**Status**: Complete debug tooling available
