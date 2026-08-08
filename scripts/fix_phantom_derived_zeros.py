"""
One-time correction: delete phantom 0.0 windchillf / heatindexf rows (source 1).

Cumulus wrote 0.0 rather than leaving the field empty when wind chill or heat
index was undefined (the same pathology as its 259,412 phantom solar/UV zeros).
There are only 14 of each — 0.0014% of the wind-chill data — but because a
record is a MAX/MIN, that is more than enough to own it outright: the all-time
"Lowest wind chill" read 0.0 F, in La Jolla, in April.

This is the cleanest possible illustration of the extremes doctrine: bad data
does not need to be common to win a record, only to exist once, pointing the
right way.

Empty != zero. A 0.0 F wind chill asserts a measurement that was never made,
so these rows are deleted rather than kept. The underlying tempf/windspeedmph
readings are untouched, so the values remain derivable if ever wanted.

NOTE this does not make those two records trustworthy — Zephyr-era humidity is
independently unreliable (see BACKLOG). It only removes readings that are
definitionally not measurements.

Guarded via data_corrections; refuses to run twice.

After running:  python scripts/build_rollups.py

Usage:
    python scripts/fix_phantom_derived_zeros.py [--dry-run]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wxdb

CORRECTION = "phantom_derived_zeros_v1"
METRICS = ("windchillf", "heatindexf")


def main() -> int:
    dry = "--dry-run" in sys.argv
    conn = wxdb.get_conn()
    conn.executescript(
        "CREATE TABLE IF NOT EXISTS data_corrections ("
        " name TEXT PRIMARY KEY, applied_at INTEGER NOT NULL, note TEXT);"
    )
    if conn.execute(
        "SELECT 1 FROM data_corrections WHERE name=?", (CORRECTION,)
    ).fetchone():
        print(f"'{CORRECTION}' already applied — nothing to do.")
        return 0

    qmarks = ",".join("?" * len(METRICS))
    where = (
        f"source_id = 1 AND value = 0.0 AND metric_id IN "
        f"(SELECT id FROM metrics WHERE name IN ({qmarks}))"
    )
    rows = conn.execute(
        f"SELECT m.name, COUNT(*) FROM observations o JOIN metrics m ON m.id=o.metric_id "
        f"WHERE {where} GROUP BY m.name",
        METRICS,
    ).fetchall()
    total = sum(n for _, n in rows)
    for name, n in rows:
        print(f"  {name:12} {n:,} phantom zeros")
    if total == 0:
        print("nothing to delete.")
        return 0

    if dry:
        print(f"DRY RUN — would delete {total:,} rows")
        return 0

    conn.execute(f"DELETE FROM observations WHERE {where}", METRICS)
    conn.execute(
        "INSERT INTO data_corrections(name, applied_at, note) VALUES (?, strftime('%s','now'), ?)",
        (CORRECTION, f"deleted {total} phantom 0.0 rows for {'/'.join(METRICS)} (source 1)"),
    )
    conn.commit()
    print(f"deleted {total:,} rows.\n\nNow re-run:  python scripts/build_rollups.py")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
