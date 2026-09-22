"""
One-off archaeology: fill interior holes in the Ambient-sourced Archive.

WHY THIS IS SEPARATE FROM THE MONITOR. The Monitor's Backfill scans the last
30 days, deliberately — that is the right window for something that runs on a
timer every half hour. Reaching further back is an archaeology job with a
different shape: it runs once, it costs real API budget (Ambient allows ~1
request/second per key), and most of what it finds will be unfillable. So it
lives here, is run by hand, and is not on any schedule.

THE BUG THAT CREATED THESE HOLES (fixed 2026-09-22, commit 4efa1e2). Backfill
used to ask only "does the Archive reach the present?" — a MAX over the REST
and WebSocket sources. The Monitor survives sleep, so on wake the Recorder
resumed, pushed that MAX to now, and Backfill exited immediately with the
night's hole behind it. It saw TRAILING gaps perfectly and INTERIOR ones not
at all. Measured when found: 15 holes, 53.4 hours, across the previous year.

WHAT TO EXPECT. Much of this is probably NOT recoverable. A 31-hour hole
(2026-02-04) is almost certainly a power or internet outage, in which case the
station could not reach Ambient either and there is nothing in their cloud to
fetch. That is a fine outcome and the point of running it: `backfill_attempts`
records the empty result so nothing asks again, and the pattern of successes
tells us empirically where Ambient's retention actually ends — cheaper and
more reliable than taking their documentation's word for it.

Recovered rows arrive at REST cadence (5 min, and Ambient THINS older data to
10 min), not the 1/min the Recorder captures live. Completeness is restorable;
fidelity is not. See BACKLOG on the 24/7 recorder.

Idempotent: INSERT OR IGNORE. Safe to re-run — already-filled holes simply
stop being holes.

Usage:
    python scripts/sweep_gaps.py --dry-run          # list holes, fetch nothing
    python scripts/sweep_gaps.py                    # sweep the last 400 days
    python scripts/sweep_gaps.py --days 60          # narrower window
    python scripts/sweep_gaps.py --min-gap 30       # minutes; default 15
"""

from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wxdb
import rescue_ambient as amb
from import_ambient import KEY_MAP

SLEEP_SECONDS = 1.1     # Ambient asks for <= 1 req/sec per key
PAGE_LIMIT = 288
MAX_PAGES_PER_GAP = 400


def find_gaps(conn, days: int, min_gap_s: int):
    """Interior holes in the Ambient-sourced record, newest first.

    Mirrors db.rs::find_gaps. Uses tempf as the marker metric: it is present
    in every Ambient reading, so its timeline IS the reading timeline.
    """
    mids = wxdb.metric_ids(conn)
    now = int(time.time())
    rows = conn.execute(
        """SELECT prev_ts, ts_utc FROM (
               SELECT ts_utc, LAG(ts_utc) OVER (ORDER BY ts_utc) AS prev_ts
               FROM observations
               WHERE metric_id = ?1
                 AND source_id IN (SELECT id FROM sources
                                   WHERE kind IN ('amb_rest','amb_ws'))
                 AND ts_utc >= ?2
           )
           WHERE prev_ts IS NOT NULL AND ts_utc - prev_ts > ?3
           ORDER BY prev_ts DESC""",
        (mids["tempf"], now - days * 86400, min_gap_s),
    ).fetchall()
    return [(int(a), int(b)) for a, b in rows]


