"""
Import MSDSD (Mt. Soledad mesonet, SDG&E) CSV exports from Synoptic/MesoWest.

MSDSD sits **559 m** from the station on the same ridge, 187 ft lower, and
reports at a 10-minute cadence with an essentially unbroken record from
2011-09-28. That makes it the best available reference for this site — an
order of magnitude closer than KSAN (~10 km, 500 ft lower, different
microclimate).

WHY THIS MATTERS: the Zephyr-era hygrometer failed progressively (see
BACKLOG ★). Its humidity — and everything derived from it: dewpointf,
heatindexf, feelslikef — is untrustworthy from roughly 2011 onward, and the
failure was invisible because source_priority gives each era exactly one
source, so there was nothing to compare against. MSDSD supplies that missing
witness for 2011-2018.

REFERENCE, NOT REPLACEMENT. These rows are deliberately inert: the
`canonical_observations` view only considers a source inside a period that
`source_priority` covers, and `msdsd` is ranked only for 2018-09 -> 2020-04.
So importing 2011-2018 changes NO canonical value and no rollup — the data is
available for comparison and stays out of the way until someone deliberately
adds a priority row. The user's own instrument remains authoritative.

Source file: a Synoptic CSV export with '#' comment header, one units row
under the header, and ISO-8601 timestamps carrying their UTC offset inline
(e.g. 2018-08-31T04:40:00-0700), so there is no timezone ambiguity to guess.

Units in the export are METRIC; the archive's canonical units are imperial,
so we convert on the way in and record the fact loudly. (Storing display
units is what cost this project nine years of understated wind.)

    air_temp                     Celsius -> tempf        (F)
    dew_point_temperature_set_1d Celsius -> dewpointf    (F)   [derived col]
    relative_humidity            %       -> humidity     (%)   [no conversion]
    wind_speed                   m/s     -> windspeedmph (mph)
    wind_direction               degrees -> winddir      (deg) [no conversion]

solar_radiation is present but only ~0.5% filled, and cross-source solar is
known to be incomparable anyway — skipped.

Idempotent via INSERT OR IGNORE. Safe to re-run.

Usage:
    python scripts/import_msdsd.py <file.csv> [more.csv ...]
"""

from __future__ import annotations

import csv
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wxdb

MS_TO_MPH = 2.2369362920544


def c_to_f(v: float) -> float:
    return v * 9.0 / 5.0 + 32.0


# CSV column -> (canonical metric, converter)
COLUMN_MAP = {
    "air_temp_set_1": ("tempf", c_to_f),
    "dew_point_temperature_set_1d": ("dewpointf", c_to_f),
    "relative_humidity_set_1": ("humidity", float),
    "wind_speed_set_1": ("windspeedmph", lambda v: v * MS_TO_MPH),
    "wind_direction_set_1": ("winddir", float),
}

# Same spirit as the other importers: reject physically impossible values
# rather than letting a sensor fault become an all-time record.
BOUNDS = {
    "tempf": (20.0, 130.0),
    "dewpointf": (-40.0, 100.0),
    "humidity": (1.0, 100.0),
    "windspeedmph": (0.0, 150.0),
    "winddir": (0.0, 360.0),
}


def import_file(conn, path: Path) -> tuple[int, int, int]:
    mids = wxdb.metric_ids(conn)
    sid = wxdb.source_id(conn, "msdsd")

    with path.open(newline="", encoding="utf-8-sig") as fh:
        lines = [ln for ln in fh if not ln.startswith("#")]
    reader = csv.DictReader(lines)
    next(reader, None)  # the units row sitting under the header

    batch: list[tuple[int, int, int, float]] = []
    n_rows = n_bad = n_oob = inserted = 0
    for row in reader:
        stamp = (row.get("Date_Time") or "").strip()
        if not stamp:
            continue
        try:
            # ISO-8601 with offset -> true UTC epoch. No guessing.
            ts_utc = int(datetime.fromisoformat(stamp).timestamp())
        except ValueError:
            n_bad += 1
            continue
        n_rows += 1
        for col, (canon, conv) in COLUMN_MAP.items():
            cell = (row.get(col) or "").strip()
            if not cell:
                continue
            try:
                val = conv(float(cell))
            except (ValueError, TypeError):
                continue
            lo, hi = BOUNDS[canon]
            if not (lo <= val <= hi):
                n_oob += 1
                continue
            batch.append((mids[canon], ts_utc, sid, val))
        if len(batch) >= 20000:
            inserted += wxdb.insert_observations(conn, batch)
            batch.clear()
    if batch:
        inserted += wxdb.insert_observations(conn, batch)
    conn.commit()
    return n_rows, inserted, n_oob + n_bad


def main() -> int:
    files = [Path(a) for a in sys.argv[1:] if not a.startswith("-")]
    if not files:
        print(__doc__)
        return 2
    conn = wxdb.get_conn()
    wxdb.ensure_schema(conn)
    for f in files:
        if not f.exists():
            print(f"missing: {f}")
            continue
        rows, ins, skipped = import_file(conn, f)
        print(f"{f.name}: {rows:,} timestamps -> {ins:,} observations inserted ({skipped:,} skipped)")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
