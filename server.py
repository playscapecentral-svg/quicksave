#!/usr/bin/env python3
"""
QuickSave — a local, multi-platform video downloader.

Original implementation of the classic paste-link -> resolve -> choose
format -> download flow. Powered by yt-dlp for resolution/downloading
and ffmpeg for merging and conversion. All processing happens locally;
no data is sent anywhere except to the source site you paste a link for.
"""
import hashlib
import hmac
import json
import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid

from flask import (
    Flask, Response, jsonify, render_template, request, send_file, abort,
)
from werkzeug.utils import secure_filename

import yt_dlp
from yt_dlp.utils import DownloadError

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 210 * 1024 * 1024  # ~200 MB upload cap + slack


@app.after_request
def _cors(resp):
    # Let the Cloudflare Pages front-end (public/) call this backend cross-origin.
    if request.path.startswith("/api/"):
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return resp

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "5000"))
MAX_UPLOAD_BYTES = 200 * 1024 * 1024

# ------------------------------------------------------------ growth events
# Initiative 1 (arena growth plan): the nine-event taxonomy. Every event is
# logged server-side, POSTed at creation time to the durable Cloudflare D1
# ingest endpoint (a Pages Function), and printed to stdout for debugging
# only. NOTHING is stored on this host's disk: Render's filesystem is
# ephemeral. A failed ingest POST is counted on /api/health, never raised.
BOOT_ID = uuid.uuid4().hex
EVENTS_INGEST_URL = os.environ.get(
    "QS_EVENTS_INGEST_URL", "https://quicksave.pages.dev/api/events")
EVENTS_INGEST_TOKEN = os.environ.get("QS_INGEST_TOKEN", "")
QS_TEST_TOKEN = os.environ.get("QS_TEST_TOKEN", "")

_event_queue = queue.Queue(maxsize=1000)
_ingest_failed = 0
_ingest_failed_lock = threading.Lock()


def _ingest_worker():
    while True:
        payload = _event_queue.get()
        try:
            body = json.dumps(payload).encode()
            headers = {"Content-Type": "application/json"}
            if EVENTS_INGEST_TOKEN:
                headers["X-QS-Ingest"] = EVENTS_INGEST_TOKEN
            ok = False
            for _attempt in range(2):  # 1 try + 1 retry, 2 s timeout each
                try:
                    req = urllib.request.Request(
                        EVENTS_INGEST_URL, data=body, headers=headers,
                        method="POST")
                    with urllib.request.urlopen(req, timeout=2) as resp:
                        ok = 200 <= resp.status < 300
                    if ok:
                        break
                except Exception:
                    ok = False
            if not ok:
                with _ingest_failed_lock:
                    global _ingest_failed
                    _ingest_failed += 1
        except Exception:
            pass
        finally:
            _event_queue.task_done()


threading.Thread(target=_ingest_worker, daemon=True,
                 name="qs-event-ingest").start()


def emit_event(event, request_id=None, **fields):
    """Build one taxonomy event, print it, and queue its ingest POST.

    Fully non-blocking and exception-proof: event plumbing must never
    break or delay a user request.
    """
    try:
        payload = {
            "event": event,
            "event_id": uuid.uuid4().hex,
            "request_id": request_id,
            "ts": time.time(),
            "ts_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "boot_id": BOOT_ID,
        }
        payload.update({k: v for k, v in fields.items() if v is not None})
        try:
            print("QS-EVENT " + json.dumps(payload), flush=True)
        except Exception:
            pass
        try:
            _event_queue.put_nowait(payload)
        except queue.Full:
            with _ingest_failed_lock:
                global _ingest_failed
                _ingest_failed += 1
    except Exception:
        pass


def _request_source():
    """source=user unless the request carries the X-QS-Test header whose
    value matches the QS_TEST_TOKEN secret. The browser never sends it."""
    if QS_TEST_TOKEN:
        hdr = request.headers.get("X-QS-Test", "")
        if hdr and hmac.compare_digest(hdr, QS_TEST_TOKEN):
            src = (request.headers.get("X-QS-Source") or "test").strip().lower()
            return src if src in ("synthetic", "test") else "test"
    return "user"


_SLUG_RE = re.compile(r"^/[a-z0-9\-/]*$")
_HOST_RE = re.compile(r"^[a-z0-9.\-]{1,120}$")


def _parse_attribution(container):
    """Validate/truncate the browser attribution fields (plan Init. 1.4)."""
    def _get(key):
        try:
            return (container.get(key) or "")
        except Exception:
            return ""
    session_id = str(_get("session_id"))[:64] or None
    slug = str(_get("page_slug"))[:120]
    if not _SLUG_RE.match(slug):
        slug = None
    ref = str(_get("referrer_host"))[:120].lower()
    if not _HOST_RE.match(ref):
        ref = None
    return {"session_id": session_id, "page_slug": slug, "referrer_host": ref}


