@echo off
REM QuickSave - start the named Cloudflare Tunnel (config must exist in %USERPROFILE%\.cloudflared\config.yml)
cloudflared tunnel run quicksave
pause
