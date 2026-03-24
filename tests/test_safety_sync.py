"""
Test that cRIO and Opto22 safety.py files remain in sync.

Per CLAUDE.md: "crio_node_v2/safety.py and opto22_node/safety.py are identical
except for the logger name. When modifying safety logic, edit cRIO first, then
copy to Opto22 and change the logger name."

This test catches divergence before it becomes a safety issue.
"""

import os

CRIO_SAFETY = os.path.join(os.path.dirname(__file__), '..', 'services', 'crio_node_v2', 'safety.py')
OPTO22_SAFETY = os.path.join(os.path.dirname(__file__), '..', 'services', 'opto22_node', 'safety.py')

def _normalize(content: str) -> str:
    """Normalize the file by replacing known allowed differences."""
    # The only allowed difference: logger name
    content = content.replace("logging.getLogger('cRIONode')", "logging.getLogger('<NODE>')")
    content = content.replace("logging.getLogger('Opto22Node')", "logging.getLogger('<NODE>')")
    # Docstring header may differ
    content = content.replace('Safety Module for cRIO Node V2', 'Safety Module for <NODE>')
    content = content.replace('Safety Module for Opto22 Node', 'Safety Module for <NODE>')
    return content

def _assert_files_in_sync(name_a: str, path_a: str, name_b: str, path_b: str):
    """Assert two safety files are identical after normalization."""
    with open(path_a, 'r', encoding='utf-8') as f:
        content_a = _normalize(f.read())
    with open(path_b, 'r', encoding='utf-8') as f:
        content_b = _normalize(f.read())

    if content_a != content_b:
        lines_a = content_a.splitlines()
        lines_b = content_b.splitlines()
        for i, (a, b) in enumerate(zip(lines_a, lines_b), 1):
            if a != b:
                assert False, (
                    f"{name_a} and {name_b} safety.py diverge at line {i}:\n"
                    f"  {name_a}: {a.strip()}\n"
                    f"  {name_b}: {b.strip()}\n"
                    f"Edit cRIO first, then copy to {name_b} and change the logger name."
                )
        if len(lines_a) != len(lines_b):
            assert False, (
                f"{name_a} safety.py has {len(lines_a)} lines, "
                f"{name_b} has {len(lines_b)} lines. "
                f"Files must be identical (except logger name)."
            )

def test_crio_opto22_safety_in_sync():
    """Verify cRIO and Opto22 safety.py are identical (except logger name)."""
    _assert_files_in_sync('cRIO', CRIO_SAFETY, 'Opto22', OPTO22_SAFETY)

def test_safety_files_exist():
    """Verify both safety.py files exist."""
    assert os.path.isfile(CRIO_SAFETY), f"cRIO safety.py not found: {CRIO_SAFETY}"
    assert os.path.isfile(OPTO22_SAFETY), f"Opto22 safety.py not found: {OPTO22_SAFETY}"
