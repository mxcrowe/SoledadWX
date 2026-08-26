# MSDSD raw exports (Synoptic / MesoWest)

Hand-pulled CSVs for **MSDSD** — Mt. Soledad mesonet (SDG&E),
32.81418 N, 117.24088 W, 335 ft. **559 m** from the station on the same
ridge, 187 ft lower, 10-minute cadence.

These are pulled by hand from the MesoWest data portal because the Synoptic
API returns 403 for the SDG&E network. The portal enforces a ~21 h cooldown
between large exports, so **keep these files** — re-pulling is expensive.

Import with:

    python scripts/import_msdsd.py data/raw/msdsd/*.csv

Idempotent (`INSERT OR IGNORE`); safe to re-run. Timestamps carry their UTC
offset inline, so there is no timezone guessing. Units are metric in the
export and converted to the archive's imperial base units on the way in.

**Reference, not replacement.** MSDSD is source 8 and holds **zero canonical
rows** — no `source_priority` entries. It must stay that way: gap-fill via
priority is *additive*, not substitutive (see BACKLOG ★), so a source on a
different sampling grid silently injects rows rather than filling holes.

## What each file contains

| File | Range | Columns |
|---|---|---|
| `MSDSD_2011-09-28_2018-08-31.csv` | 2011-09-28 → 2018-08-31 | temp, dewpoint(d), RH, wind speed, wind dir, solar* |
| `MSDSD_2018-09-01_2022-12-12.csv` | 2018-09-01 → 2022-12-12 | temp, dewpoint(d), RH, wind speed, wind dir |
| `MSDSD_2022-12-12_2026-08-07.csv` | 2022-12-12 → 2026-08-07 | temp, RH, wind speed, wind dir, **wind gust**, pressure*, solar* |

\* **Phantom columns.** The portal lists variables the station does not
actually report. Measured fill rate for `pressure_set_1` and
`solar_radiation_set_1` is **0.0%**; `dew_point_temperature_set_1` is also
empty (the useful one is the derived `..._set_1d`). Do not tick them again.
`wind_gust_set_1` is **100% filled** where it was requested.

## Still missing

**Wind gust before 2022-12-12.** The gust column was not ticked on the first
two exports, so the archive has no independent gust witness for
**2019-02-02** — the date of the disputed 52.1 kt all-time record (WU gust
factor 1.79 vs the station's own HP2000 1.22; no tiebreaker exists today).
Re-pull `2018-09-01 → 2022-12-12` with `Wind Gust`, and optionally
`2011-09-28 → 2018-08-31` for a longer comparison.
