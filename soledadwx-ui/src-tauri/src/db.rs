//! Live recorder: persists AmbientWeather readings into the SoledadWX archive.
//!
//! Schema mirrors scripts/wxdb.py, which is the schema authority — if the
//! tables diverge, fix them to match wxdb.py, not the other way around.
//! Inserts are INSERT OR IGNORE on (metric_id, ts_utc, source_id), so the
//! recorder is idempotent and coexists with the amb_rest importer.

use rusqlite::Connection;
use std::collections::HashMap;
use std::path::PathBuf;

use crate::models::AmbientReading;

const SCHEMA: &str = "
CREATE TABLE IF NOT EXISTS sources (
    id          INTEGER PRIMARY KEY,
    kind        TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    station     TEXT,
    path_or_url TEXT,
    sample_rate TEXT,
    notes       TEXT
);
CREATE TABLE IF NOT EXISTS metrics (
    id    INTEGER PRIMARY KEY,
    name  TEXT NOT NULL UNIQUE,
    unit  TEXT NOT NULL,
    label TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS observations (
    metric_id  INTEGER NOT NULL REFERENCES metrics(id),
    ts_utc     INTEGER NOT NULL,
    source_id  INTEGER NOT NULL REFERENCES sources(id),
    value      REAL NOT NULL,
    PRIMARY KEY (metric_id, ts_utc, source_id)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_obs_source_ts ON observations(source_id, ts_utc);

-- Which civil-local days need their rollup recomputed.
--
-- `observations` is WITHOUT ROWID, so there is no insertion-order counter to
-- watermark, and a ts_utc watermark would be actively WRONG: backfill and the
-- Python importers insert OLD timestamps, which such a watermark would skip
-- forever. A trigger is the only mechanism that catches every writer — the
-- live recorder, the backfill, and any script — without one of them having to
-- know that rollups exist. Measured cost: +0.7 us per inserted row, about
-- four seconds on a 4.9M-row bulk import.
CREATE TABLE IF NOT EXISTS rollup_dirty (
    day_local TEXT PRIMARY KEY
) WITHOUT ROWID;
CREATE TRIGGER IF NOT EXISTS obs_dirty_insert AFTER INSERT ON observations BEGIN
    INSERT OR IGNORE INTO rollup_dirty(day_local)
    VALUES (date(NEW.ts_utc, 'unixepoch', 'localtime'));
END;
-- Corrections delete rows (see scripts/fix_phantom_derived_zeros.py); a day
-- that loses its extreme is just as stale as one that gains a reading.
CREATE TRIGGER IF NOT EXISTS obs_dirty_delete AFTER DELETE ON observations BEGIN
    INSERT OR IGNORE INTO rollup_dirty(day_local)
    VALUES (date(OLD.ts_utc, 'unixepoch', 'localtime'));
END;

-- Gaps the Backfill has already tried to fill, so a timer does not re-request
-- the same barren window forever. Some holes are genuinely unfillable — if
-- the station or the house internet was down, Ambient has nothing either —
-- and Ambient allows only ~1 request/second per key.
CREATE TABLE IF NOT EXISTS backfill_attempts (
    gap_start    INTEGER PRIMARY KEY,   -- epoch of the last reading BEFORE the hole
    gap_end      INTEGER NOT NULL,      -- epoch of the first reading AFTER it
    last_attempt INTEGER NOT NULL,
    attempts     INTEGER NOT NULL,
    rows_gained  INTEGER NOT NULL       -- from the most recent attempt
) WITHOUT ROWID;
";

pub fn db_path() -> PathBuf {
    if let Ok(p) = std::env::var("SOLEDADWX_DB") {
        return PathBuf::from(p);
    }
    // Dev fallback: CWD is src-tauri during `npm run tauri dev`.
    PathBuf::from("../../data/soledadwx.db")
}

/// NWS wind chill (°F). Defined only for T <= 50 °F and wind > 3 mph.
///
/// AmbientWeather does not transmit wind chill or heat index — it sends only
/// `feelsLike` — so the archive had no way to record them and the all-time
/// "Lowest wind chill" / "Highest heat index" records were frozen from the
/// moment the live recorder became the current-era source. We derive them
/// here instead. Must stay bit-for-bit identical to windChillF() in
/// src/astro.ts, or the Console and the archive will disagree.
fn wind_chill_f(temp_f: Option<f64>, wind_mph: Option<f64>) -> Option<f64> {
    let (t, w) = (temp_f?, wind_mph?);
    if t > 50.0 || w <= 3.0 {
        return None;
    }
    let v = w.powf(0.16);
    Some(35.74 + 0.6215 * t - 35.75 * v + 0.4275 * t * v)
}

/// NWS heat index (°F, Rothfusz regression). Defined only for T >= 80 °F.
/// Mirrors heatIndexF() in src/astro.ts — keep the two in step.
fn heat_index_f(temp_f: Option<f64>, rh: Option<f64>) -> Option<f64> {
    let (t, r) = (temp_f?, rh?);
    if t < 80.0 {
        return None;
    }
    let mut hi = -42.379 + 2.04901523 * t + 10.14333127 * r - 0.22475541 * t * r
        - 0.00683783 * t * t - 0.05481717 * r * r + 0.00122874 * t * t * r
        + 0.00085282 * t * r * r - 0.00000199 * t * t * r * r;
    if r < 13.0 && t <= 112.0 {
        hi -= ((13.0 - r) / 4.0) * ((17.0 - (t - 95.0).abs()) / 17.0).sqrt();
    } else if r > 85.0 && t <= 87.0 {
        hi += ((r - 85.0) / 10.0) * ((87.0 - t) / 5.0);
    }
    Some(hi)
}

/// Saturation vapour pressure (hPa) from temperature (°C) — Tetens/Magnus.
/// Shared by the three moist-heat measures below.
fn sat_vp_hpa(tc: f64) -> f64 {
    6.112 * ((17.67 * tc) / (tc + 243.5)).exp()
}

/// Australian BOM apparent temperature (°F).
///
/// The one moist-heat measure that is defined at EVERY temperature: heat
/// index gives up below 80 °F and wind chill above 50 °F, which leaves a
/// 30-degree hole covering most of a San Diego year. AT fills it, and it is
/// the only one of the three that accounts for wind as well as moisture, so
/// it is the honest headline number for a coastal site.
///
/// AT = Ta + 0.33*e - 0.70*ws - 4.00, with e the actual vapour pressure
/// (hPa) and ws the wind speed in m/s at 10 m. Mirrors apparentTempF() in
/// src/astro.ts — keep the two in step.
fn apparent_temp_f(temp_f: Option<f64>, rh: Option<f64>, wind_mph: Option<f64>) -> Option<f64> {
    let (t, r) = (temp_f?, rh?);
    // Wind is required by the formula; treat a missing anemometer as calm
    // rather than discarding the reading, and say so here so nobody later
    // mistakes a still day for a broken one.
    let w_ms = wind_mph.unwrap_or(0.0) * 0.44704;
    let tc = (t - 32.0) * 5.0 / 9.0;
    let e = (r / 100.0) * sat_vp_hpa(tc);
    let at_c = tc + 0.33 * e - 0.70 * w_ms - 4.00;
    Some(at_c * 9.0 / 5.0 + 32.0)
}

/// Humidex (°F-equivalent). Canadian moist-heat index — temperature plus a
/// dewpoint-driven term, no wind. Undefined (returns None) when the moisture
/// term would subtract, i.e. dewpoint below 10 °C, which is Environment
/// Canada's own convention. Mirrors humidexF() in src/astro.ts.
fn humidex_f(temp_f: Option<f64>, dew_f: Option<f64>) -> Option<f64> {
    let (t, d) = (temp_f?, dew_f?);
    let dc = (d - 32.0) * 5.0 / 9.0;
    if dc < 10.0 {
        return None;
    }
    let tc = (t - 32.0) * 5.0 / 9.0;
    let e = 6.11 * (5417.7530 * (1.0 / 273.16 - 1.0 / (dc + 273.15))).exp();
    let h_c = tc + 0.5555 * (e - 10.0);
    Some(h_c * 9.0 / 5.0 + 32.0)
}

/// Wet-bulb temperature (°F), Stull (2011) empirical fit. Valid for roughly
/// 5-99% RH and -20..50 °C; returns None outside that. Not a comfort index —
/// it is the physical limit of evaporative cooling, which is what actually
/// bounds how well a body (or a dog) can shed heat. Mirrors wetBulbF() in
/// src/astro.ts.
fn wet_bulb_f(temp_f: Option<f64>, rh: Option<f64>) -> Option<f64> {
    let (t, r) = (temp_f?, rh?);
    if !(5.0..=99.0).contains(&r) {
        return None;
    }
    let tc = (t - 32.0) * 5.0 / 9.0;
    if !(-20.0..=50.0).contains(&tc) {
        return None;
    }
    let wb_c = tc * (0.151977 * (r + 8.313659).sqrt()).atan()
        + (tc + r).atan()
        - (r - 1.676331).atan()
        + 0.00391838 * r.powf(1.5) * (0.023101 * r).atan()
        - 4.686035;
    Some(wb_c * 9.0 / 5.0 + 32.0)
}

// Canonical metric name -> value for one reading. Shared by the live
// recorder and the backfill so both map fields identically.
fn value_pairs(r: &AmbientReading) -> [(&'static str, Option<f64>); 26] {
    [
        ("tempf", r.tempf),
        ("humidity", r.humidity.map(f64::from)),
        ("tempinf", r.tempinf),
        ("humidityin", r.humidityin.map(f64::from)),
        ("windspeedmph", r.windspeedmph),
        ("windgustmph", r.windgustmph),
        ("maxdailygust", r.maxdailygust),
        ("winddir", r.winddir.map(f64::from)),
        ("baromrelin", r.baromrelin),
        ("baromabsin", r.baromabsin),
        ("hourlyrainin", r.hourlyrainin),
        ("dailyrainin", r.dailyrainin),
        ("weeklyrainin", r.weeklyrainin),
        ("monthlyrainin", r.monthlyrainin),
        ("yearlyrainin", r.yearlyrainin),
        ("solarradiation", r.solarradiation),
        ("uv", r.uv.map(f64::from)),
        ("dewpointf", r.dewPoint),
        ("feelslikef", r.feelsLike),
        ("dewpointinf", r.dewPointin),
        ("feelslikeinf", r.feelsLikein),
        // Derived, not transmitted — see wind_chill_f / heat_index_f above.
        // None outside their valid range, so nothing is written on a mild day
        // (empty != zero: a 0 here would be a fictitious reading).
        ("windchillf", wind_chill_f(r.tempf, r.windspeedmph)),
        ("heatindexf", heat_index_f(r.tempf, r.humidity.map(f64::from))),
        // The apparent-temperature family. AT is defined at all temperatures
        // and is the only one that sees wind; humidex and wet bulb are the
        // moisture-only companions. See the helpers above.
        ("apparenttempf", apparent_temp_f(r.tempf, r.humidity.map(f64::from), r.windspeedmph)),
        ("humidexf", humidex_f(r.tempf, r.dewPoint)),
        ("wetbulbf", wet_bulb_f(r.tempf, r.humidity.map(f64::from))),
    ]
}

pub struct Recorder {
    conn: Connection,
    source_id: i64,
    metric_ids: HashMap<&'static str, i64>,
}

impl Recorder {
    pub fn open() -> Result<Self, rusqlite::Error> {
        let path = db_path();
        if let Some(dir) = path.parent() {
            let _ = std::fs::create_dir_all(dir);
        }
        let conn = Connection::open(&path)?;
        conn.pragma_update(None, "journal_mode", "WAL")?;
        conn.pragma_update(None, "synchronous", "NORMAL")?;
        conn.busy_timeout(std::time::Duration::from_secs(5))?;
        conn.execute_batch(SCHEMA)?;
        conn.execute(
            "INSERT OR IGNORE INTO sources(kind, name, station, path_or_url, sample_rate, notes)
             VALUES ('amb_ws', 'AmbientWeather live WebSocket', 'WS-1002-WiFi',
                     'wss://rt2.ambientweather.net', 'real-time',
                     'Live stream recorded by the Tauri app.')",
            [],
        )?;
        let source_id: i64 =
            conn.query_row("SELECT id FROM sources WHERE kind='amb_ws'", [], |r| r.get(0))?;

        // Metric dictionary — same canonical names/units as wxdb.py METRICS.
        let metric_defs: &[(&str, &str, &str)] = &[
            ("tempf", "F", "Outdoor temperature"),
            ("humidity", "%", "Outdoor humidity"),
            ("tempinf", "F", "Indoor temperature"),
            ("humidityin", "%", "Indoor humidity"),
            ("windspeedmph", "mph", "Wind speed"),
            ("windgustmph", "mph", "Wind gust"),
            ("maxdailygust", "mph", "Max daily gust"),
            ("winddir", "deg", "Wind direction"),
            ("baromrelin", "inHg", "Relative pressure"),
            ("baromabsin", "inHg", "Absolute pressure"),
            ("hourlyrainin", "in", "Hourly rain"),
            ("dailyrainin", "in", "Daily rain"),
            ("weeklyrainin", "in", "Weekly rain"),
            ("monthlyrainin", "in", "Monthly rain"),
            ("yearlyrainin", "in", "Yearly rain"),
            ("solarradiation", "W/m2", "Solar radiation"),
            ("uv", "index", "UV index"),
            ("dewpointf", "F", "Dew point"),
            ("feelslikef", "F", "Feels like"),
            ("dewpointinf", "F", "Indoor dew point"),
            ("feelslikeinf", "F", "Indoor feels like"),
            // Derived here rather than transmitted; ids already exist from the
            // Cumulus/MDB importers, so INSERT OR IGNORE resolves to those.
            ("windchillf", "F", "Wind chill"),
            ("heatindexf", "F", "Heat index"),
            ("apparenttempf", "F", "Apparent temperature"),
            ("humidexf", "F", "Humidex"),
            ("wetbulbf", "F", "Wet bulb"),
        ];
        let mut metric_ids = HashMap::new();
        for (name, unit, label) in metric_defs {
            conn.execute(
                "INSERT OR IGNORE INTO metrics(name, unit, label) VALUES (?1, ?2, ?3)",
                (name, unit, label),
            )?;
            let id: i64 =
                conn.query_row("SELECT id FROM metrics WHERE name=?1", [name], |r| r.get(0))?;
            metric_ids.insert(*name, id);
        }
        Ok(Self { conn, source_id, metric_ids })
    }

    /// Persist one reading. Returns number of metric rows written.
    pub fn record(&mut self, r: &AmbientReading) -> Result<usize, rusqlite::Error> {
        let ts_utc = r.dateutc / 1000;
        let values = value_pairs(r);
        let tx = self.conn.transaction()?;
        let mut n = 0;
        {
            let mut stmt = tx.prepare_cached(
                "INSERT OR IGNORE INTO observations(metric_id, ts_utc, source_id, value)
                 VALUES (?1, ?2, ?3, ?4)",
            )?;
            for (name, val) in values {
                if let Some(v) = val {
                    n += stmt.execute((self.metric_ids[name], ts_utc, self.source_id, v))?;
                }
            }
        }
        tx.commit()?;
        Ok(n)
    }
}

/// Snapshot for the UI: archive size, live-recording health, today's extremes.
#[derive(serde::Serialize)]
pub struct DbStatus {
    pub total_observations: i64,
    pub live_rows_today: i64,
    pub last_write_utc: Option<i64>,
    pub archive_start: Option<String>, // earliest ISO date in the archive
    pub today_high_f: Option<f64>,
    pub today_low_f: Option<f64>,
    pub today_max_gust_mph: Option<f64>,
    pub today_rain_in: Option<f64>,
}

pub fn status() -> Result<DbStatus, rusqlite::Error> {
    let conn = Connection::open(db_path())?;
    // Local midnight -> UTC epoch. Station and app share a timezone.
    let midnight_local = chrono::Local::now()
        .date_naive()
        .and_hms_opt(0, 0, 0)
        .unwrap()
        .and_local_timezone(chrono::Local)
        .unwrap();
    let midnight = midnight_local.timestamp();

    let total: i64 = conn.query_row("SELECT COUNT(*) FROM observations", [], |r| r.get(0))?;
    let live_today: i64 = conn.query_row(
        "SELECT COUNT(*) FROM observations
         WHERE source_id=(SELECT id FROM sources WHERE kind='amb_ws') AND ts_utc >= ?1",
        [midnight],
        |r| r.get(0),
    )?;
    let last_write: Option<i64> = conn.query_row(
        "SELECT MAX(ts_utc) FROM observations
         WHERE source_id=(SELECT id FROM sources WHERE kind='amb_ws')",
        [],
        |r| r.get(0),
    )?;

    let minmax = |metric: &str| -> Result<(Option<f64>, Option<f64>), rusqlite::Error> {
        conn.query_row(
            "SELECT MIN(value), MAX(value) FROM observations
             WHERE metric_id=(SELECT id FROM metrics WHERE name=?1) AND ts_utc >= ?2",
            rusqlite::params![metric, midnight],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
    };
    let (today_low_f, today_high_f) = minmax("tempf")?;
    let (_, today_max_gust_mph) = minmax("windgustmph")?;
    let (_, today_rain_in) = minmax("dailyrainin")?;

    // Cheap archive start from the rollups (95k rows) rather than scanning 17M obs.
    let archive_start: Option<String> = conn
        .query_row("SELECT MIN(day_local) FROM daily_rollups", [], |r| r.get(0))
        .unwrap_or(None);

    Ok(DbStatus {
        total_observations: total,
        live_rows_today: live_today,
        last_write_utc: last_write,
        archive_start,
        today_high_f,
        today_low_f,
        today_max_gust_mph,
        today_rain_in,
    })
}

// ---------- Analyst queries ----------

#[derive(serde::Serialize)]
pub struct SeriesPoint {
    pub t: i64,
    pub avg: f64,
    pub min: f64,
    pub max: f64,
    pub n: i64,
}

#[derive(serde::Serialize)]
pub struct RangeStats {
    pub metric: String,
    pub min_value: f64,
    pub min_ts: i64,
    pub max_value: f64,
    pub max_ts: i64,
    pub avg_value: f64,
    pub n_samples: i64,
    pub days_covered: i64,
    /// Only for windspeedmph: sum over days of (daily avg mph x 24 h) = miles.
    pub wind_run_mi: Option<f64>,
}

/// "YYYY-MM-DD" -> a sortable integer key.
///
/// NOTE: rollup days are CIVIL LOCAL dates (see build_rollups.py), but both
/// this and the `strftime('%s', r.day_local)` in the queries below stamp the
/// bare date at UTC midnight. That is deliberate: the two sides share one
/// naive convention, so the value is a comparable KEY, not a real instant.
/// Never feed the result to anything that treats it as a true timestamp.
fn parse_day(s: &str) -> Result<i64, String> {
    chrono::NaiveDate::parse_from_str(s, "%Y-%m-%d")
        .map_err(|e| e.to_string())
        .map(|d| d.and_hms_opt(0, 0, 0).unwrap().and_utc().timestamp())
}

/// Daily series from rollups (fast path; the Analyst always charts days+).
pub fn series_daily(metric: &str, start: &str, end: &str) -> Result<Vec<SeriesPoint>, String> {
    let conn = Connection::open(db_path()).map_err(|e| e.to_string())?;
    let (a, b) = (parse_day(start)?, parse_day(end)?);
    let mut stmt = conn
        .prepare(
            "SELECT strftime('%s', r.day_local), r.avg_value, r.min_value, r.max_value, r.n_samples
             FROM daily_rollups r
             JOIN metrics m ON m.id = r.metric_id
             WHERE m.name = ?1
               AND strftime('%s', r.day_local) + 0 >= ?2
               AND strftime('%s', r.day_local) + 0 < ?3
             ORDER BY r.day_local",
        )
        .map_err(|e| e.to_string())?;
    let rows = stmt
        .query_map(rusqlite::params![metric, a, b], |r| {
            Ok(SeriesPoint {
                t: r.get::<_, String>(0)?.parse::<i64>().unwrap_or(0),
                avg: r.get(1)?,
                min: r.get(2)?,
                max: r.get(3)?,
                n: r.get(4)?,
            })
        })
        .map_err(|e| e.to_string())?
        .collect::<Result<Vec<_>, _>>()
        .map_err(|e| e.to_string())?;
    Ok(rows)
}

pub fn range_stats(metric: &str, start: &str, end: &str) -> Result<RangeStats, String> {
    let conn = Connection::open(db_path()).map_err(|e| e.to_string())?;
    let (a, b) = (parse_day(start)?, parse_day(end)?);
    let row = conn
        .query_row(
            "SELECT MIN(r.min_value), MAX(r.max_value),
                    SUM(r.avg_value * r.n_samples) / SUM(r.n_samples),
                    SUM(r.n_samples), COUNT(*), SUM(r.avg_value * 24.0)
             FROM daily_rollups r
             JOIN metrics m ON m.id = r.metric_id
             WHERE m.name = ?1
               AND strftime('%s', r.day_local) + 0 >= ?2
               AND strftime('%s', r.day_local) + 0 < ?3",
            rusqlite::params![metric, a, b],
            |r| {
                Ok((
                    r.get::<_, Option<f64>>(0)?,
                    r.get::<_, Option<f64>>(1)?,
                    r.get::<_, Option<f64>>(2)?,
                    r.get::<_, Option<i64>>(3)?,
                    r.get::<_, i64>(4)?,
                    r.get::<_, Option<f64>>(5)?,
                ))
            },
        )
        .map_err(|e| e.to_string())?;
    let (min_v, max_v, avg_v, n, days, wind_run) = row;
    let (min_v, max_v) = (min_v.ok_or("no data in range")?, max_v.ok_or("no data")?);

    let ts_of = |col: &str, val: f64| -> i64 {
        conn.query_row(
            &format!(
                "SELECT {col} FROM daily_rollups r JOIN metrics m ON m.id=r.metric_id
                 WHERE m.name=?1 AND strftime('%s',r.day_local)+0 >= ?2
                   AND strftime('%s',r.day_local)+0 < ?3 AND {vcol} = ?4
                 LIMIT 1",
                col = col,
                vcol = if col == "ts_min" { "r.min_value" } else { "r.max_value" }
            ),
            rusqlite::params![metric, a, b, val],
            |r| r.get(0),
        )
        .unwrap_or(0)
    };
    Ok(RangeStats {
        metric: metric.to_string(),
        min_value: min_v,
        min_ts: ts_of("ts_min", min_v),
        max_value: max_v,
        max_ts: ts_of("ts_max", max_v),
        avg_value: avg_v.unwrap_or(0.0),
        n_samples: n.unwrap_or(0),
        days_covered: days,
        wind_run_mi: if metric == "windspeedmph" { wind_run } else { None },
    })
}

// ---------- Console page queries ----------

#[derive(serde::Serialize, Debug, Clone, Default)]
pub struct Extreme {
    pub value: Option<f64>,
    pub ts: Option<i64>,
}

#[derive(serde::Serialize, Default)]
pub struct DayExtremes {
    pub high_wind: Extreme,
    pub high_gust: Extreme,
    pub min_temp: Extreme,
    pub max_temp: Extreme,
    pub min_press: Extreme,
    pub max_press: Extreme,
    pub max_rain_rate: Extreme,
}

#[derive(serde::Serialize)]
pub struct ConsoleStats {
    pub temp_trend_f_hr: Option<f64>,
    pub press_trend_in_hr: Option<f64>,
    pub humidity_trend_pct_hr: Option<f64>,
    pub avg_temp_today: Option<f64>,
    pub wind_run_today_mi: Option<f64>,
    pub rain_yesterday_in: Option<f64>,
    pub rain_month_in: Option<f64>,
    pub rain_year_in: Option<f64>,
    pub solar_energy_today_kwh: Option<f64>,
    pub solar_energy_yest_kwh: Option<f64>,
    pub today: DayExtremes,
    pub yesterday: DayExtremes,
}

/// Daily solar energy (kWh/m²): trapezoidal time-integral of own-station
/// irradiance. Filtered to our WS-1002 sources (2,3,4) so neighbor-station
/// solar can't contaminate the sum. Gaps over 10 min are not bridged.
fn solar_energy_kwh(conn: &Connection, a: i64, b: i64) -> Option<f64> {
    let mut stmt = conn
        .prepare(
            "SELECT ts_utc, value FROM observations
             WHERE metric_id=(SELECT id FROM metrics WHERE name='solarradiation')
               AND source_id IN (2, 3, 4)
               AND ts_utc >= ?1 AND ts_utc < ?2
             ORDER BY ts_utc",
        )
        .ok()?;
    let rows: Vec<(i64, f64)> = stmt
        .query_map(rusqlite::params![a, b], |r| Ok((r.get(0)?, r.get(1)?)))
        .ok()?
        .flatten()
        .collect();
    if rows.len() < 2 {
        return None;
    }
    let mut joules = 0.0;
    for w in rows.windows(2) {
        let dt = (w[1].0 - w[0].0) as f64;
        if dt > 0.0 && dt <= 600.0 {
            joules += (w[0].1 + w[1].1) / 2.0 * dt; // W/m² × s = J/m²
        }
    }
    Some(joules / 3.6e6) // J/m² → kWh/m²
}

fn local_midnight_epoch(days_back: i64) -> i64 {
    (chrono::Local::now().date_naive() - chrono::Duration::days(days_back))
        .and_hms_opt(0, 0, 0)
        .unwrap()
        .and_local_timezone(chrono::Local)
        .unwrap()
        .timestamp()
}

fn extreme(conn: &Connection, metric: &str, a: i64, b: i64, want_max: bool) -> Extreme {
    let order = if want_max { "DESC" } else { "ASC" };
    conn.query_row(
        &format!(
            "SELECT o.value, o.ts_utc FROM observations o
             WHERE o.metric_id=(SELECT id FROM metrics WHERE name=?1)
               AND o.ts_utc >= ?2 AND o.ts_utc < ?3
             ORDER BY o.value {order}, o.ts_utc ASC LIMIT 1"
        ),
        rusqlite::params![metric, a, b],
        |r| Ok(Extreme { value: r.get(0)?, ts: r.get(1)? }),
    )
    .unwrap_or_default()
}

fn day_extremes(conn: &Connection, a: i64, b: i64) -> DayExtremes {
    DayExtremes {
        high_wind: extreme(conn, "windspeedmph", a, b, true),
        high_gust: extreme(conn, "windgustmph", a, b, true),
        min_temp: extreme(conn, "tempf", a, b, false),
        max_temp: extreme(conn, "tempf", a, b, true),
        min_press: extreme(conn, "baromrelin", a, b, false),
        max_press: extreme(conn, "baromrelin", a, b, true),
        max_rain_rate: extreme(conn, "rainratein", a, b, true),
    }
}

/// Trend per hour: avg of the last 15 min minus avg of minutes 60-75 ago.
fn trend_per_hour(conn: &Connection, metric: &str, now: i64) -> Option<f64> {
    let avg = |a: i64, b: i64| -> Option<f64> {
        conn.query_row(
            "SELECT AVG(value) FROM observations
             WHERE metric_id=(SELECT id FROM metrics WHERE name=?1)
               AND ts_utc >= ?2 AND ts_utc < ?3",
            rusqlite::params![metric, a, b],
            |r| r.get(0),
        )
        .ok()
        .flatten()
    };
    let recent = avg(now - 900, now)?;
    let old = avg(now - 4500, now - 3600)?;
    Some(recent - old)
}

pub fn console_stats() -> Result<ConsoleStats, rusqlite::Error> {
    let conn = Connection::open(db_path())?;
    let now = chrono::Utc::now().timestamp();
    let mid0 = local_midnight_epoch(0);
    let mid1 = local_midnight_epoch(1);

    let scalar = |q: &str, a: i64, b: i64| -> Option<f64> {
        conn.query_row(q, rusqlite::params![a, b], |r| r.get(0)).ok().flatten()
    };
    let avg_temp_today = scalar(
        "SELECT AVG(value) FROM observations
         WHERE metric_id=(SELECT id FROM metrics WHERE name='tempf')
           AND ts_utc >= ?1 AND ts_utc < ?2",
        mid0, now,
    );
    // Wind run today: mean speed x elapsed hours since local midnight.
    let wind_run_today_mi = scalar(
        "SELECT AVG(value) FROM observations
         WHERE metric_id=(SELECT id FROM metrics WHERE name='windspeedmph')
           AND ts_utc >= ?1 AND ts_utc < ?2",
        mid0, now,
    )
    .map(|v| v * ((now - mid0) as f64 / 3600.0));
    let rain_yesterday_in = scalar(
        "SELECT MAX(value) FROM observations
         WHERE metric_id=(SELECT id FROM metrics WHERE name='dailyrainin')
           AND ts_utc >= ?1 AND ts_utc < ?2",
        mid1, mid0,
    );
    let latest = |metric: &str| -> Option<f64> {
        conn.query_row(
            "SELECT value FROM observations
             WHERE metric_id=(SELECT id FROM metrics WHERE name=?1)
             ORDER BY ts_utc DESC LIMIT 1",
            [metric],
            |r| r.get(0),
        )
        .ok()
    };

    Ok(ConsoleStats {
        temp_trend_f_hr: trend_per_hour(&conn, "tempf", now),
        press_trend_in_hr: trend_per_hour(&conn, "baromrelin", now),
        humidity_trend_pct_hr: trend_per_hour(&conn, "humidity", now),
        avg_temp_today,
        wind_run_today_mi,
        rain_yesterday_in,
        rain_month_in: latest("monthlyrainin"),
        rain_year_in: latest("yearlyrainin"),
        solar_energy_today_kwh: solar_energy_kwh(&conn, mid0, now),
        solar_energy_yest_kwh: solar_energy_kwh(&conn, mid1, mid0),
        today: day_extremes(&conn, mid0, now),
        yesterday: day_extremes(&conn, mid1, mid0),
    })
}

// ---------- Today / Yesterday comparison ----------

#[derive(serde::Serialize, Default)]
pub struct DayStat {
    pub high: Extreme,
    pub low: Extreme,
    pub avg: Option<f64>,
}

#[derive(serde::Serialize)]
pub struct MetricPair {
    pub metric: String,
    pub today: DayStat,
    pub yesterday: DayStat,
}

#[derive(serde::Serialize)]
pub struct DayCompare {
    pub metrics: Vec<MetricPair>,
    pub wind_run_today: Option<f64>,
    pub wind_run_yest: Option<f64>,
    pub dom_dir_today: Option<f64>,
    pub dom_dir_yest: Option<f64>,
    pub solar_energy_today: Option<f64>,
    pub solar_energy_yest: Option<f64>,
}

fn day_stat(conn: &Connection, metric: &str, a: i64, b: i64) -> DayStat {
    let avg = conn
        .query_row(
            "SELECT AVG(value) FROM observations
             WHERE metric_id=(SELECT id FROM metrics WHERE name=?1)
               AND ts_utc >= ?2 AND ts_utc < ?3",
            rusqlite::params![metric, a, b],
            |r| r.get(0),
        )
        .ok()
        .flatten();
    DayStat {
        high: extreme(conn, metric, a, b, true),
        low: extreme(conn, metric, a, b, false),
        avg,
    }
}

/// Wind run (miles): mean speed over the window × elapsed hours.
fn wind_run_for(conn: &Connection, a: i64, b: i64, hours: f64) -> Option<f64> {
    conn.query_row(
        "SELECT AVG(value) FROM observations
         WHERE metric_id=(SELECT id FROM metrics WHERE name='windspeedmph')
           AND ts_utc >= ?1 AND ts_utc < ?2",
        rusqlite::params![a, b],
        |r| r.get::<_, Option<f64>>(0),
    )
    .ok()
    .flatten()
    .map(|v| v * hours)
}

/// Dominant wind direction (deg): speed-weighted vector mean over the window.
fn dominant_dir(conn: &Connection, a: i64, b: i64) -> Option<f64> {
    let mut stmt = conn
        .prepare(
            "SELECT d.value, s.value FROM observations d
             JOIN observations s ON s.ts_utc = d.ts_utc
             WHERE d.metric_id=(SELECT id FROM metrics WHERE name='winddir')
               AND s.metric_id=(SELECT id FROM metrics WHERE name='windspeedmph')
               AND d.ts_utc >= ?1 AND d.ts_utc < ?2",
        )
        .ok()?;
    let rows = stmt
        .query_map(rusqlite::params![a, b], |r| {
            Ok((r.get::<_, f64>(0)?, r.get::<_, f64>(1)?))
        })
        .ok()?;
    let (mut east, mut north) = (0.0_f64, 0.0_f64);
    for (dir, spd) in rows.flatten() {
        let w = if spd > 0.0 { spd } else { 0.1 }; // calm still contributes a little
        east += w * dir.to_radians().sin();
        north += w * dir.to_radians().cos();
    }
    if east == 0.0 && north == 0.0 {
        return None;
    }
    let mut deg = east.atan2(north).to_degrees();
    if deg < 0.0 {
        deg += 360.0;
    }
    Some(deg)
}

pub fn day_compare() -> Result<DayCompare, rusqlite::Error> {
    let conn = Connection::open(db_path())?;
    let now = chrono::Utc::now().timestamp();
    let mid0 = local_midnight_epoch(0);
    let mid1 = local_midnight_epoch(1);

    let names = [
        "tempf", "dewpointf", "humidity", "baromrelin", "windspeedmph",
        "windgustmph", "rainratein", "dailyrainin", "solarradiation", "uv",
        // Derived at record time (see value_pairs) — the apparent-temperature
        // family plus the two NWS indices, which are None outside their valid
        // ranges and so simply render as "--" on a mild day.
        "apparenttempf", "humidexf", "wetbulbf", "heatindexf", "windchillf",
    ];
    let metrics = names
        .iter()
        .map(|m| MetricPair {
            metric: m.to_string(),
            today: day_stat(&conn, m, mid0, now),
            yesterday: day_stat(&conn, m, mid1, mid0),
        })
        .collect();

    let hours_today = (now - mid0) as f64 / 3600.0;
    Ok(DayCompare {
        metrics,
        wind_run_today: wind_run_for(&conn, mid0, now, hours_today),
        wind_run_yest: wind_run_for(&conn, mid1, mid0, 24.0),
        dom_dir_today: dominant_dir(&conn, mid0, now),
        dom_dir_yest: dominant_dir(&conn, mid1, mid0),
        solar_energy_today: solar_energy_kwh(&conn, mid0, now),
        solar_energy_yest: solar_energy_kwh(&conn, mid1, mid0),
    })
}

#[derive(serde::Serialize)]
pub struct WindRose {
    /// counts[sector][bin]: 16 compass sectors (N=0, clockwise), speed bins
    /// [0-2, 2-5, 5-10, 10-15, 15-20, 20+] mph.
    pub counts: Vec<Vec<u32>>,
    pub total: u32,
    pub calm: u32,
    pub hours: i64,
}

pub fn wind_rose(hours: i64) -> Result<WindRose, rusqlite::Error> {
    let conn = Connection::open(db_path())?;
    let since = chrono::Utc::now().timestamp() - hours * 3600;
    let mut counts = vec![vec![0u32; 6]; 16];
    let (mut total, mut calm) = (0u32, 0u32);
    let mut stmt = conn.prepare(
        "SELECT d.value, s.value FROM observations d
         JOIN observations s ON s.ts_utc = d.ts_utc
           AND s.metric_id = (SELECT id FROM metrics WHERE name='windspeedmph')
         WHERE d.metric_id = (SELECT id FROM metrics WHERE name='winddir')
           AND d.ts_utc >= ?1",
    )?;
    let rows = stmt.query_map([since], |r| Ok((r.get::<_, f64>(0)?, r.get::<_, f64>(1)?)))?;
    // Bin edges are KNOTS (the station's display unit — see src/units.ts).
    // Observations are stored in mph, so convert first; the 20+ red band
    // therefore means 20 kt (~23 mph), which is what MXC intends by it.
    const MPH_TO_KT: f64 = 0.8689762419006479;
    for row in rows {
        let (dir, speed_mph) = row?;
        let speed = speed_mph * MPH_TO_KT;
        total += 1;
        if speed < 0.5 {
            calm += 1;
            continue;
        }
        let sector = ((dir / 22.5).round() as usize) % 16;
        let bin = match speed {
            s if s < 2.0 => 0,
            s if s < 5.0 => 1,
            s if s < 10.0 => 2,
            s if s < 15.0 => 3,
            s if s < 20.0 => 4,
            _ => 5,
        };
        counts[sector][bin] += 1;
    }
    Ok(WindRose { counts, total, calm, hours })
}

/// Hourly series over the last N hours, straight from observations
/// (bounded scan; used for the dashboard chart thumbnails).
pub fn series_hours(metric: &str, hours: i64) -> Result<Vec<SeriesPoint>, String> {
    let conn = Connection::open(db_path()).map_err(|e| e.to_string())?;
    let since = chrono::Utc::now().timestamp() - hours * 3600;
    let mut stmt = conn
        .prepare(
            "SELECT (ts_utc / 3600) * 3600 AS h, AVG(value), MIN(value), MAX(value), COUNT(*)
             FROM observations
             WHERE metric_id = (SELECT id FROM metrics WHERE name = ?1) AND ts_utc >= ?2
             GROUP BY h ORDER BY h",
        )
        .map_err(|e| e.to_string())?;
    let rows = stmt
        .query_map(rusqlite::params![metric, since], |r| {
            Ok(SeriesPoint {
                t: r.get(0)?, avg: r.get(1)?, min: r.get(2)?, max: r.get(3)?, n: r.get(4)?,
            })
        })
        .map_err(|e| e.to_string())?
        .collect::<Result<Vec<_>, _>>()
        .map_err(|e| e.to_string())?;
    Ok(rows)
}

/// One metric's series over an arbitrary window, at ADAPTIVE resolution.
///
/// The existing two series endpoints both quantise away the things worth
/// looking at: `query_series` returns daily rollups and `series_hours`
/// buckets to the hour. The dry-line event of 2026-08-26 collapsed the
/// dewpoint 13 F in 28 minutes and recovered 6 F in seven — at hourly
/// resolution that is two bars and no story.
///
/// So the bucket is chosen from the window, not fixed: short spans return
/// RAW observations (bucket = 1 s, i.e. no grouping at all), and longer ones
/// widen only as far as needed to stay under `max_points`. The caller gets
/// the finest resolution that will actually fit on a screen.
///
/// `n` is carried per point so the UI can tell a real reading from a wide
/// bucket that happens to average to the same value.
pub fn series_window(
    metric: &str,
    start_ts: i64,
    end_ts: i64,
    max_points: i64,
) -> Result<Vec<SeriesPoint>, String> {
    let conn = Connection::open(db_path()).map_err(|e| e.to_string())?;
    let span = (end_ts - start_ts).max(1);
    let cap = max_points.clamp(50, 20_000);
    // Snap to a human-legible bucket rather than an arbitrary quotient — a
    // 37-second bucket makes the x-axis lie about where samples fall.
    const STEPS: [i64; 13] = [1, 60, 300, 600, 900, 1800, 3600, 10800, 21600,
                              43200, 86400, 604800, 2592000];
    let want = span / cap;
    let bucket = *STEPS.iter().find(|&&s| s >= want).unwrap_or(STEPS.last().unwrap());

    let mut stmt = conn
        .prepare(
            "SELECT (ts_utc / ?3) * ?3 AS b, AVG(value), MIN(value), MAX(value), COUNT(*)
             FROM observations
             WHERE metric_id = (SELECT id FROM metrics WHERE name = ?1)
               AND ts_utc >= ?2 AND ts_utc <= ?4
             GROUP BY b ORDER BY b",
        )
        .map_err(|e| e.to_string())?;
    let rows = stmt
        .query_map(rusqlite::params![metric, start_ts, bucket, end_ts], |r| {
            Ok(SeriesPoint {
                t: r.get(0)?, avg: r.get(1)?, min: r.get(2)?, max: r.get(3)?, n: r.get(4)?,
            })
        })
        .map_err(|e| e.to_string())?
        .collect::<Result<Vec<_>, _>>()
        .map_err(|e| e.to_string())?;
    Ok(rows)
}

/// Recompute `daily_rollups` for every day flagged in `rollup_dirty`.
///
/// `daily_rollups` is a pure derived cache, and until now it was only ever
/// rebuilt by hand (`python scripts/build_rollups.py`). That meant a
/// perpetually-running recorder would still show a frozen Records page: live
/// data current to the minute, history stuck at whenever someone last ran the
/// script. This closes that.
///
/// PERFORMANCE, because the obvious query is unusable. Filtering
/// `canonical_observations` by a day's epoch range takes **9.5 seconds** for a
/// recent day: the view's join gives SQLite `o.ts_utc >= p.period_start` as a
/// candidate lower bound, and the current priority period is open-ended and
/// starts in 2025, so it range-scans thirteen months of data to roll up one
/// day. Older days sit in bounded periods and are fast, which is what made the
/// problem visible. Collapsing the bounds with `max()`/`min()` BEFORE the index
/// sees them takes the same query to **6 ms** — a 1,460x difference for an
/// identical result (verified against the Python builder on ten days,
/// including a DST transition).
///
/// Semantics deliberately mirror `build_rollups.py` exactly, including
/// `ts_min`/`ts_max` being the EARLIEST timestamp at which the extreme
/// occurred. If you change one, change both.
pub fn refresh_dirty_rollups() -> Result<(usize, usize), String> {
    let conn = Connection::open(db_path()).map_err(|e| e.to_string())?;
    conn.busy_timeout(std::time::Duration::from_secs(10))
        .map_err(|e| e.to_string())?;

    let days: Vec<String> = {
        let mut stmt = conn
            .prepare("SELECT day_local FROM rollup_dirty ORDER BY day_local")
            .map_err(|e| e.to_string())?;
        let rows = stmt
            .query_map([], |r| r.get::<_, String>(0))
            .map_err(|e| e.to_string())?;
        rows.collect::<Result<Vec<_>, _>>()
            .map_err(|e| e.to_string())?
    };
    if days.is_empty() {
        return Ok((0, 0));
    }

    let mut total_rows = 0usize;
    for day in &days {
        // Local midnight -> UTC epoch, for this day and the next. Deriving BOTH
        // ends this way is what makes the 23- and 25-hour DST days correct.
        let (a, b): (i64, i64) = conn
            .query_row(
                "SELECT CAST(strftime('%s', ?1 || ' 00:00:00', 'utc') AS INTEGER),
                        CAST(strftime('%s', date(?1, '+1 day') || ' 00:00:00', 'utc') AS INTEGER)",
                [day],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .map_err(|e| e.to_string())?;

        let tx = conn.unchecked_transaction().map_err(|e| e.to_string())?;
        tx.execute("DELETE FROM daily_rollups WHERE day_local = ?1", [day])
            .map_err(|e| e.to_string())?;
        let n = tx
            .execute(
                "WITH canon AS (
                     SELECT o.metric_id, o.ts_utc, o.value,
                            ROW_NUMBER() OVER (
                                PARTITION BY o.metric_id, o.ts_utc ORDER BY p.rank
                            ) rn
                     FROM observations o
                     JOIN sources s ON s.id = o.source_id
                     JOIN source_priority p ON p.source_kind = s.kind
                          AND o.ts_utc >= max(p.period_start, ?1)
                          AND o.ts_utc <  min(coalesce(p.period_end, ?2), ?2)
                 ),
                 d AS (SELECT metric_id, ts_utc, value FROM canon WHERE rn = 1),
                 agg AS (SELECT metric_id, AVG(value) av, MIN(value) mn,
                                MAX(value) mx, COUNT(*) n
                         FROM d GROUP BY metric_id)
                 INSERT INTO daily_rollups
                     (metric_id, day_local, avg_value, min_value, max_value,
                      n_samples, ts_min, ts_max)
                 SELECT a.metric_id, ?3, a.av, a.mn, a.mx, a.n,
                        (SELECT MIN(ts_utc) FROM d
                          WHERE d.metric_id = a.metric_id AND d.value = a.mn),
                        (SELECT MIN(ts_utc) FROM d
                          WHERE d.metric_id = a.metric_id AND d.value = a.mx)
                 FROM agg a",
                rusqlite::params![a, b, day],
            )
            .map_err(|e| e.to_string())?;
        // Clear the flag inside the SAME transaction as the recompute, so a
        // crash mid-refresh leaves the day dirty and it is simply redone.
        tx.execute("DELETE FROM rollup_dirty WHERE day_local = ?1", [day])
            .map_err(|e| e.to_string())?;
        tx.commit().map_err(|e| e.to_string())?;
        total_rows += n;
    }
    Ok((days.len(), total_rows))
}

// ---------- Min/Max Records (all-time hall of fame) ----------

#[derive(serde::Serialize)]
pub struct RecordRow {
    pub label: String,
    pub value: f64,
    pub unit: String,
    pub when_ts: Option<i64>,     // epoch for instantaneous records
    pub when_day: Option<String>, // ISO date for daily-derived records
}

#[derive(serde::Serialize)]
pub struct RecordCategory {
    pub name: String,
    pub rows: Vec<RecordRow>,
}

// Instantaneous all-time extreme from daily_rollups (value + the epoch it occurred).
fn inst_ext(conn: &Connection, metric: &str, want_max: bool) -> Option<(f64, i64)> {
    let (vcol, tscol, ord) = if want_max {
        ("max_value", "ts_max", "DESC")
    } else {
        ("min_value", "ts_min", "ASC")
    };
    conn.query_row(
        &format!(
            "SELECT r.{vcol}, r.{tscol} FROM daily_rollups r
             JOIN metrics m ON m.id = r.metric_id
             WHERE m.name = ?1 ORDER BY r.{vcol} {ord} LIMIT 1"
        ),
        [metric],
        |r| Ok((r.get(0)?, r.get(1)?)),
    )
    .ok()
}

// Daily-derived extreme (e.g. highest daily minimum): value + the day it happened.
fn day_ext(conn: &Connection, metric: &str, expr: &str, want_max: bool) -> Option<(f64, String)> {
    let ord = if want_max { "DESC" } else { "ASC" };
    conn.query_row(
        &format!(
            "SELECT {expr} AS v, r.day_local FROM daily_rollups r
             JOIN metrics m ON m.id = r.metric_id
             WHERE m.name = ?1 ORDER BY v {ord} LIMIT 1"
        ),
        [metric],
        |r| Ok((r.get(0)?, r.get(1)?)),
    )
    .ok()
}

fn inst_row(conn: &Connection, label: &str, metric: &str, unit: &str, max: bool) -> Option<RecordRow> {
    inst_ext(conn, metric, max).map(|(v, ts)| RecordRow {
        label: label.into(), value: v, unit: unit.into(), when_ts: Some(ts), when_day: None,
    })
}

fn day_row(conn: &Connection, label: &str, metric: &str, expr: &str, unit: &str, max: bool) -> Option<RecordRow> {
    day_ext(conn, metric, expr, max).map(|(v, d)| RecordRow {
        label: label.into(), value: v, unit: unit.into(), when_ts: None, when_day: Some(d),
    })
}

pub fn records() -> Result<Vec<RecordCategory>, rusqlite::Error> {
    let conn = Connection::open(db_path())?;
    let mut cats: Vec<RecordCategory> = Vec::new();

    let temperature = [
        inst_row(&conn, "Highest temperature", "tempf", "°F", true),
        inst_row(&conn, "Lowest temperature", "tempf", "°F", false),
        inst_row(&conn, "Highest heat index", "heatindexf", "°F", true),
        inst_row(&conn, "Lowest wind chill", "windchillf", "°F", false),
        inst_row(&conn, "Highest feels-like", "feelslikef", "°F", true),
        inst_row(&conn, "Lowest feels-like", "feelslikef", "°F", false),
        day_row(&conn, "Highest daily minimum", "tempf", "r.min_value", "°F", true),
        day_row(&conn, "Lowest daily maximum", "tempf", "r.max_value", "°F", false),
        inst_row(&conn, "Highest dew point", "dewpointf", "°F", true),
        inst_row(&conn, "Lowest dew point", "dewpointf", "°F", false),
        day_row(&conn, "Highest daily temp range", "tempf", "(r.max_value - r.min_value)", "°F", true),
        day_row(&conn, "Lowest daily temp range", "tempf", "(r.max_value - r.min_value)", "°F", false),
    ];
    cats.push(RecordCategory { name: "Temperature".into(), rows: temperature.into_iter().flatten().collect() });

    let mut wind: Vec<RecordRow> = [
        inst_row(&conn, "Highest gust", "windgustmph", "mph", true),
        inst_row(&conn, "Highest sustained wind", "windspeedmph", "mph", true),
    ].into_iter().flatten().collect();
    if let Some((v, d)) = conn.query_row(
        "SELECT wind_run_mi, date FROM daily_summaries
         WHERE wind_run_mi IS NOT NULL ORDER BY wind_run_mi DESC LIMIT 1",
        [], |r| Ok((r.get::<_, f64>(0)?, r.get::<_, String>(1)?)),
    ).ok() {
        wind.push(RecordRow { label: "Highest daily wind run".into(), value: v, unit: "mi".into(), when_ts: None, when_day: Some(d) });
    }
    cats.push(RecordCategory { name: "Wind".into(), rows: wind });

    let rain = [
        day_row(&conn, "Wettest day", "dailyrainin", "r.max_value", "in", true),
        inst_row(&conn, "Highest rain rate", "rainratein", "in/hr", true),
        day_row(&conn, "Wettest month", "monthlyrainin", "r.max_value", "in", true),
        day_row(&conn, "Wettest year", "yearlyrainin", "r.max_value", "in", true),
    ];
    cats.push(RecordCategory { name: "Rainfall".into(), rows: rain.into_iter().flatten().collect() });

    let humidity = [
        inst_row(&conn, "Highest humidity", "humidity", "%", true),
        inst_row(&conn, "Lowest humidity", "humidity", "%", false),
    ];
    cats.push(RecordCategory { name: "Humidity".into(), rows: humidity.into_iter().flatten().collect() });

    let pressure = [
        inst_row(&conn, "Highest pressure", "baromrelin", "inHg", true),
        inst_row(&conn, "Lowest pressure", "baromrelin", "inHg", false),
    ];
    cats.push(RecordCategory { name: "Pressure".into(), rows: pressure.into_iter().flatten().collect() });

    let solar = [
        inst_row(&conn, "Highest solar radiation", "solarradiation", "W/m²", true),
        inst_row(&conn, "Highest UV index", "uv", "index", true),
    ];
    cats.push(RecordCategory { name: "Solar".into(), rows: solar.into_iter().flatten().collect() });

    Ok(cats)
}

// ---------- Auto-backfill on launch ----------
//
// The station uploads to AmbientWeather's cloud 24/7 regardless of whether
// this PC is running. On launch we pull any readings the cloud captured
// since our last recorded observation and insert them as `amb_rest`, so the
// archive stays complete no matter how intermittently the app runs. (Gaps
// where the station itself couldn't reach the cloud — e.g. a home internet
// outage — are a separate concern, filled from a neighbor station.)
//
// Progress is emitted to the frontend as "backfill" events for the nav
// footer indicator. Inserts land in `observations`; daily_rollups refresh on
// the next Python rebuild (the live pages read observations directly).

use tauri::{AppHandle, Emitter};

const AMBIENT_API_BASE: &str = "https://rt.ambientweather.net/v1";

fn last_cloud_ts(conn: &Connection) -> Option<i64> {
    conn.query_row(
        "SELECT MAX(ts_utc) FROM observations
         WHERE source_id IN (SELECT id FROM sources WHERE kind IN ('amb_rest','amb_ws'))",
        [], |r| r.get(0),
    ).ok().flatten()
}

/// A hole in the Ambient-sourced record: `(last reading before, first after)`.
pub type Gap = (i64, i64);

/// Readings arrive ~1/min live and every 5 min via REST; Ambient thins older
/// data to 10 min. Anything past 15 minutes is a real hole, not cadence.
const GAP_MIN_SECS: i64 = 900;
/// How far back routine scans look. Ambient's retention makes anything older a
/// one-off archaeology job, not a job for a timer.
const GAP_SCAN_DAYS: i64 = 30;
/// A hole that yielded nothing last time is probably unfillable — the station
/// or the house internet was down, so Ambient has nothing either. Do not
/// re-request it on every tick; Ambient allows ~1 request/second per key.
const GAP_RETRY_SECS: i64 = 6 * 3600;

/// Find holes in the Ambient-sourced record, newest first.
///
/// THE BUG THIS EXISTS TO FIX: the original Backfill asked only "does the
/// archive reach the present?" — `last_cloud_ts()` is a MAX over amb_rest and
/// amb_ws. After the machine sleeps, the Recorder resumes on wake and pushes
/// that MAX to now, so the archive *looks* complete and Backfill exits in
/// under a millisecond. It handled TRAILING gaps beautifully (26 days
/// recovered on 2026-09-21) and was structurally blind to INTERIOR ones,
/// which is what sleep produces every single night. Measured on 2026-09-22:
/// 16 interior gaps and 62 hours missing across the previous year, none of
/// which would ever have been noticed, let alone filled.
///
/// The trailing gap is returned too — it is just a hole whose far end is now.
fn find_gaps(conn: &Connection, scan_days: i64, min_gap: i64) -> Vec<Gap> {
    let now = chrono::Utc::now().timestamp();
    let since = now - scan_days * 86_400;
    let mut gaps: Vec<Gap> = Vec::new();

    let mut stmt = match conn.prepare(
        "SELECT prev_ts, ts_utc FROM (
             SELECT ts_utc, LAG(ts_utc) OVER (ORDER BY ts_utc) AS prev_ts
             FROM observations
             WHERE metric_id = (SELECT id FROM metrics WHERE name='tempf')
               AND source_id IN (SELECT id FROM sources
                                 WHERE kind IN ('amb_rest','amb_ws'))
               AND ts_utc >= ?1
         )
         WHERE prev_ts IS NOT NULL AND ts_utc - prev_ts > ?2
         ORDER BY prev_ts DESC",
    ) {
        Ok(s) => s,
        Err(_) => return gaps,
    };
    if let Ok(rows) = stmt.query_map(rusqlite::params![since, min_gap], |r| {
        Ok((r.get::<_, i64>(0)?, r.get::<_, i64>(1)?))
    }) {
        gaps.extend(rows.flatten());
    }

    // ...and the trailing edge, which the LAG scan cannot see.
    if let Some(last) = last_cloud_ts(conn) {
        if now - last > min_gap {
            gaps.insert(0, (last, now));
        }
    }
    gaps
}

/// Should we attempt this hole now? False when a recent attempt came back
/// empty — see `GAP_RETRY_SECS`.
fn gap_worth_attempting(conn: &Connection, gap: Gap) -> bool {
    let now = chrono::Utc::now().timestamp();
    match conn.query_row(
        "SELECT last_attempt, rows_gained FROM backfill_attempts WHERE gap_start = ?1",
        [gap.0],
        |r| Ok((r.get::<_, i64>(0)?, r.get::<_, i64>(1)?)),
    ) {
        Ok((last_attempt, gained)) => gained > 0 || now - last_attempt > GAP_RETRY_SECS,
        Err(_) => true, // never tried
    }
}

fn record_attempt(conn: &Connection, gap: Gap, gained: i64) {
    let now = chrono::Utc::now().timestamp();
    let _ = conn.execute(
        "INSERT INTO backfill_attempts(gap_start, gap_end, last_attempt, attempts, rows_gained)
         VALUES (?1, ?2, ?3, 1, ?4)
         ON CONFLICT(gap_start) DO UPDATE SET
             gap_end      = excluded.gap_end,
             last_attempt = excluded.last_attempt,
             attempts     = attempts + 1,
             rows_gained  = excluded.rows_gained",
        rusqlite::params![gap.0, gap.1, now, gained],
    );
}

/// Fetch one range `(from, to]` from Ambient and insert it.
///
/// Walks backwards in pages of 288 from `to`, stopping once a page reaches
/// back past `from`. Returns the number of rows that were actually NEW, which
/// is what distinguishes an unfillable hole from one we merely re-fetched.
#[allow(clippy::too_many_arguments)]
async fn fill_range(
    client: &reqwest::Client,
    mac_enc: &str,
    app_key: &str,
    api_key: &str,
    from_ts: i64,
    to_ts: i64,
    app: &AppHandle,
    done: &mut usize,
) -> i64 {
    let from_ms = from_ts * 1000;
    let to_ms = to_ts * 1000;
    let mut end_date: Option<i64> = Some(to_ms);
    let mut pages = 0;
    let mut gained: i64 = 0;

    loop {
        if pages > 400 {
            break; // safety
        }
        let mut url = format!(
            "{AMBIENT_API_BASE}/devices/{mac_enc}?applicationKey={app_key}&apiKey={api_key}&limit=288"
        );
        if let Some(ed) = end_date {
            url.push_str(&format!("&endDate={ed}"));
        }

        // Fetch with backoff — 429s clear once we slow below 1 req/sec.
        let mut fetched: Option<Vec<AmbientReading>> = None;
        for attempt in 0..4u64 {
            match client.get(&url).send().await.and_then(|r| r.error_for_status()) {
                Ok(resp) => match resp.json::<Vec<AmbientReading>>().await {
                    Ok(pg) => {
                        fetched = Some(pg);
                        break;
                    }
                    Err(e) => {
                        println!("Backfill: parse failed: {e}");
                        break;
                    }
                },
                Err(e) => {
                    println!("Backfill: fetch attempt {} failed ({e}); backing off", attempt + 1);
                    tokio::time::sleep(std::time::Duration::from_secs(2 * (attempt + 1))).await;
                }
            }
        }
        let page = match fetched {
            Some(pg) => pg,
            None => break,
        };
        if page.is_empty() {
            break;
        }

        // Records are newest-first.
        let oldest_ms = page.last().map(|r| r.dateutc).unwrap_or(from_ms);
        if let Ok(conn) = Connection::open(db_path()) {
            let _ = conn.busy_timeout(std::time::Duration::from_secs(5));
            let sid: Option<i64> = conn
                .query_row("SELECT id FROM sources WHERE kind='amb_rest'", [], |r| r.get(0))
                .ok();
            if let Some(sid) = sid {
                let mids: HashMap<String, i64> = conn
                    .prepare("SELECT name, id FROM metrics")
                    .ok()
                    .and_then(|mut st| {
                        st.query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, i64>(1)?)))
                            .ok()
                            .map(|rows| rows.flatten().collect())
                    })
                    .unwrap_or_default();
                for reading in &page {
                    // Strictly inside the hole. Anything outside either exists
                    // already or belongs to a different gap's attempt.
                    if reading.dateutc <= from_ms || reading.dateutc > to_ms {
                        continue;
                    }
                    let ts = reading.dateutc / 1000;
                    for (name, val) in value_pairs(reading) {
                        if let (Some(v), Some(&mid)) = (val, mids.get(name)) {
                            if let Ok(n) = conn.execute(
                                "INSERT OR IGNORE INTO observations(metric_id, ts_utc, source_id, value)
                                 VALUES (?1, ?2, ?3, ?4)",
                                rusqlite::params![mid, ts, sid, v],
                            ) {
                                gained += n as i64;
                            }
                            *done += 1;
                        }
                    }
                }
            }
        }
        let _ = app.emit("backfill", serde_json::json!({ "active": true, "done": *done }));
        pages += 1;

        if oldest_ms <= from_ms {
            break;
        }
        end_date = Some(oldest_ms - 1);
        tokio::time::sleep(std::time::Duration::from_millis(1100)).await;
    }
    gained
}

