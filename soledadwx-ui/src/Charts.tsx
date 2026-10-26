// Charts — multi-metric overlay at adaptive resolution.
//
// Built the evening of the 2026-08-26 dry line, which is the argument for it:
// the story of that event was dewpoint COLLAPSING while temperature ROSE and
// solar fell off a cliff, all inside 28 minutes. No single-metric daily chart
// can show that, and neither can an hourly one. What matters is several
// traces on ONE time axis at the finest resolution the window allows.
//
// Traces in DIFFERENT units keep their own y-scale (normalised into the same
// box) because the point is correlation in TIME — °F and W/m² share no axis
// worth drawing. Traces in the SAME unit share one scale: temperature and
// apparent temp on separate scales made a 1.6 F drift and a 4 F swing look
// the same size (Michael, 2026-10-26; Cumulus never did that). Each trace
// carries its own labelled value and range in the readout so no number is
// lost to the normalising.
//
// Backend: db::series_window, which snaps to a legible bucket and returns raw
// observations whenever the window is short enough to allow it.

import { useEffect, useMemo, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { displayUnit, unitFactor } from "./units";

interface SeriesPoint { t: number; avg: number; min: number; max: number; n: number }

// How a trace turns buckets into values:
//   avg   the bucket mean (most metrics)
//   max   the bucket peak: gusts and rain rate are peaks, and a mean hides them
//   total rain since the window began, built from the station's daily total,
//         which resets at local midnight
//   dir   a bearing: fixed 0-360 scale, dots not a line (a line would draw
//         a false sweep every time the wind crosses north)
type Mode = "avg" | "max" | "total" | "dir";

interface Trace { metric: string; label: string; unit: string; colour: string; mode: Mode; digits: number }

const TRACES: Trace[] = [
  { metric: "tempf", label: "Temperature", unit: "F", colour: "#ff8b3d", mode: "avg", digits: 1 },
  { metric: "dewpointf", label: "Dew point", unit: "F", colour: "#4dd0a1", mode: "avg", digits: 1 },
  { metric: "humidity", label: "Humidity", unit: "%", colour: "#4da3ff", mode: "avg", digits: 0 },
  { metric: "apparenttempf", label: "Apparent temp", unit: "F", colour: "#ff5f7e", mode: "avg", digits: 1 },
  { metric: "tempinf", label: "Inside temp", unit: "F", colour: "#d9a066", mode: "avg", digits: 1 },
  { metric: "humidityin", label: "Inside humidity", unit: "%", colour: "#8fb9d9", mode: "avg", digits: 0 },
  { metric: "solarradiation", label: "Solar", unit: "W/m²", colour: "#ffd24d", mode: "avg", digits: 0 },
  { metric: "windspeedmph", label: "Wind", unit: "mph", colour: "#b388ff", mode: "avg", digits: 1 },
  { metric: "windgustmph", label: "Gust", unit: "mph", colour: "#7a5cd6", mode: "max", digits: 1 },
  { metric: "winddir", label: "Wind direction", unit: "°", colour: "#e6c3ff", mode: "dir", digits: 0 },
  { metric: "dailyrainin", label: "Rain total", unit: "in", colour: "#3d7cff", mode: "total", digits: 2 },
  // The Ambient station reports its rain RATE in the field it calls hourlyrainin.
  { metric: "hourlyrainin", label: "Rain rate", unit: "in/hr", colour: "#29c4e0", mode: "max", digits: 2 },
  { metric: "baromrelin", label: "Pressure", unit: "inHg", colour: "#9aa7b4", mode: "avg", digits: 2 },
];

const COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];
const compass = (deg: number) => COMPASS[Math.round(deg / 22.5) % 16];

/** Display values for one trace, one per bucket. */
function traceValues(tr: Trace, s: SeriesPoint[]): number[] {
  const uk = unitFactor(tr.unit);
  switch (tr.mode) {
    case "avg": return s.map(p => p.avg * uk);
    case "max": return s.map(p => p.max * uk);
    case "dir": return s.map(p => p.avg);
    case "total": {
      // Accumulate increases; a drop is the midnight reset, after which the
      // new day's reading is all fresh rain.
      let total = 0;
      return s.map((p, i) => {
        if (i > 0) {
          const prev = s[i - 1].max;
          total += p.max >= prev ? p.max - prev : p.max;
        }
        return total;
      });
    }
  }
}

