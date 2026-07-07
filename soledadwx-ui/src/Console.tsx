// Console v2 — MXUI-inspired dashboard (see Dashboard/UI Example/Dashboard.png):
// centered station header, astro strip, hero-value metric cards with trend
// arrows and red/blue today-yesterday hi-lo columns, 24 h sparkline
// thumbnails, SteelSeries gauges, wind rose.

import { useEffect, useMemo, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { astro, cardinal, cloudBaseFt, fmtDur, fmtHM } from "./astro";
import { SteelRadial, SteelWindDir } from "./SteelGauge";
import type { WeatherReading } from "./App";

interface Extreme { value: number | null; ts: number | null }
interface DayExtremes {
  high_wind: Extreme; high_gust: Extreme;
  min_temp: Extreme; max_temp: Extreme;
  min_press: Extreme; max_press: Extreme;
  max_rain_rate: Extreme;
}
interface ConsoleStats {
  temp_trend_f_hr: number | null;
  press_trend_in_hr: number | null;
  avg_temp_today: number | null;
  wind_run_today_mi: number | null;
  rain_yesterday_in: number | null;
  rain_month_in: number | null;
  rain_year_in: number | null;
  today: DayExtremes;
  yesterday: DayExtremes;
}
interface WindRoseData { counts: number[][]; total: number; calm: number; hours: number }
interface SeriesPoint { t: number; avg: number; min: number; max: number; n: number }

const fmt = (v: number | null | undefined, dp = 1) => (v == null ? "--" : v.toFixed(dp));
const fmtT = (ts: number | null) =>
  ts ? new Date(ts * 1000).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }) : "--:--";

// ---------- shared bits ----------

function Trend({ value, dp = 2, unit }: { value: number | null; dp?: number; unit: string }) {
  if (value == null) return <span className="trend">—</span>;
  const cls = value > 0.005 ? "trend up" : value < -0.005 ? "trend down" : "trend";
  const arrow = value > 0.005 ? "▲" : value < -0.005 ? "▼" : "◆";
  return (
    <span className={cls}>
      {arrow} {value > 0 ? "+" : ""}{value.toFixed(dp)} {unit}
    </span>
  );
}

function HiLo({ today, yesterday, dp = 1, unit }: {
  today: { hi: Extreme; lo: Extreme };
  yesterday: { hi: Extreme; lo: Extreme };
  dp?: number;
  unit: string;
}) {
  const cell = (e: Extreme, cls: string) => (
    <>
      <span className={cls}>{fmt(e.value, dp)}</span> <span className="hl-unit">{unit}</span>
      <div className="hl-at">@ {fmtT(e.ts)}</div>
    </>
  );
  return (
    <div className="hilo">
      <div>
        <div className="hl-head">Today</div>
        <div className="hl-row">High {cell(today.hi, "hi")}</div>
        <div className="hl-row">Low {cell(today.lo, "lo")}</div>
      </div>
      <div>
        <div className="hl-head">Yesterday</div>
        <div className="hl-row">High {cell(yesterday.hi, "hi")}</div>
        <div className="hl-row">Low {cell(yesterday.lo, "lo")}</div>
      </div>
    </div>
  );
}

function Card({ title, children, className = "" }: {
  title: string; children: React.ReactNode; className?: string;
}) {
  return (
    <section className={`mx-card ${className}`}>
      <header>{title}</header>
      <div className="mx-body">{children}</div>
    </section>
  );
}

function Spark({ series, color = "#7fc4ff", label }: {
  series: SeriesPoint[]; color?: string; label: string;
}) {
  const W = 150, H = 64;
  if (series.length < 2) return <div className="spark-empty">{label}</div>;
  const lo = Math.min(...series.map(p => p.min));
  const hi = Math.max(...series.map(p => p.max));
  const span = hi - lo || 1;
  const t0 = series[0].t, t1 = series[series.length - 1].t;
  const pts = series
    .map(p => `${(((p.t - t0) / (t1 - t0)) * W).toFixed(1)},${(H - 10 - ((p.avg - lo) / span) * (H - 16)).toFixed(1)}`)
    .join(" ");
  return (
    <div className="spark">
      <svg viewBox={`0 0 ${W} ${H}`}>
        <polyline points={pts} fill="none" stroke={color} strokeWidth="1.5" />
      </svg>
      <span>{label}</span>
    </div>
  );
}

