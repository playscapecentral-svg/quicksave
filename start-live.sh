#!/bin/sh
# QuickSave LIVE via Cloudflare Tunnel (Mac/Linux)
# First time: follow cloudflare/README-CLOUDFLARE.md (login/create/route/config).
# Every run: pulls the latest code from GitHub, starts the server, then the tunnel.
cd "$(dirname "$0")"
echo "[1/3] Pulling latest from GitHub..."
git pull || true
echo "[2/3] Starting server in background..."
nohup ./start-server.sh > quicksave-server.log 2>&1 &
sleep 5
echo "[3/3] Starting Cloudflare Tunnel - keep this terminal open..."
exec cloudflared tunnel run quicksave
