import { useEffect, useState } from "react";
import { listen } from "@tauri-apps/api/event";
import { invoke } from "@tauri-apps/api/core";
import Console from "./Console";
import "./App.css";

export interface WeatherReading {
  dateutc: number;
  date?: string;
  tempf?: number;
  humidity?: number;
  windspeedmph?: number;
  windgustmph?: number;
  maxdailygust?: number;
  winddir?: number;
  baromrelin?: number;
  baromabsin?: number;
  hourlyrainin?: number;
  dailyrainin?: number;
  weeklyrainin?: number;
  monthlyrainin?: number;
  yearlyrainin?: number;
  solarradiation?: number;
  uv?: number;
  tempinf?: number;
  humidityin?: number;
  feelsLike?: number;
  dewPoint?: number;
  feelsLikein?: number;
  dewPointin?: number;
  lastRain?: string;
}

interface DbStatus {
  total_observations: number;
  live_rows_today: number;
  last_write_utc: number | null;
  today_high_f: number | null;
  today_low_f: number | null;
  today_max_gust_mph: number | null;
  today_rain_in: number | null;
}

interface SeriesPoint { t: number; avg: number; min: number; max: number; n: number }
interface RangeStats {
  metric: string;
  min_value: number; min_ts: number;
  max_value: number; max_ts: number;
  avg_value: number; n_samples: number; days_covered: number;
  wind_run_mi: number | null;
}

const METRICS: [string, string, string][] = [
  ["tempf", "Outdoor temperature", "°F"],
  ["humidity", "Outdoor humidity", "%"],
  ["dewpointf", "Dew point", "°F"],
  ["windspeedmph", "Wind speed", "mph"],
  ["windgustmph", "Wind gust", "mph"],
  ["winddir", "Wind direction", "°"],
  ["baromrelin", "Pressure (rel)", "inHg"],
  ["dailyrainin", "Daily rain", "in"],
  ["solarradiation", "Solar radiation", "W/m²"],
  ["uv", "UV index", ""],
  ["tempinf", "Indoor temperature", "°F"],
];

const fmtTs = (ts: number) =>
  ts ? new Date(ts * 1000).toLocaleString(undefined, {
    year: "numeric", month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  }) : "—";

function Chart({ series, unit }: { series: SeriesPoint[]; unit: string }) {
  if (series.length === 0) return <div className="chart-empty">No data in range.</div>;
  const W = 900, H = 320, PL = 56, PR = 12, PT = 12, PB = 28;
  const t0 = series[0].t, t1 = series[series.length - 1].t || t0 + 1;
  const lo = Math.min(...series.map(p => p.min));
  const hi = Math.max(...series.map(p => p.max));
  const span = hi - lo || 1;
  const x = (t: number) => PL + ((t - t0) / (t1 - t0 || 1)) * (W - PL - PR);
  const y = (v: number) => PT + (1 - (v - lo) / span) * (H - PT - PB);
  const band =
    series.map(p => `${x(p.t).toFixed(1)},${y(p.max).toFixed(1)}`).join(" ") + " " +
    [...series].reverse().map(p => `${x(p.t).toFixed(1)},${y(p.min).toFixed(1)}`).join(" ");
  const line = series.map(p => `${x(p.t).toFixed(1)},${y(p.avg).toFixed(1)}`).join(" ");
  const yticks = [0, 0.25, 0.5, 0.75, 1].map(f => lo + f * span);
  const nx = Math.min(6, series.length);
  const xticks = Array.from({ length: nx }, (_, i) => t0 + ((t1 - t0) * i) / (nx - 1 || 1));
  const spanDays = (t1 - t0) / 86400;
  const fmtX = (t: number) => {
    const d = new Date(t * 1000);
    return spanDays > 700
      ? String(d.getUTCFullYear())
      : d.toLocaleDateString(undefined, { month: "short", year: "2-digit" });
  };
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="chart">
      {yticks.map((v, i) => (
        <g key={i}>
          <line x1={PL} x2={W - PR} y1={y(v)} y2={y(v)} className="gridline" />
          <text x={PL - 6} y={y(v) + 4} className="tick" textAnchor="end">
            {v.toFixed(span < 5 ? 2 : 1)}
          </text>
        </g>
      ))}
      {xticks.map((t, i) => (
        <text key={i} x={x(t)} y={H - 8} className="tick" textAnchor="middle">{fmtX(t)}</text>
      ))}
      <polygon points={band} className="band" />
      <polyline points={line} className="avgline" fill="none" />
      <text x={PL} y={PT + 2} className="tick">{unit}</text>
    </svg>
  );
}

