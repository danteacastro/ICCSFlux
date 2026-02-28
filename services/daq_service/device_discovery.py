"""
NI DAQmx Device Discovery Module

Scans for connected NI hardware via NI-DAQmx and provides device/channel enumeration.
This module interfaces with NI MAX (Measurement & Automation Explorer) database.

Usage:
    from device_discovery import DeviceDiscovery

    discovery = DeviceDiscovery()
    devices = discovery.scan()
    channels = discovery.get_available_channels()
"""

import logging
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Any
from enum import Enum

logger = logging.getLogger(__name__)

# Try to import nidaqmx - gracefully handle if not available
try:
    import nidaqmx
    import nidaqmx.system
    from nidaqmx.constants import TerminalConfiguration, ThermocoupleType, RTDType
    NIDAQMX_AVAILABLE = True
except Exception:
    NIDAQMX_AVAILABLE = False
    logger.warning("nidaqmx not available - device discovery will return simulated data")


class ModuleCategory(Enum):
    """NI C Series module categories - matches ChannelType values"""
    # Analog Inputs
    THERMOCOUPLE = "thermocouple"
    RTD = "rtd"
    VOLTAGE_INPUT = "voltage_input"
    CURRENT_INPUT = "current_input"
    STRAIN = "strain"              # Legacy - use STRAIN_INPUT
    STRAIN_INPUT = "strain_input"
    BRIDGE_INPUT = "bridge_input"
    IEPE = "iepe"                  # Legacy - use IEPE_INPUT
    IEPE_INPUT = "iepe_input"
    RESISTANCE = "resistance"
    RESISTANCE_INPUT = "resistance_input"

    # Analog Outputs
    ANALOG_OUTPUT = "analog_output"  # Legacy - use VOLTAGE_OUTPUT/CURRENT_OUTPUT
    VOLTAGE_OUTPUT = "voltage_output"
    CURRENT_OUTPUT = "current_output"

    # Digital
    DIGITAL_INPUT = "digital_input"
    DIGITAL_OUTPUT = "digital_output"

    # Counter
    COUNTER = "counter"            # Legacy - use COUNTER_INPUT
    COUNTER_INPUT = "counter_input"
    COUNTER_OUTPUT = "counter_output"
    FREQUENCY_INPUT = "frequency_input"

    # Universal/Other
    UNIVERSAL = "universal"
    UNKNOWN = "unknown"


