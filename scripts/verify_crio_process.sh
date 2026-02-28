#!/bin/sh
# Verify exactly one cRIO process is running.
# Exit 0 = exactly one process (safe). Exit 1 = zero or multiple (unsafe).
# Uses ps+grep instead of pgrep -f to avoid self-matching.

PROC_COUNT=$(ps aux | grep 'run_crio_v2.py' | grep -v grep | wc -l)

echo "cRIO process count: $PROC_COUNT"

if [ "$PROC_COUNT" -eq 0 ]; then
    echo "SAFETY FAIL: No cRIO process running!"
    exit 1
elif [ "$PROC_COUNT" -gt 1 ]; then
    echo "SAFETY FAIL: Multiple cRIO processes detected — split-brain hazard!"
    ps aux | grep 'run_crio_v2.py' | grep -v grep
    exit 1
else
    echo "SAFETY OK: Exactly 1 cRIO process running"
    ps aux | grep 'run_crio_v2.py' | grep -v grep
    exit 0
fi