_YT_ID_RES = (
    re.compile(r"[?&]v=([A-Za-z0-9_\-]{6,20})"),
    re.compile(r"youtu\.be/([A-Za-z0-9_\-]{6,20})"),
    re.compile(r"/(?:shorts|embed|live)/([A-Za-z0-9_\-]{6,20})"),
)


def _video_id_hash(url):
    """Truncated SHA-256 of a YouTube video ID (12 hex chars) — never the URL."""
    if "youtube" not in url and "youtu.be" not in url:
        return None
    for rx in _YT_ID_RES:
        m = rx.search(url)
        if m:
            return hashlib.sha256(m.group(1).encode()).hexdigest()[:12]
    return None


def _url_host(url):
    m = re.match(r"^https?://([^/]+)", url or "")
    return m.group(1).lower() if m else None


def _resolve_reason(msg):
    m = (msg or "").lower()
    if "sign in to confirm" in m or "not a bot" in m:
        return "bot_wall"
    if "timed out" in m or "timeout" in m:
        return "timeout"
    if any(k in m for k in ("private", "unavailable", "age-restricted",
                            "age restricted", "login required", "sign in to",
                            "members-only", "members only", "removed",
                            "account has been terminated")):
        return "private_or_unsupported"
    if any(k in m for k in ("urlopen error", "connection", "network",
                            "name or service", "temporary failure",
                            "remote end closed", "eof occurred")):
        return "network_error"
    return "extractor_error"


def _download_reason(msg, merge_needed):
    m = (msg or "").lower()
    if merge_needed and any(k in m for k in ("ffmpeg", "merge", "postprocess")):
        return "merge_error"
    return "upstream_error"


def _scrub(text, url):
    return (text or "").replace(url, "[url]")[:200]


def _size_bucket(n):
    mb = 1024 * 1024
    if n is None:
        return None
    if n < mb:
        return "<1MB"
    if n < 10 * mb:
        return "1-10MB"
    if n < 50 * mb:
        return "10-50MB"
    if n < 100 * mb:
        return "50-100MB"
    if n <= 200 * mb:
        return "100-200MB"
    return ">200MB"


def _file_response(path, filename, terminal):
    """Stream a finished file; terminal(delivered, reason) fires exactly
    once — delivered only if every byte was sent."""
    size = os.path.getsize(path)
    ext = os.path.splitext(path)[1].lstrip(".").lower()
    ctype = {"mp4": "video/mp4", "webm": "video/webm", "m4a": "audio/mp4",
             "mp3": "audio/mpeg", "opus": "audio/ogg", "mkv": "video/x-matroska",
             "mov": "video/quicktime", "gif": "image/gif"}.get(
                 ext, "application/octet-stream")
    state = {"done": False}

    def gen():
        sent = 0
        try:
            with open(path, "rb") as fh:
                while True:
                    chunk = fh.read(256 * 1024)
                    if not chunk:
                        break
                    sent += len(chunk)
                    yield chunk
            terminal(sent >= size, None if sent >= size else "upstream_error")
        except GeneratorExit:
            terminal(False, "client_disconnect")
            raise
        except Exception:
            terminal(False, "upstream_error")
        finally:
            state["done"] = True

    resp = Response(gen(), status=200, mimetype=ctype)
    resp.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    resp.headers["Content-Length"] = str(size)
    return resp


# ------------------------------------------------------------ yt-dlp helpers
_COOKIE_FILE = None


def _cookiefile():
    """Materialise Netscape-format cookies from the YTDLP_COOKIES env var.

    Set YTDLP_COOKIES on the host (e.g. Render env vars) to the contents of
    a cookies.txt exported from a logged-in browser. Never commit cookies
    to the repo. Returns the temp file path, or None when unset.
    """
    global _COOKIE_FILE
    raw = os.environ.get("YTDLP_COOKIES", "").strip()
    if not raw:
        return None
    if _COOKIE_FILE is None:
        fd, path = tempfile.mkstemp(prefix="quicksave-cookies-", suffix=".txt")
        with os.fdopen(fd, "w") as fh:
            fh.write(raw)
        _COOKIE_FILE = path
    return _COOKIE_FILE


# yt-dlp needs a JS runtime to solve YouTube's "n" challenge for the
# cookie-supporting web clients; without one those clients return only
# storyboard thumbnails. Prefer deno (installed in the Docker image),
# fall back to node.
_JS_RUNTIMES = {}
for _rt in ("deno", "node"):
    _rt_path = shutil.which(_rt)
    if _rt_path:
        _JS_RUNTIMES[_rt] = {"path": _rt_path}
        break

_YT_CLIENT_SETS = (
    # Cookie-capable clients first — android/ios ignore cookies entirely.
    {"youtube": {"player_client": ["web_safari"]}},
    {"youtube": {"player_client": ["web"]}},
    {"youtube": {"player_client": ["android", "ios"]}},
    {"youtube": {"player_client": ["tv_embedded", "android_vr"]}},
)

