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

// ---------- Console page queries ----------

#[derive(serde::Serialize, Default)]
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
    pub avg_temp_today: Option<f64>,
    pub wind_run_today_mi: Option<f64>,
    pub rain_yesterday_in: Option<f64>,
    pub rain_month_in: Option<f64>,
    pub rain_year_in: Option<f64>,
    pub today: DayExtremes,
    pub yesterday: DayExtremes,
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
        avg_temp_today,
        wind_run_today_mi,
        rain_yesterday_in,
        rain_month_in: latest("monthlyrainin"),
        rain_year_in: latest("yearlyrainin"),
        today: day_extremes(&conn, mid0, now),
        yesterday: day_extremes(&conn, mid1, mid0),
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
    for row in rows {
        let (dir, speed) = row?;
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
            "SELECT {expr} AS v, r.day_utc FROM daily_rollups r
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