/// Find every hole in the recent Ambient record and fill what can be filled.
///
/// Supersedes the original "is the archive behind?" check, which could only
/// ever see a trailing gap. See `find_gaps` for why that was structurally
/// blind to the holes sleep leaves every night.
pub async fn backfill(app: AppHandle) {
    dotenvy::dotenv().ok();
    let api_key = match std::env::var("AMBIENT_API_KEY") {
        Ok(k) => k,
        Err(_) => return,
    };
    let app_key = match std::env::var("AMBIENT_APP_KEY") {
        Ok(k) => k,
        Err(_) => return,
    };

    let gaps: Vec<Gap> = {
        let conn = match Connection::open(db_path()) {
            Ok(c) => c,
            Err(_) => return,
        };
        let _ = conn.busy_timeout(std::time::Duration::from_secs(5));
        if last_cloud_ts(&conn).is_none() {
            return; // empty archive: use the Python rescue, not this
        }
        find_gaps(&conn, GAP_SCAN_DAYS, GAP_MIN_SECS)
            .into_iter()
            .filter(|g| gap_worth_attempting(&conn, *g))
            .collect()
    };
    if gaps.is_empty() {
        return;
    }
    let total: i64 = gaps.iter().map(|(a, b)| b - a).sum();
    println!(
        "Backfill: {} gap(s) worth {:.1} h; fetching...",
        gaps.len(),
        total as f64 / 3600.0
    );

    let client = reqwest::Client::builder()
        .user_agent("SoledadWX/1.0")
        .build()
        .unwrap_or_default();

    // Resolve the device MAC.
    let dev_url = format!("{AMBIENT_API_BASE}/devices?applicationKey={app_key}&apiKey={api_key}");
    let mac: String = match client.get(&dev_url).send().await.and_then(|r| r.error_for_status()) {
        Ok(resp) => match resp.json::<serde_json::Value>().await {
            Ok(v) => match v.get(0).and_then(|d| d["macAddress"].as_str()) {
                Some(m) => m.to_string(),
                None => return,
            },
            Err(_) => return,
        },
        Err(e) => {
            println!("Backfill: device list failed: {e}");
            return;
        }
    };
    let mac_enc = mac.replace(':', "%3A");

    let _ = app.emit("backfill", serde_json::json!({ "active": true, "done": 0 }));
    // Ambient allows <= 1 req/sec per key; the device call just fired.
    tokio::time::sleep(std::time::Duration::from_millis(1200)).await;

    let mut done = 0usize;
    for gap in gaps {
        let gained = fill_range(
            &client, &mac_enc, &app_key, &api_key, gap.0, gap.1, &app, &mut done,
        )
        .await;
        if let Ok(conn) = Connection::open(db_path()) {
            let _ = conn.busy_timeout(std::time::Duration::from_secs(5));
            record_attempt(&conn, gap, gained);
        }
        let mins = (gap.1 - gap.0) / 60;
        if gained > 0 {
            println!("Backfill: {mins} min hole -> {gained} new values.");
        } else {
            println!(
                "Backfill: {} min hole yielded nothing; Ambient has no data either. \
Not retrying for {} h.",
                mins,
                GAP_RETRY_SECS / 3600
            );
        }
    }

    println!("Backfill: done, {done} metric-values seen.");
    let _ = app.emit("backfill", serde_json::json!({ "active": false, "done": done }));
}

