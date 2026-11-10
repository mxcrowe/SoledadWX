// The barograph's chart papers, painted live on a canvas from Archive data.
//
// One sheet is one calendar week, Monday 00:00 to Sunday 24:00 local time, as
// on a real drum. The instrument takes three papers: pressure, temperature,
// and humidity with dew point. Each has its own printed colour, ruling and
// ink. The geometry matches the drum in Dashboard/Barograph/model
// (make_textures.py, build_barograph.py).

import * as THREE from "three";
import { PAPERS, fraction, isMultiple, type Paper, type Scale, type Trace, type TracePoint } from "./papers";

// Shared with the model (millimetres).
const PAPER_MM = { w: 292.8, h: 97.0 }; // one turn of the drum, and the paper's height
const GRID_TOP_MM = 5.0;
const GRID_MM = 90.0;
const PEN_ARM_MM = 173.0; // the pen swings on this radius, so time lines are arcs

export const WEEK_HOURS = 168;

const WIDTH = 4096;
const PX = WIDTH / PAPER_MM.w; // pixels per millimetre
const HEIGHT = Math.round(PAPER_MM.h * PX);
const Y_TOP = GRID_TOP_MM * PX;
const GRID_H = GRID_MM * PX;
const Y_MID = Y_TOP + GRID_H / 2;

const PAPER_COLOUR = "rgb(243,235,214)";
const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

/** A week's readings for one paper. */
export interface SheetData {
  pen: TracePoint[];
  second?: TracePoint[];
}

/** The scales printed on one sheet. */
export interface SheetScales {
  pen: Scale;
  second?: Scale;
}

/** The scale a trace needs for these readings: its base, widened if they go beyond it. */
function fit(trace: Trace, points: TracePoint[]): Scale {
  if (!trace.widen || !points.length) return trace.base;
  let min = Infinity;
  let max = -Infinity;
  for (const pt of points) {
    if (pt.v < min) min = pt.v;
    if (pt.v > max) max = pt.v;
  }
  return {
    lo: Math.min(trace.base.lo, Math.floor(min / trace.widen) * trace.widen),
    hi: Math.max(trace.base.hi, Math.ceil(max / trace.widen) * trace.widen),
  };
}

/** The canvas row for a value on a scale. */
function yOf(value: number, scale: Scale): number {
  return Y_TOP + (1 - fraction(value, scale)) * GRID_H;
}

/** The canvas column for an hour of the week, bent along the pen's arc. */
function xOf(hours: number, y: number): number {
  const h = (y - Y_MID) / PX;
  return (hours / WEEK_HOURS) * WIDTH + (PEN_ARM_MM - Math.sqrt(PEN_ARM_MM * PEN_ARM_MM - h * h)) * PX;
}

/** Monday 00:00 local time of the week holding `when`. */
export function weekStart(when: Date): Date {
  const d = new Date(when.getFullYear(), when.getMonth(), when.getDate());
  d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
  return d;
}

/** A trace's figures down one time line, each on a patch of bare paper. */
function drawFigures(g: CanvasRenderingContext2D, trace: Trace, scale: Scale, hours: number, colour: string): void {
  const { step, text, bold } = trace.figures;
  const count = Math.round((scale.hi - scale.lo) / step);
  g.textBaseline = "middle";
  for (let i = 1; i < count; i++) {
    const value = scale.lo + i * step;
    const label = text(value);
    g.font = bold(value) ? `bold ${Math.round(3.4 * PX)}px Georgia, serif` : `${Math.round(2.2 * PX)}px Georgia, serif`;
    const y = yOf(value, scale);
    const x = xOf(hours, y);
    const w = g.measureText(label).width;
    g.fillStyle = PAPER_COLOUR;
    g.fillRect(x - w / 2 - 4, y - 1.4 * PX, w + 8, 2.8 * PX);
    g.fillStyle = colour;
    g.fillText(label, x, y);
  }
  g.textBaseline = "alphabetic";
}

