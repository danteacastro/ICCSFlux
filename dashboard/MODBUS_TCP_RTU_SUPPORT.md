# Modbus TCP vs RTU Support in NISystem

## Overview

NISystem fully supports both **Modbus TCP** (Ethernet) and **Modbus RTU** (Serial RS-485/RS-232) connections with proper differentiation at both frontend and backend layers.

---

## Frontend Support

### ModbusDeviceConfig Component

Location: [`dashboard/src/components/ModbusDeviceConfig.vue`](../src/components/ModbusDeviceConfig.vue)

#### Connection Type Selection

The UI provides a dropdown to select between TCP and RTU:

```vue
<select v-model="deviceForm.connection_type">
  <option value="tcp">Modbus TCP (Ethernet)</option>
  <option value="rtu">Modbus RTU (Serial)</option>
</select>
```

#### TCP-Specific Configuration

When `connection_type === 'tcp'`, the UI shows:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| IP Address | text | `192.168.1.100` | Device IP address |
| Port | number | `502` | Modbus TCP port (standard: 502) |

```vue
<template v-if="deviceForm.connection_type === 'tcp'">
  <div class="form-group">
    <h4>TCP Connection</h4>
    <input v-model="deviceForm.ip_address" placeholder="192.168.1.100" />
    <input v-model.number="deviceForm.port" type="number" min="1" max="65535" />
  </div>
</template>
```

#### RTU-Specific Configuration

When `connection_type === 'rtu'`, the UI shows:

| Field | Type | Options | Default | Description |
|-------|------|---------|---------|-------------|
| Serial Port | text | - | `/dev/ttyUSB0` | COM port (Windows: COM3, Linux: /dev/ttyUSB0) |
| Baud Rate | select | 9600, 19200, 38400, 57600, 115200 | `9600` | Communication speed |
| Parity | select | N (None), E (Even), O (Odd) | `E` (Even) | Parity bit |
| Data Bits | select | 7, 8 | `8` | Data bits per byte |
| Stop Bits | select | 1, 2 | `1` | Stop bits |

```vue
<template v-else>
  <div class="form-group">
    <h4>Serial Connection</h4>
    <input v-model="deviceForm.serial_port" placeholder="/dev/ttyUSB0 or COM3" />

    <select v-model.number="deviceForm.baudrate">
      <option :value="9600">9600</option>
      <option :value="19200">19200</option>
      <option :value="38400">38400</option>
      <option :value="57600">57600</option>
      <option :value="115200">115200</option>
    </select>

    <select v-model="deviceForm.parity">
      <option value="N">None</option>
      <option value="E">Even</option>
      <option value="O">Odd</option>
    </select>

    <select v-model.number="deviceForm.bytesize">
      <option :value="7">7</option>
      <option :value="8">8</option>
    </select>

    <select v-model.number="deviceForm.stopbits">
      <option :value="1">1</option>
      <option :value="2">2</option>
    </select>
  </div>
</template>
```

#### Common Settings (Both TCP and RTU)

| Field | Type | Range | Default | Description |
|-------|------|-------|---------|-------------|
| Timeout | number | 0.1 - 30 | `1.0` | Connection timeout (seconds) |
| Retries | number | 0 - 10 | `3` | Retry attempts on failure |

#### Data Sent to Backend

The frontend sends device configuration via MQTT topic `chassis/add` or `chassis/update`:

**TCP Payload:**
```json
{
  "name": "PLC_Main",
  "type": "modbus_device",
  "connection": "TCP",
  "enabled": true,
  "ip_address": "192.168.1.100",
  "modbus_port": 502,
  "modbus_timeout": 1.0,
  "modbus_retries": 3
}
```

**RTU Payload:**
```json
{
  "name": "PLC_RTU",
  "type": "modbus_device",
  "connection": "RTU",
  "enabled": true,
  "serial": "COM3",
  "modbus_baudrate": 9600,
  "modbus_parity": "E",
  "modbus_stopbits": 1,
  "modbus_bytesize": 8,
  "modbus_timeout": 1.0,
  "modbus_retries": 3
}
```

