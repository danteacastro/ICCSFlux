# GC Instrument Integration: Setup Guide for IT

## Hyper-V Virtual Machines for Legacy Gas Chromatograph Vendor Software

| | |
|---|---|
| **Document Version** | 2.0 |
| **Date** | 2026-02-12 |
| **Classification** | Internal -- IT Infrastructure |
| **Prepared for** | IT Department |
| **Author** | ICCSFlux Engineering |

---

## 1. Overview

This guide covers two methods for connecting Gas Chromatograph (GC) instruments to the ICCSFlux data acquisition platform. The method you use depends on how the GC exposes its data.

**Option A (preferred): Direct connection.** If the GC instrument provides serial (RS-232/RS-485) or Modbus output, the `gc_node` service runs directly on the ICCSFlux host PC. A USB-to-serial adapter connects the GC to the host. No VM is required. This is the simplest and most reliable approach.

**Option B: Hyper-V VM.** Some GC instruments only expose data through proprietary vendor software that requires Windows XP or Windows 7. These operating systems are end-of-life and must not be connected to production networks. In this case, the vendor software runs inside an isolated Hyper-V VM on the host PC, and `gc_node` runs inside the VM to parse result files and publish data over MQTT.

### Why VMs When Required

- **Legacy OS support.** GC vendor applications that require Windows XP SP3 or Windows 7 SP1 run in isolated VMs without affecting the host OS.
- **SOC 2 compliance.** VMs connect exclusively to an internal-only virtual switch with no route to the internet or corporate LAN. Data leaves the VM only via authenticated MQTT to the host.
- **Centralized acquisition.** The gc_node service publishes GC measurements over MQTT. The ICCSFlux DAQ service on the host consumes this data alongside all other instrument channels.
- **Recovery.** VM snapshots and exports provide rapid rollback if guest OS or vendor software becomes corrupted.

### Network Diagram

```
 OPTION A: Direct Connection (no VM)
 ====================================

 +------------------------------------------+
 |  Host PC (Win10/11 Pro or Server 2022+)  |
 |                                          |
 |  gc_node service                         |
 |       |                                  |
 |       | reads serial/Modbus              |
 |       v                                  |
 |  USB-to-Serial -----> GC Instrument      |
 |       |                                  |
 |       | publishes via MQTT               |
 |       v                                  |
 |  Mosquitto (localhost:1883)              |
 |       |                                  |
 |  ICCSFlux DAQ Service                    |
 +------------------------------------------+


 OPTION B: Hyper-V VM (legacy vendor software)
 ==============================================

 Host PC (Win10/11 Pro or Server 2022+)
 +------------------------------------------------------+
 |  ICCSFlux DAQ Service  <-- MQTT <-- Mosquitto        |
 |                                     (0.0.0.0:1883)   |
 |                                                      |
 |  Hyper-V                                             |
 |  +--------------------------------------------------+|
 |  |  Internal Virtual Switch ("GC-Internal")         ||
 |  |  Subnet: 10.10.10.0/24                           ||
 |  |                                                  ||
 |  |  Host adapter: 10.10.10.1                        ||
 |  |                                                  ||
 |  |  VM: GC-Node-01 (10.10.10.10)                    ||
 |  |    GC vendor software                            ||
 |  |    gc_node --> MQTT --> 10.10.10.1:1883           ||
 |  |    COM port passthrough --> GC Instrument         ||
 |  |                                                  ||
 |  |  VM: GC-Node-02 (10.10.10.11)                    ||
 |  |    GC vendor software                            ||
 |  |    gc_node --> MQTT --> 10.10.10.1:1883           ||
 |  +--------------------------------------------------+|
 |                                                      |
 |  Dashboard (WebSocket localhost:9002)                |
 +------------------------------------------------------+
```

---

## 2. Prerequisites

| Requirement | Details |
|---|---|
| **Host OS** | Windows 10 Pro (21H2+), Windows 11 Pro, Windows Server 2022, or Windows Server 2025. Home editions do not support Hyper-V. |
| **CPU** | 64-bit with SLAT, Intel VT-x or AMD-V enabled in BIOS/UEFI. Required only for Option B. |
| **RAM** | 8 GB minimum (16 GB recommended if running VMs). |
| **ICCSFlux** | DAQ service installed and running. Mosquitto MQTT broker operational. |
| **For Option A** | USB-to-serial adapter (FTDI or Prolific chipset recommended). GC serial/Modbus documentation. |
| **For Option B** | Windows XP SP3 or Windows 7 SP1 ISO with valid license. GC vendor software installation media. gc_node deployment package. |

---

## 3. Option A: Direct Connection (No VM)

