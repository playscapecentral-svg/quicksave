#!/usr/bin/env python3
"""QuickSave daily TikTok canary (arena plan, Initiative 1 action 5).

Resolves ONE fixed public TikTok link through the live backend, carrying
the X-QS-Test header so the backend logs it as source=synthetic — counted
completely separately, never mixed into user metrics. Exit 0 on success
(cron stays silent), exit 1 with the error on stderr (cron alerts).

There is deliberately NO YouTube canary anywhere in this plan: no
synthetic or automated YouTube test resolves are scheduled, ever.

Token: read from the QS_TEST_TOKEN environment variable, or from
growth/.test-token (a local file that is .gitignored and never
committed). It must match the QS_TEST_TOKEN secret set on the backend
(Render) — until the owner sets both, the canary's resolve simply logs
as an ordinary request and the script still verifies the backend is up.
"""
import json
import os
import sys
import urllib.error
import urllib.request

BACKEND = os.environ.get("QS_BACKEND_URL",
                         "https://quicksave-tgyk.onrender.com").rstrip("/")
# One fixed, long-lived public TikTok video (the platform's own demo-era
# upload). If it is ever deleted, replace with any other public link.
CANARY_URL = "https://www.tiktok.com/@scout2015/video/6718335390845095173"


def _token():
    tok = os.environ.get("QS_TEST_TOKEN", "").strip()
    if tok:
        return tok
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        ".test-token")
    try:
        with open(path) as fh:
            return fh.read().strip()
    except OSError:
        return ""


def main():
    body = json.dumps({
        "url": CANARY_URL,
        "session_id": "canary",
        "page_slug": "/tiktok-video-downloader/",
        "referrer_host": "canary",
    }).encode()
    headers = {"Content-Type": "application/json"}
    tok = _token()
    if tok:
        headers["X-QS-Test"] = tok
        headers["X-QS-Source"] = "synthetic"
    req = urllib.request.Request(BACKEND + "/api/resolve", data=body,
                                 headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read() or b"{}").get("error", "")
        except Exception:
            detail = ""
        print(f"canary FAILED: HTTP {e.code} {detail}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"canary FAILED: {e}", file=sys.stderr)
        return 1
    formats = data.get("formats") or []
    if not formats:
        print("canary FAILED: resolve returned no formats", file=sys.stderr)
        return 1
    print(f"canary ok: {len(formats)} formats, "
          f"request_id={data.get('request_id')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
