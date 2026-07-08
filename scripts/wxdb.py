"""
Shared database layer for SoledadWX importers.

Implements the three-layer model from ARCHITECTURE.md §3.3:
  sources        — provenance inventory (who observed)
  metrics        — dictionary of canonical metric names (what can be observed)
  observations   — raw readings, long format, native resolution (what was observed)
  daily_summaries— per-day rollups (Cumulus dayfile richness, incl. wind run)
  source_priority— time-period priority map (what we believe), data not code

Conventions:
  - All timestamps are UTC epoch seconds (INTEGER).
  - All values are imperial (°F, inHg, mph, in, W/m²) — matches the live
    AmbientWeather stream so the whole archive speaks one dialect.
  - Canonical metric names use AmbientWeather's vocabulary (tempf, humidity,
    windspeedmph, ...) since that is the vocabulary of the live stream.
  - Importers use INSERT OR IGNORE for idempotency: re-running an importer
    never duplicates or clobbers.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "soledadwx.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id          INTEGER PRIMARY KEY,
    kind        TEXT NOT NULL UNIQUE,   -- cumulus_log | mdb | amb_rest | amb_ws | sdcard | ksan_metar
    name        TEXT NOT NULL,
    station     TEXT,
    path_or_url TEXT,
    sample_rate TEXT,                   -- human-readable native rate, e.g. '5 min'
    notes       TEXT
);

CREATE TABLE IF NOT EXISTS metrics (
    id    INTEGER PRIMARY KEY,
    name  TEXT NOT NULL UNIQUE,         -- canonical Ambient-style key, e.g. 'tempf'
    unit  TEXT NOT NULL,
    label TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS observations (
    metric_id  INTEGER NOT NULL REFERENCES metrics(id),
    ts_utc     INTEGER NOT NULL,        -- epoch seconds, UTC
    source_id  INTEGER NOT NULL REFERENCES sources(id),
    value      REAL NOT NULL,
    PRIMARY KEY (metric_id, ts_utc, source_id)
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS idx_obs_source_ts ON observations(source_id, ts_utc);

CREATE TABLE IF NOT EXISTS daily_summaries (
    date          TEXT NOT NULL,        -- ISO local date (station local time)
    source_id     INTEGER NOT NULL REFERENCES sources(id),
    max_gust_mph  REAL, max_gust_bearing REAL, max_gust_time TEXT,
    min_temp_f    REAL, min_temp_time TEXT,
    max_temp_f    REAL, max_temp_time TEXT,
    min_press_in  REAL, min_press_time TEXT,
    max_press_in  REAL, max_press_time TEXT,
    max_rain_rate REAL, max_rain_rate_time TEXT,
    total_rain_in REAL,
    avg_temp_f    REAL,
    wind_run_mi   REAL,
    high_avg_wind_mph REAL, high_avg_wind_time TEXT,
    low_humidity  REAL, low_humidity_time TEXT,
    high_humidity REAL, high_humidity_time TEXT,
    high_heat_index_f REAL, high_heat_index_time TEXT,
    low_wind_chill_f REAL, low_wind_chill_time TEXT,
    high_dew_point_f REAL, high_dew_point_time TEXT,
    low_dew_point_f REAL, low_dew_point_time TEXT,
    dominant_wind_bearing REAL,
    heating_degree_days REAL,
    cooling_degree_days REAL,
    high_solar_wm2 REAL, high_solar_time TEXT,
    high_uv REAL, high_uv_time TEXT,
    PRIMARY KEY (date, source_id)
);

CREATE TABLE IF NOT EXISTS source_priority (
    period_start INTEGER NOT NULL,      -- epoch seconds UTC, inclusive
    period_end   INTEGER,               -- epoch seconds UTC, exclusive; NULL = open-ended
    source_kind  TEXT NOT NULL,
    rank         INTEGER NOT NULL,      -- 1 = most preferred within the period
    PRIMARY KEY (period_start, source_kind)
);

-- The canonical resolver: best-known value per (metric, timestamp), chosen
-- by the time-period priority map. Sources not listed for a period are
-- excluded entirely (e.g. off-site KSAN data can be rank-limited to gap
-- periods only). This is the ARCHITECTURE.md §3.3 "canonical view".
CREATE VIEW IF NOT EXISTS canonical_observations AS
SELECT metric_id, ts_utc, source_id, value FROM (
    SELECT o.metric_id, o.ts_utc, o.source_id, o.value,
           ROW_NUMBER() OVER (
               PARTITION BY o.metric_id, o.ts_utc
               ORDER BY p.rank
           ) AS rn
    FROM observations o
    JOIN sources s ON s.id = o.source_id
    JOIN source_priority p ON p.source_kind = s.kind
        AND o.ts_utc >= p.period_start
        AND (p.period_end IS NULL OR o.ts_utc < p.period_end)
)
WHERE rn = 1;
"""

