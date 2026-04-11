"""
Export a clean open-source copy of NISystem as ICCSFlux.

Copies the full codebase, then strips:
- DOD/NIST/CMMC compliance docs and internal docs
- NIST/CMMC/CUI references in code comments (keeps the security features)
- Credentials, data files, TLS certs, user databases
- Claude Code settings, audit reports, vendor dirs
- Station-specific project configs and test data

The exported copy is a clean git repo ready to push to a public GitHub repo.

Author: DAC

Usage:
    python scripts/export_opensource.py                     # Export to ../ICCSFlux
    python scripts/export_opensource.py --output ../my-dir  # Custom output path
    python scripts/export_opensource.py --dry-run            # Show what would be done
"""

import argparse
import os
import re
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
DEFAULT_OUTPUT = PROJECT_ROOT.parent / "ICCSFlux"

# ── Files and directories to completely exclude ─────────────────────────
EXCLUDE_DIRS = {
    ".claude",
    ".git",
    ".pytest_cache",
    "__pycache__",
    "audit_reports",
    "azure-venv",
    "build",
    "config/tls",
    "dashboard/demo-dist",
    "dashboard/node_modules",
    "data",
    "dist",
    "monitor/node_modules",
    "node_modules",
    "vendor",
    "venv",
    ".venv",
}

EXCLUDE_FILES = {
    # DOD/NIST compliance docs
    "docs/NIST_800-171_Compliance_Roadmap.md",
    "docs/Risk_Assessment_NIST_800-30.md",
    "docs/IT_Security_and_Compliance_Guide.md",
    "docs/OT_Security_Standards_Reference.md",
    "docs/Standards_and_Compliance.md",
    "docs/Safety_Certification_Roadmap.md",
    # Internal docs (business case, VM setup, audit findings)
    "docs/internal/ICCSFlux_IP_Business_Case.md",
    "docs/internal/ICCSFlux_System_and_VM_Overview.md",
    "docs/internal/INDUSTRIAL_AUDIT.md",
    "docs/internal/AUDIT_FINDINGS.md",
    "docs/internal/GC_VM_Setup_Guide.md",
    "docs/internal/PLAN-network-auto-update.md",
    "docs/internal/PORTABLE_CLEANUP_ANALYSIS.md",
    "docs/internal/SINGLE_INSTANCE_IMPLEMENTATION.md",
    "docs/internal/SYSTEM_VALIDATION_REPORT.md",
    # Credentials and secrets
    "config/mqtt_credentials.json",
    "config/mosquitto_passwd",
    "data/initial_admin_password.txt",
    # Station-specific test configs
    "config/station_state.json",
    # Client-specific project configs
    "config/projects/23832_Battery_Backup.json",
    "config/projects/Boiler_Combustion_Research_cDAQ.json",
    "config/projects/CRIO Test 192168120.json",
    "config/projects/DCFlux.json",
    "config/projects/DHW Test System.json",
    "config/projects/GO2_Membrane_Skid.json",
    "config/projects/H2-Ready_Boiler_Combustion_Research.json",
    "config/projects/RNG_CNG_Compression_Station.json",
    "config/projects/blankcrioconfig6mod.json",
    "config/projects/_DhwSimSoakTest.json",
    "config/projects/_StationTest_Zone1.json",
    "config/projects/_StationTest_Zone2.json",
    # Client-specific exports and archive configs
    "config/archive/boiler_combustion_demo.json",
    "config/archive/dhw_dashboard_layout.json",
    "config/archive/dhw_test_system.json",
    "config/archive/dhw_valve_schedule.json",
    # ICCSFlux session exports (may contain client data)
    "config/projects/ICCSFlux_export_2026-02-02.json",
    "config/projects/ICCSFlux_export_2026-02-03.json",
    "config/projects/ICCSFlux_export_2026-02-05.json",
    "config/projects/ICCSFlux_export_2026-02-09.json",
    "config/projects/ICCSFlux_export_2026-02-10.json",
    "config/projects/ICCSFlux_export_2026-03-06.json",
    # Client-specific test/generation scripts
    "tests/test_dhwsim_soak.py",
    "tests/test_station_integration.py",
    "tests/test_station_management.py",
    "tests/test_station_manager_unit.py",
    "scripts/create_dhwsim_soak_project.py",
    "scripts/create_station_test_projects.py",
    # Syncthing / editor artifacts
    ".stignore",
}