---

## Backend Support

### ModbusReader Class

Location: [`services/daq_service/modbus_reader.py`](../services/daq_service/modbus_reader.py)

#### Connection Type Detection

The backend automatically detects connection type from chassis configuration:

```python
conn_type = chassis.connection.upper()
if conn_type not in ("TCP", "RTU", "MODBUS_TCP", "MODBUS_RTU"):
    continue

# Determine connection type
is_tcp = conn_type in ("TCP", "MODBUS_TCP")
```

#### ModbusDeviceConfig Creation

```python
device_config = ModbusDeviceConfig(
    name=name,
    connection_type="tcp" if is_tcp else "rtu",
    # TCP settings
    ip_address=chassis.ip_address if is_tcp else "",
    port=getattr(chassis, 'modbus_port', 502),
    # RTU settings - serial is the COM port
    serial_port=chassis.serial if not is_tcp else "",
    baudrate=getattr(chassis, 'modbus_baudrate', 9600),
    parity=getattr(chassis, 'modbus_parity', 'E'),
    stopbits=getattr(chassis, 'modbus_stopbits', 1),
    bytesize=getattr(chassis, 'modbus_bytesize', 8),
    # Common settings
    timeout=getattr(chassis, 'modbus_timeout', 1.0),
    retries=getattr(chassis, 'modbus_retries', 3),
    slave_id=1
)
```

#### Connection Initialization

**TCP Connection:**
```python
if is_tcp:
    self.client = ModbusTcpClient(
        host=self.config.ip_address,
        port=self.config.port,
        timeout=self.config.timeout
    )
    logger.info(f"Initialized Modbus TCP: {name} -> {ip}:{port}")
```

**RTU Connection:**
```python
else:
    self.client = ModbusSerialClient(
        port=self.config.serial_port,      # COM3, /dev/ttyUSB0
        baudrate=self.config.baudrate,
        parity=self.config.parity,
        stopbits=self.config.stopbits,
        bytesize=self.config.bytesize,
        timeout=self.config.timeout
    )
    logger.info(f"Initialized Modbus RTU: {name} -> {serial_port} @ {baudrate} baud")
```

---

## Python Dependencies

### Required Packages

Add to [`services/daq_service/requirements.txt`](../services/daq_service/requirements.txt):

```txt
# Modbus TCP/RTU support
pymodbus>=3.0.0    # Modbus protocol (TCP + RTU)
pyserial>=3.5      # Serial port communication (required for RTU)
```

### Installation

```bash
cd services/daq_service
pip install -r requirements.txt
```

Or install directly:

```bash
pip install pymodbus>=3.0.0 pyserial>=3.5
```

### Package Dependencies

| Package | Used By | Purpose |
|---------|---------|---------|
| **pymodbus** | Both TCP and RTU | Modbus protocol implementation |
| **pyserial** | RTU only | Serial port (COM/ttyUSB) communication |

- `ModbusTcpClient` only needs `pymodbus`
- `ModbusSerialClient` needs both `pymodbus` **and** `pyserial`

---

## Channel Configuration

### TypeScript Types

From [`dashboard/src/types/index.ts`](../src/types/index.ts):

```typescript
export interface ChannelConfig {
  name: string
  channel_type: 'modbus_register' | 'modbus_coil'
  physical_channel?: string  // Connection identifier
  unit: string
  group: string

  // Modbus-specific
  modbus_register_type?: 'holding' | 'input' | 'coil' | 'discrete'
  modbus_address?: number
  modbus_data_type?: 'int16' | 'uint16' | 'int32' | 'uint32' | 'float32' | 'float64' | 'bool'
  modbus_byte_order?: 'big' | 'little'
  modbus_word_order?: 'big' | 'little'
  modbus_scale?: number
  modbus_offset?: number
}
```

### Physical Channel Formats

Two formats are supported:

#### Format 1: Legacy (currently used by backend)

