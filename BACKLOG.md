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

- [ ] **★ EVENT LOG — the dry line of 2026-08-26 (~15:17 PDT).** Observed live
  by MXC and reconstructed as it happened. Worth keeping because the archive
  cannot reproduce the part that mattered.
  What the station saw: RH 68 -> 40% and dewpoint 71.8 -> 58.5 F in 28 min,
  temperature RISING through it (83.8 -> 86.4), wind steady W/WNW the whole
  time, solar collapsing 564 -> 110 W/m**2 in three minutes. RH then held a
  noisy 39-44% band for 40+ min rather than railing.
  What made it decidable: MXC put a SECOND, unrelated hygrometer in the back
  yard and it fell too. Four independent instruments (outdoor array, console
  indoor sensor at dead-constant 82.2 F indoor temp, pyranometer, backyard
  unit). No firmware, mount or power path in common.
  The structure, from MXC reading the WU map: a north-south DRY LINE parked on
  the ridge. Everything west of the station >=60% RH; many stations east
  40-50%. Neighbour DEWPOINTS 70-76 F while ours read 61 F. MSDSD, 559 m away
  on essentially the same meridian but **187 ft LOWER**, read 83% RH — below
  the boundary, still in marine air. The station sits exactly on the edge of
  the feature, which is the one place a single station looks broken and is in
  fact most informative.
  Precedent: this signature (dewpoint <=-8F/30min, temp rising, wind W-NW,
  afternoon) has 191 days since 2019 — but 147 of them are Oct-Mar. August
  has FIVE in seven years. The mechanism is a normal cold-season behaviour of
  this ridge; what is anomalous is the date, mid-way through the most humid
  August stretch in the modern record. MXC's instinct ("it can happen here,
  but only in Santa Ana conditions") is well calibrated.
  Two wrong turns worth remembering: (1) Fathom argued sensor-vs-weather from
  RH and DEWPOINT as if they were two witnesses — they are one, the station
  derives dewpoint from temp+RH. (2) Fathom misread a WU map whose big number
  was DEWPOINT as temperature, concluded the thermometer was failing, and had
  to retract — MXC had said "we are the 60F dewpoint" in the same message.
  Read the human before the pixels.

- [ ] **★ MECHANISM — "dry bubbles": entrainment, and a failed prediction.**
  MXC's analogy, watching the Aug 26 event unfold on Wundermap: it looks like
  thermals building over a flat field at sunrise — air pooling in bubbles,
  building, letting go, rising — except these are bubbles of DRY air drifting
  through monsoon-moist air. (His father was a free-flight aeromodeller; he
  has watched streamers show this directly.)
  That is very likely the same circulation seen from the other end. A thermal
  reaching the inversion base overshoots, punches into the dry air above, and
  falls back entraining some of it; compensating subsidence between thermals
  carries it down in discrete blobs. The updraft half is what streamers show;
  the downdraft half is what Wundermap shows. Explains the discreteness, the
  neighbourhood scale, the afternoon timing, the oscillation at a station
  sitting at the boundary, and the total absence of any wind shift — the
  exchange is VERTICAL.
  Supporting: our dewpoint bottomed at 58-61 F while EVERY station on the
  county map, including the hot inland ones near I-15, held 63-78 F. Air that
  travels horizontally does not get drier en route; air that descends does.
  This is what rules out MXC's first thought (dry air pushing in from the
  east) — inland air had MORE absolute moisture than ours.
  **★ THE PREDICTION FAILED, and that is the valuable part.** If it were purely
  thermal-driven, roughness should die at sunset. Hourly dewpoint roughness on
  the five big late-Aug events: 2025-08-30 and 2020-08-18 do go quiet after
  dark (fractions of a degree). But **2023-08-29 threw 12.1 F at 18:00 and was
  still rough at 22:00, and 2019-08-25's LARGEST swing of the day was 13.5 F
  at 23:00** — no thermals at 11pm. So late-August Mt Soledad appears to have
  TWO mechanisms wearing the same costume; the nocturnal one is probably the
  marine layer surging back inland and sloshing its top across our elevation,
  which needs no sun. Do not let a future session settle on entrainment as
  the single explanation.
  **Seasonality:** afternoon dewpoint roughness (max swing in any 30-min
  window) median 2.5 F over 2,751 days; today 13.3 F = 94th pct overall and
  **#1 of all 243 August afternoons**. Top four are Aug 25, 26, 29, 30 — the
  end of the marine season. Watch that window next year.
  **MXC's open question, partly answered:** "maybe it happens all the time and
  I'm only seeing it because I'm looking closely?" Both are true. The median
  afternoon has 2.5 F of this, constantly, and neither of us had ever looked.
  What is rare is the AMPLITUDE, and today is the record.