_BOT_MARKERS = ("sign in to confirm", "not a bot", "use --cookies",
                "login required", "cookies are needed", "http error 403",
                # Authenticated web-client extractions can return zero usable
                # formats (PO-token/SABR gating) — other clients still work.
                "requested format is not available", "no video formats found",
                "no formats available", "missing a url",
                # The tv client rejects some exported cookie sets this way.
                "page needs to be reloaded")


def _looks_like_bot_wall(exc):
    msg = str(exc).lower()
    return any(marker in msg for marker in _BOT_MARKERS)


def _ydl_attempts(base_opts):
    """Opts dicts to try in order: as-is (+cookies), then alternate
    YouTube player clients, which often pass where the default web
    client is bot-walled on datacenter IPs."""
    attempts = []
    cf = _cookiefile()

    def _with_common(opts):
        if cf:
            opts["cookiefile"] = cf
        if _JS_RUNTIMES:
            opts["js_runtimes"] = _JS_RUNTIMES
        return opts

    attempts.append(_with_common(dict(base_opts,
        extractor_args={"youtube": {"player_client": ["web_embedded"]}})))
    attempts.append(_with_common(dict(base_opts)))
    for clients in _YT_CLIENT_SETS:
        opts = dict(base_opts)
        opts["extractor_args"] = clients
        attempts.append(_with_common(opts))
    return attempts


import copy
import threading

_INFO_CACHE = {}
_INFO_CACHE_LOCK = threading.Lock()
_INFO_TTL = 3600  # googlevideo URLs live ~6h; 1h is safely inside that


def _cache_get(url):
    with _INFO_CACHE_LOCK:
        hit = _INFO_CACHE.get(url)
        if hit and time.time() - hit[0] < _INFO_TTL:
            return copy.deepcopy(hit[1])
    return None


def _cache_put(url, info):
    if not isinstance(info, dict) or info.get("_type") == "playlist":
        return
    with _INFO_CACHE_LOCK:
        _INFO_CACHE[url] = (time.time(), copy.deepcopy(info))
        if len(_INFO_CACHE) > 50:  # keep it small: drop the oldest entry
            _INFO_CACHE.pop(min(_INFO_CACHE, key=lambda k: _INFO_CACHE[k][0]))


def _ydl_attempts_nocookie(base_opts):
    """Same rotation but WITHOUT the cookie file. If the stored login
    session gets blocked for this server's IP, the PO-token provider
    (bgutil, running on localhost:4416 in the Docker image) can still
    pass the bot check for the web clients — no account involved."""
    attempts = []
    first = dict(base_opts)
    if _JS_RUNTIMES:
        first["js_runtimes"] = _JS_RUNTIMES
    attempts.append(first)
    for clients in _YT_CLIENT_SETS:
        opts = dict(base_opts)
        opts["extractor_args"] = clients
        if _JS_RUNTIMES:
            opts["js_runtimes"] = _JS_RUNTIMES
        attempts.append(opts)
    return attempts


def _extract(url, base_opts, download=False, between_attempts=None):
    """extract_info with bot-wall retries across player clients.

    Downloads first try the resolve cache: re-extracting a YouTube page
    (JS challenge solving on a small CPU) costs 10-20s before a single
    byte moves, while the cached info lets the download start at once.
    Re-raises the first error immediately when it is not a bot wall.
    """
    if download:
        cached = _cache_get(url)
        if cached is not None:
            # One shot only: if the cached URLs were rejected (403 etc.),
            # fall through to a fresh extraction instead of failing.
            try:
                opts = _ydl_attempts(base_opts)[0]
                with yt_dlp.YoutubeDL(opts) as ydl:
                    return ydl.process_ie_result(copy.deepcopy(cached),
                                                 download=True)
            except DownloadError:
                if between_attempts is not None:
                    between_attempts()
    last_exc = None
    for i, opts in enumerate(_ydl_attempts(base_opts)):
        if i and between_attempts is not None:
            between_attempts()
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=download)
                if not download:
                    _cache_put(url, info)
                return info
        except DownloadError as e:
            last_exc = e
            if not _looks_like_bot_wall(e):
                raise
    if _cookiefile():
        # Every cookie attempt hit the bot wall — the login session is
        # blocked from this IP. Retry without cookies (PO-token route).
        for i, opts in enumerate(_ydl_attempts_nocookie(base_opts)):
            if between_attempts is not None:
                between_attempts()
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=download)
                    if not download:
                        _cache_put(url, info)
                    return info
            except DownloadError as e:
                last_exc = e
                if not _looks_like_bot_wall(e):
                    raise
    raise last_exc

