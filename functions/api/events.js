// QuickSave growth-event store (arena plan, Initiative 1 action 6).
//
//   POST /api/events  — ingest one event (or a JSON array of events).
//                       Used by server.py (X-QS-Ingest token) and by the
//                       site's own fire-and-forget page_view beacons.
//   GET  /api/events  — export stored events as JSONL for the 6-hourly
//                       backup pull. Guarded by EVENTS_EXPORT_TOKEN
//                       (Authorization: Bearer <token>, X-QS-Export header,
//                       or ?token=). Params: since_id (row id cursor),
//                       since_event_id, limit (default 5000, max 20000).
//                       Response header X-Total-Count carries the store's
//                       total row count for the daily reconciliation.
//
// Storage is the Cloudflare D1 database bound to this Pages project as
// `DB` (schema: growth/schema.sql). If the binding is absent the site
// keeps working — both verbs return a clear 503 JSON error instead.

const TAXONOMY = new Set([
  "resolve_started", "resolve_succeeded", "resolve_failed",
  "download_requested", "download_delivered", "download_failed",
  "convert_started", "convert_delivered", "convert_failed",
  "page_view", // browser context only — never used in funnel rates
]);

function json(status, obj) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function noStore(env) {
  return !env || !env.DB;
}

export async function onRequestPost(context) {
  const { request, env } = context;
  if (noStore(env)) {
    return json(503, { error: "events store not configured (D1 binding DB missing)" });
  }
  // Ingest token is enforced when the owner has set one. Browser beacons
  // cannot carry it, so when it is set only token-carrying posts are
  // accepted — server.py always sends it; page_view beacons are optional
  // context and may be dropped until the owner decides otherwise.
  if (env.EVENTS_INGEST_TOKEN) {
    if (request.headers.get("X-QS-Ingest") !== env.EVENTS_INGEST_TOKEN) {
      return json(401, { error: "bad or missing ingest token" });
    }
  }
  let body;
  try {
    body = await request.json();
  } catch (_) {
    return json(400, { error: "invalid JSON" });
  }
  const events = Array.isArray(body) ? body : [body];
  if (!events.length || events.length > 100) {
    return json(400, { error: "expected 1..100 events" });
  }
  const stmt = env.DB.prepare(
    `INSERT OR IGNORE INTO events
       (event_id, request_id, event, ts, ts_iso, source, session_id,
        page_slug, referrer_host, platform, reason, format_id, boot_id, payload)
     VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14)`);
  const bound = [];
  for (const e of events) {
    if (!e || typeof e !== "object" || !TAXONOMY.has(e.event)) {
      return json(400, { error: "unknown or missing event name" });
    }
    const payload = JSON.stringify(e);
    bound.push(stmt.bind(
      String(e.event_id || crypto.randomUUID().replace(/-/g, "")),
      e.request_id ? String(e.request_id) : null,
      e.event,
      typeof e.ts === "number" ? e.ts : Date.now() / 1000,
      e.ts_iso ? String(e.ts_iso) : null,
      e.source ? String(e.source) : "user",
      e.session_id ? String(e.session_id) : null,
      e.page_slug ? String(e.page_slug) : null,
      e.referrer_host ? String(e.referrer_host) : null,
      e.platform ? String(e.platform) : null,
      e.reason ? String(e.reason) : null,
      e.format_id ? String(e.format_id) : null,
      e.boot_id ? String(e.boot_id) : null,
      payload));
  }
  try {
    await env.DB.batch(bound);
  } catch (err) {
    return json(500, { error: "insert failed: " + String(err).slice(0, 200) });
  }
  return json(201, { ok: true, inserted: bound.length });
}

export async function onRequestGet(context) {
  const { request, env } = context;
  if (noStore(env)) {
    return json(503, { error: "events store not configured (D1 binding DB missing)" });
  }
  if (!env.EVENTS_EXPORT_TOKEN) {
    return json(503, { error: "export not configured (EVENTS_EXPORT_TOKEN unset)" });
  }
  const url = new URL(request.url);
  const token = (request.headers.get("Authorization") || "").replace(/^Bearer\s+/i, "")
    || request.headers.get("X-QS-Export")
    || url.searchParams.get("token");
  if (token !== env.EVENTS_EXPORT_TOKEN) {
    return json(401, { error: "bad or missing export token" });
  }
  let sinceId = parseInt(url.searchParams.get("since_id") || "0", 10);
  if (Number.isNaN(sinceId) || sinceId < 0) sinceId = 0;
  const sinceEventId = url.searchParams.get("since_event_id");
  if (sinceEventId) {
    const row = await env.DB.prepare(
      "SELECT id FROM events WHERE event_id = ?1").bind(sinceEventId).first();
    if (row && typeof row.id === "number") sinceId = Math.max(sinceId, row.id);
  }
  let limit = parseInt(url.searchParams.get("limit") || "5000", 10);
  if (Number.isNaN(limit) || limit < 1) limit = 5000;
  if (limit > 20000) limit = 20000;
  const total = await env.DB.prepare("SELECT COUNT(*) AS n FROM events").first();
  const res = await env.DB.prepare(
    "SELECT id, payload FROM events WHERE id > ?1 ORDER BY id ASC LIMIT ?2")
    .bind(sinceId, limit).all();
  const lines = (res.results || []).map((r) => {
    try {
      const obj = JSON.parse(r.payload);
      obj._row_id = r.id;
      return JSON.stringify(obj);
    } catch (_) {
      return r.payload;
    }
  });
  return new Response(lines.join("\n") + (lines.length ? "\n" : ""), {
    status: 200,
    headers: {
      "Content-Type": "application/x-ndjson",
      "X-Total-Count": String(total ? total.n : 0),
    },
  });
}

export async function onRequest(context) {
  if (context.request.method === "POST") return onRequestPost(context);
  if (context.request.method === "GET") return onRequestGet(context);
  return json(405, { error: "method not allowed" });
}
