import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { toKt, toNm, WIND_UNIT, WIND_RUN_UNIT } from "./units";

// Synopsis by Period: the report card for one month, year or custom range,
// after Cumulus's "Averages and Extremes for [period]". Read-only: pick a
// period, read the numbers. Comparing periods is the Analyst's job.

interface Extreme { value: number | null; ts: number | null }
interface DayValue { value: number; day: string }
interface SourceShare { kind: string; readings: number; proxy: boolean }
interface SynopsisData {
  start: string;
  end: string; // exclusive
  days_in_period: number;
  days_with_data: number;
  includes_today: boolean;
  temp: {
    mean_all: number | null; mean_minmax: number | null;
    mean_min: number | null; mean_max: number | null;
    min: Extreme; max: Extreme;
    highest_min: DayValue | null; lowest_max: DayValue | null;
    hot_days: number; warm_nights: number;
  };
  rain: {
    total_in: number | null; wettest: DayValue | null; max_rate: Extreme;
    rain_days: number; dry_days: number;
  };
  pressure: { highest: Extreme; lowest: Extreme };
  wind: { highest_gust: Extreme; mean_mph: number | null; run_mi: number | null; gale_days: number };
  humidity: { mean_rh: number | null; mean_dewpoint: number | null; highest_dewpoint: Extreme; lowest_rh: Extreme };
  solar: { peak: Extreme; max_uv: Extreme; mean_daily_kwh: number | null; energy_days: number };
  sources: SourceShare[];
}

type Mode = "month" | "year" | "custom";

const FIRST_YEAR = 2009;
const FIRST_MONTH = 8; // September 2009, 0-based: the Archive's first month
const MONTHS = ["January", "February", "March", "April", "May", "June", "July",
  "August", "September", "October", "November", "December"];

/** The hygrometer saturated (railed at 99/10) until it was replaced. */
// Railed hygrometers, measured 2026-10-26 (scripts/wxdb.py QUALITY_PERIODS).
// Extremes inside these are already set aside; the warning covers the means.
const BAD_HUMIDITY: [string, string][] = [
  ["2010-07-01", "2016-12-01"],
  ["2017-08-01", "2018-09-01"],
];

const SOURCE_LABELS: Record<string, string> = {
  cumulus_log: "Cumulus log",
  mdb: "HP2000 console log",
  amb_rest: "Ambient cloud",
  amb_ws: "Recorder (live)",
  wu_pws: "Weather Underground (our station)",
  sdcard: "Console SD card",
  msdsd: "MSDSD Mt Soledad",
  ksan_metar: "San Diego airport",
  wu_ksandi354: "Neighbour KCASANDI354",
  wu_ksandi4366: "Neighbour KCASANDI4366",
  wu_ksandi84: "Neighbour KCASANDI84",
};

const pad = (n: number) => String(n).padStart(2, "0");
const iso = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const addDays = (s: string, n: number) => {
  const d = new Date(s + "T00:00:00");
  d.setDate(d.getDate() + n);
  return iso(d);
};

function periodBounds(mode: Mode, year: number, month: number, from: string, to: string): [string, string] {
  if (mode === "month") {
    const next = month === 11 ? `${year + 1}-01-01` : `${year}-${pad(month + 2)}-01`;
    return [`${year}-${pad(month + 1)}-01`, next];
  }
  if (mode === "year") return [`${year}-01-01`, `${year + 1}-01-01`];
  return [from, addDays(to, 1)]; // custom: the end date is inclusive on screen
}

function periodTitle(mode: Mode, year: number, month: number, from: string, to: string): string {
  if (mode === "month") return `${MONTHS[month]} ${year}`;
  if (mode === "year") return String(year);
  const f = (s: string) => new Date(s + "T00:00:00").toLocaleDateString(undefined,
    { day: "numeric", month: "short", year: "numeric" });
  return `${f(from)} – ${f(to)}`;
}