PLATFORMS = {
    "home": {
        "slug": "",
        "name": "Any site",
        "heading": "Download video from almost any site",
        "hint": "Paste a link from YouTube, Facebook, Instagram, TikTok, Vimeo and 1,000+ other sites.",
        "placeholder": "Paste a video link here — e.g. https://www.youtube.com/watch?v=…",
    },
    "youtube": {
        "slug": "youtube",
        "name": "YouTube",
        "heading": "YouTube Video Downloader",
        "hint": "Paste any YouTube video or Shorts link, pick a quality, and save it as MP4 or MP3.",
        "placeholder": "Paste a YouTube link — e.g. https://www.youtube.com/watch?v=…",
    },
    "facebook": {
        "slug": "facebook",
        "name": "Facebook",
        "heading": "Facebook Video Downloader",
        "hint": "Paste a public Facebook video or Reel link and save it in the quality you want.",
        "placeholder": "Paste a Facebook video link…",
    },
    "instagram": {
        "slug": "instagram",
        "name": "Instagram",
        "heading": "Instagram Video Downloader",
        "hint": "Paste a public Instagram Reel or video link to save it locally.",
        "placeholder": "Paste an Instagram Reel / video link…",
    },
    "tiktok": {
        "slug": "tiktok",
        "name": "TikTok",
        "heading": "TikTok Video Downloader",
        "hint": "Paste a TikTok link and download the video, or just its audio as MP3.",
        "placeholder": "Paste a TikTok link…",
    },
    "vimeo": {
        "slug": "vimeo",
        "name": "Vimeo",
        "heading": "Vimeo Video Downloader",
        "hint": "Paste a Vimeo link and choose from every quality the video offers.",
        "placeholder": "Paste a Vimeo link…",
    },
}


def _safe_name(title, ext, fallback="quicksave-download"):
    name = re.sub(r"[^\w\s.-]", "", str(title or "")).strip()
    name = re.sub(r"\s+", " ", name)[:80].strip() or fallback
    return f"{name}.{ext}"


def _clean_formats(info):
    formats = []
    for f in info.get("formats") or []:
        fid = f.get("format_id")
        ext = f.get("ext") or ""
        if not fid or ext in ("mhtml", "json", "vtt", "srv3"):
            continue
        note = (f.get("format_note") or "").lower()
        if "storyboard" in note or fid.startswith("sb"):
            continue
        # Codec fields can be None (unknown), notably for direct-media /
        # Generic results — infer from *_ext fields / container in that case.
        audio_exts = {"mp3", "m4a", "opus", "ogg", "oga", "wav", "flac", "aac"}
        vcodec, acodec = f.get("vcodec"), f.get("acodec")
        if vcodec is not None:
            has_video = vcodec != "none"
        elif f.get("video_ext"):
            has_video = f["video_ext"] != "none"
        else:
            has_video = ext not in audio_exts
        if acodec is not None:
            has_audio = acodec != "none"
        elif f.get("audio_ext"):
            has_audio = f["audio_ext"] != "none"
        else:
            has_audio = ext in audio_exts or has_video
        if not has_video and not has_audio:
            continue
        height = f.get("height")
        formats.append({
            "format_id": str(fid),
            "ext": ext,
            "height": height,
            "resolution": f.get("resolution") or (f"{height}p" if height else ("video" if has_video else "audio only")),
            "fps": f.get("fps"),
            "filesize_approx": f.get("filesize") or f.get("filesize_approx"),
            "has_video": has_video,
            "has_audio": has_audio,
            "note": f.get("format_note") or "",
            "tbr": f.get("tbr"),
        })
    # Video first (tallest first), then audio (highest bitrate first)
    video = sorted([x for x in formats if x["has_video"]],
                   key=lambda x: (x["height"] or 0, x["tbr"] or 0), reverse=True)
    audio = sorted([x for x in formats if not x["has_video"]],
                   key=lambda x: (x["tbr"] or 0), reverse=True)
    return video + audio



import urllib.request
import urllib.error


def _relay_format(url, format_id, ev_ctx=None):
    """Stream a single-file format straight through to the browser.

    The old flow downloaded the whole file to the server (plus a merge)
    before the browser saw a single byte — that is why downloads "took
    forever to start". When the picked format is one self-contained
    http(s) stream (progressive MP4, audio-only, ...), relay its bytes
    chunk by chunk instead: the browser's download starts in ~1s.
    Returns a Flask Response, or None when relaying does not apply /
    the upstream refuses (caller falls back to the classic flow).
    """
    if format_id in ("mp3", "best_mp4"):
        return None
    info = _cache_get(url)
    if info is None:
        try:
            info = _extract(url, {"quiet": True, "no_warnings": True,
                                  "skip_download": True, "socket_timeout": 45,
                                  "retries": 1, "noplaylist": True},
                            download=False)
        except Exception:
            return None
    fmt = None
    for f in info.get("formats") or []:
        if str(f.get("format_id")) == format_id:
            fmt = f
            break
    if not fmt:
        return None
    direct = fmt.get("url") or ""
    proto = fmt.get("protocol") or ""
    if not direct.startswith("http") or proto not in ("https", "http"):
        return None
    vcodec, acodec = fmt.get("vcodec"), fmt.get("acodec")
    if vcodec == "none" and acodec == "none":
        return None
    if vcodec == "none" or acodec == "none":
        # Video-only needs the audio merge; audio-only DASH URLs throttle
        # a plain relay (measured: 3.9 MB in 300s) — yt-dlp's chunked
        # downloader handles both better. Relay only combined streams.
        return None
    headers = dict(fmt.get("http_headers") or {})
    headers.setdefault("User-Agent", "Mozilla/5.0")
    req = urllib.request.Request(direct, headers=headers)
    try:
        upstream = urllib.request.urlopen(req, timeout=30)
    except Exception:
        return None
    if upstream.status != 200:
        upstream.close()
        return None
    ext = fmt.get("ext") or "mp4"
    filename = _safe_name(info.get("title"), ext)
    length = upstream.headers.get("Content-Length")
    ctype = {"mp4": "video/mp4", "webm": "video/webm", "m4a": "audio/mp4",
             "mp3": "audio/mpeg", "opus": "audio/ogg"}.get(ext,
                                                           "application/octet-stream")

    expected = int(length) if length and str(length).isdigit() else None

    def _terminal(delivered, reason):
        if ev_ctx is None:
            return
        if delivered:
            emit_event("download_delivered", ev_ctx["request_id"], **ev_ctx["fields"])
        else:
            emit_event("download_failed", ev_ctx["request_id"], reason=reason,
                       **ev_ctx["fields"])

    def _gen():
        sent = 0
        try:
            while True:
                chunk = upstream.read(256 * 1024)
                if not chunk:
                    break
                sent += len(chunk)
                yield chunk
            ok = expected is None or sent >= expected
            _terminal(ok, None if ok else "upstream_error")
        except GeneratorExit:
            _terminal(False, "client_disconnect")
            raise
        except Exception:
            _terminal(False, "upstream_error")
        finally:
            upstream.close()

    resp = Response(_gen(), status=200, mimetype=ctype)
    resp.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    if length:
        resp.headers["Content-Length"] = length
    return resp

