"""
Correction for the rain gauge blockage of 16 Nov 2026 and the test of 17 Nov.

What happened (Michael, 2026-11-17): about 0.78 in fell on the evening of
16 Nov (two neighbours, KCASANDI4366 and KCASANDI84, agree to the hundredth),
but our tipping bucket recorded 0.06 in: something in the funnel held the
water back. Next morning Michael climbed up, freed the bucket with a length of
wire and poured in water to test it, and the station reported 0.13 in of rain
that never fell (09:14-09:31 local).

This script, in three parts (each guarded in data_corrections):

1. test_rain  Sets the morning test aside: rain rate (hourlyrainin) zeroed for
              09:14-09:45, and 0.13 in taken off the day's running total
              (dailyrainin) from 09:14 until 13:34, never below zero, when
              Michael zeroed the console's day total. Re-runnable: it only
              touches rows in that window still above zero.
              The weekly, monthly and yearly counters are NOT touched here: the
              station itself carries those forward (see BACKLOG).
2. faulty     Marks our gauge's dailyrainin and hourlyrainin as unusable for the
              whole local day of 16 Nov, for both live sources. With
              charts_fallback = 1, charts let another source take over, and
              rollups set our readings aside, as for the Zephyr hygrometer.
3. borrowed   Adds KCASANDI4366's readings for that day as its own source
              (wu_ksandi4366), ranked below everything on site, and ranks that
              source for the current era so it can surface. Its raw JSON is
              kept in Legacy/WU-Neighbors/KCASANDI4366/.

4. totals    Weekly, monthly and yearly rain corrected from the storm until
              13:34 on 17 Nov, when Michael set the console's counters right
              (0.00 / 0.78 / 1.35 / 7.11) in its Calibration mode.

Before anything changes, the rows it will alter are saved to
data/corrections/rain_2026_11_16_before.json, so all of it can be undone.

Usage:
    python scripts/fix_rain_2026_11_16.py [--dry-run]
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wxdb

LIVE = ("amb_rest", "amb_ws")
TEST_START = int(datetime(2026, 11, 17, 9, 14).timestamp())   # local time on this machine
TEST_RATE_END = int(datetime(2026, 11, 17, 9, 45).timestamp())
TEST_DAY_END = int(datetime(2026, 11, 17, 13, 34).timestamp())   # Michael zeroed the console's day total then
TEST_RAIN = 0.13
STORM_DAY = (int(datetime(2026, 11, 16, 0, 0).timestamp()), int(datetime(2026, 11, 17, 0, 0).timestamp()))
NEIGHBOUR, NEIGHBOUR_KIND = "KCASANDI4366", "wu_ksandi4366"
NEIGHBOUR_JSON = wxdb.ROOT / "Legacy" / "WU-Neighbors" / NEIGHBOUR / f"{NEIGHBOUR}_20261116.json"
FETCHED = Path(sys.argv[sys.argv.index("--json") + 1]) if "--json" in sys.argv else None
SNAPSHOT = wxdb.ROOT / "data" / "corrections" / "rain_2026_11_16_before.json"
SNAPSHOT_TOTALS = wxdb.ROOT / "data" / "corrections" / "rain_totals_2026_11_16_before.json"
CONSOLE_FIXED = TEST_DAY_END   # first reading with Michael's corrected totals
REASON = "rain gauge blocked during the 16 Nov 2026 storm (0.06 of about 0.78 in); KCASANDI4366 used for the day"


def ids(conn, table: str, column: str, names) -> dict[str, int]:
    marks = ",".join("?" * len(names))
    return dict(conn.execute(f"SELECT {column}, id FROM {table} WHERE {column} IN ({marks})", tuple(names)))


def done(conn, name: str) -> bool:
    return conn.execute("SELECT 1 FROM data_corrections WHERE name=?", (name,)).fetchone() is not None


def main() -> int:
    dry = "--dry-run" in sys.argv
    conn = wxdb.get_conn()
    conn.execute("PRAGMA busy_timeout = 10000")     # the Monitor is writing too
    metric = ids(conn, "metrics", "name", ("dailyrainin", "hourlyrainin"))
    live = list(ids(conn, "sources", "kind", LIVE).values())
    src = ids(conn, "sources", "kind", (NEIGHBOUR_KIND,))[NEIGHBOUR_KIND]
    live_marks = ",".join("?" * len(live))

    # ---- What will change, saved first ---------------------------------------
    rate_rows = conn.execute(
        f"SELECT metric_id, ts_utc, source_id, value FROM observations WHERE metric_id=? AND source_id IN ({live_marks})"
        " AND ts_utc >= ? AND ts_utc < ? AND value > 0", (metric["hourlyrainin"], *live, TEST_START, TEST_RATE_END)).fetchall()
    day_rows = conn.execute(
        f"SELECT metric_id, ts_utc, source_id, value FROM observations WHERE metric_id=? AND source_id IN ({live_marks})"
        " AND ts_utc >= ? AND ts_utc < ? AND value > 0", (metric["dailyrainin"], *live, TEST_START, TEST_DAY_END)).fetchall()
    print(f"test rain: {len(rate_rows)} rate rows to zero, {len(day_rows)} daily-total rows to reduce by {TEST_RAIN}")

    source_json = FETCHED or NEIGHBOUR_JSON
    obs = json.loads(source_json.read_text())["observations"]
    borrowed = []
    for o in obs:
        t = int(o["epoch"])
        if not STORM_DAY[0] <= t < STORM_DAY[1]:
            continue
        imp = o.get("imperial") or {}
        for name, field in (("dailyrainin", "precipTotal"), ("hourlyrainin", "precipRate")):
            if imp.get(field) is not None:
                borrowed.append((metric[name], t, src, float(imp[field])))
    total = max((v for m, _, _, v in borrowed if m == metric["dailyrainin"]), default=0.0)
    print(f"borrowed: {len(borrowed)} rows from {NEIGHBOUR}, day total {total:.2f} in")
    if dry:
        print("DRY RUN: nothing changed")
        return 0

    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    if not SNAPSHOT.exists():
        SNAPSHOT.write_text(json.dumps({"columns": ["metric_id", "ts_utc", "source_id", "value"],
                                        "rate_rows": rate_rows, "day_rows": day_rows}, indent=1))
    if FETCHED and not NEIGHBOUR_JSON.exists():
        NEIGHBOUR_JSON.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FETCHED, NEIGHBOUR_JSON)

    with conn:
        # 1. The test.
        conn.execute(
            f"UPDATE observations SET value = 0 WHERE metric_id=? AND source_id IN ({live_marks})"
            " AND ts_utc >= ? AND ts_utc < ? AND value > 0", (metric["hourlyrainin"], *live, TEST_START, TEST_RATE_END))
        conn.execute(
            f"UPDATE observations SET value = max(0, round(value - ?, 2)) WHERE metric_id=? AND source_id IN ({live_marks})"
            " AND ts_utc >= ? AND ts_utc < ? AND value > 0", (TEST_RAIN, metric["dailyrainin"], *live, TEST_START, TEST_DAY_END))
        conn.execute("INSERT OR REPLACE INTO data_corrections(name, applied_at, note) VALUES (?, strftime('%s','now'), ?)",
                     ("rain_test_2026_11_17_v1",
                      f"17 Nov test tips set aside: hourlyrainin zeroed 09:14-09:45, dailyrainin less {TEST_RAIN} from 09:14 "
                      f"(last run: {len(rate_rows)} + {len(day_rows)} rows); undo from {SNAPSHOT.name}"))

        # 2. The faulty gauge.
        if not done(conn, "rain_blocked_2026_11_16_v1"):
            cols = [r[1] for r in conn.execute("PRAGMA table_info(quality_periods)")]
            if "charts_fallback" not in cols:
                conn.execute("ALTER TABLE quality_periods ADD COLUMN charts_fallback INTEGER NOT NULL DEFAULT 0")
            for name in ("dailyrainin", "hourlyrainin"):
                for kind in LIVE:
                    conn.execute(
                        "INSERT OR REPLACE INTO quality_periods(metric, source_kind, period_start, period_end, reason,"
                        " charts_fallback) VALUES (?,?,?,?,?,1)", (name, kind, STORM_DAY[0], STORM_DAY[1], REASON))

            # 3. The borrowed rain, and a rank for its source in this era.
            conn.executemany("INSERT OR IGNORE INTO observations(metric_id, ts_utc, source_id, value) VALUES (?,?,?,?)",
                             borrowed)
            conn.execute("INSERT OR IGNORE INTO source_priority(period_start, period_end, source_kind, rank)"
                         " VALUES (?, NULL, ?, 6)", (int(datetime(2025, 8, 17, tzinfo=timezone.utc).timestamp()), NEIGHBOUR_KIND))
            conn.execute("INSERT INTO data_corrections(name, applied_at, note) VALUES (?, strftime('%s','now'), ?)",
                         ("rain_blocked_2026_11_16_v1",
                          f"16 Nov: our dailyrainin/hourlyrainin set aside (quality_periods, charts_fallback=1); "
                          f"{len(borrowed)} rows of {NEIGHBOUR} added as {NEIGHBOUR_KIND} (day total {total:.2f} in); "
                          f"{NEIGHBOUR_KIND} ranked 6 from 2025-08-17. Undo: delete those rows and periods."))

        # 4. The running totals, up to the moment Michael corrected the console.
        if not done(conn, "rain_totals_2026_11_16_v1"):
            fix_totals(conn, metric, live, src)

        # Days whose rollups must be worked out again (updates fire no trigger).
        for day in ("2026-11-16", "2026-11-17"):
            conn.execute("INSERT OR IGNORE INTO rollup_dirty(day_local) VALUES (?)", (day,))
    print("applied; the Monitor recomputes the two days' rollups on its next pass")
    return 0


def fix_totals(conn, metric: dict[str, int], live: list[int], src: int) -> None:
    """Weekly, monthly and yearly rain from the storm until the console was corrected.

    On the 16th: less what our gauge had caught so far that day, plus the
    neighbour's running total at that moment. On the 17th: plus 0.72 (0.78 less
    our 0.06) until the test, then plus 0.59 (less the 0.13 test as well).
    """
    totals = ids(conn, "metrics", "name", ("weeklyrainin", "monthlyrainin", "yearlyrainin"))
    live_marks = ",".join("?" * len(live))
    total_marks = ",".join("?" * len(totals))
    rows = conn.execute(
        f"SELECT metric_id, ts_utc, source_id, value FROM observations WHERE metric_id IN ({total_marks})"
        f" AND source_id IN ({live_marks}) AND ts_utc >= ? AND ts_utc < ?",
        (*totals.values(), *live, STORM_DAY[0], CONSOLE_FIXED)).fetchall()
    SNAPSHOT_TOTALS.write_text(json.dumps({"columns": ["metric_id", "ts_utc", "source_id", "value"], "rows": rows}))

    def latest(metric_id: int, source_id: int, t: int) -> float:
        r = conn.execute("SELECT value FROM observations WHERE metric_id=? AND source_id=? AND ts_utc <= ?"
                         " AND ts_utc >= ? ORDER BY ts_utc DESC LIMIT 1",
                         (metric_id, source_id, t, STORM_DAY[0])).fetchone()
        return r[0] if r else 0.0

    updates = []
    for m, t, s, v in rows:
        if t < STORM_DAY[1]:
            shift = latest(metric["dailyrainin"], src, t) - latest(metric["dailyrainin"], s, t)
        elif t < TEST_START:
            shift = 0.72
        else:
            shift = 0.59
        updates.append((round(v + shift, 2), m, t, s))
    conn.executemany("UPDATE observations SET value=? WHERE metric_id=? AND ts_utc=? AND source_id=?", updates)
    conn.execute("INSERT INTO data_corrections(name, applied_at, note) VALUES (?, strftime('%s','now'), ?)",
                 ("rain_totals_2026_11_16_v1",
                  f"weekly/monthly/yearly rain corrected for {len(updates)} rows, 16 Nov 00:00 to 17 Nov 13:34 "
                  f"(console totals reset by Michael at 13:34); undo from {SNAPSHOT_TOTALS.name}"))
    print(f"running totals: {len(updates)} rows corrected")


if __name__ == "__main__":
    raise SystemExit(main())
