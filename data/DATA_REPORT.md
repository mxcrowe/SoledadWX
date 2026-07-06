# SoledadWX Data Archive — Validation Report

Generated 2026-07-06 16:22 UTC by `scripts/validate.py` against `data/soledadwx.db`.

## 1. Source inventory

| Source | Rows | Timestamps | From (UTC) | To (UTC) |
|---|---|---|---|---|
| `cumulus_log` | 4,528,534 | 290,361 | 2009-09-06 21:57 | 2018-08-28 04:15 |
| `mdb` | 5,292,888 | 294,464 | 2020-04-20 01:45 | 2025-08-16 22:11 |
| `amb_rest` | 1,942,752 | 93,125 | 2025-08-16 14:16 | 2026-07-06 15:55 |
| `amb_ws` | — | — | — | — |
| `ksan_metar` | — | — | — | — |
| `sdcard` | — | — | — | — |

**Total observations: 11,764,174** across all sources, plus 3,205 daily summaries (Cumulus era, incl. wind run).

## 2. Coverage gaps (canonical `tempf`, holes > 6 h)

Canonical tempf timestamps: 677,597 (2009-09-06 21:57 -> 2026-07-06 15:55)

| Gap start (UTC) | Gap end (UTC) | Duration |
|---|---|---|
| 2011-09-07 04:00 | 2011-09-07 14:00 | 10.0 h |
| 2011-09-10 06:15 | 2011-09-10 16:15 | 10.0 h |
| 2013-07-04 14:07 | 2013-07-04 21:21 | 7.2 h |
| 2014-05-12 03:45 | 2014-06-13 06:01 | 32.1 d |
| 2016-05-24 00:00 | 2016-06-23 10:14 | 30.4 d |
| 2018-07-08 19:45 | 2018-07-16 11:46 | 7.7 d |
| 2018-08-28 04:15 | 2020-04-20 01:45 | 600.9 d |
| 2020-05-09 19:45 | 2020-05-10 14:42 | 18.9 h |
| 2020-05-26 03:42 | 2022-02-05 18:52 | 620.6 d |
| 2022-03-24 23:57 | 2022-04-26 12:02 | 32.5 d |
| 2022-05-08 16:27 | 2022-06-08 00:32 | 30.3 d |
| 2022-07-05 17:37 | 2022-08-01 02:22 | 26.4 d |
| 2022-08-24 23:17 | 2023-01-01 08:04 | 129.4 d |
| 2023-01-01 09:09 | 2023-02-03 21:13 | 33.5 d |
| 2023-02-10 16:28 | 2023-02-11 03:11 | 10.7 h |
| 2023-02-11 21:46 | 2023-02-21 07:11 | 9.4 d |
| 2023-02-22 17:46 | 2023-03-02 23:01 | 8.2 d |
| 2023-12-21 04:45 | 2024-01-01 08:01 | 11.1 d |
| 2024-12-12 21:55 | 2025-01-01 08:00 | 19.4 d |
| 2026-02-04 08:35 | 2026-02-05 16:05 | 1.3 d |

**20 gaps, 1596 days total missing.**

## 3. Overlap-zone cross-validation (2025-08-16, MDB vs Ambient)

Matched pairs within ±150 s; same physical weather, two independent recorders.

| Metric | Pairs | Mean abs diff | Max abs diff |
|---|---|---|---|
| tempf | 96 | 0.056 | 0.220 |
| humidity | 96 | 0.375 | 1.000 |
| baromrelin | 96 | 0.005 | 0.013 |
| windspeedmph | 96 | 2.406 | 10.305 |
| solarradiation | 96 | 13.846 | 266.680 |
| uv | 96 | 0.385 | 1.976 |

Note: the two sources log on offset clocks (MDB at :01/:06, Ambient at :00/:05), so canonical view interleaves rather than deduplicates inside the 8-hour overlap. Values agree, so this is harmless; revisit only if a future source overlaps for months rather than hours.

## 4. Unit sanity (whole archive, all sources)

| Metric | Min | Max | Unit | Plausible for La Jolla? |
|---|---|---|---|---|
| tempf | 38.30 | 110.70 | F | yes |
| humidity | 2.00 | 99.00 | % | REVIEW |
| baromrelin | 29.17 | 30.54 | inHg | yes |
| windspeedmph | 0.00 | 39.60 | mph | yes |
| windgustmph | 0.00 | 47.40 | mph | yes |
| dailyrainin | 0.00 | 3.43 | in | yes |
| solarradiation | 0.00 | 880.76 | W/m2 | yes |
| uv | 0.00 | 13.00 | index | yes |

## 5. All-time extremes (canonical archive)

- **Hottest reading:** 110.7 on 2010-09-27 18:36 UTC (source: `cumulus_log`)
- **Coldest reading:** 38.3 on 2011-02-27 14:20 UTC (source: `cumulus_log`)
- **Highest gust:** 47.4 on 2025-12-24 19:40 UTC (source: `amb_rest`)
- **Lowest pressure:** 29.2 on 2010-01-21 20:00 UTC (source: `cumulus_log`)
- **Highest pressure:** 30.5 on 2013-01-15 17:27 UTC (source: `cumulus_log`)
- **Windiest day (wind run):** 210.3 miles on 2014-02-28
- **Total recorded wind run (2009-2018):** 136,442 miles