# Canonical metric dictionary — Ambient vocabulary, imperial units.
METRICS = [
    ("tempf",          "F",    "Outdoor temperature"),
    ("humidity",       "%",    "Outdoor humidity"),
    ("tempinf",        "F",    "Indoor temperature"),
    ("humidityin",     "%",    "Indoor humidity"),
    ("windspeedmph",   "mph",  "Wind speed"),
    ("windgustmph",    "mph",  "Wind gust"),
    ("maxdailygust",   "mph",  "Max daily gust"),
    ("winddir",        "deg",  "Wind direction"),
    ("baromrelin",     "inHg", "Relative pressure"),
    ("baromabsin",     "inHg", "Absolute pressure"),
    ("rainratein",     "in/hr","Rain rate"),
    ("hourlyrainin",   "in",   "Hourly rain"),
    ("dailyrainin",    "in",   "Daily rain"),
    ("weeklyrainin",   "in",   "Weekly rain"),
    ("monthlyrainin",  "in",   "Monthly rain"),
    ("yearlyrainin",   "in",   "Yearly rain"),
    ("solarradiation", "W/m2", "Solar radiation"),
    ("uv",             "index","UV index"),
    ("dewpointf",      "F",    "Dew point"),
    ("windchillf",     "F",    "Wind chill"),
    ("heatindexf",     "F",    "Heat index"),
    ("feelslikef",     "F",    "Feels like"),
    ("dewpointinf",    "F",    "Indoor dew point"),
    ("feelslikeinf",   "F",    "Indoor feels like"),
]

SOURCES = [
    ("cumulus_log", "Cumulus monthly logs + dayfile", "Zephyr PWS-1000TD",
     "Legacy/Cumulus-Historical-Data/data", "~20 min",
     "Sep 2009 - Aug 2018. Imperial native. dd/mm/yy local time."),
    ("mdb", "EasyWeatherIP HP2000-history.mdb", "WS-1002-WiFi",
     "Legacy/EasyWeatherIP-Historical-Data/HP2000-history.mdb", "5 min",
     "Apr 2020 - Aug 2025. Metric x10 scaled ints; converted to imperial on import."),
    ("amb_rest", "AmbientWeather REST rescue dump", "WS-1002-WiFi",
     "Legacy/AmbientWeather-Rescue", "5 min",
     "Aug 2025 onward (rolling). Imperial native, epoch-ms UTC timestamps."),
    ("amb_ws", "AmbientWeather live WebSocket", "WS-1002-WiFi",
     "wss://rt2.ambientweather.net", "real-time",
     "Live stream recorded by the Tauri app."),
    ("ksan_metar", "KSAN METAR climatological records", "San Diego Intl (off-site)",
     None, "60 min",
     "Fallback gap-fill. Off-site; never preferred over station data."),
    ("wu_pws", "Weather Underground PWS KCALAJOL6", "Zephyr then WS-1002-WiFi",
     "Legacy/WU-Rescue", "5 min",
     "Same-roof uploads: Nov 2012 - Jun 2018 (Zephyr), Sep 2018 - present "
     "(WS-1002). 5-min aggregates (high/low/avg). Primary fill for the "
     "2018-2022 holes."),
    ("msdsd", "MSDSD Mt Soledad mesonet (SDG&E)", "MSDSD (off-site, 0.5 km)",
     "Legacy/MSDSD-Rescue", "10 min",
     "Temp/dewpoint/RH/wind only; no rain/solar/pressure. Synoptic API "
     "history is paywalled; free tier = rolling week."),
    ("wu_ksandi354", "Weather Underground PWS KCASANDI354", "Neighbor (~1.1 km)",
     "Legacy/WU-Neighbors/KCASANDI354", "5 min",
     "Nearby La Jolla PWS, same microclimate. Gap-fill only (2016 outage). "
     "Full parameter set. Ranked below all on-site sources."),
    ("wu_ksandi4366", "Weather Underground PWS KCASANDI4366", "Neighbor (~1.2 km)",
     "Legacy/WU-Neighbors/KCASANDI4366", "5 min",
     "Nearby La Jolla PWS, same microclimate. Gap-fill only (2018 July "
     "outage + Aug-Sep instrument swap). Full parameter set."),
    ("wu_ksandi84", "Weather Underground PWS KCASANDI84", "Neighbor (~1.5 km)",
     "Legacy/WU-Neighbors/KCASANDI84", "5 min",
     "Nearby La Jolla PWS, same microclimate. Gap-fill only (2014 outage)."),
]

