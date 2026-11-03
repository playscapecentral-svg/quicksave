#!/bin/sh
# QuickSave - start the named Cloudflare Tunnel (config must exist in ~/.cloudflared/config.yml)
exec cloudflared tunnel run quicksave