export default function Synopsis() {
  const now = new Date();
  const [mode, setMode] = useState<Mode>("month");
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth());
  const [from, setFrom] = useState(iso(new Date(now.getFullYear(), now.getMonth(), 1)));
  const [to, setTo] = useState(iso(now));
  const [data, setData] = useState<SynopsisData | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [start, end] = periodBounds(mode, year, month, from, to);

  useEffect(() => {
    if (mode === "custom" && from > to) { setErr("The start date is after the end date."); return; }
    let live = true;
    setBusy(true);
    setErr(null);
    invoke<SynopsisData>("synopsis", { start, end })
      .then((d) => { if (live) setData(d); })
      .catch((e) => { if (live) { setErr(String(e)); setData(null); } })
      .finally(() => { if (live) setBusy(false); });
    return () => { live = false; };
  }, [start, end]);

  // Stepping: the ◀ ▶ arrows walk months or years, clamped to the Archive.
  const atStart = mode === "month" ? year === FIRST_YEAR && month <= FIRST_MONTH : year <= FIRST_YEAR;
  const atEnd = mode === "month"
    ? year === now.getFullYear() && month >= now.getMonth()
    : year >= now.getFullYear();
  const step = (dir: -1 | 1) => {
    if (mode === "year") { setYear(year + dir); return; }
    const m = month + dir;
    if (m < 0) { setMonth(11); setYear(year - 1); }
    else if (m > 11) { setMonth(0); setYear(year + 1); }
    else setMonth(m);
  };

  const years: number[] = [];
  for (let y = now.getFullYear(); y >= FIRST_YEAR; y--) years.push(y);

  // Dates in a single-year period don't need the year repeated.
  const multiYear = start.slice(0, 4) !== addDays(end, -1).slice(0, 4);
  const whenTs = (e: Extreme) => e.ts == null ? "" : new Date(e.ts * 1000).toLocaleString(undefined, {
    day: "numeric", month: "short", ...(multiYear ? { year: "numeric" } : {}),
    hour: "numeric", minute: "2-digit",
  });
  const whenDay = (d: DayValue | null) => d == null ? "" : new Date(d.day + "T00:00:00").toLocaleDateString(undefined, {
    day: "numeric", month: "short", ...(multiYear ? { year: "numeric" } : {}),
  });

  return (
    <div className="synopsis">
      <h2 className="page-title">Averages and Extremes</h2>
      <p className="page-sub">{periodTitle(mode, year, month, from, to)}</p>

      <div className="syn-controls">
        <div className="rec-tabs">
          {(["month", "year", "custom"] as Mode[]).map((m) => (
            <button key={m} className={m === mode ? "rec-tab active" : "rec-tab"}
                    onClick={() => setMode(m)}>
              {m === "month" ? "Month" : m === "year" ? "Year" : "Custom"}
            </button>
          ))}
        </div>
        {mode !== "custom" ? (
          <div className="syn-picker">
            <button className="syn-step" disabled={atStart} onClick={() => step(-1)}>◀</button>
            {mode === "month" && (
              <select value={month} onChange={(e) => setMonth(Number(e.target.value))}>
                {MONTHS.map((name, i) => <option key={name} value={i}>{name}</option>)}
              </select>
            )}
            <select value={year} onChange={(e) => setYear(Number(e.target.value))}>
              {years.map((y) => <option key={y} value={y}>{y}</option>)}
            </select>
            <button className="syn-step" disabled={atEnd} onClick={() => step(1)}>▶</button>
          </div>
        ) : (
          <div className="syn-picker">
            <input type="date" value={from} min="2009-09-01" max={iso(now)} onChange={(e) => setFrom(e.target.value)} />
            <span className="syn-to">to</span>
            <input type="date" value={to} min="2009-09-01" max={iso(now)} onChange={(e) => setTo(e.target.value)} />
          </div>
        )}
      </div>

      {err && <div className="error">{err}</div>}
      {!data && !err && <div className="loading">Computing…</div>}
      {data && <Card data={data} busy={busy} whenTs={whenTs} whenDay={whenDay} />}
    </div>
  );
}

const num = (v: number | null | undefined, dp: number) => v == null ? null : v.toFixed(dp);

function Row({ label, value, unit, when }: { label: string; value: string | number | null; unit?: string; when?: string }) {
  return (
    <tr>
      <td className="syn-label">{label}</td>
      <td className="syn-val">{value == null ? "—" : value}{value != null && unit && <span className="syn-unit">{unit}</span>}</td>
      <td className="syn-when">{value == null ? "" : when}</td>
    </tr>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="syn-panel">
      <h3>{title}</h3>
      <table><tbody>{children}</tbody></table>
    </section>
  );
}

