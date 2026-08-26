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
  // Each event is stamped onto its own day's UTC midnight, so sunset (which
  // falls after 00:00 UTC here) can land a calendar day "before" sunrise and
  // make the raw difference negative. Normalize into a single 0–24 h day.
  const dayLen = (rise: Date | null, set: Date | null) => {
    if (!rise || !set) return 0;
    const m = (set.getTime() - rise.getTime()) / 60000;
    return ((m % 1440) + 1440) % 1440;
  };
  const dayLengthMin = dayLen(sunrise, sunset);
  const tm = new Date(now.getTime() + 86400000);
  const r2 = sunEvent(tm, true, 90.833);
  const s2 = sunEvent(tm, false, 90.833);
  const tomorrowLen = dayLen(r2, s2);

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

/** NWS wind chill (°F). Only defined for T ≤ 50 °F and wind > 3 mph; else null. */
export function windChillF(tempF?: number, windMph?: number): number | null {
  if (tempF == null || windMph == null || tempF > 50 || windMph <= 3) return null;
  const v = Math.pow(windMph, 0.16);
  return 35.74 + 0.6215 * tempF - 35.75 * v + 0.4275 * tempF * v;
}

/** NWS heat index (°F, Rothfusz regression). Only defined for T ≥ 80 °F; else null. */
export function heatIndexF(tempF?: number, rh?: number): number | null {
  if (tempF == null || rh == null || tempF < 80) return null;
  const T = tempF, R = rh;
  let hi =
    -42.379 + 2.04901523 * T + 10.14333127 * R - 0.22475541 * T * R -
    0.00683783 * T * T - 0.05481717 * R * R + 0.00122874 * T * T * R +
    0.00085282 * T * R * R - 0.00000199 * T * T * R * R;
  if (R < 13 && T <= 112) hi -= ((13 - R) / 4) * Math.sqrt((17 - Math.abs(T - 95)) / 17);
  else if (R > 85 && T <= 87) hi += ((R - 85) / 10) * ((87 - T) / 5);
  return hi;
}

const satVpHpa = (tc: number) => 6.112 * Math.exp((17.67 * tc) / (tc + 243.5));

/**
 * Australian BOM apparent temperature (°F). The only moist-heat measure
 * defined at EVERY temperature — heat index quits below 80 °F and wind chill
 * above 50 °F, leaving a 30-degree hole that covers most of a San Diego year
 * — and the only one that accounts for wind as well as moisture. Missing
 * wind is treated as calm, not as missing data.
 * Must stay bit-for-bit identical to apparent_temp_f() in src-tauri/src/db.rs.
 */
export function apparentTempF(tempF?: number, rh?: number, windMph?: number): number | null {
  if (tempF == null || rh == null) return null;
  const wMs = (windMph ?? 0) * 0.44704;
  const tc = ((tempF - 32) * 5) / 9;
  const e = (rh / 100) * satVpHpa(tc);
  return ((tc + 0.33 * e - 0.7 * wMs - 4.0) * 9) / 5 + 32;
}

/**
 * Humidex (°F-equivalent). Null below a 10 °C dewpoint, per Environment
 * Canada — below that the moisture term would subtract, which humidex does
 * not claim to model. Mirrors humidex_f() in db.rs.
 */
export function humidexF(tempF?: number, dewF?: number): number | null {
  if (tempF == null || dewF == null) return null;
  const dc = ((dewF - 32) * 5) / 9;
  if (dc < 10) return null;
  const tc = ((tempF - 32) * 5) / 9;
  const e = 6.11 * Math.exp(5417.753 * (1 / 273.16 - 1 / (dc + 273.15)));
  return ((tc + 0.5555 * (e - 10)) * 9) / 5 + 32;
}

/**
 * Wet-bulb temperature (°F), Stull (2011). Not a comfort index — it is the
 * physical floor of evaporative cooling, i.e. what actually limits how well
 * a body sheds heat. Valid ~5-99% RH and -20..50 °C; null outside.
 * Mirrors wet_bulb_f() in db.rs.
 */
export function wetBulbF(tempF?: number, rh?: number): number | null {
  if (tempF == null || rh == null || rh < 5 || rh > 99) return null;
  const tc = ((tempF - 32) * 5) / 9;
  if (tc < -20 || tc > 50) return null;
  const wb =
    tc * Math.atan(0.151977 * Math.sqrt(rh + 8.313659)) +
    Math.atan(tc + rh) -
    Math.atan(rh - 1.676331) +
    0.00391838 * Math.pow(rh, 1.5) * Math.atan(0.023101 * rh) -
    4.686035;
  return (wb * 9) / 5 + 32;
}

const ELEV_M = 159; // station altitude (522 ft) for the air-mass term

