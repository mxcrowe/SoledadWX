"""
Import the Cumulus (Sandysoft) era: Sep 2009 -> Aug 2018.

Two file families in Legacy/Cumulus-Historical-Data/data/:

  MMMYYlog.txt  — interval readings (~20 min), comma-separated, dd/mm/yy dates,
                  imperial units (Cumulus was configured F/inHg/mph/in).
                  Column count GREW over the years (17 in 2009 -> 27 by 2018);
                  older rows are a strict prefix of monthlyfileheader.txt.
  dayfile.txt   — one row per day, 46-field layout per dayfileheader.txt,
                  including Total Wind Run. Early years leave trailing fields
                  empty. -> daily_summaries table.

Times are station-local (America/Los_Angeles) -> converted to UTC for
observations. daily_summaries keeps the local date + local HH:MM strings,
matching how Cumulus reasoned about days.

Idempotent via INSERT OR IGNORE / INSERT OR REPLACE.

Usage:
    python scripts/import_cumulus.py
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wxdb

DATA_DIR = wxdb.ROOT / "Legacy" / "Cumulus-Historical-Data" / "data"
LOCAL_TZ = ZoneInfo("America/Los_Angeles")

# Monthly log column index (0-based) -> canonical metric.
# Per monthlyfileheader.txt. Skipped: rainfall counter (11), current gust (14),
# ET (19,20), max theoretical solar (22), sunshine hours (23), instantaneous
# bearing (24), RG-11 (25), rain-since-midnight (26).
MONTHLY_MAP = {
    2:  "tempf",
    3:  "humidity",
    4:  "dewpointf",
    5:  "windspeedmph",
    6:  "windgustmph",      # "recent high gust" — closest analog to Ambient's gust
    7:  "winddir",          # average wind bearing
    8:  "rainratein",
    9:  "dailyrainin",      # "rainfall so far" (today)
    10: "baromrelin",       # sea-level pressure
    12: "tempinf",
    13: "humidityin",
    15: "windchillf",
    16: "heatindexf",
    17: "uv",
    18: "solarradiation",
    21: "feelslikef",       # Cumulus "apparent temperature"
}

BOUNDS = {
    "tempf": (-30.0, 130.0), "tempinf": (20.0, 130.0),
    "dewpointf": (-40.0, 100.0), "windchillf": (-40.0, 130.0),
    "heatindexf": (-40.0, 150.0), "feelslikef": (-40.0, 150.0),
    "humidity": (0.0, 100.0), "humidityin": (0.0, 100.0),
    "windspeedmph": (0.0, 150.0), "windgustmph": (0.0, 200.0),
    "winddir": (0.0, 360.0),
    "baromrelin": (27.0, 32.0),
    "rainratein": (0.0, 12.0), "dailyrainin": (0.0, 15.0),
    "solarradiation": (0.0, 1500.0), "uv": (0.0, 16.0),
}

# dayfile.txt field index (0-based) -> daily_summaries column.
DAYFILE_MAP = {
    1: "max_gust_mph", 2: "max_gust_bearing", 3: "max_gust_time",
    4: "min_temp_f", 5: "min_temp_time",
    6: "max_temp_f", 7: "max_temp_time",
    8: "min_press_in", 9: "min_press_time",
    10: "max_press_in", 11: "max_press_time",
    12: "max_rain_rate", 13: "max_rain_rate_time",
    14: "total_rain_in",
    15: "avg_temp_f",
    16: "wind_run_mi",
    17: "high_avg_wind_mph", 18: "high_avg_wind_time",
    19: "low_humidity", 20: "low_humidity_time",
    21: "high_humidity", 22: "high_humidity_time",
    25: "high_heat_index_f", 26: "high_heat_index_time",
    31: "high_hourly_rain",  # not in table; handled below via TEXT_COLS check
    33: "low_wind_chill_f", 34: "low_wind_chill_time",
    35: "high_dew_point_f", 36: "high_dew_point_time",
    37: "low_dew_point_f", 38: "low_dew_point_time",
    39: "dominant_wind_bearing",
    40: "heating_degree_days",
    41: "cooling_degree_days",
    42: "high_solar_wm2", 43: "high_solar_time",
    44: "high_uv", 45: "high_uv_time",
}
# Columns that hold HH:MM strings rather than numbers.
TIME_COLS = {c for c in DAYFILE_MAP.values() if c.endswith("_time")}
# daily_summaries doesn't have a high_hourly_rain column; drop it.
DAYFILE_MAP = {k: v for k, v in DAYFILE_MAP.items() if v != "high_hourly_rain"}


def parse_date(d: str) -> datetime | None:
    """dd/mm/yy or dd-mm-yy."""
    d = d.strip()
    for sep in ("/", "-"):
        if sep in d:
            try:
                dd, mm, yy = d.split(sep)
                return datetime(2000 + int(yy), int(mm), int(dd))
            except ValueError:
                return None
    return None


def import_monthly(conn) -> None:
    mids = wxdb.metric_ids(conn)
    sid = wxdb.source_id(conn, "cumulus_log")
    # MMMYYlog.txt only — excludes alltimelog.txt (Cumulus's record-change
    # audit log, which matches *log.txt but holds no interval readings).
    files = sorted(f for f in DATA_DIR.glob("*log.txt") if len(f.name) == len("Apr10log.txt"))
    n_rows = n_inserted = n_bad = n_oob = 0

    for f in files:
        batch = []
        for line in f.read_text(encoding="latin-1").splitlines():
            if not line.strip():
                continue
            parts = line.split(",")
            base = parse_date(parts[0])
            if base is None or len(parts) < 3:
                n_bad += 1
                continue
            try:
                hh, mm = parts[1].split(":")
                local_dt = base.replace(hour=int(hh), minute=int(mm), tzinfo=LOCAL_TZ)
                ts_utc = int(local_dt.timestamp())
            except (ValueError, IndexError):
                n_bad += 1
                continue
            n_rows += 1
            for idx, canon in MONTHLY_MAP.items():
                if idx >= len(parts):
                    continue  # older short rows: missing columns simply absent
                cell = parts[idx].strip()
                if not cell:
                    continue
                try:
                    val = float(cell)
                except ValueError:
                    continue
                lo, hi = BOUNDS[canon]
                if not (lo <= val <= hi):
                    n_oob += 1
                    continue
                batch.append((mids[canon], ts_utc, sid, val))
        n_inserted += wxdb.insert_observations(conn, batch)
    conn.commit()
    print(f"[monthly] files={len(files)} rows={n_rows} inserted={n_inserted} "
          f"bad_lines={n_bad} out_of_bounds={n_oob}")


def import_dayfile(conn) -> None:
    sid = wxdb.source_id(conn, "cumulus_log")
    dayfile = DATA_DIR / "dayfile.txt"
    cols = list(DAYFILE_MAP.values())
    n_rows = n_bad = 0

    for line in dayfile.read_text(encoding="latin-1").splitlines():
        if not line.strip():
            continue
        parts = line.split(",")
        base = parse_date(parts[0])
        if base is None:
            n_bad += 1
            continue
        values: dict[str, object] = {}
        for idx, col in DAYFILE_MAP.items():
            if idx >= len(parts):
                continue
            cell = parts[idx].strip()
            if not cell:
                continue
            if col in TIME_COLS:
                values[col] = cell
            else:
                try:
                    values[col] = float(cell)
                except ValueError:
                    pass
        present = [c for c in cols if c in values]
        placeholders = ",".join("?" * (len(present) + 2))
        conn.execute(
            f"INSERT OR REPLACE INTO daily_summaries(date, source_id, {','.join(present)}) "
            f"VALUES ({placeholders})",
            [base.strftime("%Y-%m-%d"), sid, *[values[c] for c in present]],
        )
        n_rows += 1
    conn.commit()
    print(f"[dayfile] rows={n_rows} bad_lines={n_bad}")


def main() -> int:
    conn = wxdb.get_conn()
    wxdb.ensure_schema(conn)
    import_monthly(conn)
    import_dayfile(conn)

    sid = wxdb.source_id(conn, "cumulus_log")
    n_ts = conn.execute(
        "SELECT COUNT(DISTINCT ts_utc) FROM observations WHERE source_id=?", (sid,)
    ).fetchone()[0]
    rng = conn.execute(
        "SELECT datetime(MIN(ts_utc),'unixepoch'), datetime(MAX(ts_utc),'unixepoch') "
        "FROM observations WHERE source_id=?", (sid,)
    ).fetchone()
    n_days = conn.execute(
        "SELECT COUNT(*), MIN(date), MAX(date) FROM daily_summaries WHERE source_id=?", (sid,)
    ).fetchone()
    wr = conn.execute(
        "SELECT COUNT(wind_run_mi), ROUND(SUM(wind_run_mi)) FROM daily_summaries "
        "WHERE source_id=? AND wind_run_mi IS NOT NULL", (sid,)
    ).fetchone()

    print(f"Distinct timestamps: {n_ts}")
    print(f"Time range (UTC):    {rng[0]} -> {rng[1]}")
    print(f"Daily summaries:     {n_days[0]} days, {n_days[1]} -> {n_days[2]}")
    print(f"Wind run:            {wr[0]} days recorded, {wr[1]} total miles")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
