// Stand-alone harness for the barograph (barograph.html, dev server only).
// It runs the scene and the live drum in a plain browser with no Tauri
// backend, inking made-up readings in place of the Archive.

import { createBarograph, type Barograph } from "./scene";
import { ChartSheet } from "./chart";
import { createLiveDrum, type LiveDrum } from "./drum";
import { PAPER_ORDER, type TracePoint } from "./papers";

declare global {
  interface Window {
    barograph?: Barograph;
    barographDrum?: LiveDrum;
    barographSheet?: ChartSheet;
  }
}

const wave = (hours: number, period: number, shift = 0) => Math.sin((2 * Math.PI * (hours - shift)) / period);

/** Plausible readings for each metric: slow swings plus a daily rhythm. */
const MADE_UP: Record<string, (hours: number) => number> = {
  baromrelin: (h) => 29.98 + 0.14 * wave(h, 110) + 0.05 * wave(h, 31, -5) + 0.035 * wave(h, 12, 7),
  tempf: (h) => 66 + 8 * wave(h, 24, 17) + 4 * wave(h, 130),
  humidity: (h) => 68 - 22 * wave(h, 24, 17) + 8 * wave(h, 90),
  dewpointf: (h) => 54 + 5 * wave(h, 100) + 1.5 * wave(h, 24, 20),
};

async function madeUpSeries(metric: string, startTs: number, endTs: number): Promise<TracePoint[]> {
  const points: TracePoint[] = [];
  const now = Date.now() / 1000;
  for (let t = startTs; t < Math.min(endTs, now); t += 600) points.push({ t, v: MADE_UP[metric](t / 3600) });
  return points;
}

// A hidden tab gets no animation frames. "?timers" runs the animations off a
// timer instead, so they can be tested and captured there.
if (new URLSearchParams(location.search).has("timers")) {
  window.requestAnimationFrame = (step) => window.setTimeout(() => step(performance.now()), 16);
}

const canvas = document.querySelector("canvas")!;
const sheet = new ChartSheet();
let drum: LiveDrum | undefined;
createBarograph(canvas, {
  chart: sheet.texture,
  onDrumDrag: (hours) => drum?.drag(hours),
  onDrumRelease: () => drum?.release(),
  onSelect: (position) => drum?.setPaper(PAPER_ORDER[position]),
}).then(
  (handle) => {
    window.barograph = handle;
    window.barographSheet = sheet;
    handle.setTemperature(71);
    drum = createLiveDrum(handle, sheet, madeUpSeries, (s) => {
      document.title = `Barograph: ${s.paper} ${s.changing ? "changing" : s.live ? "now" : "back"} ${s.value?.toFixed(2)}`;
    });
    window.barographDrum = drum;
  },
  (err) => {
    document.title = "Barograph: failed";
    document.body.append(String(err));
  },
);