const RANGES: [string, number][] = [
  ["1 h", 1], ["3 h", 3], ["6 h", 6], ["12 h", 12],
  ["24 h", 24], ["3 d", 72], ["7 d", 168], ["30 d", 720],
];

const fmtClock = (ts: number, spanH: number) => {
  const d = new Date(ts * 1000);
  if (spanH <= 24) return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  if (spanH <= 168) return d.toLocaleString(undefined, { weekday: "short", hour: "2-digit" });
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
};

export default function Charts() {
  const [hours, setHours] = useState(3);
  const [active, setActive] = useState<string[]>(["tempf", "dewpointf", "solarradiation"]);
  const [data, setData] = useState<Record<string, SeriesPoint[]>>({});
  const [busy, setBusy] = useState(false);
  const [hoverX, setHoverX] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);

  const activeKey = active.join(",");

  useEffect(() => {
    let dead = false;
    const load = () => {
      const end = Math.floor(Date.now() / 1000);
      const start = end - hours * 3600;
      setBusy(true);
      Promise.all(
        active.map(m =>
          invoke<SeriesPoint[]>("series_window", {
            metric: m, startTs: start, endTs: end, maxPoints: 1200,
          })
            .then(s => [m, s] as const)
            .catch(() => [m, [] as SeriesPoint[]] as const)
        )
      )
        .then(pairs => { if (!dead) setData(Object.fromEntries(pairs)); })
        .finally(() => { if (!dead) setBusy(false); });
    };
    load();
    // Live tail: only worth re-polling on short windows.
    const id = hours <= 24 ? setInterval(load, 60_000) : null;
    return () => { dead = true; if (id) clearInterval(id); };
  }, [hours, activeKey]);

  const toggle = (m: string) =>
    setActive(a => (a.includes(m) ? a.filter(x => x !== m) : [...a, m]));

  const W = 1000, H = 420, PL = 8, PR = 8, PT = 16, PB = 30;

  const view = useMemo(() => {
    const all = active.map(m => data[m] ?? []).filter(s => s.length > 0);
    if (all.length === 0) return null;
    const t0 = Math.min(...all.map(s => s[0].t));
    const tEnd = Math.max(...all.map(s => s[s.length - 1].t));
    return { t0, t1: tEnd > t0 ? tEnd : t0 + 1 };
  }, [data, activeKey]);

  // One [lo, hi] per display unit across the active traces; bearings keep a
  // fixed compass scale.
  const scales = useMemo(() => {
    const out: Record<string, [number, number]> = {};
    for (const m of active) {
      const s = data[m];
      const def = TRACES.find(tr => tr.metric === m);
      if (!s || s.length === 0 || !def || def.mode === "dir") continue;
      const vals = traceValues(def, s);
      const key = displayUnit(def.unit);
      const [lo, hi] = out[key] ?? [Infinity, -Infinity];
      out[key] = [Math.min(lo, ...vals), Math.max(hi, ...vals)];
    }
    return out;
  }, [data, activeKey]);

  const x = (t: number) =>
    view ? PL + ((t - view.t0) / (view.t1 - view.t0)) * (W - PL - PR) : 0;

  // Bucket actually returned, inferred from consecutive timestamps — this is
  // how the footer reports resolution honestly instead of claiming "raw".
  const bucketS = useMemo(() => {
    for (const m of active) {
      const s = data[m];
      if (s && s.length > 2) return s[1].t - s[0].t;
    }
    return null;
  }, [data, activeKey]);

  const hoverT = hoverX != null && view
    ? view.t0 + ((hoverX - PL) / (W - PL - PR)) * (view.t1 - view.t0)
    : null;

  const nx = 6;
  const xticks = view
    ? Array.from({ length: nx }, (_, i) => view.t0 + ((view.t1 - view.t0) * i) / (nx - 1))
    : [];

  return (
    <div className="charts">
      <h2 className="page-title">Charts</h2>
      <p className="page-sub">
        Several metrics on one time axis, at the finest resolution the window allows.
        Traces in the same unit share a scale; different units are each scaled to fit —
        the point is when things move together.
      </p>

      <div className="ch-controls">
        <div className="ch-ranges">
          {RANGES.map(([label, h]) => (
            <button key={h} className={h === hours ? "on" : ""} onClick={() => setHours(h)}>
              {label}
            </button>
          ))}
        </div>
        <div className="ch-legend">
          {TRACES.map(({ metric: m, label, colour }) => (
            <button
              key={m}
              className={`ch-chip ${active.includes(m) ? "on" : ""}`}
              style={active.includes(m) ? { borderColor: colour, color: colour } : undefined}
              onClick={() => toggle(m)}
            >
              <span className="ch-swatch" style={{ background: colour }} />{label}
            </button>
          ))}
        </div>
      </div>

      {!view ? (
        <div className="chart-empty">{busy ? "Loading…" : "No data in range."}</div>
      ) : (
        <svg
          ref={svgRef}
          viewBox={`0 0 ${W} ${H}`}
          className="ch-svg"
          onMouseMove={e => {
            const r = svgRef.current?.getBoundingClientRect();
            if (r) setHoverX(((e.clientX - r.left) / r.width) * W);
          }}
          onMouseLeave={() => setHoverX(null)}
        >
          {xticks.map((t, i) => (
            <g key={i}>
              <line x1={x(t)} x2={x(t)} y1={PT} y2={H - PB} className="gridline" />
              <text x={x(t)} y={H - 10} className="tick" textAnchor="middle">
                {fmtClock(t, hours)}
              </text>
            </g>
          ))}

          {active.map(m => {
            const s = data[m];
            const def = TRACES.find(tr => tr.metric === m);
            if (!s || s.length === 0 || !def) return null;
            const vals = traceValues(def, s);
            const [lo, hi] = def.mode === "dir" ? [0, 360] : scales[displayUnit(def.unit)];
            const span = hi - lo || 1;
            // Each trace gets 88% of the box, inset, so a flat trace does not
            // sit welded to the frame edge.
            const y = (v: number) =>
              PT + (1 - (v - lo) / span) * (H - PT - PB) * 0.88 + (H - PT - PB) * 0.06;
            if (def.mode === "dir")
              return (
                <g key={m} fill={def.colour}>
                  {s.map((p, i) => <circle key={p.t} cx={x(p.t)} cy={y(vals[i])} r={1.6} />)}
                </g>
              );
            const line = s
              .map((p, i) => `${x(p.t).toFixed(1)},${y(vals[i]).toFixed(1)}`)
              .join(" ");
            return (
              <polyline
                key={m}
                points={line}
                fill="none"
                stroke={def.colour}
                strokeWidth={1.8}
                strokeLinejoin="round"
              />
            );
          })}

          {hoverT != null && (
            <line x1={x(hoverT)} x2={x(hoverT)} y1={PT} y2={H - PB} className="ch-cursor" />
          )}
        </svg>
      )}

      <div className="ch-readout">
        {active.map(m => {
          const s = data[m];
          const def = TRACES.find(tr => tr.metric === m);
          if (!s || s.length === 0 || !def) return null;
          const unit = displayUnit(def.unit);
          const vals = traceValues(def, s);
          let cur = vals[vals.length - 1];
          if (hoverT != null) {
            let best = 0, bd = Infinity;
            s.forEach((p, i) => {
              const d = Math.abs(p.t - hoverT);
              if (d < bd) { bd = d; best = i; }
            });
            cur = vals[best];
          }
          return (
            <div key={m} className="ch-stat" style={{ borderLeftColor: def.colour }}>
              <span className="ch-stat-label">{def.label}</span>
              <span className="ch-stat-val">
                {def.mode === "dir" ? `${compass(cur)} ` : ""}{cur.toFixed(def.digits)}<em>{unit}</em>
              </span>
              <span className="ch-stat-range">
                {def.mode === "dir" ? "bearing"
                  : def.mode === "total" ? "since window start"
                  : `${Math.min(...vals).toFixed(def.digits)} – ${Math.max(...vals).toFixed(def.digits)}`}
              </span>
            </div>
          );
        })}
      </div>

      <p className="chart-note">
        {bucketS != null &&
          (bucketS <= 1
            ? "Raw observations — no averaging."
            : `Bucketed to ${bucketS < 3600 ? `${Math.round(bucketS / 60)} min` : `${Math.round(bucketS / 3600)} h`}.`)}
        {hoverT != null && ` · ${new Date(hoverT * 1000).toLocaleString()}`}
      </p>
    </div>
  );
}
