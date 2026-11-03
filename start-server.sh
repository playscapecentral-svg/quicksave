#!/bin/sh
# QuickSave - start the server on Mac/Linux
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "First run: creating venv and installing requirements..."
  python3 -m venv .venv
  .venv/bin/pip install yt-dlp flask
fi
exec .venv/bin/python server.py
