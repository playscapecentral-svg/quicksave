---
title: QuickSave
emoji: ⬇️
colorFrom: purple
colorTo: indigo
sdk: docker
app_port: 5000
pinned: false
---

# QuickSave — local multi-platform video downloader & converter

QuickSave is an original, locally-run implementation of the classic
*paste a link → see the formats → pick one → download* flow, plus a file
converter and a small Chrome helper extension. It is **not** affiliated
with any other downloader site; all branding and copy here are original.

Everything runs on your own machine: the only network calls are to the
site whose link you paste, to fetch that video.

## Run it

```bash
cd ~/workspace/savefrom-full
.venv/bin/python server.py
```

Then open <http://127.0.0.1:5000>

Optional: pick another port with `PORT=8000 .venv/bin/python server.py`.

Requirements already vendored in this folder: a Python venv (`.venv`)
with Flask and yt-dlp, plus a system `ffmpeg`/`ffprobe` on your PATH
(used for merging video+audio, MP3 extraction and conversions).

## What you get

| Route | What it is |
|---|---|
| `/` | Downloader for any supported site |
| `/youtube` `/facebook` `/instagram` `/tiktok` `/vimeo` | Same app, platform-specific landing pages |
| `POST /api/resolve` | JSON `{url}` → title, thumbnail, duration, uploader, platform and a cleaned list of formats (id, ext, height, fps, approx. size, video/audio flags) |
| `GET /api/download?url=…&format_id=…` | Downloads one format. Special values: `best_mp4` (best video+audio merged to MP4) and `mp3` (audio extracted to MP3 via ffmpeg). Video-only formats are automatically merged with the best audio. |
| `POST /api/convert` | Multipart upload (`file` + `target` = mp3 / mp4 / webm / mov / mkv / gif), max 200 MB, converted with ffmpeg and returned as a download. GIFs are scaled to 480 px wide at 12 fps. |
| `GET /api/supported` | JSON: how many site extractors the bundled resolver supports, plus highlights/sample |
| `GET /api/health` | Simple liveness check |

**Frontend** (Flask templates + vanilla CSS/JS, no CDN — works offline):
hero URL box, loading state, result card with thumbnail/title/duration,
format buttons grouped into Video and Audio with quality + extension +
approx. size, a drag-and-drop converter section, a supported-platforms
grid fed by the live API, “How it works”, FAQ, and footer. If the page is
opened with `?url=<link>` (the extension does this) the link is prefilled
and resolved automatically.

## Browser extension — QuickSave Helper

`extension/` is a Manifest V3 Chrome extension:

- Adds a **“⬇ Download with QuickSave”** button on YouTube watch pages
  (and a floating button on Facebook / Instagram / TikTok pages). Clicking
  it opens QuickSave with the current page's URL prefilled.
- Popup with a paste-a-link field, a “use current tab” button, and a
  **configurable server URL** (default `http://127.0.0.1:5000`, stored in
  `chrome.storage.sync`).

**Load it unpacked:**

1. Start the QuickSave server (above).
2. In Chrome open `chrome://extensions`, turn on **Developer mode**.
3. Click **Load unpacked** and select the `~/workspace/savefrom-full/extension` folder.
4. Open a YouTube video — the green Download button appears under the title.

## Architecture

```
browser ──paste link──▶ Flask (server.py)
                            ├─ /api/resolve  ─▶ yt-dlp extract_info (no download)
                            ├─ /api/download ─▶ yt-dlp download (+ ffmpeg merge / MP3 extract) ─▶ temp dir ─▶ send_file
                            └─ /api/convert  ─▶ ffmpeg subprocess ─▶ temp dir ─▶ send_file
extension (MV3) ──opens──▶  /?url=<page url>
```

- One temp directory per download/conversion request, removed when the
  response closes. Filenames sent to the browser are sanitised.
- No `shell=True` anywhere — yt-dlp is used through its Python API and
  ffmpeg through argument lists.
- Downloads/conversions are synchronous; very large files can take a
  while (ffmpeg conversions time out at 10 minutes).

## Honest limitations

- **Sites fight back.** YouTube and others may rate-limit, return
  “sign-in to confirm you're not a bot”, or block extraction from
  datacenter IPs. Private, age-gated or login-only posts usually can't be
  resolved without that site's cookies (yt-dlp supports `--cookies`, but
  QuickSave intentionally does not wire cookie files in).
- Which formats exist depends entirely on the source video — e.g. a
  4K source offers more rows than a 360p one, and approx. sizes can be
  missing for some sites.
- No playlists-as-a-whole download: a playlist link resolves to its
  first entry. No scheduling, no history, no accounts — by design.
- The converted file and the download come straight from your machine;
  if you stop the server mid-download, the transfer stops.
- Only download content you own or have permission to save, and respect
  each platform's terms of service.

## Layout

```
savefrom-full/
├── server.py            Flask backend (API + page routes)
├── templates/index.html Single-page frontend
├── static/style.css     Vanilla CSS (no CDN)
├── static/app.js        Vanilla JS wired to the real APIs
├── extension/           QuickSave Helper (Manifest V3)
│   ├── manifest.json
│   ├── content.js       Injects the Download button
│   ├── popup.html / popup.js
│   └── icons/           Original generated icons
└── README.md
```
