"""
Query layer: canonical series + on-demand resampling.

The archive preserves native resolution per source (ARCHITECTURE.md §3.4);
this module is the resampler that sits between the raw observations and any
consumer (Analyst UI, reports, the Oracle). Resolution is chosen at query
time, never baked in at ingest.

Usage as a library:
    from wxquery import series
    rows = series("tempf", "2010-01-01", "2010-02-01", bucket="1d")

Usage as a CLI (quick sanity checks):
    python scripts/wxquery.py tempf 2010-01-01 2010-02-01 1d
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wxdb

BUCKETS = {
    "raw": 0,
    "5m": 300, "20m": 1200, "1h": 3600, "3h": 10800,
    "1d": 86400, "1w": 604800, "30d": 2592000,
}


def _to_epoch(t: str | int | datetime) -> int:
    if isinstance(t, int):
        return t
    if isinstance(t, datetime):
        return int(t.timestamp())
    return int(datetime.fromisoformat(t).replace(tzinfo=timezone.utc).timestamp())


def series(
    metric: str,
    start: str | int | datetime,
    end: str | int | datetime,
    bucket: str = "1h",
    conn=None,
):
    """
    Canonical time series for a metric, resampled to `bucket`.

    Returns rows of (bucket_start_epoch, avg, min, max, n_samples).
    bucket="raw" returns native-resolution rows (ts, value, value, value, 1).
    """
    own = conn is None
    if own:
        conn = wxdb.get_conn()
    a, b = _to_epoch(start), _to_epoch(end)
    step = BUCKETS[bucket]

    if step == 0:
        q = """
            SELECT o.ts_utc, o.value, o.value, o.value, 1
            FROM canonical_observations o
            JOIN metrics m ON m.id = o.metric_id
            WHERE m.name = ? AND o.ts_utc >= ? AND o.ts_utc < ?
            ORDER BY o.ts_utc
        """
    else:
        q = f"""
            SELECT (o.ts_utc / {step}) * {step} AS bucket_start,
                   AVG(o.value), MIN(o.value), MAX(o.value), COUNT(*)
            FROM canonical_observations o
            JOIN metrics m ON m.id = o.metric_id
            WHERE m.name = ? AND o.ts_utc >= ? AND o.ts_utc < ?
            GROUP BY bucket_start
            ORDER BY bucket_start
        """
    rows = conn.execute(q, (metric, a, b)).fetchall()
    if own:
        conn.close()
    return rows


def main() -> int:
    metric, start, end = sys.argv[1], sys.argv[2], sys.argv[3]
    bucket = sys.argv[4] if len(sys.argv) > 4 else "1h"
    rows = series(metric, start, end, bucket)
    print(f"{'bucket_utc':20} {'avg':>8} {'min':>8} {'max':>8} {'n':>6}")
    for ts, avg, lo, hi, n in rows:
        stamp = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        print(f"{stamp:20} {avg:8.2f} {lo:8.2f} {hi:8.2f} {n:6}")
    print(f"({len(rows)} buckets)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
