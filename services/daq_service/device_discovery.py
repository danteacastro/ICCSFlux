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
except ImportError:
    NIDAQMX_AVAILABLE = False
    logger.warning("nidaqmx not available - device discovery will return simulated data")


class ModuleCategory(Enum):
    """NI C Series module categories"""
    THERMOCOUPLE = "thermocouple"
    RTD = "rtd"
    VOLTAGE_INPUT = "voltage"
    CURRENT_INPUT = "current"
    STRAIN = "strain"
    IEPE = "iepe"
    DIGITAL_INPUT = "digital_input"
    DIGITAL_OUTPUT = "digital_output"
    ANALOG_OUTPUT = "analog_output"
    COUNTER = "counter"
    RESISTANCE = "resistance"
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
    "NI 9201": {"category": ModuleCategory.VOLTAGE_INPUT, "channels": 8, "description": "8-Ch ±10V AI"},
    "NI 9205": {"category": ModuleCategory.VOLTAGE_INPUT, "channels": 32, "description": "32-Ch ±10V AI"},
    "NI 9206": {"category": ModuleCategory.VOLTAGE_INPUT, "channels": 16, "description": "16-Ch ±10V AI"},
    "NI 9215": {"category": ModuleCategory.VOLTAGE_INPUT, "channels": 4, "description": "4-Ch Simultaneous ±10V"},
    "NI 9220": {"category": ModuleCategory.VOLTAGE_INPUT, "channels": 16, "description": "16-Ch ±10V AI"},
    "NI 9221": {"category": ModuleCategory.VOLTAGE_INPUT, "channels": 8, "description": "8-Ch ±60V AI"},
    "NI 9222": {"category": ModuleCategory.VOLTAGE_INPUT, "channels": 4, "description": "4-Ch ±10V AI"},
    "NI 9223": {"category": ModuleCategory.VOLTAGE_INPUT, "channels": 4, "description": "4-Ch ±10V AI"},
    "NI 9229": {"category": ModuleCategory.VOLTAGE_INPUT, "channels": 4, "description": "4-Ch ±60V AI"},
    "NI 9239": {"category": ModuleCategory.VOLTAGE_INPUT, "channels": 4, "description": "4-Ch ±10V AI 24-bit"},

    # Current input modules
    "NI 9203": {"category": ModuleCategory.CURRENT_INPUT, "channels": 8, "description": "8-Ch ±20mA AI"},
    "NI 9207": {"category": ModuleCategory.CURRENT_INPUT, "channels": 16, "description": "16-Ch V/I AI"},
    "NI 9208": {"category": ModuleCategory.CURRENT_INPUT, "channels": 16, "description": "16-Ch ±20mA AI"},
    "NI 9227": {"category": ModuleCategory.CURRENT_INPUT, "channels": 4, "description": "4-Ch Current AI"},
    "NI 9246": {"category": ModuleCategory.CURRENT_INPUT, "channels": 3, "description": "3-Ch Current AI"},
    "NI 9247": {"category": ModuleCategory.CURRENT_INPUT, "channels": 3, "description": "3-Ch Current AI"},
    "NI 9253": {"category": ModuleCategory.CURRENT_INPUT, "channels": 8, "description": "8-Ch ±20mA AI"},

    # Strain/Bridge modules
    "NI 9235": {"category": ModuleCategory.STRAIN, "channels": 8, "description": "8-Ch Quarter Bridge"},
    "NI 9236": {"category": ModuleCategory.STRAIN, "channels": 8, "description": "8-Ch Quarter Bridge"},
    "NI 9237": {"category": ModuleCategory.STRAIN, "channels": 4, "description": "4-Ch Bridge AI"},

    # IEPE/Accelerometer modules
    "NI 9230": {"category": ModuleCategory.IEPE, "channels": 3, "description": "3-Ch IEPE AI"},
    "NI 9231": {"category": ModuleCategory.IEPE, "channels": 8, "description": "8-Ch IEPE AI"},
    "NI 9232": {"category": ModuleCategory.IEPE, "channels": 3, "description": "3-Ch IEPE AI"},
    "NI 9233": {"category": ModuleCategory.IEPE, "channels": 4, "description": "4-Ch IEPE AI"},
    "NI 9234": {"category": ModuleCategory.IEPE, "channels": 4, "description": "4-Ch IEPE AI"},
    "NI 9250": {"category": ModuleCategory.IEPE, "channels": 2, "description": "2-Ch IEPE AI"},
    "NI 9251": {"category": ModuleCategory.IEPE, "channels": 2, "description": "2-Ch IEPE AI"},

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

    "NI 9470": {"category": ModuleCategory.DIGITAL_OUTPUT, "channels": 8, "description": "8-Ch 24V Sourcing DO"},
    "NI 9472": {"category": ModuleCategory.DIGITAL_OUTPUT, "channels": 8, "description": "8-Ch 24V Sourcing DO"},
    "NI 9474": {"category": ModuleCategory.DIGITAL_OUTPUT, "channels": 8, "description": "8-Ch 24V Sourcing DO"},
    "NI 9475": {"category": ModuleCategory.DIGITAL_OUTPUT, "channels": 8, "description": "8-Ch 60V Sourcing DO"},
    "NI 9476": {"category": ModuleCategory.DIGITAL_OUTPUT, "channels": 32, "description": "32-Ch 24V Sourcing DO"},
    "NI 9477": {"category": ModuleCategory.DIGITAL_OUTPUT, "channels": 32, "description": "32-Ch 60V Sinking DO"},
    "NI 9478": {"category": ModuleCategory.DIGITAL_OUTPUT, "channels": 16, "description": "16-Ch Sinking DO"},

    # Analog output modules
    "NI 9260": {"category": ModuleCategory.ANALOG_OUTPUT, "channels": 2, "description": "2-Ch ±10V AO"},
    "NI 9262": {"category": ModuleCategory.ANALOG_OUTPUT, "channels": 2, "description": "2-Ch ±10V AO"},
    "NI 9263": {"category": ModuleCategory.ANALOG_OUTPUT, "channels": 4, "description": "4-Ch ±10V AO"},
    "NI 9264": {"category": ModuleCategory.ANALOG_OUTPUT, "channels": 16, "description": "16-Ch ±10V AO"},
    "NI 9265": {"category": ModuleCategory.ANALOG_OUTPUT, "channels": 4, "description": "4-Ch 0-20mA AO"},
    "NI 9266": {"category": ModuleCategory.ANALOG_OUTPUT, "channels": 8, "description": "8-Ch 0-20mA AO"},
    "NI 9269": {"category": ModuleCategory.ANALOG_OUTPUT, "channels": 4, "description": "4-Ch ±10V AO"},

    # Counter modules
    "NI 9361": {"category": ModuleCategory.COUNTER, "channels": 8, "description": "8-Ch Counter/DI"},

    # Universal modules
    "NI 9219": {"category": ModuleCategory.UNIVERSAL, "channels": 4, "description": "4-Ch Universal AI"},
}


