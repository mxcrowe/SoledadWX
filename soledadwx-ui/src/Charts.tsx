// Charts — multi-metric overlay at adaptive resolution.
//
// Built the evening of the 2026-08-26 dry line, which is the argument for it:
// the story of that event was dewpoint COLLAPSING while temperature ROSE and
// solar fell off a cliff, all inside 28 minutes. No single-metric daily chart
// can show that, and neither can an hourly one. What matters is several
// traces on ONE time axis at the finest resolution the window allows.
//
// Each metric keeps its own y-scale (normalised into the same box) because
// the point is correlation in TIME, not comparison of magnitudes — °F and
// W/m² share no axis worth drawing. Each trace carries its own labelled
// value and range in the readout so no number is lost to the normalising.
//
// Backend: db::series_window, which snaps to a legible bucket and returns raw
// observations whenever the window is short enough to allow it.

import { useEffect, useMemo, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { displayUnit, unitFactor } from "./units";

interface SeriesPoint { t: number; avg: number; min: number; max: number; n: number }

// metric, label, stored unit, colour
const TRACES: [string, string, string, string][] = [
  ["tempf", "Temperature", "F", "#ff8b3d"],
  ["dewpointf", "Dew point", "F", "#4dd0a1"],
  ["humidity", "Humidity", "%", "#4da3ff"],
  ["apparenttempf", "Apparent temp", "F", "#ff5f7e"],
  ["solarradiation", "Solar", "W/m²", "#ffd24d"],
  ["windspeedmph", "Wind", "mph", "#b388ff"],
  ["windgustmph", "Gust", "mph", "#7a5cd6"],
  ["baromrelin", "Pressure", "inHg", "#9aa7b4"],
];

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
        Each trace is scaled to its own range — the point is when things move together,
        not how big they are.
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
          {TRACES.map(([m, label, , colour]) => (
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
            const def = TRACES.find(tr => tr[0] === m);
            if (!s || s.length === 0 || !def) return null;
            const uk = unitFactor(def[2]);
            const vals = s.map(p => p.avg * uk);
            const lo = Math.min(...vals), hi = Math.max(...vals);
            const span = hi - lo || 1;
            // Each trace gets 88% of the box, inset, so a flat trace does not
            // sit welded to the frame edge.
            const y = (v: number) =>
              PT + (1 - (v - lo) / span) * (H - PT - PB) * 0.88 + (H - PT - PB) * 0.06;
            const line = s
              .map((p, i) => `${x(p.t).toFixed(1)},${y(vals[i]).toFixed(1)}`)
              .join(" ");
            return (
              <polyline
                key={m}
                points={line}
                fill="none"
                stroke={def[3]}
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
          const def = TRACES.find(tr => tr[0] === m);
          if (!s || s.length === 0 || !def) return null;
          const uk = unitFactor(def[2]);
          const unit = displayUnit(def[2]);
          const vals = s.map(p => p.avg * uk);
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
            <div key={m} className="ch-stat" style={{ borderLeftColor: def[3] }}>
              <span className="ch-stat-label">{def[1]}</span>
              <span className="ch-stat-val">{cur.toFixed(1)}<em>{unit}</em></span>
              <span className="ch-stat-range">
                {Math.min(...vals).toFixed(1)} – {Math.max(...vals).toFixed(1)}
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
