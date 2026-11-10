// What the drum shows, and when: the live clockwork of the Barograph page.
//
// The pen sits at "now" and writes the week's trace. Dragging the drum turns
// it back up to MAX_BACK_WEEKS; the pen lifts off the paper while you look at
// the past, and the drum turns itself home after a quiet spell. The drum takes
// three papers (chart.ts); changing one lifts the pen, spins the drum once
// while the new sheet wraps on behind the clip, and sets the pen down again.
// Data comes through `fetchSeries`, so the page can use the Archive and the dev
// harness can use made-up readings.

import { WEEK_HOURS, weekStart, type ChartSheet, type SheetData } from "./chart";
import { PAPERS, PAPER_ORDER, fraction, type Paper, type PaperId, type Trace, type TracePoint } from "./papers";
import type { Barograph } from "./scene";

const MAX_BACK_WEEKS = 4; // the drum shows recent weeks only
const REFRESH_MS = 60_000; // new readings for the current week
const HOME_AFTER_MS = 120_000; // turn back to now after this long untouched
const HOME_HOURS_PER_SEC = 24 * 7; // how fast it turns home (a week in a second)
const LIFT_WHEN_BACK_HOURS = 0.25;
const PEN_LIFT_MS = 450; // time for the pen to clear the paper before the drum spins
const SPIN_MS = 1900; // one turn of the drum while the new sheet wraps on
const LOAD_WAIT_MS = 2000; // spin with a blank sheet if the readings take longer than this

/** A week of one Archive metric, in 10-minute steps. */
export type FetchSeries = (metric: string, startTs: number, endTs: number) => Promise<TracePoint[]>;

export interface DrumStatus {
  /** True when the pen is at now and writing. */
  live: boolean;
  /** The moment under the pen. */
  at: Date;
  /** The paper on the drum, or the one going on. */
  paper: PaperId;
  /** True while one paper is being changed for another. */
  changing: boolean;
  /** The latest reading of what the pen writes, if any has arrived. */
  value: number | null;
  /** The latest reading of the paper's second trace, if it has one. */
  second: number | null;
}

export interface LiveDrum {
  /** Drag hook for the scene: positive hours turn forward in time. */
  drag(hours: number): void;
  /** Release hook for the scene. */
  release(): void;
  /** Turn straight back to now. */
  home(): void;
  /** Change the paper on the drum. Asked for mid-change, it follows on. */
  setPaper(id: PaperId): void;
  dispose(): void;
}

const wait = (ms: number) => new Promise<void>((done) => window.setTimeout(done, ms));
const easeInOut = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