# ---------------------------------------------------------------- pages
@app.route("/")
def index():
    return render_template("index.html", platform=PLATFORMS["home"], platforms=PLATFORMS)


@app.route("/<slug>")
def platform_page(slug):
    platform = PLATFORMS.get(slug)
    if platform is None:
        abort(404)
    return render_template("index.html", platform=platform, platforms=PLATFORMS)


# ---------------------------------------------------------------- api
@app.get("/api/supported")
def api_supported():
    try:
        from yt_dlp.extractor import gen_extractor_classes
        names = sorted({c.IE_NAME for c in gen_extractor_classes()})
    except Exception:
        names = []
    wanted = ["youtube", "facebook", "instagram", "tiktok", "vimeo",
              "dailymotion", "reddit", "twitter", "soundcloud", "twitch",
              "pinterest", "tumblr"]
    by_lower = {n.lower(): n for n in names}
    highlights = [by_lower[w] for w in wanted if w in by_lower]
    return jsonify({
        "count": len(names),
        "highlights": highlights,
        "sample": names[:120],
    })


@app.post("/api/resolve")
def api_resolve():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url or not re.match(r"^https?://", url):
        return jsonify({"error": "Please paste a valid http(s) video link."}), 400
    request_id = uuid.uuid4().hex
    source = _request_source()
    fields = {"source": source, "url_host": _url_host(url),
              "video_id_hash": _video_id_hash(url)}
    fields.update(_parse_attribution(data))
    emit_event("resolve_started", request_id, **fields)
    t0 = time.time()
    opts = {
        "quiet": True, "no_warnings": True, "skip_download": True,
        "socket_timeout": 45, "retries": 1, "noplaylist": True,
    }
    try:
        info = _extract(url, opts, download=False)
    except DownloadError as e:
        msg = re.sub(r"\x1b\[[0-9;]*m", "", str(e)).strip().splitlines()
        first = msg[0] if msg else "Could not resolve that link."
        emit_event("resolve_failed", request_id, reason=_resolve_reason(first),
                   duration_sec=round(time.time() - t0, 3),
                   detail=_scrub(first, url), **fields)
        return jsonify({"error": first[:300]}), 422
    except Exception as e:  # pragma: no cover
        emit_event("resolve_failed", request_id, reason="extractor_error",
                   duration_sec=round(time.time() - t0, 3),
                   detail=_scrub(str(e), url), **fields)
        return jsonify({"error": f"Resolver error: {e}"}), 500
    if info is None:
        emit_event("resolve_failed", request_id, reason="extractor_error",
                   duration_sec=round(time.time() - t0, 3), **fields)
        return jsonify({"error": "No video found at that link."}), 422
    if info.get("_type") == "playlist":
        entries = [e for e in (info.get("entries") or []) if e]
        if not entries:
            return jsonify({"error": "That playlist looks empty."}), 422
        info = entries[0]
    formats = _clean_formats(info)
    emit_event("resolve_succeeded", request_id,
               duration_sec=round(time.time() - t0, 3),
               platform=info.get("extractor_key") or info.get("extractor"),
               **fields)
    return jsonify({
        "request_id": request_id,
        "id": info.get("id"),
        "title": info.get("title"),
        "thumbnail": info.get("thumbnail"),
        "duration": info.get("duration"),
        "uploader": info.get("uploader") or info.get("channel"),
        "platform": info.get("extractor_key") or info.get("extractor"),
        "webpage_url": info.get("webpage_url") or url,
        "formats": formats,
    })


