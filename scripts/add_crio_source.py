#!/usr/bin/env python3
"""
Add cRIO source metadata to a .nisystem project file.

Usage:
    python add_crio_source.py <input.nisystem> <node_id> [output.nisystem]

Example:
    python add_crio_source.py CZFlux.nisystem crio-001
    python add_crio_source.py CZFlux.nisystem crio-001 CZFlux_crio.nisystem
"""

import json
import sys
from pathlib import Path


def add_crio_source(input_path: str, node_id: str, output_path: str = None):
    """Add source_type and source_node_id to all channels in a project file."""

    # Read the project file
    with open(input_path, 'r', encoding='utf-8') as f:
        project = json.load(f)

    if 'channels' not in project:
        print("Error: No 'channels' section found in project file")
        return False

    # Count channels updated
    updated = 0
    skipped = 0

    for tag_name, channel in project['channels'].items():
        # Skip if already has source_type
        if channel.get('source_type'):
            skipped += 1
            continue

        # Add cRIO source metadata
        channel['source_type'] = 'crio'
        channel['source_node_id'] = node_id
        updated += 1

    # Also update alarm configs if they exist
    if 'alarmConfigs' in project:
        for alarm_id, alarm in project['alarmConfigs'].items():
            if 'source_node_id' not in alarm:
                alarm['source_node_id'] = node_id

    # Determine output path
    if output_path is None:
        # Overwrite input file
        output_path = input_path

    # Write the updated project
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(project, f, indent=2)

    print(f"Updated {updated} channels with source_type='crio', source_node_id='{node_id}'")
    if skipped:
        print(f"Skipped {skipped} channels (already had source_type)")
    print(f"Saved to: {output_path}")

    return True


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    input_path = sys.argv[1]
    node_id = sys.argv[2]
    output_path = sys.argv[3] if len(sys.argv) > 3 else None

    if not Path(input_path).exists():
        print(f"Error: File not found: {input_path}")
        sys.exit(1)

    success = add_crio_source(input_path, node_id, output_path)
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
