"""
Compare the current working tree against a previous portable build's source manifest.

Shows which source files have been added, modified, or deleted since the build
was created — without requiring git commits.

Author: DAC

Usage:
    python scripts/build_diff.py                           # Compare against latest build
    python scripts/build_diff.py dist/ICCSFlux-Portable    # Compare against specific build
    python scripts/build_diff.py --summary                 # Counts only
    python scripts/build_diff.py --json                    # Machine-readable output
"""

import hashlib
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
DEFAULT_BUILD = PROJECT_ROOT / "dist" / "ICCSFlux-Portable"


def hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def scan_current_sources() -> dict[str, str]:
    """Hash all source files in the current working tree."""
    source_patterns = [
        "services/**/*.py",
        "scripts/*.py",
        "dashboard/src/**/*.vue",
        "dashboard/src/**/*.ts",
        "dashboard/src/**/*.tsx",
        "config/*.json",
        "config/*.conf",
        "config/*.ini",
        "*.md",
        "*.bat",
    ]
    exclude_dirs = {"node_modules", "__pycache__", ".git", "dist", "build",
                    "venv", "azure-venv", ".venv", "vendor", "data"}

    current = {}
    for pattern in source_patterns:
        for filepath in PROJECT_ROOT.glob(pattern):
            if not filepath.is_file():
                continue
            rel = filepath.relative_to(PROJECT_ROOT)
            if any(part in exclude_dirs for part in rel.parts):
                continue
            try:
                current[str(rel.as_posix())] = hash_file(filepath)
            except (OSError, PermissionError):
                continue
    return current


def load_manifest(build_dir: Path) -> tuple[dict[str, str], str]:
    """Load SOURCE_MANIFEST.json from a build directory."""
    manifest_path = build_dir / "SOURCE_MANIFEST.json"
    if not manifest_path.exists():
        print(f"ERROR: No SOURCE_MANIFEST.json in {build_dir}")
        print("       This build was created before source manifests were added.")
        print("       Rebuild with the latest build_exe.py to generate one.")
        sys.exit(1)

    data = json.loads(manifest_path.read_text())
    return data["files"], data.get("generated", "unknown")


def compute_diff(build_files: dict[str, str], current_files: dict[str, str]):
    """Compare build manifest against current working tree."""
    all_keys = set(build_files.keys()) | set(current_files.keys())

    added = []
    modified = []
    deleted = []

    for key in sorted(all_keys):
        in_build = key in build_files
        in_current = key in current_files

        if in_current and not in_build:
            added.append(key)
        elif in_build and not in_current:
            deleted.append(key)
        elif build_files[key] != current_files[key]:
            modified.append(key)

    return added, modified, deleted


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Diff current source against a portable build")
    parser.add_argument("build_dir", nargs="?", default=str(DEFAULT_BUILD),
                        help="Path to portable build (default: dist/ICCSFlux-Portable)")
    parser.add_argument("--summary", action="store_true", help="Show counts only")
    parser.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    parser.add_argument("--modified-only", action="store_true", help="Only show modified files")
    args = parser.parse_args()

    build_dir = Path(args.build_dir)
    if not build_dir.exists():
        print(f"ERROR: Build directory not found: {build_dir}")
        sys.exit(1)

    build_files, build_time = load_manifest(build_dir)
    current_files = scan_current_sources()
    added, modified, deleted = compute_diff(build_files, current_files)

    if args.json:
        output = {
            "build_dir": str(build_dir),
            "build_time": build_time,
            "build_files": len(build_files),
            "current_files": len(current_files),
            "added": added,
            "modified": modified,
            "deleted": deleted,
        }
        print(json.dumps(output, indent=2))
        return

    # Header
    version_file = build_dir / "VERSION.txt"
    version_info = ""
    if version_file.exists():
        for line in version_file.read_text().splitlines():
            if "Git commit:" in line or "Build time:" in line:
                version_info += f"  {line.strip()}\n"

    print()
    print("=" * 60)
    print("  SOURCE DIFF: Working Tree vs Portable Build")
    print("=" * 60)
    print(f"  Build:     {build_dir.name}")
    print(f"  Manifest:  {build_time}")
    if version_info:
        print(version_info.rstrip())
    print(f"  Files at build: {len(build_files)}  |  Files now: {len(current_files)}")
    print()

    total_changes = len(added) + len(modified) + len(deleted)

    if total_changes == 0:
        print("  No changes detected — working tree matches the build.")
        print()
        return

    print(f"  Changes: {len(modified)} modified, {len(added)} added, {len(deleted)} deleted")
    print()

    if args.summary:
        return

    if modified:
        print("MODIFIED")
        print("-" * 40)
        for f in modified:
            print(f"  M  {f}")
        print()

    if added and not args.modified_only:
        print("ADDED")
        print("-" * 40)
        for f in added:
            print(f"  A  {f}")
        print()

    if deleted and not args.modified_only:
        print("DELETED")
        print("-" * 40)
        for f in deleted:
            print(f"  D  {f}")
        print()


if __name__ == "__main__":
    main()
