import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { toDisplay } from "./units";
import { dp } from "./Records";

interface Cell {
  value: number;
  when_ts: number | null;
  when_day: string | null;
}
interface Row {
  label: string;
  unit: string;
  month: Cell | null;
  month_record: Cell | null;
  year: Cell | null;
  all_time: Cell | null;
}
interface Group { name: string; rows: Row[] }
interface Report { month_start: string; year_start: string; groups: Group[] }

// The Monitor refreshes today's rollup every 5 minutes; match it.
const REFRESH_MS = 5 * 60 * 1000;

/** The cell's civil-local ISO date, for comparing against window starts. */
const isoDay = (c: Cell) => {
  if (c.when_day) return c.when_day;
  const d = new Date(c.when_ts! * 1000);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
};

/** Recent cells need the time of day; record cells need the year. */
const fmtWhen = (c: Cell, withYear: boolean) => {
  const opts: Intl.DateTimeFormatOptions = withYear
    ? { day: "numeric", month: "short", year: "numeric" }
    : { day: "numeric", month: "short" };
  if (c.when_ts != null) {
    const d = new Date(c.when_ts * 1000);
    if (withYear) return d.toLocaleDateString(undefined, opts);
    return `${d.toLocaleDateString(undefined, opts)}, ${d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}`;
  }
  return new Date(c.when_day + "T00:00:00").toLocaleDateString(undefined, opts);
};

function Value({ cell, unit, withYear, badge }: {
  cell: Cell | null; unit: string; withYear: boolean; badge?: string | null;
}) {
  if (!cell) return <td className="ext-cell ext-none">—</td>;
  const d = toDisplay(cell.value, unit);
  return (
    <td className={badge ? "ext-cell ext-new" : "ext-cell"}>
      <div className="ext-value">
        {(d.value ?? 0).toFixed(dp(unit))} <span className="rec-unit">{d.unit}</span>
      </div>
      <div className="ext-when">{fmtWhen(cell, withYear)}</div>
      {badge && <div className="ext-badge">★ {badge}</div>}
    </td>
  );
}

export default function Extremes() {
  const [report, setReport] = useState<Report | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    const load = () => invoke<Report>("extremes").then(setReport).catch((e) => setErr(String(e)));
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, []);

  if (err) return <div className="error">{err}</div>;
  if (!report) return <div className="loading">Finding extremes…</div>;

  const start = new Date(report.month_start + "T00:00:00");
  const monthName = start.toLocaleDateString(undefined, { month: "long" });
  const year = start.getFullYear();
  const inMonth = (c: Cell | null) => c != null && isoDay(c) >= report.month_start;
  const inYear = (c: Cell | null) => c != null && isoDay(c) >= report.year_start;
  // A record held by an earlier year but matched now is a tie, not a new one.
  const ties = (now: Cell | null, rec: Cell | null) =>
    now != null && rec != null && !inMonth(rec) && Math.abs(now.value - rec.value) < 1e-9;

  return (
    <div className="extremes">
      <h2 className="page-title">Soledad Extremes</h2>
      <p className="page-sub">
        {monthName} {year} so far, against every {monthName} since 2009 · updates every few minutes
      </p>

      <table className="ext-table">
        <thead>
          <tr>
            <th />
            <th>This month</th>
            <th>{monthName} record</th>
            <th>This year</th>
            <th>All time</th>
          </tr>
        </thead>
        {report.groups.map((g) => (
          <tbody key={g.name}>
            <tr className="ext-group"><td colSpan={5}>{g.name}</td></tr>
            {g.rows.map((r) => (
              <tr key={r.label}>
                <td className="rec-label">{r.label}</td>
                <Value cell={r.month} unit={r.unit} withYear={false}
                       badge={ties(r.month, r.month_record) ? `ties ${monthName} record` : null} />
                <Value cell={r.month_record} unit={r.unit} withYear
                       badge={inMonth(r.month_record) ? "set this month" : null} />
                <Value cell={r.year} unit={r.unit} withYear={false} />
                <Value cell={r.all_time} unit={r.unit} withYear
                       badge={inMonth(r.all_time) ? "set this month" : inYear(r.all_time) ? "set this year" : null} />
              </tr>
            ))}
          </tbody>
        ))}
      </table>

      <p className="rec-note">
        Extremes are quality-checked the same way as All-Time Records: impossible values, one-reading
        spikes and known sensor failures are set aside, and on finely logged data an extreme must hold
        for two consecutive readings. Humidity and dew point have no usable record for most of 2010–2018.
      </p>
    </div>
  );
}