@app.get("/api/download")
def api_download():
    url = (request.args.get("url") or "").strip()
    format_id = (request.args.get("format_id") or "best_mp4").strip()
    if not url or not re.match(r"^https?://", url):
        return jsonify({"error": "Missing or invalid url."}), 400
    if not re.match(r"^[\w.\-+]+$", format_id):
        return jsonify({"error": "Invalid format_id."}), 400

    request_id = uuid.uuid4().hex
    fields = {"source": _request_source(), "url_host": _url_host(url),
              "video_id_hash": _video_id_hash(url), "format_id": format_id}
    fields.update(_parse_attribution(request.args))
    # Best-effort format facts (for the merge flag / height) from the cache.
    merge_needed = format_id == "best_mp4"
    cached = _cache_get(url)
    if cached:
        for f in cached.get("formats") or []:
            if str(f.get("format_id")) == format_id:
                if f.get("height") is not None:
                    fields["height"] = f.get("height")
                vc, ac = f.get("vcodec"), f.get("acodec")
                if vc not in (None, "none") and ac in (None, "none"):
                    merge_needed = True
                fields["platform"] = (cached.get("extractor_key")
                                      or cached.get("extractor"))
                break
    fields["merge"] = merge_needed
    emit_event("download_requested", request_id, **fields)

    relay = _relay_format(url, format_id,
                          ev_ctx={"request_id": request_id, "fields": fields})
    if relay is not None:
        return relay

    tmpdir = tempfile.mkdtemp(prefix="quicksave-dl-")
    opts = {
        "quiet": True, "no_warnings": True, "socket_timeout": 30,
        "retries": 2, "noplaylist": True,
        "concurrent_fragment_downloads": 8,
        "http_chunk_size": 10 * 1024 * 1024,
        "outtmpl": os.path.join(tmpdir, "%(title).80s.%(ext)s"),
        "restrictfilenames": True,
    }
    if format_id == "mp3":
        opts["format"] = "bestaudio/best"
        opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]
    elif format_id == "best_mp4":
        opts["format"] = ("bestvideo[ext=mp4]+bestaudio[ext=m4a]/"
                          "bestvideo+bestaudio/best")
        opts["merge_output_format"] = "mp4"
    else:
        # Progressive formats play as-is; video-only formats get audio merged.
        opts["format"] = f"{format_id}+bestaudio/{format_id}/best"
        opts["merge_output_format"] = "mp4"
    def _clean_tmp():
        for name in os.listdir(tmpdir):
            p = os.path.join(tmpdir, name)
            if os.path.isfile(p):
                os.unlink(p)

    try:
        info = _extract(url, opts, download=True, between_attempts=_clean_tmp)
    except DownloadError as e:
        shutil.rmtree(tmpdir, ignore_errors=True)
        msg = re.sub(r"\x1b\[[0-9;]*m", "", str(e)).strip().splitlines()
        first = msg[0] if msg else "Download failed."
        emit_event("download_failed", request_id,
                   reason=_download_reason(first, merge_needed),
                   detail=_scrub(first, url), **fields)
        return jsonify({"error": first[:300]}), 422
    except Exception as e:
        shutil.rmtree(tmpdir, ignore_errors=True)
        emit_event("download_failed", request_id, reason="upstream_error",
                   detail=_scrub(str(e), url), **fields)
        return jsonify({"error": f"Download error: {e}"}), 500

    files = [os.path.join(tmpdir, f) for f in os.listdir(tmpdir)
             if not f.endswith((".part", ".ytdl", ".webp", ".jpg", ".png"))]
    files = [f for f in files if os.path.isfile(f)]
    if not files:
        shutil.rmtree(tmpdir, ignore_errors=True)
        emit_event("download_failed", request_id, reason="upstream_error",
                   detail="Download produced no file.", **fields)
        return jsonify({"error": "Download produced no file."}), 500
    path = max(files, key=os.path.getsize)
    ext = os.path.splitext(path)[1].lstrip(".") or "mp4"
    title = (info or {}).get("title") if isinstance(info, dict) else None
    filename = _safe_name(title, ext)
    fields["platform"] = fields.get("platform") or (
        (info or {}).get("extractor_key") or (info or {}).get("extractor")
        if isinstance(info, dict) else None)

    def _terminal(delivered, reason):
        if delivered:
            emit_event("download_delivered", request_id, **fields)
        else:
            emit_event("download_failed", request_id, reason=reason, **fields)

    response = _file_response(path, filename, _terminal)

    @response.call_on_close
    def _cleanup():
        shutil.rmtree(tmpdir, ignore_errors=True)

    return response


CONVERT_TARGETS = ("mp3", "mp4", "webm", "mov", "mkv", "gif")


