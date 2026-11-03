@echo off
REM QuickSave LIVE via Cloudflare Tunnel - one click (Windows)
REM Prothom bar: cloudflare\README-CLOUDFLARE.md onujayi tunnel login/create/route/config kore nao.
REM Prottek bar: GitHub theke latest code pull kore, server + tunnel chalu kore.
cd /d %~dp0
echo [1/3] GitHub theke latest update nicchi...
git pull
echo [2/3] Server chalu hocche (notun window)...
start "QuickSave Server" start-server.bat
timeout /t 5 /nobreak >nul
echo [3/3] Cloudflare Tunnel chalu hocche - ei window khola rakho...
cloudflared tunnel run quicksave
pause