/** The printed sheet for a paper, before any ink. */
function printSheet(paper: Paper, scales: SheetScales): HTMLCanvasElement {
  const canvas = document.createElement("canvas");
  canvas.width = WIDTH;
  canvas.height = HEIGHT;
  const g = canvas.getContext("2d")!;
  g.fillStyle = PAPER_COLOUR;
  g.fillRect(0, 0, WIDTH, HEIGHT);
  const { line, bold } = paper.print;

  // Ruling across the sheet. A much widened scale is ruled half as closely.
  const span = scales.pen.hi - scales.pen.lo;
  const fine = span / paper.ruling.line > 90 ? paper.ruling.line * 2 : paper.ruling.line;
  const steps = Math.round(span / fine);
  for (let i = 0; i <= steps; i++) {
    const value = scales.pen.lo + i * fine;
    const strong = isMultiple(value, paper.ruling.strong) || i === 0 || i === steps;
    const mid = isMultiple(value, paper.ruling.mid);
    const y = Y_TOP + (1 - i / steps) * GRID_H;
    g.strokeStyle = mid || strong ? bold : line;
    g.lineWidth = strong ? 4.6 : mid ? 3.2 : 1.6;
    g.beginPath();
    g.moveTo(0, y);
    g.lineTo(WIDTH, y);
    g.stroke();
  }

  // Time lines every 2 hours, as arcs; heavier at noon and midnight.
  for (let h = 0; h <= WEEK_HOURS; h += 2) {
    g.strokeStyle = h % 12 === 0 ? bold : line;
    g.lineWidth = h % 24 === 0 ? 4.6 : h % 12 === 0 ? 3.2 : 1.6;
    g.beginPath();
    for (let k = 0; k <= 40; k++) {
      const y = Y_TOP + (GRID_H * k) / 40;
      if (k === 0) g.moveTo(xOf(h, y), y);
      else g.lineTo(xOf(h, y), y);
    }
    g.stroke();
  }

  // Day names over noon, hours along the top, the pen's figures down each noon
  // line, the legend along the bottom edge.
  g.textAlign = "center";
  g.textBaseline = "alphabetic";
  const small = `${Math.round(1.25 * PX)}px Georgia, serif`;
  DAYS.forEach((name, day) => {
    g.fillStyle = bold;
    g.font = `italic bold ${Math.round(3.3 * PX)}px Georgia, serif`;
    g.fillText(name, xOf(day * 24 + 12, Y_TOP), Y_TOP - 0.6 * PX);
    g.fillStyle = line;
    g.font = `${Math.round(1.7 * PX)}px Georgia, serif`;
    for (const [h, label] of [[2, "2"], [4, "4"], [20, "8"], [22, "10"]] as const) {
      g.fillText(label, xOf(day * 24 + h, Y_TOP), Y_TOP - 0.5 * PX);
    }
    drawFigures(g, paper.pen, scales.pen, day * 24 + 12, bold);
    g.fillStyle = bold;
    g.font = small;
    g.fillText(paper.legend, xOf(day * 24 + 12, Y_TOP + GRID_H), HEIGHT - 0.45 * PX);
    // The second trace's figures and legend stand at midnight, in its own ink.
    // The first midnight is the seam, under the clip.
    if (paper.second && scales.second && day > 0) {
      drawFigures(g, paper.second, scales.second, day * 24, paper.second.ink);
      g.fillStyle = paper.second.ink;
      g.font = small;
      const legend = `${paper.second.name.toUpperCase()}, ${paper.second.unit}`;
      g.fillText(legend, xOf(day * 24, Y_TOP + GRID_H), HEIGHT - 0.45 * PX);
    }
  });
  return canvas;
}

/** Ink one trace. A gap of more than `maxGapSecs` in the readings lifts the pen. */
function inkTrace(
  g: CanvasRenderingContext2D,
  trace: Trace,
  scale: Scale,
  points: TracePoint[],
  t0: number,
  maxGapSecs: number,
): void {
  g.strokeStyle = trace.ink;
  g.lineWidth = trace.nib * PX;
  g.lineJoin = "round";
  g.lineCap = "round";
  g.beginPath();
  let last: TracePoint | null = null;
  for (const pt of points) {
    const hours = (pt.t - t0) / 3600;
    if (hours < 0 || hours > WEEK_HOURS) continue;
    const y = yOf(pt.v, scale);
    const x = xOf(hours, y);
    if (last && pt.t - last.t <= maxGapSecs) g.lineTo(x, y);
    else g.moveTo(x, y);
    last = pt;
  }
  g.stroke();
}