# NI Module database - maps model numbers to categories and specs
NI_MODULE_DATABASE: Dict[str, Dict[str, Any]] = {
    # Thermocouple modules
    "NI 9210": {"category": ModuleCategory.THERMOCOUPLE, "channels": 4, "description": "4-Ch Thermocouple"},
    "NI 9211": {"category": ModuleCategory.THERMOCOUPLE, "channels": 4, "description": "4-Ch Thermocouple"},
    "NI 9212": {"category": ModuleCategory.THERMOCOUPLE, "channels": 8, "description": "8-Ch Thermocouple"},
    "NI 9213": {"category": ModuleCategory.THERMOCOUPLE, "channels": 16, "description": "16-Ch Thermocouple"},
    "NI 9214": {"category": ModuleCategory.THERMOCOUPLE, "channels": 16, "description": "16-Ch Isothermal TC"},

    # RTD modules
    "NI 9216": {"category": ModuleCategory.RTD, "channels": 8, "description": "8-Ch RTD"},
    "NI 9217": {"category": ModuleCategory.RTD, "channels": 4, "description": "4-Ch RTD"},
    "NI 9226": {"category": ModuleCategory.RTD, "channels": 8, "description": "8-Ch RTD"},

    # Voltage input modules
    "NI 9201": {"category": ModuleCategory.VOLTAGE_INPUT, "channels": 8, "description": "8-Ch ±10V AI, 12-bit"},
    "NI 9202": {"category": ModuleCategory.VOLTAGE_INPUT, "channels": 16, "description": "16-Ch ±10V AI, 24-bit simultaneous"},
    "NI 9204": {"category": ModuleCategory.VOLTAGE_INPUT, "channels": 16, "description": "16 SE / 8 DIFF, ±0.2-10V, 16-bit, programmable gain"},
    "NI 9205": {"category": ModuleCategory.VOLTAGE_INPUT, "channels": 32, "description": "32 SE / 16 DIFF, ±0.2-10V, 16-bit"},
    "NI 9206": {"category": ModuleCategory.VOLTAGE_INPUT, "channels": 16, "description": "16 DIFF, ±0.2-10V, 16-bit, high-isolation"},
    "NI 9209": {"category": ModuleCategory.VOLTAGE_INPUT, "channels": 32, "description": "16 DIFF / 32 SE, ±10V, 24-bit"},
    "NI 9215": {"category": ModuleCategory.VOLTAGE_INPUT, "channels": 4, "description": "4-Ch ±10V simultaneous, 16-bit"},
    "NI 9220": {"category": ModuleCategory.VOLTAGE_INPUT, "channels": 16, "description": "16-Ch ±10V simultaneous, 16-bit"},
    "NI 9221": {"category": ModuleCategory.VOLTAGE_INPUT, "channels": 8, "description": "8-Ch ±60V, 12-bit"},
    "NI 9222": {"category": ModuleCategory.VOLTAGE_INPUT, "channels": 4, "description": "4-Ch ±10V, 16-bit, 500 kS/s"},
    "NI 9223": {"category": ModuleCategory.VOLTAGE_INPUT, "channels": 4, "description": "4-Ch ±10V, 16-bit, 1 MS/s"},
    "NI 9224": {"category": ModuleCategory.VOLTAGE_INPUT, "channels": 8, "description": "8-Ch ±10.5V, 16-bit"},
    "NI 9225": {"category": ModuleCategory.VOLTAGE_INPUT, "channels": 3, "description": "3-Ch 300 Vrms, 24-bit (high-voltage power)"},
    "NI 9228": {"category": ModuleCategory.VOLTAGE_INPUT, "channels": 8, "description": "8-Ch ±60V, 24-bit"},
    "NI 9229": {"category": ModuleCategory.VOLTAGE_INPUT, "channels": 4, "description": "4-Ch ±60V, 24-bit isolated simultaneous"},
    "NI 9238": {"category": ModuleCategory.VOLTAGE_INPUT, "channels": 4, "description": "4-Ch ±0.5V, 24-bit (low-voltage precision)"},
    "NI 9239": {"category": ModuleCategory.VOLTAGE_INPUT, "channels": 4, "description": "4-Ch ±10V, 24-bit simultaneous"},
    "NI 9242": {"category": ModuleCategory.VOLTAGE_INPUT, "channels": 3, "description": "3-Ch 250 Vrms L-N, 24-bit (3-phase power)"},
    "NI 9244": {"category": ModuleCategory.VOLTAGE_INPUT, "channels": 3, "description": "3-Ch 400 Vrms L-N, 24-bit (high-voltage power)"},
    "NI 9252": {"category": ModuleCategory.VOLTAGE_INPUT, "channels": 8, "description": "8-Ch voltage digitizer"},

    # Combo modules (voltage + current on same module — per-channel type handled in _enumerate_channels)
    "NI 9207": {"category": ModuleCategory.VOLTAGE_INPUT, "channels": 16, "description": "16-Ch V/I AI (ai0-7 V, ai8-15 I), 24-bit"},

    # Current input modules
    "NI 9203": {"category": ModuleCategory.CURRENT_INPUT, "channels": 8, "description": "8-Ch ±20mA AI, 16-bit"},
    "NI 9208": {"category": ModuleCategory.CURRENT_INPUT, "channels": 16, "description": "16-Ch ±20mA AI, 24-bit high-precision"},
    "NI 9227": {"category": ModuleCategory.CURRENT_INPUT, "channels": 4, "description": "4-Ch 5 Arms AI, 24-bit (AC power)"},
    "NI 9246": {"category": ModuleCategory.CURRENT_INPUT, "channels": 3, "description": "3-Ch 20 Arms AI, 24-bit (3-phase power)"},
    "NI 9247": {"category": ModuleCategory.CURRENT_INPUT, "channels": 3, "description": "3-Ch 50 Arms AI, 24-bit (high-current 3-phase)"},
    "NI 9253": {"category": ModuleCategory.CURRENT_INPUT, "channels": 8, "description": "8-Ch ±20mA AI, 24-bit simultaneous"},

    # Strain/Bridge modules
    "NI 9235": {"category": ModuleCategory.STRAIN_INPUT, "channels": 8, "description": "8-Ch Quarter Bridge"},
    "NI 9236": {"category": ModuleCategory.STRAIN_INPUT, "channels": 8, "description": "8-Ch Quarter Bridge"},
    "NI 9237": {"category": ModuleCategory.BRIDGE_INPUT, "channels": 4, "description": "4-Ch Bridge AI"},

    # IEPE/Accelerometer modules
    "NI 9230": {"category": ModuleCategory.IEPE_INPUT, "channels": 3, "description": "3-Ch IEPE AI"},
    "NI 9231": {"category": ModuleCategory.IEPE_INPUT, "channels": 8, "description": "8-Ch IEPE AI"},
    "NI 9232": {"category": ModuleCategory.IEPE_INPUT, "channels": 3, "description": "3-Ch IEPE AI"},
    "NI 9233": {"category": ModuleCategory.IEPE_INPUT, "channels": 4, "description": "4-Ch IEPE AI"},
    "NI 9234": {"category": ModuleCategory.IEPE_INPUT, "channels": 4, "description": "4-Ch IEPE AI"},
    "NI 9250": {"category": ModuleCategory.IEPE_INPUT, "channels": 2, "description": "2-Ch IEPE AI"},
    "NI 9251": {"category": ModuleCategory.IEPE_INPUT, "channels": 2, "description": "2-Ch IEPE AI"},

    # Digital I/O modules
    "NI 9375": {"category": ModuleCategory.DIGITAL_INPUT, "channels": 32, "description": "16 DI + 16 DO"},
    "NI 9401": {"category": ModuleCategory.DIGITAL_INPUT, "channels": 8, "description": "8-Ch Bidirectional DIO"},
    "NI 9402": {"category": ModuleCategory.DIGITAL_INPUT, "channels": 4, "description": "4-Ch Bidirectional DIO"},
    "NI 9403": {"category": ModuleCategory.DIGITAL_INPUT, "channels": 32, "description": "32-Ch DIO"},
    "NI 9411": {"category": ModuleCategory.DIGITAL_INPUT, "channels": 6, "description": "6-Ch Diff DI"},
    "NI 9421": {"category": ModuleCategory.DIGITAL_INPUT, "channels": 8, "description": "8-Ch 24V Sinking DI"},
    "NI 9422": {"category": ModuleCategory.DIGITAL_INPUT, "channels": 8, "description": "8-Ch 24V Sourcing DI"},
    "NI 9423": {"category": ModuleCategory.DIGITAL_INPUT, "channels": 8, "description": "8-Ch 24V DI"},
    "NI 9425": {"category": ModuleCategory.DIGITAL_INPUT, "channels": 32, "description": "32-Ch 24V Sinking DI"},
    "NI 9426": {"category": ModuleCategory.DIGITAL_INPUT, "channels": 32, "description": "32-Ch 24V Sourcing DI"},
    "NI 9435": {"category": ModuleCategory.DIGITAL_INPUT, "channels": 4, "description": "4-Ch Universal DI (5-250 VDC/VAC)"},
    "NI 9436": {"category": ModuleCategory.DIGITAL_INPUT, "channels": 8, "description": "8-Ch 12-24V DI, 1 µs (high-speed)"},
    "NI 9437": {"category": ModuleCategory.DIGITAL_INPUT, "channels": 8, "description": "8-Ch 250 VDC/VAC DI (high-voltage)"},

    "NI 9470": {"category": ModuleCategory.DIGITAL_OUTPUT, "channels": 8, "description": "8-Ch 24V Sourcing DO"},
    "NI 9472": {"category": ModuleCategory.DIGITAL_OUTPUT, "channels": 8, "description": "8-Ch 24V Sourcing DO"},
    "NI 9474": {"category": ModuleCategory.DIGITAL_OUTPUT, "channels": 8, "description": "8-Ch 24V Sourcing DO"},
    "NI 9475": {"category": ModuleCategory.DIGITAL_OUTPUT, "channels": 8, "description": "8-Ch 60V Sourcing DO"},
    "NI 9476": {"category": ModuleCategory.DIGITAL_OUTPUT, "channels": 32, "description": "32-Ch 24V Sourcing DO"},
    "NI 9477": {"category": ModuleCategory.DIGITAL_OUTPUT, "channels": 32, "description": "32-Ch 60V Sinking DO"},
    "NI 9478": {"category": ModuleCategory.DIGITAL_OUTPUT, "channels": 16, "description": "16-Ch Sinking DO"},
    "NI 9481": {"category": ModuleCategory.DIGITAL_OUTPUT, "channels": 4, "description": "4-Ch Relay DO"},
    "NI 9482": {"category": ModuleCategory.DIGITAL_OUTPUT, "channels": 4, "description": "4-Ch Relay DO"},
    "NI 9485": {"category": ModuleCategory.DIGITAL_OUTPUT, "channels": 8, "description": "8-Ch SSR DO"},

    # Voltage output modules
    "NI 9260": {"category": ModuleCategory.VOLTAGE_OUTPUT, "channels": 2, "description": "2-Ch ±10V AO"},
    "NI 9262": {"category": ModuleCategory.VOLTAGE_OUTPUT, "channels": 6, "description": "6-Ch ±10V AO, 16-bit, 1 MS/s"},
    "NI 9263": {"category": ModuleCategory.VOLTAGE_OUTPUT, "channels": 4, "description": "4-Ch ±10V AO"},
    "NI 9264": {"category": ModuleCategory.VOLTAGE_OUTPUT, "channels": 16, "description": "16-Ch ±10V AO"},
    "NI 9269": {"category": ModuleCategory.VOLTAGE_OUTPUT, "channels": 4, "description": "4-Ch ±10V AO"},

    # Current output modules
    "NI 9265": {"category": ModuleCategory.CURRENT_OUTPUT, "channels": 4, "description": "4-Ch 0-20mA AO"},
    "NI 9266": {"category": ModuleCategory.CURRENT_OUTPUT, "channels": 8, "description": "8-Ch 0-20mA AO"},

    # Counter modules
    "NI 9361": {"category": ModuleCategory.COUNTER_INPUT, "channels": 8, "description": "8-Ch Counter/DI"},

    # Universal modules (per-channel configurable: V, I, TC, RTD, R, bridge)
    "NI 9218": {"category": ModuleCategory.BRIDGE_INPUT, "channels": 2, "description": "2-Ch Universal AI (V, I, bridge, IEPE)"},
    "NI 9219": {"category": ModuleCategory.BRIDGE_INPUT, "channels": 4, "description": "4-Ch Universal AI (V, I, TC, RTD, R, bridge)"},
}


