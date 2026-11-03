#!/bin/sh
# QuickSave - one-time setup on a fresh Ubuntu/Debian VPS (e.g. Oracle Cloud Always Free)
# Run as a sudo-capable user:  sh setup-vps.sh
set -e

echo "[1/4] Installing Docker..."
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER" || true
fi

echo "[2/4] Getting the code..."
if [ -d quicksave/.git ]; then
  cd quicksave && git pull
else
  git clone https://github.com/playscapecentral-svg/quicksave.git
  cd quicksave
fi

echo "[3/4] Building and starting (restart: unless-stopped = survives reboots)..."
sudo docker compose up -d --build

echo "[4/4] Done. Local check:"
sleep 3
curl -s -o /dev/null -w "QuickSave on this VPS: HTTP %{http_code}\n" http://127.0.0.1:5000/ || echo "Not up yet - check: sudo docker compose logs"
echo "Next: point your Cloudflare Tunnel or DNS at this machine (see cloudflare/README-CLOUDFLARE.md),"
echo "or open port 5000 in the VPS firewall and use http://<VPS-IP>:5000 as the Backend URL."
echo "Future updates: sh deploy/update.sh"