// ---------- Synopsis by Period ----------
//
// The report card for one period, after Cumulus's "Averages and Extremes".
// Days are civil-local, start inclusive and end exclusive, as everywhere.
// Most figures come from daily_rollups. Wind run and solar energy are
// integrated over time instead, because a sample-weighted mean is biased by
// how densely each era happened to log.

/// A day is hot when its high reaches this (°F). Stands in for Cumulus's
/// "air frosts", which never happen on Mount Soledad.
const HOT_DAY_F: f64 = 90.0;

/// A night is warm when the day's low stays at or above this (°F).
const WARM_NIGHT_F: f64 = 70.0;

/// Beaufort force 8 (34 kt), in mph. A day whose highest sustained wind
/// reaches it is a gale day.
const GALE_MPH: f64 = 34.0 / 0.868_976_241_900_647_9;

/// The smallest daily total that makes a rain day (in): Cumulus's 0.2 mm
/// default, rounded to the gauge's 0.01 in resolution.
const RAIN_DAY_IN: f64 = 0.01;

/// Wind run integration never bridges a gap longer than this. Cumulus-era
/// days logged roughly every 15 minutes; 30 keeps them without inventing
/// wind across a real outage.
const WIND_GAP_MAX_SECS: i64 = 1800;

/// Solar integration never bridges a gap longer than this (matches
/// `solar_energy_kwh`, used by the Console).
const SOLAR_GAP_MAX_SECS: i64 = 600;

