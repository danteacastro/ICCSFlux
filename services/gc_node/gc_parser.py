"""
GC Result Parser — Pluggable Templates for Gas Chromatograph Output

Parses result files from various gas chromatograph instruments into a
normalized dictionary format suitable for MQTT publication.

Uses only stdlib (csv module) — no pandas or third-party dependencies.

Supported templates:
- GenericCSVTemplate   : Standard CSV with configurable headers and column mapping
- AgilentCSVTemplate   : Agilent ChemStation / OpenLab CSV export
- ABBNGCTemplate       : ABB NGC/PGC (Natural Gas Chromatograph) result format

Usage:
    from gc_parser import GCParser

    result = GCParser.parse(file_content, template='generic', config={
        'delimiter': ',',
        'header_rows': 0,
        'column_mapping': {'CH4 Conc': 'Methane'},
        'timestamp_column': 'DateTime',
        'timestamp_format': '%Y-%m-%d %H:%M:%S',
    })

Result format:
    {
        'timestamp': '2026-02-12T14:30:00',
        'components': {
            'Methane': {'value': 94.52, 'unit': 'mol%'},
            'Ethane':  {'value': 2.31, 'unit': 'mol%'},
        },
        'metadata': {...},
        'raw_rows': 12,
    }
"""

import csv
import io
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Type

logger = logging.getLogger('GCNode.Parser')

class ParseError(Exception):
    """Raised when a GC result file cannot be parsed."""
    pass

# ---------------------------------------------------------------------------
# Base template
# ---------------------------------------------------------------------------