EXCLUDE_PATTERNS = [
    "*.sync-conflict-*",
    "*credentials*.json",
    "*_secret*",
    "*.pem",
    "*.key",
    "**/users.json",
    ".env.local",
    ".env.production",
]

# ── NIST/DOD comment scrubbing patterns ─────────────────────────────────
# These remove compliance LABELS from comments, not the security features themselves.
SCRUB_PATTERNS = [
    # Comment lines that are purely NIST/CMMC references
    (re.compile(r'^\s*#.*\bNIST\s+800-171\b.*$', re.MULTILINE), None),
    (re.compile(r'^\s*#.*\bCMMC\s+Level\s+\d\b.*$', re.MULTILINE), None),
    (re.compile(r'^\s*#.*\bDFARS\b.*$', re.MULTILINE), None),
    (re.compile(r'^\s*//.*\bNIST\s+800-171\b.*$', re.MULTILINE), None),
    (re.compile(r'^\s*//.*\bCMMC\s+Level\s+\d\b.*$', re.MULTILINE), None),
    # Inline NIST references in comments (keep the rest of the comment)
    (re.compile(r'\s*\(NIST\s+800-171[^)]*\)'), ""),
    (re.compile(r'\s*\(CMMC[^)]*\)'), ""),
    # Vue template NIST badge text
    (re.compile(r'NIST 800-171'), "Security Compliance"),
    (re.compile(r'CMMC Level \d'), "Security Compliance"),
]

# Files to apply comment scrubbing to (by extension)
SCRUB_EXTENSIONS = {".py", ".ts", ".vue", ".js", ".json", ".md", ".conf"}

# Files to skip scrubbing (binary, generated, etc.)
SCRUB_SKIP_DIRS = {"node_modules", "__pycache__", ".git", "vendor", "dist"}


def should_exclude_path(rel_path: str) -> bool:
    """Check if a relative path should be excluded."""
    parts = Path(rel_path).parts

    # Check excluded directories
    for excl_dir in EXCLUDE_DIRS:
        excl_parts = Path(excl_dir).parts
        if parts[:len(excl_parts)] == excl_parts:
            return True

    # Check excluded files
    if rel_path.replace("\\", "/") in EXCLUDE_FILES:
        return True

    # Check patterns
    name = Path(rel_path).name
    for pattern in EXCLUDE_PATTERNS:
        if "**/" in pattern:
            if Path(rel_path).match(pattern.replace("**/", "")):
                return True
        elif "*" in pattern:
            if Path(name).match(pattern):
                return True
        elif name == pattern:
            return True

    return False


def scrub_file_content(content: str, file_path: str) -> str:
    """Remove NIST/DOD compliance references from file content."""
    ext = Path(file_path).suffix.lower()
    if ext not in SCRUB_EXTENSIONS:
        return content

    result = content
    for pattern, replacement in SCRUB_PATTERNS:
        if replacement is None:
            # Remove entire matching lines
            result = pattern.sub("", result)
        else:
            result = pattern.sub(replacement, result)

    # Clean up multiple blank lines left by removed comments
    result = re.sub(r'\n{3,}', '\n\n', result)

    return result


