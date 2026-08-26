"""
Derive the apparent-temperature family for the whole archive.

The live recorder computes apparenttempf / humidexf / wetbulbf at record time
(db.rs value_pairs), but that only reaches readings taken after the feature
existed. This script walks the historical observations and derives the same
three metrics from tempf + humidity + windspeedmph + dewpointf, per source,
at the source's own timestamps.

WHY PER SOURCE, AT ITS OWN TIMESTAMPS: writing derived rows on a grid the
source never sampled would inject observations that no instrument made — the
same additive trap that made MSDSD gap-fill silently rewrite 2011-2017
minima. A derived row here is written ONLY where the inputs it needs already
exist at that exact ts_utc, for that same source_id. Nothing is interpolated.

Formulas are bit-for-bit the ones in db.rs / astro.ts. If you change one,
change all three.

    apparenttempf  Australian BOM AT. Defined at every temperature, and the
                   only one that sees wind. Missing wind is treated as calm.
    humidexf       Environment Canada humidex. None below a 10 C dewpoint.
    wetbulbf       Stull (2011). None outside 5-99% RH or -20..50 C.

HONESTY NOTE: these inherit their inputs' quality. Humidity before ~2019 is
distorted by a slope error in the hygrometer (see BACKLOG), so humidex and
wet bulb for source 1 are as wrong as the humidity that fed them. That is a
reason to FLAG, not to skip — the numbers are reproducible from stored
inputs and deleting them would only hide the problem.

Idempotent via INSERT OR IGNORE. Safe to re-run.

After running:  python scripts/build_rollups.py

Usage:
    python scripts/derive_apparent_temp.py [--source N] [--dry-run]
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wxdb

MPH_TO_MS = 0.44704


def sat_vp_hpa(tc: float) -> float:
    return 6.112 * math.exp((17.67 * tc) / (tc + 243.5))


def apparent_temp_f(t_f, rh, wind_mph):
    if t_f is None or rh is None:
        return None
    w_ms = (wind_mph or 0.0) * MPH_TO_MS
    tc = (t_f - 32.0) * 5.0 / 9.0
    e = (rh / 100.0) * sat_vp_hpa(tc)
    return (tc + 0.33 * e - 0.70 * w_ms - 4.00) * 9.0 / 5.0 + 32.0


def humidex_f(t_f, dew_f):
    if t_f is None or dew_f is None:
        return None
    dc = (dew_f - 32.0) * 5.0 / 9.0
    if dc < 10.0:
        return None
    tc = (t_f - 32.0) * 5.0 / 9.0
    e = 6.11 * math.exp(5417.7530 * (1.0 / 273.16 - 1.0 / (dc + 273.15)))
    return (tc + 0.5555 * (e - 10.0)) * 9.0 / 5.0 + 32.0


def wet_bulb_f(t_f, rh):
    if t_f is None or rh is None or not (5.0 <= rh <= 99.0):
        return None
    tc = (t_f - 32.0) * 5.0 / 9.0
    if not (-20.0 <= tc <= 50.0):
        return None
    wb = (
        tc * math.atan(0.151977 * math.sqrt(rh + 8.313659))
        + math.atan(tc + rh)
        - math.atan(rh - 1.676331)
        + 0.00391838 * rh ** 1.5 * math.atan(0.023101 * rh)
        - 4.686035
    )
    return wb * 9.0 / 5.0 + 32.0


# Physically impossible values are a sensor fault, not a record. Same spirit
# as the importers' BOUNDS.
BOUNDS = {"apparenttempf": (-40.0, 150.0), "humidexf": (-40.0, 160.0), "wetbulbf": (-40.0, 120.0)}


def main() -> int:
    dry = "--dry-run" in sys.argv
    only = None
    if "--source" in sys.argv:
        only = int(sys.argv[sys.argv.index("--source") + 1])

    conn = wxdb.get_conn()
    wxdb.ensure_schema(conn)
    for name, label in (("apparenttempf", "Apparent temperature"),
                        ("humidexf", "Humidex"),
                        ("wetbulbf", "Wet bulb")):
        conn.execute(
            "INSERT OR IGNORE INTO metrics(name, unit, label) VALUES (?,?,?)",
            (name, "F", label),
        )
    conn.commit()
    mids = wxdb.metric_ids(conn)

    srcs = [only] if only else [
        r[0] for r in conn.execute(
            "SELECT DISTINCT source_id FROM observations WHERE metric_id=?", (mids["tempf"],)
        )
    ]

    grand = 0
    for sid in sorted(srcs):
        # Pull the four inputs for this source and pivot them onto shared
        # timestamps. Only timestamps carrying tempf+humidity can produce
        # anything, so nothing is invented where the sensors were silent.
        rows = conn.execute(
            """SELECT o.ts_utc,
                 MAX(CASE WHEN o.metric_id=? THEN o.value END),
                 MAX(CASE WHEN o.metric_id=? THEN o.value END),
                 MAX(CASE WHEN o.metric_id=? THEN o.value END),
                 MAX(CASE WHEN o.metric_id=? THEN o.value END)
               FROM observations o
               WHERE o.source_id=? AND o.metric_id IN (?,?,?,?)
               GROUP BY o.ts_utc""",
            (mids["tempf"], mids["humidity"], mids["windspeedmph"], mids["dewpointf"],
             sid,
             mids["tempf"], mids["humidity"], mids["windspeedmph"], mids["dewpointf"]),
        ).fetchall()

        batch, made = [], 0
        for ts, t, rh, w, dew in rows:
            for name, val in (
                ("apparenttempf", apparent_temp_f(t, rh, w)),
                ("humidexf", humidex_f(t, dew)),
                ("wetbulbf", wet_bulb_f(t, rh)),
            ):
                if val is None:
                    continue
                lo, hi = BOUNDS[name]
                if not (lo <= val <= hi):
                    continue
                batch.append((mids[name], ts, sid, val))
            if len(batch) >= 20000 and not dry:
                made += wxdb.insert_observations(conn, batch)
                batch.clear()
        if dry:
            made = len(batch)
        elif batch:
            made += wxdb.insert_observations(conn, batch)
        conn.commit()
        grand += made
        print(f"  source {sid:2}: {len(rows):>9,} timestamps -> {made:>9,} derived rows"
              + ("  (dry run)" if dry else ""))

    print(f"\ntotal: {grand:,} rows"
          + ("" if dry else "\n\nNow re-run:  python scripts/build_rollups.py"))
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
