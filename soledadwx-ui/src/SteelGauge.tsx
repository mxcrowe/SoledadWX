// React wrappers around the SteelSeries v2 gauges — the same library behind
// the CumulusMX gauges page (and Dashboard/CustomGauges.png).
//
// v2 is Lit web components: importing the package registers
// <steelseries-radial> and <steelseries-wind-direction>. Enum-ish options
// are STRING names resolved against the library's objectEnum maps
// ('CHROME', 'BLUE', 'ORANGE', 'TYPE4', ...). Needle animation is built in
// (500 ms eased transition on value changes). Elements are created
// imperatively with properties assigned directly, which sidesteps Lit's
// attribute-name mapping entirely.

import { useEffect, useRef } from "react";
import "steelseries";

// House style: chrome frame, navy face, orange pointer, curved glass.
const HOUSE = {
  frameDesign: "CHROME",
  backgroundColor: "BLUE",
  foregroundType: "TYPE2",
  pointerColor: "ORANGE",
};

type GaugeEl = HTMLElement & Record<string, unknown>;

function SteelElement({ tag, options, live }: {
  tag: string;
  options: Record<string, unknown>;
  live: Record<string, number | null | undefined>;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const elRef = useRef<GaugeEl | null>(null);

  useEffect(() => {
    if (!hostRef.current) return;
    const el = document.createElement(tag) as GaugeEl;
    Object.assign(el, options);
    hostRef.current.appendChild(el);
    elRef.current = el;
    return () => {
      el.remove();
      elRef.current = null;
    };
    // Recreate only if the tag itself changes; options are creation-time.
  }, [tag]);

  useEffect(() => {
    const el = elRef.current;
    if (!el) return;
    for (const [k, v] of Object.entries(live)) {
      if (v != null && el[k] !== v) el[k] = v;
    }
  });

  return <div ref={hostRef} />;
}

export function SteelRadial({
  value, title, unit, max, min = 0, size = 220, decimals = 1,
}: {
  value: number | null | undefined;
  title: string;
  unit: string;
  max: number;
  min?: number;
  size?: number;
  decimals?: number;
}) {
  return (
    <SteelElement
      tag="steelseries-radial"
      options={{
        ...HOUSE,
        size,
        gaugeType: "TYPE4",
        titleString: title,
        unitString: unit,
        minValue: min,
        maxValue: max,
        noNiceScale: true,
        lcdDecimals: decimals,
      }}
      live={{ value }}
    />
  );
}

export function SteelWindDir({
  latest, average, size = 220,
}: {
  latest: number | null | undefined;
  average: number | null | undefined;
  size?: number;
}) {
  return (
    <SteelElement
      tag="steelseries-wind-direction"
      options={{
        ...HOUSE,
        size,
        titleString: "Wind Dir.",
        pointerColorAverage: "WHITE",
      }}
      live={{ valueLatest: latest, valueAverage: average }}
    />
  );
}
