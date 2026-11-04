"use strict";
const API_BASE = "https://quicksave-tgyk.onrender.com";
function api(path) { return API_BASE + path; }

// ---- Growth measurement (arena plan, Initiative 1): anonymous session
// attribution + fire-and-forget page-view context posts to the same-origin
// Pages Function ingest. Everything is wrapped so a failure here can NEVER
// break or delay resolving, downloading or converting.
const QS_SLUG = window.location.pathname || "/";
let qsSessionId = null, qsReferrerHost = "direct";
try {
  qsSessionId = sessionStorage.getItem("qs_session_id");
  if (!qsSessionId) {
    qsSessionId = (crypto.randomUUID ? crypto.randomUUID()
      : "s-" + Date.now() + "-" + Math.random().toString(36).slice(2, 10));
    sessionStorage.setItem("qs_session_id", qsSessionId);
  }
  let ref = sessionStorage.getItem("qs_referrer_host");
  if (ref === null) {
    ref = "direct";
    try {
      if (document.referrer) {
        const h = new URL(document.referrer).hostname;
        if (h && h !== window.location.hostname) ref = h;
      }
    } catch (_) {}
    sessionStorage.setItem("qs_referrer_host", ref);
  }
  qsReferrerHost = ref || "direct";
} catch (_) {}
function qsAttribution() {
  return { session_id: qsSessionId, page_slug: QS_SLUG, referrer_host: qsReferrerHost };
}
function qsTrack(event, extra) {
  try {
    const payload = Object.assign(
      { event, source: "user", ts: Date.now() / 1000 }, qsAttribution(), extra || {});
    const body = JSON.stringify(payload);
    if (navigator.sendBeacon) {
      navigator.sendBeacon("/api/events", new Blob([body], { type: "application/json" }));
    } else {
      fetch("/api/events", { method: "POST", headers: { "Content-Type": "application/json" },
        body, keepalive: true }).catch(() => {});
    }
  } catch (_) {}
}
qsTrack("page_view");
const $ = (s) => document.querySelector(s);
const form = $("#resolve-form"), input = $("#url-input"), fetchBtn = $("#fetch-btn");
const statusBox = $("#status"), result = $("#result");
let currentUrl = "";

function setStatus(msg, isError) {
  statusBox.hidden = !msg;
  statusBox.textContent = msg || "";
  statusBox.classList.toggle("error", !!isError);
}
function fmtDuration(sec) {
  if (!sec && sec !== 0) return "—";
  sec = Math.round(sec);
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  return (h ? h + ":" + String(m).padStart(2, "0") : m) + ":" + String(s).padStart(2, "0");
}
function fmtSize(bytes) {
  if (!bytes) return "size ?";
  const u = ["B", "KB", "MB", "GB"]; let i = 0, n = bytes;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return n.toFixed(n >= 100 ? 0 : 1) + " " + u[i];
}
function downloadUrl(formatId) {
  let u = api("/api/download?url=" + encodeURIComponent(currentUrl) +
         "&format_id=" + encodeURIComponent(formatId));
  try {
    const a = qsAttribution();
    if (a.session_id) u += "&session_id=" + encodeURIComponent(a.session_id);
    u += "&page_slug=" + encodeURIComponent(a.page_slug) +
         "&referrer_host=" + encodeURIComponent(a.referrer_host);
  } catch (_) {}
  return u;
}
function makeDlButton(label, formatId) {
  const b = document.createElement("button");
  b.className = "dl-btn small"; b.textContent = "⬇ " + label;
  b.addEventListener("click", () => {
    setStatus("Preparing your file on the server — HD/large videos can take a little while…", false);
    window.location.href = downloadUrl(formatId);
  });
  return b;
}

async function resolve(url) {
  if (!API_BASE) {
    setStatus("No backend connected yet. Set your Backend URL in the 'Backend server' section below first — downloads run on that server.", true);
    const b = document.querySelector("#backend"); if (b) b.scrollIntoView({ behavior: "smooth" });
    return;
  }
  currentUrl = url;
  result.hidden = true;
  fetchBtn.disabled = true;
  setStatus("Fetching formats for that link…", false);
  try {
    const r = await fetch(api("/api/resolve"), {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(Object.assign({ url }, qsAttribution())),
    });
    let data = {};
    try { data = await r.json(); } catch (_) { throw new Error("The backend did not answer properly — check the Backend URL in the 'Backend server' section."); }
    if (!r.ok) throw new Error(data.error || "Could not resolve that link.");
    $("#r-thumb").src = data.thumbnail || "";
    $("#r-title").textContent = data.title || "Untitled";
    $("#r-uploader").textContent = data.uploader || "Unknown uploader";
    $("#r-duration").textContent = fmtDuration(data.duration);
    $("#r-platform").textContent = data.platform || "web";
    const vg = $("#formats-video"), ag = $("#formats-audio");
    vg.innerHTML = ""; ag.innerHTML = "";
    // TikTok only (arena plan, Initiative 2): the play-stream format the
    // Day-4 gate verified watermark-free — a bytevc1_*/h264_* format_id
    // ending in "-0", highest resolution — is labelled "MP4 — no watermark"
    // and rendered as the first button. No other platform gets this label.
    let isTikTok = /tiktok/i.test(data.platform || "");
    if (!isTikTok) {
      try { isTikTok = /(^|\.)tiktok\.com$/i.test(new URL(url).hostname); } catch (_) {}
    }
    let ttPick = null;
    if (isTikTok) {
      for (const f of data.formats) {
        if (f.has_video && /^(bytevc1|h264)_.*-0$/.test(f.format_id || "") &&
            (!ttPick || (f.height || 0) > (ttPick.height || 0))) ttPick = f;
      }
    }
    let vCount = 0, aCount = 0;
    for (const f of data.formats) {
      const quality = f.has_video ? (f.height ? f.height + "p" : f.resolution) : (f.note || "audio");
      const label = f === ttPick ? "MP4 — no watermark"
        : `${quality} · ${f.ext}${f.fps ? " · " + f.fps + "fps" : ""} · ${fmtSize(f.filesize_approx)}${f.has_video && !f.has_audio ? " (merges audio)" : ""}`;
      const btn = makeDlButton(label, f.format_id);
      if (f.has_video) {
        if (f === ttPick) vg.prepend(btn); else vg.appendChild(btn);
        vCount++;
      } else { ag.appendChild(btn); aCount++; }
    }
    if (!vCount) vg.innerHTML = "<p>No separate video formats — use Best quality MP4 above.</p>";
    if (!aCount) ag.innerHTML = "<p>No audio-only formats — use Audio only (MP3) above.</p>";
    result.hidden = false;
    setStatus(`Found ${data.formats.length} formats. Pick one to download.`, false);
  } catch (e) {
    setStatus(e.message, true);
  } finally {
    fetchBtn.disabled = false;
  }
}