/// Sources that are another instrument, not ours. Their readings are labeled
/// as proxy wherever they reach a figure.
const PROXY_KINDS: [&str; 5] = ["msdsd", "ksan_metar", "wu_ksandi354", "wu_ksandi4366", "wu_ksandi84"];

/// A value tied to a whole civil-local day, such as the highest minimum.
#[derive(serde::Serialize, Debug, Clone, PartialEq)]
pub struct DayValue {
    pub value: f64,
    pub day: String,
}

#[derive(serde::Serialize, Debug, Default)]
pub struct SynTemp {
    /// Mean of every reading (Cumulus: "Mean (1 minute)").
    pub mean_all: Option<f64>,
    /// Mean of each day's (min + max) / 2.
    pub mean_minmax: Option<f64>,
    pub mean_min: Option<f64>,
    pub mean_max: Option<f64>,
    pub min: Extreme,
    pub max: Extreme,
    pub highest_min: Option<DayValue>,
    pub lowest_max: Option<DayValue>,
    pub hot_days: i64,
    pub warm_nights: i64,
}

#[derive(serde::Serialize, Debug, Default)]
pub struct SynRain {
    pub total_in: Option<f64>,
    pub wettest: Option<DayValue>,
    /// in/hr. Stitched from `rainratein` (to 2026-07) and `hourlyrainin`.
    pub max_rate: Extreme,
    pub rain_days: i64,
    pub dry_days: i64,
}