def fill_gap(conn, mac, api_key, app_key, gap, mids, sid) -> int:
    """Page backwards through one hole. Returns rows actually inserted."""
    start, end = gap
    end_ms, start_ms = end * 1000, start * 1000
    cursor = end_ms
    gained = 0
    for _ in range(MAX_PAGES_PER_GAP):
        try:
            page = amb.fetch_page(mac, api_key, app_key, cursor)
        except Exception as exc:                      # noqa: BLE001
            print(f"      fetch failed: {exc}")
            break
        if not page:
            break
        batch = []
        for rec in page:
            ts_ms = rec.get("dateutc")
            if ts_ms is None or ts_ms <= start_ms or ts_ms > end_ms:
                continue
            ts = ts_ms // 1000
            for key, canon in KEY_MAP.items():
                v = rec.get(key)
                if v is None or canon not in mids:
                    continue
                try:
                    batch.append((mids[canon], ts, sid, float(v)))
                except (TypeError, ValueError):
                    continue
        if batch:
            gained += wxdb.insert_observations(conn, batch)
            conn.commit()
        oldest = page[-1].get("dateutc", start_ms)
        if oldest <= start_ms:
            break
        cursor = oldest - 1
        time.sleep(SLEEP_SECONDS)
    return gained


def main() -> int:
    dry = "--dry-run" in sys.argv
    days = 400
    min_gap = 15
    if "--days" in sys.argv:
        days = int(sys.argv[sys.argv.index("--days") + 1])
    if "--min-gap" in sys.argv:
        min_gap = int(sys.argv[sys.argv.index("--min-gap") + 1])

    conn = wxdb.get_conn()
    wxdb.ensure_schema(conn)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS backfill_attempts (
               gap_start INTEGER PRIMARY KEY, gap_end INTEGER NOT NULL,
               last_attempt INTEGER NOT NULL, attempts INTEGER NOT NULL,
               rows_gained INTEGER NOT NULL) WITHOUT ROWID"""
    )
    conn.commit()

    gaps = find_gaps(conn, days, min_gap * 60)
    total_h = sum(b - a for a, b in gaps) / 3600
    print(f"{len(gaps)} hole(s) over {min_gap} min in the last {days} days — {total_h:.1f} h\n")
    for a, b in gaps:
        print(f"   {datetime.fromtimestamp(a):%Y-%m-%d %H:%M} -> "
              f"{datetime.fromtimestamp(b):%m-%d %H:%M}   {(b - a) // 60:>5} min")
    if dry or not gaps:
        print("\n(dry run — nothing fetched)" if dry else "\nnothing to do")
        return 0

    env = amb.load_env()
    api_key, app_key = env["AMBIENT_API_KEY"], env["AMBIENT_APP_KEY"]
    devices = amb.get_devices(api_key, app_key)
    if not devices:
        print("no devices returned")
        return 1
    mac = devices[0]["macAddress"]
    time.sleep(SLEEP_SECONDS)

    mids = wxdb.metric_ids(conn)
    sid = wxdb.source_id(conn, "amb_rest")

    print(f"\nsweeping (1 req/{SLEEP_SECONDS}s)…\n")
    filled = barren = 0
    recovered = 0
    for gap in gaps:
        a, b = gap
        label = f"{datetime.fromtimestamp(a):%Y-%m-%d %H:%M} ({(b - a) // 60} min)"
        gained = fill_gap(conn, mac, api_key, app_key, gap, mids, sid)
        conn.execute(
            """INSERT INTO backfill_attempts
                   (gap_start, gap_end, last_attempt, attempts, rows_gained)
               VALUES (?1, ?2, ?3, 1, ?4)
               ON CONFLICT(gap_start) DO UPDATE SET
                   gap_end=excluded.gap_end, last_attempt=excluded.last_attempt,
                   attempts=attempts+1, rows_gained=excluded.rows_gained""",
            (a, b, int(time.time()), gained),
        )
        conn.commit()
        recovered += gained
        if gained:
            filled += 1
            print(f"   {label}: +{gained:,} values")
        else:
            barren += 1
            print(f"   {label}: nothing — Ambient has no data either")
        time.sleep(SLEEP_SECONDS)

    print(f"\n{filled} hole(s) yielded data, {barren} were barren, "
          f"{recovered:,} values recovered.")
    print("\nNow re-run:  python scripts/build_rollups.py"
          "\n(or just leave it — the Monitor's rollup refresher will pick the days up)")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
