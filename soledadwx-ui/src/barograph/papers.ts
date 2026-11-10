// The chart papers the barograph takes: what each records, its printed colours
// and ruling, and its ink. Plain data, so the page can read it without loading
// the 3D code.

/** One reading on a trace: time (unix seconds) and value, in the trace's unit. */
export interface TracePoint {
  t: number;
  v: number;
}

/** A printed scale: the values at the bottom and top of the grid. */
export interface Scale {
  lo: number;
  hi: number;
}

/** One inked line on a paper. */
export interface Trace {
  /** The Archive metric it is read from. */
  metric: string;
  name: string;
  unit: string;
  /** Decimal places when its value is shown. */
  digits: number;
  ink: string;
  /** Width of the inked line, in millimetres. */
  nib: number;
  /** The scale when the week's readings fit it. */
  base: Scale;
  /**
   * A week that goes beyond the base scale widens it in steps of this.
   * Zero pins the scale, and the pen stops at its edge.
   */
  widen: number;
  /** Figures printed down the sheet: how often, what they say, and which are bold. */
  figures: { step: number; text(value: number): string; bold(value: number): boolean };
}

export type PaperId = "pressure" | "temperature" | "humidity";

/** A chart paper: its printing, the trace the pen writes, and perhaps a second, finer trace. */
export interface Paper {
  id: PaperId;
  name: string;
  /** Printed along the bottom edge of the sheet. */
  legend: string;
  /** The colours of the printed ruling. */
  print: { line: string; bold: string };
  /** Ruling across the sheet, in the pen's unit: a fine line, a heavier one, the heaviest. */
  ruling: { line: number; mid: number; strong: number };
  pen: Trace;
  /** A second trace with its own scale. Its figures stand at each midnight line, in its ink. */
  second?: Trace;
}

export const isMultiple = (value: number, of: number) => Math.abs(value / of - Math.round(value / of)) < 1e-6;
const tens = { step: 10, text: (v: number) => String(Math.round(v)), bold: () => true };

export const PAPERS: Record<PaperId, Paper> = {
  // The expanded "storm chart" range, so San Diego's small swings show.
  pressure: {
    id: "pressure",
    name: "Pressure",
    legend: "PRESSURE, INCHES OF MERCURY",
    print: { line: "rgb(205,92,88)", bold: "rgb(188,60,60)" },
    ruling: { line: 0.02, mid: 0.1, strong: 0.5 },
    pen: {
      metric: "baromrelin",
      name: "Pressure",
      unit: "inHg",
      digits: 2,
      ink: "rgb(38,34,128)",
      nib: 0.34,
      base: { lo: 29.5, hi: 30.5 },
      widen: 0,
      figures: {
        step: 0.1,
        text: (v) => (isMultiple(v, 1) ? String(Math.round(v)) : String(Math.round(v * 10) % 10)),
        bold: (v) => isMultiple(v, 1),
      },
    },
  },
  // Nearly every week on Mount Soledad sits between 50 and 90 degrees.
  temperature: {
    id: "temperature",
    name: "Temperature",
    legend: "TEMPERATURE, DEGREES FAHRENHEIT",
    print: { line: "rgb(104,136,176)", bold: "rgb(66,100,146)" },
    ruling: { line: 1, mid: 5, strong: 10 },
    pen: {
      metric: "tempf",
      name: "Temperature",
      unit: "°F",
      digits: 1,
      ink: "rgb(176,28,36)",
      nib: 0.34,
      base: { lo: 50, hi: 90 },
      widen: 10,
      figures: {
        step: 5,
        text: (v) => (isMultiple(v, 10) ? String(Math.round(v)) : "5"),
        bold: (v) => isMultiple(v, 10),
      },
    },
  },
  // On the base scales one fine line is 2.5 % of humidity and 1 degree of dew point.
  humidity: {
    id: "humidity",
    name: "Humidity",
    legend: "RELATIVE HUMIDITY, PER CENT",
    print: { line: "rgb(178,142,100)", bold: "rgb(146,106,64)" },
    ruling: { line: 2.5, mid: 10, strong: 50 },
    pen: {
      metric: "humidity",
      name: "Humidity",
      unit: "%",
      digits: 0,
      ink: "rgb(98,36,140)",
      nib: 0.34,
      base: { lo: 0, hi: 100 },
      widen: 0,
      figures: { step: 10, text: (v) => String(Math.round(v)), bold: (v) => isMultiple(v, 50) },
    },
    second: {
      metric: "dewpointf",
      name: "Dew point",
      unit: "°F",
      digits: 0,
      ink: "rgb(18,112,62)",
      nib: 0.22,
      base: { lo: 30, hi: 70 },
      widen: 10,
      figures: tens,
    },
  },
};

export const PAPER_ORDER: PaperId[] = ["pressure", "temperature", "humidity"];

/** How far up the grid a value sits on a scale: 0 at the bottom, 1 at the top, stopped at the edges like a pen. */
export function fraction(value: number, scale: Scale): number {
  return Math.min(1, Math.max(0, (value - scale.lo) / (scale.hi - scale.lo)));
}
