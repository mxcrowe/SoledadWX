// Display units.
//
// RULE: the archive stores wind in mph as its canonical base unit. Nothing is
// ever STORED in display units — that was exactly Cumulus's mistake, and it
// cost this project nine years of silently understated wind (see
// scripts/fix_cumulus_knots.py). Convert here, at the render boundary, and
// nowhere else.
//
// Michael reads wind in knots and has for 17 years — that intuition is a
// calibrated instrument (his "about 40 kt max ever" matches the Cumulus-era
// peak of 37.7 kt), so knots is the display unit for everything wind.

/** mph -> knots. Also statute miles -> nautical miles (same ratio). */
export const MPH_TO_KT = 0.8689762419006479;

export const WIND_UNIT = "kt";
/** Wind run: knots integrated over hours gives nautical miles. */
export const WIND_RUN_UNIT = "nm";

/** mph -> knots. Passes null/undefined through so callers can render "N/A". */
export function toKt(mph: number | null | undefined): number | null {
  return mph == null ? null : mph * MPH_TO_KT;
}

/** Statute miles -> nautical miles (wind run). */
export const toNm = toKt;

/**
 * Convert a stored value + its STORED unit into display units.
 *
 * For generic surfaces (Records, the Analyst plotter) that carry a unit string
 * from the database rather than knowing which metric they hold. Converts value
 * and label together — never relabel without converting, which is the exact
 * failure this project already paid for once.
 */
export function toDisplay(
  value: number | null | undefined,
  storedUnit: string,
): { value: number | null; unit: string } {
  if (storedUnit === "mph")
    return { value: toKt(value), unit: WIND_UNIT };
  if (storedUnit === "mi")   // wind run
    return { value: toNm(value), unit: WIND_RUN_UNIT };
  return { value: value ?? null, unit: storedUnit };
}

/** Display label for a stored unit (mph -> kt, mi -> nm, else unchanged). */
export function displayUnit(storedUnit: string): string {
  return storedUnit === "mph" ? WIND_UNIT
       : storedUnit === "mi"  ? WIND_RUN_UNIT
       : storedUnit;
}

/**
 * Multiplier taking a stored value into display units. Always use together
 * with displayUnit() — scaling without relabelling (or vice versa) is the bug
 * class this module exists to prevent.
 */
export function unitFactor(storedUnit: string): number {
  return storedUnit === "mph" || storedUnit === "mi" ? MPH_TO_KT : 1;
}

/** Format a stored-mph value as knots. Returns "N/A" for missing data. */
export function fmtKt(mph: number | null | undefined, digits = 1): string {
  const v = toKt(mph);
  return v == null ? "N/A" : v.toFixed(digits);
}
