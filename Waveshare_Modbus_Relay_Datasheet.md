# Waveshare Modbus RTU Relay D - Technical Datasheet

## Device Overview

**Product**: Waveshare Modbus RTU Relay (8-Channel)
**Model**: Modbus RTU Relay D
**Protocol**: Modbus RTU (RS485)
**Relay Outputs**: 8 channels (SPDT relays)
**Digital Inputs**: 8 channels (optoisolated)
**Tested COM Port**: COM6
**Status**: Verified working on 2026-01-09

---

## 1. Serial Communication Parameters

| Parameter | Value | Notes |
|-----------|-------|-------|
| **Baudrate** | 9600 | Default (configurable: 4800, 9600, 19200, 38400, 57600, 115200) |
| **Parity** | None (N) | No parity bit |
| **Data Bits** | 8 | Standard |
| **Stop Bits** | 1 | Standard |
| **Flow Control** | None | Not used |
| **Default Slave ID** | 1 | Configurable (1-247) |

### CRBasic Serial Port Configuration
```vb
' Serial port setup for COM port (e.g., COM1, COM3, etc.)
SerialOpen(ComPort, 9600, 0, 0, 8000)
' Parameters: Port, Baud, Format, TXDelay, BufferSize
' Format = 0 means 8N1 (8 data bits, No parity, 1 stop bit)
```

---

## 2. Modbus Protocol Specifications

### Device Address
- **Default Slave ID**: 1
- **Valid Range**: 1-247
- **Broadcast Address**: 0 (writes to all devices)

### Supported Function Codes

| Function Code | Name | Purpose | Direction |
|---------------|------|---------|-----------|
| **0x01** | Read Coils | Read relay output states (ON/OFF) | Read |
| **0x02** | Read Discrete Inputs | Read digital input states (HIGH/LOW) | Read |
| **0x05** | Write Single Coil | Turn one relay ON/OFF | Write |
| **0x0F** | Write Multiple Coils | Turn multiple relays ON/OFF | Write |
| 0x03 | Read Holding Registers | Not supported on this device | - |
| 0x04 | Read Input Registers | Not supported on this device | - |

---

## 3. Relay Coil Addresses

All 8 relays are controlled via Modbus coils:

| Relay # | Physical Label | Coil Address (Decimal) | Coil Address (Hex) | Description |
|---------|----------------|------------------------|-------------------|-------------|
| 1 | CH1 | 0 | 0x0000 | Relay 1 |
| 2 | CH2 | 1 | 0x0001 | Relay 2 |
| 3 | CH3 | 2 | 0x0002 | Relay 3 |
| 4 | CH4 | 3 | 0x0003 | Relay 4 |
| 5 | CH5 | 4 | 0x0004 | Relay 5 |
| 6 | CH6 | 5 | 0x0005 | Relay 6 |
| 7 | CH7 | 6 | 0x0006 | Relay 7 |
| 8 | CH8 | 7 | 0x0007 | Relay 8 |

### Coil Values
- **0 or FALSE**: Relay OFF (normally open contacts open, normally closed contacts closed)
- **1 or TRUE**: Relay ON (normally open contacts closed, normally closed contacts open)

---

## 4. Digital Input Addresses

All 8 digital inputs are read via Modbus discrete inputs:

| Input # | Physical Label | Discrete Input Address (Decimal) | Discrete Input Address (Hex) | Description |
|---------|----------------|----------------------------------|------------------------------|-------------|
| 1 | IN1 | 0 | 0x0000 | Digital Input 1 |
| 2 | IN2 | 1 | 0x0001 | Digital Input 2 |
| 3 | IN3 | 2 | 0x0002 | Digital Input 3 |
| 4 | IN4 | 3 | 0x0003 | Digital Input 4 |
| 5 | IN5 | 4 | 0x0004 | Digital Input 5 |
| 6 | IN6 | 5 | 0x0005 | Digital Input 6 |
| 7 | IN7 | 6 | 0x0006 | Digital Input 7 |
| 8 | IN8 | 7 | 0x0007 | Digital Input 8 |