#[derive(serde::Serialize, Debug, Default)]
pub struct SynPressure {
    pub highest: Extreme,
    pub lowest: Extreme,
}

#[derive(serde::Serialize, Debug, Default)]
pub struct SynWind {
    pub highest_gust: Extreme,
    /// Time-weighted mean speed (mph): integrated run / hours covered.
    pub mean_mph: Option<f64>,
    /// Integrated wind run (statute miles).
    pub run_mi: Option<f64>,
    pub gale_days: i64,
}

#[derive(serde::Serialize, Debug, Default)]
pub struct SynHumidity {
    pub mean_rh: Option<f64>,
    pub mean_dewpoint: Option<f64>,
    pub highest_dewpoint: Extreme,
    pub lowest_rh: Extreme,
}

#[derive(serde::Serialize, Debug, Default)]
pub struct SynSolar {
    pub peak: Extreme,
    pub max_uv: Extreme,
    /// Mean over days with own-station solar data (kWh/m²).
    pub mean_daily_kwh: Option<f64>,
    pub energy_days: i64,
}

/// How many canonical temperature readings in the period came from each source.
#[derive(serde::Serialize, Debug)]
pub struct SourceShare {
    pub kind: String,
    pub readings: i64,
    pub proxy: bool,
}

#[derive(serde::Serialize, Debug)]
pub struct Synopsis {
    pub start: String,
    /// Exclusive, after clamping to tomorrow.
    pub end: String,
    pub days_in_period: i64,
    pub days_with_data: i64,
    pub includes_today: bool,
    pub temp: SynTemp,
    pub rain: SynRain,
    pub pressure: SynPressure,
    pub wind: SynWind,
    pub humidity: SynHumidity,
    pub solar: SynSolar,
    pub sources: Vec<SourceShare>,
}

