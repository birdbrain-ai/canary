#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Stopping Prometheus and Grafana..."
sudo docker compose -f "$SCRIPT_DIR/docker-compose.yml" down

echo "Stopping tunnel..."
if [ -f "$SCRIPT_DIR/.tunnel.pid" ]; then
    TUNNEL_PID=$(cat "$SCRIPT_DIR/.tunnel.pid")
    kill "$TUNNEL_PID" 2>/dev/null && echo "Tunnel stopped." || echo "Tunnel already gone."
    rm "$SCRIPT_DIR/.tunnel.pid"
fi

pkill -f "ssh.*erebus" 2>/dev/null || true
echo "Done."
