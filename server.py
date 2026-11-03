#!/usr/bin/env python3
"""
QuickSave — a local, multi-platform video downloader.

Original implementation of the classic paste-link -> resolve -> choose
format -> download flow. Powered by yt-dlp for resolution/downloading
and ffmpeg for merging and conversion. All processing happens locally;
no data is sent anywhere except to the source site you paste a link for.
"""
import os
import re
import shutil
import subprocess
import tempfile
import time

from flask import (
    Flask, jsonify, render_template, request, send_file, abort,
)
from werkzeug.utils import secure_filename

import yt_dlp
from yt_dlp.utils import DownloadError

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 210 * 1024 * 1024  # ~200 MB upload cap + slack

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "5000"))
MAX_UPLOAD_BYTES = 200 * 1024 * 1024

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
    opts = {
        "quiet": True, "no_warnings": True, "skip_download": True,
        "socket_timeout": 45, "retries": 1, "noplaylist": True,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except DownloadError as e:
        msg = re.sub(r"\x1b\[[0-9;]*m", "", str(e)).strip().splitlines()
        return jsonify({"error": (msg[0] if msg else "Could not resolve that link.")[:300]}), 422
    except Exception as e:  # pragma: no cover
        return jsonify({"error": f"Resolver error: {e}"}), 500
    if info is None:
        return jsonify({"error": "No video found at that link."}), 422
    if info.get("_type") == "playlist":
        entries = [e for e in (info.get("entries") or []) if e]
        if not entries:
            return jsonify({"error": "That playlist looks empty."}), 422
        info = entries[0]
    formats = _clean_formats(info)
    return jsonify({
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

    tmpdir = tempfile.mkdtemp(prefix="quicksave-dl-")
    opts = {
        "quiet": True, "no_warnings": True, "socket_timeout": 30,
        "retries": 2, "noplaylist": True,
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
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except DownloadError as e:
        shutil.rmtree(tmpdir, ignore_errors=True)
        msg = re.sub(r"\x1b\[[0-9;]*m", "", str(e)).strip().splitlines()
        return jsonify({"error": (msg[0] if msg else "Download failed.")[:300]}), 422
    except Exception as e:
        shutil.rmtree(tmpdir, ignore_errors=True)
        return jsonify({"error": f"Download error: {e}"}), 500

    files = [os.path.join(tmpdir, f) for f in os.listdir(tmpdir)
             if not f.endswith((".part", ".ytdl", ".webp", ".jpg", ".png"))]
    files = [f for f in files if os.path.isfile(f)]
    if not files:
        shutil.rmtree(tmpdir, ignore_errors=True)
        return jsonify({"error": "Download produced no file."}), 500
    path = max(files, key=os.path.getsize)
    ext = os.path.splitext(path)[1].lstrip(".") or "mp4"
    title = (info or {}).get("title") if isinstance(info, dict) else None
    filename = _safe_name(title, ext)

    response = send_file(path, as_attachment=True, download_name=filename)

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
    if target not in CONVERT_TARGETS:
        return jsonify({"error": f"target must be one of: {', '.join(CONVERT_TARGETS)}"}), 400
    if upload is None or not upload.filename:
        return jsonify({"error": "No file uploaded (field name: file)."}), 400
    if request.content_length and request.content_length > MAX_UPLOAD_BYTES + 1024 * 1024:
        return jsonify({"error": "File too large — 200 MB maximum."}), 413

    tmpdir = tempfile.mkdtemp(prefix="quicksave-cv-")
    try:
        safe = secure_filename(upload.filename) or "upload.bin"
        src = os.path.join(tmpdir, safe)
        upload.save(src)
        if os.path.getsize(src) > MAX_UPLOAD_BYTES:
            shutil.rmtree(tmpdir, ignore_errors=True)
            return jsonify({"error": "File too large — 200 MB maximum."}), 413
        stem = os.path.splitext(safe)[0] or "converted"
        dst = os.path.join(tmpdir, f"{stem}.{target}")
        if os.path.abspath(src) == os.path.abspath(dst):
            dst = os.path.join(tmpdir, f"{stem}-converted.{target}")
        proc = _ffmpeg_convert(src, dst, target)
        if proc.returncode != 0 or not os.path.exists(dst) or os.path.getsize(dst) == 0:
            tail = (proc.stderr or "").strip().splitlines()[-3:]
            shutil.rmtree(tmpdir, ignore_errors=True)
            return jsonify({"error": "Conversion failed: " + " ".join(tail)[:300]}), 422
        response = send_file(dst, as_attachment=True,
                             download_name=f"{stem}.{target}")

        @response.call_on_close
        def _cleanup():
            shutil.rmtree(tmpdir, ignore_errors=True)

        return response
    except subprocess.TimeoutExpired:
        shutil.rmtree(tmpdir, ignore_errors=True)
        return jsonify({"error": "Conversion timed out (10 min limit)."}), 504
    except Exception:
        # If we already returned a response above, exceptions from send_file
        # streaming are handled by Flask; only clean up on setup errors.
        if not os.path.exists(tmpdir):
            raise
        raise


@app.get("/api/health")
def api_health():
    return jsonify({"ok": True, "app": "QuickSave", "time": int(time.time())})


if __name__ == "__main__":
    app.run(host=HOST, port=PORT, threaded=True)