function rad(d: number) { return (d * Math.PI) / 180; }

// ---------- wind rose (unchanged visual, MXUI card shell) ----------

const BIN_COLORS = ["#3548c9", "#3f8de0", "#39cfc3", "#4ed44e", "#b6e34a", "#f5e042"];
const BIN_LABELS = ["0–2", "2–5", "5–10", "10–15", "15–20", "20+"];

function WindRose({ data }: { data: WindRoseData | null }) {
  if (!data || data.total === 0) return <div className="rose-empty">No data yet</div>;
  const R = 108, cx = 140, cy = 128;
  const maxCount = Math.max(1, ...data.counts.map(s => s.reduce((a, b) => a + b, 0)));
  const wedges: React.ReactElement[] = [];
  data.counts.forEach((bins, sector) => {
    const angle = sector * 22.5 - 90;
    let r0 = 0;
    bins.forEach((count, bin) => {
      if (count === 0) return;
      const r1 = r0 + (count / maxCount) * R;
      const a0 = rad(angle - 9), a1 = rad(angle + 9);
      const p = (r: number, a: number) => `${cx + r * Math.cos(a)},${cy + r * Math.sin(a)}`;
      wedges.push(
        <path key={`${sector}-${bin}`}
              d={`M ${p(r0, a0)} L ${p(r1, a0)} A ${r1} ${r1} 0 0 1 ${p(r1, a1)} L ${p(r0, a1)} A ${r0} ${r0} 0 0 0 ${p(r0, a0)} Z`}
              fill={BIN_COLORS[bin]} stroke="#161616" strokeWidth="0.5" />
      );
      r0 = r1;
    });
  });
  return (
    <div className="rose-wrap">
      <svg viewBox="0 0 280 262" className="rose">
        {[0.25, 0.5, 0.75, 1].map(f => (
          <circle key={f} cx={cx} cy={cy} r={f * R} fill="none"
                  stroke="rgba(255,255,255,0.15)" strokeDasharray="3 4" />
        ))}
        {["N", "E", "S", "W"].map((c, i) => {
          const a = rad(i * 90 - 90);
          return (
            <text key={c} x={cx + (R + 13) * Math.cos(a)} y={cy + (R + 13) * Math.sin(a) + 4}
                  textAnchor="middle" className="rose-cardinal">{c}</text>
          );
        })}
        {wedges}
      </svg>
      <div className="rose-legend">
        {BIN_LABELS.map((l, i) => (
          <span key={l}><i style={{ background: BIN_COLORS[i] }} />{l}</span>
        ))}
        <span className="rose-meta">mph · {data.hours} h · calm {Math.round((data.calm / data.total) * 100)}%</span>
      </div>
    </div>
  );
}

// ---------- conditions sentence ----------

function conditions(r: WeatherReading | null, s: ConsoleStats | null): string {
  if (!r) return "Waiting for station data…";
  const parts: string[] = [];
  const w = r.windspeedmph ?? 0;
  parts.push(
    w < 1 ? "Calm" :
    w < 8 ? `Light air from the ${cardinal(r.winddir ?? 0)}` :
    w < 16 ? `Breezy from the ${cardinal(r.winddir ?? 0)}` :
    `Windy from the ${cardinal(r.winddir ?? 0)}`
  );
  const tt = s?.temp_trend_f_hr;
  if (tt != null)
    parts.push(Math.abs(tt) < 0.5 ? "temperature steady" : tt > 0 ? "temperature rising" : "temperature falling");
  const pt = s?.press_trend_in_hr;
  if (pt != null)
    parts.push(Math.abs(pt) < 0.005 ? "barometer steady" : pt > 0 ? "barometer rising" : "barometer falling");
  if ((r.hourlyrainin ?? 0) > 0) parts.push("rain falling");
  else if ((r.humidity ?? 0) >= 97) parts.push("fog or marine layer likely");
  return parts.join(", ") + ".";
}

// ---------- the page ----------

