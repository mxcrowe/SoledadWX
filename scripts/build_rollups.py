"""
Materialize daily_rollups from the canonical view.

The canonical_observations view resolves priorities at query time, which is
correct but slow for multi-year scans (~11 s for 17 years). This table trades
freshness for speed: one row per (metric, LOCAL civil day) with avg/min/max/count
and the timestamps of the min and max. The Analyst UI reads rollups for buckets
>= 1 day and the live view for finer resolutions.

DAY BOUNDARY (decided Jul 24 2026): days are bucketed on the station's CIVIL
LOCAL time (America/Los_Angeles, DST-aware), NOT UTC. The station sits at
117deg 14' 26" W / 32.8192 N, so a UTC day would run 17:00-17:00 local and
amputate the evening of every day -- measured error was up to +5.2 F on daily
max temp (a warm evening bleeding onto the next date) and +/-11% on integrated
solar energy. Civil local also matches Cumulus, and matches the live Rust
paths, which already use local_midnight_epoch(). One definition everywhere.

Caveat: DST transition days are 23 h and 25 h long. Harmless for max/min/avg
(a max over a 23 h day is still that day's max), but integrated quantities
(solar energy, wind run) on those two dates a year are not comparable to
their neighbours. Those are computed live in Rust, not from this table.

Rebuild is full (DELETE + INSERT) — takes ~seconds-to-a-minute and runs after
any import. Re-run me whenever sources change.

Usage:
    python scripts/build_rollups.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wxdb

# The station's civil timezone. Day buckets are anchored here, not to UTC and
# not to whatever machine happens to run this script (see check_timezone).
STATION_TZ = "America/Los_Angeles"

DDL = """
CREATE TABLE IF NOT EXISTS daily_rollups (
    metric_id INTEGER NOT NULL REFERENCES metrics(id),
    day_local TEXT NOT NULL,          -- ISO date, station civil local time
    avg_value REAL NOT NULL,
    min_value REAL NOT NULL,
    max_value REAL NOT NULL,
    n_samples INTEGER NOT NULL,
    ts_min    INTEGER NOT NULL,       -- epoch of the minimum reading
    ts_max    INTEGER NOT NULL,       -- epoch of the maximum reading
    PRIMARY KEY (metric_id, day_local)
) WITHOUT ROWID;
"""


def check_timezone(conn) -> None:
    """Fail loudly unless SQLite's 'localtime' == the station's civil time.

    We bucket with SQLite's 'localtime' modifier because it is fast (C-level,
    over ~17M rows). But that follows the MACHINE's timezone, which is an
    implicit dependency. Verify it against the IANA rules for STATION_TZ at
    DST boundaries before trusting it; a machine in another zone would
    silently produce a subtly wrong archive, which is exactly the class of
    bug this change exists to kill.
    """
    import datetime as dt
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(STATION_TZ)
    probes = [
        int(dt.datetime(y, mo, d, hh, 30, tzinfo=dt.timezone.utc).timestamp())
        for y in range(2009, dt.date.today().year + 2)
        for mo, d in ((3, 8), (3, 9), (11, 1), (11, 2), (7, 4), (1, 15))
        for hh in (6, 7, 8, 9, 15, 23)
    ]
    for ts in probes:
        got = conn.execute("SELECT date(?,'unixepoch','localtime')", (ts,)).fetchone()[0]
        want = dt.datetime.fromtimestamp(ts, tz).date().isoformat()
        if got != want:
            raise SystemExit(
                f"Timezone mismatch: this machine buckets epoch {ts} as {got}, "
                f"but {STATION_TZ} says {want}. Run this on a machine set to "
                f"{STATION_TZ}, or rewrite the bucketing to use zoneinfo."
            )
    print(f"timezone check: SQLite localtime == {STATION_TZ} "
          f"across {len(probes)} instants incl. DST transitions")


def main() -> int:
    conn = wxdb.get_conn()
    wxdb.ensure_schema(conn)
    check_timezone(conn)

    # Migrate off the old UTC-keyed schema. daily_rollups is a pure derived
    # cache -- everything in it is recomputed below from observations -- so
    # dropping it loses nothing that cannot be rebuilt.
    cols = [r[1] for r in conn.execute("PRAGMA table_info(daily_rollups)")]
    if cols and "day_local" not in cols:
        print(f"migrating daily_rollups: {cols[1]} -> day_local (UTC days -> civil local days)")
        conn.execute("DROP TABLE daily_rollups")
    conn.executescript(DDL)

    t0 = time.time()
    conn.execute("DELETE FROM daily_rollups")
    # Materialize the canonical view once — correlated lookups against the
    # view itself would re-resolve source priorities per row.
    conn.execute(
        "CREATE TEMP TABLE snap AS "
        "SELECT metric_id, ts_utc, date(ts_utc,'unixepoch','localtime') AS day_local, value "
        "FROM canonical_observations"
    )
    conn.execute("CREATE INDEX snap_idx ON snap(metric_id, day_local, value)")
    conn.execute(
        """
        INSERT INTO daily_rollups
        SELECT s.metric_id, s.day_local,
               AVG(s.value), MIN(s.value), MAX(s.value), COUNT(*),
               0, 0
        FROM snap s
        GROUP BY s.metric_id, s.day_local
        """
    )
    conn.execute(
        """
        UPDATE daily_rollups AS r SET
          ts_min = (SELECT MIN(s.ts_utc) FROM snap s
                    WHERE s.metric_id=r.metric_id AND s.day_local=r.day_local
                      AND s.value=r.min_value),
          ts_max = (SELECT MIN(s.ts_utc) FROM snap s
                    WHERE s.metric_id=r.metric_id AND s.day_local=r.day_local
                      AND s.value=r.max_value)
        """
    )
    conn.commit()
    n = conn.execute("SELECT COUNT(*) FROM daily_rollups").fetchone()[0]
    print(f"daily_rollups: {n:,} rows in {time.time() - t0:.1f}s")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