#[derive(Clone, Copy)]
enum Pick {
    Lowest,
    Highest,
}

impl Pick {
    fn order(self) -> &'static str {
        match self {
            Pick::Lowest => "ASC",
            Pick::Highest => "DESC",
        }
    }
}

#[derive(Clone, Copy)]
enum Col {
    Min,
    Max,
}

impl Col {
    fn value(self) -> &'static str {
        match self {
            Col::Min => "r.min_value",
            Col::Max => "r.max_value",
        }
    }
    fn ts(self) -> &'static str {
        match self {
            Col::Min => "r.ts_min",
            Col::Max => "r.ts_max",
        }
    }
}

/// Day-range filter shared by every rollup query below: ?1 metric, ?2..?3 days.
const ROLLUP_RANGE: &str = "FROM daily_rollups r JOIN metrics m ON m.id = r.metric_id
     WHERE m.name = ?1 AND r.day_local >= ?2 AND r.day_local < ?3";

struct DayAgg {
    days: i64,
    mean: Option<f64>,
    mean_min: Option<f64>,
    mean_max: Option<f64>,
    mean_mid: Option<f64>,
}

fn day_agg(conn: &Connection, metric: &str, a: &str, b: &str) -> rusqlite::Result<DayAgg> {
    let sql = format!(
        "SELECT COUNT(*), SUM(r.avg_value * r.n_samples) / SUM(r.n_samples),
                AVG(r.min_value), AVG(r.max_value), AVG((r.min_value + r.max_value) / 2.0)
         {ROLLUP_RANGE}"
    );
    conn.query_row(&sql, rusqlite::params![metric, a, b], |r| {
        Ok(DayAgg {
            days: r.get(0)?,
            mean: r.get(1)?,
            mean_min: r.get(2)?,
            mean_max: r.get(3)?,
            mean_mid: r.get(4)?,
        })
    })
}