class BaseTemplate:
    """
    Abstract base for GC result parsing templates.

    Subclasses must implement parse(content, config) -> dict.
    """

    # Human-readable name for logging and UI
    name: str = 'base'

    @staticmethod
    def parse(content: str, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Parse file content into a normalized result dictionary.

        Args:
            content: Full file content as a string.
            config:  Template-specific configuration dict. Common keys:
                     - delimiter (str): Column separator, default ','
                     - header_rows (int): Number of non-data rows to skip
                       before the column-name row, default 0
                     - column_mapping (dict): {CSVColumnName: ChannelTagName}
                     - timestamp_column (str): Column name containing timestamp
                     - timestamp_format (str): strptime format string

        Returns:
            Normalized result dict with keys:
            - timestamp (str): ISO-format timestamp or empty string
            - components (dict): {name: {'value': float, 'unit': str}}
            - metadata (dict): Extra information extracted from the file
            - raw_rows (int): Number of data rows parsed
        """
        raise NotImplementedError

    @staticmethod
    def _safe_float(value: str) -> Optional[float]:
        """
        Convert a string to float, returning None on failure.

        Handles common GC output quirks:
        - Whitespace and trailing units (e.g. '94.52 %')
        - Comma as decimal separator (e.g. '94,52')
        - Angle brackets for below-detection (e.g. '<0.01')
        - 'N/A', 'n/a', '-', '--', '' as missing
        """
        if value is None:
            return None

        s = value.strip()

        if not s or s in ('N/A', 'n/a', 'NA', '-', '--', '---', 'NaN', 'nan'):
            return None

        # Handle below-detection-limit markers like '<0.01'
        if s.startswith('<'):
            s = s[1:].strip()

        # Strip trailing non-numeric characters (units like '%', 'ppm', 'mol%')
        # but keep decimal point, minus sign, and digits
        s = re.sub(r'[^\d.eE+\-,]', '', s)

        if not s:
            return None

        # Handle comma as decimal separator (European notation)
        # Only replace if there is exactly one comma and no period
        if ',' in s and '.' not in s and s.count(',') == 1:
            s = s.replace(',', '.')

        try:
            return float(s)
        except (ValueError, OverflowError):
            return None

    @staticmethod
    def _extract_unit(value: str) -> str:
        """
        Try to extract a unit suffix from a value string.

        Examples:
            '94.52 mol%' -> 'mol%'
            '2.31%'      -> '%'
            '150 ppm'    -> 'ppm'
            '23.4'       -> ''
        """
        if value is None:
            return ''

        s = value.strip()

        # Match trailing unit after a number
        m = re.search(r'[\d.]+\s*([a-zA-Z%/]+)$', s)
        if m:
            return m.group(1)

        return ''

    @staticmethod
    def _make_result(timestamp: str = '',
                     components: Optional[Dict[str, Dict[str, Any]]] = None,
                     metadata: Optional[Dict[str, Any]] = None,
                     raw_rows: int = 0) -> Dict[str, Any]:
        """Build a normalized result dictionary."""
        return {
            'timestamp': timestamp,
            'components': components or {},
            'metadata': metadata or {},
            'raw_rows': raw_rows,
        }

# ---------------------------------------------------------------------------
# GenericCSVTemplate
# ---------------------------------------------------------------------------

class GenericCSVTemplate(BaseTemplate):
    """
    Generic CSV parser for standard GC result files with column headers.

    File layout:
        [header_rows lines to skip]
        ColumnName1, ColumnName2, ...    <-- column header row
        value1, value2, ...              <-- data rows
        ...

    Config keys:
        delimiter (str): Column separator, default ','
        header_rows (int): Lines to skip before the column-name row, default 0
        column_mapping (dict): {CSVColumnName: ChannelTagName}, default {} (use CSV names)
        timestamp_column (str): Column name for timestamp, default ''
        timestamp_format (str): strptime format, default '%Y-%m-%d %H:%M:%S'
        unit_column (str): Column containing units, default '' (no unit column)
        default_unit (str): Unit to use when not specified, default ''
        component_columns (list): Specific columns to treat as components.
            If empty, all non-timestamp numeric columns are treated as components.
    """

    name = 'generic'

    @staticmethod
    def parse(content: str, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Parse generic CSV content."""
        cfg = config or {}
        delimiter = cfg.get('delimiter', ',')
        header_rows = cfg.get('header_rows', 0)
        column_mapping = cfg.get('column_mapping', {})
        timestamp_column = cfg.get('timestamp_column', '')
        timestamp_format = cfg.get('timestamp_format', '%Y-%m-%d %H:%M:%S')
        unit_column = cfg.get('unit_column', '')
        default_unit = cfg.get('default_unit', '')
        component_columns = cfg.get('component_columns', [])

        lines = content.splitlines()

        if not lines:
            raise ParseError("Empty file content")

        # Skip header_rows
        if header_rows >= len(lines):
            raise ParseError(
                f"header_rows ({header_rows}) exceeds total lines ({len(lines)})"
            )

        metadata = {}

        # Capture skipped header lines as metadata
        for i in range(header_rows):
            line = lines[i].strip()
            if line:
                # Try to parse as key: value or key=value
                for sep in (':', '='):
                    if sep in line:
                        key, _, val = line.partition(sep)
                        metadata[key.strip()] = val.strip()
                        break
                else:
                    metadata[f'header_line_{i + 1}'] = line

        data_lines = lines[header_rows:]

        if not data_lines:
            raise ParseError("No data lines after skipping headers")

        # Parse with csv.reader
        reader = csv.reader(data_lines, delimiter=delimiter)
        rows = list(reader)

        if len(rows) < 2:
            # Need at least a column header row and one data row
            if len(rows) == 1:
                raise ParseError("Only column header row found, no data rows")
            raise ParseError("No rows found after header skip")

        # First row is column names
        col_names = [c.strip() for c in rows[0]]
        data_rows = rows[1:]

        # Build column index
        col_index = {name: idx for idx, name in enumerate(col_names) if name}

        # Extract timestamp from first data row if configured
        timestamp = ''
        if timestamp_column and timestamp_column in col_index:
            ts_idx = col_index[timestamp_column]
            for row in data_rows:
                if ts_idx < len(row) and row[ts_idx].strip():
                    raw_ts = row[ts_idx].strip()
                    try:
                        dt = datetime.strptime(raw_ts, timestamp_format)
                        timestamp = dt.isoformat()
                    except ValueError:
                        # Try ISO format as fallback
                        try:
                            dt = datetime.fromisoformat(raw_ts)
                            timestamp = dt.isoformat()
                        except ValueError:
                            timestamp = raw_ts
                    break

        # Determine which columns are components
        if component_columns:
            target_cols = [c for c in component_columns if c in col_index]
        else:
            # All columns except timestamp and unit columns
            exclude = set()
            if timestamp_column:
                exclude.add(timestamp_column)
            if unit_column:
                exclude.add(unit_column)
            target_cols = [c for c in col_names if c and c not in exclude]

        # Parse components — aggregate across all data rows
        # For single-row results (typical), we get one value per component.
        # For multi-row results (e.g., peak table), each row is a component.
        components: Dict[str, Dict[str, Any]] = {}

        # Check if this looks like a vertical table (component name in one column,
        # value in another) vs. a horizontal table (each column is a component)
        is_vertical = len(data_rows) > 1 and len(target_cols) <= 3

        if is_vertical and len(target_cols) >= 2:
            # Vertical layout: first target column is component name,
            # second is value, optional third is unit
            name_col = target_cols[0]
            value_col = target_cols[1]
            unit_col_name = target_cols[2] if len(target_cols) >= 3 else unit_column

            name_idx = col_index[name_col]
            value_idx = col_index[value_col]
            unit_idx = col_index.get(unit_col_name, -1) if unit_col_name else -1

            for row in data_rows:
                if name_idx >= len(row) or value_idx >= len(row):
                    continue

                comp_name = row[name_idx].strip()
                if not comp_name:
                    continue

                raw_value = row[value_idx].strip()
                parsed_value = BaseTemplate._safe_float(raw_value)

                if parsed_value is None:
                    continue

                # Determine unit
                unit = default_unit
                if 0 <= unit_idx < len(row):
                    row_unit = row[unit_idx].strip()
                    if row_unit:
                        unit = row_unit
                elif raw_value:
                    extracted = BaseTemplate._extract_unit(raw_value)
                    if extracted:
                        unit = extracted

                # Apply column mapping
                tag_name = column_mapping.get(comp_name, comp_name)

                components[tag_name] = {
                    'value': parsed_value,
                    'unit': unit,
                }
        else:
            # Horizontal layout: each column is a component, use first data row
            if data_rows:
                row = data_rows[0]

                # Get unit row if unit_column points to a row pattern
                unit_row = None
                if len(data_rows) > 1:
                    # Check if second row looks like units (all non-numeric)
                    second_row = data_rows[1]
                    numeric_count = sum(
                        1 for cell in second_row
                        if BaseTemplate._safe_float(cell) is not None
                    )
                    if numeric_count == 0 and any(c.strip() for c in second_row):
                        unit_row = second_row

                for col_name in target_cols:
                    if col_name not in col_index:
                        continue

                    idx = col_index[col_name]
                    if idx >= len(row):
                        continue

                    raw_value = row[idx].strip()
                    parsed_value = BaseTemplate._safe_float(raw_value)

                    if parsed_value is None:
                        continue

                    # Determine unit
                    unit = default_unit
                    if unit_row and idx < len(unit_row):
                        row_unit = unit_row[idx].strip()
                        if row_unit:
                            unit = row_unit
                    elif raw_value:
                        extracted = BaseTemplate._extract_unit(raw_value)
                        if extracted:
                            unit = extracted

                    # Apply column mapping
                    tag_name = column_mapping.get(col_name, col_name)

                    components[tag_name] = {
                        'value': parsed_value,
                        'unit': unit,
                    }

        return BaseTemplate._make_result(
            timestamp=timestamp,
            components=components,
            metadata=metadata,
            raw_rows=len(data_rows),
        )

# ---------------------------------------------------------------------------
# AgilentCSVTemplate
# ---------------------------------------------------------------------------

class AgilentCSVTemplate(BaseTemplate):
    """
    Parser for Agilent ChemStation / OpenLab CSV exports.

    Agilent CSV files typically have:
    - Metadata header lines (Sample Name, Injection Date, Method, etc.)
    - A blank line or separator
    - A data table starting with a header row containing
      'Peak#' or 'Compound Name' or 'Component Name'

    This template extracts metadata from the header, then delegates
    data table parsing to GenericCSVTemplate logic.

    Config keys (all optional):
        delimiter (str): Default ','
        column_mapping (dict): {CSVColumnName: ChannelTagName}
        timestamp_format (str): For injection date parsing
        name_column (str): Column with component names, default auto-detect
        value_column (str): Column with concentrations, default auto-detect
        unit_column (str): Column with units, default auto-detect
        default_unit (str): Fallback unit, default ''
    """

    name = 'agilent'

    # Agilent metadata keys to look for (case-insensitive)
    _METADATA_KEYS = {
        'sample name', 'sample id', 'injection date', 'injection time',
        'method', 'method name', 'instrument', 'instrument name',
        'sequence', 'sequence name', 'operator', 'vial', 'vial number',
        'injection volume', 'dilution factor', 'data file',
        'acq. method', 'analysis method', 'last changed',
    }

    # Markers that indicate the start of the data table header row
    _DATA_TABLE_MARKERS = [
        'peak#', 'peak #', 'peak no',
        'compound name', 'component name', 'component',
        'name', 'ret.time', 'retention time',
    ]

    @staticmethod
    def parse(content: str, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Parse Agilent ChemStation CSV content."""
        cfg = config or {}
        delimiter = cfg.get('delimiter', ',')
        column_mapping = cfg.get('column_mapping', {})
        timestamp_format = cfg.get('timestamp_format', '')
        name_column = cfg.get('name_column', '')
        value_column = cfg.get('value_column', '')
        unit_column = cfg.get('unit_column', '')
        default_unit = cfg.get('default_unit', '')

        lines = content.splitlines()

        if not lines:
            raise ParseError("Empty file content")

        metadata = {}
        data_table_start = -1

        # Phase 1: Scan for metadata and find data table start
        for i, line in enumerate(lines):
            stripped = line.strip()

            if not stripped:
                continue

            # Check if this line starts the data table
            lower = stripped.lower()
            cells = [c.strip().lower() for c in stripped.split(delimiter)]

            is_data_header = False
            for marker in AgilentCSVTemplate._DATA_TABLE_MARKERS:
                if any(marker in cell for cell in cells):
                    is_data_header = True
                    break

            if is_data_header:
                data_table_start = i
                break

            # Try to extract metadata (key: value or key = value or key,value)
            for sep in (':', '=', ','):
                if sep in stripped:
                    key, _, val = stripped.partition(sep)
                    key_clean = key.strip()
                    val_clean = val.strip().strip('"').strip("'")

                    if key_clean.lower() in AgilentCSVTemplate._METADATA_KEYS:
                        metadata[key_clean] = val_clean
                        break
            else:
                # Line doesn't match any metadata pattern — might be a comment
                if stripped.startswith('#') or stripped.startswith('//'):
                    metadata.setdefault('comments', [])
                    metadata['comments'].append(stripped.lstrip('#/ '))

        # Extract timestamp from Injection Date if available
        timestamp = ''
        injection_date_keys = ['Injection Date', 'injection date',
                               'Injection Time', 'injection time']
        for key in injection_date_keys:
            if key in metadata:
                raw_ts = metadata[key]
                timestamp = AgilentCSVTemplate._parse_agilent_timestamp(
                    raw_ts, timestamp_format
                )
                if timestamp:
                    break

        # Phase 2: Parse data table
        if data_table_start < 0:
            # No data table found — try parsing entire content as generic CSV
            logger.warning("No Agilent data table marker found, falling back to generic parse")
            data_table_content = content
            header_rows_to_skip = 0
            # Try to find any row with numeric data
            for i, line in enumerate(lines):
                cells = line.strip().split(delimiter)
                numeric_count = sum(
                    1 for c in cells
                    if BaseTemplate._safe_float(c) is not None
                )
                if numeric_count > 0 and i > 0:
                    # Previous line is likely the header
                    data_table_start = i - 1
                    break

            if data_table_start < 0:
                raise ParseError(
                    "Cannot find data table in Agilent CSV "
                    "(no Peak#/Compound Name header found)"
                )

        data_table_lines = lines[data_table_start:]
        data_table_content = '\n'.join(data_table_lines)

        # Parse data table header to auto-detect columns
        reader = csv.reader(data_table_lines, delimiter=delimiter)
        table_rows = list(reader)

        if len(table_rows) < 2:
            raise ParseError("Data table has no data rows after header")

        col_names = [c.strip() for c in table_rows[0]]
        col_index = {name.lower(): idx for idx, name in enumerate(col_names) if name}

        # Auto-detect name, value, and unit columns if not specified
        if not name_column:
            for candidate in ['Compound Name', 'Component Name', 'Component',
                              'Name', 'Peak Name', 'Compound']:
                if candidate.lower() in col_index:
                    name_column = col_names[col_index[candidate.lower()]]
                    break

        if not value_column:
            for candidate in ['Amount', 'Concentration', 'Conc', 'Conc.',
                              'Area%', 'Area %', 'Norm%', 'Norm %',
                              'Result', 'Value', 'Mol%', 'Mol %']:
                if candidate.lower() in col_index:
                    value_column = col_names[col_index[candidate.lower()]]
                    break

        if not unit_column:
            for candidate in ['Unit', 'Units', 'UOM']:
                if candidate.lower() in col_index:
                    unit_column = col_names[col_index[candidate.lower()]]
                    break

        if not name_column or not value_column:
            raise ParseError(
                f"Cannot auto-detect columns in Agilent CSV. "
                f"Found columns: {col_names}. "
                f"Please specify name_column and value_column in config."
            )

        # Parse data rows into components
        components: Dict[str, Dict[str, Any]] = {}
        name_idx = col_index.get(name_column.lower(), -1)
        value_idx = col_index.get(value_column.lower(), -1)
        unit_idx = col_index.get(unit_column.lower(), -1) if unit_column else -1

        data_rows = table_rows[1:]

        for row in data_rows:
            if name_idx < 0 or name_idx >= len(row):
                continue
            if value_idx < 0 or value_idx >= len(row):
                continue

            comp_name = row[name_idx].strip()
            if not comp_name:
                continue

            raw_value = row[value_idx].strip()
            parsed_value = BaseTemplate._safe_float(raw_value)

            if parsed_value is None:
                continue

            # Determine unit
            unit = default_unit
            if 0 <= unit_idx < len(row):
                row_unit = row[unit_idx].strip()
                if row_unit:
                    unit = row_unit
            elif raw_value:
                extracted = BaseTemplate._extract_unit(raw_value)
                if extracted:
                    unit = extracted

            # Apply column mapping
            tag_name = column_mapping.get(comp_name, comp_name)

            components[tag_name] = {
                'value': parsed_value,
                'unit': unit,
            }

        return BaseTemplate._make_result(
            timestamp=timestamp,
            components=components,
            metadata=metadata,
            raw_rows=len(data_rows),
        )

    @staticmethod
    def _parse_agilent_timestamp(raw_ts: str, user_format: str = '') -> str:
        """
        Parse Agilent-style timestamps into ISO format.

        Agilent uses various formats:
        - '12/25/2026 2:30:00 PM'
        - '2026-02-12 14:30:00'
        - '12-Feb-2026 14:30'
        """
        if not raw_ts:
            return ''

        raw_ts = raw_ts.strip()

        # Try user-specified format first
        if user_format:
            try:
                dt = datetime.strptime(raw_ts, user_format)
                return dt.isoformat()
            except ValueError:
                pass

        # Try common Agilent formats
        formats = [
            '%m/%d/%Y %I:%M:%S %p',
            '%m/%d/%Y %H:%M:%S',
            '%d/%m/%Y %H:%M:%S',
            '%Y-%m-%d %H:%M:%S',
            '%d-%b-%Y %H:%M:%S',
            '%d-%b-%Y %H:%M',
            '%m/%d/%Y %I:%M %p',
            '%Y-%m-%dT%H:%M:%S',
        ]

        for fmt in formats:
            try:
                dt = datetime.strptime(raw_ts, fmt)
                return dt.isoformat()
            except ValueError:
                continue

        # Try ISO format as final fallback
        try:
            dt = datetime.fromisoformat(raw_ts)
            return dt.isoformat()
        except ValueError:
            pass

        logger.warning(f"Could not parse Agilent timestamp: {raw_ts!r}")
        return raw_ts

# ---------------------------------------------------------------------------
# ABBNGCTemplate
# ---------------------------------------------------------------------------

class ABBNGCTemplate(BaseTemplate):
    """
    Parser for ABB NGC/PGC (Natural Gas Chromatograph) result files.

    ABB NGC output is typically tab-delimited with a structure like:

        Analysis Date\t2026-02-12 14:30:00
        Stream\t1
        Status\tValid
        <blank line>
        Component\tConcentration\tUnit
        Methane\t94.52\tmol%
        Ethane\t2.31\tmol%
        ...

    Or a simpler flat format:

        Component\tConcentration\tUnit
        Methane\t94.52\tmol%
        ...

    Config keys (all optional):
        delimiter (str): Default '\\t' (tab)
        column_mapping (dict): {ComponentName: ChannelTagName}
        timestamp_format (str): For date parsing
        default_unit (str): Fallback unit, default 'mol%'
        name_column (str): Column with component names, default auto-detect
        value_column (str): Column with concentration values, default auto-detect
        unit_column (str): Column with units, default auto-detect
    """

    name = 'abb_ngc'

    # ABB NGC metadata keys (case-insensitive)
    _METADATA_KEYS = {
        'analysis date', 'analysis time', 'date', 'time',
        'stream', 'stream number', 'stream no',
        'status', 'analysis status', 'result status',
        'method', 'method name', 'calibration',
        'instrument', 'serial number', 'serial no',
        'cycle time', 'analysis cycle',
        'total', 'sum', 'balance',
        'heating value', 'wobbe index', 'specific gravity',
        'compressibility', 'z factor',
    }

    # Column header markers for the component table
    _TABLE_MARKERS = [
        'component', 'comp', 'name',
        'concentration', 'conc', 'result', 'value',
    ]

    @staticmethod
    def parse(content: str, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Parse ABB NGC/PGC result content."""
        cfg = config or {}
        delimiter = cfg.get('delimiter', '\t')
        column_mapping = cfg.get('column_mapping', {})
        timestamp_format = cfg.get('timestamp_format', '%Y-%m-%d %H:%M:%S')
        default_unit = cfg.get('default_unit', 'mol%')
        name_column = cfg.get('name_column', '')
        value_column = cfg.get('value_column', '')
        unit_column = cfg.get('unit_column', '')

        lines = content.splitlines()

        if not lines:
            raise ParseError("Empty file content")

        metadata = {}
        data_table_start = -1
        timestamp = ''

        # Phase 1: Scan for metadata and find data table
        for i, line in enumerate(lines):
            stripped = line.strip()

            if not stripped:
                continue

            cells = [c.strip() for c in stripped.split(delimiter)]
            cells_lower = [c.lower() for c in cells]

            # Check if this line is the data table header
            is_table_header = False
            match_count = 0
            for marker in ABBNGCTemplate._TABLE_MARKERS:
                if any(marker in cell for cell in cells_lower):
                    match_count += 1
            # Need at least 2 marker matches to consider it a table header
            # (e.g., both 'component' and 'concentration')
            if match_count >= 2:
                is_table_header = True

            if is_table_header:
                data_table_start = i
                break

            # Try to extract metadata (key<delim>value pairs)
            if len(cells) >= 2:
                key = cells[0].strip()
                val = delimiter.join(cells[1:]).strip()

                if key.lower() in ABBNGCTemplate._METADATA_KEYS:
                    metadata[key] = val

                    # Extract timestamp from date/time fields
                    if key.lower() in ('analysis date', 'date', 'analysis time'):
                        if not timestamp:
                            timestamp = ABBNGCTemplate._parse_ngc_timestamp(
                                val, timestamp_format
                            )

        # Phase 2: Parse data table
        if data_table_start < 0:
            # No explicit table header — try treating entire file as a table
            # Look for the first line that could be a column header
            for i, line in enumerate(lines):
                stripped = line.strip()
                if not stripped:
                    continue
                cells = [c.strip().lower() for c in stripped.split(delimiter)]
                # Check if any cell contains a component-like name
                for marker in ['component', 'comp', 'name']:
                    if any(marker in cell for cell in cells):
                        data_table_start = i
                        break
                if data_table_start >= 0:
                    break

        if data_table_start < 0:
            raise ParseError(
                "Cannot find component table in ABB NGC output "
                "(no Component/Concentration header found)"
            )

        table_lines = lines[data_table_start:]

        # Parse table using csv.reader with the delimiter
        reader = csv.reader(table_lines, delimiter=delimiter)
        table_rows = list(reader)

        if len(table_rows) < 2:
            raise ParseError("Component table has no data rows after header")

        col_names = [c.strip() for c in table_rows[0]]
        col_index = {name.lower(): idx for idx, name in enumerate(col_names) if name}

        # Auto-detect columns
        if not name_column:
            for candidate in ['Component', 'Comp', 'Name', 'Component Name']:
                if candidate.lower() in col_index:
                    name_column = col_names[col_index[candidate.lower()]]
                    break

        if not value_column:
            for candidate in ['Concentration', 'Conc', 'Conc.', 'Result',
                              'Value', 'Mol%', 'Mole%', 'Amount']:
                if candidate.lower() in col_index:
                    value_column = col_names[col_index[candidate.lower()]]
                    break

        if not unit_column:
            for candidate in ['Unit', 'Units', 'UOM']:
                if candidate.lower() in col_index:
                    unit_column = col_names[col_index[candidate.lower()]]
                    break

        if not name_column or not value_column:
            raise ParseError(
                f"Cannot auto-detect columns in ABB NGC output. "
                f"Found columns: {col_names}. "
                f"Please specify name_column and value_column in config."
            )

        # Parse component rows
        components: Dict[str, Dict[str, Any]] = {}
        name_idx = col_index.get(name_column.lower(), -1)
        value_idx = col_index.get(value_column.lower(), -1)
        unit_idx = col_index.get(unit_column.lower(), -1) if unit_column else -1

        data_rows = table_rows[1:]

        for row in data_rows:
            if name_idx < 0 or name_idx >= len(row):
                continue
            if value_idx < 0 or value_idx >= len(row):
                continue

            comp_name = row[name_idx].strip()
            if not comp_name:
                continue

            # Skip summary rows (Total, Sum, Balance, etc.)
            if comp_name.lower() in ('total', 'sum', 'balance', 'remainder',
                                     'unidentified', '---', '***'):
                # Store in metadata instead
                raw_val = row[value_idx].strip()
                parsed_val = BaseTemplate._safe_float(raw_val)
                if parsed_val is not None:
                    metadata[comp_name] = parsed_val
                continue

            raw_value = row[value_idx].strip()
            parsed_value = BaseTemplate._safe_float(raw_value)

            if parsed_value is None:
                continue

            # Determine unit
            unit = default_unit
            if 0 <= unit_idx < len(row):
                row_unit = row[unit_idx].strip()
                if row_unit:
                    unit = row_unit
            elif raw_value:
                extracted = BaseTemplate._extract_unit(raw_value)
                if extracted:
                    unit = extracted

            # Apply column mapping
            tag_name = column_mapping.get(comp_name, comp_name)

            components[tag_name] = {
                'value': parsed_value,
                'unit': unit,
            }

        # Add calculated properties from metadata if present
        for prop in ('Heating Value', 'Wobbe Index', 'Specific Gravity',
                     'Compressibility', 'Z Factor'):
            for key in list(metadata.keys()):
                if key.lower() == prop.lower():
                    val = BaseTemplate._safe_float(str(metadata[key]))
                    if val is not None:
                        metadata[key] = val

        return BaseTemplate._make_result(
            timestamp=timestamp,
            components=components,
            metadata=metadata,
            raw_rows=len(data_rows),
        )

    @staticmethod
    def _parse_ngc_timestamp(raw_ts: str, user_format: str = '') -> str:
        """Parse ABB NGC timestamp formats into ISO format."""
        if not raw_ts:
            return ''

        raw_ts = raw_ts.strip()

        # Try user format first
        if user_format:
            try:
                dt = datetime.strptime(raw_ts, user_format)
                return dt.isoformat()
            except ValueError:
                pass

        # Common ABB formats
        formats = [
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%dT%H:%M:%S',
            '%d/%m/%Y %H:%M:%S',
            '%m/%d/%Y %H:%M:%S',
            '%Y%m%d %H%M%S',
            '%d-%b-%Y %H:%M:%S',
            '%Y-%m-%d',
        ]

        for fmt in formats:
            try:
                dt = datetime.strptime(raw_ts, fmt)
                return dt.isoformat()
            except ValueError:
                continue

        # ISO fallback
        try:
            dt = datetime.fromisoformat(raw_ts)
            return dt.isoformat()
        except ValueError:
            pass

        logger.warning(f"Could not parse NGC timestamp: {raw_ts!r}")
        return raw_ts

# ---------------------------------------------------------------------------
# GCParser — Template Registry and Entry Point
# ---------------------------------------------------------------------------

# Template registry: name -> template class
_TEMPLATE_REGISTRY: Dict[str, Type[BaseTemplate]] = {
    'generic': GenericCSVTemplate,
    'generic_csv': GenericCSVTemplate,
    'agilent': AgilentCSVTemplate,
    'agilent_csv': AgilentCSVTemplate,
    'abb_ngc': ABBNGCTemplate,
}

class GCParser:
    """
    Pluggable GC result parser with template registry.

    Usage:
        # Parse with a specific template
        result = GCParser.parse(content, template='agilent', config={...})

        # List available templates
        templates = GCParser.list_templates()

        # Register a custom template
        GCParser.register_template('custom', MyCustomTemplate)
    """

    def __init__(
        self,
        template: str = 'generic',
        delimiter: str = ',',
        header_rows: int = 0,
        encoding: str = 'utf-8',
        column_mapping: Optional[Dict[str, str]] = None,
        timestamp_column: str = '',
        timestamp_format: str = '%Y-%m-%d %H:%M:%S',
    ):
        """Create a GCParser instance with stored config.

        This allows file_watcher.py and serial_source.py to create a
        parser once and call parser.parse(content) repeatedly.
        """
        self._template = template
        self._config = {
            'delimiter': delimiter,
            'header_rows': header_rows,
            'encoding': encoding,
            'column_mapping': column_mapping or {},
            'timestamp_column': timestamp_column,
            'timestamp_format': timestamp_format,
        }

    def parse(self, content: str,
              template: str = '',
              config: Optional[Dict[str, Any]] = None,
              source_path: str = '') -> Dict[str, Any]:
        """Parse content using instance config or explicit overrides.

        Supports both instance-based and static-style calling:
          - parser.parse(content)  — uses stored template/config
          - parser.parse(content, source_path='file.csv')
          - GCParser.parse_static(content, template='agilent', config={})
        """
        tpl = template or self._template
        cfg = config if config is not None else self._config
        result = GCParser.parse_static(content, template=tpl, config=cfg)
        if source_path:
            result.setdefault('metadata', {})['source_path'] = source_path
        return result

    @staticmethod
    def parse_static(content: str,
                     template: str = 'generic',
                     config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Parse GC result file content using the specified template.

        Args:
            content:  Full file content as a string.
            template: Template name ('generic', 'agilent', 'abb_ngc').
            config:   Template-specific configuration dict.

        Returns:
            Normalized result dict:
            {
                'timestamp': 'ISO string or empty',
                'components': {
                    'ComponentName': {'value': float, 'unit': str},
                    ...
                },
                'metadata': {...},
                'raw_rows': int,
            }

        Raises:
            ParseError: If the content cannot be parsed.
            ValueError: If the template name is not registered.
        """
        template_lower = template.lower()

        if template_lower not in _TEMPLATE_REGISTRY:
            available = ', '.join(sorted(_TEMPLATE_REGISTRY.keys()))
            raise ValueError(
                f"Unknown GC parser template '{template}'. "
                f"Available templates: {available}"
            )

        template_cls = _TEMPLATE_REGISTRY[template_lower]

        try:
            result = template_cls.parse(content, config)
        except ParseError:
            raise
        except Exception as e:
            raise ParseError(f"Failed to parse with template '{template}': {e}") from e

        # Validate result structure
        if not isinstance(result, dict):
            raise ParseError(f"Template '{template}' returned non-dict result")

        for key in ('timestamp', 'components', 'metadata', 'raw_rows'):
            if key not in result:
                raise ParseError(f"Template '{template}' result missing key '{key}'")

        return result

    @staticmethod
    def register_template(name: str, template_cls: Type[BaseTemplate]):
        """
        Register a custom parsing template.

        Args:
            name:         Template name (lowercase, used in parse() calls).
            template_cls: Class with a static parse(content, config) method.

        Raises:
            ValueError: If a template with this name already exists.
        """
        name_lower = name.lower()

        if name_lower in _TEMPLATE_REGISTRY:
            raise ValueError(
                f"Template '{name}' is already registered. "
                f"Use unregister_template() first to replace it."
            )

        if not hasattr(template_cls, 'parse') or not callable(getattr(template_cls, 'parse')):
            raise ValueError(
                f"Template class must have a callable parse(content, config) method"
            )

        _TEMPLATE_REGISTRY[name_lower] = template_cls
        logger.info(f"Registered GC parser template: {name}")

    @staticmethod
    def unregister_template(name: str):
        """
        Remove a registered template.

        Args:
            name: Template name to remove.

        Raises:
            ValueError: If the template is not registered.
        """
        name_lower = name.lower()

        if name_lower not in _TEMPLATE_REGISTRY:
            raise ValueError(f"Template '{name}' is not registered")

        del _TEMPLATE_REGISTRY[name_lower]
        logger.info(f"Unregistered GC parser template: {name}")

    @staticmethod
    def list_templates() -> List[str]:
        """Return list of registered template names."""
        return sorted(_TEMPLATE_REGISTRY.keys())

    @staticmethod
    def auto_detect(content: str) -> str:
        """
        Attempt to auto-detect the appropriate template for the given content.

        Heuristic checks:
        - Agilent: Look for ChemStation/OpenLab markers
        - ABB NGC: Look for ABB-specific structure (tab-delimited, gas components)
        - Fallback: generic

        Args:
            content: File content to analyze.

        Returns:
            Template name string.
        """
        if not content:
            return 'generic'

        content_lower = content.lower()

        # Check for Agilent markers
        agilent_markers = [
            'chemstation', 'openlab', 'agilent',
            'injection date', 'sample name',
            'acq. method', 'analysis method',
        ]
        agilent_score = sum(1 for m in agilent_markers if m in content_lower)
        if agilent_score >= 2:
            return 'agilent'

        # Check for ABB NGC markers
        abb_markers = [
            'analysis date', 'stream',
            'heating value', 'wobbe index', 'specific gravity',
            'compressibility', 'z factor',
        ]
        abb_score = sum(1 for m in abb_markers if m in content_lower)

        # Also check if tab-delimited with gas component names
        gas_components = ['methane', 'ethane', 'propane', 'butane',
                          'pentane', 'nitrogen', 'carbon dioxide', 'co2']
        gas_score = sum(1 for g in gas_components if g in content_lower)

        if abb_score >= 2 or (abb_score >= 1 and gas_score >= 3):
            return 'abb_ngc'

        # Check if the file is tab-delimited (ABB-like) vs comma-delimited
        lines = content.splitlines()[:20]
        tab_count = sum(line.count('\t') for line in lines)
        comma_count = sum(line.count(',') for line in lines)

        if tab_count > comma_count and gas_score >= 2:
            return 'abb_ngc'

        return 'generic'
