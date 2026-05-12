#!/bin/bash
# tunnel.sh — Submit a vLLM serve job on Slurm, wait for it to come up,
# then run an auto-restarting SSH tunnel from localhost to the compute node.
#
# Usage: ./tunnel.sh [MODEL] [LOCAL_PORT]
#   LOCAL_PORT defaults to 8000. The remote vLLM port is hardcoded to 8000.

set -euo pipefail

# --- Configuration ---------------------------------------------------------

LOGIN="jtm2066@slurm01.cs.northwestern.edu"
PROJECT_DIR="/nyx-projects/jtm2066/canary/language-models"
MODEL="${1:-google/gemma-4-E2B-it}"
LOCAL_PORT="${2:-8000}"
REMOTE_PORT=8000

PID_FILE=".tunnel.pid"
LOG_FILE="tunnel.log"

# --- Helpers ---------------------------------------------------------------

remote() {
    ssh "$LOGIN" "$@"
}

# Poll until the given command succeeds, printing a dotted progress line.
wait_for() {
    local message=$1; shift
    echo -n "$message"
    until "$@" &>/dev/null; do
        echo -n "."
        sleep 2
    done
    echo " ✓"
}

job_is_running() {
    [[ -n "$(remote squeue -j "$JOB_ID" -h -t RUNNING -o '%N')" ]]
}

vllm_is_healthy() {
    remote "curl -sf --max-time 2 http://${NODE}:${REMOTE_PORT}/health"
}

# --- Submit the serve job --------------------------------------------------

echo "Submitting serve job ($MODEL on port $REMOTE_PORT)..."
JOB_ID=$(remote "cd $PROJECT_DIR && sbatch --parsable serve.sh '$MODEL' '$REMOTE_PORT'")
echo "Job ID: $JOB_ID"

# --- Wait for the node to be assigned and vLLM to be ready -----------------

wait_for "Waiting for job to start" job_is_running
NODE=$(remote "squeue -j $JOB_ID -h -t RUNNING -o '%N'")
echo "Node: $NODE"

wait_for "Waiting for vLLM" vllm_is_healthy

# --- Start the auto-restarting background tunnel ---------------------------

echo "Tunneling localhost:$LOCAL_PORT -> $NODE:$REMOTE_PORT (logs: $LOG_FILE)"

nohup bash -c "
while :; do
    ssh -N \
        -L '$LOCAL_PORT:localhost:$REMOTE_PORT' \
        -o ProxyCommand='ssh -W %h:%p $LOGIN' \
        -o StrictHostKeyChecking=no \
        -o UserKnownHostsFile=/dev/null \
        -o ServerAliveInterval=30 \
        -o ServerAliveCountMax=3 \
        -o ExitOnForwardFailure=yes \
        'jtm2066@$NODE'
    echo \"\$(date): tunnel died, restarting in 5s...\"
    sleep 5
done
" > "$LOG_FILE" 2>&1 &

echo $! > "$PID_FILE"
disown

echo "Tunnel PID: $(cat "$PID_FILE")"
echo "Stop with:  kill \$(cat $PID_FILE)"
