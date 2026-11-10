// The barograph's chart paper, painted live on a canvas from Archive data.
//
// One sheet is one calendar week, Monday 00:00 to Sunday 24:00 local time, as
// on a real drum. The scale is the expanded "storm chart" range, 29.5 to 30.5
// inHg, so San Diego's small swings show. The geometry matches the drum in
// Dashboard/Barograph/model (make_textures.py, build_barograph.py).

import * as THREE from "three";

// Shared with the model (millimetres).
const PAPER_MM = { w: 292.8, h: 97.0 }; // one turn of the drum, and the paper's height
const GRID_TOP_MM = 5.0;
const GRID_MM = 90.0;
const PEN_ARM_MM = 173.0; // the pen swings on this radius, so time lines are arcs

export const SCALE = { lo: 29.5, hi: 30.5 }; // inHg, bottom and top of the grid
export const WEEK_HOURS = 168;

const WIDTH = 4096;
const PX = WIDTH / PAPER_MM.w; // pixels per millimetre
const HEIGHT = Math.round(PAPER_MM.h * PX);
const Y_TOP = GRID_TOP_MM * PX;
const GRID_H = GRID_MM * PX;
const Y_MID = Y_TOP + GRID_H / 2;

const PAPER = "rgb(243,235,214)";
const RED = "rgb(205,92,88)";
const RED_BOLD = "rgb(188,60,60)";
const INK = "rgb(38,34,128)";
const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

/** One reading on the trace: time (unix seconds) and pressure (inHg). */
export interface TracePoint {
  t: number;
  p: number;
}

/** The canvas row for a pressure, clamped to the grid like a pen at its stop. */
function yOf(p: number): number {
  const clamped = Math.min(SCALE.hi, Math.max(SCALE.lo, p));
  return Y_TOP + ((SCALE.hi - clamped) / (SCALE.hi - SCALE.lo)) * GRID_H;
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

function drawGrid(): HTMLCanvasElement {
  const canvas = document.createElement("canvas");
  canvas.width = WIDTH;
  canvas.height = HEIGHT;
  const g = canvas.getContext("2d")!;
  g.fillStyle = PAPER;
  g.fillRect(0, 0, WIDTH, HEIGHT);

  // Pressure lines every 0.02 inHg; heavier every tenth and at the half inch.
  const steps = Math.round((SCALE.hi - SCALE.lo) / 0.02);
  for (let i = 0; i <= steps; i++) {
    const y = Y_TOP + (i / steps) * GRID_H;
    const strong = i % 25 === 0;
    const tenth = i % 5 === 0;
    g.strokeStyle = tenth ? RED_BOLD : RED;
    g.lineWidth = strong ? 4.6 : tenth ? 3.2 : 1.6;
    g.beginPath();
    g.moveTo(0, y);
    g.lineTo(WIDTH, y);
    g.stroke();
  }

  // Time lines every 2 hours, as arcs; heavier at noon and midnight.
  for (let h = 0; h <= WEEK_HOURS; h += 2) {
    g.strokeStyle = h % 12 === 0 ? RED_BOLD : RED;
    g.lineWidth = h % 24 === 0 ? 4.6 : h % 12 === 0 ? 3.2 : 1.6;
    g.beginPath();
    for (let k = 0; k <= 40; k++) {
      const y = Y_TOP + (GRID_H * k) / 40;
      if (k === 0) g.moveTo(xOf(h, y), y);
      else g.lineTo(xOf(h, y), y);
    }
    g.stroke();
  }

  // Day names over noon, hours along the top, pressures down each noon line.
  g.textAlign = "center";
  g.textBaseline = "alphabetic";
  DAYS.forEach((name, day) => {
    g.fillStyle = RED_BOLD;
    g.font = `italic bold ${Math.round(3.3 * PX)}px Georgia, serif`;
    g.fillText(name, xOf(day * 24 + 12, Y_TOP), Y_TOP - 0.6 * PX);
    g.fillStyle = RED;
    g.font = `${Math.round(1.7 * PX)}px Georgia, serif`;
    for (const [h, label] of [[2, "2"], [4, "4"], [20, "8"], [22, "10"]] as const) {
      g.fillText(label, xOf(day * 24 + h, Y_TOP), Y_TOP - 0.5 * PX);
    }
    g.textBaseline = "middle";
    for (let tenth = 1; tenth < 10; tenth++) {
      const p = SCALE.lo + tenth / 10;
      const whole = Math.abs(p - Math.round(p)) < 1e-6;
      const label = whole ? String(Math.round(p)) : String(Math.round(p * 10) % 10);
      g.font = whole ? `bold ${Math.round(3.4 * PX)}px Georgia, serif` : `${Math.round(2.2 * PX)}px Georgia, serif`;
      const y = yOf(p);
      const x = xOf(day * 24 + 12, y);
      const w = g.measureText(label).width;
      g.fillStyle = PAPER;
      g.fillRect(x - w / 2 - 4, y - 1.4 * PX, w + 8, 2.8 * PX);
      g.fillStyle = RED_BOLD;
      g.fillText(label, x, y);
    }
    g.textBaseline = "alphabetic";
  });
  return canvas;
}

/** A sheet of chart paper: the printed grid plus a week's ink, as a live texture. */
export class ChartSheet {
  readonly texture: THREE.CanvasTexture;
  private readonly canvas = document.createElement("canvas");
  private readonly grid = drawGrid();

  constructor() {
    this.canvas.width = WIDTH;
    this.canvas.height = HEIGHT;
    this.texture = new THREE.CanvasTexture(this.canvas);
    this.texture.colorSpace = THREE.SRGBColorSpace;
    this.texture.flipY = false; // glTF texture coordinates
    this.texture.wrapS = THREE.RepeatWrapping;
    this.texture.anisotropy = 16;
    this.draw(weekStart(new Date()), []);
  }

  /**
   * Print a fresh sheet for the week starting `monday` and ink `points` on it.
   * A gap of more than `maxGapSecs` in the readings lifts the pen.
   */
  draw(monday: Date, points: TracePoint[], maxGapSecs = 1800): void {
    const g = this.canvas.getContext("2d")!;
    g.drawImage(this.grid, 0, 0);
    const t0 = monday.getTime() / 1000;
    g.strokeStyle = INK;
    g.lineWidth = 0.34 * PX;
    g.lineJoin = "round";
    g.lineCap = "round";
    g.beginPath();
    let last: TracePoint | null = null;
    for (const pt of points) {
      const hours = (pt.t - t0) / 3600;
      if (hours < 0 || hours > WEEK_HOURS) continue;
      const y = yOf(pt.p);
      const x = xOf(hours, y);
      if (last && pt.t - last.t <= maxGapSecs) g.lineTo(x, y);
      else g.moveTo(x, y);
      last = pt;
    }
    g.stroke();
    this.texture.needsUpdate = true;
  }

  dispose(): void {
    this.texture.dispose();
  }
}