def export(output_dir: Path, dry_run: bool = False):
    """Export clean open-source copy."""
    if output_dir.exists() and not dry_run:
        print(f"Output directory exists: {output_dir}")
        response = input("  Delete and recreate? [y/N] ")
        if response.lower() != 'y':
            print("Aborted.")
            return False

    print(f"\n{'DRY RUN — ' if dry_run else ''}Exporting ICCSFlux to: {output_dir}\n")

    # Collect all files
    all_files = []
    excluded_files = []
    scrubbed_files = []

    for root, dirs, files in os.walk(PROJECT_ROOT):
        # Skip excluded directories (modify dirs in-place to prevent descent)
        rel_root = Path(root).relative_to(PROJECT_ROOT)
        dirs[:] = [d for d in dirs
                   if not should_exclude_path(str(rel_root / d))]

        for fname in files:
            rel_path = str((rel_root / fname)).replace("\\", "/")

            if should_exclude_path(rel_path):
                excluded_files.append(rel_path)
                continue

            all_files.append(rel_path)

    print(f"  Files to copy:    {len(all_files)}")
    print(f"  Files excluded:   {len(excluded_files)}")

    if dry_run:
        print("\n  EXCLUDED:")
        for f in sorted(excluded_files)[:30]:
            print(f"    - {f}")
        if len(excluded_files) > 30:
            print(f"    ... and {len(excluded_files) - 30} more")
        return True

    # Clean output directory
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    # Copy and scrub files
    for rel_path in all_files:
        src = PROJECT_ROOT / rel_path
        dst = output_dir / rel_path
        dst.parent.mkdir(parents=True, exist_ok=True)

        ext = Path(rel_path).suffix.lower()
        if ext in SCRUB_EXTENSIONS:
            try:
                content = src.read_text(encoding="utf-8", errors="replace")
                scrubbed = scrub_file_content(content, rel_path)
                if scrubbed != content:
                    scrubbed_files.append(rel_path)
                dst.write_text(scrubbed, encoding="utf-8")
            except Exception:
                shutil.copy2(src, dst)
        else:
            shutil.copy2(src, dst)

    print(f"  Files scrubbed:   {len(scrubbed_files)}")
    if scrubbed_files:
        for f in scrubbed_files:
            print(f"    ~ {f}")

    # Write a clean README header
    readme_path = output_dir / "README.md"
    if readme_path.exists():
        content = readme_path.read_text(encoding="utf-8")
        # Ensure the project name reflects ICCSFlux
        if "NISystem" in content:
            content = content.replace("NISystem", "ICCSFlux")
            readme_path.write_text(content, encoding="utf-8")

    # Remove CLAUDE.md from the export (it's project-internal)
    claude_md = output_dir / "CLAUDE.md"
    if claude_md.exists():
        claude_md.unlink()
        print("  Removed CLAUDE.md (project-internal)")

    # Create .gitignore for the public repo (based on existing, cleaned up)
    gitignore_src = output_dir / ".gitignore"
    if gitignore_src.exists():
        content = gitignore_src.read_text(encoding="utf-8")
        # Add extra exclusions for public repo
        if "# Open-source exclusions" not in content:
            content += "\n# Open-source exclusions\n.claude/\naudit_reports/\n"
            gitignore_src.write_text(content, encoding="utf-8")

    # Initialize clean git repo
    import subprocess
    subprocess.run(["git", "init"], cwd=output_dir, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=output_dir, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial open-source release of ICCSFlux"],
        cwd=output_dir, capture_output=True
    )

    print(f"\n  Done! Clean repo at: {output_dir}")
    print(f"  Next steps:")
    print(f"    cd {output_dir}")
    print(f"    gh repo create danteacastro/ICCSFlux --public --source=.")
    print(f"    git push -u origin main")

    return True


def main():
    parser = argparse.ArgumentParser(description="Export clean open-source ICCSFlux repo")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT),
                        help=f"Output directory (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be excluded without copying")
    args = parser.parse_args()

    export(Path(args.output), dry_run=args.dry_run)


if __name__ == "__main__":
    main()
