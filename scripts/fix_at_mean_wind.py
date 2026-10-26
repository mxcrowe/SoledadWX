"""
Recompute stored apparent temperature with the 10-minute mean wind.

WHY. AT was derived from each reading's own wind speed. The BOM formula is
calibrated against AVERAGE wind, and on this ridge one-minute wind swings
8 -> 17 mph, so AT jumped up to 4 F in a minute while the thermometer sat
still (Michael spotted it on the Charts page, 2026-10-26). The live recorder
and derive_apparent_temp.py now use the mean over (ts - 600, ts] of the same
source; this brings the rows already stored into line.

WHAT IT TOUCHES. Only `apparenttempf`, and never source 1: Cumulus logged its
own AT, and its wind column is already an interval average, so its values are
consistent as they stand. Sources sampling every 10 minutes or less often
(MSDSD) have one reading in the window, so they come out unchanged.

SAFE. AT is derived, never measured: every value is recomputed from inputs
still stored, so nothing is lost. Inverse: recompute with each reading's own
wind (the pre-2026-10-26 derive_apparent_temp.py). Guarded by a
`data_corrections` row so it applies once.

After running:  python scripts/build_rollups.py

Usage:
    python scripts/fix_at_mean_wind.py [--dry-run]
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wxdb
from derive_apparent_temp import BOUNDS, apparent_temp_f, rolling_mean_wind

CORRECTION = "apparent_temp_mean_wind_v1"


def main() -> int:
    dry = "--dry-run" in sys.argv
    conn = wxdb.get_conn()
    conn.execute("PRAGMA busy_timeout=10000")
    if conn.execute("SELECT 1 FROM data_corrections WHERE name=?", (CORRECTION,)).fetchone():
        print(f"{CORRECTION} already applied; nothing to do.")
        return 0
    mids = wxdb.metric_ids(conn)
    at = mids["apparenttempf"]
    sources = [r[0] for r in conn.execute(
        "SELECT DISTINCT source_id FROM observations WHERE metric_id=? AND source_id<>1", (at,))]

    total = 0
    for sid in sorted(sources):
        rows = conn.execute(
            """SELECT o.ts_utc,
                 MAX(CASE WHEN o.metric_id=? THEN o.value END),
                 MAX(CASE WHEN o.metric_id=? THEN o.value END),
                 MAX(CASE WHEN o.metric_id=? THEN o.value END),
                 MAX(CASE WHEN o.metric_id=? THEN o.value END)
               FROM observations o
               WHERE o.source_id=? AND o.metric_id IN (?,?,?,?)
               GROUP BY o.ts_utc ORDER BY o.ts_utc""",
            (mids["tempf"], mids["humidity"], mids["windspeedmph"], at,
             sid, mids["tempf"], mids["humidity"], mids["windspeedmph"], at),
        ).fetchall()
        means = rolling_mean_wind((r[0], r[3]) for r in rows)
        updates, worst = [], 0.0
        for (ts, t, rh, _w, old), w_mean in zip(rows, means):
            if old is None:
                continue
            new = apparent_temp_f(t, rh, w_mean)
            lo, hi = BOUNDS["apparenttempf"]
            if new is None or not (lo <= new <= hi) or abs(new - old) < 1e-9:
                continue
            worst = max(worst, abs(new - old))
            updates.append((new, at, ts, sid))
        if not dry:
            t0 = time.time()
            for i in range(0, len(updates), 20000):
                conn.executemany(
                    "UPDATE observations SET value=? WHERE metric_id=? AND ts_utc=? AND source_id=?",
                    updates[i:i + 20000])
                conn.commit()
        total += len(updates)
        print(f"  source {sid:2}: {len(updates):>9,} AT rows change, largest {worst:5.2f} F"
              + ("  (dry run)" if dry else ""))

    if not dry:
        conn.execute(
            "INSERT INTO data_corrections(name, applied_at, note) VALUES (?,?,?)",
            (CORRECTION, int(time.time()),
             f"apparenttempf recomputed with 10-min mean wind ({total:,} rows, sources <> 1); "
             "invert by recomputing with each reading's own wind"))
        conn.commit()
        print(f"\n{total:,} rows updated.\n\nNow re-run:  python scripts/build_rollups.py")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