Use this option when the GC instrument provides data over a serial (RS-232/RS-485) or Modbus interface. This is the preferred approach -- it avoids the complexity of VMs entirely.

### Steps

1. **Connect the GC instrument** to the host PC using a USB-to-serial adapter. Plug the adapter into a USB port on the host and connect the serial cable to the GC.

2. **Identify the COM port.** Open Device Manager on the host and expand "Ports (COM & LPT)". Note the COM port number assigned to the adapter (e.g., COM3).

   ```powershell
   # Or via PowerShell:
   Get-WmiObject Win32_SerialPort | Select-Object DeviceID, Description
   ```

3. **Install gc_node on the host.** Copy the gc_node package to a directory on the host (e.g., `C:\gc_node\`).

   ```powershell
   # Install dependencies
   cd C:\gc_node
   python -m pip install -r requirements.txt
   ```

4. **Configure gc_node.** Edit `gc_node_config.json` to specify the serial port, baud rate, and protocol:

   ```json
   {
     "mode": "serial",
     "serial_port": "COM3",
     "baud_rate": 9600,
     "protocol": "modbus_rtu",
     "broker_host": "127.0.0.1",
     "broker_port": 1883,
     "node_id": "gc-001"
   }
   ```

5. **Run the installer** to register gc_node as a Windows service:

   ```cmd
   install.bat 127.0.0.1 gc-001
   ```

6. **Verify.** Check that the service is running and publishing data:

   ```powershell
   sc query gc_node
   ```

   Confirm GC values appear in the ICCSFlux dashboard.

That is all that is required for a direct connection. The remainder of this guide covers Option B only.

---

## 4. Option B: Hyper-V VM Setup

Use this option only when GC vendor software requires a legacy OS (Windows XP or Windows 7) that cannot run on the host.

### 4a. Enable Hyper-V

**Windows 10/11 Pro:**

```powershell
Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V -All -Restart
```

**Windows Server 2022/2025:**

```powershell
Install-WindowsFeature -Name Hyper-V -IncludeManagementTools -Restart
```

Or use Server Manager: Add Roles and Features > Hyper-V. The system will reboot.

Verify after reboot:

```powershell
Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V | Select-Object State
# Expected: State: Enabled
```

### 4b. Create Internal Virtual Switch

Create a virtual network that exists only between the host and VMs. It has no connection to any physical adapter, the internet, or the corporate LAN.

1. Open **Hyper-V Manager** > **Virtual Switch Manager**.
2. Select **Internal** as the type. Click **Create Virtual Switch**.
3. Name it `GC-Internal`. Confirm connection type is **Internal network**.
4. Click **OK**.

```powershell
# Or via PowerShell:
New-VMSwitch -Name "GC-Internal" -SwitchType Internal
```

**The switch type MUST be Internal.** Do NOT use External (bridges to physical network), Default Switch (provides NAT/internet), or Private (blocks host-to-VM communication).

### 4c. Configure Host Network

Assign a static IP to the virtual adapter that Hyper-V created on the host.

```powershell
$adapter = Get-NetAdapter | Where-Object { $_.Name -like "*GC-Internal*" }
Remove-NetIPAddress -InterfaceIndex $adapter.ifIndex -Confirm:$false -ErrorAction SilentlyContinue
New-NetIPAddress -InterfaceIndex $adapter.ifIndex -IPAddress 10.10.10.1 -PrefixLength 24
Set-DnsClient -InterfaceIndex $adapter.ifIndex -RegisterThisConnectionsAddress $false
```

Do not assign a default gateway or DNS server to this adapter. It must serve only as a link between the host and GC VMs.

### 4d. Mosquitto Configuration

The ICCSFlux Mosquitto broker binds to `0.0.0.0:1883`, which already covers the internal switch adapter. No changes are needed.

Verify:

```powershell
netstat -an | findstr ":1883"
# Expected: TCP    0.0.0.0:1883    0.0.0.0:0    LISTENING
```

Create MQTT credentials for each gc_node instance:

```powershell
python scripts\mqtt_credentials.py add gc_node_01
python scripts\mqtt_credentials.py add gc_node_02
```

Record the generated passwords for use during gc_node installation.

### 4e. Create Generation 1 VMs

Generation 1 is required because Windows XP and Windows 7 do not support UEFI boot (Generation 2).

| Setting | Windows XP SP3 | Windows 7 SP1 |
|---|---|---|
| **Generation** | 1 (required) | 1 (required) |
| **RAM** | 1-2 GB static | 2-4 GB static |
| **vCPUs** | 1-2 | 1-2 |
| **VHD** | 20 GB fixed | 40 GB fixed |
| **Network** | GC-Internal | GC-Internal |

Use fixed-size VHDs for consistent disk I/O. GC vendor software sometimes performs real-time data capture and benefits from predictable latency.

```powershell
# Example: Create a Windows XP VM
New-Item -ItemType Directory -Path "C:\Hyper-V\VMs\GC-Node-01" -Force
New-VHD -Path "C:\Hyper-V\VMs\GC-Node-01\GC-Node-01.vhd" -SizeBytes 20GB -Fixed
New-VM -Name "GC-Node-01" -MemoryStartupBytes 1536MB -Generation 1 `
       -VHDPath "C:\Hyper-V\VMs\GC-Node-01\GC-Node-01.vhd" `
       -SwitchName "GC-Internal"
Set-VMProcessor -VMName "GC-Node-01" -Count 2
Set-VMDvdDrive -VMName "GC-Node-01" -Path "D:\ISOs\WindowsXP_SP3.iso"
```

Connect each VM ONLY to `GC-Internal`. Do not add a second adapter on an external switch.

### 4f. Install Guest OS

**Windows XP SP3:**

1. Boot from ISO and complete installation.
2. Install Integration Services: Action > Insert Integration Services Setup Disk. Run `setup.exe` from the mounted CD inside the VM. Reboot.
3. Set static IP: Control Panel > Network Connections > adapter Properties > TCP/IP:
   - IP: `10.10.10.10` (use `.11`, `.12` for additional VMs)
   - Subnet: `255.255.255.0`
   - Gateway: *(blank)*
   - DNS: *(blank)*
4. Verify: `ping 10.10.10.1` from within the VM.

**Windows 7 SP1:**

1. Boot from ISO and complete installation. Integration Services install automatically.
2. Set static IP: Control Panel > Network and Sharing Center > adapter Properties > IPv4:
   - IP: `10.10.10.11`
   - Subnet: `255.255.255.0`
   - Gateway: *(blank)*
   - DNS: *(blank)*
3. Verify: `ping 10.10.10.1` from within the VM.

Do NOT set a default gateway or DNS server. The VM must have no route outside 10.10.10.0/24.

### 4g. COM Port Passthrough

For GC instruments connected via serial:

**Physical COM port:** In VM Settings > COM 1, select the physical port (e.g., COM3). The port must not be in use by the host.

**USB-to-serial adapter:** Hyper-V does not natively pass through USB. Options:
- Enhanced Session Mode (Win7 guests): connect via RDP and map the USB device.
- Network serial gateway (e.g., Moxa NPort): presents serial over TCP on the 10.10.10.0/24 subnet.
- Third-party USB passthrough software (evaluate against security requirements).

### 4h. Install GC Vendor Software

Inside each VM:

1. Copy vendor installation media into the VM (Hyper-V file copy or mount a second ISO).
2. Run the vendor installer per manufacturer instructions.
3. Configure the vendor software to write result files to a known directory (e.g., `C:\GCResults\`).
4. Perform a test run to confirm result files are generated. Record the output format and path.

### 4i. Install gc_node in the VM

Install the appropriate Python version (XP: Python 3.4.x; Win7: Python 3.8.x). Then:

```cmd
cd C:\gc_node
python -m pip install --no-index --find-links C:\gc_node\vendor -r requirements.txt
install.bat 10.10.10.1 gc_node_01
```

The installer creates `gc_node_config.json`, registers gc_node as a Windows service (or scheduled task on XP), and starts the service.

Verify:

```cmd
sc query gc_node
```

### 4j. Windows Firewall

Configure the firewall inside each VM to allow only MQTT traffic to the host. This is defense-in-depth on top of the internal switch isolation.

**Windows 7:**

```powershell
netsh advfirewall set allprofiles firewallpolicy blockinbound,blockoutbound
netsh advfirewall firewall add rule name="Allow MQTT to Host" dir=out action=allow protocol=tcp remoteip=10.10.10.1 remoteport=1883
netsh advfirewall firewall add rule name="Allow ICMP to Host" dir=out action=allow protocol=icmpv4 remoteip=10.10.10.1
netsh advfirewall firewall add rule name="Allow ICMP from Host" dir=in action=allow protocol=icmpv4 remoteip=10.10.10.1
```

**Windows XP:** The built-in XP firewall has limited outbound filtering. The primary isolation control is the internal-only switch with no gateway. Enable the XP firewall for inbound protection:

```cmd
netsh firewall set opmode enable
```

---

## 5. SOC 2 Control Mapping

| SOC 2 Control | Criteria | Implementation |
|---|---|---|
| **CC6.1** | Logical access | MQTT broker requires username/password authentication. Each gc_node uses a unique credential. No interactive accounts on VMs beyond local admin for maintenance. |
| **CC6.6** | Network segmentation | Internal-only virtual switch. No physical adapter bridged. No default gateway. VMs cannot reach any network outside 10.10.10.0/24. |
| **CC6.7** | Restrict data transmission | Guest firewall allows only outbound TCP 1883 to 10.10.10.1. All other outbound traffic is blocked. Data leaves the VM exclusively as MQTT messages. |
| **CC7.2** | Monitoring | ICCSFlux audit trail with SHA-256 hash chain. gc_node publishes heartbeats over MQTT. Mosquitto logs all connection and authentication events. |
| **CC8.1** | Change management | VM snapshots taken before any software change. Changes to gc_node configuration logged in audit trail. |
| **A1.2** | Backup and recovery | Weekly VM exports to network share. Daily gc_node config backup. 4-week retention. Annual restore test documented. |

---

## 6. Backup Strategy

| Frequency | Action | Retention |
|---|---|---|
| **Before any change** | VM checkpoint in Hyper-V | Delete after change is verified stable (max 3 per VM) |
| **Daily** | Copy `gc_node_config.json` from each VM to host `C:\ICCSFlux\backups\gc_nodes\` | 30 days |
| **Weekly** | Full VM export (`Export-VM`) to network share | 4 weekly exports (rolling, 28-day retention) |
| **Annually** | Restore test: import VM export to test host, verify gc_node connectivity | Document results |

### Weekly Export Script

Run as a scheduled task on the host (e.g., Sunday 02:00):

```powershell
$exportPath = "\\fileserver\backups\nisystem\hyper-v"
$vms = @("GC-Node-01", "GC-Node-02")
$datestamp = Get-Date -Format "yyyy-MM-dd"

foreach ($vm in $vms) {
    Export-VM -Name $vm -Path (Join-Path $exportPath "$vm-$datestamp")
}

# Remove exports older than 28 days
Get-ChildItem -Path $exportPath -Directory |
    Where-Object { $_.CreationTime -lt (Get-Date).AddDays(-28) } |
    Remove-Item -Recurse -Force
```

---

## 7. Troubleshooting

| Symptom | Possible Cause | Resolution |
|---|---|---|
| **Cannot ping host from VM** | VM not on the correct virtual switch. | VM Settings > Network Adapter: verify it is connected to `GC-Internal`. |
| | Host vEthernet adapter not configured. | Run `Get-NetIPAddress -InterfaceAlias "vEthernet (GC-Internal)"` and verify `10.10.10.1/24` is assigned. |
| | Guest IP misconfigured. | Verify static IP in 10.10.10.x/24 range, no gateway, no DNS. |
| | Integration Services missing (XP). | Action > Insert Integration Services Setup Disk. Run setup. Reboot VM. |
| **MQTT connection refused** | Mosquitto not running. | On host: `sc query mosquitto`. Restart if stopped. |
| | Mosquitto bound to 127.0.0.1 only. | Run `netstat -an \| findstr :1883`. If showing `127.0.0.1:1883`, update `mosquitto.conf` listener to `0.0.0.0`. |
| | Invalid credentials. | Re-run `python scripts\mqtt_credentials.py add gc_node_01` on the host. Update password in VM's `gc_node_config.json`. |
| | Host firewall blocking 1883. | Ensure Windows Firewall on the host allows inbound TCP 1883 from 10.10.10.0/24. |
| **GC data not appearing** | gc_node not running. | Inside VM: `sc query gc_node`. Check logs at `C:\gc_node\logs\`. |
| | File watcher path mismatch. | Verify `watch_directory` in `gc_node_config.json` matches where vendor software writes results. |
| | Serial port not configured. | For direct connections: verify COM port number in Device Manager. Check `gc_node_config.json` serial settings. |
| | File format not recognized. | Verify GC output format matches gc_node parser config. Check logs for parse errors. |
| **VM will not boot** | Generation 2 used for XP/Win7. | Delete and recreate as Generation 1. XP and Win7 require BIOS boot (no UEFI). |
| | Boot order incorrect. | VM Settings > BIOS: move IDE/CD to top of boot order for initial OS install. |
| | Checkpoint corruption. | Delete the checkpoint. If VM still fails, import from the most recent weekly export. |

### Collecting Diagnostics

When escalating, collect from the host:

```powershell
Get-VM | Format-List Name, State, Generation, ProcessorCount, MemoryAssigned
Get-VMSwitch | Format-List Name, SwitchType
Get-NetIPAddress -InterfaceAlias "vEthernet (GC-Internal)"
sc query mosquitto
netstat -an | findstr :1883
```

And from inside each VM:

```cmd
ipconfig /all
ping 10.10.10.1
sc query gc_node
type C:\gc_node\logs\gc_node.log
```

---

*For questions not covered here, contact ICCSFlux Engineering.*
