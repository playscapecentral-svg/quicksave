#!/usr/bin/env python3
"""QuickSave funnel counting script (arena plan, Initiative 1 action 4 / §4).

Reads the PERSISTED event backup files (growth-data/events-YYYY-MM.jsonl,
pulled from the Cloudflare D1 store and reconciled daily — never the live
Render log view), joins start and terminal events on request_id, and
prints counts and joined rates:

  * per event, per page slug, per platform, per failure reason and per
    referrer host — always split by source;
  * headline rates are computed for source=user ONLY;
  * a request belongs to the cohort of the (Asia/Dhaka, Mon–Sun) week its
    START event occurred in; its terminal event counts toward that cohort
    whenever it arrives within a 72-hour grace window;
  * a cohort is FINALISED at 00:30 Dhaka on the Thursday after its week
    ends. Rates are printed for finalised cohorts only; the newest
    cohort(s) print provisional counts, never rates;
  * sanity rule: a duplicate-terminal or orphan-terminal rate above 1% of
    requests means a counting/logging bug — the affected funnel's numbers
    must not be used until it is found.

Usage:
  python3 growth/count_events.py [--data-dir growth-data] [--as-of ISO]
"""
import argparse
import glob
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, time as dtime, timedelta, timezone

DHAKA = timezone(timedelta(hours=6))
GRACE = timedelta(hours=72)

STARTS = {
    "resolve_started": "resolve",
    "download_requested": "download",
    "convert_started": "convert",
}
TERMINALS = {
    "resolve_succeeded": ("resolve", True),
    "resolve_failed": ("resolve", False),
    "download_delivered": ("download", True),
    "download_failed": ("download", False),
    "convert_delivered": ("convert", True),
    "convert_failed": ("convert", False),
}
SUCCESS_EVENT = {"resolve": "resolve_succeeded",
                 "download": "download_delivered",
                 "convert": "convert_delivered"}


def cohort_monday(ts):
    d = datetime.fromtimestamp(ts, DHAKA).date()
    return d - timedelta(days=d.weekday())


def finalised_at(monday):
    # Thursday (monday + 10 days) 00:30 Dhaka — >=72h after the week's
    # last possible start (Sunday 23:59:59).
    return datetime.combine(monday + timedelta(days=10),
                            dtime(0, 30), tzinfo=DHAKA)


def load_events(data_dir):
    files = sorted(glob.glob(os.path.join(data_dir, "events-*.jsonl")))
    events, seen, dupes = [], set(), 0
    for path in files:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                eid = e.get("event_id")
                if eid:
                    if eid in seen:
                        dupes += 1
                        continue
                    seen.add(eid)
                events.append(e)
    return events, dupes, files


