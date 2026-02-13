"""
File watching module for GC Node.

Monitors a directory for new/modified GC result files (CSV, TXT, etc.).
Uses watchdog library for filesystem events when available, falls back
to polling when not (Python 3.4 / Windows XP compatibility).

Typical flow:
  1. FileWatcher starts watching the configured directory
  2. New or modified file detected -> read and parse via GCParser
  3. Parsed result dict passed to on_new_file callback
  4. If archive_processed is True, file is moved to processed_dir
"""

import fnmatch
import logging
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Callable, Dict, Optional, Set, Tuple

from .config import FileWatcherConfig

logger = logging.getLogger('GCNode')

# Try to import watchdog for filesystem event monitoring.
# Falls back to polling if unavailable.
try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileModifiedEvent
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    Observer = None
    FileSystemEventHandler = object

# Try to import GCParser. May not exist yet during early development;
# file_watcher can still be imported but _process_file will fail gracefully.
try:
    from .gc_parser import GCParser
    PARSER_AVAILABLE = True
except ImportError:
    GCParser = None
    PARSER_AVAILABLE = False


class _WatchdogHandler(FileSystemEventHandler if WATCHDOG_AVAILABLE else object):
    """Watchdog event handler that forwards file events to the FileWatcher."""

    def __init__(self, file_watcher: 'FileWatcher'):
        if WATCHDOG_AVAILABLE:
            super().__init__()
        self._watcher = file_watcher

    def on_created(self, event):
        if not event.is_directory:
            self._watcher._on_file_event(event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            self._watcher._on_file_event(event.src_path)


class FileWatcher:
    """Watches a directory for new/modified GC result files.

    Uses watchdog library for filesystem events when available,
    falls back to polling when not (Python 3.4/XP compatibility).

    Args:
        config: FileWatcherConfig with watch directory, pattern, etc.
        on_new_file: Callback receiving parsed result dict from GCParser.
    """

    def __init__(self, config: FileWatcherConfig, on_new_file: Callable[[dict], None]):
        self._config = config
        self._on_new_file = on_new_file

        # Set of (filepath, mtime) tuples that have been processed.
        # Prevents re-processing the same file at the same mtime.
        self._processed: Set[Tuple[str, float]] = set()
        self._processed_lock = threading.Lock()

        # Shutdown signal
        self._stop_event = threading.Event()

        # Background threads
        self._observer = None          # watchdog Observer (if available)
        self._poll_thread: Optional[threading.Thread] = None

        # Parser instance
        self._parser: Optional[object] = None
        if PARSER_AVAILABLE:
            self._parser = GCParser(
                template=config.parse_template,
                delimiter=config.delimiter,
                header_rows=config.header_rows,
                encoding=config.encoding,
                column_mapping=config.column_mapping,
                timestamp_column=config.timestamp_column,
                timestamp_format=config.timestamp_format,
            )

        # Ensure watch directory exists
        self._watch_dir = Path(config.watch_directory) if config.watch_directory else None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start watching the configured directory for new GC result files."""
        if not self._watch_dir:
            logger.warning("FileWatcher: watch_directory not configured, cannot start")
            return

        if not self._watch_dir.exists():
            try:
                self._watch_dir.mkdir(parents=True, exist_ok=True)
                logger.info(f"FileWatcher: Created watch directory: {self._watch_dir}")
            except OSError as e:
                logger.error(f"FileWatcher: Cannot create watch directory {self._watch_dir}: {e}")
                return

        # Ensure processed directory exists if archiving is enabled
        if self._config.archive_processed and self._config.processed_dir:
            processed_path = Path(self._config.processed_dir)
            try:
                processed_path.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                logger.error(f"FileWatcher: Cannot create processed directory {processed_path}: {e}")

        self._stop_event.clear()

        # Process any existing files that haven't been handled yet
        self._process_existing_files()

        # Start watching: prefer watchdog, fall back to polling
        if WATCHDOG_AVAILABLE:
            self._start_watchdog()
        else:
            logger.info("FileWatcher: watchdog not available, using polling fallback")
            self._start_polling()

        logger.info(
            f"FileWatcher: Started watching {self._watch_dir} "
            f"for '{self._config.file_pattern}' "
            f"(mode={'watchdog' if WATCHDOG_AVAILABLE else 'polling'})"
        )

    def stop(self) -> None:
        """Stop watching and shut down background threads."""
        self._stop_event.set()

        # Stop watchdog observer
        if self._observer is not None:
            try:
                self._observer.stop()
                self._observer.join(timeout=5.0)
            except Exception as e:
                logger.warning(f"FileWatcher: Error stopping watchdog observer: {e}")
            self._observer = None

        # Stop polling thread
        if self._poll_thread is not None:
            self._poll_thread.join(timeout=10.0)
            if self._poll_thread.is_alive():
                logger.warning("FileWatcher: Polling thread did not exit in time")
            self._poll_thread = None

        logger.info("FileWatcher: Stopped")

    # ------------------------------------------------------------------
    # Watchdog mode
    # ------------------------------------------------------------------

    def _start_watchdog(self) -> None:
        """Start watchdog Observer for real-time filesystem event monitoring."""
        handler = _WatchdogHandler(self)
        self._observer = Observer()
        self._observer.schedule(handler, str(self._watch_dir), recursive=False)
        self._observer.daemon = True
        self._observer.start()

    def _on_file_event(self, filepath: str) -> None:
        """Handle a watchdog filesystem event (created or modified)."""
        if self._stop_event.is_set():
            return

        # Check file matches the configured pattern
        filename = os.path.basename(filepath)
        if not fnmatch.fnmatch(filename, self._config.file_pattern):
            return

        # Small delay to let the writing process finish flushing
        # (GC vendor software may still be writing)
        time.sleep(0.5)

        self._process_file(filepath)

    # ------------------------------------------------------------------
    # Polling fallback mode
    # ------------------------------------------------------------------

    def _start_polling(self) -> None:
        """Start a polling thread that checks the directory at regular intervals."""
        self._poll_thread = threading.Thread(
            target=self._poll_loop,
            name="FileWatcher-Poll",
            daemon=True,
        )
        self._poll_thread.start()

    def _poll_loop(self) -> None:
        """Poll the watch directory for new/modified files."""
        while not self._stop_event.is_set():
            try:
                self._scan_directory()
            except Exception as e:
                logger.error(f"FileWatcher: Error during directory scan: {e}")

            # Wait for the configured interval, checking stop_event periodically
            # so we can exit promptly on shutdown
            self._stop_event.wait(timeout=self._config.poll_interval_s)

    def _scan_directory(self) -> None:
        """Scan the watch directory and process any new/modified files."""
        if not self._watch_dir or not self._watch_dir.exists():
            return

        try:
            entries = os.listdir(str(self._watch_dir))
        except OSError as e:
            logger.error(f"FileWatcher: Cannot list directory {self._watch_dir}: {e}")
            return

        for entry in sorted(entries):
            if self._stop_event.is_set():
                break

            # Match file pattern
            if not fnmatch.fnmatch(entry, self._config.file_pattern):
                continue

            filepath = os.path.join(str(self._watch_dir), entry)

            # Skip directories
            if os.path.isdir(filepath):
                continue

            # Check mtime to see if we already processed this version
            try:
                mtime = os.stat(filepath).st_mtime
            except OSError:
                continue

            key = (filepath, mtime)
            with self._processed_lock:
                if key in self._processed:
                    continue

            self._process_file(filepath)

    # ------------------------------------------------------------------
    # File processing
    # ------------------------------------------------------------------

    def _process_existing_files(self) -> None:
        """Process any files that already exist in the watch directory on startup."""
        if not self._watch_dir or not self._watch_dir.exists():
            return

        try:
            entries = os.listdir(str(self._watch_dir))
        except OSError as e:
            logger.error(f"FileWatcher: Cannot list directory on startup: {e}")
            return

        count = 0
        for entry in sorted(entries):
            if not fnmatch.fnmatch(entry, self._config.file_pattern):
                continue

            filepath = os.path.join(str(self._watch_dir), entry)
            if os.path.isdir(filepath):
                continue

            self._process_file(filepath)
            count += 1

        if count > 0:
            logger.info(f"FileWatcher: Processed {count} existing file(s) on startup")

    def _process_file(self, filepath: str) -> None:
        """Read, parse, and dispatch a single GC result file.

        Steps:
          1. Read the file contents with the configured encoding
          2. Parse via GCParser to extract result dict
          3. Pass result to on_new_file callback
          4. Mark as processed (path + mtime)
          5. Archive to processed_dir if configured
        """
        filename = os.path.basename(filepath)

        # Get current mtime for dedup tracking
        try:
            mtime = os.stat(filepath).st_mtime
        except OSError as e:
            logger.warning(f"FileWatcher: Cannot stat {filename}: {e}")
            return

        key = (filepath, mtime)
        with self._processed_lock:
            if key in self._processed:
                return

        # Read file contents with encoding fallback
        content = self._read_file(filepath)
        if content is None:
            return

        # Parse through GCParser
        result = self._parse_content(filepath, content)
        if result is None:
            logger.warning(f"FileWatcher: Failed to parse {filename}, skipping")
            # Still mark as processed to avoid retrying a bad file forever
            with self._processed_lock:
                self._processed.add(key)
            return

        # Add metadata to result
        result['_source'] = 'file'
        result['_filename'] = filename
        result['_filepath'] = filepath
        result['_file_mtime'] = mtime
        result['_processed_at'] = time.time()

        # Dispatch to callback
        try:
            self._on_new_file(result)
            logger.debug(f"FileWatcher: Dispatched result from {filename}")
        except Exception as e:
            logger.error(f"FileWatcher: Callback error for {filename}: {e}")

        # Mark as processed
        with self._processed_lock:
            self._processed.add(key)

        # Archive the file if configured
        if self._config.archive_processed and self._config.processed_dir:
            self._archive_file(filepath)

    def _read_file(self, filepath: str) -> Optional[str]:
        """Read file contents, trying configured encoding then fallbacks.

        Tries: configured encoding -> utf-8 -> latin-1 -> cp1252
        """
        filename = os.path.basename(filepath)
        encodings = [self._config.encoding]

        # Add fallback encodings that aren't already in the list
        for fallback in ('utf-8', 'latin-1', 'cp1252'):
            if fallback not in encodings:
                encodings.append(fallback)

        for encoding in encodings:
            try:
                with open(filepath, 'r', encoding=encoding) as f:
                    content = f.read()
                if encoding != self._config.encoding:
                    logger.debug(
                        f"FileWatcher: {filename} read with fallback encoding '{encoding}' "
                        f"(configured: '{self._config.encoding}')"
                    )
                return content
            except UnicodeDecodeError:
                continue
            except OSError as e:
                logger.error(f"FileWatcher: Cannot read {filename}: {e}")
                return None

        logger.error(
            f"FileWatcher: Cannot decode {filename} with any encoding "
            f"({', '.join(encodings)})"
        )
        return None

    def _parse_content(self, filepath: str, content: str) -> Optional[dict]:
        """Parse file content via GCParser.

        Returns parsed result dict or None on failure.
        """
        if not PARSER_AVAILABLE or self._parser is None:
            logger.error(
                "FileWatcher: GCParser not available. "
                "Ensure gc_parser.py exists in the gc_node package."
            )
            return None

        try:
            return self._parser.parse(content, source_path=filepath)
        except Exception as e:
            logger.error(f"FileWatcher: Parse error for {os.path.basename(filepath)}: {e}")
            return None

    def _archive_file(self, filepath: str) -> None:
        """Move a processed file to the archive directory.

        If a file with the same name already exists in the archive,
        append a timestamp suffix to avoid overwriting.
        """
        if not self._config.processed_dir:
            return

        processed_dir = Path(self._config.processed_dir)
        filename = os.path.basename(filepath)
        dest = processed_dir / filename

        # Avoid overwriting existing archived files
        if dest.exists():
            stem = Path(filename).stem
            suffix = Path(filename).suffix
            timestamp = time.strftime('%Y%m%d_%H%M%S')
            dest = processed_dir / f"{stem}_{timestamp}{suffix}"

        try:
            shutil.move(filepath, str(dest))
            logger.debug(f"FileWatcher: Archived {filename} -> {dest}")

            # Remove from processed set since the original path no longer exists
            with self._processed_lock:
                keys_to_remove = [k for k in self._processed if k[0] == filepath]
                for k in keys_to_remove:
                    self._processed.discard(k)

        except OSError as e:
            logger.error(f"FileWatcher: Cannot archive {filename}: {e}")

    # ------------------------------------------------------------------
    # Housekeeping
    # ------------------------------------------------------------------

    def clear_processed(self) -> None:
        """Clear the set of processed files, allowing re-processing."""
        with self._processed_lock:
            count = len(self._processed)
            self._processed.clear()
        logger.info(f"FileWatcher: Cleared {count} processed file entries")

    @property
    def processed_count(self) -> int:
        """Number of files that have been processed."""
        with self._processed_lock:
            return len(self._processed)

    @property
    def is_running(self) -> bool:
        """Whether the watcher is currently active."""
        if self._stop_event.is_set():
            return False
        if self._observer is not None:
            return self._observer.is_alive()
        if self._poll_thread is not None:
            return self._poll_thread.is_alive()
        return False

    def get_status(self) -> Dict:
        """Return status dict for diagnostics / MQTT status publishing."""
        return {
            'running': self.is_running,
            'mode': 'watchdog' if (self._observer is not None) else 'polling',
            'watch_directory': str(self._watch_dir) if self._watch_dir else '',
            'file_pattern': self._config.file_pattern,
            'processed_count': self.processed_count,
            'parser_available': PARSER_AVAILABLE,
            'watchdog_available': WATCHDOG_AVAILABLE,
        }
