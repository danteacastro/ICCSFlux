# NI MAX Simulated Device Setup Guide

This guide explains how to set up simulated NI-DAQmx devices in NI MAX for testing the DHW (Domestic Hot Water) test system without physical hardware.

## Quick Start (Automatic)

Run the Python script to automatically create all simulated devices:

```bash
cd c:\Users\User\Documents\Projects\NISystem
python tools/create_simulated_devices.py
```

Options:
- `--list` - List all current devices
- `--remove` - Remove existing DHW simulated devices first
- `--verify` - Verify devices after creation
- `--mapping` - Show channel mapping

## Manual Setup in NI MAX

If the Python script doesn't work, follow these steps to manually create simulated devices in NI MAX.

### Step 1: Open NI MAX

1. Press `Win + S` and search for "NI MAX" or "Measurement & Automation Explorer"
2. Open the application

### Step 2: Create Simulated Devices

For each device below, repeat these steps:

1. In the left panel, expand **My System**
2. Right-click **Devices and Interfaces**
3. Select **Create New...** → **Simulated NI-DAQmx Device**
4. In the dialog:
   - Select the product type from the list
   - Enter the device name
   - Click **OK**

### Required Devices for DHW System

Create these 4 simulated devices:

| Device Name | Product Type | Description |
|-------------|--------------|-------------|
| `DHW_Mod1` | NI 9217 | 4-channel RTD module |
| `DHW_Mod2` | NI 9213 | 16-channel Thermocouple module |
| `DHW_Mod7` | NI 9203 | 8-channel Current Input module |
| `DHW_Mod8` | NI 9472 | 8-channel Digital Output module |

### Step 3: Verify Devices

After creating the devices:

1. Expand **Devices and Interfaces** in NI MAX
2. You should see all 4 DHW devices listed
3. Click on each device to see its properties
4. Right-click and select **Self-Test** to verify it works

### Step 4: Configure NISystem

Use the NI MAX simulation configuration file:

```bash
python services/daq_service/daq_service.py -c config/dhw_test_system_nimax_sim.ini
```

## Channel Mapping Reference

### DHW_Mod1 (NI-9217 RTD Module)

| Channel | Physical Channel | Description |
|---------|-----------------|-------------|
| RTD_in | DHW_Mod1/ai0 | City Water inlet RTD |
| RTD_out | DHW_Mod1/ai1 | DHW outlet RTD |

### DHW_Mod2 (NI-9213 Thermocouple Module)

| Channel | Physical Channel | Description |
|---------|-----------------|-------------|
| TC_in | DHW_Mod2/ai0 | City water inlet TC |
| TC_out | DHW_Mod2/ai1 | DHW outlet TC |
| Tank_1 | DHW_Mod2/ai2 | Tank Temp 1 (Top) |
| Tank_2 | DHW_Mod2/ai3 | Tank Temp 2 |
| Tank_3 | DHW_Mod2/ai4 | Tank Temp 3 |
| Tank_4 | DHW_Mod2/ai5 | Tank Temp 4 |
| Tank_5 | DHW_Mod2/ai6 | Tank Temp 5 |
| Tank_6 | DHW_Mod2/ai7 | Tank Temp 6 |
| Tank_7 | DHW_Mod2/ai8 | Tank Temp 7 |
| Tank_8 | DHW_Mod2/ai9 | Tank Temp 8 (Bottom) |
| T_gas | DHW_Mod2/ai10 | Gas Temperature |
| T_amb | DHW_Mod2/ai11 | Ambient Temperature |
| T_flu | DHW_Mod2/ai12 | Flue Gas Temperature |
| T_ex1 | DHW_Mod2/ai13 | Extra Temp 1 |
| T_ex2 | DHW_Mod2/ai14 | Extra Temp 2 |
| T_ex3 | DHW_Mod2/ai15 | Extra Temp 3 |

### DHW_Mod7 (NI-9203 Current Input Module)

| Channel | Physical Channel | Description |
|---------|-----------------|-------------|
| Ifm | DHW_Mod7/ai0 | Flow Rate (4-20mA) |
| RH_rm | DHW_Mod7/ai1 | Room Humidity |
| T_rm | DHW_Mod7/ai2 | Room Temperature |
| RH_W | DHW_Mod7/ai3 | West Room Humidity |
| T_W | DHW_Mod7/ai4 | West Room Temp |
| RH_E | DHW_Mod7/ai5 | East Room Humidity |
| T_E | DHW_Mod7/ai6 | East Room Temp |
| NGin | DHW_Mod7/ai7 | Gas Flow Rate |

### DHW_Mod8 (NI-9472 Digital Output Module)

| Channel | Physical Channel | Description |
|---------|-----------------|-------------|
| SV1 | DHW_Mod8/port0/line0 | Solenoid Valve 1 |
| SV2 | DHW_Mod8/port0/line1 | Solenoid Valve 2 |
| SV3 | DHW_Mod8/port0/line2 | Solenoid Valve 3 |

## Simulation Modes Comparison

| Mode | Config Setting | Description |
|------|---------------|-------------|
| **Software Simulation** | `simulation_mode = true` | Pure Python simulation, no NI MAX needed |
| **NI MAX Simulation** | `simulation_mode = false` | Uses NI-DAQmx with simulated devices |
| **Real Hardware** | `simulation_mode = false` | Uses actual NI hardware |

### When to Use Each Mode

- **Software Simulation**: Development, UI testing, no NI drivers installed
- **NI MAX Simulation**: Testing NI-DAQmx integration, verifying channel configuration
- **Real Hardware**: Production, actual measurements

## Troubleshooting

### "Device not found" Error

1. Open NI MAX and verify the device exists
2. Check the device name matches exactly (case-sensitive)
3. Run device self-test in NI MAX

### "Module not supported" Error

The NI-9203 may not be directly supported as a simulated standalone device. Alternatives:

1. Use a different current input module (e.g., NI-9208)
2. Use software simulation mode for testing
3. Create a simulated cDAQ chassis with the module installed

### Creating a Simulated Chassis with Modules

For more realistic simulation, create a complete cDAQ chassis:

1. In NI MAX, create a simulated **cDAQ-9189** chassis
2. Right-click the chassis → **Add Device**
3. Add each module to the appropriate slot:
   - Slot 1: NI 9217
   - Slot 2: NI 9213
   - Slot 7: NI 9203
   - Slot 8: NI 9472

The channel names will then be:
- `cDAQ9189-XXXX/Mod1/ai0` instead of `DHW_Mod1/ai0`

Update the INI file accordingly.

## Deleting Simulated Devices

To remove simulated devices:

1. Open NI MAX
2. Expand **Devices and Interfaces**
3. Right-click the simulated device
4. Select **Delete**

Or use the Python script:
```bash
python tools/create_simulated_devices.py --remove
```

## Additional Resources

- [NI MAX Help Documentation](https://www.ni.com/docs/en-US/bundle/ni-max/page/max-help.html)
- [NI-DAQmx Simulated Devices](https://www.ni.com/docs/en-US/bundle/ni-daqmx/page/mxcncpts/simdaqdevices.html)
- [nidaqmx Python Documentation](https://nidaqmx-python.readthedocs.io/)
