# QuickSave — Cloudflare e Publish (Step-by-Step, Windows)

Backend (yt-dlp + ffmpeg) Python server e chole — Cloudflare Pages/Workers eta
chalate pare na. Sothik rasta: **Cloudflare Tunnel**. Server tomar PC te thakbe,
Cloudflare setake tomar domain er public HTTPS address e dekhabey.

Dorkari jinish: Windows PC, Cloudflare account (ache), ar account e add kora
ekta domain. Niche `tomardomain.com` lekha jaygay nijer domain bosabe,
ar address hobe `download.tomardomain.com` (subdomain chaile bodlate paro).

---

## Step 0 — Domain check (Cloudflare account e)
1. https://dash.cloudflare.com e login koro.
2. Home page e tomar domain ta dekhle — thik ache, Step 1 e jao.
3. Domain na thakle: "Add a domain" → domain naam → Free plan → Cloudflare
   dui ta nameserver dibe, segulo tomar domain registrar e giye bodle dao.
   Active hote kichu somoy lage (email ashbe "now active").

## Step 1 — PC te ja lagbe install koro
1. **Python 3.10+** — https://www.python.org/downloads/ (install er somoy
   "Add python.exe to PATH" tick dio). Check: `python --version`
2. **ffmpeg** — https://www.gyan.dev/ffmpeg/builds/ theke "ffmpeg-release-essentials.zip"
   download → unzip → vitore `bin` folder ta PATH e add koro. Check: `ffmpeg -version`
3. **cloudflared** — https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/
   theke Windows 64-bit `.msi` install koro. Check: `cloudflared --version`

## Step 2 — QuickSave server chalu koro
1. `savefrom-full.zip` unzip koro (jemon Desktop e).
2. Folder er vitore `start-server.bat` double-click koro.
   Prothom bar venv + yt-dlp + flask auto-install hobe.
3. Window khola rekhe browser e jao: http://127.0.0.1:5000
   — site dekhlei server thik ache. Ei window bondho kora jabe na.

## Step 3 — Cloudflare e login (ekbar)
Notun ekta **CMD** kholo (arekta window) ar chalao:
```
cloudflared tunnel login
```
Browser khulbe → tomar Cloudflare account e login → tomar domain ta select
kore **Authorize** koro. CMD te "You have successfully logged in" dekhbe.

## Step 4 — Tunnel banao
Eki CMD te:
```
cloudflared tunnel create quicksave
```
Output e ekta lomba Tunnel ID ashbe (likhe rakho) ar ekta `.json` file
toiri hobe `%USERPROFILE%\.cloudflared\` folder e.

## Step 5 — DNS route (tomar subdomain → tunnel)
```
cloudflared tunnel route dns quicksave download.tomardomain.com
```
`download.tomardomain.com` er jaygay tomar asol domain bosabe.
"Added CNAME" dekhlei DNS ready.

## Step 6 — Config file sajao
1. Notepad e kholo: `%USERPROFILE%\.cloudflared\config.yml`
   (na thakle notun banao — extension `.yml`, `.txt` jeno na hoy)
2. Vitore ei lekho (ID, path, hostname nijer hisebe):
```yml
tunnel: TUNNEL_ID_EKHANE
credentials-file: C:\Users\TOMAR_NAME\.cloudflared\TUNNEL_ID.json

ingress:
  - hostname: download.tomardomain.com
    service: http://127.0.0.1:5000
  - service: http_status:404
```
Nijer Windows username bosabe `TOMAR_NAME` er jaygay.

## Step 7 — Tunnel chalu koro + LIVE
CMD te:
```
cloudflared tunnel run quicksave
```
"Connection ... registered" (4 ta) dekhlei live.
Browser e jao: **https://download.tomardomain.com** — QuickSave duniya
theke khulche. Link paste kore ekta video diye test kore nio.

## Chalate ja mone rakhte hobe
- Dui ta window khola thakte hobe: server (Step 2) + tunnel (Step 7).
  Jekono ekta bondho = site off. PC off = site off.
- Porer bar: sudhu `start-server.bat` + `cloudflared tunnel run quicksave`.

## Somossa hole
- `cloudflared` command chine na → CMD bondho kore notun kholo (PATH refresh).
- Site 404/1033 error → tunnel window cholche kina dekho; config er
  hostname ar Step 5 er subdomain ek kina milao.
- YouTube "bot" error → browser theke cookies niye yt-dlp chalate hoy;
  server.py te `cookiefile` option ache kina README dekho — proyojon hole
  Maya ke bolo, cookies setup kore dibe.
- Port 5000 busy → onno program port ta dhore ache; PC restart diye try koro.

---

## Quick Tunnel (domain chara, temporary link — test er jonno)
Server chalu rekhe notun CMD te:
```
cloudflared tunnel --url http://127.0.0.1:5000
```
`https://xxxx.trycloudflare.com` address pabe — terminal khola thaka
porjonto live, protibar notun address.
