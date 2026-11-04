-- QuickSave growth events — Cloudflare D1 schema (arena plan, Initiative 1).
-- Create the database (Cloudflare dashboard → Storage & Databases → D1 →
-- Create database, name: quicksave-events), then run this SQL in the D1
-- console, then bind the database to the Pages project as `DB`
-- (Pages project → Settings → Bindings → D1 database → variable name DB).
-- See growth/README.md for the full owner checklist.

CREATE TABLE IF NOT EXISTS events (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id      TEXT UNIQUE NOT NULL,   -- per-event UUID, dedupe key on export
  request_id    TEXT,                   -- per-request UUID, joins start/terminal
  event         TEXT NOT NULL,          -- taxonomy name (see server.py)
  ts            REAL,                   -- epoch seconds (event creation)
  ts_iso        TEXT,                   -- ISO-8601 UTC
  source        TEXT,                   -- user | synthetic | test
  session_id    TEXT,                   -- anonymous browser session id
  page_slug     TEXT,                   -- e.g. /tiktok-video-downloader/
  referrer_host TEXT,                   -- first-touch external referrer host only
  platform      TEXT,                   -- extractor name when known
  reason        TEXT,                   -- failure reason code on *_failed events
  format_id     TEXT,                   -- download events
  boot_id       TEXT,                   -- backend boot UUID (restarts visible)
  payload       TEXT NOT NULL,          -- the full event JSON, verbatim
  received_at   TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_events_request_id ON events (request_id);
CREATE INDEX IF NOT EXISTS idx_events_event_id   ON events (event_id);
CREATE INDEX IF NOT EXISTS idx_events_ts         ON events (ts);
CREATE INDEX IF NOT EXISTS idx_events_source     ON events (source);