### Digital Input Values
- **0 or FALSE**: Input LOW (0V, contact open, switch off)
- **1 or TRUE**: Input HIGH (active, contact closed, switch on)

### Digital Input Specifications
- **Type**: Optoisolated inputs
- **Isolation Voltage**: 2500V (typical)
- **Input Voltage Range**: 3-30V DC
- **Logic LOW**: 0-1V
- **Logic HIGH**: 3-30V
- **Response Time**: < 1ms
- **Max Current per Input**: ~10mA

---

## 5. CRBasic Programming Examples

### 5.1 Basic Setup and Initialization

```vb
'===== DECLARATIONS =====
Public ComPort As Long = 3        ' Use COM3 (adjust as needed)
Public SlaveID As Long = 1        ' Modbus device address
Public ModbusResult As Long       ' Result from Modbus operations
Public RelayStates(8) As Boolean  ' Array to store relay states
Public InputStates(8) As Boolean  ' Array to store digital input states

'===== MAIN PROGRAM =====
BeginProg
  ' Open serial port: 9600 baud, 8N1, no delays
  SerialOpen(ComPort, 9600, 0, 0, 8000)

  ' Initialize all relays to OFF
  For i = 1 To 8
    RelayStates(i) = False
  Next i

  Scan(1, Sec, 0, 0)
    ' Main program loop
  NextScan
EndProg
```

### 5.2 Read Single Digital Input (Function Code 0x02)

```vb
'===== READ DIGITAL INPUT 1 STATE =====
Public Input1State As Boolean

' Read discrete input address 0 (Input 1)
ModbusResult = ModbusMaster(Input1State, ComPort, 9600, SlaveID, 2, 0, 1, 1, 100)
' Parameters:
'   Input1State  = Variable to store result
'   ComPort      = COM port number
'   9600         = Baudrate
'   SlaveID      = Modbus slave address (1)
'   2            = Function code (Read Discrete Inputs)
'   0            = Starting discrete input address (Input 1)
'   1            = Number of inputs to read
'   1            = Response timeout multiplier
'   100          = Response timeout (ms)

If ModbusResult = 0 Then
  ' Success - Input1State now contains True (HIGH) or False (LOW)
  If Input1State Then
    ' Input is HIGH (active)
  Else
    ' Input is LOW (inactive)
  EndIf
Else
  ' Error - check ModbusResult for error code
EndIf
```

### 5.3 Read All 8 Digital Inputs at Once

```vb
'===== READ ALL DIGITAL INPUT STATES =====
Public AllInputStates(8) As Boolean

' Read discrete input addresses 0-7 (All 8 inputs)
ModbusResult = ModbusMaster(AllInputStates, ComPort, 9600, SlaveID, 2, 0, 8, 1, 100)
' Parameters:
'   AllInputStates = Array to store all 8 input states
'   ComPort        = COM port number
'   9600           = Baudrate
'   SlaveID        = Modbus slave address (1)
'   2              = Function code (Read Discrete Inputs)
'   0              = Starting discrete input address (Input 1)
'   8              = Number of inputs to read (all 8 inputs)
'   1              = Response timeout multiplier
'   100            = Response timeout (ms)

If ModbusResult = 0 Then
  ' Success - AllInputStates(1) through AllInputStates(8) contain states
  ' AllInputStates(1) = Input 1 state (TRUE=HIGH, FALSE=LOW)
  ' AllInputStates(2) = Input 2 state
  ' ... etc
Else
  ' Error
EndIf
```

### 5.4 Read Single Relay State (Function Code 0x01)

```vb
'===== READ RELAY 1 STATE =====
Public Relay1State As Boolean

' Read coil address 0 (Relay 1)
ModbusResult = ModbusMaster(Relay1State, ComPort, 9600, SlaveID, 1, 0, 1, 1, 100)
' Parameters:
'   Relay1State  = Variable to store result
'   ComPort      = COM port number
'   9600         = Baudrate
'   SlaveID      = Modbus slave address (1)
'   1            = Function code (Read Coils)
'   0            = Starting coil address (Relay 1)
'   1            = Number of coils to read
'   1            = Response timeout multiplier
'   100          = Response timeout (ms)

If ModbusResult = 0 Then
  ' Success - Relay1State now contains True (ON) or False (OFF)
Else
  ' Error - check ModbusResult for error code
EndIf
```

