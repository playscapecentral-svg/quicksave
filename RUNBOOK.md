# QuickSave Runbook — YouTube-path degradation (arena plan, Initiative 6)

YouTube is simultaneously QuickSave's biggest demand and its single point
of failure: YouTube blocks datacenter IPs with a "Sign in to confirm
you're not a bot" wall, and extraction depends on a backend mechanism that
can stop working at any time, possibly permanently. This runbook's
standing posture is **degradation and honesty, not escalation**: when the
block bites, the site tells users the truth and effort shifts to the
platforms that work (TikTok, Instagram, Facebook, Vimeo, the converter).

## 1. Detection signals

All signals come from the Initiative 1 event store (`source=user` only —
there is deliberately **no synthetic YouTube signal**: no automated
YouTube test resolves are run anywhere, so no test streak can masquerade
as user evidence).

| Signal | Where to see it | Meaning |
|---|---|---|
| `resolve_failed` with `reason=bot_wall` | `growth/count_events.py` failure-reason split, platform=YouTube | Real visitors are hitting the bot wall. |
| Daily bot-wall share | bot_wall ÷ all real-user YouTube resolves that day | Only computed on days with **≥5 real-user YouTube resolves**; below that, report raw counts ("insufficient evidence") — one event must never read as a 50–100% failure rate. |
| **Kill condition (§5)** | `bot_wall` > 50% of YouTube resolves on **2 consecutive days**, each with ≥5 real-user resolves | Execute the degradation response in §2. Days below the volume floor neither trigger nor clear this condition. |
| Recovery signal | 3 consecutive passing days (each ≥5 real-user resolves, `bot_wall` < 25%) | Take the status line down, note the recovery in `growth-log.md`. |
| Backend down (different problem) | `/api/health` not 200; `quicksave-keepalive` cron alert | Not a bot wall — fix the service first. The canary (TikTok, `source=synthetic`) separates "backend down" from "YouTube blocked". |

Symptom in the raw API: `POST /api/resolve` returns 422 with an error
containing "Sign in to confirm you're not a bot", logged server-side as
`resolve_failed` / `reason=bot_wall`.

## 2. Degradation response (in this order, ~30 min)

1. **Tell users the truth on the YouTube pages.** Add this status line to
   `/youtube-video-downloader/` (and `/youtube-shorts-downloader/` if it
   exists): *"YouTube is currently blocking our server — TikTok,
   Instagram, Facebook and the converter still work."* Never present the
   YouTube tool as working when the signals say it is not.
2. **Stop promoting YouTube pages** for that week. Community and
   directory effort points only at non-YouTube pages.
3. **Treat the Initiative 3 Shorts gate as failed** (no new YouTube page
   is built while the path is blocked).
4. **Log the episode** in `growth-log.md` with the day's real-user counts
   (resolves, bot_wall count/share, distinct `video_id_hash` count).
5. When the recovery signal (§1) passes, remove the status line and log
   the recovery. Nothing else is prescribed — a quiet week with too few
   real-user resolves is "no evidence yet", not a problem to solve with
   test traffic.

## 3. The pre-existing cookie mechanism (owner's own operation — outside the growth plan)

The growth plan deliberately does **not** adopt, recommend, or depend on
the backend's cookie mechanism; no plan target, gate pass, or initiative
needs it. It is recorded here only because the backend currently runs
with it, and its operation is the owner's own decision, taken outside
the plan:

- **History:** a cookie set died within ~7 hours when its login session
  was *also* active in a browser. A dedicated session (used by nothing
  else) is the configuration that survived.
- **Replacement procedure, when the owner chooses to replace the set:**
  1. Open a Chrome **Incognito** window; sign in to YouTube with the
     **spare account only** (never a channel account — see §4).
  2. Export the cookies for youtube.com with the "Get cookies.txt
     LOCALLY" extension; confirm the file contains the full set
     (including `SID` and `__Secure-1PSID` — partial exports resolve to
     storyboard-only formats).
  3. **Close the Incognito window completely** and do not use that login
     in any browser or phone again; the session must belong to the
     server alone.
  4. Set the file's contents as the `YTDLP_COOKIES` secret in the Render
     environment (dashboard → quicksave → Environment). **Never commit
     cookies to this repo, never paste them in chat logs or files.**
  5. Verify with one manual resolve of a previously blocked video,
     sent with the `X-QS-Test` header so it logs as `source=test`.
- The policy-clean alternative always exists: run YouTube extraction
  with no cookies at all and accept the `bot_wall` failures under §2.
  Every non-YouTube part of the site is unaffected either way.

## 4. What NOT to do

- **Never** use the owner's real channel accounts (The Shorter Version,
  Age of Vanishing) for backend extraction, in any form.
- **Never** add a bypass technique as a "fix": no cookie-rotation
  services, no token harvesting, no proxy rotation, no CAPTCHA-solving
  services, no fingerprint spoofing.
- **Never** schedule synthetic/automated YouTube resolves (no YouTube
  canary) — health is judged on user-initiated traffic only.
- **Never** soften the honest copy: YouTube pages keep the FAQ line that
  private, age-restricted and region-locked videos may fail.
- **Never** store event data or cookies on the Render disk or in this
  repo; events live in the Cloudflare D1 store, secrets in host env vars.
- **Never** argue with a rights holder or a hosting abuse notice —
  comply, document it in `growth-log.md` (see `/dmca/`).

## 5. Copyright complaints

The intake route is the `/dmca/` page and its published inbox
(playscapecentral@gmail.com): acknowledge within 2 business days, act
within 5. If the page or inbox is ever found broken or unmonitored at a
Monday review, fixing it outranks that week's growth work.
