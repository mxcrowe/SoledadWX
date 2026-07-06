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
";

pub fn db_path() -> PathBuf {
    if let Ok(p) = std::env::var("SOLEDADWX_DB") {
        return PathBuf::from(p);
    }
    // Dev fallback: CWD is src-tauri during `npm run tauri dev`.
    PathBuf::from("../../data/soledadwx.db")
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
        let values: [(&str, Option<f64>); 21] = [
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
        ];
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

    Ok(DbStatus {
        total_observations: total,
        live_rows_today: live_today,
        last_write_utc: last_write,
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
            "SELECT strftime('%s', r.day_utc), r.avg_value, r.min_value, r.max_value, r.n_samples
             FROM daily_rollups r
             JOIN metrics m ON m.id = r.metric_id
             WHERE m.name = ?1
               AND strftime('%s', r.day_utc) + 0 >= ?2
               AND strftime('%s', r.day_utc) + 0 < ?3
             ORDER BY r.day_utc",
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
               AND strftime('%s', r.day_utc) + 0 >= ?2
               AND strftime('%s', r.day_utc) + 0 < ?3",
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
                 WHERE m.name=?1 AND strftime('%s',r.day_utc)+0 >= ?2
                   AND strftime('%s',r.day_utc)+0 < ?3 AND {vcol} = ?4
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