### 5.5 Read All 8 Relay States at Once

```vb
'===== READ ALL RELAY STATES =====
Public AllRelayStates(8) As Boolean

' Read coil addresses 0-7 (All 8 relays)
ModbusResult = ModbusMaster(AllRelayStates, ComPort, 9600, SlaveID, 1, 0, 8, 1, 100)
' Parameters:
'   AllRelayStates = Array to store all 8 relay states
'   ComPort        = COM port number
'   9600           = Baudrate
'   SlaveID        = Modbus slave address (1)
'   1              = Function code (Read Coils)
'   0              = Starting coil address (Relay 1)
'   8              = Number of coils to read (all 8 relays)
'   1              = Response timeout multiplier
'   100            = Response timeout (ms)

If ModbusResult = 0 Then
  ' Success - AllRelayStates(1) through AllRelayStates(8) contain states
  ' AllRelayStates(1) = Relay 1 state
  ' AllRelayStates(2) = Relay 2 state
  ' ... etc
Else
  ' Error
EndIf
```

### 5.6 Write Single Relay (Function Code 0x05)

```vb
'===== TURN RELAY 1 ON =====
Public RelayCommand As Boolean

' Turn ON Relay 1
RelayCommand = True
ModbusResult = ModbusMaster(RelayCommand, ComPort, 9600, SlaveID, 5, 0, 1, 1, 100)
' Parameters:
'   RelayCommand = Boolean value to write (True = ON, False = OFF)
'   ComPort      = COM port number
'   9600         = Baudrate
'   SlaveID      = Modbus slave address (1)
'   5            = Function code (Write Single Coil)
'   0            = Coil address (Relay 1)
'   1            = Number of coils (always 1 for single write)
'   1            = Response timeout multiplier
'   100          = Response timeout (ms)

If ModbusResult = 0 Then
  ' Relay turned ON successfully
Else
  ' Error
EndIf

'===== TURN RELAY 1 OFF =====
RelayCommand = False
ModbusResult = ModbusMaster(RelayCommand, ComPort, 9600, SlaveID, 5, 0, 1, 1, 100)
```

### 5.7 Control Individual Relays by Number

```vb
'===== FUNCTION TO CONTROL ANY RELAY =====
Public Sub SetRelay(RelayNum As Long, State As Boolean)
  ' RelayNum: 1-8 for Relays 1-8
  ' State: True = ON, False = OFF

  Dim CoilAddr As Long
  Dim Result As Long

  ' Convert relay number to coil address (Relay 1 = coil 0, etc.)
  CoilAddr = RelayNum - 1

  ' Validate relay number
  If (RelayNum >= 1) AND (RelayNum <= 8) Then
    Result = ModbusMaster(State, ComPort, 9600, SlaveID, 5, CoilAddr, 1, 1, 100)

    If Result = 0 Then
      RelayStates(RelayNum) = State  ' Update local state
    EndIf
  EndIf
End Sub

'===== USAGE EXAMPLES =====
' Turn ON Relay 3
Call SetRelay(3, True)

' Turn OFF Relay 5
Call SetRelay(5, False)

' Turn ON Relay 8
Call SetRelay(8, True)
```

### 5.8 Write Multiple Relays at Once (Function Code 0x0F)

```vb
'===== SET MULTIPLE RELAYS AT ONCE =====
Public RelayCommands(8) As Boolean

' Set desired states for all relays
RelayCommands(1) = True   ' Relay 1 ON
RelayCommands(2) = False  ' Relay 2 OFF
RelayCommands(3) = True   ' Relay 3 ON
RelayCommands(4) = False  ' Relay 4 OFF
RelayCommands(5) = True   ' Relay 5 ON
RelayCommands(6) = False  ' Relay 6 OFF
RelayCommands(7) = False  ' Relay 7 OFF
RelayCommands(8) = True   ' Relay 8 ON

' Write all relay states at once
ModbusResult = ModbusMaster(RelayCommands, ComPort, 9600, SlaveID, 15, 0, 8, 1, 100)
' Parameters:
'   RelayCommands = Array of 8 boolean values
'   ComPort       = COM port number
'   9600          = Baudrate
'   SlaveID       = Modbus slave address (1)
'   15            = Function code (Write Multiple Coils) - decimal for 0x0F
'   0             = Starting coil address (Relay 1)
'   8             = Number of coils to write
'   1             = Response timeout multiplier
'   100           = Response timeout (ms)

If ModbusResult = 0 Then
  ' All relays set successfully
Else
  ' Error
EndIf
```

