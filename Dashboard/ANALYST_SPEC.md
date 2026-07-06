# Analyst v2 — Functional Spec (Cumulus parity and beyond)

Derived from Cumulus UI screenshots in `Dashboard/Cumulus UI Examples/` plus
the known Cumulus (Sandysoft) feature set. Goal: replicate what made Cumulus
great for data interrogation, then exceed it. The SoledadWX schema
(observations + daily_rollups + daily_summaries) already supports most of
this; items marked **[derive]** need new calculations.

## Verified correctness note (2026-07-06)
Cumulus's own All Time Records screen agrees with our imported archive
exactly (110.7 °F @ 2010-09-27, 38.3 °F @ 2011-02-27) — independent
cross-validation of the Cumulus importer.

## 1. Records system (the heart of Cumulus)
Tabbed by category: **Temperature / Wind / Rainfall / Humidity / Pressure**,
each over four scopes: **All-time / By-month-of-year / This month / This year**.

Temperature tab fields (from screenshot):
- Highest / Lowest temperature (+timestamp)
- Highest heat index, Lowest wind chill, Highest/Lowest apparent temp
- **Highest minimum** / **Lowest maximum** (daily aggregate records) [derive from rollups]
- Highest/Lowest dew point
- Highest/Lowest **daily temp range** [derive: max-min per day]

Wind: highest gust, highest sustained, highest daily wind run.
Rain: wettest day/hour/month/year, longest dry/wet spell [derive spells].
Pressure/Humidity: extremes with timestamps.

Implementation: all computable from daily_rollups (fast) except hourly-rain
records (need hourly buckets over observations — acceptable one-time scans).

## 2. Dashboard panels (main screen, for Fish Tank + Live view)
- Outdoor: temp + **trend (°F/hr)** [derive], avg temp, wind chill, heat
  index, dew point, RH, apparent temp
- Wind: latest/gust/average speeds, bearing + avg dir, **wind run today**
- Barometer: pressure + **trend (in/hr) + trend word ("Steady", "Rising")** [derive]
- Rainfall: rate, last hour, today, last 24 h, yesterday, month, year
- Recent Extremes panel: today vs yesterday side-by-side (hi wind/gust,
  min/max temp, min/max pressure, rain rate — each with time)
- Solar: lux, W/m², UV, sun-up indicator
- Astro strip [derive, pure math]: sunrise/set, dawn/dusk, day length,
  tomorrow's Δ, moon rise/set/phase, **cloud base estimate** (from temp/dewpoint spread)
- Indoor panel; status LEDs (new record / error / catch-up)

## 3. Interrogation (Analyst v2)
- Any start/stop range (have it) + presets: today, yesterday, this month,
  this year, each calendar year, each month-of-year across all years
- Min/max/avg + timestamps (have it), plus per-range: wind run total,
  rain total, heating/cooling degree days [derive], temp range stats
- **This-day-in-history**: same calendar date across all 17 years
- Multi-metric chart overlay (e.g., temp + dewpoint + humidity)
- Hourly resolution for ranges < ~60 days (query observations directly)
- NOAA-style monthly/annual text reports (Cumulus had these; users loved them)
- CSV export of any query result

## 4. Beyond Cumulus (SoledadWX advantages)
- Source provenance visible per datapoint (which logger recorded it)
- Gap-aware charts (render known gaps honestly, not interpolated)
- Overlap-zone comparisons (two sources, same hours)
- The Oracle (Phase 5) gets these same query primitives

## Suggested build order
1. Records system (all-time + monthly) — highest nostalgia-per-effort,
   reads pure rollups
2. Range presets + this-day-in-history
3. Trends + astro strip (needed for Fish Tank anyway)
4. Hourly drill-down, overlays, NOAA reports, CSV export
