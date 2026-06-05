#!/bin/bash
# killall.sh — Tear down the local SSH tunnel and cancel all of my Slurm jobs.

LOGIN="jtm2066@slurm01.cs.northwestern.edu"
PID_FILE=".tunnel.pid"

# --- Kill the local tunnel -------------------------------------------------

if [[ -f "$PID_FILE" ]]; then
    PID=$(cat "$PID_FILE")
    if kill "$PID" 2>/dev/null; then
        echo "Killed tunnel (PID $PID)"
    else
        echo "Tunnel PID $PID not running"
    fi
    rm -f "$PID_FILE"
else
    echo "No $PID_FILE file found"
fi

# --- Cancel all of my remote Slurm jobs ------------------------------------

ssh "$LOGIN" "scancel -u \$USER && echo 'All Slurm jobs cancelled.'"