```
modbus:holding:100
modbus:input:200
modbus:coil:300
modbus:discrete:400
```

#### Format 2: URI-style (used in tests, future enhancement)

**TCP:**
```
modbus_tcp://192.168.1.100:502
modbus_tcp://192.168.1.101:5502
```

**RTU:**
```
modbus_rtu://COM3:9600:8:E:1
modbus_rtu:///dev/ttyUSB0:19200:8:N:1
```

Format: `modbus_rtu://<port>:<baud>:<databits>:<parity>:<stopbits>`

---

## Visual Indicators

### Frontend UI

The ModbusDeviceConfig component shows connection type visually:

**TCP Devices:**
- Icon: 🌐 (globe)
- Tag: `TCP`
- Display: `192.168.1.100:502`

**RTU Devices:**
- Icon: 📡 (satellite/antenna)
- Tag: `RTU`
- Display: `COM3 @ 9600` (or `/dev/ttyUSB0 @ 19200`)

**Connection Status:**
- Green dot (●): Connected
- Gray dot (○): Disconnected
- Red: Error

```vue
<div class="device-info">
  <template v-if="device.connection_type === 'tcp'">
    <span class="info-tag">TCP</span>
    <span class="info-value">{{ device.ip_address }}:{{ device.port }}</span>
  </template>
  <template v-else>
    <span class="info-tag">RTU</span>
    <span class="info-value">{{ device.serial_port }} @ {{ device.baudrate }}</span>
  </template>
</div>
```

---

## Testing

### Test Coverage

Location: [`dashboard/src/stores/modbusValidation.test.ts`](../src/stores/modbusValidation.test.ts)

**TCP Tests** (4 tests):
- Basic TCP configuration
- Multiple TCP devices with different IPs
- Standard port 502
- Non-standard ports (503, 5502, 10502)

**RTU Tests** (6 tests):
- Basic RTU configuration
- Baud rates (9600, 19200, 38400, 57600, 115200)
- Parity (N, E, O)
- Serial ports (COM1, /dev/ttyUSB0, /dev/tty.usbserial)
- Data bits (7, 8)
- Stop bits (1, 2)

**Mixed Tests** (2 tests):
- Simultaneous TCP and RTU channels
- Auto-widget generation for mixed channels

Total: **24 Modbus validation tests**

### Running Tests

```bash
cd dashboard
npm test -- modbusValidation.test.ts
```

Expected output:
```
✓ Modbus System Validation (12 tests)
  ✓ Channel Type Support
  ✓ Data Type Handling
  ✓ Register Type Support
  ✓ Scaling and Offset
  ✓ Widget Auto-Generation
  ✓ Channel Configuration Validation
  ✓ Address Range Validation

✓ Modbus Connection Types (TCP and RTU) (12 tests)
  ✓ Modbus TCP Connection (4 tests)
  ✓ Modbus RTU Connection (6 tests)
  ✓ Mixed TCP and RTU Channels (2 tests)

Total: 24 tests passing ✅
```

---

## Common Use Cases

### Use Case 1: Single TCP Device

**Hardware:** Allen-Bradley PLC with Modbus TCP at `192.168.1.50:502`

**Configuration:**
1. Open ModbusDeviceConfig in UI
2. Click "Add Device"
3. Select "Modbus TCP (Ethernet)"
4. Enter IP: `192.168.1.50`, Port: `502`
5. Click "Add Device"

**Result:** Backend creates TCP connection via `ModbusTcpClient`

---

### Use Case 2: Single RTU Device

**Hardware:** Waveshare relay board on `/dev/ttyUSB0` at 9600 baud, 8N1

**Configuration:**
1. Open ModbusDeviceConfig in UI
2. Click "Add Device"
3. Select "Modbus RTU (Serial)"
4. Enter Serial Port: `/dev/ttyUSB0`
5. Select Baud Rate: `9600`, Parity: `None`, Data Bits: `8`, Stop Bits: `1`
6. Click "Add Device"