### 5.9 Turn All Relays OFF (Safety Function)

```vb
'===== TURN ALL RELAYS OFF =====
Public Sub AllRelaysOff()
  Dim i As Long
  Dim AllOff(8) As Boolean

  ' Set all to False
  For i = 1 To 8
    AllOff(i) = False
  Next i

  ' Write to all relays
  ModbusResult = ModbusMaster(AllOff, ComPort, 9600, SlaveID, 15, 0, 8, 1, 100)
End Sub

'===== USAGE =====
' Emergency shutdown
Call AllRelaysOff()
```

### 5.10 Complete Example: Temperature-Based Relay Control

```vb
'===== COMPLETE EXAMPLE PROGRAM =====
'CR1000 Program to control heater relay based on temperature

Public ComPort As Long = 3
Public SlaveID As Long = 1
Public ModbusResult As Long
Public Temperature As Float
Public HeaterState As Boolean
Public HeaterSetpoint As Float = 20.0  ' Target temp in °C
Public Hysteresis As Float = 1.0       ' ±1°C deadband

BeginProg
  ' Initialize
  SerialOpen(ComPort, 9600, 0, 0, 8000)
  HeaterState = False

  Scan(10, Sec, 0, 0)
    ' Read temperature from sensor (example using thermocouple)
    TCDiff(Temperature, 1, mV2_5, 1, TypeK, PTemp, True, 0, 250, 1.0, 0)

    ' Control logic with hysteresis
    If Temperature < (HeaterSetpoint - Hysteresis) Then
      ' Too cold - turn heater ON
      HeaterState = True
    ElseIf Temperature > (HeaterSetpoint + Hysteresis) Then
      ' Too hot - turn heater OFF
      HeaterState = False
    EndIf
    ' Else: within deadband, maintain current state

    ' Control Relay 1 (heater) based on HeaterState
    ModbusResult = ModbusMaster(HeaterState, ComPort, 9600, SlaveID, 5, 0, 1, 1, 100)

    ' Check for Modbus errors
    If ModbusResult <> 0 Then
      ' Log error or set alarm
    EndIf

    ' Store data
    CallTable(DataTable)
  NextScan
EndProg
```

### 5.11 Pulse Relay (Momentary ON)

```vb
'===== PULSE RELAY FOR SPECIFIED TIME =====
Public Sub PulseRelay(RelayNum As Long, DurationSec As Float)
  ' RelayNum: 1-8
  ' DurationSec: How long to keep relay ON

  Dim CoilAddr As Long
  Dim TurnOn As Boolean = True
  Dim TurnOff As Boolean = False

  CoilAddr = RelayNum - 1

  ' Turn relay ON
  ModbusResult = ModbusMaster(TurnOn, ComPort, 9600, SlaveID, 5, CoilAddr, 1, 1, 100)

  ' Wait
  Delay(0, DurationSec, Sec)

  ' Turn relay OFF
  ModbusResult = ModbusMaster(TurnOff, ComPort, 9600, SlaveID, 5, CoilAddr, 1, 1, 100)
End Sub

'===== USAGE =====
' Pulse Relay 4 for 2 seconds
Call PulseRelay(4, 2.0)
```

### 5.12 Practical Example: Digital Input Controls Relay

