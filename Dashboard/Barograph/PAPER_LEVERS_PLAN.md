# Barograph: paper-change levers, work plan

Drafted 2026-11-09 for Michael to check against, and built the same day (steps 1 to 5 and 7; step 6, the second pen, is left for later).

## What it does

A brass selector on the instrument has three positions: **Pressure**, **Temperature**, **Humidity**. Move it and the instrument changes its paper:

1. The pen lifts off the paper (the lifter foot swings, as it does now when you look back).
2. The drum turns one quick revolution. As it does, the new chart wraps on from the clip, so by the time the seam has gone past the pen, the drum carries the new sheet.
3. The pen swings to the new reading and drops back onto the paper.

The whole change takes about 3 seconds. Everything that works on the pressure chart today works on each paper: the live trace, dragging back up to four weeks, the pen lifting while you look back, and homing after 2 minutes.

## The three papers

| Paper | Archive metric | Scale | Ink | Notes |
|---|---|---|---|---|
| Pressure | `baromrelin` | 29.5 to 30.5 inHg (as now) | blue | unchanged |
| Temperature | `tempf` (outside) | 50 to 90 °F, widened in 10 ° steps only for a week that goes beyond | red | the dial thermometer stays on inside temperature |
| Humidity / dew point | `humidity`, `dewpointf` | 0 to 100 % (left); dew point on the right, 30 to 70 °F, widened the same way | violet, green | one pen (humidity); dew point printed as a finer second trace |

The chart artwork keeps the same look as the pressure chart: week of days across the top, curved time lines (the pen's arc), and the printed scale at intervals. Each paper gets its own title and scale figures.

## Decisions (Michael, 2026-11-09)

1. **Selector: A, the quadrant lever** (C, a slide, is the fallback if A will not fit). It lies flat on the right side of the satin movement plate, left of the zero knob, and is read from the instrument's right side: the arc's two ends sit at (or nearly at) the plate's right edge, its apex points toward the drum, and the lever pivots at the right edge and sweeps across it. BAR · THERM · HYGR are engraved to read from the right. To work it, you turn the instrument (the view swings round to the right), so the orbit's side limit opens up beyond today's 70 degrees. Clicking a position, or the lever itself, moves it; the status line keeps buttons for the keyboard.
2. **Temperature scale:** 50 to 90 °F, which holds nearly all of La Jolla's weeks; a week that goes beyond widens in 10 ° steps. Not authentic, and that is fine.
3. **Humidity and dew point:** (a), one pen for now, with dew point as a printed second trace.
4. **Linkage:** the whole linkage moves with the pen on every paper. Small fictions are fine.
5. **Remember the paper:** yes, the page opens on the last paper chosen.

## Work, in order

Each step ends with something checked before the next starts.

1. **Charts for any quantity** (`chart.ts`): a chart description (metric, scale, ink, title, scale figures), so one `ChartSheet` draws any paper. Check: pressure looks exactly as today.
2. **Data and drum** (`drum.ts`, `Barograph.tsx`): fetch by the chosen paper's metric; the drum, look-back and homing work per paper. Temporary buttons on the status line to switch papers. Check: each paper in the dev harness with made-up readings, then the Monitor with real data (Michael).
3. **The pen on each scale** (`scene.ts`): pen position from the chosen paper's scale; the needle stays on pressure. Check: pen on the number for each paper.
4. **The selector** (Blender, `build_barograph.py`; orbit limits in `scene.ts`): model the lever and its engraved quadrant, open the view's side limit so the quadrant can be seen square on, mark the handle as moving (no baked shadow), re-bake and re-export. Click or drag the handle to change paper; the status line buttons stay as the keyboard way in. Check: hero and close renders, then on the page.
5. **The change itself** (`drum.ts`, `chart.ts`, `scene.ts`): pen lifts, one-turn spin with the new sheet wrapping on at the clip, pen lands. Check: watch it on the dev page, capture frames.
6. **Second pen** (only if decision 3 is (b)).
7. **Finish**: README and PAGES_SPEC, build, deploy, Michael checks on real data, commit.

## Risks

- The pen sits 82 hours into the week as built; the turn-and-wrap must start and end there so the trace lines up.
- Temperature swings faster than pressure; the trace will be busier. Ten-minute averages, as now, should keep it readable.
- One more re-bake (step 4) of several minutes.