function Card({ data: d, busy, whenTs, whenDay }: {
  data: SynopsisData; busy: boolean;
  whenTs: (e: Extreme) => string; whenDay: (d: DayValue | null) => string;
}) {
  const t = d.temp, r = d.rain, p = d.pressure, w = d.wind, h = d.humidity, s = d.solar;
  const badHumidity = BAD_HUMIDITY.some(([from, to]) => d.start < to && d.end > from);
  const proxies = d.sources.filter((x) => x.proxy);
  const total = d.sources.reduce((n, x) => n + x.readings, 0);

  return (
    <div className={busy ? "syn-card syn-busy" : "syn-card"}>
      <div className="syn-grid">
        <Panel title="Temperature">
          <Row label="Mean (all readings)" value={num(t.mean_all, 1)} unit="°F" />
          <Row label="Mean (min + max)" value={num(t.mean_minmax, 1)} unit="°F" />
          <Row label="Mean minimum" value={num(t.mean_min, 1)} unit="°F" />
          <Row label="Mean maximum" value={num(t.mean_max, 1)} unit="°F" />
          <Row label="Minimum" value={num(t.min.value, 1)} unit="°F" when={whenTs(t.min)} />
          <Row label="Maximum" value={num(t.max.value, 1)} unit="°F" when={whenTs(t.max)} />
          <Row label="Highest minimum" value={num(t.highest_min?.value, 1)} unit="°F" when={whenDay(t.highest_min)} />
          <Row label="Lowest maximum" value={num(t.lowest_max?.value, 1)} unit="°F" when={whenDay(t.lowest_max)} />
          <Row label="Hot days (≥ 90 °F)" value={d.days_with_data ? t.hot_days : null} />
          <Row label="Warm nights (low ≥ 70 °F)" value={d.days_with_data ? t.warm_nights : null} />
        </Panel>

        <Panel title="Rainfall">
          <Row label="Total" value={num(r.total_in, 2)} unit="in" />
          <Row label="Wettest day" value={num(r.wettest?.value, 2)} unit="in" when={whenDay(r.wettest)} />
          <Row label="Highest rain rate" value={num(r.max_rate.value, 2)} unit="in/hr" when={whenTs(r.max_rate)} />
          <Row label="Rain days" value={r.total_in == null ? null : r.rain_days} />
          <Row label="Dry days" value={r.total_in == null ? null : r.dry_days} />
        </Panel>

        <Panel title="Pressure">
          <Row label="Highest" value={num(p.highest.value, 2)} unit="inHg" when={whenTs(p.highest)} />
          <Row label="Lowest" value={num(p.lowest.value, 2)} unit="inHg" when={whenTs(p.lowest)} />
        </Panel>

        <Panel title="Wind">
          <Row label="Highest gust" value={num(toKt(w.highest_gust.value), 1)} unit={WIND_UNIT} when={whenTs(w.highest_gust)} />
          <Row label="Average speed" value={num(toKt(w.mean_mph), 1)} unit={WIND_UNIT} />
          <Row label="Wind run" value={num(toNm(w.run_mi), 0)} unit={WIND_RUN_UNIT} />
          <Row label="Gale days (≥ 34 kt)" value={w.run_mi == null ? null : w.gale_days} />
        </Panel>

        <Panel title="Humidity">
          <Row label="Mean humidity" value={num(h.mean_rh, 0)} unit="%" />
          <Row label="Mean dew point" value={num(h.mean_dewpoint, 1)} unit="°F" />
          <Row label="Highest dew point" value={num(h.highest_dewpoint.value, 1)} unit="°F" when={whenTs(h.highest_dewpoint)} />
          <Row label="Lowest humidity" value={num(h.lowest_rh.value, 0)} unit="%" when={whenTs(h.lowest_rh)} />
        </Panel>

        <Panel title="Solar">
          <Row label="Peak radiation" value={num(s.peak.value, 0)} unit="W/m²" when={whenTs(s.peak)} />
          <Row label="Mean daily energy" value={num(s.mean_daily_kwh, 2)} unit="kWh/m²" />
          <Row label="Highest UV index" value={num(s.max_uv.value, 0)} when={whenTs(s.max_uv)} />
        </Panel>
      </div>

      <div className="syn-notes">
        <div>
          {d.days_with_data} of {d.days_in_period} days have data
          {d.includes_today && <span className="syn-badge">includes today so far</span>}
        </div>
        {total > 0 && (
          <div className="syn-sources">
            Temperature readings:{" "}
            {d.sources.map((x, i) => (
              <span key={x.kind} className={x.proxy ? "syn-proxy" : undefined}>
                {i > 0 && " · "}
                {SOURCE_LABELS[x.kind] ?? x.kind}{x.proxy && " (proxy)"} {x.readings.toLocaleString()}
              </span>
            ))}
          </div>
        )}
        {proxies.length > 0 && (
          <div className="syn-warn">
            Some figures include readings from another station, used where ours were missing.
          </div>
        )}
        {badHumidity && (
          <div className="syn-warn">
            Humidity from July 2010 to November 2016, and from August 2017 to August 2018, is unreliable:
            the hygrometer was stuck at its limits. Humidity and dew point extremes from those months are
            left out; the means shown here include them.
          </div>
        )}
        {s.mean_daily_kwh != null && (
          <div>Solar energy is averaged over the {s.energy_days} days with live solar data.</div>
        )}
      </div>
    </div>
  );
}