- [ ] **★ THE ARCHIVE HAS NO SPATIAL CONTEXT, and today it cost us.** Every
  question this event raised — is it the sensor, where is the boundary, which
  side are we on — is a one-query answer with neighbour data and a guess
  without it. We hold 3.8M MSDSD rows but they are HAND-PULLED and were 19
  days stale at the moment we needed them; the WU neighbour sources (9/10/11)
  are staler still. Concrete asks, in value order:
    1. Automate the MSDSD pull (Synoptic 403s the SDG&E network — investigate
       a key, or scrape the same CSV endpoint the portal uses).
    2. Live-poll 3-6 WU neighbour PWSs, spanning the ridge E-W so the archive
       can see a gradient rather than a point.
    3. A "neighbourhood" panel: our reading vs the local median, flagged when
       we sit outside the spread. That panel would have answered the question
       in one glance instead of an hour.

- [ ] **★ THE ISOLATED-RECORD TEST — plausibility as a first-class signal.**
  MXC (Aug 26 2026): "52 kt over Mt Soledad sticks out like a sore thumb, and
  if 76 kt had really happened we'd *still* be cleaning up from it." He is
  right, and it generalizes past gust. Cross-source comparison is expensive
  (needs a witness, and most eras have none); this test needs nothing but the
  source's own history.
  The signal is NOT "the value is large" — extreme-value tails are long, and
  a 3x-median gust is unremarkable. The signal is **a record standing alone
  above a CROWDED tail.** Real weather stacks up; measured daily peak gust:
      HP2000 src2   top three days are a 3-way TIE at 34.8 kt, next three tie
                    at 30.3      -> gap(#1,#2) = 0%      healthy
      WU src7       52.1, then 43.4, 43.4, 41.2, 41.2, 39.1
                    -> gap(#1,#2) = +20%, above a dense tail    suspicious
      MSDSD src8    76.2, then 33.3, 27.9, 27.8, 27.5, 27.1
                    -> gap(#1,#2) = +129%                       not weather
  Proposed statistic: gap(#1,#2) divided by the MEDIAN gap over ranks 2..20.
  Flag when it exceeds ~3. Quantization helps here rather than hurting: unit
  conversion makes the tail tie a lot, so a real gap is unambiguous.
  Apply per source, per metric, per season where data allows. Then FLAG, never
  delete (extremes doctrine) — this is the natural consumer of the
  `quality_flag` column that is already backlogged.
  Second, independent leg MXC used and we should encode where we can:
  **consequence.** A 76 kt gust over La Jolla implies roof damage, downed
  trees, an NWS storm report. Absence of consequence is evidence. Cheap
  version: cross-check the top N days per metric against NWS storm events /
  advisories before granting record status.
  Why this matters most: it is the ONLY validity test available for the
  Zephyr era (2009-2018), which has no witness at all for most metrics.

- [ ] **Wind GUST across sources — RESOLVED by MSDSD (Aug 26 2026).** The
  earlier reading of this was backwards. Median daily gust factor
  (peak gust / peak sustained), now with a neutral third party:
      WU src7      1.91
      MSDSD src8   1.92   <- independent professional mesonet, 559 m away
      HP2000 src2  1.22
      Ambient 3/4  1.19-1.21
  MSDSD, which has no connection to our upload path, reports the SAME ~1.9
  gust factor as WU. So ~1.9 is simply what this ridge does, and **src 2/3/4
  are the outliers** — the station's own logging path under-reports gust
  relative to sustained. Do not "fix" WU's gust factor; if anything is
  suspect it is the HP2000/Ambient path. (Caution: src2 daily peak SUSTAINED
  runs 1.85x MSDSD while its peak GUST runs only 1.15x — its "sustained"
  column looks max-like, which is probably the whole 1.22 story. Worth a
  look before trusting src2 sustained.)

- [ ] **The 52.1 kt record (2019-02-02) — real storm, inflated peak.** MSDSD
  now gives an independent witness: 26.9 kt gust / 14.8 kt sustained that day
  (a top-2 legitimate day in MSDSD's whole 8-year gust record). Our station
  normally reads 1.26x MSDSD on daily peak gust; from the SE quarter, where
  our roof is genuinely more exposed, 1.39x. That day blew from **127 deg**
  (SE) and our ratio was **1.93 — the single highest of all 122 SE-wind days,
  99.6th percentile of all 1,379 compared days.**
  Expected peak given MSDSD and SE exposure: **~37 kt.** MXC's independent
  recollection is that ~40 kt is the most this house has seen. The 52.1 is
  ~15 kt above what the day supports.
  It is NOT a single-sample spike: the whole 14:00-15:00 hour reads 39-52 kt
  against MSDSD's 23-27 kt, so it is a sustained inflation of a real event,
  not one bad reading. Cause unknown (mast, exposure, WU's gust window).
  Suggested action: keep the value, LABEL it (extremes doctrine), and quote
  the storm as "~37-40 kt" in prose. *(Found Aug 26 2026.)*
  Hypothesis tested and REJECTED: mast wobble inflating gusts pre-guy-wires.
  The apparent 2022/23 step is entirely a source changeover, not a repair date.

- [ ] **MSDSD has its own bad extremes.** Its all-time peak gust is 76.2 kt on
  2025-06-18 — a day our station recorded 13.0 kt. That is an MSDSD artifact,
  clean proof that "reference station" does not mean "trustworthy extremes".
  The extremes doctrine applies to sources we did not install, too. Exclude
  that day before using MSDSD gust as a yardstick.

- [ ] **★ Zephyr-era HUMIDITY is broadly untrustworthy — and it propagates.**
  MXC (Aug 7 2026): the old station's hygrometer "saturated out", gave rail
  readings, got progressively worse, and was eventually replaced. Confirmed and
  quantified in the archive (source 1, metric 2). Mean RH by calendar month:
      healthy (src 2/3/7, 2019+)  Jan 66 -> Jul 84 -> Dec 72   (true marine curve)
      Zephyr 2011-2014            Jan 56 -> Jul 96 -> Dec 67   (~+10 pts, right shape)
      Zephyr Mar-Oct 2016         12 - 23 all months           (CATASTROPHIC, ~60 pts dry)
      Zephyr 2018                 Jan 62 -> Jul 93             (railing, worst at the end)
  Signature: monthly MAX is pinned at exactly 99.0 in every month EXCEPT
  Apr-Oct 2016 (max varies 62-84) — i.e. a hard ceiling rail most of the time,
  and a separate dry-failure episode in 2016. Share of readings >=95% RH climbs
  5% (2009) -> 81% (2012) -> 78% (mid-2018).
  **Propagation is the real damage:** dewpointf, heatindexf and feelslikef for
  that era are all DERIVED from this humidity, so they inherit the fault. The
  all-time "Highest heat index" record of 138.7 F (2012-09-14) is exactly this:
  Cumulus faithfully computed Rothfusz from 92.1 F / 96% RH, implying a ~91 F
  dew point that this coast has never produced.
  Decision needed: exclude source 1 humidity-derived metrics (humidity,
  dewpointf, heatindexf, feelslikef) from records/climatology, or flag them.
  Do NOT delete — label. Michael's rule: hold extremes loosely, keep the data.

  **QUANTIFIED against MSDSD (Aug 7 2026).** MSDSD (source 8, Mt Soledad
  mesonet, 559 m away, 10-min cadence, 2011-09-28 → 2018-08-31) is now imported
  and gives us the witness this era never had. Temperature acts as the control:
  Zephyr runs a steady **+1.1 to +2.2 °F** warmer than MSDSD in EVERY year
  (consistent with the 187 ft elevation difference), while humidity swings
  across 58 points. Same air mass, so the humidity error is purely instrumental.

      year  temp diff   RH diff
      2011    +2.2       +13.7   too WET
      2012    +1.6       +12.1
      2013    +1.6        +8.7
      2014    +1.3        +4.5
      2015    +1.6       -27.9   dry failure begins (Dec 2015)
      2016    +1.4       -44.2   catastrophic (May-Oct: -54 to -64)
      2017    +1.7        +4.1   NEW SENSOR
      2018    +1.1       +11.0   degrading again

  **Hygrometer replaced NOVEMBER 2016** — dated from the data, not memory:
  Oct 2016 -54.3 → Nov 2016 -14.0 → Dec 2016 -1.9 → Jan 2017 -0.3.
  MXC could not recall the date; the artifact dated its own repair.

  **Healthy agreement = ±2 points.** Dec 2016-Jun 2017 sits within ±2.5, which
  is the yardstick for flagging every other era — no guessing needed.
  Usable-as-is: roughly 2014 and Dec 2016 → mid-2017. Everything else needs a
  flag. NOTE 2009 → Sep 2011 predates MSDSD and remains unwitnessed.

- [ ] **Plausibility gate for humidity-derived values.** Reject/flag any derived
  reading whose implied dew point exceeds what this coast can produce (La Jolla
  has never seen a dew point near 91 F; the marine layer tops out in the low
  70s). Cheap guard that would retire the 138.7 F heat index automatically and
  catch the next sensor failure early. Ties to the clear-sky envelope tracker
  idea — same "watch for the instrument drifting" family.

- [ ] **★ Gap-fill by source_priority is broken by design — it is ADDITIVE, not
  substitutive.** `canonical_observations` partitions by exact `ts_utc`, so
  priority only chooses between sources sharing an IDENTICAL timestamp. Sources
  on different clocks (MSDSD on clean 10-min marks, Cumulus on ~20-min, WU
  irregular) essentially never collide, so the rank is never consulted and
  EVERY row of the lower-priority source is added to canonical.
  Demonstrated Aug 7 2026: adding msdsd priority rows (ranked LAST, 6/9/11)
  pulled ~250k rows/yr into canonical for 2011-2018 and:
      - MSDSD supplied 65-75% of all daily MINIMA (it runs 1-2 F cooler,
        so it wins nearly every night)
      - daily MEAN temp shifted -0.46 to -1.52 F across 2011-2017
  i.e. it quietly cooled seven years of climatology to gain 27 days. Reverted;
  msdsd priority rows deleted and it is now pure reference data (0 canonical).
  **This is not hypothetical elsewhere:** the pre-existing wu_ksandi84 (2014)
  and wu_ksandi354 (2016) rows do the same thing, warming those years by
  +0.24 and +0.63 F respectively. Still present — decide what to do.
  Proper fix: fallback must be evaluated over an INTERVAL, not a timestamp —
  use a secondary source only across spans where the primary is silent for
  more than N minutes (resample to a common grid, or a "coverage window"
  join). Until then, do NOT add priority rows for a source on a different
  sampling grid.

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
