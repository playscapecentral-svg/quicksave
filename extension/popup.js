"use strict";
const DEFAULT_SERVER = "http://127.0.0.1:5000";
const $ = (id) => document.getElementById(id);

function getServer(cb) {
  chrome.storage.sync.get({ serverUrl: DEFAULT_SERVER }, (cfg) => {
    cb((cfg.serverUrl || DEFAULT_SERVER).replace(/\/+$/, ""));
  });
}
function openInQuickSave(url) {
  if (!url) { $("msg").textContent = "Paste a link first."; return; }
  getServer((base) => {
    chrome.tabs.create({ url: base + "/?url=" + encodeURIComponent(url) });
  });
}

document.addEventListener("DOMContentLoaded", () => {
  getServer((base) => { $("server").value = base; });
  // Prefill with the active tab URL when it looks like a watch/media page.
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    if (tabs && tabs[0] && /^https?:/.test(tabs[0].url || "")) {
      $("url").placeholder = tabs[0].url;
      $("url").dataset.tabUrl = tabs[0].url;
    }
  });
});

$("open").addEventListener("click", () => openInQuickSave($("url").value.trim()));
$("use-tab").addEventListener("click", () => {
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    if (tabs && tabs[0]) openInQuickSave(tabs[0].url);
  });
});
$("save-server").addEventListener("click", () => {
  const v = $("server").value.trim() || DEFAULT_SERVER;
  chrome.storage.sync.set({ serverUrl: v.replace(/\/+$/, "") }, () => {
    $("msg").textContent = "Server URL saved: " + v.replace(/\/+$/, "");
  });
});