# Priority map from ARCHITECTURE.md §3.3. Epochs computed in ensure_schema().
# (start_iso, end_iso_or_None, kind, rank)
# wu_pws is the same physical roof (KCALAJOL6), so it ranks directly under
# each era's native logger and fills that logger's holes. SD card was a dead
# end (checked Jul 2026, empty); msdsd is off-site fallback for the one true
# instrument gap (~Aug 28 - Sep 27, 2018).
PRIORITY = [
    ("2009-09-01", "2018-09-01", "cumulus_log",   1),
    ("2012-11-29", "2018-09-01", "wu_pws",        2),
    ("2009-09-01", "2018-09-01", "wu_ksandi354",  8),
    ("2009-09-01", "2018-09-01", "wu_ksandi4366", 9),
    ("2009-09-01", "2018-09-01", "wu_ksandi84",  10),
    ("2018-09-01", "2020-04-19", "wu_pws",        1),
    ("2018-09-01", "2020-04-19", "wu_ksandi4366", 8),
    ("2018-09-01", "2020-04-19", "msdsd",         9),
    ("2020-04-19", "2025-08-17", "mdb",           1),
    ("2020-04-19", "2025-08-17", "amb_rest",      2),
    ("2020-04-19", "2025-08-17", "wu_pws",        3),
    ("2025-08-17", None,         "amb_rest",      1),
    ("2025-08-17", None,         "amb_ws",        2),
    # Standing current-era backup: a neighbor on a different ISP fills gaps
    # from local internet outages (station can't reach the cloud). Only
    # surfaces where amb_rest/amb_ws are silent.
    ("2025-08-17", None,         "wu_ksandi354",  5),
]


def get_conn(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.executemany(
        "INSERT OR IGNORE INTO metrics(name, unit, label) VALUES (?,?,?)", METRICS
    )
    conn.executemany(
        "INSERT OR IGNORE INTO sources(kind, name, station, path_or_url, sample_rate, notes) "
        "VALUES (?,?,?,?,?,?)",
        SOURCES,
    )
    from datetime import datetime, timezone

    for start_iso, end_iso, kind, rank in PRIORITY:
        start = int(datetime.fromisoformat(start_iso).replace(tzinfo=timezone.utc).timestamp())
        end = (
            int(datetime.fromisoformat(end_iso).replace(tzinfo=timezone.utc).timestamp())
            if end_iso
            else None
        )
        conn.execute(
            "INSERT OR IGNORE INTO source_priority(period_start, period_end, source_kind, rank) "
            "VALUES (?,?,?,?)",
            (start, end, kind, rank),
        )
    conn.commit()


def metric_ids(conn: sqlite3.Connection) -> dict[str, int]:
    return {name: mid for mid, name in conn.execute("SELECT id, name FROM metrics")}


def source_id(conn: sqlite3.Connection, kind: str) -> int:
    row = conn.execute("SELECT id FROM sources WHERE kind=?", (kind,)).fetchone()
    if row is None:
        raise KeyError(f"unknown source kind: {kind}")
    return row[0]


def insert_observations(conn: sqlite3.Connection, rows) -> int:
    """rows: iterable of (metric_id, ts_utc, source_id, value). Returns rows actually inserted."""
    before = conn.total_changes
    conn.executemany(
        "INSERT OR IGNORE INTO observations(metric_id, ts_utc, source_id, value) VALUES (?,?,?,?)",
        rows,
    )
    return conn.total_changes - before