if (form) form.addEventListener("submit", (e) => {
  e.preventDefault();
  const url = input.value.trim();
  if (url) resolve(url);
});
document.querySelectorAll(".quick-actions .dl-btn").forEach((b) => {
  b.addEventListener("click", () => {
    if (!currentUrl) return;
    setStatus("Preparing your file on the server — HD/large videos can take a little while…", false);
    window.location.href = downloadUrl(b.dataset.format);
  });
});

// Prefill from ?url= (used by the QuickSave Helper extension)
const prefill = new URLSearchParams(window.location.search).get("url");
if (prefill && input) { input.value = prefill; resolve(prefill); }

// ---- Supported platforms
const supNote = $("#supported-note"), supGrid = $("#supported-grid");
if (supNote && supGrid) fetch(api("/api/supported")).then((r) => r.json()).then((data) => {
  supNote.textContent =
    `QuickSave's resolver ships ${data.count} site extractors. Highlights:`;
  const grid = supGrid;
  const items = (data.highlights && data.highlights.length ? data.highlights : data.sample.slice(0, 24));
  for (const name of items) {
    const c = document.createElement("span"); c.className = "chip"; c.textContent = name; grid.appendChild(c);
  }
}).catch(() => { supNote.textContent = "Coverage list unavailable right now."; });

// ---- Converter
const dz = $("#drop-zone"), fileInput = $("#convert-file"),
      convBtn = $("#convert-btn"), convStatus = $("#convert-status");
let convertFile = null;
if (dz && fileInput && convBtn && convStatus) {
function setConvertFile(f) {
  convertFile = f || null;
  $("#convert-name").textContent = f ? `${f.name} (${fmtSize(f.size)})` : "";
}
fileInput.addEventListener("change", () => setConvertFile(fileInput.files[0]));
["dragover", "dragenter"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("drag"); }));
["dragleave", "drop"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("drag"); }));
dz.addEventListener("drop", (e) => setConvertFile(e.dataTransfer.files[0]));
convBtn.addEventListener("click", async () => {
  if (!API_BASE) {
    convStatus.hidden = false; convStatus.classList.add("error");
    convStatus.textContent = "No backend connected yet — set your Backend URL above first."; return;
  }
  if (!convertFile) {
    convStatus.hidden = false; convStatus.classList.add("error");
    convStatus.textContent = "Choose a file first."; return;
  }
  const target = $("#convert-target").value;
  const fd = new FormData();
  fd.append("file", convertFile); fd.append("target", target);
  try {
    const a = qsAttribution();
    if (a.session_id) fd.append("session_id", a.session_id);
    fd.append("page_slug", a.page_slug);
    fd.append("referrer_host", a.referrer_host);
  } catch (_) {}
  convBtn.disabled = true;
  convStatus.hidden = false; convStatus.classList.remove("error");
  convStatus.textContent = "Converting… this can take a while for big files.";
  try {
    const r = await fetch(api("/api/convert"), { method: "POST", body: fd });
    if (!r.ok) {
      let msg = "Conversion failed.";
      try { msg = (await r.json()).error || msg; } catch (_) {}
      throw new Error(msg);
    }
    const blob = await r.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = convertFile.name.replace(/\.[^.]+$/, "") + "." + target;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 4000);
    convStatus.textContent = "Done — your converted file is downloading.";
  } catch (e) {
    convStatus.classList.add("error"); convStatus.textContent = e.message;
  } finally { convBtn.disabled = false; }
});
}

// ---- Static (Cloudflare Pages) extras: backend picker (only on pages that include it)
const apiInput = document.querySelector("#api-base"), apiStatus = document.querySelector("#api-status");
if (apiInput) {
  apiInput.value = API_BASE;
  document.querySelector("#api-save").addEventListener("click", () => {
    const v = apiInput.value.trim().replace(/\/$/, "");
    if (v) localStorage.setItem("qs_api_base", v); else localStorage.removeItem("qs_api_base");
    apiStatus.hidden = false; apiStatus.textContent = "Saved. Reloading…";
    setTimeout(() => window.location.reload(), 500);
  });
  if (!API_BASE) { apiStatus.hidden = false; apiStatus.classList.add("error"); apiStatus.textContent = "No backend set yet — downloads will not work until you set a Backend URL above."; }
}
