import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { toDisplay } from "./units";

interface RecordRow {
  label: string;
  value: number;
  unit: string;
  when_ts: number | null;
  when_day: string | null;
  // The raw single-reading record, only when it differs from the QC'd one.
  raw_value: number | null;
  raw_when_ts: number | null;
  raw_when_day: string | null;
}
interface RecordCategory { name: string; rows: RecordRow[] }

export const dp = (unit: string) =>
  unit === "mi" || unit === "index" || unit === "%" ? (unit === "%" ? 0 : unit === "mi" ? 0 : 1)
  : unit === "inHg" || unit === "in" || unit === "in/hr" ? 2
  : unit === "W/m²" ? 0
  : 1;

const fmtWhen = (ts: number | null, day: string | null) => {
  if (ts != null)
    return new Date(ts * 1000).toLocaleString(undefined, {
      hour: "numeric", minute: "2-digit", day: "numeric", month: "long", year: "numeric",
    });
  if (day)
    return new Date(day + "T00:00:00").toLocaleDateString(undefined, {
      day: "numeric", month: "long", year: "numeric",
    });
  return "—";
};

const localDay = (ts: number | null, day: string | null) =>
  ts != null ? new Date(ts * 1000).toDateString() : day;

export default function Records() {
  const [cats, setCats] = useState<RecordCategory[] | null>(null);
  const [tab, setTab] = useState(0);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    invoke<RecordCategory[]>("records").then(setCats).catch((e) => setErr(String(e)));
  }, []);

  if (err) return <div className="error">{err}</div>;
  if (!cats) return <div className="loading">Computing records…</div>;
  const cat = cats[tab];

  return (
    <div className="records">
      <h2 className="page-title">All-Time Records</h2>
      <p className="page-sub">Mount Soledad South · September 2009 – present</p>
      <p className="rec-note">
        A record must hold for two consecutive readings (where the station logged every few minutes),
        and readings that fail a quality check
        (impossible values, one-reading spikes, known sensor failures) are set aside. Where the raw
        single reading was more extreme, it is shown underneath.
      </p>

      <div className="rec-tabs">
        {cats.map((c, i) => (
          <button key={c.name}
                  className={i === tab ? "rec-tab active" : "rec-tab"}
                  onClick={() => setTab(i)}>{c.name}</button>
        ))}
      </div>

      <table className="rec-table">
        <tbody>
          {cat.rows.map((r) => {
            // Wind is stored in mph but displayed in knots (wind run in nm).
            const d = toDisplay(r.value, r.unit);
            const raw = r.raw_value != null ? toDisplay(r.raw_value, r.unit) : null;
            const rawElsewhen = localDay(r.raw_when_ts, r.raw_when_day) !== localDay(r.when_ts, r.when_day);
            return (
            <tr key={r.label}>
              <td className="rec-label">{r.label}</td>
              <td className="rec-value">
                {(d.value ?? 0).toFixed(dp(r.unit))} <span className="rec-unit">{d.unit}</span>
                {raw && (
                  <div className="rec-raw" title={`Raw single reading: ${fmtWhen(r.raw_when_ts, r.raw_when_day)}`}>
                    raw {(raw.value ?? 0).toFixed(dp(r.unit))}
                  </div>
                )}
              </td>
              <td className="rec-when">
                {fmtWhen(r.when_ts, r.when_day)}
                {raw && rawElsewhen && (
                  <div className="rec-raw">{fmtWhen(r.raw_when_ts, r.raw_when_day)}</div>
                )}
              </td>
            </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
