"""
Serial port reading for GC instruments.

Reads raw serial data from a GC instrument COM port and extracts
complete frames using configurable framing protocols:

  - line:     Newline-delimited (CR, LF, or CRLF)
  - stx_etx:  STX (0x02) ... ETX (0x03) framing
  - custom:   User-defined start/end markers

Each complete frame is parsed via GCParser and the resulting dict
is passed to the on_new_frame callback.
"""

import logging
import threading
import time
from typing import Any, Callable, Dict, Optional

from .config import SerialSourceConfig, AnalysisSourceConfig

logger = logging.getLogger('GCNode')

# Try to import pyserial; source will not start if unavailable.
try:
    import serial
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False
    serial = None

# Try to import GCParser. May not exist yet during early development.
try:
    from .gc_parser import GCParser
    PARSER_AVAILABLE = True
except ImportError:
    GCParser = None
    PARSER_AVAILABLE = False

# Protocol constants
STX = 0x02
ETX = 0x03

class SerialSource:
    """Reads raw serial data from GC instrument COM port.

    Supports framing protocols:
    - line: Newline-delimited (CR, LF, CRLF)
    - stx_etx: STX (0x02) ... ETX (0x03) framing
    - custom: User-defined start/end markers

    Args:
        config: SerialSourceConfig with port, baud, framing params, etc.
        on_new_frame: Callback receiving parsed result dict from GCParser.
    """

    def __init__(
        self,
        config: SerialSourceConfig,
        on_new_frame: Callable[[dict], None],
        analysis_config: Optional['AnalysisSourceConfig'] = None,
        on_raw_sample: Optional[Callable[[float, float], None]] = None,
        on_inject_marker: Optional[Callable[[], None]] = None,
    ):
        self._config = config
        self._on_new_frame = on_new_frame

        # Streaming mode callbacks (for direct GC analysis)
        self._analysis_config = analysis_config
        self._on_raw_sample = on_raw_sample
        self._on_inject_marker = on_inject_marker
        self._streaming_mode = (
            analysis_config is not None
            and analysis_config.enabled
            and analysis_config.mode == 'streaming'
        )
        self._stream_start_time: float = 0.0

        self._serial: Optional[Any] = None
        self._connected = False
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._read_thread: Optional[threading.Thread] = None

        # Incoming byte buffer for frame extraction
        self._buffer = bytearray()
        self._buffer_lock = threading.Lock()

        # Reconnection state
        self._reconnect_attempts = 0
        self._max_reconnect_delay = 30.0

        # Error tracking
        self._last_error: str = ""
        self._error_count: int = 0
        self._frames_received: int = 0
        self._raw_samples_sent: int = 0

        # Parser instance
        self._parser: Optional[object] = None
        if PARSER_AVAILABLE:
            self._parser = GCParser(
                template=config.parse_template,
                delimiter=config.delimiter,
                column_mapping=config.column_mapping,
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the serial read loop."""
        if not SERIAL_AVAILABLE:
            logger.error(
                "SerialSource: pyserial not installed. "
                "Install with: pip install pyserial"
            )
            return

        self._stop_event.clear()

        if not self._connect():
            logger.warning(
                "SerialSource: Initial connection failed, "
                "will retry in read loop"
            )

        self._read_thread = threading.Thread(
            target=self._read_loop,
            name="SerialSource-Read",
            daemon=True,
        )
        self._read_thread.start()
        logger.info(
            f"SerialSource: Started reading {self._config.port} "
            f"({self._config.baudrate} baud, "
            f"protocol={self._config.protocol})"
        )

    def stop(self) -> None:
        """Stop the serial read loop and close the port."""
        self._stop_event.set()

        if self._read_thread is not None:
            self._read_thread.join(timeout=10.0)
            if self._read_thread.is_alive():
                logger.warning("SerialSource: Read thread did not exit in time")
            self._read_thread = None

        self._disconnect()
        logger.info("SerialSource: Stopped")

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _connect(self) -> bool:
        """Open the serial port with configured parameters."""
        with self._lock:
            try:
                parity_map = {
                    'N': serial.PARITY_NONE,
                    'E': serial.PARITY_EVEN,
                    'O': serial.PARITY_ODD,
                    'NONE': serial.PARITY_NONE,
                    'EVEN': serial.PARITY_EVEN,
                    'ODD': serial.PARITY_ODD,
                }
                parity = parity_map.get(
                    self._config.parity.upper(), serial.PARITY_NONE,
                )

                self._serial = serial.Serial(
                    port=self._config.port,
                    baudrate=self._config.baudrate,
                    parity=parity,
                    stopbits=self._config.stopbits,
                    bytesize=self._config.bytesize,
                    timeout=self._config.timeout,
                )
                self._connected = True
                self._reconnect_attempts = 0
                self._error_count = 0
                logger.info(f"SerialSource: Connected to {self._config.port}")
                return True
            except serial.SerialException as e:
                self._connected = False
                self._last_error = f"Cannot open {self._config.port}: {e}"
                logger.error(f"SerialSource: {self._last_error}")
                return False
            except Exception as e:
                self._connected = False
                self._last_error = str(e)
                logger.error(f"SerialSource: Connection error: {e}")
                return False

    def _disconnect(self) -> None:
        """Close the serial port."""
        with self._lock:
            if self._serial is not None:
                try:
                    self._serial.close()
                except Exception:
                    pass
                self._serial = None
            self._connected = False

    def _reconnect(self) -> bool:
        """Disconnect and reconnect with exponential backoff."""
        self._disconnect()

        delay = min(
            self._config.timeout * (2 ** self._reconnect_attempts),
            self._max_reconnect_delay,
        )
        logger.info(
            f"SerialSource: Reconnecting to {self._config.port} "
            f"in {delay:.1f}s (attempt {self._reconnect_attempts + 1})"
        )

        # Wait with stop_event check so we can exit promptly
        if self._stop_event.wait(timeout=delay):
            return False

        self._reconnect_attempts += 1
        return self._connect()

    # ------------------------------------------------------------------
    # Read loop
    # ------------------------------------------------------------------

    def _read_loop(self) -> None:
        """Main read loop: read bytes, extract frames, parse, dispatch."""
        while not self._stop_event.is_set():
            # Reconnect if needed
            if not self._connected:
                if not self._reconnect():
                    continue

            try:
                data = self._read_bytes()
                if data:
                    with self._buffer_lock:
                        self._buffer.extend(data)
                    self._extract_frames()
            except serial.SerialException as e:
                self._error_count += 1
                self._last_error = f"Serial read error: {e}"
                logger.error(f"SerialSource: {self._last_error}")
                self._connected = False
            except Exception as e:
                self._error_count += 1
                self._last_error = f"Read loop error: {e}"
                logger.error(f"SerialSource: {self._last_error}")
                # Brief pause to avoid tight error loop
                self._stop_event.wait(timeout=1.0)

    def _read_bytes(self) -> Optional[bytes]:
        """Read available bytes from the serial port.

        Returns bytes read, or None if no data available.
        Uses the configured timeout so we don't block forever.
        """
        with self._lock:
            if self._serial is None or not self._connected:
                return None

            try:
                # Read whatever is available (up to 4096 bytes)
                waiting = self._serial.in_waiting
                if waiting > 0:
                    return self._serial.read(min(waiting, 4096))
                else:
                    # Blocking read with timeout to avoid busy-waiting
                    data = self._serial.read(1)
                    if data:
                        # Read any additional bytes that arrived
                        extra = self._serial.in_waiting
                        if extra > 0:
                            data += self._serial.read(min(extra, 4095))
                    return data if data else None
            except serial.SerialException:
                raise
            except Exception as e:
                logger.debug(f"SerialSource: Read error: {e}")
                return None

    # ------------------------------------------------------------------
    # Frame extraction
    # ------------------------------------------------------------------

    def _extract_frames(self) -> None:
        """Extract complete frames from the byte buffer based on protocol."""
        protocol = self._config.protocol.lower()

        if protocol == 'line':
            self._extract_line_frames()
        elif protocol == 'stx_etx':
            self._extract_stx_etx_frames()
        elif protocol == 'custom':
            self._extract_custom_frames()
        else:
            logger.warning(
                f"SerialSource: Unknown protocol '{protocol}', "
                f"falling back to line mode"
            )
            self._extract_line_frames()

    def _extract_line_frames(self) -> None:
        """Extract newline-delimited frames (CR, LF, or CRLF)."""
        with self._buffer_lock:
            while True:
                # Search for any line terminator
                cr_pos = self._buffer.find(b'\r')
                lf_pos = self._buffer.find(b'\n')

                if cr_pos == -1 and lf_pos == -1:
                    break  # No complete line yet

                if cr_pos >= 0 and lf_pos >= 0:
                    if cr_pos < lf_pos:
                        if lf_pos == cr_pos + 1:
                            # CRLF
                            frame_data = bytes(self._buffer[:cr_pos])
                            self._buffer = self._buffer[lf_pos + 1:]
                        else:
                            # Bare CR (followed later by LF from different line)
                            frame_data = bytes(self._buffer[:cr_pos])
                            self._buffer = self._buffer[cr_pos + 1:]
                    else:
                        # LF comes before CR
                        frame_data = bytes(self._buffer[:lf_pos])
                        self._buffer = self._buffer[lf_pos + 1:]
                elif cr_pos >= 0:
                    frame_data = bytes(self._buffer[:cr_pos])
                    self._buffer = self._buffer[cr_pos + 1:]
                else:
                    frame_data = bytes(self._buffer[:lf_pos])
                    self._buffer = self._buffer[lf_pos + 1:]

                if frame_data:
                    self._dispatch_frame(frame_data)

    def _extract_stx_etx_frames(self) -> None:
        """Extract STX (0x02) ... ETX (0x03) framed data."""
        with self._buffer_lock:
            while True:
                stx_pos = self._buffer.find(bytes([STX]))
                if stx_pos == -1:
                    # No STX found; discard everything (noise before STX)
                    self._buffer.clear()
                    break

                # Discard anything before STX
                if stx_pos > 0:
                    self._buffer = self._buffer[stx_pos:]

                etx_pos = self._buffer.find(bytes([ETX]), 1)
                if etx_pos == -1:
                    break  # No complete frame yet

                # Extract frame between STX and ETX (exclusive)
                frame_data = bytes(self._buffer[1:etx_pos])
                self._buffer = self._buffer[etx_pos + 1:]

                if frame_data:
                    self._dispatch_frame(frame_data)

    def _extract_custom_frames(self) -> None:
        """Extract frames using user-defined end delimiter."""
        delimiter = self._config.frame_end.encode('utf-8', errors='replace')
        if not delimiter:
            return

        with self._buffer_lock:
            while True:
                pos = self._buffer.find(delimiter)
                if pos == -1:
                    break  # No complete frame yet

                frame_data = bytes(self._buffer[:pos])
                self._buffer = self._buffer[pos + len(delimiter):]

                if frame_data:
                    self._dispatch_frame(frame_data)

    # ------------------------------------------------------------------
    # Frame dispatch
    # ------------------------------------------------------------------

    def _dispatch_frame(self, frame_data: bytes) -> None:
        """Decode a frame, parse via GCParser, and send to callback.

        In streaming mode, attempts to extract a raw voltage value from each
        line and calls on_raw_sample(time_s, voltage). Also checks for inject
        marker strings and calls on_inject_marker().

        Args:
            frame_data: Raw bytes of the extracted frame (without delimiters).
        """
        self._frames_received += 1

        # Decode bytes to string
        try:
            text = frame_data.decode('utf-8', errors='replace')
        except Exception:
            text = frame_data.decode('latin-1', errors='replace')

        text = text.strip()
        if not text:
            return

        # Check for inject marker (in any mode)
        if self._analysis_config and self._on_inject_marker:
            marker = self._analysis_config.inject_marker
            if marker and text.upper().startswith(marker.upper()):
                logger.info(f"SerialSource: Inject marker detected: '{text}'")
                try:
                    self._on_inject_marker()
                except Exception as e:
                    logger.error(f"SerialSource: Inject marker callback error: {e}")
                return  # Marker line is not a data point

        # Streaming mode: extract raw voltage and send to analysis engine
        if self._streaming_mode and self._on_raw_sample:
            voltage = self._try_extract_voltage(text)
            if voltage is not None:
                now = time.time()
                if self._stream_start_time == 0.0:
                    self._stream_start_time = now
                elapsed = now - self._stream_start_time
                try:
                    self._on_raw_sample(elapsed, voltage)
                    self._raw_samples_sent += 1
                except Exception as e:
                    logger.error(f"SerialSource: Raw sample callback error: {e}")
                return  # Don't also dispatch as a parsed frame

        # Non-streaming: parse through GCParser if available
        result = self._parse_frame(text)
        if result is None:
            # If no parser, pass raw text in a simple dict
            result = {'raw_frame': text}

        # Add metadata
        result['_source'] = 'serial'
        result['_port'] = self._config.port
        result['_frame_number'] = self._frames_received
        result['_timestamp'] = time.time()

        # Dispatch to callback
        try:
            self._on_new_frame(result)
            logger.debug(
                f"SerialSource: Dispatched frame #{self._frames_received} "
                f"({len(frame_data)} bytes)"
            )
        except Exception as e:
            logger.error(f"SerialSource: Callback error: {e}")

    def _try_extract_voltage(self, text: str) -> Optional[float]:
        """Try to extract a numeric voltage value from a serial line.

        Supports formats:
        - Plain number: "0.4523"
        - CSV with timestamp: "1234.5,0.4523"  (last numeric field)
        - Labeled: "V=0.4523" or "voltage:0.4523"
        """
        # Try labeled formats first
        for prefix in ('V=', 'v=', 'voltage:', 'Voltage:', 'VOLTAGE:'):
            if text.startswith(prefix):
                try:
                    return float(text[len(prefix):].strip())
                except ValueError:
                    pass

        # Try plain float
        try:
            return float(text)
        except ValueError:
            pass

        # Try CSV — take last numeric field
        delimiter = self._config.delimiter or ','
        parts = text.split(delimiter)
        for part in reversed(parts):
            try:
                return float(part.strip())
            except ValueError:
                continue

        return None

    def _parse_frame(self, text: str) -> Optional[dict]:
        """Parse a frame string via GCParser.

        Returns parsed result dict or None if parser is unavailable
        or parsing fails.
        """
        if not PARSER_AVAILABLE or self._parser is None:
            return None

        try:
            return self._parser.parse(text, source_path=f"serial:{self._config.port}")
        except Exception as e:
            logger.debug(f"SerialSource: Parse error: {e}")
            return None

    # ------------------------------------------------------------------
    # Status / diagnostics
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        """Whether the read loop is currently active."""
        if self._stop_event.is_set():
            return False
        return self._read_thread is not None and self._read_thread.is_alive()

    @property
    def is_connected(self) -> bool:
        return self._connected

    def reset_stream_timer(self) -> None:
        """Reset the streaming elapsed-time origin (called at run start)."""
        self._stream_start_time = 0.0
        self._raw_samples_sent = 0

    def get_status(self) -> Dict[str, Any]:
        """Return status dict for diagnostics / MQTT status publishing."""
        status = {
            'running': self.is_running,
            'connected': self._connected,
            'port': self._config.port,
            'baudrate': self._config.baudrate,
            'protocol': self._config.protocol,
            'frames_received': self._frames_received,
            'buffer_size': len(self._buffer),
            'error_count': self._error_count,
            'last_error': self._last_error,
            'parser_available': PARSER_AVAILABLE,
            'serial_available': SERIAL_AVAILABLE,
        }
        if self._streaming_mode:
            status['streaming_mode'] = True
            status['raw_samples_sent'] = self._raw_samples_sent
        return status
