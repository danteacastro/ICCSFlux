#!/usr/bin/env python3
"""
Modbus Poll Tool — Standalone Modbus TCP/RTU diagnostic and configuration tool.
A web-based clone of the commercial Modbus Poll application.

Usage:
    python modbus_tool.py [--port 8502] [--no-browser]

Requires: pip install fastapi uvicorn pymodbus pyserial
"""

import argparse
import asyncio
import csv
import io
import json
import logging
import os
import signal
import socket
import sys
import time
import uuid
import webbrowser
from collections import deque
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
import uvicorn

from modbus_adapter import (
    ModbusConnection,
    ModbusDeviceConfig,
    ModbusDataType,
    ModbusRegisterType,
    REGISTERS_PER_TYPE,
    PYMODBUS_AVAILABLE,
    EXCEPTION_CODES,
    decode_registers,
    encode_value,
    list_serial_ports,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ModbusTool")


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class ConnectionConfig:
    id: str = ""
    name: str = "New Device"
    connection_type: str = "tcp"
    ip_address: str = "192.168.1.100"
    port: int = 502
    serial_port: str = "COM1"
    baudrate: int = 9600
    parity: str = "N"
    stopbits: int = 1
    bytesize: int = 8
    timeout: float = 1.0
    retries: int = 3


@dataclass
class PollDefinition:
    id: str = ""
    connection_id: str = ""
    name: str = "New Poll"
    register_type: str = "holding"
    start_address: int = 0
    count: int = 10
    slave_id: int = 1
    scan_rate_ms: int = 1000
    enabled: bool = True
    descriptions: Dict[int, str] = field(default_factory=dict)


@dataclass
class ConnectionStats:
    tx_count: int = 0
    rx_count: int = 0
    error_count: int = 0
    last_response_ms: float = 0.0
    connected: bool = False
    last_error: str = ""


# ---------------------------------------------------------------------------
# Traffic log handler — captures pymodbus debug frames
# ---------------------------------------------------------------------------

class TrafficEntry:
    __slots__ = ("timestamp", "connection_id", "direction", "function_code",
                 "raw_hex", "summary")

    def __init__(self, timestamp: float, connection_id: str, direction: str,
                 function_code: int, raw_hex: str, summary: str):
        self.timestamp = timestamp
        self.connection_id = connection_id
        self.direction = direction
        self.function_code = function_code
        self.raw_hex = raw_hex
        self.summary = summary

    def to_dict(self):
        return {
            "timestamp": self.timestamp,
            "connection_id": self.connection_id,
            "direction": self.direction,
            "function_code": self.function_code,
            "raw_hex": self.raw_hex,
            "summary": self.summary,
        }


FC_NAMES = {
    1: "Read Coils", 2: "Read Discrete Inputs",
    3: "Read Holding Registers", 4: "Read Input Registers",
    5: "Write Single Coil", 6: "Write Single Register",
    15: "Write Multiple Coils", 16: "Write Multiple Registers",
    43: "Read Device Identification",
}


class PymodbusTrafficHandler(logging.Handler):
    """Intercepts pymodbus debug logs to capture TX/RX frames."""

    def __init__(self, poll_manager: "PollManager"):
        super().__init__()
        self.poll_manager = poll_manager

    def emit(self, record):
        try:
            msg = record.getMessage()
            lower = msg.lower()
            if "send:" in lower or "recv:" in lower:
                direction = "TX" if "send:" in lower else "RX"
                idx = lower.find("send:") if direction == "TX" else lower.find("recv:")
                raw_part = msg[idx + 5:].strip()

                # Try to extract function code from hex bytes
                fc = 0
                hex_bytes = raw_part.split()
                # For TCP: bytes 7+ contain the PDU. Byte 7 is function code.
                # For RTU: byte 1 is function code.
                if len(hex_bytes) >= 8:
                    try:
                        fc = int(hex_bytes[7], 16)
                    except (ValueError, IndexError):
                        pass
                elif len(hex_bytes) >= 2:
                    try:
                        fc = int(hex_bytes[1], 16)
                    except (ValueError, IndexError):
                        pass

                fc_name = FC_NAMES.get(fc, f"FC{fc}") if fc else ""
                summary = f"{direction} {len(hex_bytes)} bytes"
                if fc_name:
                    summary = f"{fc_name} — {len(hex_bytes)} bytes"

                entry = TrafficEntry(
                    timestamp=time.time(),
                    connection_id="",
                    direction=direction,
                    function_code=fc,
                    raw_hex=raw_part[:200],
                    summary=summary,
                )
                self.poll_manager.add_traffic(entry)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Continuous data logger
# ---------------------------------------------------------------------------

class DataLogger:
    """Logs poll data continuously to CSV files."""

    def __init__(self, log_dir: Path):
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.active_files: Dict[str, io.TextIOWrapper] = {}
        self.active_writers: Dict[str, csv.writer] = {}
        self.logging_polls: set = set()

    def start_logging(self, poll_id: str, poll_name: str, start_address: int, count: int):
        if poll_id in self.active_files:
            return
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in poll_name)
        filename = self.log_dir / f"modbus_log_{safe_name}_{ts}.csv"
        f = open(filename, "w", newline="", buffering=1)
        writer = csv.writer(f)
        header = ["Timestamp"] + [str(start_address + i) for i in range(count)]
        writer.writerow(header)
        self.active_files[poll_id] = f
        self.active_writers[poll_id] = writer
        self.logging_polls.add(poll_id)
        logger.info(f"Data logging started: {filename}")
        return str(filename)

    def stop_logging(self, poll_id: str):
        self.logging_polls.discard(poll_id)
        f = self.active_files.pop(poll_id, None)
        self.active_writers.pop(poll_id, None)
        if f:
            f.close()
            logger.info(f"Data logging stopped for poll {poll_id}")

    def log_data(self, poll_id: str, values: List):
        writer = self.active_writers.get(poll_id)
        if writer:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            writer.writerow([ts] + values)

    def is_logging(self, poll_id: str) -> bool:
        return poll_id in self.logging_polls

    def shutdown(self):
        for poll_id in list(self.active_files):
            self.stop_logging(poll_id)


