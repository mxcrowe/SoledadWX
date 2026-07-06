// Solar/lunar calculations for the Console astro strip.
// NOAA sunrise-equation approximation — accurate to ~1 min at this latitude.

const LAT = 32.8192;
const LON = -117.2406;

const rad = (d: number) => (d * Math.PI) / 180;
const deg = (r: number) => (r * 180) / Math.PI;

/** Sunrise/sunset (or dawn/dusk) as local Date for the given date.
 *  zenith: 90.833 = official, 96 = civil twilight. */
function sunEvent(date: Date, rising: boolean, zenith: number): Date | null {
  const doy = Math.ceil(
    (date.getTime() - new Date(date.getFullYear(), 0, 0).getTime()) / 86400000
  );
  const lngHour = LON / 15;
  const t = doy + ((rising ? 6 : 18) - lngHour) / 24;
  const M = 0.9856 * t - 3.289;
  let L = M + 1.916 * Math.sin(rad(M)) + 0.02 * Math.sin(rad(2 * M)) + 282.634;
  L = ((L % 360) + 360) % 360;
  let RA = deg(Math.atan(0.91764 * Math.tan(rad(L))));
  RA = ((RA % 360) + 360) % 360;
  RA += (Math.floor(L / 90) - Math.floor(RA / 90)) * 90;
  RA /= 15;
  const sinDec = 0.39782 * Math.sin(rad(L));
  const cosDec = Math.cos(Math.asin(sinDec));
  const cosH =
    (Math.cos(rad(zenith)) - sinDec * Math.sin(rad(LAT))) /
    (cosDec * Math.cos(rad(LAT)));
  if (cosH > 1 || cosH < -1) return null; // never rises/sets (not at 32°N)
  let H = rising ? 360 - deg(Math.acos(cosH)) : deg(Math.acos(cosH));
  H /= 15;
  const T = H + RA - 0.06571 * t - 6.622;
  let UT = T - lngHour;
  UT = ((UT % 24) + 24) % 24;
  const d = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
  d.setUTCMinutes(Math.round(UT * 60));
  return d;
}

export interface AstroInfo {
  sunrise: Date | null;
  sunset: Date | null;
  dawn: Date | null;
  dusk: Date | null;
  dayLengthMin: number;
  tomorrowDeltaMin: number;
  moonPhaseName: string;
  moonIllum: number; // 0..1
  moonAge: number;   // days into synodic cycle
}

const PHASES = [
  "New Moon", "Waxing Crescent", "First Quarter", "Waxing Gibbous",
  "Full Moon", "Waning Gibbous", "Last Quarter", "Waning Crescent",
];

export function astro(now = new Date()): AstroInfo {
  const sunrise = sunEvent(now, true, 90.833);
  const sunset = sunEvent(now, false, 90.833);
  const dawn = sunEvent(now, true, 96);
  const dusk = sunEvent(now, false, 96);
  const dayLengthMin =
    sunrise && sunset ? (sunset.getTime() - sunrise.getTime()) / 60000 : 0;
  const tm = new Date(now.getTime() + 86400000);
  const r2 = sunEvent(tm, true, 90.833);
  const s2 = sunEvent(tm, false, 90.833);
  const tomorrowLen = r2 && s2 ? (s2.getTime() - r2.getTime()) / 60000 : 0;

  // Moon: synodic age from a known new moon (2000-01-06 18:14 UTC).
  const synodic = 29.530588853;
  const age =
    (((now.getTime() - Date.UTC(2000, 0, 6, 18, 14)) / 86400000) % synodic +
      synodic) % synodic;
  const illum = (1 - Math.cos((2 * Math.PI * age) / synodic)) / 2;
  const phaseIdx = Math.round((age / synodic) * 8) % 8;

  return {
    sunrise, sunset, dawn, dusk, dayLengthMin,
    tomorrowDeltaMin: tomorrowLen - dayLengthMin,
    moonPhaseName: PHASES[phaseIdx],
    moonIllum: illum,
    moonAge: age,
  };
}

/** Cloud base estimate (ft AGL) from temp/dewpoint spread in °F. */
export const cloudBaseFt = (tempF: number, dewF: number) =>
  Math.max(0, Math.round(((tempF - dewF) / 4.4) * 1000));

export const CARDINALS = [
  "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
  "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
];
export const cardinal = (d: number) => CARDINALS[Math.round(d / 22.5) % 16];

export const fmtHM = (d: Date | null) =>
  d
    ? d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })
    : "--:--";
export const fmtDur = (min: number) =>
  `${Math.floor(min / 60)}:${String(Math.round(min % 60)).padStart(2, "0")}`;
