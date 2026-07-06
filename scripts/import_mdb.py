"""
Import HP2000-history.mdb (EasyWeatherIP era, 2020-04-19 -> 2025-08-16).

Unit conversions were verified empirically against the AmbientWeather overlap
zone on 2025-08-16 (same physical weather, two independent recorders):
  - Temps:    raw/10 deg C  -> deg F          (209 -> 69.6F, Ambient: 69.4-69.6F)
  - Pressure: raw/10 hPa    -> inHg (x0.029530) (10129 -> 29.91, Ambient: 29.91 exact)
  - Wind:     raw/10 m/s    -> mph (x2.236936)  (gust value sets quantize identically)
  - Solar:    raw/10 lux    -> W/m2 (/126.7)    (698520 -> 551 W/m2, Ambient: 550.8)
  - Rain:     raw/10 mm     -> in (/25.4)
  - UVI:      raw uW/cm2    -> UV index (/450)  (4500 -> 10, Ambient: 10 exact)
  - Humidity, wind dir: raw, no scaling
Sentinels: HEAT_INDEX=255 (raw) means "not computed" -> skipped.
Timestamps: TIME column is station-local (America/Los_Angeles) -> converted to UTC.

Reads the MDB via ODBC (pyodbc). Idempotent via INSERT OR IGNORE.

Usage:
    python scripts/import_mdb.py
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wxdb

MDB_PATH = wxdb.ROOT / "Legacy" / "EasyWeatherIP-Historical-Data" / "HP2000-history.mdb"
LOCAL_TZ = ZoneInfo("America/Los_Angeles")

C_TO_F = lambda c: c * 9.0 / 5.0 + 32.0
HPA_TO_INHG = 0.029529983071445
MS_TO_MPH = 2.2369362920544
MM_TO_IN = 1.0 / 25.4
LUX_TO_WM2 = 1.0 / 126.7

# column -> (canonical metric, converter taking raw int, sentinel raw values to skip)
COLUMNS = {
    "IN_TEMP":    ("tempinf",       lambda v: C_TO_F(v / 10.0),          ()),
    "IN_HUMI":    ("humidityin",    float,                               ()),
    "OUT_TEMP":   ("tempf",         lambda v: C_TO_F(v / 10.0),          ()),
    "OUT_HUMI":   ("humidity",      float,                               ()),
    "WIND_SPEED": ("windspeedmph",  lambda v: v / 10.0 * MS_TO_MPH,      ()),
    "GUST_SPEED": ("windgustmph",   lambda v: v / 10.0 * MS_TO_MPH,      ()),
    "DEW_POINT":  ("dewpointf",     lambda v: C_TO_F(v / 10.0),          ()),
    "WIND_CHILL": ("windchillf",    lambda v: C_TO_F(v / 10.0),          ()),
    "WIND_DIR":   ("winddir",       float,                               ()),
    "ABS_BARO":   ("baromabsin",    lambda v: v / 10.0 * HPA_TO_INHG,    ()),
    "REL_BARO":   ("baromrelin",    lambda v: v / 10.0 * HPA_TO_INHG,    ()),
    "RAIN_RATE":  ("rainratein",    lambda v: v / 10.0 * MM_TO_IN,       ()),
    "DAY_RAIN":   ("dailyrainin",   lambda v: v / 10.0 * MM_TO_IN,       ()),
    "WEEK_RAIN":  ("weeklyrainin",  lambda v: v / 10.0 * MM_TO_IN,       ()),
    "MONTH_RAIN": ("monthlyrainin", lambda v: v / 10.0 * MM_TO_IN,       ()),
    "YEAR_RAIN":  ("yearlyrainin",  lambda v: v / 10.0 * MM_TO_IN,       ()),
    "SOLAR":      ("solarradiation",lambda v: v / 10.0 * LUX_TO_WM2,     ()),
    "HEAT_INDEX": ("heatindexf",    lambda v: C_TO_F(v / 10.0),          (255,)),
    "UVI":        ("uv",            lambda v: v / 450.0,                 ()),
}

# Post-conversion sanity bounds (drop and count anything outside — protects
# the archive from corrupt rows without failing the whole import).
BOUNDS = {
    "tempf": (20.0, 130.0), "tempinf": (20.0, 130.0),
    "dewpointf": (-40.0, 100.0), "windchillf": (-40.0, 130.0),
    "heatindexf": (-40.0, 150.0),
    "humidity": (0.0, 100.0), "humidityin": (0.0, 100.0),
    "windspeedmph": (0.0, 150.0), "windgustmph": (0.0, 200.0),
    "winddir": (0.0, 360.0),
    "baromabsin": (27.0, 32.0), "baromrelin": (27.0, 32.0),
    "rainratein": (0.0, 12.0), "dailyrainin": (0.0, 15.0),
    "weeklyrainin": (0.0, 30.0), "monthlyrainin": (0.0, 40.0),
    "yearlyrainin": (0.0, 80.0),
    "solarradiation": (0.0, 1500.0), "uv": (0.0, 13.0),
}


def main() -> int:
    import pyodbc

    conn = wxdb.get_conn()
    wxdb.ensure_schema(conn)
    mids = wxdb.metric_ids(conn)
    sid = wxdb.source_id(conn, "mdb")

    odbc = pyodbc.connect(
        r"Driver={Microsoft Access Driver (*.mdb, *.accdb)};"
        rf"Dbq={MDB_PATH};"
    )
    cur = odbc.cursor()
    col_list = ", ".join(COLUMNS.keys())
    cur.execute(f"SELECT TIME, {col_list} FROM Records")

    n_read = 0
    n_inserted = 0
    n_sentinel = 0
    n_out_of_bounds = 0
    n_bad_time = 0
    batch: list[tuple[int, int, int, float]] = []

    for row in cur:
        n_read += 1
        time_str = row[0]
        try:
            local_dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M").replace(tzinfo=LOCAL_TZ)
            ts_utc = int(local_dt.timestamp())
        except (ValueError, TypeError):
            n_bad_time += 1
            continue

        for i, (col, (canon, convert, sentinels)) in enumerate(COLUMNS.items(), start=1):
            raw = row[i]
            if raw is None or raw in sentinels:
                n_sentinel += 1
                continue
            val = convert(raw)
            lo, hi = BOUNDS[canon]
            if not (lo <= val <= hi):
                n_out_of_bounds += 1
                continue
            batch.append((mids[canon], ts_utc, sid, val))

        if len(batch) >= 50_000:
            n_inserted += wxdb.insert_observations(conn, batch)
            batch.clear()

    if batch:
        n_inserted += wxdb.insert_observations(conn, batch)
    conn.commit()
    odbc.close()

    n_ts = conn.execute(
        "SELECT COUNT(DISTINCT ts_utc) FROM observations WHERE source_id=?", (sid,)
    ).fetchone()[0]
    rng = conn.execute(
        "SELECT datetime(MIN(ts_utc),'unixepoch'), datetime(MAX(ts_utc),'unixepoch') "
        "FROM observations WHERE source_id=?", (sid,)
    ).fetchone()

    print(f"MDB rows read:          {n_read}")
    print(f"Rows inserted this run: {n_inserted}")
    print(f"Sentinel/null skipped:  {n_sentinel}")
    print(f"Out-of-bounds dropped:  {n_out_of_bounds}")
    print(f"Unparseable times:      {n_bad_time}")
    print(f"Distinct timestamps:    {n_ts}")
    print(f"Time range (UTC):       {rng[0]} -> {rng[1]}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