# ---------------------------------------------------------------------------
# Poll Manager — manages connections, polls, traffic, WebSocket broadcast
# ---------------------------------------------------------------------------

class PollManager:
    def __init__(self):
        self.connections: Dict[str, ConnectionConfig] = {}
        self.clients: Dict[str, ModbusConnection] = {}
        self.stats: Dict[str, ConnectionStats] = {}
        self.polls: Dict[str, PollDefinition] = {}
        self.poll_tasks: Dict[str, asyncio.Task] = {}
        self.latest_results: Dict[str, Dict] = {}
        self.traffic: deque = deque(maxlen=2000)
        self.subscribers: List[WebSocket] = []
        self._scan_task: Optional[asyncio.Task] = None
        self._scan_cancel: bool = False
        self._scan_results: Dict = {}

        # Data logger
        log_dir = Path(__file__).parent / "logs"
        if getattr(sys, 'frozen', False):
            log_dir = Path(sys.executable).parent / "logs"
        self.data_logger = DataLogger(log_dir)

    # --- Connections ---

    def add_connection(self, cfg: dict) -> ConnectionConfig:
        conn = ConnectionConfig(**{k: v for k, v in cfg.items() if hasattr(ConnectionConfig, k)})
        if not conn.id:
            conn.id = str(uuid.uuid4())[:8]
        self.connections[conn.id] = conn
        self.stats[conn.id] = ConnectionStats()
        return conn

    def update_connection(self, conn_id: str, cfg: dict) -> Optional[ConnectionConfig]:
        """Update connection config without dropping existing connection."""
        conn = self.connections.get(conn_id)
        if not conn:
            return None
        was_connected = conn_id in self.clients and self.stats.get(conn_id, ConnectionStats()).connected
        needs_reconnect = False
        for k, v in cfg.items():
            if hasattr(conn, k) and k != "id":
                old_val = getattr(conn, k)
                setattr(conn, k, v)
                if k in ("connection_type", "ip_address", "port", "serial_port",
                         "baudrate", "parity", "stopbits", "bytesize", "timeout", "retries"):
                    if old_val != v:
                        needs_reconnect = True
        if needs_reconnect and was_connected:
            self.disconnect(conn_id)
            self.connect(conn_id)
        return conn

    def remove_connection(self, conn_id: str):
        for poll_id in list(self.polls):
            if self.polls[poll_id].connection_id == conn_id:
                self.stop_poll(poll_id)
                del self.polls[poll_id]
        self.disconnect(conn_id)
        self.connections.pop(conn_id, None)
        self.clients.pop(conn_id, None)
        self.stats.pop(conn_id, None)

    def connect(self, conn_id: str) -> bool:
        cfg = self.connections.get(conn_id)
        if not cfg:
            return False
        device_cfg = ModbusDeviceConfig(
            name=cfg.name,
            connection_type=cfg.connection_type,
            ip_address=cfg.ip_address,
            port=cfg.port,
            serial_port=cfg.serial_port,
            baudrate=cfg.baudrate,
            parity=cfg.parity,
            stopbits=cfg.stopbits,
            bytesize=cfg.bytesize,
            timeout=cfg.timeout,
            retries=cfg.retries,
        )
        try:
            client = ModbusConnection(device_cfg)
            success = client.connect()
            if success:
                self.clients[conn_id] = client
                self.stats[conn_id].connected = True
                self.stats[conn_id].last_error = ""
                logger.info(f"Connected: {cfg.name} ({cfg.connection_type})")
            else:
                self.stats[conn_id].connected = False
                self.stats[conn_id].last_error = client.last_error or "Connection failed"
            return success
        except Exception as e:
            self.stats[conn_id].connected = False
            self.stats[conn_id].last_error = str(e)
            return False

    def disconnect(self, conn_id: str):
        client = self.clients.get(conn_id)
        if client:
            client.disconnect()
        self.clients.pop(conn_id, None)
        if conn_id in self.stats:
            self.stats[conn_id].connected = False

    def test_connection(self, conn_id: str) -> Dict:
        start = time.time()
        success = self.connect(conn_id)
        elapsed = (time.time() - start) * 1000
        if success:
            client = self.clients.get(conn_id)
            if client:
                read_start = time.time()
                result = client.read_holding_registers(0, 1, 1)
                read_elapsed = (time.time() - read_start) * 1000
                return {
                    "success": True,
                    "connect_ms": round(elapsed, 1),
                    "read_ms": round(read_elapsed, 1),
                    "read_ok": result is not None,
                }
        return {"success": False, "error": self.stats.get(conn_id, ConnectionStats()).last_error}

    def read_device_id(self, conn_id: str, slave_id: int) -> Dict:
        client = self.clients.get(conn_id)
        if not client or not client.connected:
            return {"success": False, "error": "Not connected"}
        info = client.read_device_identification(slave_id)
        if info:
            return {"success": True, "info": info}
        return {"success": False, "error": client.last_error or "Device does not support FC43"}

    # --- Polls ---

    def add_poll(self, cfg: dict) -> PollDefinition:
        poll = PollDefinition(**{k: v for k, v in cfg.items()
                                 if hasattr(PollDefinition, k) and k != "descriptions"})
        if "descriptions" in cfg and isinstance(cfg["descriptions"], dict):
            poll.descriptions = {int(k): v for k, v in cfg["descriptions"].items()}
        if not poll.id:
            poll.id = str(uuid.uuid4())[:8]
        self.polls[poll.id] = poll
        return poll

    def update_poll(self, poll_id: str, cfg: dict) -> Optional[PollDefinition]:
        poll = self.polls.get(poll_id)
        if not poll:
            return None
        was_running = poll_id in self.poll_tasks
        if was_running:
            self.stop_poll(poll_id)
        for k, v in cfg.items():
            if hasattr(poll, k) and k not in ("id",):
                if k == "descriptions":
                    poll.descriptions = {int(dk): dv for dk, dv in v.items()} if isinstance(v, dict) else {}
                else:
                    setattr(poll, k, v)
        if was_running and poll.enabled:
            self.start_poll(poll_id)
        return poll

    def remove_poll(self, poll_id: str):
        self.stop_poll(poll_id)
        self.data_logger.stop_logging(poll_id)
        self.polls.pop(poll_id, None)
        self.latest_results.pop(poll_id, None)

    def start_poll(self, poll_id: str):
        if poll_id in self.poll_tasks:
            return
        poll = self.polls.get(poll_id)
        if not poll:
            return
        task = asyncio.create_task(self._poll_loop(poll_id))
        self.poll_tasks[poll_id] = task

    def stop_poll(self, poll_id: str):
        task = self.poll_tasks.pop(poll_id, None)
        if task:
            task.cancel()

    async def _poll_loop(self, poll_id: str):
        try:
            while True:
                poll = self.polls.get(poll_id)
                if not poll or not poll.enabled:
                    break

                client = self.clients.get(poll.connection_id)
                if not client or not client.connected:
                    await asyncio.sleep(poll.scan_rate_ms / 1000.0)
                    continue

                start = time.time()
                values = await asyncio.to_thread(
                    self._do_read, client, poll.register_type,
                    poll.start_address, poll.count, poll.slave_id
                )
                elapsed = (time.time() - start) * 1000

                stats = self.stats.get(poll.connection_id)
                if stats:
                    stats.tx_count += 1

                success = values is not None
                if success and stats:
                    stats.rx_count += 1
                    stats.last_response_ms = round(elapsed, 1)
                elif stats:
                    stats.error_count += 1
                    stats.last_error = client.last_error or "Read failed"

                result = {
                    "type": "poll_data",
                    "poll_id": poll_id,
                    "timestamp": time.time(),
                    "success": success,
                    "response_time_ms": round(elapsed, 1),
                    "values": values if values is not None else [],
                    "register_type": poll.register_type,
                    "start_address": poll.start_address,
                    "count": poll.count,
                    "slave_id": poll.slave_id,
                }
                self.latest_results[poll_id] = result
                await self.broadcast(result)

                # Continuous data logging
                if success and self.data_logger.is_logging(poll_id):
                    self.data_logger.log_data(poll_id, values)

                # Stats update
                if stats:
                    await self.broadcast({
                        "type": "connection_status",
                        "connection_id": poll.connection_id,
                        "stats": asdict(stats),
                    })

                sleep_time = max(0, (poll.scan_rate_ms / 1000.0) - (time.time() - start))
                await asyncio.sleep(sleep_time)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Poll loop {poll_id} error: {e}")

    def _do_read(self, client: ModbusConnection, reg_type: str,
                 address: int, count: int, slave_id: int) -> Optional[List]:
        rt = reg_type.lower()
        if rt == "holding":
            return client.read_holding_registers(address, count, slave_id)
        elif rt == "input":
            return client.read_input_registers(address, count, slave_id)
        elif rt == "coil":
            bits = client.read_coils(address, count, slave_id)
            return [1 if b else 0 for b in bits] if bits is not None else None
        elif rt == "discrete":
            bits = client.read_discrete_inputs(address, count, slave_id)
            return [1 if b else 0 for b in bits] if bits is not None else None
        return None

    # --- Write ---

    def write_register(self, conn_id: str, slave_id: int, address: int,
                       value: float, data_type: str,
                       byte_order: str = "big", word_order: str = "big") -> Dict:
        client = self.clients.get(conn_id)
        if not client or not client.connected:
            return {"success": False, "error": "Not connected"}
        try:
            dt = ModbusDataType(data_type)
            regs = encode_value(value, dt, byte_order, word_order)
            if len(regs) == 1:
                ok = client.write_register(address, regs[0], slave_id)
            else:
                ok = client.write_registers(address, regs, slave_id)
            stats = self.stats.get(conn_id)
            if stats:
                stats.tx_count += 1
                if ok:
                    stats.rx_count += 1
            return {"success": ok, "registers_written": regs}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def write_coil(self, conn_id: str, slave_id: int, address: int, value: bool) -> Dict:
        client = self.clients.get(conn_id)
        if not client or not client.connected:
            return {"success": False, "error": "Not connected"}
        try:
            ok = client.write_coil(address, value, slave_id)
            stats = self.stats.get(conn_id)
            if stats:
                stats.tx_count += 1
                if ok:
                    stats.rx_count += 1
            return {"success": ok}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def write_coils(self, conn_id: str, slave_id: int, address: int,
                    values: List[bool]) -> Dict:
        """Write multiple coils (FC15)."""
        client = self.clients.get(conn_id)
        if not client or not client.connected:
            return {"success": False, "error": "Not connected"}
        try:
            ok = client.write_coils(address, values, slave_id)
            stats = self.stats.get(conn_id)
            if stats:
                stats.tx_count += 1
                if ok:
                    stats.rx_count += 1
            return {"success": ok}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # --- Scanner ---

    async def scan_registers(self, conn_id: str, slave_id: int, reg_type: str,
                             start: int, end: int):
        self._scan_cancel = False
        client = self.clients.get(conn_id)
        if not client or not client.connected:
            await self.broadcast({"type": "scan_complete", "connection_id": conn_id,
                                  "found": [], "error": "Not connected"})
            return

        found = []
        total = end - start + 1
        for addr in range(start, end + 1):
            if self._scan_cancel:
                await self.broadcast({
                    "type": "scan_complete", "connection_id": conn_id,
                    "found": found, "total_scanned": addr - start, "cancelled": True,
                })
                return

            result = await asyncio.to_thread(
                self._do_read, client, reg_type, addr, 1, slave_id
            )
            if result is not None:
                found.append({"address": addr, "value": result[0]})

            if (addr - start) % 10 == 0 or addr == end:
                await self.broadcast({
                    "type": "scan_progress",
                    "connection_id": conn_id,
                    "current": addr - start + 1,
                    "total": total,
                    "found": found,
                })

        self._scan_results = {
            "connection_id": conn_id,
            "found": found,
            "total_scanned": total,
        }
        await self.broadcast({
            "type": "scan_complete",
            "connection_id": conn_id,
            "found": found,
            "total_scanned": total,
        })

    def cancel_scan(self):
        self._scan_cancel = True

    # --- Traffic ---

    def add_traffic(self, entry: TrafficEntry):
        self.traffic.append(entry)
        # Also push to WebSocket subscribers asynchronously
        # (can't await here since we're in a logging handler)

    def get_traffic(self, limit: int = 200) -> List[Dict]:
        entries = list(self.traffic)[-limit:]
        return [e.to_dict() for e in entries]

    def clear_traffic(self):
        self.traffic.clear()

    # --- WebSocket ---

    async def broadcast(self, message: Dict):
        data = json.dumps(message)
        disconnected = []
        for ws in self.subscribers:
            try:
                await ws.send_text(data)
            except Exception:
                disconnected.append(ws)
        for ws in disconnected:
            if ws in self.subscribers:
                self.subscribers.remove(ws)

    # --- CSV export ---

    def export_csv(self, poll_id: str) -> Optional[str]:
        result = self.latest_results.get(poll_id)
        poll = self.polls.get(poll_id)
        if not result or not poll:
            return None
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Address", "Raw Value", "Description"])
        values = result.get("values", [])
        for i, val in enumerate(values):
            addr = poll.start_address + i
            desc = poll.descriptions.get(i, "")
            writer.writerow([addr, val, desc])
        return output.getvalue()

    # --- Workspace ---

    def get_workspace(self) -> Dict:
        return {
            "version": "1.0",
            "connections": [asdict(c) for c in self.connections.values()],
            "polls": [{**asdict(p), "descriptions": {str(k): v for k, v in p.descriptions.items()}}
                      for p in self.polls.values()],
        }

    def load_workspace(self, data: Dict):
        for pid in list(self.poll_tasks):
            self.stop_poll(pid)
        for cid in list(self.clients):
            self.disconnect(cid)
        self.connections.clear()
        self.polls.clear()
        self.stats.clear()
        self.latest_results.clear()
        for c in data.get("connections", []):
            self.add_connection(c)
        for p in data.get("polls", []):
            self.add_poll(p)

    # --- Shutdown ---

    def shutdown(self):
        self.data_logger.shutdown()
        for pid in list(self.poll_tasks):
            self.stop_poll(pid)
        for cid in list(self.clients):
            self.disconnect(cid)
        logger.info("PollManager shut down")


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

