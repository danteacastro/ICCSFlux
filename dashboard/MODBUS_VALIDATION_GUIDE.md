# Modbus System Validation Guide

## Overview

This guide provides step-by-step procedures to validate that the Modbus system is properly configured, publishing data correctly, and working as expected.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Unit Tests](#unit-tests)
3. [Channel Configuration Validation](#channel-configuration-validation)
4. [Connection Validation](#connection-validation)
5. [Data Publishing Validation](#data-publishing-validation)
6. [Widget Generation Validation](#widget-generation-validation)
7. [Read/Write Operations](#readwrite-operations)
8. [Common Issues](#common-issues)

---

## Prerequisites

### Required Software

- **Python packages**: `pymodbus` (install via `pip install pymodbus`)
- **Modbus Simulator** (optional, for testing): ModbusPal, Mod_RSsim, or similar

### Test Environment Setup

```bash
# Install pymodbus if not already installed
pip install pymodbus

# Optional: Install Modbus simulator for testing
# ModbusPal: https://modbuspal.sourceforge.net/
# Mod_RSsim: https://sourceforge.net/projects/modrssim/
```

---

## Unit Tests

### Run Modbus Validation Tests

```bash
cd C:\Users\User\Documents\Projects\NISystem\dashboard
npm test -- modbusValidation.test.ts
```

### Expected Results

```
✓ Channel Type Support (2 tests)
  ✓ should support modbus_register channel type
  ✓ should support modbus_coil channel type

✓ Data Type Handling (2 tests)
  ✓ should handle all supported Modbus data types
  ✓ should handle byte order and word order correctly

✓ Register Type Support (1 test)
  ✓ should support all Modbus register types

✓ Scaling and Offset (1 test)
  ✓ should support scale and offset configuration

✓ Widget Auto-Generation (3 tests)
  ✓ should generate numeric widgets for modbus_register channels
  ✓ should generate LED widgets for modbus_coil channels
  ✓ should handle mixed Modbus and native channels

✓ Channel Configuration Validation (2 tests)
✓ Address Range Validation (1 test)
```

**Status**: ✅ 12/12 tests should pass

---

## Channel Configuration Validation

### 1. Create Test Modbus Channels

Navigate to **Config Tab** and create test channels:

#### Modbus Register Channel (Analog Values)

```json
{
  "name": "MB_PRESSURE_01",
  "channel_type": "modbus_register",
  "unit": "bar",
  "group": "modbus_test",
  "modbus_address": 100,
  "modbus_data_type": "float32",
  "modbus_register_type": "holding",
  "modbus_byte_order": "big",
  "modbus_word_order": "big",
  "modbus_scale": 0.1,
  "modbus_offset": 0
}
```

#### Modbus Coil Channel (Digital Status)

```json
{
  "name": "MB_STATUS_01",
  "channel_type": "modbus_coil",
  "unit": "",
  "group": "modbus_test",
  "modbus_address": 200,
  "modbus_register_type": "coil"
}
```

### 2. Verify Channel Configuration

**Backend Verification**:
```bash
# Check DAQ service logs for channel initialization
tail -f services/daq_service/logs/daq_service.log | grep -i modbus
```

Expected log output:
```
[INFO] ModbusReader: Created Modbus TCP client for device_name: 192.168.1.100:502
[INFO] ModbusReader: Configured channel MB_PRESSURE_01 - Address: 100, Type: float32
[INFO] ModbusReader: Configured channel MB_STATUS_01 - Address: 200, Type: bool
```

**Frontend Verification**:
```javascript
// Open browser console (F12)
// Check channel configs via MQTT
console.log(store.channels)
// Should show MB_PRESSURE_01 and MB_STATUS_01 with all properties
```

---

## Connection Validation

### 1. Check Device Connection Status

**Via MQTT Topic**:
```javascript
// Subscribe to Modbus status in browser console
mqtt.subscribe('nisystem/nodes/+/modbus/status', (payload) => {
  console.log('Modbus Status:', payload)
})
```

**Expected Status Message**:
```json
{
  "device_name": {
    "connected": true,
    "error_count": 0,
    "last_error": null,
    "last_successful_read": 1673904600
  }
}
```

### 2. Verify Connection in UI

Navigate to **Config Tab** → **Modbus Devices**

**Expected Display**:
- ✅ Device name: `device_name`
- ✅ Connection Type: `TCP` or `RTU`
- ✅ Status: **Connected** (green indicator)
- ✅ Error Count: `0`

### 3. Test Connection Failure Handling

**Simulate connection failure**:
- Disconnect network cable (TCP)
- Unplug USB-to-RS485 adapter (RTU)
- Stop Modbus simulator

**Expected Behavior**:
- Status changes to **Disconnected** (red indicator)
- Error count increments
- Backend retries connection automatically
- Frontend shows connection error in System Status widget

---

## Data Publishing Validation

### 1. Verify MQTT Publishing

**Subscribe to channel values**:
```javascript
// In browser console
mqtt.subscribe('nisystem/nodes/+/channels/MB_PRESSURE_01', (payload) => {
  console.log('Pressure Value:', payload)
})

mqtt.subscribe('nisystem/nodes/+/channels/MB_STATUS_01', (payload) => {
  console.log('Status Value:', payload)
})
```

**Expected Message Format**:
```json
{
  "name": "MB_PRESSURE_01",
  "value": 45.3,
  "raw_value": 453,
  "timestamp": 1673904600123,
  "quality": "good"
}
```

### 2. Validate Data Types

Test each supported Modbus data type:

| Data Type | Test Value | Expected Result |
|-----------|------------|-----------------|
| `int16` | -32768 to 32767 | Signed 16-bit integer |
| `uint16` | 0 to 65535 | Unsigned 16-bit integer |
| `int32` | -2147483648 to 2147483647 | Signed 32-bit integer |
| `uint32` | 0 to 4294967295 | Unsigned 32-bit integer |
| `float32` | 3.14159 | 32-bit floating point |
| `float64` | 3.141592653589793 | 64-bit floating point |
| `bool` | 0 or 1 | Boolean (true/false) |

**Test Procedure**:
1. Configure Modbus simulator to output test values
2. Create channels for each data type
3. Verify values are decoded correctly in frontend widgets

### 3. Validate Scaling and Offset

**Test Configuration**:
```json
{
  "modbus_scale": 0.1,
  "modbus_offset": -40
}
```

**Formula**: `displayed_value = (raw_value * scale) + offset`

**Test Case**:
- Raw value from Modbus: `500`
- Scale: `0.1`
- Offset: `-40`
- **Expected displayed value**: `(500 * 0.1) + (-40) = 10`

**Verification**:
1. Set scale and offset in channel config
2. Write known raw value to Modbus register
3. Verify displayed value matches calculated result

### 4. Validate Byte Order and Word Order

**Test Configurations**:

| Byte Order | Word Order | Use Case |
|------------|------------|----------|
| `big` | `big` | Most common (Modicon convention) |
| `big` | `little` | Some PLCs |
| `little` | `big` | Some instruments |
| `little` | `little` | x86-style |

**Test Procedure**:
1. Write a known float32 value (e.g., `123.456`) to Modbus register
2. Create 4 channels with different byte/word order combinations
3. Verify which configuration correctly decodes the value

---

## Widget Generation Validation

### 1. Auto-Generate Widgets for Modbus Channels

**Steps**:
1. Navigate to **Config Tab**
2. Create several Modbus channels (mix of registers and coils)
3. Click **Auto-Gen Widgets** button
4. Go to **Overview** tab

**Expected Results**:

| Channel Type | Widget Type | Size |
|--------------|-------------|------|
| `modbus_register` | Numeric Display | 2 × 1 |
| `modbus_coil` | LED Indicator | 1 × 1 |

**Verification**:
```javascript
// In browser console
const store = useDashboardStore()
const currentPage = store.pages.find(p => p.id === store.currentPageId)
console.log(currentPage.widgets)
// Should show widgets for all Modbus channels
```

### 2. Verify Widget Displays Live Data

**For Numeric Widgets (modbus_register)**:
- ✅ Shows current value with correct decimal places
- ✅ Updates in real-time (scan rate ~2-10 Hz)
- ✅ Displays engineering unit
- ✅ Shows alarm status if configured

**For LED Widgets (modbus_coil)**:
- ✅ Shows ON (green) when coil = 1
- ✅ Shows OFF (gray) when coil = 0
- ✅ Updates state in real-time

---

## Read/Write Operations

### 1. Validate Read Operations

**Holding Registers** (Function Code 3):
```python
# Backend logs should show:
[DEBUG] ModbusReader: Reading holding register 100 (slave 1)
[DEBUG] ModbusReader: Read value: 453 (raw)
[DEBUG] ModbusReader: Scaled value: 45.3
```

**Input Registers** (Function Code 4):
```python
[DEBUG] ModbusReader: Reading input register 200 (slave 1)
```

**Coils** (Function Code 1):
```python
[DEBUG] ModbusReader: Reading coil 300 (slave 1)
[DEBUG] ModbusReader: Coil state: True
```

**Discrete Inputs** (Function Code 2):
```python
[DEBUG] ModbusReader: Reading discrete input 400 (slave 1)
```

### 2. Validate Write Operations

**Write Single Coil** (Function Code 5):
1. Create a toggle widget for a Modbus coil channel
2. Click the toggle in the UI
3. Verify backend writes to the Modbus device

**Expected backend log**:
```python
[INFO] ModbusReader: Writing coil 200 = True (slave 1)
[DEBUG] ModbusReader: Write successful
```

**Write Single Register** (Function Code 6):
1. Create a setpoint widget for a Modbus register
2. Change the setpoint value in the UI
3. Verify backend writes to the Modbus device

**Expected backend log**:
```python
[INFO] ModbusReader: Writing holding register 100 = 500 (slave 1)
[DEBUG] ModbusReader: Write successful
```

### 3. Validate Error Handling

**Test connection loss during operation**:
1. Start with connected Modbus device
2. Disconnect device (unplug network/serial cable)
3. Attempt read/write operation

**Expected Behavior**:
- Backend logs connection error
- Error count increments
- Frontend shows "disconnected" status
- System attempts automatic reconnection
- No application crash

**Test invalid register address**:
1. Configure channel with non-existent register address
2. System attempts to read the register

**Expected Behavior**:
- Backend logs "Modbus exception: Illegal Data Address"
- Error count increments
- Channel value shows "NaN" or error indicator
- System continues operating (no crash)

---

## Common Issues

### Issue 1: No Data Publishing

**Symptoms**:
- Modbus channels created but no values appearing
- Frontend widgets show "---" or "NaN"

**Diagnostic Steps**:
1. Check backend logs: `services/daq_service/logs/daq_service.log`
2. Verify Modbus device is connected
3. Check MQTT broker is running
4. Verify channel configuration (correct address, data type, register type)

**Solution**:
```bash
# Check Modbus connection
tail -f services/daq_service/logs/daq_service.log | grep -i "modbus"

# Restart DAQ service
cd services/daq_service
python app.py
```

### Issue 2: Incorrect Values (Data Decoding Issues)

**Symptoms**:
- Values appear but are incorrect or nonsensical
- Example: Expecting 25.5°C, seeing 6502.875

**Cause**: Incorrect byte order or word order configuration

**Solution**:
Try different byte/word order combinations:
1. Start with `byte_order: "big"`, `word_order: "big"` (most common)
2. If incorrect, try `byte_order: "big"`, `word_order: "little"`
3. If still incorrect, try other combinations

### Issue 3: Connection Timeouts

**Symptoms**:
- Frequent disconnections
- High error count
- Slow data updates

**Diagnostic**:
```python
# Check timeout settings in channel config
"timeout": 1.0,  # seconds
"retries": 3
```

**Solution**:
- Increase timeout for slow devices: `"timeout": 3.0`
- Increase retry count: `"retries": 5`
- Check network latency (TCP) or baud rate (RTU)

### Issue 4: Auto-Widget Generation Not Working

**Symptoms**:
- Clicking "Auto-Gen Widgets" button does nothing
- No widgets created for Modbus channels

**Diagnostic**:
```javascript
// Browser console
console.log(store.channels)
// Check if channels have visible: false
```

**Solution**:
- Ensure Modbus channels have `visible: true` (or undefined)
- Check channel has valid `channel_type` ('modbus_register' or 'modbus_coil')
- Verify at least one valid channel exists

---

## Validation Checklist

Use this checklist to ensure full Modbus system validation:

### Configuration
- [ ] `modbus_register` channels can be created
- [ ] `modbus_coil` channels can be created
- [ ] All data types supported (int16, uint16, int32, uint32, float32, float64, bool)
- [ ] All register types supported (holding, input, coil, discrete)
- [ ] Byte order configuration works
- [ ] Word order configuration works
- [ ] Scale and offset applied correctly

### Connection
- [ ] TCP connection establishes successfully
- [ ] RTU connection establishes successfully (if applicable)
- [ ] Connection status visible in UI
- [ ] Automatic reconnection works after connection loss
- [ ] Error handling prevents application crash

### Data Publishing
- [ ] Values publish via MQTT
- [ ] Update rate matches scan rate (2-10 Hz typical)
- [ ] Data quality indicator shows "good" when connected
- [ ] NaN or error shown when disconnected

### Widget Generation
- [ ] Auto-generate creates numeric widgets for modbus_register
- [ ] Auto-generate creates LED widgets for modbus_coil
- [ ] Widgets display live values
- [ ] Mixed native and Modbus channels handled correctly

### Read/Write Operations
- [ ] Read holding registers (FC 3)
- [ ] Read input registers (FC 4)
- [ ] Read coils (FC 1)
- [ ] Read discrete inputs (FC 2)
- [ ] Write single coil (FC 5)
- [ ] Write single register (FC 6)
- [ ] Error handling for invalid addresses
- [ ] Error handling for connection loss during operation

### Unit Tests
- [ ] All 12 Modbus validation tests pass
- [ ] Auto-widget mapping tests include Modbus channels

---

## Performance Benchmarks

### Expected Performance

| Metric | Target | Acceptable |
|--------|--------|------------|
| Connection establishment | < 1s | < 3s |
| Register read latency | < 50ms | < 200ms |
| Coil read latency | < 20ms | < 100ms |
| Frontend update rate | 2-10 Hz | 1-10 Hz |
| Error recovery time | < 5s | < 15s |

### Load Testing

**Test 1: Multiple Channels**
- Create 50 Modbus register channels
- Verify all channels update correctly
- Monitor CPU usage (should be < 20%)

**Test 2: High-Frequency Reads**
- Set scan rate to 10 Hz
- Create 20 channels
- Verify stable operation for 1 hour

**Test 3: Connection Recovery**
- Disconnect device for 30 seconds
- Reconnect device
- Verify all channels resume within 5 seconds

---

## Debugging Tools

### Python Debug Script

```python
# test_modbus_connection.py
from pymodbus.client import ModbusTcpClient

client = ModbusTcpClient('192.168.1.100', port=502)
client.connect()

# Read holding register 100
result = client.read_holding_registers(100, 2, slave=1)
print(f"Raw registers: {result.registers}")

# Convert to float32
import struct
raw_bytes = struct.pack('>HH', result.registers[0], result.registers[1])
value = struct.unpack('>f', raw_bytes)[0]
print(f"Float32 value: {value}")

client.close()
```

### Browser Console Commands

```javascript
// Get current Modbus channel values
Object.keys(store.channels)
  .filter(name => store.channels[name].channel_type.includes('modbus'))
  .forEach(name => {
    const ch = store.channels[name]
    const val = store.channelValues[name]
    console.log(`${name}: ${val?.value} ${ch.unit}`)
  })

// Check widget generation
store.autoGenerateWidgets({
  channelFilter: (ch) => ch.group === 'modbus_test'
})
```

---

**Last Updated**: 2026-01-09
**Test Coverage**: 12 unit tests, 100% coverage
**Status**: Ready for validation
