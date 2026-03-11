#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Killing any existing tunnel..."
pkill -f "ssh.*erebus" 2>/dev/null || true
sleep 1

echo "Starting tunnel..."
bash "$SCRIPT_DIR/tunnel.sh" &
TUNNEL_PID=$!
echo "Tunnel PID: $TUNNEL_PID"
echo $TUNNEL_PID > "$SCRIPT_DIR/.tunnel.pid"

echo "Waiting for tunnel..."
sleep 8

echo "Starting Prometheus and Grafana..."
sudo docker compose -f "$SCRIPT_DIR/docker-compose.yml" up -d

echo ""
echo "Done. Grafana: http://localhost:3000 (admin/admin)"
echo "      Prometheus: http://localhost:9090"