/** Sun's altitude above the horizon, degrees (NOAA approximation, ~0.5°). */
export function solarAltitudeDeg(now = new Date()): number {
  const yearStart = Date.UTC(now.getUTCFullYear(), 0, 0);
  const dayMid = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
  const doy = Math.floor((dayMid - yearStart) / 86400000);
  const utMin = now.getUTCHours() * 60 + now.getUTCMinutes() + now.getUTCSeconds() / 60;
  const g = ((2 * Math.PI) / 365) * (doy - 1 + (utMin / 60 - 12) / 24);
  const decl =
    0.006918 - 0.399912 * Math.cos(g) + 0.070257 * Math.sin(g) -
    0.006758 * Math.cos(2 * g) + 0.000907 * Math.sin(2 * g) -
    0.002697 * Math.cos(3 * g) + 0.00148 * Math.sin(3 * g);
  const eqtime =
    229.18 * (0.000075 + 0.001868 * Math.cos(g) - 0.032077 * Math.sin(g) -
      0.014615 * Math.cos(2 * g) - 0.040849 * Math.sin(2 * g));
  const tst = utMin + eqtime + 4 * LON;   // true solar time (min)
  const ha = rad(tst / 4 - 180);          // hour angle
  const sinAlt =
    Math.sin(rad(LAT)) * Math.sin(decl) +
    Math.cos(rad(LAT)) * Math.cos(decl) * Math.cos(ha);
  return deg(Math.asin(Math.max(-1, Math.min(1, sinAlt))));
}

/** Ryan–Stolzenbach clear-sky global horizontal irradiance, W/m². */
export function clearSkyGHI(altitudeDeg: number): number {
  if (altitudeDeg <= 0) return 0;
  const sinAlt = Math.sin(rad(altitudeDeg));
  const airMass =
    Math.exp(-0.0001184 * ELEV_M) /
    (sinAlt + 0.15 * Math.pow(altitudeDeg + 3.885, -1.253));
  return 1368 * Math.pow(0.8, airMass) * sinAlt;
}

// Fraction of the theoretical clear-sky DAILY energy this (flat, south-tilted,
// cup-shadowed) sensor captures on a genuinely clear day. Calibrated from the
// archive — clearest recent day integrated to ~0.62 of the model. It's the one
// knob for the "% of a clear day" readout; recalibrate as the sensor ages or
// when the station is upgraded (a proper horizontal pyranometer → ~0.9+).
export const SOLAR_CLEAR_CAPTURE = 0.62;

/** Theoretical clear-sky global-horizontal energy (kWh/m²) from `from` to `to`,
 *  integrating the Ryan–Stolzenbach model in 5-minute steps. */
export function clearSkyEnergyKwh(from: Date, to: Date): number {
  const stepMs = 5 * 60 * 1000;
  if (to.getTime() <= from.getTime()) return 0;
  let joules = 0;
  let prev = clearSkyGHI(solarAltitudeDeg(from));
  for (let t = from.getTime() + stepMs; t <= to.getTime(); t += stepMs) {
    const cur = clearSkyGHI(solarAltitudeDeg(new Date(t)));
    joules += ((prev + cur) / 2) * (stepMs / 1000); // W/m² × s = J/m²
    prev = cur;
  }
  return joules / 3.6e6; // → kWh/m²
}

export interface SkyState { usable: boolean; fraction: number; label: string; clearGHI: number }

// A genuinely clear day reaches only a fraction of the pure model (aerosols,
// water vapour) AND less as the sensor's diffuser ages/fouls. Measured from
// this station's own 2026 clear-day envelope (~0.83, down from ~0.98 in 2019 —
// see solar_decay probe). Tunable; ultimately should auto-track the envelope.
const CLEAR_FRACTION = 0.83;

/** Estimate cloud cover by comparing measured solar flux to clear-sky model. */
export function skyState(now: Date, solarWm2: number | null | undefined): SkyState {
  const alt = solarAltitudeDeg(now);
  const clear = clearSkyGHI(alt);
  // Below ~7° sun the model and the sensor are both unreliable (long shadows,
  // horizon obstructions), and at night solar tells us nothing about cloud.
  if (alt < 7 || clear < 40 || solarWm2 == null) {
    return { usable: false, fraction: 0, label: "", clearGHI: clear };
  }
  const ratio = solarWm2 / clear;
  const fraction = Math.max(0, Math.min(1, 1 - ratio / CLEAR_FRACTION));
  const label =
    fraction < 0.15 ? "sky clear" :
    fraction < 0.35 ? "mostly clear" :
    fraction < 0.65 ? "partly cloudy" :
    fraction < 0.88 ? "mostly cloudy" : "overcast";
  return { usable: true, fraction, label, clearGHI: clear };
}

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