/// The period's lowest minimum or highest maximum, with the instant it
/// happened. Ties go to the earliest, matching build_rollups.py.
fn instant_extreme(conn: &Connection, metric: &str, a: &str, b: &str, pick: Pick) -> rusqlite::Result<Extreme> {
    use rusqlite::OptionalExtension;
    let col = match pick {
        Pick::Lowest => Col::Min,
        Pick::Highest => Col::Max,
    };
    let sql = format!(
        "SELECT {v}, {t} {ROLLUP_RANGE} AND {v} IS NOT NULL ORDER BY {v} {o}, {t} LIMIT 1",
        v = col.value(),
        t = col.ts(),
        o = pick.order()
    );
    let row = conn
        .query_row(&sql, rusqlite::params![metric, a, b], |r| {
            Ok((r.get::<_, f64>(0)?, r.get::<_, Option<i64>>(1)?))
        })
        .optional()?;
    Ok(match row {
        Some((value, ts)) => Extreme { value: Some(value), ts },
        None => Extreme::default(),
    })
}

/// A day-level extreme, such as the highest daily minimum.
fn day_extreme(conn: &Connection, metric: &str, a: &str, b: &str, col: Col, pick: Pick) -> rusqlite::Result<Option<DayValue>> {
    use rusqlite::OptionalExtension;
    let sql = format!(
        "SELECT {v}, r.day_local {ROLLUP_RANGE} AND {v} IS NOT NULL ORDER BY {v} {o}, r.day_local LIMIT 1",
        v = col.value(),
        o = pick.order()
    );
    conn.query_row(&sql, rusqlite::params![metric, a, b], |r| {
        Ok(DayValue { value: r.get(0)?, day: r.get(1)? })
    })
    .optional()
}

/// Days whose `col` value is at least `threshold`.
fn days_at_least(conn: &Connection, metric: &str, a: &str, b: &str, col: Col, threshold: f64) -> rusqlite::Result<i64> {
    let sql = format!("SELECT COUNT(*) {ROLLUP_RANGE} AND {v} >= ?4", v = col.value());
    conn.query_row(&sql, rusqlite::params![metric, a, b, threshold], |r| r.get(0))
}

/// Solar and UV rollups from the Zephyr years hold phantom zeros (that
/// station had no photocell). A whole period peaking at zero is absence,
/// not darkness.
fn zero_is_absent(e: Extreme) -> Extreme {
    if e.value == Some(0.0) {
        Extreme::default()
    } else {
        e
    }
}

fn local_midnight(d: chrono::NaiveDate) -> Result<i64, String> {
    d.and_hms_opt(0, 0, 0)
        .and_then(|t| t.and_local_timezone(chrono::Local).earliest())
        .map(|t| t.timestamp())
        .ok_or_else(|| format!("no local midnight on {d}"))
}

/// One metric's canonical readings over [a_ts, b_ts), with each reading's
/// source kind, in time order.
///
/// Resolves source priority itself rather than reading
/// `canonical_observations`, which took 20 s for October 2025. Two traps,
/// both needed for the same rows in ~20 ms:
/// - the view hands SQLite `p.period_start` as an index bound, and the
///   current open-ended period makes a recent month scan a year of data.
///   Collapsing the bounds with `max()`/`min()`, as `refresh_dirty_rollups`
///   does, fixes that;
/// - bounds that live only in the join can't reach the primary key, so the
///   plain `o.ts_utc` range in WHERE is what lets SQLite seek on
///   `(metric_id, ts_utc)` instead of reading the metric's whole history.
fn canonical_series(conn: &Connection, metric: &str, a_ts: i64, b_ts: i64) -> rusqlite::Result<Vec<(i64, f64, String)>> {
    let mut stmt = conn.prepare(
        "WITH canon AS (
             SELECT o.ts_utc, o.value, s.kind,
                    ROW_NUMBER() OVER (PARTITION BY o.ts_utc ORDER BY p.rank) rn
             FROM observations o
             JOIN sources s ON s.id = o.source_id
             JOIN source_priority p ON p.source_kind = s.kind
                  AND o.ts_utc >= max(p.period_start, ?2)
                  AND o.ts_utc <  min(coalesce(p.period_end, ?3), ?3)
             WHERE o.metric_id = (SELECT id FROM metrics WHERE name = ?1)
               AND o.ts_utc >= ?2 AND o.ts_utc < ?3
         )
         SELECT ts_utc, value, kind FROM canon WHERE rn = 1 ORDER BY ts_utc",
    )?;
    let rows = stmt
        .query_map(rusqlite::params![metric, a_ts, b_ts], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))?
        .collect::<rusqlite::Result<Vec<_>>>()?;
    Ok(rows)
}

/// Trapezoidal wind run over the canonical record: (statute miles, hours covered).
fn wind_run(conn: &Connection, a_ts: i64, b_ts: i64) -> rusqlite::Result<Option<(f64, f64)>> {
    let rows = canonical_series(conn, "windspeedmph", a_ts, b_ts)?;
    let mut miles = 0.0;
    let mut secs: i64 = 0;
    for w in rows.windows(2) {
        let dt = w[1].0 - w[0].0;
        if dt > 0 && dt <= WIND_GAP_MAX_SECS {
            miles += (w[0].1 + w[1].1) / 2.0 * dt as f64 / 3600.0;
            secs += dt;
        }
    }
    Ok((secs > 0).then(|| (miles, secs as f64 / 3600.0)))
}

