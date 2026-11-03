"use strict";
const API_BASE = (localStorage.getItem("qs_api_base") || "https://quicksave-tgyk.onrender.com").replace(/\/$/, "");
function api(path) { return API_BASE + path; }
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
  return api("/api/download?url=" + encodeURIComponent(currentUrl) +
         "&format_id=" + encodeURIComponent(formatId));
}
function makeDlButton(label, formatId) {
  const b = document.createElement("button");
  b.className = "dl-btn small"; b.textContent = "⬇ " + label;
  b.addEventListener("click", () => { window.location.href = downloadUrl(formatId); });
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
      body: JSON.stringify({ url }),
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
    let vCount = 0, aCount = 0;
    for (const f of data.formats) {
      const quality = f.has_video ? (f.height ? f.height + "p" : f.resolution) : (f.note || "audio");
      const label = `${quality} · ${f.ext}${f.fps ? " · " + f.fps + "fps" : ""} · ${fmtSize(f.filesize_approx)}${f.has_video && !f.has_audio ? " (merges audio)" : ""}`;
      const btn = makeDlButton(label, f.format_id);
      if (f.has_video) { vg.appendChild(btn); vCount++; } else { ag.appendChild(btn); aCount++; }
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

form.addEventListener("submit", (e) => {
  e.preventDefault();
  const url = input.value.trim();
  if (url) resolve(url);
});
document.querySelectorAll(".quick-actions .dl-btn").forEach((b) => {
  b.addEventListener("click", () => { if (currentUrl) window.location.href = downloadUrl(b.dataset.format); });
});

// Prefill from ?url= (used by the QuickSave Helper extension)
const prefill = new URLSearchParams(window.location.search).get("url");
if (prefill) { input.value = prefill; resolve(prefill); }

// ---- Supported platforms
fetch(api("/api/supported")).then((r) => r.json()).then((data) => {
  $("#supported-note").textContent =
    `QuickSave's resolver ships ${data.count} site extractors. Highlights:`;
  const grid = $("#supported-grid");
  const items = (data.highlights && data.highlights.length ? data.highlights : data.sample.slice(0, 24));
  for (const name of items) {
    const c = document.createElement("span"); c.className = "chip"; c.textContent = name; grid.appendChild(c);
  }
}).catch(() => { $("#supported-note").textContent = "Coverage list unavailable right now."; });

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