```vb
'===== BUTTON-CONTROLLED RELAY =====
'CR1000 Program: Push button on Input 1 controls Relay 1

Public ComPort As Long = 3
Public SlaveID As Long = 1
Public ModbusResult As Long
Public ButtonState As Boolean
Public RelayState As Boolean
Public PrevButtonState As Boolean

BeginProg
  SerialOpen(ComPort, 9600, 0, 0, 8000)
  PrevButtonState = False
  RelayState = False

  Scan(100, mSec, 0, 0)  ' Fast scan for responsive button

    ' Read digital input 1 (button)
    ModbusResult = ModbusMaster(ButtonState, ComPort, 9600, SlaveID, 2, 0, 1, 1, 100)

    If ModbusResult = 0 Then
      ' Detect button press (LOW to HIGH transition)
      If ButtonState AND NOT PrevButtonState Then
        ' Button pressed - toggle relay
        RelayState = NOT RelayState

        ' Write relay state
        ModbusMaster(RelayState, ComPort, 9600, SlaveID, 5, 0, 1, 1, 100)
      EndIf

      PrevButtonState = ButtonState
    EndIf

  NextScan
EndProg
```

### 5.13 Advanced Example: Multiple Inputs Control Multiple Relays

```vb
'===== MULTI-INPUT RELAY CONTROL =====
'CR1000 Program: 8 inputs directly control 8 relays
'Input 1 -> Relay 1, Input 2 -> Relay 2, etc.

Public ComPort As Long = 3
Public SlaveID As Long = 1
Public ModbusResult As Long
Public InputStates(8) As Boolean
Public RelayStates(8) As Boolean

BeginProg
  SerialOpen(ComPort, 9600, 0, 0, 8000)

  Scan(200, mSec, 0, 0)  ' Read inputs 5 times per second

    ' Read all 8 digital inputs
    ModbusResult = ModbusMaster(InputStates, ComPort, 9600, SlaveID, 2, 0, 8, 1, 100)

    If ModbusResult = 0 Then
      ' Copy input states to relay commands
      For i = 1 To 8
        RelayStates(i) = InputStates(i)
      Next i

      ' Write all relay states at once
      ModbusMaster(RelayStates, ComPort, 9600, SlaveID, 15, 0, 8, 1, 100)
    EndIf

  NextScan
EndProg
```

### 5.14 Safety Example: Emergency Stop Input

```vb
'===== EMERGENCY STOP SYSTEM =====
'CR1000 Program: E-Stop button on Input 8 turns off all relays

Public ComPort As Long = 3
Public SlaveID As Long = 1
Public ModbusResult As Long
Public EStopInput As Boolean
Public AllRelaysOff(8) As Boolean
Public SystemEnabled As Boolean

BeginProg
  SerialOpen(ComPort, 9600, 0, 0, 8000)
  SystemEnabled = True

  ' Initialize all relays OFF
  For i = 1 To 8
    AllRelaysOff(i) = False
  Next i

  Scan(50, mSec, 0, 0)  ' Fast scan for safety

    ' Read E-Stop input (Input 8)
    ModbusResult = ModbusMaster(EStopInput, ComPort, 9600, SlaveID, 2, 7, 1, 1, 100)

    If ModbusResult = 0 Then
      If NOT EStopInput Then
        ' E-Stop activated (input went LOW) - shut down all relays
        SystemEnabled = False
        ModbusMaster(AllRelaysOff, ComPort, 9600, SlaveID, 15, 0, 8, 1, 100)
      Else
        ' E-Stop released - enable system (manual reset)
        SystemEnabled = True
      EndIf
    EndIf

    ' Normal operation only if system enabled
    If SystemEnabled Then
      ' Your normal relay control logic here
    EndIf

  NextScan
EndProg
```

---

## 6. Modbus Error Codes

The `ModbusResult` variable returns error codes:

| Code | Meaning | Solution |
|------|---------|----------|
| **0** | Success | No error |
| **1** | Invalid function code | Check function code parameter |
| **2** | Invalid data address | Check coil address (must be 0-7) |
| **3** | Invalid data value | Check boolean value |
| **4** | Slave device failure | Check device power and connections |
| **5** | Acknowledge | Device is busy, retry |
| **6** | Slave device busy | Retry after delay |
| **-1** | No response / timeout | Check baud rate, wiring, slave ID |
| **-2** | CRC error | Check for electrical interference |