def _ffmpeg_convert(src, dst, target):
    if target == "mp3":
        cmd = ["ffmpeg", "-y", "-i", src, "-vn", "-c:a", "libmp3lame", "-q:a", "2", dst]
    elif target == "gif":
        cmd = ["ffmpeg", "-y", "-i", src,
               "-vf", "fps=12,scale=480:-1:flags=lanczos", "-loop", "0", dst]
    elif target == "webm":
        cmd = ["ffmpeg", "-y", "-i", src, "-c:v", "libvpx-vp9", "-deadline", "realtime",
               "-cpu-used", "4", "-b:v", "1M", "-c:a", "libopus", dst]
    elif target in ("mp4", "mov"):
        cmd = ["ffmpeg", "-y", "-i", src, "-c:v", "libx264", "-pix_fmt", "yuv420p",
               "-preset", "veryfast", "-c:a", "aac", "-b:a", "160k", dst]
    else:  # mkv
        cmd = ["ffmpeg", "-y", "-i", src, "-c:v", "libx264", "-pix_fmt", "yuv420p",
               "-preset", "veryfast", "-c:a", "aac", "-b:a", "160k", dst]
    # Audio-only inputs have no video stream; -c:v would fail in ffmpeg.
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=codec_type", "-of", "csv=p=0", src],
        capture_output=True, text=True, timeout=30)
    if target in ("mp4", "mov", "mkv", "webm") and "video" not in (probe.stdout or ""):
        audio_cmd = {
            "mp4": ["ffmpeg", "-y", "-i", src, "-c:a", "aac", "-b:a", "160k", dst],
            "mov": ["ffmpeg", "-y", "-i", src, "-c:a", "aac", "-b:a", "160k", dst],
            "mkv": ["ffmpeg", "-y", "-i", src, "-c:a", "aac", "-b:a", "160k", dst],
            "webm": ["ffmpeg", "-y", "-i", src, "-c:a", "libopus", dst],
        }[target]
        cmd = audio_cmd
    return subprocess.run(cmd, capture_output=True, text=True, timeout=600)


@app.post("/api/convert")
def api_convert():
    upload = request.files.get("file")
    target = (request.form.get("target") or "").strip().lower()
    request_id = uuid.uuid4().hex
    in_ext = ""
    if upload is not None and upload.filename:
        in_ext = os.path.splitext(upload.filename)[1].lstrip(".").lower()[:10]
    fields = {"source": _request_source(),
              "input_format": in_ext or None, "output_format": target or None,
              "size_bucket": _size_bucket(request.content_length)}
    fields.update(_parse_attribution(request.form))
    emit_event("convert_started", request_id, **fields)

    def _fail(reason, msg, status):
        emit_event("convert_failed", request_id, reason=reason, **fields)
        return jsonify({"error": msg}), status

    if target not in CONVERT_TARGETS:
        return _fail("unsupported_format",
                     f"target must be one of: {', '.join(CONVERT_TARGETS)}", 400)
    if upload is None or not upload.filename:
        return _fail("unsupported_format",
                     "No file uploaded (field name: file).", 400)
    if request.content_length and request.content_length > MAX_UPLOAD_BYTES + 1024 * 1024:
        return _fail("too_large", "File too large — 200 MB maximum.", 413)

    tmpdir = tempfile.mkdtemp(prefix="quicksave-cv-")
    try:
        safe = secure_filename(upload.filename) or "upload.bin"
        src = os.path.join(tmpdir, safe)
        upload.save(src)
        if os.path.getsize(src) > MAX_UPLOAD_BYTES:
            shutil.rmtree(tmpdir, ignore_errors=True)
            return _fail("too_large", "File too large — 200 MB maximum.", 413)
        stem = os.path.splitext(safe)[0] or "converted"
        dst = os.path.join(tmpdir, f"{stem}.{target}")
        if os.path.abspath(src) == os.path.abspath(dst):
            dst = os.path.join(tmpdir, f"{stem}-converted.{target}")
        proc = _ffmpeg_convert(src, dst, target)
        if proc.returncode != 0 or not os.path.exists(dst) or os.path.getsize(dst) == 0:
            tail = (proc.stderr or "").strip().splitlines()[-3:]
            shutil.rmtree(tmpdir, ignore_errors=True)
            return _fail("ffmpeg_error",
                         "Conversion failed: " + " ".join(tail)[:300], 422)

        def _terminal(delivered, reason):
            if delivered:
                emit_event("convert_delivered", request_id, **fields)
            else:
                emit_event("convert_failed", request_id,
                           reason=reason or "client_disconnect", **fields)

        response = _file_response(dst, f"{stem}.{target}", _terminal)

        @response.call_on_close
        def _cleanup():
            shutil.rmtree(tmpdir, ignore_errors=True)

        return response
    except subprocess.TimeoutExpired:
        shutil.rmtree(tmpdir, ignore_errors=True)
        return _fail("timeout", "Conversion timed out (10 min limit).", 504)
    except Exception:
        # If we already returned a response above, exceptions from send_file
        # streaming are handled by Flask; only clean up on setup errors.
        if not os.path.exists(tmpdir):
            raise
        raise