manager = PollManager()


@asynccontextmanager
async def lifespan(app):
    # Startup
    pymodbus_logger = logging.getLogger("pymodbus")
    pymodbus_logger.setLevel(logging.DEBUG)
    handler = PymodbusTrafficHandler(manager)
    handler.setLevel(logging.DEBUG)
    pymodbus_logger.addHandler(handler)
    logger.info("Modbus Poll Tool started")
    yield
    # Shutdown
    manager.shutdown()
    logger.info("Modbus Poll Tool stopped")


app = FastAPI(title="Modbus Poll Tool", lifespan=lifespan)


def get_html_path() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS) / "index.html"
    return Path(__file__).parent / "index.html"


@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    html_path = get_html_path()
    if html_path.exists():
        return HTMLResponse(html_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Modbus Poll Tool</h1><p>index.html not found</p>")


# --- Serial ports ---

@app.get("/api/serial-ports")
async def get_serial_ports():
    return list_serial_ports()


# --- Connections ---

@app.get("/api/connections")
async def list_connections():
    result = []
    for cid, cfg in manager.connections.items():
        stats = manager.stats.get(cid, ConnectionStats())
        result.append({**asdict(cfg), "stats": asdict(stats)})
    return result


@app.post("/api/connections")
async def add_connection(body: dict):
    conn = manager.add_connection(body)
    return asdict(conn)


@app.put("/api/connections/{conn_id}")
async def update_connection(conn_id: str, body: dict):
    conn = manager.update_connection(conn_id, body)
    if not conn:
        return JSONResponse({"error": "Not found"}, 404)
    stats = manager.stats.get(conn_id, ConnectionStats())
    return {**asdict(conn), "stats": asdict(stats)}


@app.delete("/api/connections/{conn_id}")
async def remove_connection(conn_id: str):
    manager.remove_connection(conn_id)
    return {"ok": True}


@app.post("/api/connections/{conn_id}/connect")
async def connect_device(conn_id: str):
    success = await asyncio.to_thread(manager.connect, conn_id)
    stats = manager.stats.get(conn_id, ConnectionStats())
    return {"success": success, "stats": asdict(stats)}


@app.post("/api/connections/{conn_id}/disconnect")
async def disconnect_device(conn_id: str):
    manager.disconnect(conn_id)
    return {"ok": True}


@app.post("/api/connections/{conn_id}/test")
async def test_connection(conn_id: str):
    result = await asyncio.to_thread(manager.test_connection, conn_id)
    return result


@app.post("/api/connections/{conn_id}/identify")
async def identify_device(conn_id: str, body: dict = None):
    slave_id = (body or {}).get("slave_id", 1)
    result = await asyncio.to_thread(manager.read_device_id, conn_id, slave_id)
    return result


# --- Polls ---

@app.get("/api/polls")
async def list_polls():
    result = []
    for pid, poll in manager.polls.items():
        running = pid in manager.poll_tasks
        logging_active = manager.data_logger.is_logging(pid)
        result.append({**asdict(poll), "running": running, "logging": logging_active,
                       "descriptions": {str(k): v for k, v in poll.descriptions.items()}})
    return result


@app.post("/api/polls")
async def add_poll(body: dict):
    poll = manager.add_poll(body)
    return {**asdict(poll), "descriptions": {str(k): v for k, v in poll.descriptions.items()}}


@app.put("/api/polls/{poll_id}")
async def update_poll(poll_id: str, body: dict):
    poll = manager.update_poll(poll_id, body)
    if not poll:
        return JSONResponse({"error": "Not found"}, 404)
    return {**asdict(poll), "descriptions": {str(k): v for k, v in poll.descriptions.items()}}


@app.delete("/api/polls/{poll_id}")
async def remove_poll(poll_id: str):
    manager.remove_poll(poll_id)
    return {"ok": True}


@app.post("/api/polls/{poll_id}/start")
async def start_poll(poll_id: str):
    manager.start_poll(poll_id)
    return {"ok": True}


@app.post("/api/polls/{poll_id}/stop")
async def stop_poll(poll_id: str):
    manager.stop_poll(poll_id)
    return {"ok": True}


@app.post("/api/polls/{poll_id}/descriptions")
async def update_descriptions(poll_id: str, body: dict):
    """Update per-register descriptions."""
    poll = manager.polls.get(poll_id)
    if not poll:
        return JSONResponse({"error": "Not found"}, 404)
    poll.descriptions = {int(k): v for k, v in body.items()}
    return {"ok": True}


# --- Data logging ---

@app.post("/api/polls/{poll_id}/log/start")
async def start_logging(poll_id: str):
    poll = manager.polls.get(poll_id)
    if not poll:
        return JSONResponse({"error": "Not found"}, 404)
    filename = manager.data_logger.start_logging(
        poll_id, poll.name, poll.start_address, poll.count
    )
    return {"ok": True, "filename": filename}


@app.post("/api/polls/{poll_id}/log/stop")
async def stop_logging(poll_id: str):
    manager.data_logger.stop_logging(poll_id)
    return {"ok": True}


# --- Write ---

@app.post("/api/write/register")
async def write_register(body: dict):
    result = await asyncio.to_thread(
        manager.write_register,
        body["connection_id"],
        body.get("slave_id", 1),
        body["address"],
        body["value"],
        body.get("data_type", "uint16"),
        body.get("byte_order", "big"),
        body.get("word_order", "big"),
    )
    return result


@app.post("/api/write/coil")
async def write_coil(body: dict):
    result = await asyncio.to_thread(
        manager.write_coil,
        body["connection_id"],
        body.get("slave_id", 1),
        body["address"],
        bool(body["value"]),
    )
    return result


@app.post("/api/write/coils")
async def write_coils(body: dict):
    """Write multiple coils (FC15)."""
    values = [bool(v) for v in body["values"]]
    result = await asyncio.to_thread(
        manager.write_coils,
        body["connection_id"],
        body.get("slave_id", 1),
        body["address"],
        values,
    )
    return result


# --- Scanner ---

@app.post("/api/scan")
async def scan_registers(body: dict):
    conn_id = body["connection_id"]
    slave_id = body.get("slave_id", 1)
    reg_type = body.get("register_type", "holding")
    start = body.get("start_address", 0)
    end = body.get("end_address", 99)

    if manager._scan_task and not manager._scan_task.done():
        return {"error": "Scan already in progress"}

    manager._scan_task = asyncio.create_task(
        manager.scan_registers(conn_id, slave_id, reg_type, start, end)
    )
    return {"ok": True, "total": end - start + 1}


@app.post("/api/scan/cancel")
async def cancel_scan():
    manager.cancel_scan()
    return {"ok": True}


@app.get("/api/scan/results")
async def get_scan_results():
    return manager._scan_results


# --- Traffic log ---

@app.get("/api/traffic")
async def get_traffic(limit: int = 200):
    return manager.get_traffic(limit)


@app.delete("/api/traffic")
async def clear_traffic():
    manager.clear_traffic()
    return {"ok": True}


# --- CSV export ---

@app.get("/api/export/csv/{poll_id}")
async def export_csv(poll_id: str):
    data = manager.export_csv(poll_id)
    if not data:
        return JSONResponse({"error": "No data"}, 404)
    return StreamingResponse(
        io.StringIO(data),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=modbus_poll_{poll_id}.csv"},
    )


# --- Workspace ---

@app.post("/api/workspace/save")
async def save_workspace():
    return manager.get_workspace()


@app.post("/api/workspace/load")
async def load_workspace(body: dict):
    manager.load_workspace(body)
    return {"ok": True, "connections": len(manager.connections), "polls": len(manager.polls)}


# --- Stats ---

@app.get("/api/stats")
async def get_stats():
    return {cid: asdict(s) for cid, s in manager.stats.items()}


# --- WebSocket ---

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    manager.subscribers.append(ws)
    logger.info(f"WebSocket client connected ({len(manager.subscribers)} total)")
    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            if msg.get("type") == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if ws in manager.subscribers:
            manager.subscribers.remove(ws)
        logger.info(f"WebSocket client disconnected ({len(manager.subscribers)} total)")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def is_port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def main():
    parser = argparse.ArgumentParser(description="Modbus Poll Tool")
    parser.add_argument("--port", type=int, default=8502, help="HTTP port (default: 8502)")
    parser.add_argument("--no-browser", action="store_true", help="Don't open browser")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    args = parser.parse_args()

    port = args.port
    if not is_port_available(port):
        for p in range(port + 1, port + 10):
            if is_port_available(p):
                port = p
                break
        else:
            print(f"ERROR: Ports {args.port}-{args.port + 9} all in use")
            sys.exit(1)

    if not PYMODBUS_AVAILABLE:
        print("WARNING: pymodbus not installed. Install with: pip install pymodbus pyserial")
        print("The tool will start but connections will fail.")

    url = f"http://{args.host}:{port}"
    print(f"Modbus Poll Tool starting at {url}")

    if not args.no_browser:
        def open_browser():
            time.sleep(1.0)
            webbrowser.open(url)
        import threading
        threading.Thread(target=open_browser, daemon=True).start()

    def handle_signal(sig, frame):
        logger.info("Shutting down...")
        manager.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    uvicorn.run(app, host=args.host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
