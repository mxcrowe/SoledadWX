// Stand-alone harness for the barograph (barograph.html, dev server only).
// It runs the scene and the live drum in a plain browser with no Tauri
// backend, inking made-up readings in place of the Archive.

import { createBarograph, type Barograph } from "./scene";
import { ChartSheet, type TracePoint } from "./chart";
import { createLiveDrum, type LiveDrum } from "./drum";

declare global {
  interface Window {
    barograph?: Barograph;
    barographDrum?: LiveDrum;
  }
}

/** Plausible sea-level pressure: a slow swing plus the twice-daily tide. */
async function madeUpWeek(startTs: number, endTs: number): Promise<TracePoint[]> {
  const points: TracePoint[] = [];
  const now = Date.now() / 1000;
  for (let t = startTs; t < Math.min(endTs, now); t += 600) {
    const h = t / 3600;
    const p = 29.98 + 0.14 * Math.sin((2 * Math.PI * h) / 110) + 0.05 * Math.sin((2 * Math.PI * h) / 31 + 1) +
      0.035 * Math.cos((2 * Math.PI * (h - 10)) / 12);
    points.push({ t, p });
  }
  return points;
}

const canvas = document.querySelector("canvas")!;
const sheet = new ChartSheet();
let drum: LiveDrum | undefined;
createBarograph(canvas, {
  chart: sheet.texture,
  onDrumDrag: (hours) => drum?.drag(hours),
  onDrumRelease: () => drum?.release(),
}).then(
  (handle) => {
    window.barograph = handle;
    handle.setTemperature(71);
    drum = createLiveDrum(handle, sheet, madeUpWeek, (s) => {
      document.title = `Barograph: ${s.live ? "now" : "back"} ${s.at.toISOString()} ${s.pressure?.toFixed(3)}`;
    });
    window.barographDrum = drum;
  },
  (err) => {
    document.title = "Barograph: failed";
    document.body.append(String(err));
  },
);
