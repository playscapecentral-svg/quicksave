@echo off
REM QuickSave - start the server on Windows
cd /d %~dp0
if not exist .venv\Scripts\python.exe (
  echo First run: creating venv and installing requirements...
  python -m venv .venv
  .venv\Scripts\pip install yt-dlp flask
)
.venv\Scripts\python server.py
pause
