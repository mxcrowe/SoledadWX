// What the drum shows, and when: the live clockwork of the Barograph page.
//
// The pen sits at "now" and writes the week's trace. Dragging the drum turns
// it back up to MAX_BACK_WEEKS; the pen lifts off the paper while you look at
// the past, and the drum turns itself home after a quiet spell. Data comes
// through `fetchWeek`, so the page can use the Archive and the dev harness can
// use made-up readings.

import { ChartSheet, weekStart, WEEK_HOURS, type TracePoint } from "./chart";
import type { Barograph } from "./scene";

const MAX_BACK_WEEKS = 4; // the drum shows recent weeks only
const REFRESH_MS = 60_000; // new readings for the current week
const HOME_AFTER_MS = 120_000; // turn back to now after this long untouched
const HOME_HOURS_PER_SEC = 24 * 7; // how fast it turns home (a week in a second)
const LIFT_WHEN_BACK_HOURS = 0.25;

export type FetchWeek = (startTs: number, endTs: number) => Promise<TracePoint[]>;

export interface DrumStatus {
  /** True when the pen is at now and writing. */
  live: boolean;
  /** The moment under the pen. */
  at: Date;
  /** The latest pressure, inHg, if any has arrived. */
  pressure: number | null;
}

export interface LiveDrum {
  /** Drag hook for the scene: positive hours turn forward in time. */
  drag(hours: number): void;
  /** Release hook for the scene. */
  release(): void;
  /** Turn straight back to now. */
  home(): void;
  dispose(): void;
}

export function createLiveDrum(
  scene: Barograph,
  sheet: ChartSheet,
  fetchWeek: FetchWeek,
  onStatus: (status: DrumStatus) => void,
): LiveDrum {
  const weeks = new Map<number, TracePoint[]>(); // Monday (ms) -> readings
  const pending = new Set<number>();
  let back = 0; // hours behind now
  let drawn = ""; // which sheet is on the drum
  let latest: number | null = null;
  let homeTimer: number | undefined;
  let homeFrame = 0;
  let gone = false;

  const load = async (monday: Date, force = false) => {
    const key = monday.getTime();
    if (pending.has(key) || (!force && weeks.has(key))) return;
    pending.add(key);
    try {
      const start = key / 1000;
      const points = await fetchWeek(start, start + WEEK_HOURS * 3600);
      if (gone) return;
      weeks.set(key, points);
      const isCurrent = key === weekStart(new Date()).getTime();
      if (isCurrent && points.length) latest = points[points.length - 1].p;
      if (isCurrent && !points.length && latest === null) {
        // Early on a Monday: the newest reading is on last week's sheet.
        const prev = new Date(monday);
        prev.setDate(prev.getDate() - 7);
        void load(prev);
      }
      if (latest === null && points.length && key < weekStart(new Date()).getTime()) {
        latest = points[points.length - 1].p;
      }
      show();
    } catch (err) {
      console.error("barograph: could not read the Archive", err);
    } finally {
      pending.delete(key);
    }
  };

  const show = () => {
    const at = new Date(Date.now() - back * 3600_000);
    const monday = weekStart(at);
    const key = monday.getTime();
    const points = weeks.get(key);
    if (points === undefined) void load(monday);
    const stamp = `${key}:${points?.length ?? -1}:${points?.[points.length - 1]?.t ?? 0}`;
    if (stamp !== drawn) {
      sheet.draw(monday, points ?? []);
      drawn = stamp;
      scene.invalidate();
    }
    scene.setPenTime((at.getTime() - key) / 3600_000);
    if (latest !== null) scene.setPressure(latest);
    scene.setPenLifted(back > LIFT_WHEN_BACK_HOURS);
    onStatus({ live: back <= LIFT_WHEN_BACK_HOURS, at, pressure: latest });
  };

  const stopHoming = () => {
    cancelAnimationFrame(homeFrame);
    homeFrame = 0;
    window.clearTimeout(homeTimer);
  };

  const home = () => {
    stopHoming();
    let last = performance.now();
    const step = (now: number) => {
      back = Math.max(0, back - (HOME_HOURS_PER_SEC * (now - last)) / 1000);
      last = now;
      show();
      homeFrame = back > 0 ? requestAnimationFrame(step) : 0;
    };
    homeFrame = requestAnimationFrame(step);
  };

  // Keep the current week fresh, and the pen moving with the clock.
  const refresh = window.setInterval(() => {
    void load(weekStart(new Date()), true);
    show();
  }, REFRESH_MS);
  void load(weekStart(new Date()));
  show();

  return {
    drag(hours) {
      stopHoming();
      back = Math.min(MAX_BACK_WEEKS * WEEK_HOURS, Math.max(0, back - hours));
      show();
    },
    release() {
      window.clearTimeout(homeTimer);
      if (back > 0) homeTimer = window.setTimeout(home, HOME_AFTER_MS);
    },
    home,
    dispose() {
      gone = true;
      stopHoming();
      window.clearInterval(refresh);
    },
  };
}
