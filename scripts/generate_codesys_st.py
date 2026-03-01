"""
Generate CODESYS Structured Text from an NISystem project JSON.

Reads PID loops, interlocks, and channels from the project file and generates
IEC 61131-3 ST files for the groov EPIC CODESYS runtime.

Usage:
    python scripts/generate_codesys_st.py config/projects/MyProject.json
    python scripts/generate_codesys_st.py config/projects/MyProject.json --output dist/codesys_st

Output:
    FB_PID_Loop.st      - PID controller function block
    FB_Interlock.st     - IEC 61511 interlock state machine
    FB_SafeState.st     - Safe state manager
    GVL_Registers.st    - Global variable list with Modbus AT declarations
    Main.st             - Main program (project-specific wiring)
"""

import argparse
import json
import sys
from pathlib import Path

# Add project root to path so we can import the opto22 codegen
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from services.opto22_node.codesys.st_codegen import STCodeGenerator


def load_project(project_path: Path) -> dict:
    """Load and validate a project JSON file."""
    if not project_path.exists():
        print(f"ERROR: Project file not found: {project_path}")
        sys.exit(1)

    with open(project_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    if data.get('type') != 'nisystem-project':
        print(f"WARNING: File may not be an NISystem project (type={data.get('type')})")

    return data


def extract_pid_loops(project: dict) -> list:
    """Extract PID loop configs from project data."""
    pid_data = project.get('pidLoops', {})
    loops = pid_data.get('loops', [])
    if not loops:
        print("  No PID loops found in project (pidLoops.loops)")
    else:
        print(f"  Found {len(loops)} PID loop(s)")
    return loops


def extract_interlocks(project: dict) -> list:
    """Extract interlock configs from project data."""
    # Try top-level interlocks first, then safety.interlocks
    interlocks = project.get('interlocks', [])
    if not interlocks:
        safety = project.get('safety', {})
        interlocks = safety.get('interlocks', [])
    if not interlocks:
        print("  No interlocks found in project")
    else:
        print(f"  Found {len(interlocks)} interlock(s)")
    return interlocks


def extract_channels(project: dict) -> dict:
    """Extract channel configs from project data."""
    channels = project.get('channels', {})
    if not channels:
        print("  No channels found in project")
    else:
        output_types = {'voltage_output', 'current_output', 'digital_output', 'analog_output'}
        inputs = sum(1 for ch in channels.values() if ch.get('channel_type', '') not in output_types)
        outputs = len(channels) - inputs
        print(f"  Found {len(channels)} channel(s) ({inputs} inputs, {outputs} outputs)")
    return channels


def main():
    parser = argparse.ArgumentParser(
        description='Generate CODESYS Structured Text from an NISystem project',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        'project',
        type=Path,
        help='Path to project JSON file (e.g., config/projects/MyProject.json)'
    )
    parser.add_argument(
        '--output', '-o',
        type=Path,
        default=Path('dist/codesys_st'),
        help='Output directory for generated ST files (default: dist/codesys_st)'
    )
    parser.add_argument(
        '--name',
        type=str,
        default=None,
        help='Project name (default: from project JSON)'
    )
    args = parser.parse_args()

    # Load project
    print(f"Loading project: {args.project}")
    project = load_project(args.project)
    project_name = args.name or project.get('name', args.project.stem)
    print(f"  Project: {project_name}")

    # Extract configuration
    print("\nExtracting configuration:")
    pid_loops = extract_pid_loops(project)
    interlocks = extract_interlocks(project)
    channels = extract_channels(project)

    if not pid_loops and not interlocks:
        print("\nWARNING: No PID loops or interlocks found.")
        print("The generated ST code will have no control logic.")
        print("PID loops must be configured in the running system and saved to the project.")
        print("(Configure PID via MQTT commands, then save the project to persist them.)")

    # Generate ST code
    print(f"\nGenerating Structured Text...")
    codegen = STCodeGenerator(project_name=project_name)

    if pid_loops:
        codegen.add_pid_loops(pid_loops)

    if interlocks:
        codegen.add_interlocks(interlocks)

    if channels:
        codegen.add_channels(channels)

    # Write files
    written = codegen.generate_to_dir(str(args.output))

    print(f"\nGenerated {len(written)} file(s) in {args.output}/:")
    for path in sorted(written):
        print(f"  {Path(path).name}")

    # Print register map summary
    rmap = codegen.get_register_map()
    print(f"\nRegister map:")
    print(f"  PID loops:   {len(rmap.pid_loops)}")
    print(f"  Interlocks:  {len(rmap.interlocks)}")
    print(f"  Channels:    {len(rmap.channels)}")
    print(f"  Outputs:     {len(rmap.outputs)}")

    # Warn about channels without I/O paths
    missing_io = [ch.name for ch in codegen._channels if '(* TODO' in ch.get_io_path()]
    if missing_io:
        print(f"\nWARNING: {len(missing_io)} channel(s) have no groov I/O path assigned.")
        print("These will appear as TODO comments in the generated ST code.")
        print("Add 'io_path' or 'groov_module_index'/'groov_channel_index' to channel config.")
        for name in missing_io[:5]:
            print(f"  - {name}")
        if len(missing_io) > 5:
            print(f"  ... and {len(missing_io) - 5} more")

    print(f"\nDone. Import these files into CODESYS IDE for the groov EPIC.")


if __name__ == '__main__':
    main()
