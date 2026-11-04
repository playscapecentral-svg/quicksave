# QuickSave growth measurement — owner setup checklist

The code for the arena plan's Initiative 1 is shipped (event taxonomy in
`server.py`, ingest/export Pages Function in `functions/api/events.js`,
counting script in `growth/count_events.py`). The event store itself is a
Cloudflare D1 database that only the account owner can create and bind.
Until these steps are done, `/api/events` returns a clear 503, the site
works normally, and the backend counts the missed ingests on
`/api/health` as `event_ingest_failed` (a visible number, not a silent
gap).

## Owner steps (Cloudflare dashboard, ~15 minutes)

1. **Create the database:** Cloudflare dashboard → Storage & Databases →
   D1 → *Create database* → name it exactly `quicksave-events`.
2. **Create the table:** open the new database → *Console* → paste the
   whole contents of `growth/schema.sql` → Execute.
3. **Bind it to the Pages project:** Workers & Pages → `quicksave` →
   Settings → Bindings → *Add* → D1 database → variable name **exactly
   `DB`** → pick `quicksave-events` → save, then redeploy (Deployments →
   latest → Retry deployment, or any git push).
4. **Set the Pages secrets** (same Settings area → Variables and Secrets,
   type *Secret*):
   - `EVENTS_INGEST_TOKEN` — a long random string you invent.
   - `EVENTS_EXPORT_TOKEN` — a different long random string.
5. **Tell the backend (Render dashboard → quicksave → Environment):**
   - `QS_INGEST_TOKEN` = the same value as `EVENTS_INGEST_TOKEN` above.
   - `QS_TEST_TOKEN` = another random string (marks canary/test traffic;
     keep it private). `QS_EVENTS_INGEST_URL` needs no change — the
     default already points at `https://quicksave.pages.dev/api/events`.
6. **Give Maya the test token once** so it can be placed in
   `growth/.test-token` on the automation VM (that file is git-ignored
   and never committed) — the daily TikTok canary and manual trace tests
   use it to log as `source=synthetic` / `source=test` instead of
   polluting the user numbers.

## What runs where

| Piece | Where | Notes |
|---|---|---|
| Event ingest/export | `functions/api/events.js` (Pages) | POST writes one event row; GET exports JSONL behind `EVENTS_EXPORT_TOKEN`. |
| Event emission | `server.py` (Render) | stdout is debugging only; D1 is the only source of truth. Nothing is stored on Render's disk. |
| Backup files | `growth-data/events-YYYY-MM.jsonl` | Pulled from the D1 export every 6 h, reconciled daily against D1's row count, then committed. Never inside `public/`. |
| Counting | `python3 growth/count_events.py` | Joins on `request_id`, 72-hour cohort finalisation; headline rates are `source=user` only. |
| Canary | `python3 growth/canary.py` | One TikTok resolve/day via the `quicksave-canary` cron. No YouTube canary exists, by design. |