# ------------------------------------------- TEMPORARY loader.to probe
# One-shot Render-side confirmation for the loader.to fallback build:
# does the loader.to v2 flow (start -> progress -> media URL) work from
# THIS server's IP? Removed in the same change that ships the fallback.
# Guarded by X-QS-Test + QS_TEST_TOKEN when that secret is set; otherwise
# by a one-time token — only its SHA-256 is stored here, never the token.
import urllib.parse

_PROBE_TOKEN_SHA256 = \
    "158bb3586f8ddedc82ce3a432367b51306a9b1a065f105677ff166ef09d477f9"
_PROBE_UA = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/130.0.0.0 Safari/537.36"),
    "Accept": "application/json,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://en.loader.to/",
}
_PROBE_LOADER_KEY = "dfcb6d76f2f6a9894gjkege8a4ab232222"  # loader frontend key


def _probe_authorized():
    if QS_TEST_TOKEN:
        hdr = request.headers.get("X-QS-Test", "")
        if hdr and hmac.compare_digest(hdr, QS_TEST_TOKEN):
            return True
    tok = request.headers.get("X-QS-Probe", "")
    if tok:
        digest = hashlib.sha256(tok.encode()).hexdigest()
        if hmac.compare_digest(digest, _PROBE_TOKEN_SHA256):
            return True
    return False


def _probe_get_json(url, timeout):
    req = urllib.request.Request(url, headers=_PROBE_UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8", "replace"))


@app.post("/api/probe/loader")
def api_probe_loader():
    if not _probe_authorized():
        abort(404)
    out = {"ok": False, "steps": {}}
    t_all = time.time()
    video = "https://www.youtube.com/watch?v=jNQXAC9IVRw"
    host = "p.savenow.to"
    t0 = time.time()
    try:
        req = urllib.request.Request(f"https://{host}/api/health",
                                     headers=_PROBE_UA)
        with urllib.request.urlopen(req, timeout=15) as resp:
            out["steps"]["health"] = {"status": resp.status,
                                      "sec": round(time.time() - t0, 2)}
            if resp.status != 200:
                host = "p.lbserver.xyz"
    except Exception as e:
        out["steps"]["health"] = {"error": str(e)[:200],
                                  "sec": round(time.time() - t0, 2)}
        host = "p.lbserver.xyz"
    out["host"] = host
    t0 = time.time()
    jid, dl = None, ""
    try:
        q = urllib.parse.urlencode({"format": "720", "url": video,
                                    "apikey": _PROBE_LOADER_KEY})
        status, j = _probe_get_json(f"https://{host}/api/v2/download?{q}", 40)
        jid = j.get("id")
        dl = j.get("download_url") or ""
        out["steps"]["start"] = {
            "status": status, "sec": round(time.time() - t0, 2), "id": jid,
            "title": (j.get("info") or {}).get("title"),
            "success": j.get("success")}
    except Exception as e:
        out["steps"]["start"] = {"error": str(e)[:200],
                                 "sec": round(time.time() - t0, 2)}
        out["total_sec"] = round(time.time() - t_all, 2)
        return jsonify(out)
    t0 = time.time()
    polls, last = 0, {}
    while jid and not dl and time.time() - t0 < 240:
        time.sleep(5)
        polls += 1
        try:
            _, pj = _probe_get_json(
                f"https://{host}/api/progress?id={urllib.parse.quote(jid)}",
                30)
            last = pj
            dl = pj.get("download_url") or dl
            if pj.get("success") in (1, True) and dl:
                break
        except Exception as e:
            last = {"error": str(e)[:200]}
    out["steps"]["progress"] = {"polls": polls,
                                "sec": round(time.time() - t0, 2),
                                "progress": last.get("progress"),
                                "success": last.get("success"),
                                "text": last.get("text"),
                                "error": last.get("error")}
    out["download_url_host"] = _url_host(dl) if dl else None
    if dl:
        t0 = time.time()
        try:
            h = dict(_PROBE_UA)
            h["Range"] = "bytes=0-2047"
            req = urllib.request.Request(dl, headers=h)
            with urllib.request.urlopen(req, timeout=25) as resp:
                chunk = resp.read(4096)
                out["steps"]["range"] = {
                    "status": resp.status,
                    "content_type": resp.headers.get("Content-Type"),
                    "bytes_read": len(chunk),
                    "sec": round(time.time() - t0, 2)}
                ctype = resp.headers.get("Content-Type") or ""
                out["ok"] = bool(resp.status in (200, 206) and chunk
                                 and ("video" in ctype or "audio" in ctype
                                      or "octet-stream" in ctype))
        except Exception as e:
            out["steps"]["range"] = {"error": str(e)[:200]}
    out["total_sec"] = round(time.time() - t_all, 2)
    return jsonify(out)


@app.get("/api/health")
def api_health():
    with _ingest_failed_lock:
        failed = _ingest_failed
    return jsonify({"ok": True, "app": "QuickSave", "time": int(time.time()),
                    "boot_id": BOOT_ID, "event_ingest_failed": failed})


if __name__ == "__main__":
    app.run(host=HOST, port=PORT, threaded=True)