@dataclass
class PhysicalChannel:
    """Represents a physical channel on an NI module"""
    name: str                    # e.g., "cDAQ1Mod1/ai0"
    device: str                  # e.g., "cDAQ1Mod1"
    channel_type: str            # e.g., "ai", "ao", "di", "do", "ci"
    index: int                   # Channel index (0, 1, 2...)
    category: str                # Module category (thermocouple, voltage, etc.)
    description: str = ""

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
    serial_number: str
    status: str                  # "online", "offline", "unknown"
    last_seen: str               # ISO timestamp
    channels: int = 0            # Number of configured channels
    modules: List[Module] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            **asdict(self),
            "modules": [mod.to_dict() for mod in self.modules],
            "node_type": "crio"
        }


@dataclass
class DiscoveryResult:
    """Complete discovery result"""
    success: bool
    message: str
    timestamp: str
    chassis: List[Chassis] = field(default_factory=list)
    standalone_devices: List[Module] = field(default_factory=list)
    crio_nodes: List[CRIONode] = field(default_factory=list)  # Remote cRIO nodes
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
            "crio_nodes": [node.to_dict() for node in self.crio_nodes]
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
        # Track cRIO nodes that have registered via MQTT
        self._crio_nodes: Dict[str, CRIONode] = {}
        self._crio_lock = __import__('threading').Lock()

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
                # Parse channels
                for ch_data in mod_data.get('channels', []):
                    mod.channels.append(PhysicalChannel(
                        name=ch_data.get('name', ''),
                        device=mod.name,
                        channel_type=ch_data.get('channel_type', ''),
                        index=ch_data.get('index', 0),
                        category=ch_data.get('category', ''),
                        description=ch_data.get('description', '')
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
                modules=modules
            )
            logger.info(f"Registered cRIO node: {node_id} ({status_data.get('status', 'online')})")

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
                    modules=[]  # Will be populated when full status arrives
                )
                logger.info(f"Registered cRIO node: {node_id} ({heartbeat_data.get('status', 'online')})")

    def get_crio_nodes(self) -> List[CRIONode]:
        """Get list of known cRIO nodes"""
        with self._crio_lock:
            return list(self._crio_nodes.values())

    def scan(self, include_crio: bool = True) -> DiscoveryResult:
        """
        Scan for all connected NI devices (local and remote cRIO).

        Args:
            include_crio: If True, include registered cRIO nodes in results

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
                logger.error(f"Hardware scan failed: {e}")
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

        self._last_result = result
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

        # Enumerate physical channels
        module.channels = self._enumerate_channels(device, category)

        return module

    def _enumerate_channels(self, device, category: ModuleCategory) -> List[PhysicalChannel]:
        """Enumerate all physical channels on a device"""
        channels: List[PhysicalChannel] = []
        device_name = device.name
        cat_value = category.value if isinstance(category, ModuleCategory) else str(category)

        # Analog input channels
        for i, ai_chan in enumerate(device.ai_physical_chans):
            channels.append(PhysicalChannel(
                name=ai_chan.name,
                device=device_name,
                channel_type="ai",
                index=i,
                category=cat_value,
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
                        "channel_type": channel.category,
                        "index": channel.index,
                        "description": channel.description
                    })

        for device in self._last_result.standalone_devices:
            for channel in device.channels:
                channels.append({
                    "physical_channel": channel.name,
                    "device": channel.device,
                    "module": device.product_type,
                    "slot": device.slot,
                    "chassis": "",
                    "channel_type": channel.category,
                    "index": channel.index,
                    "description": channel.description
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
    print(f"Discovery Result: {result.message}")
    print(f"Simulation Mode: {result.simulation_mode}")
    print(f"Total Channels: {result.total_channels}")
    print(f"{'='*60}\n")

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
