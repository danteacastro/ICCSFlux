#!/bin/sh
# Verify NO cRIO processes are running (safe to deploy).
# Exit 0 = clean (no processes). Exit 1 = processes still running (unsafe).
# Uses ps+grep instead of pgrep -f to avoid self-matching.

COUNT=$(ps aux | grep 'run_crio_v2.py' | grep -v grep | wc -l)

if [ "$COUNT" -gt 0 ]; then
    echo "FAIL: $COUNT run_crio_v2.py process(es) still running:"
    ps aux | grep 'run_crio_v2.py' | grep -v grep
    exit 1
fi

COUNT2=$(ps aux | grep 'python3 -m crio_node' | grep -v grep | wc -l)

if [ "$COUNT2" -gt 0 ]; then
    echo "FAIL: $COUNT2 python3 -m crio_node process(es) still running:"
    ps aux | grep 'python3 -m crio_node' | grep -v grep
    exit 1
fi

echo "CLEAN: No cRIO processes running"
exit 0
