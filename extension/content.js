// QuickSave Helper — content script
// Injects a "Download" button on YouTube watch pages (and a floating button
// on Facebook / Instagram / TikTok media pages) that opens the local
// QuickSave site with the current page URL prefilled.
(function () {
  "use strict";
  const DEFAULT_SERVER = "http://127.0.0.1:5000";
  const BTN_ID = "quicksave-helper-btn";

  function openQuickSave() {
    chrome.storage.sync.get({ serverUrl: DEFAULT_SERVER }, (cfg) => {
      const base = (cfg.serverUrl || DEFAULT_SERVER).replace(/\/+$/, "");
      const target = base + "/?url=" + encodeURIComponent(window.location.href);
      window.open(target, "_blank");
    });
  }

  function makeButton() {
    const btn = document.createElement("button");
    btn.id = BTN_ID;
    btn.textContent = "⬇ Download with QuickSave";
    btn.style.cssText = [
      "background:#2f9e44", "color:#fff", "border:0", "border-radius:999px",
      "padding:8px 16px", "font-weight:700", "font-size:14px", "cursor:pointer",
      "margin:8px 0", "z-index:9999",
    ].join(";");
    btn.addEventListener("click", openQuickSave);
    return btn;
  }

  function inject() {
    if (document.getElementById(BTN_ID)) return;
    const host = window.location.hostname;
    if (host.includes("youtube.com")) {
      if (!/\/watch/.test(window.location.pathname)) return;
      // Near the title / actions area of a watch page.
      const anchor =
        document.querySelector("#above-the-fold #title") ||
        document.querySelector("ytd-watch-metadata #title") ||
        document.querySelector("#info-contents") ||
        document.querySelector("h1.ytd-watch-metadata");
      if (anchor && anchor.parentElement) {
        anchor.parentElement.insertBefore(makeButton(), anchor.nextSibling);
      }
    } else {
      // Floating button on other supported sites.
      const btn = makeButton();
      btn.style.position = "fixed";
      btn.style.bottom = "18px";
      btn.style.right = "18px";
      btn.style.boxShadow = "0 4px 16px rgba(0,0,0,.3)";
      document.body.appendChild(btn);
    }
  }

  inject();
  // YouTube is a SPA — re-inject after in-page navigations, and retry for
  // slow-rendering title areas.
  let lastUrl = window.location.href;
  setInterval(() => {
    if (window.location.href !== lastUrl) {
      lastUrl = window.location.href;
      const old = document.getElementById(BTN_ID);
      if (old) old.remove();
    }
    inject();
  }, 1500);
})();
