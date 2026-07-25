"""
One-time correction: Cumulus-era (source 1) wind was imported as mph but is knots.

Cumulus writes its log files in DISPLAY units, not base units. This station's
Cumulus displayed knots (cumulus.ini WindUnit=3; Diags print "WindUnit=kts"),
so every wind value imported from Sep 2009 - Aug 2018 is understated by
1.150779448. Temperature, rain and pressure were assumed correctly.

Confirmed against the archive's own physics before running -- recomputing
Cumulus's OWN logged wind chill (712 rows) and apparent temperature (76,091
rows) from the logged temp/humidity/wind reproduces them to ~0.04 F under the
knots reading, vs ~0.33-0.47 F under mph.

This is NOT visible as a step at the 2018 changeover: source_priority gives
each era one source, so the Cumulus era never overlaps an mph-native source.

Scope:
  observations     source_id=1, metric windspeedmph + windgustmph   x1.150779
  daily_summaries  source_id=1, max_gust_mph, high_avg_wind_mph     x1.150779
                                wind_run_mi (nautical -> statute mi) x1.150779
  winddir is degrees and is NOT touched.

Guarded: records itself in data_corrections and refuses to run twice.
Exactly invertible (divide by the same constant) if it ever needs undoing.

After running:  python scripts/build_rollups.py

Usage:
    python scripts/fix_cumulus_knots.py [--dry-run]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wxdb

KNOTS_TO_MPH = 1.150779448023542
CORRECTION = "cumulus_knots_to_mph_v1"

GUARD_DDL = """
CREATE TABLE IF NOT EXISTS data_corrections (
    name       TEXT PRIMARY KEY,
    applied_at INTEGER NOT NULL,
    note       TEXT
);
"""


def main() -> int:
    dry = "--dry-run" in sys.argv
    conn = wxdb.get_conn()
    conn.executescript(GUARD_DDL)

    if conn.execute(
        "SELECT 1 FROM data_corrections WHERE name=?", (CORRECTION,)
    ).fetchone():
        print(f"'{CORRECTION}' already applied — nothing to do.")
        return 0

    wind_ids = [
        r[0]
        for r in conn.execute(
            "SELECT id FROM metrics WHERE name IN ('windspeedmph','windgustmph')"
        )
    ]
    qmarks = ",".join("?" * len(wind_ids))

    before = conn.execute(
        f"SELECT COUNT(*), AVG(value), MAX(value) FROM observations "
        f"WHERE source_id=1 AND metric_id IN ({qmarks})",
        wind_ids,
    ).fetchone()
    print(f"observations  before: n={before[0]:,}  avg={before[1]:.4f}  max={before[2]:.2f}")

    if dry:
        print(f"DRY RUN — would multiply by {KNOTS_TO_MPH}")
        print(f"              -> avg={before[1]*KNOTS_TO_MPH:.4f}  max={before[2]*KNOTS_TO_MPH:.2f}")
        return 0

    conn.execute(
        f"UPDATE observations SET value = value * ? "
        f"WHERE source_id=1 AND metric_id IN ({qmarks})",
        [KNOTS_TO_MPH, *wind_ids],
    )
    conn.execute(
        "UPDATE daily_summaries SET "
        "  max_gust_mph      = max_gust_mph      * ?1, "
        "  high_avg_wind_mph = high_avg_wind_mph * ?1, "
        "  wind_run_mi       = wind_run_mi       * ?1 "
        "WHERE source_id = 1",
        (KNOTS_TO_MPH,),
    )
    conn.execute(
        "INSERT INTO data_corrections(name, applied_at, note) "
        "VALUES (?, strftime('%s','now'), ?)",
        (CORRECTION, f"source 1 wind x{KNOTS_TO_MPH} (knots->mph); invert by dividing"),
    )
    conn.commit()

    after = conn.execute(
        f"SELECT COUNT(*), AVG(value), MAX(value) FROM observations "
        f"WHERE source_id=1 AND metric_id IN ({qmarks})",
        wind_ids,
    ).fetchone()
    print(f"observations   after: n={after[0]:,}  avg={after[1]:.4f}  max={after[2]:.2f}")
    print(f"ratio applied: {after[1]/before[1]:.9f}  (expected {KNOTS_TO_MPH})")
    print("\nNow re-run:  python scripts/build_rollups.py")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
