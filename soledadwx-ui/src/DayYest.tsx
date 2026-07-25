// Today vs Yesterday — a grouped comparison of daily high/low/avg with the
// time-of-occurrence and the today-minus-yesterday difference, modeled on the
// Beaumaris/MXUI "Today/Yesterday" report. Backend: db::day_compare.

import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { clearSkyEnergyKwh, SOLAR_CLEAR_CAPTURE } from "./astro";
import { toKt, WIND_RUN_UNIT, WIND_UNIT } from "./units";

interface Extreme { value: number | null; ts: number | null }
interface DayStat { high: Extreme; low: Extreme; avg: number | null }
interface MetricPair { metric: string; today: DayStat; yesterday: DayStat }
interface DayCompare {
  metrics: MetricPair[];
  wind_run_today: number | null;
  wind_run_yest: number | null;
  dom_dir_today: number | null;
  dom_dir_yest: number | null;
  solar_energy_today: number | null;
  solar_energy_yest: number | null;
}

const CARDINALS = [
  "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
  "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
];
const cardinal = (d: number) => CARDINALS[Math.round(d / 22.5) % 16];

const fmtN = (v: number | null | undefined, dp = 1) =>
  v == null ? "--" : v.toFixed(dp);
const fmtT = (ts: number | null | undefined) =>
  ts ? new Date(ts * 1000).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }) : "";

// One comparison row: today value (+time) · difference · yesterday value (+time).
function StatRow({
  label, unit, dp = 1, today, todayTs, yest, yestTs, noTime = false, noDiff = false,
}: {
  label: string; unit: string; dp?: number;
  today: number | null; todayTs?: number | null;
  yest: number | null; yestTs?: number | null;
  noTime?: boolean; noDiff?: boolean;
}) {
  const diff = today != null && yest != null ? today - yest : null;
  const diffCls = diff == null ? "" : diff > 0 ? "dy-up" : diff < 0 ? "dy-down" : "";
  return (
    <tr>
      <td className="dy-label">{label}</td>
      <td className="dy-val">{fmtN(today, dp)}<span className="dy-unit">{unit}</span></td>
      <td className="dy-at">{!noTime && todayTs ? fmtT(todayTs) : ""}</td>
      <td className={`dy-diff ${diffCls}`}>
        {noDiff || diff == null ? "" : `${diff > 0 ? "+" : ""}${diff.toFixed(dp)}`}
      </td>
      <td className="dy-val">{fmtN(yest, dp)}<span className="dy-unit">{unit}</span></td>
      <td className="dy-at">{!noTime && yestTs ? fmtT(yestTs) : ""}</td>
    </tr>
  );
}

function GroupHead({ title }: { title: string }) {
  return (
    <tr className="dy-group">
      <td colSpan={6}>{title}</td>
    </tr>
  );
}