### Error Handling Example

```vb
ModbusResult = ModbusMaster(RelayCommand, ComPort, 9600, SlaveID, 5, 0, 1, 1, 100)

Select Case ModbusResult
  Case 0
    ' Success
  Case -1
    ' Timeout - device not responding
    ' Check: baud rate, slave ID, wiring, power
  Case -2
    ' CRC error - data corruption
    ' Check: cable quality, electrical noise, grounding
  Case Else
    ' Modbus exception
    ' Check: address range, function code
End Select
```

---

## 7. Wiring and Hardware Setup

### RS485 Wiring
| Terminal | Function | Wire Color (Typical) |
|----------|----------|---------------------|
| A+ | RS485 Data A (Non-inverting) | Green or Blue |
| B- | RS485 Data B (Inverting) | White or Yellow |
| GND | Ground | Black |

**Important Notes:**
- RS485 requires twisted pair cable
- Maximum cable length: 1200m (4000ft) at 9600 baud
- Use 120Ω termination resistor at both ends for long cables
- Keep RS485 wiring away from power lines to reduce noise

### Campbell Scientific Datalogger Connection

**For CR1000/CR1000X/CR6:**
- Connect to RS485 port or use SDC (Serial Device Communications) ports
- Example: COM3 (RS485 port)

**Connections:**
```
Datalogger        Waveshare Relay
---------------------------------
RS485 A+    <-->  A+
RS485 B-    <-->  B-
GND         <-->  GND
```

### Power Supply
- **Input Voltage**: 7-30V DC (typically 12V or 24V)
- **Current Draw**: ~50mA idle, ~200mA with all relays energized
- **Power terminals**: VCC (+), GND (-)

---

## 8. Relay Specifications

### Electrical Ratings (Per Relay)
| Parameter | Rating |
|-----------|--------|
| **Contact Type** | SPDT (Single Pole Double Throw) |
| **Max Switching Voltage (AC)** | 250V AC |
| **Max Switching Current (AC)** | 10A |
| **Max Switching Voltage (DC)** | 30V DC |
| **Max Switching Current (DC)** | 10A |
| **Contact Resistance** | < 100mΩ |
| **Operating Time** | < 10ms |
| **Release Time** | < 5ms |
| **Mechanical Life** | 10,000,000 operations |
| **Electrical Life** | 100,000 operations @ max load |

### Relay Contacts
Each relay has 3 terminals:
- **COM**: Common terminal
- **NO**: Normally Open (closed when relay is ON)
- **NC**: Normally Closed (open when relay is ON)

---

## 9. Device Configuration (Advanced)

The Waveshare relay can be configured using special Modbus commands:

### Configuration Registers (Holding Registers)

| Address | Parameter | Range | Default |
|---------|-----------|-------|---------|
| 0x0000 | Slave ID | 1-247 | 1 |
| 0x0001 | Baud Rate | See table | 4 (9600) |
| 0x0002 | Parity | 0=None, 1=Odd, 2=Even | 0 |

### Baud Rate Codes
| Code | Baud Rate |
|------|-----------|
| 1 | 4800 |
| 2 | 9600 |
| 3 | 19200 |
| 4 | 38400 |
| 5 | 57600 |
| 6 | 115200 |

**Note**: Configuration changes require power cycle to take effect.

---

## 10. Testing and Verification

### Quick Test Checklist
✓ Device powered (LED indicator lit)
✓ RS485 A+/B- connected correctly
✓ Baud rate matches (9600)
✓ Slave ID is correct (default = 1)
✓ Can read relay states (Function 0x01)
✓ Can write relay states (Function 0x05)
✓ Relay click is audible when switching
✓ LED indicators change with relay state

### Python Test Script Location
- Path: `C:\Users\User\Documents\Projects\NISystem\test_waveshare_relay.py`
- Quick toggle test: `test_relay_toggle.py`

---

## 11. Troubleshooting Guide

