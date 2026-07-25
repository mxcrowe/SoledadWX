# SoledadWX — Backlog

Recognized work deliberately deferred. Not a roadmap of *what to build next*
(that's `Dashboard/PAGES_SPEC.md`) — this is the "we noticed it, we chose to
do it later" list, so nothing quietly falls through the cracks.

Convention: `[ ]` open · `[~]` in progress · `[x]` done (leave done items a
while for context, then prune). Newest context at the bottom of each item.

---

## Data integrity

- [ ] **Empty ≠ zero.** Absent-sensor readings must be NULL in the data layer
  and render "N/A" (or "—") in the UI — never `0`, which asserts a real
  measurement. Concretely:
  - Purge or exclude the 259,412 phantom `0.0` solar + UV rows on the Zephyr
    (source_id=1, 2010–2018 — that station had no photocell). Right now only
    the ad-hoc analysis excludes them; the archive still stores them.
  - Audit importers so a missing field writes NULL, not `0`.
  - Make `canonical_observations` / `daily_rollups` treat these as absent.
  - UI: gauges/cards show "N/A" when the value is null.
  - *Why:* a `0` masquerading as data corrupts averages and fakes trends
    (this is exactly what nearly produced a bogus "solar declining" signal).

- [ ] **Solar is not comparable across sources.** WU (src7) reads ~13% higher
  than HP2000 MDB (src2) for the *same physical sensor* — different upload-path
  scaling. Any cross-source solar comparison must normalize first (e.g. via the
  clear-sky ratio). Document this in ARCHITECTURE.md alongside the unit-quirks
  section. *(Found Jul 8 2026; see scratchpad/solar_decay.py.)*

- [ ] **Wind Run from rollups is `avg x 24` — fragile on unevenly-sampled days.**
  `db::range_stats` computes wind run as `SUM(avg_value * 24.0)`, which assumes
  the day's samples are an unbiased 24 h mean. Sample density varies wildly by
  era (2014-02-28: 99 samples; 2023-02-22: 118; 2021-01-25: 287), so a day whose
  samples cluster during the windy hours is over-credited. Sanity check: MXC's
  Cumulus-validated record, 210.3 mi on 2014-02-28, reproduces here as 208.2 mi
  (avg 8.674 x 24) — good to ~1%, so the method is roughly right but the RANKING
  across eras is not trustworthy. Fix: integrate wind run over time (trapezoidal,
  gap-capped) exactly like `solar_energy_kwh` does, instead of `avg x 24`; and/or
  require a minimum sample count / coverage fraction before a day can hold a
  record. *(Found Jul 24 2026 during the day-boundary recast.)*
  NOT a unit bug — `import_mdb.py` uses the correct `MS_TO_MPH = 2.2369362920544`
  (a suspicious-looking value, 9.84251968503936, is just 4.4 m/s converted; it
  coincidentally equals 3.0 x 3.28084, which briefly looked like a ft/mph mixup).

- [ ] **Wind GUST is not comparable across sources** (same twin as the solar
  finding). For the SAME physical anemometer in the SAME years, the median
  gust factor (gust / same-timestamp sustained) is:
      WU src7      1.78-1.81   (2018-2023, every year)
      HP2000 src2  1.20-1.22   (2020-2025, every year)
      Ambient 3/4  1.19-1.21
  2020, 2022 and 2023 have BOTH paths running simultaneously, so this is a
  property of the upload path, not of the year, the mast or the weather —
  WU derives "gust" over a different window than the station's own log.
  Consequence: the all-time gust record (52.1 kt, 2019-02-02, src7) is not
  commensurable with the rest of the archive. MXC flagged it on instinct —
  he knows >30 kt over the house is memorable and 52 kt would be unforgettable.
  The 2019-02-02 STORM is real (8 of the top 10 gusts, sustained 20-25 kt all
  afternoon); it is the cross-source comparison that is invalid.
  Fix: normalize gust by source (as with solar) or exclude WU from gust
  records. Do NOT "correct" the underlying values — they are each right in
  their own convention. *(Found Jul 24 2026.)*
  Hypothesis tested and REJECTED: mast wobble inflating gusts pre-guy-wires.
  The apparent 2022/23 step is entirely a source changeover, not a repair date.

## Instrument / sensor health

- [ ] **★ Solar sensor blocked at HIGH sun angles (Jul 8 2026, refined dx).**
  Full-day clear-sky analysis (Jul 7): the own/clear-sky ratio is a U — best at
  LOW sun (dawn 0.89, dusk 0.93+) and worst at solar NOON (0.49). Absolute output
  is flat ~460-552 for 7 h (10:00-17:00) while true clear-sky arcs 819→1078→731.
  NO evening collapse → the SW yard pine is NOT the cause (sun swings north of it
  by evening). Annual max steady ~790-880 since 2020 (sensor not dying); recent
  middays pile up at 525-575 but CAN rarely hit ~800 = 0.74 = matches neighbor
  KCASANDI354. Verdict: something blocks the sensor's view of the sun when the
  sun is HIGH (roughly overhead), leaving it reading mostly diffuse (~520); low
  morning/evening sun comes in under the obstruction and reads true. Rules OUT:
  uniform aging (keeps bell shape), cosine/tilt (would be worst at low sun), the
  pine, hard electronic cap (it reaches 800 sometimes). **Action for MXC:** stand
  at the solar sensor and look UP / high-S — prime suspect is the WS-1002 array's
  own superstructure (anemometer cups / wind vane / mast cap / a wire / bolt)
  sitting over the little solar dome, clipping the high sun. Cleaning won't fix.
  **CONFIRMED on roof Jul 8 2026:** (a) anemometer cups above the cell flicker-
  shadow it (dominant midday cause); (b) cell not horizontal — faces due S,
  tilted <45° from horizon. Lens cleaned, wasn't dirty. Effective tilt penalty
  is milder than 45° implies (seasonal hump persists — domed diffuser is angle-
  tolerant); shadow does most of the damage. Net: this station's solar is
  RELATIVE-only, never valid absolute GHI. Nothing to fix on this unit — see
  "Next station siting". Solar in Records/climatology carries an asterisk.

- [ ] **Next station siting (carry-forward lesson).** Mount the replacement's
  solar/UV sensor with a clear hemispherical sky view — above the wind gear and
  mast, nothing overhead. This obstruction is the kind of thing that quietly
  corrupts a decade of solar data; clean siting is the permanent fix.

- [ ] **Re-interpret the "2-3%/yr solar decay" finding.** It may be largely a
  GROWING obstruction (vegetation/structure encroaching over 8 yr), which is
  indistinguishable from diffuser aging in the YEARLY envelope but obvious in
  the INTRA-DAY curve shape (smooth-but-dim = aging; notched/asymmetric =
  shading). Decay rate in [[soledadwx-project-overview]] should be read with
  this caveat until the obstruction is resolved.

- [ ] **Clear-sky envelope tracker** (the "build in the degradation factor"
  item). Per-source monthly clear-day peak ratio over the sensor's life.
  Now also should flag intra-day curve SHAPE (bell vs. notched) to separate
  shading from aging, and compare against the neighbor PWS as a live "clear
  sensor" benchmark. Double duty: (a) auto-calibrates the cloudiness estimate so
  `CLEAR_FRACTION` self-tracks instead of being hand-set; (b) sensor-health +
  obstruction monitor. Lives on the future Charts surface or a health corner.
  *Current state:* `CLEAR_FRACTION` hard-set to 0.83 — NOTE this is now known to
  be corrupted by shading and is not a clean atmosphere+sensor figure.
  *Reference clear days (calibration anchors):*
  - **Jul 24 2026** — cloudless from sunrise, clear all day (MXC).
    Caveat: air noticeably THICKER/hazier than typical San Diego, so true GHI
    is depressed atmospherically — a low "% of clear day" today is NOT proof of
    sensor decay. To separate the two effects, do the three-way compare after
    sunset: our sensor → neighbor KCASANDI354 (= instrument penalty) → R-S
    clear-sky model (= atmospheric thickness). Judge on MIDDAY hours (our sensor
    flatters at low sun). Use to check whether `SOLAR_CLEAR_CAPTURE=0.62` holds.

- [ ] **Photocell wipe experiment** (secondary now that shading is the prime
  suspect). MXC to clean the WS-1002 solar dome (headlight cleaner). Log date;
  watch envelope ~1 week. But fix the obstruction FIRST — cleaning a shaded
  sensor proves nothing. *Cleaned on: ____.*

- [ ] **Station replacement is coming** (WS-1002 is near end-of-life,
  ~2–3%/yr solar decay, ~15–20% total). When the 3rd station lands: add it as a
  new source, set `source_priority` for its era, expect a fresh (un-aged) solar
  baseline — and keep the old sensor's decay curve for the historical record.
  The data engine already handles this by design (priority is data, not code).

## Deployment

- [ ] **Rebuild release exe.** Desktop shortcut still runs an older build
  (pre-Console/Records/footer/backfill and all of today's work). Run
  `npm run tauri build` to redeploy. Deferred while we keep making changes.

## Today/Yesterday page — deferred polish

- [ ] **Apparent-temperature family rows.** Beaumaris shows High/Low Feels Like,
  Heat Index, Wind Chill, Humidex under Temperature; we omitted them because we
  don't store those extremes per-day. Would need a backend calc over the day's
  temp+humidity+wind rows (or storing the derived series). Also "Hours of
  sunshine" and "Days since last dry / last rained."
- [ ] **Optional: match Beaumaris difference colors** (blue = higher today,
  red = lower). We use green-up / red-down. Trivial CSS flip if wanted.

## UI polish

- [ ] **Footer "Update rate 60s" is a static label.** Fine for the WS-1002, but
  make it self-truthing (compute the median inter-arrival from the archive) so a
  future station at a different cadence stays honest.

## Security / hygiene

- [ ] **Ambient app key logged in cleartext.** `src-tauri/src/lib.rs` `println!`s
  the full WebSocket URL including `applicationKey` on every connect (shows up in
  the dev console and background-task logs). Redact the key in that log line.
  Low risk (local only) but sloppy. *(Spotted Jul 8 2026.)*

---

## Ideas from the field (benchmark survey Jul 14 2026)

Harvested from the three best amateur stations we found — all CumulusMX-family:
Silver Acorn (Royal Oak, Auckland; author of the **MXUI** template our Console is
inspired by), Beaumaris BWX (Tasmania; a heavily-extended MXUI), and
WeatherStation40 / WS40 (Italy; commercial WordPress template, ~23 modular
blocks). They're gorgeous *live* dashboards but mostly live + light history —
SoledadWX already has the thing they lack (17-yr unified multi-source archive
with provenance). So this is display-idea shopping to sit on our deeper engine.
(Both BWX and WS40 are so heavy they hang a headless screenshot — a caution
against over-building the UI.)

### Cheap, local-only (no external API)
- [ ] **Beaufort force** on the wind card + Today/Yesterday. All THREE show it;
  we're the odd one out. Trivial mph→force lookup (0 Calm … 12 Hurricane).
- [ ] **Finish the apparent-temp family** — we have Feels Like / Heat Index /
  Wind Chill; add **Wet Bulb** and **Humidex** (pure formulae from temp/RH/
  pressure). Same gap already noted under "Today/Yesterday deferred polish".
- [ ] **Richer astro** in astro.ts — **solar noon, day length** (have), plus
  **civil / nautical / astronomical** twilight, and **moonrise / moonset**.
  We already have the solar-altitude engine to compute all of it.
- [ ] **Sun hours** (bright-sunshine: time solar > ~120 W/m² today). Ties into
  the solar-energy work; relative-only on our tilted sensor but honest.
- [ ] **10-min wind-speed average** — we already buffer wind for the vector dir
  average; adding a speed average is nearly free.
- [ ] **Multi-period rain** — last hour / 24 h / week / month / year, plus
  "storm rain" (accumulation since rain began).
- [ ] **Per-metric trend arrows** (↑ ↓ →) — extend the temp/press/humidity
  trends we already compute to the other cards.
- [ ] **Zambretti "System Forecast"** — Silver Acorn's offline pressure-trend +
  wind + season lookup → a plain-text forecast line. No API. A classic Cumulus
  feature and a cheap bridge to the eventual AI "Oracle".

### External API — and especially relevant to San Diego
- [ ] **NWS forecast + alerts** — `api.weather.gov` (free, no key): real text/
  icon forecast AND active alerts (fire weather, heat, wind, flood) for La
  Jolla. The honest bridge to the Oracle; BWX/WS40 both lean on feeds like this.
- [ ] **Air Quality / AQI** — WS40 has a full PM1/2.5/10 + AQI block. For a
  wildfire-prone hilltop this is arguably MORE useful to us than to them.
  AirNow (free key) or Open-Meteo/CAMS.
- [ ] **Rain radar** — RainViewer tiles on a small Leaflet map (free; all three
  embed it). Also satellite imagery (EUMETSAT there; US = GOES).
- [ ] **Earthquakes** — USGS feed (BWX shows quakes; San Diego has faults).

### Skip — climate/region mismatch
Saharan dust & AOD, European pollen, Mediterranean-wind rose, ASX200 ticker.

## Product roadmap (pointer, not duplicated here)

Page-build order lives in `Dashboard/PAGES_SPEC.md`. Next cheapest wins:
Synopsis by Period → Soledad Extremes → Today/Yesterday → Analyze & Compare →
Charts → Micro-forecast (Oracle) → Gauges → Barograph.