def main():
    ap = argparse.ArgumentParser()
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("--data-dir",
                    default=os.path.join(here, "..", "growth-data"))
    ap.add_argument("--as-of", default=None,
                    help="ISO datetime treated as 'now' (testing)")
    args = ap.parse_args()
    as_of = (datetime.fromisoformat(args.as_of) if args.as_of
             else datetime.now(DHAKA))
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=DHAKA)

    events, dupe_events, files = load_events(args.data_dir)
    print(f"files: {len(files)}  events: {len(events)}  "
          f"duplicate event_ids skipped: {dupe_events}")
    if not events:
        print("no events yet — nothing to count.")
        return 0

    by_source_event = Counter((e.get("source") or "user", e.get("event"))
                              for e in events)
    print("\n== raw counts by source x event ==")
    for (src, ev), n in sorted(by_source_event.items()):
        print(f"  {src:10s} {ev:20s} {n}")

    # ---- join starts and terminals on request_id
    starts = {}        # request_id -> start event
    terminals = defaultdict(list)
    orphan_terminals = 0
    for e in events:
        rid = e.get("request_id")
        if not rid:
            continue
        if e.get("event") in STARTS:
            starts.setdefault(rid, e)
        elif e.get("event") in TERMINALS:
            terminals[rid].append(e)
    for rid, terms in terminals.items():
        if rid not in starts:
            orphan_terminals += len(terms)
    duplicate_terminals = sum(len(t) - 1 for t in terminals.values()
                              if len(t) > 1)
    total_requests = len(starts)
    problem = orphan_terminals + duplicate_terminals
    rate = (problem / total_requests) if total_requests else 0.0
    print(f"\n== join sanity ==\n  requests (starts): {total_requests}  "
          f"orphan terminals: {orphan_terminals}  "
          f"duplicate terminals: {duplicate_terminals}  "
          f"problem rate: {rate:.2%}")
    if rate > 0.01:
        print("  !! COUNTING BUG: duplicate/orphan-terminal rate > 1% — "
              "do not use the affected funnel's numbers until fixed.")

    # ---- joined records (user source only for headline numbers)
    joined = []  # dicts: funnel, cohort, outcome, start event, terminal
    for rid, st in starts.items():
        funnel = STARTS[st["event"]]
        terms = [t for t in terminals.get(rid, [])
                 if t["event"] in TERMINALS
                 and TERMINALS[t["event"]][0] == funnel]
        in_grace, late = [], 0
        t0 = st.get("ts") or 0
        for t in terms:
            if (t.get("ts") or 0) - t0 <= GRACE.total_seconds():
                in_grace.append(t)
            else:
                late += 1
        term = in_grace[0] if in_grace else None
        joined.append({
            "funnel": funnel, "start": st, "terminal": term,
            "late_terminals": late,
            "cohort": cohort_monday(t0),
            "source": st.get("source") or "user",
            "outcome": (term["event"] if term else "abandoned"),
        })

    cohorts = sorted({j["cohort"] for j in joined})
    print("\n== joined cohorts (headline rates: source=user only) ==")
    for monday in cohorts:
        fin = finalised_at(monday)
        is_fin = as_of >= fin
        label = "FINALISED" if is_fin else f"provisional (finalises {fin:%a %Y-%m-%d %H:%M} Dhaka)"
        print(f"\n-- cohort week of {monday} — {label}")
        for funnel in ("resolve", "download", "convert"):
            rows = [j for j in joined
                    if j["cohort"] == monday and j["funnel"] == funnel
                    and j["source"] == "user"]
            if not rows:
                continue
            n = len(rows)
            succ = sum(1 for j in rows
                       if j["terminal"] and TERMINALS[j["terminal"]["event"]][1])
            fail = sum(1 for j in rows
                       if j["terminal"] and not TERMINALS[j["terminal"]["event"]][1])
            aband = n - succ - fail
            late = sum(j["late_terminals"] for j in rows)
            line = (f"  {funnel:8s} started={n} success={succ} "
                    f"failed={fail} abandoned={aband}")
            if late:
                line += f" late_terminals={late}"
            if is_fin and n:
                kind = {"resolve": "success rate",
                        "download": "delivery rate",
                        "convert": "completion rate"}[funnel]
                line += f"  {kind}={succ / n:.1%}"
            print(line)

    # ---- breakdowns (all events, split by source; user shown first)
    def breakdown(title, keyfn, source):
        counts = Counter()
        for e in events:
            if (e.get("source") or "user") != source:
                continue
            k = keyfn(e)
            if k:
                counts[k] += 1
        if counts:
            print(f"\n== {title} (source={source}) ==")
            for k, n in counts.most_common(25):
                print(f"  {k}: {n}")

    for source in ("user", "synthetic", "test"):
        breakdown(f"by page slug", lambda e: e.get("page_slug"), source)
        breakdown(f"by platform", lambda e: e.get("platform"), source)
        breakdown(f"failures by reason",
                  lambda e: (f'{e["event"]}:{e.get("reason")}'
                             if e.get("event", "").endswith("_failed") else None),
                  source)
        breakdown(f"by referrer host", lambda e: e.get("referrer_host"), source)
        breakdown(f"YouTube distinct videos (video_id_hash)",
                  lambda e: (e.get("video_id_hash")
                             if e.get("event") == "resolve_started" else None),
                  source)
    return 0


if __name__ == "__main__":
    sys.exit(main())