function makeTexture(canvas: HTMLCanvasElement): THREE.CanvasTexture {
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.flipY = false; // glTF texture coordinates
  texture.wrapS = THREE.RepeatWrapping;
  texture.anisotropy = 16;
  return texture;
}

/** The chart on the drum: a printed sheet plus a week's ink, as a live texture. */
export class ChartSheet {
  readonly texture: THREE.CanvasTexture;
  /** The scales on the sheet as last drawn. */
  scales: SheetScales = { pen: PAPERS.pressure.pen.base };
  private readonly canvas = document.createElement("canvas");
  private printed: { key: string; canvas: HTMLCanvasElement } | null = null;
  private incoming: { canvas: HTMLCanvasElement; texture: THREE.CanvasTexture; scales: SheetScales } | null = null;

  constructor() {
    this.canvas.width = WIDTH;
    this.canvas.height = HEIGHT;
    this.texture = makeTexture(this.canvas);
    this.draw(PAPERS.pressure, weekStart(new Date()), { pen: [] });
  }

  /** Print a fresh sheet of `paper` for the week starting `monday` and ink `data` on it. */
  draw(paper: Paper, monday: Date, data: SheetData, maxGapSecs = 1800): SheetScales {
    this.scales = this.paint(this.canvas, paper, monday, data, maxGapSecs);
    this.texture.needsUpdate = true;
    return this.scales;
  }

  /**
   * Draw a sheet to one side, ready to wrap onto the drum over the one that is
   * there (the scene's setIncoming). `adopt` then makes it the sheet.
   */
  prepare(paper: Paper, monday: Date, data: SheetData, maxGapSecs = 1800): { texture: THREE.Texture; scales: SheetScales } {
    this.discardIncoming();
    const canvas = document.createElement("canvas");
    canvas.width = WIDTH;
    canvas.height = HEIGHT;
    const scales = this.paint(canvas, paper, monday, data, maxGapSecs);
    this.incoming = { canvas, texture: makeTexture(canvas), scales };
    return this.incoming;
  }

  /** The sheet drawn by `prepare` becomes the sheet on the drum. */
  adopt(): void {
    if (!this.incoming) return;
    this.canvas.getContext("2d")!.drawImage(this.incoming.canvas, 0, 0);
    this.scales = this.incoming.scales;
    this.texture.needsUpdate = true;
    this.discardIncoming();
  }

  dispose(): void {
    this.discardIncoming();
    this.texture.dispose();
  }

  private discardIncoming(): void {
    if (!this.incoming) return;
    this.incoming.texture.dispose();
    this.incoming.canvas.width = 0; // give the pixels back now
    this.incoming = null;
  }

  private paint(canvas: HTMLCanvasElement, paper: Paper, monday: Date, data: SheetData, maxGapSecs: number): SheetScales {
    const scales: SheetScales = { pen: fit(paper.pen, data.pen) };
    if (paper.second) scales.second = fit(paper.second, data.second ?? []);
    // Printing is the slow part, so the last printed sheet is kept for re-inking.
    const key = `${paper.id}:${JSON.stringify(scales)}`;
    if (this.printed?.key !== key) this.printed = { key, canvas: printSheet(paper, scales) };
    const g = canvas.getContext("2d")!;
    g.drawImage(this.printed.canvas, 0, 0);
    const t0 = monday.getTime() / 1000;
    if (paper.second && scales.second) inkTrace(g, paper.second, scales.second, data.second ?? [], t0, maxGapSecs);
    inkTrace(g, paper.pen, scales.pen, data.pen, t0, maxGapSecs);
    return scales;
  }
}