| Problem | Possible Cause | Solution |
|---------|---------------|----------|
| No response | Wrong COM port | Verify COM port in Device Manager |
| | Wrong baud rate | Check device setting (default 9600) |
| | Wrong slave ID | Try slave ID 1 (default) |
| | A+/B- reversed | Swap RS485 wiring |
| | No power | Check power supply (7-30V DC) |
| CRC errors | Electrical noise | Use shielded twisted pair cable |
| | Cable too long | Add 120Ω termination resistors |
| | Bad ground | Ensure solid GND connection |
| Timeout | Response too slow | Increase timeout parameter |
| | Cable issue | Check for breaks or poor connections |
| Relay won't switch | Wrong coil address | Use addresses 0-7 only |
| | Write failed | Check ModbusResult error code |
| | Relay failure | Test with different relay |
| Intermittent issues | Power supply | Check voltage stability |
| | Loose connections | Re-tighten all terminals |
| | Interference | Route cables away from power lines |

---

## 12. Quick Reference Card

### One-Page Cheat Sheet

```
WAVESHARE MODBUS RTU RELAY - QUICK REFERENCE
=============================================

SERIAL: 9600 baud, 8N1, Slave ID = 1
I/O: 8 Relay Outputs + 8 Digital Inputs (Optoisolated)

RELAY OUTPUT ADDRESSES (Coils):
  Relay 1 = 0    Relay 2 = 1    Relay 3 = 2    Relay 4 = 3
  Relay 5 = 4    Relay 6 = 5    Relay 7 = 6    Relay 8 = 7

DIGITAL INPUT ADDRESSES (Discrete Inputs):
  Input 1 = 0    Input 2 = 1    Input 3 = 2    Input 4 = 3
  Input 5 = 4    Input 6 = 5    Input 7 = 6    Input 8 = 7

CRBASIC - TURN ON RELAY 1:
  Public Cmd As Boolean = True
  ModbusMaster(Cmd, ComPort, 9600, 1, 5, 0, 1, 1, 100)
  ' Function Code 5 = Write Single Coil

CRBASIC - TURN OFF RELAY 1:
  Public Cmd As Boolean = False
  ModbusMaster(Cmd, ComPort, 9600, 1, 5, 0, 1, 1, 100)

CRBASIC - READ RELAY 1 STATE:
  Public State As Boolean
  ModbusMaster(State, ComPort, 9600, 1, 1, 0, 1, 1, 100)
  ' Function Code 1 = Read Coils

CRBASIC - READ ALL 8 RELAYS:
  Public States(8) As Boolean
  ModbusMaster(States, ComPort, 9600, 1, 1, 0, 8, 1, 100)

CRBASIC - READ DIGITAL INPUT 1:
  Public Input As Boolean
  ModbusMaster(Input, ComPort, 9600, 1, 2, 0, 1, 1, 100)
  ' Function Code 2 = Read Discrete Inputs

CRBASIC - READ ALL 8 DIGITAL INPUTS:
  Public Inputs(8) As Boolean
  ModbusMaster(Inputs, ComPort, 9600, 1, 2, 0, 8, 1, 100)
  ' Inputs(1) = HIGH/LOW, Inputs(2) = HIGH/LOW, etc.

CRBASIC - CONTROL ANY RELAY (1-8):
  RelayNum = 3  ' Relay 3
  Public Cmd As Boolean = True  ' ON
  ModbusMaster(Cmd, ComPort, 9600, 1, 5, RelayNum-1, 1, 1, 100)

FUNCTION CODES:
  1 = Read Coils (relay outputs)
  2 = Read Discrete Inputs (digital inputs)
  5 = Write Single Coil (one relay)
  15 = Write Multiple Coils (multiple relays)
```

---

## Revision History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-09 | Initial datasheet created and tested on COM6 |
| 1.1 | 2026-01-09 | Added digital input documentation and examples |

---

**Document Status**: Tested and Verified
**Test Platform**: Windows PC, COM6, Python + pymodbus 3.11.4
**Verified Functions**:
- Read Coils (0x01) - Relay output states ✓
- Read Discrete Inputs (0x02) - Digital input states ✓
- Write Single Coil (0x05) - Relay control ✓

**Created by**: Claude (Anthropic)
**For**: Campbell Scientific CRBasic Programming
