"""
Materialize daily_rollups from the canonical view.

The canonical_observations view resolves priorities at query time, which is
correct but slow for multi-year scans (~11 s for 17 years). This table trades
freshness for speed: one row per (metric, UTC day) with avg/min/max/count and
the timestamps of the min and max. The Analyst UI reads rollups for buckets
>= 1 day and the live view for finer resolutions.

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

DDL = """
CREATE TABLE IF NOT EXISTS daily_rollups (
    metric_id INTEGER NOT NULL REFERENCES metrics(id),
    day_utc   TEXT NOT NULL,          -- ISO date, UTC
    avg_value REAL NOT NULL,
    min_value REAL NOT NULL,
    max_value REAL NOT NULL,
    n_samples INTEGER NOT NULL,
    ts_min    INTEGER NOT NULL,       -- epoch of the minimum reading
    ts_max    INTEGER NOT NULL,       -- epoch of the maximum reading
    PRIMARY KEY (metric_id, day_utc)
) WITHOUT ROWID;
"""


def main() -> int:
    conn = wxdb.get_conn()
    wxdb.ensure_schema(conn)
    conn.executescript(DDL)

    t0 = time.time()
    conn.execute("DELETE FROM daily_rollups")
    # Materialize the canonical view once — correlated lookups against the
    # view itself would re-resolve source priorities per row.
    conn.execute(
        "CREATE TEMP TABLE snap AS "
        "SELECT metric_id, ts_utc, date(ts_utc,'unixepoch') AS day_utc, value "
        "FROM canonical_observations"
    )
    conn.execute("CREATE INDEX snap_idx ON snap(metric_id, day_utc, value)")
    conn.execute(
        """
        INSERT INTO daily_rollups
        SELECT s.metric_id, s.day_utc,
               AVG(s.value), MIN(s.value), MAX(s.value), COUNT(*),
               0, 0
        FROM snap s
        GROUP BY s.metric_id, s.day_utc
        """
    )
    conn.execute(
        """
        UPDATE daily_rollups AS r SET
          ts_min = (SELECT MIN(s.ts_utc) FROM snap s
                    WHERE s.metric_id=r.metric_id AND s.day_utc=r.day_utc
                      AND s.value=r.min_value),
          ts_max = (SELECT MIN(s.ts_utc) FROM snap s
                    WHERE s.metric_id=r.metric_id AND s.day_utc=r.day_utc
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