/// Mean daily solar energy (kWh/m²) over the days that have own-station
/// solar data, integrated per civil-local day in one pass. `midnights` holds
/// each day's start, then the period's end.
fn mean_daily_solar(conn: &Connection, midnights: &[i64]) -> rusqlite::Result<(Option<f64>, i64)> {
    let (Some(&a_ts), Some(&b_ts)) = (midnights.first(), midnights.last()) else {
        return Ok((None, 0));
    };
    let mut stmt = conn.prepare(
        "SELECT ts_utc, value FROM observations
         WHERE metric_id = (SELECT id FROM metrics WHERE name = 'solarradiation')
           AND source_id IN (2, 3, 4)
           AND ts_utc >= ?1 AND ts_utc < ?2
         ORDER BY ts_utc",
    )?;
    let rows: Vec<(i64, f64)> = stmt
        .query_map(rusqlite::params![a_ts, b_ts], |r| Ok((r.get(0)?, r.get(1)?)))?
        .collect::<rusqlite::Result<_>>()?;
    let mut joules = vec![0.0_f64; midnights.len().saturating_sub(1)];
    let mut day = 0;
    for w in rows.windows(2) {
        while day + 1 < joules.len() && w[0].0 >= midnights[day + 1] {
            day += 1;
        }
        let dt = w[1].0 - w[0].0;
        if dt > 0 && dt <= SOLAR_GAP_MAX_SECS {
            joules[day] += (w[0].1 + w[1].1) / 2.0 * dt as f64;
        }
    }
    let lit: Vec<f64> = joules.into_iter().filter(|&j| j > 0.0).map(|j| j / 3.6e6).collect();
    let n = i64::try_from(lit.len()).unwrap_or(i64::MAX);
    let mean = (!lit.is_empty()).then(|| lit.iter().sum::<f64>() / lit.len() as f64);
    Ok((mean, n))
}

/// Builds the report card for civil-local days `start` (inclusive) to `end`
/// (exclusive), both "YYYY-MM-DD". An end past today is clamped to tomorrow,
/// so a running month includes today so far.
///
/// # Errors
/// Returns an error for unparseable dates, an empty or wholly future period,
/// or any database failure.
pub fn synopsis(start: &str, end: &str) -> Result<Synopsis, String> {
    use chrono::NaiveDate;
    let parse = |s: &str| NaiveDate::parse_from_str(s, "%Y-%m-%d").map_err(|e| format!("bad date {s:?}: {e}"));
    let s = parse(start)?;
    let today = chrono::Local::now().date_naive();
    let tomorrow = today.succ_opt().ok_or("date overflow")?;
    let e = parse(end)?.min(tomorrow);
    if e <= s {
        return Err(format!("no days to report between {start} and {end}"));
    }
    let a = s.format("%Y-%m-%d").to_string();
    let b = e.format("%Y-%m-%d").to_string();
    let days: Vec<NaiveDate> = s.iter_days().take_while(|d| *d < e).collect();
    let mut midnights = days.iter().map(|d| local_midnight(*d)).collect::<Result<Vec<_>, _>>()?;
    midnights.push(local_midnight(e)?);
    let (a_ts, b_ts) = (midnights[0], midnights[midnights.len() - 1]);

    let conn = Connection::open(db_path()).map_err(|e| e.to_string())?;
    let db = |e: rusqlite::Error| e.to_string();

    let t = day_agg(&conn, "tempf", &a, &b).map_err(db)?;
    let temp = SynTemp {
        mean_all: t.mean,
        mean_minmax: t.mean_mid,
        mean_min: t.mean_min,
        mean_max: t.mean_max,
        min: instant_extreme(&conn, "tempf", &a, &b, Pick::Lowest).map_err(db)?,
        max: instant_extreme(&conn, "tempf", &a, &b, Pick::Highest).map_err(db)?,
        highest_min: day_extreme(&conn, "tempf", &a, &b, Col::Min, Pick::Highest).map_err(db)?,
        lowest_max: day_extreme(&conn, "tempf", &a, &b, Col::Max, Pick::Lowest).map_err(db)?,
        hot_days: days_at_least(&conn, "tempf", &a, &b, Col::Max, HOT_DAY_F).map_err(db)?,
        warm_nights: days_at_least(&conn, "tempf", &a, &b, Col::Min, WARM_NIGHT_F).map_err(db)?,
    };

    // Daily rain: each day's max of the midnight-resetting counter is its total.
    let rain_sql = format!(
        "SELECT COUNT(*), SUM(r.max_value), COUNT(CASE WHEN r.max_value >= ?4 THEN 1 END) {ROLLUP_RANGE}"
    );
    let (rain_measured, total_in, rain_days): (i64, Option<f64>, i64) = conn
        .query_row(&rain_sql, rusqlite::params!["dailyrainin", a, b, RAIN_DAY_IN], |r| {
            Ok((r.get(0)?, r.get(1)?, r.get(2)?))
        })
        .map_err(db)?;
    let rate_old = instant_extreme(&conn, "rainratein", &a, &b, Pick::Highest).map_err(db)?;
    let rate_new = instant_extreme(&conn, "hourlyrainin", &a, &b, Pick::Highest).map_err(db)?;
    let max_rate = if rate_new.value.unwrap_or(f64::MIN) > rate_old.value.unwrap_or(f64::MIN) {
        rate_new
    } else {
        rate_old
    };
    let rain = SynRain {
        total_in,
        wettest: day_extreme(&conn, "dailyrainin", &a, &b, Col::Max, Pick::Highest).map_err(db)?,
        max_rate,
        rain_days,
        dry_days: rain_measured - rain_days,
    };

    let pressure = SynPressure {
        highest: instant_extreme(&conn, "baromrelin", &a, &b, Pick::Highest).map_err(db)?,
        lowest: instant_extreme(&conn, "baromrelin", &a, &b, Pick::Lowest).map_err(db)?,
    };

    let run = wind_run(&conn, a_ts, b_ts).map_err(db)?;
    let wind = SynWind {
        highest_gust: instant_extreme(&conn, "windgustmph", &a, &b, Pick::Highest).map_err(db)?,
        mean_mph: run.map(|(mi, h)| mi / h),
        run_mi: run.map(|(mi, _)| mi),
        gale_days: days_at_least(&conn, "windspeedmph", &a, &b, Col::Max, GALE_MPH).map_err(db)?,
    };

    let rh = day_agg(&conn, "humidity", &a, &b).map_err(db)?;
    let dp = day_agg(&conn, "dewpointf", &a, &b).map_err(db)?;
    let humidity = SynHumidity {
        mean_rh: rh.mean,
        mean_dewpoint: dp.mean,
        highest_dewpoint: instant_extreme(&conn, "dewpointf", &a, &b, Pick::Highest).map_err(db)?,
        lowest_rh: instant_extreme(&conn, "humidity", &a, &b, Pick::Lowest).map_err(db)?,
    };

    let (mean_daily_kwh, energy_days) = mean_daily_solar(&conn, &midnights).map_err(db)?;
    let solar = SynSolar {
        peak: zero_is_absent(instant_extreme(&conn, "solarradiation", &a, &b, Pick::Highest).map_err(db)?),
        max_uv: zero_is_absent(instant_extreme(&conn, "uv", &a, &b, Pick::Highest).map_err(db)?),
        mean_daily_kwh,
        energy_days,
    };

    let mut counts: Vec<(String, i64)> = Vec::new();
    for (_, _, kind) in canonical_series(&conn, "tempf", a_ts, b_ts).map_err(db)? {
        match counts.iter_mut().find(|(k, _)| *k == kind) {
            Some((_, n)) => *n += 1,
            None => counts.push((kind, 1)),
        }
    }
    counts.sort_by(|x, y| y.1.cmp(&x.1).then_with(|| x.0.cmp(&y.0)));
    let sources = counts
        .into_iter()
        .map(|(kind, readings)| {
            let proxy = PROXY_KINDS.contains(&kind.as_str());
            SourceShare { kind, readings, proxy }
        })
        .collect();

    Ok(Synopsis {
        start: a,
        end: b,
        days_in_period: i64::try_from(days.len()).unwrap_or(i64::MAX),
        days_with_data: t.days,
        includes_today: s <= today && today < e,
        temp,
        rain,
        pressure,
        wind,
        humidity,
        solar,
        sources,
    })
}

#[cfg(test)]
mod synopsis_tests {
    use super::*;

    /// Cumulus's own "Averages and Extremes for July 2010" screen
    /// (Dashboard/Cumulus UI Examples/2026-07-06 10_49_53-Cumulus.png),
    /// computed independently from the same station. Needs the Archive, so
    /// run with `cargo test -- --ignored --nocapture`.
    #[test]
    #[ignore = "reads the live Archive"]
    fn july_2010_matches_cumulus() {
        let s = synopsis("2010-07-01", "2010-08-01").expect("synopsis for July 2010");
        let near = |got: Option<f64>, want: f64, tol: f64, what: &str| {
            let g = got.unwrap_or_else(|| panic!("{what}: no value, want {want}"));
            assert!((g - want).abs() <= tol, "{what}: got {g}, Cumulus says {want}");
        };
        let kt = |mph: Option<f64>| mph.map(|v| v * 0.868_976_241_900_647_9);
        let t = &s.temp;
        near(t.mean_all, 64.8, 0.05, "mean (1 minute)");
        near(t.mean_minmax, 66.8, 0.05, "mean (min+max)");
        near(t.mean_min, 60.4, 0.05, "mean minimum");
        near(t.mean_max, 73.1, 0.05, "mean maximum");
        near(t.min.value, 57.9, 0.001, "minimum");
        near(t.max.value, 99.1, 0.001, "maximum");
        assert_eq!(t.highest_min, Some(DayValue { value: 66.7, day: "2010-07-16".into() }));
        assert_eq!(t.lowest_max, Some(DayValue { value: 64.0, day: "2010-07-08".into() }));
        near(s.rain.total_in, 0.03, 0.001, "rain total");
        assert_eq!(s.rain.wettest, Some(DayValue { value: 0.02, day: "2010-07-22".into() }));
        near(s.rain.max_rate.value, 0.04, 0.001, "high rain rate");
        assert_eq!((s.rain.rain_days, s.rain.dry_days), (2, 29), "rain days / dry days");
        near(s.pressure.highest.value, 30.10, 0.001, "highest pressure");
        // Cumulus reports 29.55 on the 16th: a one-reading spike in its
        // high-rate internal sampling (its own 03:10 log line says 29.92).
        // The logged record never dipped below 29.81, so that is what we report.
        near(s.pressure.lowest.value, 29.81, 0.001, "lowest pressure (logged)");
        near(kt(s.wind.highest_gust.value), 13.2, 0.05, "highest gust (kt)");
        near(kt(s.wind.mean_mph), 1.2, 0.05, "average speed (kt)");
        near(kt(s.wind.run_mi), 911.2, 1.0, "wind run (nm)");
        assert_eq!(s.wind.gale_days, 0, "gale days");
    }
}
