#!/bin/sh
# QuickSave - update a VPS deployment to the latest GitHub code and restart.
set -e
cd "$(dirname "$0")/.."
git pull
sudo docker compose up -d --build
echo "Updated. QuickSave is running the latest code."