function Analyst() {
  const today = new Date().toISOString().slice(0, 10);
  const [metric, setMetric] = useState("tempf");
  const [start, setStart] = useState("2009-09-06");
  const [end, setEnd] = useState(today);
  const [series, setSeries] = useState<SeriesPoint[] | null>(null);
  const [stats, setStats] = useState<RangeStats | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const unit = METRICS.find(m => m[0] === metric)?.[2] ?? "";

  const run = () => {
    setBusy(true); setErr(null);
    Promise.all([
      invoke<SeriesPoint[]>("query_series", { metric, start, end }),
      invoke<RangeStats>("range_stats", { metric, start, end }),
    ])
      .then(([s, st]) => { setSeries(s); setStats(st); })
      .catch(e => { setErr(String(e)); setSeries(null); setStats(null); })
      .finally(() => setBusy(false));
  };

  return (
    <div className="analyst">
      <div className="controls">
        <select value={metric} onChange={e => setMetric(e.target.value)}>
          {METRICS.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
        </select>
        <input type="date" value={start} min="2009-09-06" max={today}
               onChange={e => setStart(e.target.value)} />
        <span>→</span>
        <input type="date" value={end} min="2009-09-06" max={today}
               onChange={e => setEnd(e.target.value)} />
        <button onClick={run} disabled={busy}>{busy ? "Crunching…" : "Analyze"}</button>
      </div>
      {err && <div className="error">{err}</div>}
      {stats && (
        <div className="stats-row">
          <div className="stat"><span className="label">Min</span>
            <span className="val">{stats.min_value.toFixed(2)} {unit}</span>
            <span className="when">{fmtTs(stats.min_ts)}</span></div>
          <div className="stat"><span className="label">Max</span>
            <span className="val">{stats.max_value.toFixed(2)} {unit}</span>
            <span className="when">{fmtTs(stats.max_ts)}</span></div>
          <div className="stat"><span className="label">Average</span>
            <span className="val">{stats.avg_value.toFixed(2)} {unit}</span>
            <span className="when">{stats.n_samples.toLocaleString()} samples / {stats.days_covered.toLocaleString()} days</span></div>
          {stats.wind_run_mi != null && (
            <div className="stat"><span className="label">Wind run</span>
              <span className="val">{Math.round(stats.wind_run_mi).toLocaleString()} mi</span>
              <span className="when">Σ daily avg × 24 h</span></div>
          )}
        </div>
      )}
      {series && <Chart series={series} unit={unit} />}
      {series && series.length > 0 && (
        <p className="chart-note">
          Band = daily min→max · line = daily average · {series.length.toLocaleString()} days shown
        </p>
      )}
    </div>
  );
}

type View =
  | "console" | "live" | "today" | "microforecast" | "charts"
  | "records" | "synopsis" | "analyst" | "gauges" | "barograph" | "extremes";

const NAV: [View, string, string][] = [
  ["console", "Console", "▦"],
  ["live", "Live", "◉"],
  ["today", "Today/Yesterday", "⇄"],
  ["microforecast", "Micro-forecast", "☁"],
  ["charts", "Charts", "∿"],
  ["records", "Min/Max Records", "★"],
  ["synopsis", "Synopsis by Period", "▤"],
  ["analyst", "Analyze & Compare", "⌕"],
  ["gauges", "Gauges", "◎"],
  ["barograph", "Barograph", "◠"],
  ["extremes", "Soledad Extremes", "⇅"],
];

const BUILT: View[] = ["console", "live", "analyst"];

function Placeholder({ label }: { label: string }) {
  return (
    <div className="placeholder">
      <div className="placeholder-glyph">◱</div>
      <h2>{label}</h2>
      <p>Coming soon</p>
    </div>
  );
}

function App() {
  const [reading, setReading] = useState<WeatherReading | null>(null);
  const [status, setStatus] = useState<DbStatus | null>(null);
  const [view, setView] = useState<View>("console");

  useEffect(() => {
    const unlisten = listen<WeatherReading>("weather-reading", (event) => {
      setReading(event.payload);
    });
    return () => {
      unlisten.then((f) => f());
    };
  }, []);

  useEffect(() => {
    const poll = () => invoke<DbStatus>("db_status").then(setStatus).catch(() => {});
    poll();
    const id = setInterval(poll, 30_000);
    return () => clearInterval(id);
  }, []);

  const lastWriteAge =
    status?.last_write_utc != null
      ? Math.round(Date.now() / 1000 - status.last_write_utc)
      : null;
  const recording = lastWriteAge != null && lastWriteAge < 120;

  return (
    <div className="app-shell">
      <nav className="sidebar">
        <div className="brand">SoledadWX</div>
        <ul className="nav">
          {NAV.map(([v, label, glyph]) => (
            <li key={v}
                className={view === v ? "nav-item active" : "nav-item"}
                onClick={() => setView(v)}>
              <span className="nav-glyph">{glyph}</span>{label}
            </li>
          ))}
        </ul>
        <div className="nav-foot">
          <span>
            <span className={recording ? "rec-dot rec-on" : "rec-dot rec-off"}>●</span>{" "}
            {recording ? "Recording" : "Offline"}
          </span>
          {status && <span className="nav-foot-obs">{status.total_observations.toLocaleString()} obs</span>}
        </div>
      </nav>

      <main className="content">
      {view === "console" && <Console reading={reading} />}
      {view === "analyst" && <Analyst />}
      {!BUILT.includes(view) && <Placeholder label={NAV.find((n) => n[0] === view)![1]} />}

      {view === "live" && (reading ? (
        <div className="telemetry-grid">
          {/* Group 1: Outdoor Conditions */}
          <div className="data-box"><span className="label">Temp (Out)</span><span className="val">{reading.tempf}°F</span></div>
          <div className="data-box"><span className="label">Humidity (Out)</span><span className="val">{reading.humidity}%</span></div>
          <div className="data-box"><span className="label">Feels Like</span><span className="val">{reading.feelsLike}°F</span></div>
          <div className="data-box"><span className="label">Dew Point</span><span className="val">{reading.dewPoint}°F</span></div>

          {/* Group 2: Indoor Conditions */}
          <div className="data-box"><span className="label">Temp (In)</span><span className="val">{reading.tempinf}°F</span></div>
          <div className="data-box"><span className="label">Humidity (In)</span><span className="val">{reading.humidityin}%</span></div>
          <div className="data-box"><span className="label">Feels Like (In)</span><span className="val">{reading.feelsLikein}°F</span></div>
          <div className="data-box"><span className="label">Dew Point (In)</span><span className="val">{reading.dewPointin}°F</span></div>

          {/* Group 3: Wind */}
          <div className="data-box"><span className="label">Wind Speed</span><span className="val">{reading.windspeedmph ? (reading.windspeedmph * 0.868976).toFixed(1) : "--"} kts</span></div>
          <div className="data-box"><span className="label">Wind Gust</span><span className="val">{reading.windgustmph ? (reading.windgustmph * 0.868976).toFixed(1) : "--"} kts</span></div>
          <div className="data-box"><span className="label">Max Daily Gust</span><span className="val">{reading.maxdailygust ? (reading.maxdailygust * 0.868976).toFixed(1) : "--"} kts</span></div>
          <div className="data-box"><span className="label">Wind Dir</span><span className="val">{reading.winddir}°</span></div>

          {/* Group 4: Pressure & Sun */}
          <div className="data-box"><span className="label">Pressure (Rel)</span><span className="val">{reading.baromrelin} inHg</span></div>
          <div className="data-box"><span className="label">Pressure (Abs)</span><span className="val">{reading.baromabsin} inHg</span></div>
          <div className="data-box"><span className="label">Solar Rad</span><span className="val">{reading.solarradiation} W/m²</span></div>
          <div className="data-box"><span className="label">UV Index</span><span className="val">{reading.uv}</span></div>

          {/* Group 5: Rain */}
          <div className="data-box"><span className="label">Rain (Hourly)</span><span className="val">{reading.hourlyrainin} in</span></div>
          <div className="data-box"><span className="label">Rain (Daily)</span><span className="val">{reading.dailyrainin} in</span></div>
          <div className="data-box"><span className="label">Rain (Weekly)</span><span className="val">{reading.weeklyrainin} in</span></div>
          <div className="data-box"><span className="label">Rain (Yearly)</span><span className="val">{reading.yearlyrainin} in</span></div>
          
          <div className="data-box span-full"><span className="label">Last Rain:</span><span className="val">{reading.lastRain}</span></div>
          <div className="data-box span-full"><span className="label">Timestamp:</span><span className="val">{reading.date}</span></div>
        </div>
      ) : (
        <div className="loading">Waiting for data from weather station...</div>
      ))}
      </main>
    </div>
  );
}

export default App;