const SPARKS: [string, string, string][] = [
  ["tempf", "Temperature", "#ff9c40"],
  ["baromrelin", "Pressure", "#7fc4ff"],
  ["windspeedmph", "Wind", "#4ed44e"],
  ["humidity", "Humidity", "#39cfc3"],
  ["solarradiation", "Solar", "#f5e042"],
  ["dailyrainin", "Rain", "#3f8de0"],
];

export default function Console({ reading }: { reading: WeatherReading | null }) {
  const [stats, setStats] = useState<ConsoleStats | null>(null);
  const [rose, setRose] = useState<WindRoseData | null>(null);
  const [sparks, setSparks] = useState<Record<string, SeriesPoint[]>>({});
  const [clock, setClock] = useState(new Date());

  useEffect(() => {
    const poll = () => invoke<ConsoleStats>("console_stats").then(setStats).catch(() => {});
    poll(); const id = setInterval(poll, 30_000); return () => clearInterval(id);
  }, []);
  useEffect(() => {
    const poll = () => invoke<WindRoseData>("wind_rose", { hours: 24 }).then(setRose).catch(() => {});
    poll(); const id = setInterval(poll, 300_000); return () => clearInterval(id);
  }, []);
  useEffect(() => {
    const poll = () =>
      SPARKS.forEach(([m]) =>
        invoke<SeriesPoint[]>("series_hours", { metric: m, hours: 24 })
          .then(s => setSparks(prev => ({ ...prev, [m]: s })))
          .catch(() => {})
      );
    poll(); const id = setInterval(poll, 300_000); return () => clearInterval(id);
  }, []);
  useEffect(() => {
    const id = setInterval(() => setClock(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  const a = useMemo(() => astro(clock), [clock.getMinutes()]);
  const r = reading;
  const s = stats;

  return (
    <div className="mx">
      <header className="mx-head">
        <h1>Mount Soledad South</h1>
        <div className="mx-geo">
          Latitude: 32° 49′ 09″ N &nbsp; Longitude: 117° 14′ 26″ W &nbsp; Altitude: 522 ft
        </div>
        <div className="mx-clockline">
          {clock.toLocaleTimeString()} &nbsp;
          {clock.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long", year: "numeric" })}
          &nbsp;·&nbsp; {clock.toUTCString().slice(17, 25)} UTC
          &nbsp;·&nbsp; Last reading {r?.date ? new Date(r.date).toLocaleTimeString() : "--"}
        </div>
      </header>

      <div className="mx-astro">
        <span>☀️ Dawn {fmtHM(a.dawn)}</span>
        <span>Sunrise {fmtHM(a.sunrise)}</span>
        <span>Sunset {fmtHM(a.sunset)}</span>
        <span>Dusk {fmtHM(a.dusk)}</span>
        <span>Day length {fmtDur(a.dayLengthMin)}</span>
        <span>Tomorrow {a.tomorrowDeltaMin >= 0 ? "+" : ""}{Math.round(a.tomorrowDeltaMin)} min</span>
        <span>🌙 {a.moonPhaseName}, {Math.round(a.moonIllum * 100)}% lit, {Math.round(a.moonAge)} days old</span>
        <span>Cloud base {r?.tempf != null && r?.dewPoint != null ? `${cloudBaseFt(r.tempf, r.dewPoint).toLocaleString()} ft` : "--"}</span>
      </div>

      <div className="mx-conditions">
        <b>Current conditions:</b>&nbsp;{conditions(r, s)}
      </div>

      <div className="mx-grid">
        {/* 1 */}
        <Card title="Temp Gauge"><SteelRadial value={r?.tempf} title="Ext. Temp" unit="°F" min={30} max={110} /></Card>

        {/* 2 */}
        <Card title="Temperature">
          <div className="hero">{fmt(r?.tempf)}<small>°F</small></div>
          <Trend value={s?.temp_trend_f_hr ?? null} unit="°F/hr" />
          <div className="sub">Avg today {fmt(s?.avg_temp_today)} °F · Inside {fmt(r?.tempinf)} °F</div>
          {s && <HiLo unit="°F"
            today={{ hi: s.today.max_temp, lo: s.today.min_temp }}
            yesterday={{ hi: s.yesterday.max_temp, lo: s.yesterday.min_temp }} />}
        </Card>

        {/* 3 */}
        <Card title="Apparent · Dew Point">
          <div className="hero">{fmt(r?.feelsLike)}<small>°F</small></div>
          <div className="sub">Feels like</div>
          <div className="pairline">
            <span>Dew point <b>{fmt(r?.dewPoint)} °F</b></span>
            <span>Humidity <b>{fmt(r?.humidity, 0)} %</b></span>
          </div>
          <div className="pairline">
            <span>Inside dew <b>{fmt(r?.dewPointin)} °F</b></span>
            <span>Inside hum <b>{fmt(r?.humidityin, 0)} %</b></span>
          </div>
        </Card>

        {/* 4 */}
        <Card title="Charts — last 24 h" className="mx-charts">
          <div className="spark-grid">
            {SPARKS.map(([m, label, color]) => (
              <Spark key={m} series={sparks[m] ?? []} label={label} color={color} />
            ))}
          </div>
        </Card>

        {/* 5 */}
        <Card title="Wind Speed"><SteelRadial value={r?.windspeedmph} title="Wind Speed" unit="mph" max={40} /></Card>
        {/* 6 */}
        <Card title="Wind Direction"><SteelWindDir latest={r?.winddir} average={r?.winddir} /></Card>
        {/* 7 */}
        <Card title="Wind Rose"><WindRose data={rose} /></Card>

        {/* 8 */}
        <Card title="Wind">
          <div className="hero">{fmt(r?.windspeedmph)}<small>mph</small></div>
          <div className="sub">Gust {fmt(r?.windgustmph)} mph · {r?.winddir != null ? `${r.winddir}° ${cardinal(r.winddir)}` : "--"}</div>
          <div className="pairline"><span>Wind run today <b>{fmt(s?.wind_run_today_mi, 0)} mi</b></span></div>
          {s && <HiLo unit="mph"
            today={{ hi: s.today.high_gust, lo: s.today.high_wind }}
            yesterday={{ hi: s.yesterday.high_gust, lo: s.yesterday.high_wind }} />}
          <div className="hl-note">"High" = gust · "Low" = sustained</div>
        </Card>

        {/* 9 */}
        <Card title="Pressure Gauge"><SteelRadial value={r?.baromrelin} title="Pressure" unit="inHg" min={29} max={31} decimals={2} /></Card>

        {/* 10 */}
        <Card title="Pressure">
          <div className="hero">{fmt(r?.baromrelin, 2)}<small>inHg</small></div>
          <Trend value={s?.press_trend_in_hr ?? null} dp={3} unit="in/hr" />
          {s && <HiLo unit="in" dp={2}
            today={{ hi: s.today.max_press, lo: s.today.min_press }}
            yesterday={{ hi: s.yesterday.max_press, lo: s.yesterday.min_press }} />}
        </Card>

        {/* 11 */}
        <Card title="Rainfall">
          <div className="hero">{fmt(r?.dailyrainin, 2)}<small>in today</small></div>
          <div className="pairline"><span>Rate <b>{fmt(r?.hourlyrainin, 2)} in/hr</b></span><span>Yesterday <b>{fmt(s?.rain_yesterday_in, 2)} in</b></span></div>
          <div className="pairline"><span>Month <b>{fmt(s?.rain_month_in, 2)} in</b></span><span>Year <b>{fmt(s?.rain_year_in, 2)} in</b></span></div>
          <div className="pairline"><span>Max rate today <b>{fmt(s?.today.max_rain_rate.value, 2)} in/hr</b></span><span>Yest <b>{fmt(s?.yesterday.max_rain_rate.value, 2)} in/hr</b></span></div>
        </Card>

        {/* 12 */}
        <Card title="Solar · UV">
          <div className="hero">{fmt(r?.solarradiation, 0)}<small>W/m²</small></div>
          <div className="pairline"><span>UV index <b>{fmt(r?.uv, 0)}</b></span>
            <span>{(r?.solarradiation ?? 0) > 10 ? "☀️ Sun up" : "🌙 Sun down"}</span></div>
        </Card>
      </div>
    </div>
  );
}
