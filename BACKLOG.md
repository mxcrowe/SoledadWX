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

## Product roadmap (pointer, not duplicated here)

Page-build order lives in `Dashboard/PAGES_SPEC.md`. Next cheapest wins:
Synopsis by Period → Soledad Extremes → Today/Yesterday → Analyze & Compare →
Charts → Micro-forecast (Oracle) → Gauges → Barograph.