# CompactFieldPoint backplane database — slot count per model
CFP_BACKPLANES: Dict[str, Dict[str, Any]] = {
    'cFP-1804': {'slots': 4, 'description': '4-Slot Ethernet Backplane'},
    'cFP-1808': {'slots': 8, 'description': '8-Slot Ethernet Backplane'},
    'cFP-2020': {'slots': 8, 'description': '8-Slot Programmable Controller'},
    'cFP-2120': {'slots': 8, 'description': '8-Slot High-Performance Controller'},
}
CFP_SLOT_REGISTER_OFFSET = 100  # Slot base address = (slot - 1) * 100

# Optional pymodbus import for CFP slot probing
try:
    from pymodbus.client import ModbusTcpClient as _CfpModbusTcpClient
    from pymodbus.exceptions import ModbusException as _CfpModbusException
    _PYMODBUS_AVAILABLE = True
except ImportError:
    _PYMODBUS_AVAILABLE = False


@dataclass
class PhysicalChannel:
    """Represents a physical channel on an NI module"""
    name: str                    # e.g., "cDAQ1Mod1/ai0"
    device: str                  # e.g., "cDAQ1Mod1"
    channel_type: str            # e.g., "ai", "ao", "di", "do", "ci"
    index: int                   # Channel index (0, 1, 2...)
    category: str                # Module category (thermocouple, voltage, etc.)
    description: str = ""
    source_type: str = "local"   # "local" for cDAQ/PXI, "crio" for remote cRIO
    node_id: str = ""            # Node ID for remote nodes (e.g., "crio-001")

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class Module:
    """Represents an NI C Series module"""
    name: str                    # e.g., "cDAQ1Mod1"
    product_type: str            # e.g., "NI 9213"
    serial_number: str
    slot: int
    chassis: str                 # e.g., "cDAQ1"
    category: str                # Module category
    description: str
    channels: List[PhysicalChannel] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            **asdict(self),
            "channels": [ch.to_dict() for ch in self.channels]
        }


@dataclass
class Chassis:
    """Represents an NI CompactDAQ chassis"""
    name: str                    # e.g., "cDAQ1"
    product_type: str            # e.g., "cDAQ-9189"
    serial_number: str
    slot_count: int
    modules: List[Module] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            **asdict(self),
            "modules": [mod.to_dict() for mod in self.modules]
        }


@dataclass
class CRIONode:
    """Represents a remote cRIO node discovered via MQTT"""
    node_id: str                 # e.g., "crio-001"
    ip_address: str              # e.g., "192.168.1.50"
    product_type: str            # e.g., "cRIO-9056"
    serial_number: str           # NI-DAQmx chassis serial number
    status: str                  # "online", "offline", "unknown"
    last_seen: str               # ISO timestamp
    channels: int = 0            # Number of configured channels
    mac_address: str = ''        # Hardware MAC address for device identity
    modules: List[Module] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            **asdict(self),
            "modules": [mod.to_dict() for mod in self.modules],
            "node_type": "crio"
        }


@dataclass
class Opto22Node:
    """Represents a remote Opto22 groov EPIC/RIO node discovered via MQTT"""
    node_id: str                 # e.g., "opto22-001"
    ip_address: str              # e.g., "192.168.1.60"
    product_type: str            # e.g., "groov EPIC"
    serial_number: str
    status: str                  # "online", "offline", "unknown"
    last_seen: str               # ISO timestamp
    channels: int = 0            # Number of configured channels
    modules: List[Module] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            **asdict(self),
            "modules": [mod.to_dict() for mod in self.modules],
            "node_type": "opto22"
        }


@dataclass
class GCNode:
    """Represents a remote GC node in a Hyper-V VM discovered via MQTT"""
    node_id: str                 # e.g., "gc-001"
    ip_address: str              # e.g., "10.10.10.10"
    gc_type: str                 # e.g., "Agilent 7890"
    status: str                  # "online", "offline", "unknown"
    last_seen: str               # ISO timestamp
    channels: int = 0
    last_analysis: str = ""      # ISO timestamp of last GC result
    analysis_count: int = 0
    source_type: str = ""        # "file", "modbus", "serial"

    def to_dict(self) -> Dict:
        return {**asdict(self), "node_type": "gc"}


@dataclass
class DiscoveryResult:
    """Complete discovery result"""
    success: bool
    message: str
    timestamp: str
    chassis: List[Chassis] = field(default_factory=list)
    standalone_devices: List[Module] = field(default_factory=list)
    crio_nodes: List[CRIONode] = field(default_factory=list)  # Remote cRIO nodes
    opto22_nodes: List[Opto22Node] = field(default_factory=list)  # Remote Opto22 nodes
    gc_nodes: List[GCNode] = field(default_factory=list)  # Remote GC nodes in VMs
    total_channels: int = 0
    simulation_mode: bool = False

    def to_dict(self) -> Dict:
        return {
            "success": self.success,
            "message": self.message,
            "timestamp": self.timestamp,
            "simulation_mode": self.simulation_mode,
            "total_channels": self.total_channels,
            "chassis": [ch.to_dict() for ch in self.chassis],
            "standalone_devices": [dev.to_dict() for dev in self.standalone_devices],
            "crio_nodes": [node.to_dict() for node in self.crio_nodes],
            "opto22_nodes": [node.to_dict() for node in self.opto22_nodes],
            "gc_nodes": [node.to_dict() for node in self.gc_nodes],
        }