**Result:** Backend creates RTU connection via `ModbusSerialClient`

---

### Use Case 3: Mixed TCP + RTU

**Hardware:**
- PLC #1: TCP at `192.168.1.50:502`
- PLC #2: TCP at `192.168.1.51:502`
- Relay board: RTU on `COM3` at 9600 baud

**Configuration:** Add all three devices via UI (as shown above)

**Result:** Backend creates 2 TCP connections + 1 RTU connection simultaneously

---

## Troubleshooting

### TCP Issues

| Symptom | Cause | Solution |
|---------|-------|----------|
| Connection timeout | Firewall blocking port 502 | Check firewall, try ping |
| "Connection refused" | Wrong IP or port | Verify device IP and port |
| "No route to host" | Network issue | Check network cable, switch |

### RTU Issues

| Symptom | Cause | Solution |
|---------|-------|----------|
| "Port not found" | Wrong serial port name | Check `ls /dev/tty*` or Device Manager |
| "Permission denied" | No serial port access | Run `sudo usermod -a -G dialout $USER` (Linux) |
| Garbled data | Wrong baud rate or parity | Match device documentation |
| Intermittent errors | Loose wiring | Check RS-485 A/B wiring, termination |

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────┐
│                    Frontend (Vue.js)                     │
│  ┌────────────────────────────────────────────────────┐  │
│  │          ModbusDeviceConfig.vue                    │  │
│  │  ┌──────────────┐      ┌───────────────────────┐  │  │
│  │  │ Connection   │      │ TCP: IP + Port        │  │  │
│  │  │ Type Selector├──────┤ RTU: Serial + Params  │  │  │
│  │  └──────────────┘      └───────────────────────┘  │  │
│  └────────────────┬───────────────────────────────────┘  │
└───────────────────┼───────────────────────────────────────┘
                    │ MQTT: chassis/add, chassis/update
                    ▼
┌─────────────────────────────────────────────────────────┐
│              Backend (Python DAQ Service)                │
│  ┌────────────────────────────────────────────────────┐  │
│  │             modbus_reader.py                       │  │
│  │  ┌──────────────────────────────────────────────┐  │  │
│  │  │     Connection Type Detection                │  │  │
│  │  │  if conn_type in ("TCP", "MODBUS_TCP"):     │  │  │
│  │  │      use ModbusTcpClient                     │  │  │
│  │  │  else:                                        │  │  │
│  │  │      use ModbusSerialClient                  │  │  │
│  │  └──────────────┬────────────┬──────────────────┘  │  │
│  └─────────────────┼────────────┼─────────────────────┘  │
└────────────────────┼────────────┼─────────────────────────┘
                     │            │
         ┌───────────▼─┐      ┌──▼──────────────┐
         │  pymodbus   │      │    pyserial     │
         │ModbusTcpClient│    │ModbusSerialClient│
         └───────┬─────┘      └──┬──────────────┘
                 │               │
        ┌────────▼────┐    ┌─────▼────────┐
        │ Ethernet    │    │ RS-485/RS-232│
        │ (TCP/IP)    │    │ Serial Port  │
        └────────┬────┘    └─────┬────────┘
                 │               │
          ┌──────▼────────┐  ┌──▼─────────┐
          │  Modbus TCP   │  │ Modbus RTU │
          │  Device       │  │  Device    │
          │ 192.168.1.100│  │   COM3     │
          └───────────────┘  └────────────┘
```

---

## Summary

✅ **Frontend**: Fully supports TCP and RTU with dedicated UI for each
✅ **Backend**: Automatically creates correct connection type
✅ **Dependencies**: Requires `pymodbus` + `pyserial`
✅ **Testing**: 24 validation tests covering both connection types
✅ **Documentation**: Complete configuration guide
✅ **Visual Feedback**: Icons and tags differentiate connection types

**Status**: Production-ready with full TCP/RTU support

---

**Last Updated**: January 9, 2026
**Test Coverage**: 24/24 tests passing (100%)
**Documentation**: Complete