export function createLiveDrum(
  scene: Barograph,
  sheet: ChartSheet,
  fetchSeries: FetchSeries,
  onStatus: (status: DrumStatus) => void,
  startPaper: PaperId = "pressure",
): LiveDrum {
  const weeks = new Map<string, SheetData>(); // paper and Monday -> readings
  const loading = new Map<string, Promise<void>>();
  const latest = new Map<string, number>(); // metric -> newest reading
  let paper = PAPERS[startPaper];
  let back = 0; // hours behind now
  let drawn = ""; // which sheet is on the drum
  let penAt = 0.5; // where the pen stands, up the grid
  let changing = false;
  let queued: PaperId | null = null;
  let homeTimer: number | undefined;
  let homeFrame = 0;
  let changeFrame = 0;
  let gone = false;

  const keyOf = (p: Paper, monday: Date) => `${p.id}:${monday.getTime()}`;
  const thisMonday = () => weekStart(new Date());

  const note = (trace: Trace, points: TracePoint[], current: boolean) => {
    if (points.length && (current || !latest.has(trace.metric))) latest.set(trace.metric, points[points.length - 1].v);
  };

  /** Read one paper's week from the Archive, once; `force` reads it afresh. */
  const load = (p: Paper, monday: Date, force = false): Promise<void> => {
    const key = keyOf(p, monday);
    const running = loading.get(key);
    if (running) return running;
    if (!force && weeks.has(key)) return Promise.resolve();
    const start = monday.getTime() / 1000;
    const end = start + WEEK_HOURS * 3600;
    const run = (async () => {
      try {
        await null; // so `loading` holds this run before anything here can fail
        const [pen, second] = await Promise.all([
          fetchSeries(p.pen.metric, start, end),
          p.second ? fetchSeries(p.second.metric, start, end) : undefined,
        ]);
        if (gone) return;
        weeks.set(key, { pen, second });
        const current = monday.getTime() === thisMonday().getTime();
        note(p.pen, pen, current);
        if (p.second && second) note(p.second, second, current);
        if (current && !pen.length && !latest.has(p.pen.metric)) {
          // Early on a Monday: the newest reading is on last week's sheet.
          const prev = new Date(monday);
          prev.setDate(prev.getDate() - 7);
          void load(p, prev);
        }
        show();
      } catch (err) {
        console.error("barograph: could not read the Archive", err);
      } finally {
        loading.delete(key);
      }
    })();
    loading.set(key, run);
    return run;
  };

  const report = (shown: Paper) =>
    onStatus({
      live: !changing && back <= LIFT_WHEN_BACK_HOURS,
      at: new Date(Date.now() - back * 3600_000),
      paper: shown.id,
      changing,
      value: latest.get(shown.pen.metric) ?? null,
      second: shown.second ? (latest.get(shown.second.metric) ?? null) : null,
    });

  const show = () => {
    if (changing) return;
    const at = new Date(Date.now() - back * 3600_000);
    const monday = weekStart(at);
    const key = keyOf(paper, monday);
    const data = weeks.get(key);
    if (!data) void load(paper, monday);
    const last = data?.pen[data.pen.length - 1];
    const stamp = `${key}:${data?.pen.length ?? -1}:${last?.t ?? 0}:${data?.second?.length ?? 0}`;
    if (stamp !== drawn) {
      sheet.draw(paper, monday, data ?? { pen: [] });
      drawn = stamp;
      scene.invalidate();
    }
    scene.setPenTime((at.getTime() - monday.getTime()) / 3600_000);
    const value = latest.get(paper.pen.metric);
    if (value !== undefined) {
      penAt = fraction(value, sheet.scales.pen);
      scene.setPen(penAt);
    }
    // The dial is a barometer whatever paper is on the drum.
    const inHg = latest.get(PAPERS.pressure.pen.metric);
    if (inHg !== undefined) scene.setNeedle(inHg);
    scene.setPenLifted(back > LIFT_WHEN_BACK_HOURS);
    report(paper);
  };

  const stopHoming = () => {
    cancelAnimationFrame(homeFrame);
    homeFrame = 0;
    window.clearTimeout(homeTimer);
  };

  const home = () => {
    if (changing) return;
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

  /** Take the paper off and put `next` on, at the same moment under the pen. */
  const change = async (next: Paper) => {
    changing = true;
    stopHoming();
    scene.setSelector(PAPER_ORDER.indexOf(next.id));
    scene.setPenLifted(true);
    report(next);
    const at = new Date(Date.now() - back * 3600_000);
    const monday = weekStart(at);
    const hours = (at.getTime() - monday.getTime()) / 3600_000;
    const read = Promise.all([load(next, monday), load(next, thisMonday())]);
    await Promise.all([wait(PEN_LIFT_MS), Promise.race([read, wait(LOAD_WAIT_MS)])]);
    if (gone) return;

    const incoming = sheet.prepare(next, monday, weeks.get(keyOf(next, monday)) ?? { pen: [] });
    scene.setIncoming(incoming.texture);
    const from = penAt;
    const value = latest.get(next.pen.metric);
    const to = value === undefined ? from : fraction(value, incoming.scales.pen);
    const began = performance.now();
    await new Promise<void>((done) => {
      const step = (now: number) => {
        const e = easeInOut(Math.min(1, (now - began) / SPIN_MS));
        scene.setPenTime(hours + WEEK_HOURS * e); // one whole turn, back to where it was
        scene.setWrap(e); // the new sheet follows the clip round
        scene.setPen(from + (to - from) * e);
        if (now - began < SPIN_MS) changeFrame = requestAnimationFrame(step);
        else done();
      };
      changeFrame = requestAnimationFrame(step);
    });
    if (gone) return;

    sheet.adopt();
    scene.setIncoming(null);
    scene.setInk(next.pen.ink);
    paper = next;
    penAt = to;
    drawn = "";
    changing = false;
    show();
    if (back > 0) homeTimer = window.setTimeout(home, HOME_AFTER_MS);
    const then = queued;
    queued = null;
    if (then && then !== paper.id) void change(PAPERS[then]);
  };

  // Keep the current week fresh, and the pen moving with the clock.
  const refresh = window.setInterval(() => {
    void load(paper, thisMonday(), true);
    if (paper.id !== "pressure") void load(PAPERS.pressure, thisMonday(), true);
    show();
  }, REFRESH_MS);
  scene.setSelector(PAPER_ORDER.indexOf(paper.id));
  scene.setInk(paper.pen.ink);
  void load(paper, thisMonday());
  if (paper.id !== "pressure") void load(PAPERS.pressure, thisMonday());
  show();

  return {
    drag(hours) {
      if (changing) return;
      stopHoming();
      back = Math.min(MAX_BACK_WEEKS * WEEK_HOURS, Math.max(0, back - hours));
      show();
    },
    release() {
      window.clearTimeout(homeTimer);
      if (back > 0) homeTimer = window.setTimeout(home, HOME_AFTER_MS);
    },
    home,
    setPaper(id) {
      if (changing) queued = id;
      else if (id !== paper.id) void change(PAPERS[id]);
    },
    dispose() {
      gone = true;
      stopHoming();
      cancelAnimationFrame(changeFrame);
      window.clearInterval(refresh);
    },
  };
}