class DeviceDiscovery:
    """
    NI DAQmx Device Discovery

    Scans the system for connected NI hardware and enumerates all available
    channels. Works with both real hardware and simulation mode.

    Also tracks remote cRIO nodes that connect via MQTT.
    """

    def __init__(self):
        self._last_result: Optional[DiscoveryResult] = None
        self._last_scan_time: float = 0
        # Track cRIO nodes that have registered via MQTT
        self._crio_nodes: Dict[str, CRIONode] = {}
        self._crio_lock = __import__('threading').Lock()
        # Track Opto22 nodes that have registered via MQTT
        self._opto22_nodes: Dict[str, Opto22Node] = {}
        self._opto22_lock = __import__('threading').Lock()
        # Track GC nodes in Hyper-V VMs that have registered via MQTT
        self._gc_nodes: Dict[str, GCNode] = {}
        self._gc_lock = __import__('threading').Lock()

    def register_crio_node(self, node_id: str, status_data: Dict[str, Any]):
        """
        Register or update a cRIO node from MQTT status message.

        Called by DAQ service when receiving status from cRIO nodes.

        Args:
            node_id: The node ID (e.g., "crio-001")
            status_data: Status payload from cRIO node containing:
                - ip_address: Node's IP address
                - product_type: Hardware type (e.g., "cRIO-9056")
                - serial_number: Hardware serial
                - status: "online" or "offline"
                - channels: Number of configured channels
                - modules: Optional list of module info
        """
        from datetime import datetime

        with self._crio_lock:
            # Parse modules if provided
            modules = []
            for mod_data in status_data.get('modules', []):
                mod = Module(
                    name=mod_data.get('name', ''),
                    product_type=mod_data.get('product_type', ''),
                    serial_number=mod_data.get('serial_number', ''),
                    slot=mod_data.get('slot', 0),
                    chassis=node_id,
                    category=mod_data.get('category', 'unknown'),
                    description=mod_data.get('description', '')
                )
                # Parse channels - mark as cRIO source with node_id
                for ch_data in mod_data.get('channels', []):
                    # cRIO sends 'channel_type' for each channel - use it as category fallback
                    ch_type = ch_data.get('channel_type', '')
                    ch_category = ch_data.get('category', '') or ch_type  # Fallback to channel_type
                    mod.channels.append(PhysicalChannel(
                        name=ch_data.get('name', ''),
                        device=mod.name,
                        channel_type=ch_type,
                        index=ch_data.get('index', 0),
                        category=ch_category,
                        description=ch_data.get('description', ''),
                        source_type='crio',  # Mark as cRIO channel
                        node_id=node_id       # Include cRIO node ID
                    ))
                modules.append(mod)

            self._crio_nodes[node_id] = CRIONode(
                node_id=node_id,
                ip_address=status_data.get('ip_address', 'unknown'),
                product_type=status_data.get('product_type', 'cRIO'),
                serial_number=status_data.get('serial_number', ''),
                status=status_data.get('status', 'online'),
                last_seen=datetime.utcnow().isoformat(),
                channels=status_data.get('channels', 0),
                mac_address=status_data.get('mac_address', ''),
                modules=modules
            )
            serial_info = f", serial={status_data.get('serial_number', '')}" if status_data.get('serial_number') else ""
            mac_info = f", mac={status_data.get('mac_address', '')}" if status_data.get('mac_address') else ""
            logger.info(f"Registered cRIO node: {node_id} ({status_data.get('status', 'online')}{serial_info}{mac_info})")

    def unregister_crio_node(self, node_id: str):
        """Remove a cRIO node from tracking"""
        with self._crio_lock:
            if node_id in self._crio_nodes:
                del self._crio_nodes[node_id]
                logger.info(f"Unregistered cRIO node: {node_id}")

    def mark_crio_offline(self, node_id: str):
        """Mark a cRIO node as offline (but don't remove it)"""
        with self._crio_lock:
            if node_id in self._crio_nodes:
                self._crio_nodes[node_id].status = 'offline'
                logger.info(f"cRIO node offline: {node_id}")

    def update_crio_heartbeat(self, node_id: str, heartbeat_data: Dict[str, Any]):
        """
        Update cRIO node from heartbeat without overwriting full registration.

        If the node exists with full info (modules), only update heartbeat fields.
        If the node doesn't exist, create minimal registration.
        """
        from datetime import datetime
        with self._crio_lock:
            if node_id in self._crio_nodes:
                # Existing node - only update heartbeat fields, preserve modules
                node = self._crio_nodes[node_id]
                node.status = heartbeat_data.get('status', 'online')
                node.last_seen = datetime.utcnow().isoformat()
                # Update channel count if provided (but keep modules intact)
                if 'channels' in heartbeat_data and not node.modules:
                    node.channels = heartbeat_data.get('channels', 0)
            else:
                # New node - create minimal registration from heartbeat
                self._crio_nodes[node_id] = CRIONode(
                    node_id=node_id,
                    ip_address=heartbeat_data.get('ip_address', 'unknown'),
                    product_type=heartbeat_data.get('product_type', 'cRIO'),
                    serial_number=heartbeat_data.get('serial_number', ''),
                    status=heartbeat_data.get('status', 'online'),
                    last_seen=datetime.utcnow().isoformat(),
                    channels=heartbeat_data.get('channels', 0),
                    mac_address=heartbeat_data.get('mac_address', ''),
                    modules=[]  # Will be populated when full status arrives
                )
                logger.info(f"Registered cRIO node: {node_id} ({heartbeat_data.get('status', 'online')})")

    def get_crio_nodes(self) -> List[CRIONode]:
        """Get list of known cRIO nodes"""
        with self._crio_lock:
            return list(self._crio_nodes.values())

    def register_opto22_node(self, node_id: str, status_data: Dict[str, Any]):
        """
        Register or update an Opto22 node from MQTT status message.

        Called by DAQ service when receiving status from Opto22 nodes.

        Args:
            node_id: The node ID (e.g., "opto22-001")
            status_data: Status payload from Opto22 node containing:
                - ip_address: Node's IP address
                - product_type: Hardware type (e.g., "groov EPIC")
                - serial_number: Hardware serial
                - status: "online" or "offline"
                - channels: Number of configured channels
                - modules: Optional list of module info
        """
        from datetime import datetime

        with self._opto22_lock:
            # Parse modules if provided
            modules = []
            for mod_data in status_data.get('modules', []):
                mod = Module(
                    name=mod_data.get('name', ''),
                    product_type=mod_data.get('product_type', ''),
                    serial_number=mod_data.get('serial_number', ''),
                    slot=mod_data.get('slot', 0),
                    chassis=node_id,
                    category=mod_data.get('category', 'unknown'),
                    description=mod_data.get('description', '')
                )
                # Parse channels - mark as Opto22 source with node_id
                for ch_data in mod_data.get('channels', []):
                    # Use channel_type as category fallback
                    ch_type = ch_data.get('channel_type', '')
                    ch_category = ch_data.get('category', '') or ch_type
                    mod.channels.append(PhysicalChannel(
                        name=ch_data.get('name', ''),
                        device=mod.name,
                        channel_type=ch_type,
                        index=ch_data.get('index', 0),
                        category=ch_category,
                        description=ch_data.get('description', ''),
                        source_type='opto22',  # Mark as Opto22 channel
                        node_id=node_id         # Include Opto22 node ID
                    ))
                modules.append(mod)

            self._opto22_nodes[node_id] = Opto22Node(
                node_id=node_id,
                ip_address=status_data.get('ip_address', 'unknown'),
                product_type=status_data.get('product_type', 'groov EPIC'),
                serial_number=status_data.get('serial_number', ''),
                status=status_data.get('status', 'online'),
                last_seen=datetime.utcnow().isoformat(),
                channels=status_data.get('channels', 0),
                modules=modules
            )
            logger.info(f"Registered Opto22 node: {node_id} ({status_data.get('status', 'online')})")

    def unregister_opto22_node(self, node_id: str):
        """Remove an Opto22 node from tracking"""
        with self._opto22_lock:
            if node_id in self._opto22_nodes:
                del self._opto22_nodes[node_id]
                logger.info(f"Unregistered Opto22 node: {node_id}")

    def mark_opto22_offline(self, node_id: str):
        """Mark an Opto22 node as offline (but don't remove it)"""
        with self._opto22_lock:
            if node_id in self._opto22_nodes:
                self._opto22_nodes[node_id].status = 'offline'
                logger.info(f"Opto22 node offline: {node_id}")

    def update_opto22_heartbeat(self, node_id: str, heartbeat_data: Dict[str, Any]):
        """
        Update Opto22 node from heartbeat without overwriting full registration.

        If the node exists with full info (modules), only update heartbeat fields.
        If the node doesn't exist, create minimal registration.
        """
        from datetime import datetime
        with self._opto22_lock:
            if node_id in self._opto22_nodes:
                # Existing node - only update heartbeat fields, preserve modules
                node = self._opto22_nodes[node_id]
                node.status = heartbeat_data.get('status', 'online')
                node.last_seen = datetime.utcnow().isoformat()
                # Update channel count if provided (but keep modules intact)
                if 'channels' in heartbeat_data and not node.modules:
                    node.channels = heartbeat_data.get('channels', 0)
            else:
                # New node - create minimal registration from heartbeat
                self._opto22_nodes[node_id] = Opto22Node(
                    node_id=node_id,
                    ip_address=heartbeat_data.get('ip_address', 'unknown'),
                    product_type=heartbeat_data.get('product_type', 'groov EPIC'),
                    serial_number=heartbeat_data.get('serial_number', ''),
                    status=heartbeat_data.get('status', 'online'),
                    last_seen=datetime.utcnow().isoformat(),
                    channels=heartbeat_data.get('channels', 0),
                    modules=[]  # Will be populated when full status arrives
                )
                logger.info(f"Registered Opto22 node: {node_id} ({heartbeat_data.get('status', 'online')})")

    def get_opto22_nodes(self) -> List[Opto22Node]:
        """Get list of known Opto22 nodes"""
        with self._opto22_lock:
            return list(self._opto22_nodes.values())

    def register_gc_node(self, node_id: str, status_data: Dict[str, Any]):
        """
        Register or update a GC node from MQTT status message.

        Called by DAQ service when receiving status from GC nodes in Hyper-V VMs.

        Args:
            node_id: The node ID (e.g., "gc-001")
            status_data: Status payload from GC node containing:
                - ip_address: VM's IP address
                - gc_type: GC instrument type (e.g., "Agilent 7890")
                - status: "online" or "offline"
                - channels: Number of configured channels
                - analysis_count: Number of GC analyses completed
                - last_analysis: Timestamp of last analysis
                - source_type: Active data source ("file", "modbus", "serial")
        """
        from datetime import datetime

        with self._gc_lock:
            self._gc_nodes[node_id] = GCNode(
                node_id=node_id,
                ip_address=status_data.get('ip_address', 'unknown'),
                gc_type=status_data.get('gc_type', ''),
                status=status_data.get('status', 'online'),
                last_seen=datetime.utcnow().isoformat(),
                channels=status_data.get('channels', 0),
                last_analysis=str(status_data.get('last_analysis', '')),
                analysis_count=status_data.get('analysis_count', 0),
                source_type=status_data.get('source_type', ''),
            )
            logger.info(f"Registered GC node: {node_id} ({status_data.get('status', 'online')})")

    def unregister_gc_node(self, node_id: str):
        """Remove a GC node from tracking"""
        with self._gc_lock:
            if node_id in self._gc_nodes:
                del self._gc_nodes[node_id]
                logger.info(f"Unregistered GC node: {node_id}")

    def mark_gc_offline(self, node_id: str):
        """Mark a GC node as offline (but don't remove it)"""
        with self._gc_lock:
            if node_id in self._gc_nodes:
                self._gc_nodes[node_id].status = 'offline'
                logger.info(f"GC node offline: {node_id}")

    def update_gc_heartbeat(self, node_id: str, heartbeat_data: Dict[str, Any]):
        """
        Update GC node from heartbeat without overwriting full registration.

        If the node exists, only update heartbeat fields.
        If the node doesn't exist, create minimal registration.
        """
        from datetime import datetime
        with self._gc_lock:
            if node_id in self._gc_nodes:
                # Existing node - only update heartbeat fields
                node = self._gc_nodes[node_id]
                node.status = heartbeat_data.get('status', 'online')
                node.last_seen = datetime.utcnow().isoformat()
                if 'channels' in heartbeat_data:
                    node.channels = heartbeat_data.get('channels', 0)
                if 'analysis_count' in heartbeat_data:
                    node.analysis_count = heartbeat_data.get('analysis_count', 0)
            else:
                # New node - create minimal registration from heartbeat
                self._gc_nodes[node_id] = GCNode(
                    node_id=node_id,
                    ip_address=heartbeat_data.get('ip_address', 'unknown'),
                    gc_type=heartbeat_data.get('gc_type', ''),
                    status=heartbeat_data.get('status', 'online'),
                    last_seen=datetime.utcnow().isoformat(),
                    channels=heartbeat_data.get('channels', 0),
                    source_type=heartbeat_data.get('source_type', ''),
                )
                logger.info(f"Registered GC node: {node_id} ({heartbeat_data.get('status', 'online')})")

    def get_gc_nodes(self) -> List[GCNode]:
        """Get list of known GC nodes"""
        with self._gc_lock:
            return list(self._gc_nodes.values())

    def scan_cfp(self, ip_address: str, port: int = 502, slave_id: int = 1,
                 backplane_model: str = 'cFP-1808', device_name: str = '') -> Dict[str, Any]:
        """
        Probe a CFP backplane via Modbus TCP to detect populated slots.

        Since CFP hardware does not expose module IDs via standard Modbus registers,
        we detect slot occupancy by attempting reads at each slot's base address.
        The register type that responds reveals the general I/O category.

        Args:
            ip_address: CFP backplane IP address
            port: Modbus TCP port (default 502)
            slave_id: Modbus slave ID (default 1)
            backplane_model: Backplane model for slot count (e.g., 'cFP-1808')
            device_name: Optional device name for result labeling

        Returns:
            Dict with success, slots array, and message
        """
        if not _PYMODBUS_AVAILABLE:
            return {
                'success': False,
                'message': 'Modbus library (pymodbus) not available',
                'ip_address': ip_address,
                'port': port,
                'backplane_model': backplane_model,
                'device_name': device_name,
                'slots': []
            }

        backplane = CFP_BACKPLANES.get(backplane_model, {'slots': 8})
        num_slots = backplane['slots']

        # Create temporary Modbus TCP client for probing
        client = _CfpModbusTcpClient(host=ip_address, port=port, timeout=0.5)

        try:
            if not client.connect():
                return {
                    'success': False,
                    'message': f'Cannot connect to {ip_address}:{port}',
                    'ip_address': ip_address,
                    'port': port,
                    'backplane_model': backplane_model,
                    'device_name': device_name,
                    'slots': []
                }

            slots = []
            populated_count = 0

            for slot_num in range(1, num_slots + 1):
                base_addr = (slot_num - 1) * CFP_SLOT_REGISTER_OFFSET
                slot_result = {
                    'slot': slot_num,
                    'populated': False,
                    'category': '',
                    'register_type': ''
                }

                # Probe register types in priority order.
                # Stop on first successful read — that reveals the module category.
                probe_sequence = [
                    ('input', 'analog_input', lambda a: client.read_input_registers(a, count=1, slave=slave_id)),
                    ('discrete', 'digital_input', lambda a: client.read_discrete_inputs(a, count=1, slave=slave_id)),
                    ('holding', 'analog_output', lambda a: client.read_holding_registers(a, count=1, slave=slave_id)),
                    ('coil', 'digital_output', lambda a: client.read_coils(a, count=1, slave=slave_id)),
                ]

                for reg_type, category, read_fn in probe_sequence:
                    try:
                        result = read_fn(base_addr)
                        if result is not None and not result.isError():
                            slot_result['populated'] = True
                            slot_result['category'] = category
                            slot_result['register_type'] = reg_type
                            populated_count += 1
                            break
                    except Exception:
                        continue

                slots.append(slot_result)

            return {
                'success': True,
                'ip_address': ip_address,
                'port': port,
                'backplane_model': backplane_model,
                'device_name': device_name,
                'slots': slots,
                'message': f'Found {populated_count} populated slot{"s" if populated_count != 1 else ""} out of {num_slots}'
            }

        except Exception as e:
            logger.error(f"CFP slot probe failed for {ip_address}:{port}: {e}")
            return {
                'success': False,
                'message': f'Probe failed: {e}',
                'ip_address': ip_address,
                'port': port,
                'backplane_model': backplane_model,
                'device_name': device_name,
                'slots': []
            }
        finally:
            try:
                client.close()
            except Exception:
                pass

    def scan(self, include_crio: bool = True, include_opto22: bool = True) -> DiscoveryResult:
        """
        Scan for all connected NI devices and remote nodes (cRIO, Opto22).

        Args:
            include_crio: If True, include registered cRIO nodes in results
            include_opto22: If True, include registered Opto22 nodes in results

        Returns:
            DiscoveryResult with all discovered hardware
        """
        from datetime import datetime
        timestamp = datetime.now().isoformat()

        if not NIDAQMX_AVAILABLE:
            logger.info("nidaqmx not available, returning simulated discovery")
            result = self._get_simulated_result(timestamp)
        else:
            try:
                result = self._scan_real_hardware(timestamp)
            except Exception as e:
                logger.error(f"Hardware scan failed: {e}", exc_info=True)
                result = DiscoveryResult(
                    success=False,
                    message=f"Scan failed: {str(e)}",
                    timestamp=timestamp,
                    simulation_mode=False
                )

        # Add cRIO nodes to result
        if include_crio:
            crio_nodes = self.get_crio_nodes()
            result.crio_nodes = crio_nodes

            # Add cRIO channel count to total
            crio_channels = sum(node.channels for node in crio_nodes)
            result.total_channels += crio_channels

            if crio_nodes:
                result.message += f", {len(crio_nodes)} cRIO nodes ({crio_channels} remote channels)"

        # Add Opto22 nodes to result
        if include_opto22:
            opto22_nodes = self.get_opto22_nodes()
            result.opto22_nodes = opto22_nodes

            # Add Opto22 channel count to total
            opto22_channels = sum(node.channels for node in opto22_nodes)
            result.total_channels += opto22_channels

            if opto22_nodes:
                result.message += f", {len(opto22_nodes)} Opto22 nodes ({opto22_channels} remote channels)"

        # Add GC nodes to result
        gc_nodes = self.get_gc_nodes()
        result.gc_nodes = gc_nodes
        gc_channels = sum(node.channels for node in gc_nodes)
        result.total_channels += gc_channels
        if gc_nodes:
            result.message += f", {len(gc_nodes)} GC nodes ({gc_channels} remote channels)"

        self._last_result = result
        self._last_scan_time = __import__('time').time()
        return result

    def _scan_real_hardware(self, timestamp: str) -> DiscoveryResult:
        """Scan real NI hardware using nidaqmx"""
        system = nidaqmx.system.System.local()

        chassis_list: List[Chassis] = []
        standalone_list: List[Module] = []
        total_channels = 0

        # Get all devices
        for device in system.devices:
            device_name = device.name
            product_type = device.product_type
            serial = str(device.dev_serial_num) if device.dev_serial_num else "N/A"

            logger.info(f"Found device: {device_name} ({product_type})")

            # Check if this is a chassis or a module
            if "cDAQ" in product_type and "Mod" not in device_name:
                # This is a chassis
                chassis = Chassis(
                    name=device_name,
                    product_type=product_type,
                    serial_number=serial,
                    slot_count=self._get_chassis_slots(product_type)
                )
                chassis_list.append(chassis)
            else:
                # This is a module or standalone device
                module = self._create_module_from_device(device)
                if module:
                    total_channels += len(module.channels)

                    # Check if it belongs to a chassis
                    chassis_name = self._extract_chassis_name(device_name)
                    if chassis_name:
                        # Find or create chassis
                        chassis = next((c for c in chassis_list if c.name == chassis_name), None)
                        if chassis:
                            chassis.modules.append(module)
                        else:
                            # Module in chassis we haven't seen yet
                            standalone_list.append(module)
                    else:
                        standalone_list.append(module)

        return DiscoveryResult(
            success=True,
            message=f"Found {len(chassis_list)} chassis, {total_channels} channels",
            timestamp=timestamp,
            chassis=chassis_list,
            standalone_devices=standalone_list,
            total_channels=total_channels,
            simulation_mode=False
        )

    def _create_module_from_device(self, device) -> Optional[Module]:
        """Create a Module object from an nidaqmx device"""
        device_name = device.name
        product_type = device.product_type
        serial = str(device.dev_serial_num) if device.dev_serial_num else "N/A"

        # Look up module info
        module_info = NI_MODULE_DATABASE.get(product_type, {})
        category = module_info.get("category", ModuleCategory.UNKNOWN)
        description = module_info.get("description", product_type)

        # Extract slot number if in chassis
        slot = self._extract_slot_number(device_name)
        chassis = self._extract_chassis_name(device_name) or ""

        module = Module(
            name=device_name,
            product_type=product_type,
            serial_number=serial,
            slot=slot,
            chassis=chassis,
            category=category.value if isinstance(category, ModuleCategory) else str(category),
            description=description
        )

        # Enumerate physical channels (pass product_type for combo module handling)
        module.channels = self._enumerate_channels(device, category, product_type)

        return module

    # Combo modules: channels at index >= split_point use the alternate category
    COMBO_MODULES: Dict[str, tuple] = {
        "NI 9207": ("current_input", 8),  # ai0-7 = voltage_input, ai8-15 = current_input
    }

    def _enumerate_channels(self, device, category: ModuleCategory, product_type: str = "") -> List[PhysicalChannel]:
        """Enumerate all physical channels on a device"""
        channels: List[PhysicalChannel] = []
        device_name = device.name
        cat_value = category.value if isinstance(category, ModuleCategory) else str(category)

        # Check if this is a combo module (e.g., NI 9207)
        combo = self.COMBO_MODULES.get(product_type)

        # Analog input channels
        for i, ai_chan in enumerate(device.ai_physical_chans):
            # For combo modules, override category for channels at/above split index
            ch_category = cat_value
            if combo and i >= combo[1]:
                ch_category = combo[0]
            channels.append(PhysicalChannel(
                name=ai_chan.name,
                device=device_name,
                channel_type="ai",
                index=i,
                category=ch_category,
                description=f"Analog Input {i}"
            ))

        # Analog output channels
        for i, ao_chan in enumerate(device.ao_physical_chans):
            channels.append(PhysicalChannel(
                name=ao_chan.name,
                device=device_name,
                channel_type="ao",
                index=i,
                category="analog_output",
                description=f"Analog Output {i}"
            ))

        # Digital input lines
        for i, di_line in enumerate(device.di_lines):
            channels.append(PhysicalChannel(
                name=di_line.name,
                device=device_name,
                channel_type="di",
                index=i,
                category="digital_input",
                description=f"Digital Input {i}"
            ))

        # Digital output lines
        for i, do_line in enumerate(device.do_lines):
            channels.append(PhysicalChannel(
                name=do_line.name,
                device=device_name,
                channel_type="do",
                index=i,
                category="digital_output",
                description=f"Digital Output {i}"
            ))

        # Counter channels
        for i, ci_chan in enumerate(device.ci_physical_chans):
            channels.append(PhysicalChannel(
                name=ci_chan.name,
                device=device_name,
                channel_type="ci",
                index=i,
                category="counter",
                description=f"Counter Input {i}"
            ))

        return channels

    def _get_simulated_result(self, timestamp: str) -> DiscoveryResult:
        """Return simulated discovery result for testing without hardware"""

        # Simulated cDAQ-9189 with common modules
        chassis = Chassis(
            name="cDAQ1",
            product_type="cDAQ-9189",
            serial_number="SIM001",
            slot_count=8
        )

        # Slot 1: NI-9213 Thermocouple
        tc_module = Module(
            name="cDAQ1Mod1",
            product_type="NI 9213",
            serial_number="SIM-TC01",
            slot=1,
            chassis="cDAQ1",
            category="thermocouple",
            description="16-Ch Thermocouple"
        )
        for i in range(16):
            tc_module.channels.append(PhysicalChannel(
                name=f"cDAQ1Mod1/ai{i}",
                device="cDAQ1Mod1",
                channel_type="ai",
                index=i,
                category="thermocouple",
                description=f"Thermocouple {i}"
            ))
        chassis.modules.append(tc_module)

        # Slot 2: NI-9203 Current Input
        current_module = Module(
            name="cDAQ1Mod2",
            product_type="NI 9203",
            serial_number="SIM-AI01",
            slot=2,
            chassis="cDAQ1",
            category="current",
            description="8-Ch ±20mA AI"
        )
        for i in range(8):
            current_module.channels.append(PhysicalChannel(
                name=f"cDAQ1Mod2/ai{i}",
                device="cDAQ1Mod2",
                channel_type="ai",
                index=i,
                category="current",
                description=f"Current Input {i}"
            ))
        chassis.modules.append(current_module)

        # Slot 3: NI-9239 Voltage Input
        voltage_module = Module(
            name="cDAQ1Mod3",
            product_type="NI 9239",
            serial_number="SIM-VI01",
            slot=3,
            chassis="cDAQ1",
            category="voltage",
            description="4-Ch ±10V AI 24-bit"
        )
        for i in range(4):
            voltage_module.channels.append(PhysicalChannel(
                name=f"cDAQ1Mod3/ai{i}",
                device="cDAQ1Mod3",
                channel_type="ai",
                index=i,
                category="voltage",
                description=f"Voltage Input {i}"
            ))
        chassis.modules.append(voltage_module)

        # Slot 4: NI-9423 Digital Input
        di_module = Module(
            name="cDAQ1Mod4",
            product_type="NI 9423",
            serial_number="SIM-DI01",
            slot=4,
            chassis="cDAQ1",
            category="digital_input",
            description="8-Ch 24V DI"
        )
        for i in range(8):
            di_module.channels.append(PhysicalChannel(
                name=f"cDAQ1Mod4/port0/line{i}",
                device="cDAQ1Mod4",
                channel_type="di",
                index=i,
                category="digital_input",
                description=f"Digital Input {i}"
            ))
        chassis.modules.append(di_module)

        # Slot 5: NI-9472 Digital Output
        do_module = Module(
            name="cDAQ1Mod5",
            product_type="NI 9472",
            serial_number="SIM-DO01",
            slot=5,
            chassis="cDAQ1",
            category="digital_output",
            description="8-Ch 24V Sourcing DO"
        )
        for i in range(8):
            do_module.channels.append(PhysicalChannel(
                name=f"cDAQ1Mod5/port0/line{i}",
                device="cDAQ1Mod5",
                channel_type="do",
                index=i,
                category="digital_output",
                description=f"Digital Output {i}"
            ))
        chassis.modules.append(do_module)

        # Slot 6: NI-9263 Analog Output
        ao_module = Module(
            name="cDAQ1Mod6",
            product_type="NI 9263",
            serial_number="SIM-AO01",
            slot=6,
            chassis="cDAQ1",
            category="analog_output",
            description="4-Ch ±10V AO"
        )
        for i in range(4):
            ao_module.channels.append(PhysicalChannel(
                name=f"cDAQ1Mod6/ao{i}",
                device="cDAQ1Mod6",
                channel_type="ao",
                index=i,
                category="analog_output",
                description=f"Analog Output {i}"
            ))
        chassis.modules.append(ao_module)

        total_channels = sum(len(m.channels) for m in chassis.modules)

        return DiscoveryResult(
            success=True,
            message=f"Simulated: Found 1 chassis, {total_channels} channels",
            timestamp=timestamp,
            chassis=[chassis],
            standalone_devices=[],
            total_channels=total_channels,
            simulation_mode=True
        )

    def _get_chassis_slots(self, product_type: str) -> int:
        """Get slot count for a chassis type"""
        slot_counts = {
            "cDAQ-9171": 1,
            "cDAQ-9174": 4,
            "cDAQ-9178": 8,
            "cDAQ-9179": 8,
            "cDAQ-9181": 1,
            "cDAQ-9184": 4,
            "cDAQ-9185": 4,
            "cDAQ-9188": 8,
            "cDAQ-9189": 8,
        }
        return slot_counts.get(product_type, 8)

    def _extract_chassis_name(self, device_name: str) -> Optional[str]:
        """Extract chassis name from device name (e.g., 'cDAQ1' from 'cDAQ1Mod1')"""
        if "Mod" in device_name:
            return device_name.split("Mod")[0]
        return None

    def _extract_slot_number(self, device_name: str) -> int:
        """Extract slot number from device name (e.g., 1 from 'cDAQ1Mod1')"""
        if "Mod" in device_name:
            try:
                return int(device_name.split("Mod")[1])
            except (ValueError, IndexError):
                pass
        return 0

    def is_stale(self, max_age_s: float = 300.0) -> bool:
        """Check if discovery results are stale (older than max_age_s seconds)."""
        if not self._last_result:
            return True
        return (__import__('time').time() - self._last_scan_time) > max_age_s

    def get_scan_age(self) -> Optional[float]:
        """Get age of last discovery scan in seconds, or None if never scanned."""
        if not self._last_scan_time:
            return None
        return __import__('time').time() - self._last_scan_time

    def get_available_channels(self) -> List[Dict]:
        """
        Get flat list of all available physical channels from last scan.

        Returns:
            List of channel dictionaries ready for config generation
        """
        if not self._last_result:
            self.scan()

        if not self._last_result:
            return []

        age = self.get_scan_age()
        if age and age > 300:
            logger.warning(f"Discovery results are {age:.0f}s old — consider re-scanning")

        channels = []

        for chassis in self._last_result.chassis:
            for module in chassis.modules:
                for channel in module.channels:
                    channels.append({
                        "physical_channel": channel.name,
                        "device": channel.device,
                        "module": module.product_type,
                        "slot": module.slot,
                        "chassis": chassis.name,
                        "channel_type": channel.channel_type,  # Hardware direction (digital_input, analog_input, etc.)
                        "category": channel.category,           # Measurement type (digital, voltage, thermocouple, etc.)
                        "index": channel.index,
                        "description": channel.description,
                        "source_type": channel.source_type,
                        "node_id": channel.node_id
                    })

        for device in self._last_result.standalone_devices:
            for channel in device.channels:
                channels.append({
                    "physical_channel": channel.name,
                    "device": channel.device,
                    "module": device.product_type,
                    "slot": device.slot,
                    "chassis": "",
                    "channel_type": channel.channel_type,  # Hardware direction
                    "category": channel.category,           # Measurement type
                    "index": channel.index,
                    "description": channel.description,
                    "source_type": channel.source_type,
                    "node_id": channel.node_id
                })

        # Add cRIO node channels
        for crio_node in self._last_result.crio_nodes:
            for module in crio_node.modules:
                for channel in module.channels:
                    channels.append({
                        "physical_channel": channel.name,
                        "device": channel.device,
                        "module": module.product_type,
                        "slot": module.slot,
                        "chassis": crio_node.node_id,
                        "channel_type": channel.channel_type,  # Hardware direction
                        "category": channel.category,           # Measurement type
                        "index": channel.index,
                        "description": channel.description,
                        "source_type": channel.source_type,
                        "node_id": channel.node_id
                    })

        # Add Opto22 node channels
        for opto22_node in self._last_result.opto22_nodes:
            for module in opto22_node.modules:
                for channel in module.channels:
                    channels.append({
                        "physical_channel": channel.name,
                        "device": channel.device,
                        "module": module.product_type,
                        "slot": module.slot,
                        "chassis": opto22_node.node_id,
                        "channel_type": channel.channel_type,  # Hardware direction
                        "category": channel.category,           # Measurement type
                        "index": channel.index,
                        "description": channel.description,
                        "source_type": channel.source_type,
                        "node_id": channel.node_id
                    })

        return channels

    def generate_config_template(self, channels: Optional[List[Dict]] = None) -> Dict[str, Any]:
        """
        Generate a configuration template from discovered channels.

        Args:
            channels: Optional list of channels (uses last scan if not provided)

        Returns:
            Configuration dictionary suitable for INI file generation
        """
        if channels is None:
            channels = self.get_available_channels()

        config = {
            "chassis": {},
            "modules": {},
            "channels": {}
        }

        # Group by chassis and module
        for ch in channels:
            chassis_name = ch.get("chassis", "")
            module_name = ch.get("device", "")

            # Add chassis
            if chassis_name and chassis_name not in config["chassis"]:
                config["chassis"][chassis_name] = {
                    "type": "cDAQ",
                    "serial": ""
                }

            # Add module
            if module_name and module_name not in config["modules"]:
                config["modules"][module_name] = {
                    "type": ch.get("module", ""),
                    "slot": ch.get("slot", 0),
                    "chassis": chassis_name
                }

            # Add channel with default config
            ch_name = self._generate_channel_name(ch)
            config["channels"][ch_name] = {
                "physical_channel": ch["physical_channel"],
                "channel_type": ch["channel_type"],
                "module": module_name,
                # display_name removed - use name (TAG) everywhere
                "unit": self._get_default_unit(ch["channel_type"]),
                "enabled": True
            }

        return config

    def _generate_channel_name(self, channel: Dict) -> str:
        """Generate a user-friendly channel name"""
        device = channel.get("device", "Dev")
        ch_type = channel.get("channel_type", "ch")
        index = channel.get("index", 0)

        type_prefixes = {
            "thermocouple": "TC",
            "rtd": "RTD",
            "voltage": "AI",
            "current": "mA",
            "strain": "STR",
            "iepe": "IEPE",
            "digital_input": "DI",
            "digital_output": "DO",
            "analog_output": "AO",
            "counter": "CTR",
        }
        prefix = type_prefixes.get(ch_type, "CH")

        # Extract module number
        mod_num = ""
        if "Mod" in device:
            mod_num = device.split("Mod")[1]

        return f"{prefix}{mod_num}_{index:02d}"

    def _get_default_unit(self, channel_type: str) -> str:
        """Get default unit for a channel type"""
        units = {
            "thermocouple": "degC",
            "rtd": "degC",
            "voltage": "V",
            "current": "mA",
            "strain": "µε",
            "iepe": "g",
            "digital_input": "",
            "digital_output": "",
            "analog_output": "V",
            "counter": "counts",
        }
        return units.get(channel_type, "")


# Standalone test
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    discovery = DeviceDiscovery()
    result = discovery.scan()

    print(f"\n{'='*60}")
    print(f"Discovery Success: {result.success}")
    print(f"Discovery Result: {result.message}")
    print(f"Simulation Mode: {result.simulation_mode}")
    print(f"Total Channels: {result.total_channels}")
    print(f"{'='*60}\n")

    if not result.success:
        print("WARNING: Discovery failed - data below may be incomplete or empty")

    for chassis in result.chassis:
        print(f"Chassis: {chassis.name} ({chassis.product_type})")
        for module in chassis.modules:
            print(f"  Slot {module.slot}: {module.product_type} - {module.description}")
            print(f"    Channels: {len(module.channels)}")

    print(f"\n{'='*60}")
    print("Available Channels:")
    for ch in discovery.get_available_channels()[:10]:
        print(f"  {ch['physical_channel']} ({ch['channel_type']})")
    print("  ...")