export default function DayYest() {
  const [d, setD] = useState<DayCompare | null>(null);

  useEffect(() => {
    const poll = () => invoke<DayCompare>("day_compare").then(setD).catch(() => {});
    poll();
    const id = setInterval(poll, 30_000);
    return () => clearInterval(id);
  }, []);

  if (!d) return <div className="loading">Loading Today / Yesterday…</div>;

  const m = (name: string) => d.metrics.find(x => x.metric === name);
  const tempf = m("tempf"), dew = m("dewpointf"), hum = m("humidity");
  const baro = m("baromrelin"), spd = m("windspeedmph"), gust = m("windgustmph");
  const rate = m("rainratein"), rain = m("dailyrainin"), solar = m("solarradiation"), uv = m("uv");
  const range = (s?: DayStat) =>
    s && s.high.value != null && s.low.value != null ? s.high.value - s.low.value : null;

  const dirCell = (deg: number | null) =>
    deg == null ? "--" : `${Math.round(deg)}° ${cardinal(deg)}`;

  // "% of a clear day" (same calc as the Console): measured solar energy vs.
  // theoretical clear-sky energy over the matching window × sensor capture.
  const pctClear = (kwh: number | null, from: Date, to: Date) => {
    if (kwh == null) return null;
    const cs = clearSkyEnergyKwh(from, to);
    return cs > 0.05 ? (kwh / (cs * SOLAR_CLEAR_CAPTURE)) * 100 : null;
  };
  const mid0 = new Date(); mid0.setHours(0, 0, 0, 0);
  const mid1 = new Date(mid0.getTime() - 86_400_000);
  const pctToday = pctClear(d.solar_energy_today, mid0, new Date());
  const pctYest = pctClear(d.solar_energy_yest, mid1, mid0);

  return (
    <div className="dayyest">
      <h2 className="page-title">Today vs Yesterday</h2>
      <p className="page-sub">Since local midnight, compared with the full prior day.</p>

      <table className="dy-table">
        <tbody>
          <tr className="dy-head">
            <td></td>
            <td colSpan={2}>Today</td>
            <td>Diff</td>
            <td colSpan={2}>Yesterday</td>
          </tr>
          <GroupHead title="Temperature" />
          <StatRow label="High temperature" unit="°F"
            today={tempf?.today.high.value ?? null} todayTs={tempf?.today.high.ts}
            yest={tempf?.yesterday.high.value ?? null} yestTs={tempf?.yesterday.high.ts} />
          <StatRow label="Low temperature" unit="°F"
            today={tempf?.today.low.value ?? null} todayTs={tempf?.today.low.ts}
            yest={tempf?.yesterday.low.value ?? null} yestTs={tempf?.yesterday.low.ts} />
          <StatRow label="Temperature range" unit="°F" noTime
            today={range(tempf?.today)} yest={range(tempf?.yesterday)} />
          <StatRow label="Average temperature" unit="°F" noTime
            today={tempf?.today.avg ?? null} yest={tempf?.yesterday.avg ?? null} />

          <GroupHead title="Dew point" />
          <StatRow label="High dew point" unit="°F"
            today={dew?.today.high.value ?? null} todayTs={dew?.today.high.ts}
            yest={dew?.yesterday.high.value ?? null} yestTs={dew?.yesterday.high.ts} />
          <StatRow label="Low dew point" unit="°F"
            today={dew?.today.low.value ?? null} todayTs={dew?.today.low.ts}
            yest={dew?.yesterday.low.value ?? null} yestTs={dew?.yesterday.low.ts} />

          <GroupHead title="Humidity" />
          <StatRow label="High humidity" unit="%" dp={0}
            today={hum?.today.high.value ?? null} todayTs={hum?.today.high.ts}
            yest={hum?.yesterday.high.value ?? null} yestTs={hum?.yesterday.high.ts} />
          <StatRow label="Low humidity" unit="%" dp={0}
            today={hum?.today.low.value ?? null} todayTs={hum?.today.low.ts}
            yest={hum?.yesterday.low.value ?? null} yestTs={hum?.yesterday.low.ts} />

          <GroupHead title="Wind" />
          <StatRow label="Highest gust" unit={WIND_UNIT}
            today={toKt(gust?.today.high.value)} todayTs={gust?.today.high.ts}
            yest={toKt(gust?.yesterday.high.value)} yestTs={gust?.yesterday.high.ts} />
          <StatRow label="Highest sustained" unit={WIND_UNIT}
            today={toKt(spd?.today.high.value)} todayTs={spd?.today.high.ts}
            yest={toKt(spd?.yesterday.high.value)} yestTs={spd?.yesterday.high.ts} />
          <StatRow label="Wind run" unit={WIND_RUN_UNIT} dp={0} noTime
            today={toKt(d.wind_run_today)} yest={toKt(d.wind_run_yest)} />
          <tr>
            <td className="dy-label">Dominant direction</td>
            <td className="dy-val">{dirCell(d.dom_dir_today)}</td>
            <td className="dy-at"></td><td className="dy-diff"></td>
            <td className="dy-val">{dirCell(d.dom_dir_yest)}</td>
            <td className="dy-at"></td>
          </tr>

          <GroupHead title="Pressure" />
          <StatRow label="High pressure" unit="inHg" dp={2}
            today={baro?.today.high.value ?? null} todayTs={baro?.today.high.ts}
            yest={baro?.yesterday.high.value ?? null} yestTs={baro?.yesterday.high.ts} />
          <StatRow label="Low pressure" unit="inHg" dp={2}
            today={baro?.today.low.value ?? null} todayTs={baro?.today.low.ts}
            yest={baro?.yesterday.low.value ?? null} yestTs={baro?.yesterday.low.ts} />

          <GroupHead title="Rain" />
          <StatRow label="Rainfall total" unit="in" dp={2} noTime
            today={rain?.today.high.value ?? null} yest={rain?.yesterday.high.value ?? null} />
          <StatRow label="Max rain rate" unit="in/hr" dp={2}
            today={rate?.today.high.value ?? null} todayTs={rate?.today.high.ts}
            yest={rate?.yesterday.high.value ?? null} yestTs={rate?.yesterday.high.ts} />

          <GroupHead title="Solar / UV" />
          <StatRow label="High solar radiation" unit="W/m²" dp={0}
            today={solar?.today.high.value ?? null} todayTs={solar?.today.high.ts}
            yest={solar?.yesterday.high.value ?? null} yestTs={solar?.yesterday.high.ts} />
          <StatRow label="High UV index" unit="" dp={0}
            today={uv?.today.high.value ?? null} todayTs={uv?.today.high.ts}
            yest={uv?.yesterday.high.value ?? null} yestTs={uv?.yesterday.high.ts} />
          <StatRow label="Solar energy" unit="kWh/m²" dp={2} noTime
            today={d.solar_energy_today} yest={d.solar_energy_yest} />
          <StatRow label="Sun vs clear day" unit="%" dp={0} noTime
            today={pctToday} yest={pctYest} />
        </tbody>
      </table>
    </div>
  );
}
