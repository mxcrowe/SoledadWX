# SoledadWX — Page Taxonomy & Information Architecture

Nav-rail order (left panel). Inspiration: **CumulusMX desktop** + **Beaumaris MXUI**
(beaumaris-weather.com/MXUI). Our archive spans ~17 years (2009→present) — a
decade-plus deeper than a typical MXUI site, which matters for Records/Extremes/Climate.

## Surfaces

| # | Page | Status | Job | Inspiration |
|---|------|--------|-----|-------------|
| 1 | **Console** | ✅ built | Live dashboard: current conditions, astro strip, trends, today/yesterday extremes, gauges, wind rose (12-card grid) | MXUI dashboard.php |
| 2 | **Live** | ✅ built | Raw telemetry firehose — every WebSocket field, unstyled. Debug/verify view | — |
| 3 | **Today/Yesterday** | ⏳ planned | All parameters, two-column today-vs-yesterday with hi/lo + times. Fixed 2-day compare | Beaumaris |
| 4 | **Micro-forecast** | ⏳ Phase 5 | Hyperlocal AI forecast: NWS regional signal + 17yr archive → LLM bias-corrects to the Mt Soledad microclimate. Needs a synoptic feed (NWS gridpoint) first | the "Oracle" |
| 5 | **Charts** | ⏳ deferred | Interactive time-series, four modes: Recent, Recent SelectaChart, Historic, Climate | Beaumaris (does this superbly) |
| 6 | **Records** | ⏳ planned | **All-time** hall of fame: single highest/lowest *ever* per parameter with date/time, tabbed by category (Temp/Wind/Rain/Humidity/Pressure). Static | Cumulus "All Time Records" (Cumulus UI Examples/…10_50_15…png) |
| 7 | **Synopsis** | ⏳ planned · **placement TBD** | Per-period **report card**: fixed output, a View selector picks the range (This Month / This Year / This Period custom). Means (1-min, min+max, mean-min/max), extremes w/ days, rain days / dry days, wind run, sunshine hours | Cumulus "Averages and Extremes for [period]" (…10_49_53…png) |
| 8 | **Analyst** | ⏳ design TBD | **NEW capability, not in Cumulus.** Comparison workbench: compare dates/periods/records over time (July 2010 vs July 2020; this-day-in-history across 17 yrs; decade-over-decade drift). Replaces the user's old by-hand value-copying | own idea |
| 9 | **Gauges** | ⏳ deferred toy | Full-page SteelSeries steam-gauge instrument panel — the ambient "fish tank" | CustomGauges.png |
| 10 | **Barograph** | ⏳ deferred toy | Bermuda rotating-drum barograph, ink trace of recent pressure; brass/glass via AI textures + SVG | uncle's barograph |
| 11 | **Extremes** | ⏳ planned | **Current-period** bests: this-month / this-year highest-lowest per parameter with dates, live-updating. Distinct from Records' all-time statics | Beaumaris extremes.php |

## Key distinctions (locked)

- **Records vs Extremes** — Records = all-time (static). Extremes = this-month/this-year (rolling, live). CumulusMX convention.
- **Synopsis vs Analyst** — Synopsis = read-only *report card* for one chosen period (the Cumulus digest; This Month/Year/Period is just how you set start/stop). Analyst = the *workbench* that compares periods/records and answers open-ended questions. **The user considers these two distinct surfaces** (Analyst is genuinely new, not a Cumulus feature).
- **Charts vs Synopsis/Analyst** — Charts = *see* it (visual plots). Synopsis/Analyst = *tabulate/compare* it (numbers).
- **Note:** the current "Analyst" nav item points at the interactive plotter built in Analyst v1 — that code is really a **proto-Charts** and will migrate to the Charts surface. The real Analyst gets built fresh.

## OPEN QUESTION
Synopsis is not yet in the nav rail (user's list has Analyst but not Synopsis, while describing them as separate). Decide: **own rail item**, or the landing view of Analyst?

## Data foundation (already built — everything below reads these)
- `observations` — 17.1M rows, source-tagged, canonical priority resolver (`canonical_observations` view)
- `daily_rollups` — 95k rows: per-metric-per-day avg/min/max/n + epoch of the extremes. **The workhorse for Records / Synopsis / Extremes / Analyst.**
- `daily_summaries` — Cumulus dayfile incl. wind run
- Rust commands: `db_status`, `console_stats`, `wind_rose`, `query_series`, `range_stats`, `series_hours`

## Suggested build order (analysis family)
1. **Records** — pure rollup reads, high nostalgia, cheap
2. **Synopsis** — GROUP BY rollups + a few derived counts (rain days, dry days); the report card most missed
3. **Extremes** — this month/year, sibling of Records
4. **Today/Yesterday** — mostly an extension of `console_stats`
5. **Analyst** — the new workbench (design first)
6. **Charts** — big Beaumaris-grade surface, deferred
7. **Micro-forecast / Gauges / Barograph** — later phases
