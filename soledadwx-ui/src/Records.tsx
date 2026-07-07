import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";

interface RecordRow {
  label: string;
  value: number;
  unit: string;
  when_ts: number | null;
  when_day: string | null;
}
interface RecordCategory { name: string; rows: RecordRow[] }

const dp = (unit: string) =>
  unit === "mi" || unit === "index" || unit === "%" ? (unit === "%" ? 0 : unit === "mi" ? 0 : 1)
  : unit === "inHg" || unit === "in" || unit === "in/hr" ? 2
  : unit === "W/m²" ? 0
  : 1;

const fmtWhen = (r: RecordRow) => {
  if (r.when_ts != null)
    return new Date(r.when_ts * 1000).toLocaleString(undefined, {
      hour: "numeric", minute: "2-digit", day: "numeric", month: "long", year: "numeric",
    });
  if (r.when_day)
    return new Date(r.when_day + "T00:00:00").toLocaleDateString(undefined, {
      day: "numeric", month: "long", year: "numeric",
    });
  return "—";
};

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

      <div className="rec-tabs">
        {cats.map((c, i) => (
          <button key={c.name}
                  className={i === tab ? "rec-tab active" : "rec-tab"}
                  onClick={() => setTab(i)}>{c.name}</button>
        ))}
      </div>

      <table className="rec-table">
        <tbody>
          {cat.rows.map((r) => (
            <tr key={r.label}>
              <td className="rec-label">{r.label}</td>
              <td className="rec-value">
                {r.value.toFixed(dp(r.unit))} <span className="rec-unit">{r.unit}</span>
              </td>
              <td className="rec-when">{fmtWhen(r)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
