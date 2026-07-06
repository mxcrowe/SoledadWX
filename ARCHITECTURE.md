# SoledadWX — Vision & Architecture

**Status:** Living document. Last updated 2026-05-09.
**Location:** Mount Soledad, La Jolla, CA (32.819° N, 117.241° W, 522 ft / 159 m)
**Repo:** [github.com/mxcrowe/SoledadWX](https://github.com/mxcrowe/SoledadWX)

---

## 1. Vision

A desktop weather application for a single hyper-local weather station, designed to be both **mesmerizing** and **deep**:

- **Mode 1 — The "Bermuda Fish Tank":** A photorealistic, skeuomorphic instrument panel inspired by classic analog barographs (brass, glass, drum-paper). Something you leave running on a monitor and just *enjoy*.
- **Mode 2 — The "Analyst":** A modern, data-dense interface for deep-diving 17 years of historical data. Scrubbable charts, NOAA-style reports, classic calculations like Wind Run.
- **Mode 3 — The "Oracle" (capstone):** Hyper-local AI forecasting trained on the full historical archive. Not generic grid weather — predictions tuned to *this exact spot* on Mount Soledad.

The motivation: existing weather-station software is uniformly poor. Cumulus by Sandysoft was the gold standard, but it is unsupported and incompatible with the current station hardware. 
SoledadWX is its spiritual successor, modernized and AI-augmented.

---

## 2. Technology Stack

| Layer | Technology | Why |
|---|---|---|
| Frontend | **Tauri + React (TypeScript)** | Web rendering (SVG/Canvas/CSS) is the best toolkit available for the photorealistic gauge aesthetic. Tauri keeps the binary small and uses the OS native webview rather than bundling Chromium (unlike Electron). |
| Backend | **Rust** (via Tauri) | Owns the WebSocket connection, SQLite, importers, and any heavy data work. Single statically-linked binary, no runtime to ship. |
| AI / ML | **Python sidecar** (Phase 5+) | Python remains the lingua franca of ML. Run as a subprocess; communicate over stdio or a local socket. Used only when the Oracle phase needs it — not a dependency for the dashboard. |
| Storage | **SQLite** | Embedded, file-based, fast for the data volumes involved (~few million rows lifetime). No server to administer. |

### What's already built

- `soledadwx-ui/src-tauri/src/lib.rs` — working AmbientWeather Socket.IO/WebSocket client in Rust with auto-reconnect and ping/pong handling. Deserializes into a typed `AmbientReading` and emits events to the frontend.
- `soledadwx-ui/src/App.tsx` — minimal "telemetry firehose" React UI displaying live values in a 20-tile grid.
- `soledadwx-ui/src-tauri/.env` — Ambient API + Application keys.

This is a working **tracer bullet**: end-to-end live data flow, no persistence, no aesthetics.

---

## 3. The Data Architecture (the real challenge)

Source-of-truth is **a function of time period, not of source identity**. Different sources own different slices of the timeline. 
The architecture must accept this as a first-class concern.

### 3.1 Source inventory

| Period | Station | Source | Format | Quality | Status |
|---|---|---|---|---|---|
| 2009-09 → 2018-08 | Zephyr (Fine Offset clone) | Cumulus dayfiles + monthly logs | Plain text | ★★★★★ on-site, native | Confirmed solid via Cumulus app |
| 2018-08 → 2020-04-18 | (off-site) | **KSAN METAR** climatological records | NOAA/NCEI CSV, hourly | ★★ off-site (San Diego Airport, not Mt Soledad) | Planned gap-fill |
| 2020-04-19 → 2025-08-16 22:11 UTC | WS-1002-WiFi | `HP2000-history.mdb` | MS Access, 5-min, **metric ×10** scaled ints, 21 columns, 294,488 rows | ★★★★★ on-site, 5-min | Verified readable via ODBC |
| 2025-08-16 14:16 UTC → 2026-05-10 | WS-1002-WiFi | AmbientWeather REST (rescued) | JSON, imperial, 5-min | ★★★★★ on-site, 5-min | Rescued: 267 pages / ~76,548 records / 47 MB in `Legacy/AmbientWeather-Rescue/` |
| WS-1002 era (subset) | WS-1002-WiFi | On-device SD card | Unknown format/depth | TBD | Confirmed working in-station; depth pending physical pull |
| Live → ∞ | WS-1002-WiFi | AmbientWeather WebSocket (Socket.IO) | JSON, real-time, imperial | ★★★★★ | Implemented in Rust (`soledadwx-ui/src-tauri/src/lib.rs`) |
| Future | Station #3 (TBD) | TBD | TBD | TBD | Architecture must accommodate |

### 3.2 Overlap zones (gold)

Where two sources cover the same period independently, they validate each other:

- **2025-08-16, ~14:16 → ~22:11 UTC (~8 hours):** MDB ∩ AmbientWeather REST. Small window, but enough to validate MDB unit conversion (×10 metric → imperial), detect clock drift between the device's local logger and Ambient's cloud timestamps, and confirm sample-rate alignment.
- **The handoff itself is a story:** EasyWeatherIP died on Aug 16, 2025 (last MDB record at 22:11 UTC); the same day, the user connected the WS-1002 to AmbientWeather (first cloud record at 14:16 UTC) — almost certainly *because* the local logger had failed. The two sources butt up against each other on the same day with no visible data loss at the seam.
- **(future) AmbientWeather REST ∩ SD card:** likely overlap exists once the SD card is pulled and characterized. If the card covers any of the 2018-2020 gap, the KSAN gap-fill becomes a fallback rather than the primary source for that period.

### 3.3 The three-layer model

The schema separates **what** was observed from **who** observed it from **what we believe is true**:

#### Sources (provenance inventory)
```
sources(id, name, station_id, kind, path_or_url,
        native_sample_rate, time_range_start, time_range_end,
        ingested_at, notes)
```
`kind` ∈ {`cumulus_log`, `mdb`, `amb_rest`, `amb_ws`, `sdcard`, `nws_backfill`, ...}

#### Observations (raw, multi-source, native resolution)
```
observations(source_id, timestamp_utc, metric, value,
             raw_json (optional), quality_flag)
```
- **Long format** (one row per metric per timestamp): handles divergent metric sets across sources without schema churn. Wide-format would be a refactor nightmare.
- **Native resolution preserved.** No resampling on ingest. A 30-second WebSocket reading and a 5-minute MDB reading both go in raw. Resampling is a derived view.
- Indexed on `(metric, timestamp_utc)` for query speed and on `(source_id, timestamp_utc)` for provenance lookups.

#### Canonical view (derived, "best known truth")
Not a stored table — a **materialized view** or stored function that resolves each `(metric, timestamp)` request using a **time-period priority map**:

```
2009-09 → 2018-08:           prefer cumulus_log
2018-08 → 2020-04-18:        prefer sdcard (if recovered), fallback ksan_metar
2020-04-19 → 2025-08-16 22Z: prefer mdb
2025-08-16 14-22Z:           OVERLAP — keep both, prefer mdb
2025-08-16 22Z → 2026-05-10: prefer amb_rest
2026-05-10 → now:            prefer amb_ws (live), backfill amb_rest
```

The priority map is **data, not code** — a config table or YAML. When new information arrives (SD card pulled, station #3 added, gap discovered), you update one row, not the importer.

### 3.4 Resampling and units

- **Native resolution preserved in `observations`.** Every reading kept at the rate the source recorded it.
- **Analyst UI queries through a resampler** that takes `(metric, time_range, target_resolution)` and aggregates on demand using SQL window functions. SQLite is fast enough for this; if it isn't, DuckDB drops in cleanly.
- **Units normalized to imperial on ingest** (project preference; matches user's existing mental model and the AmbientWeather native format). The MDB importer's main job is the metric-×10 → imperial conversion. Raw values may be retained in `raw_json`.
- **Sentinel-value detection:** the MDB uses values like `255` for "no data" in some columns. Importers map these to `NULL`.

### 3.5 Importers vs. resolver — separate concerns

- **Importer:** per-source. Knows the wire format, the units, the quirks. Outputs into `observations`. One importer per `kind`.
- **Resolver:** source-agnostic. Reads the priority map and the observations and returns the canonical view. Swappable independently of any importer.

This separation is what makes adding station #3 (or recovering the SD card) cheap.

### 3.6 External / forecast data (Phase 5 prep)

Same `observations` table, additional `kind` values (e.g., `nws_forecast`, `open_meteo`, `metar_kmyf`). The priority map decides whether external sources are eligible for the canonical view (e.g., gap-fill only) or never preferred over station data.

---

## 4. Phases

| # | Name | Goal |
|---|---|---|
| 0 | **Data archaeology** *(in progress)* | Catalog every source, characterize formats, rescue at-risk data (Ambient REST), pull SD card, scan Cumulus folder. Lock the schema and priority map. |
| 1 | The Bermuda Fish Tank | Photorealistic live-data dashboard. Build SVG/Canvas gauge components. Ride the existing WebSocket. |
| 2 | The Memory Bank | Persist live data into SQLite using the locked schema. Display today's live extremes. |
| 3 | The Time Machine | Historical importers (MDB → Cumulus → SD card → external gap-fill). Build canonical-view resolver. Validate via overlap zones. |
| 4 | The Analyst | Second UI mode: scrubbable historical charts, Wind Run, NOAA reports, exports. |
| 5 | The Oracle | Python sidecar. Hyper-local AI forecasting. Compare against external forecasts as ground truth. |

**Phase 0 was inserted ahead of Phase 1** because the original plan would have written the SQLite layer twice — once for live, then refactored once historical sources revealed their full complexity. Lock the schema first.

---

## 5. Open questions / known unknowns

1. **SD card depth and format** — needs physical pull and characterization. Now *essential*, not optional: validation revealed the MDB era has huge internal holes (620 days missing May 2020 → Feb 2022, ~130 days late 2022, ~30-day chunks elsewhere). Total archive gap across 17 years: **1,596 days**, mostly 2018–2022. See `data/DATA_REPORT.md` §2 for the full gap inventory.
2. **KSAN METAR ingest** — exact NCEI dataset to use (ISD-Lite vs. ASOS 5-minute), automation vs. one-shot CSV download, and how to flag off-site data in `quality_flag`. Scope now includes the MDB-era internal gaps, not just 2018-2020.
3. **Cumulus folder integrity** — confirmed runnable in the Cumulus app; per-file/per-month integrity not yet spot-checked at the file level. Risk of partial months, encoding issues, or year-2038-style date quirks.
4. **Station #3 model** — unknown; affects whether new sources are likely to be Ambient-cloud-compatible or need a fresh importer kind.
5. **Display target** — currently a desktop monitor. Future possibility: dedicated always-on small screen (Raspberry Pi, etc.).

---

## 6. Repository layout

```
SoledadWX/
├── ARCHITECTURE.md           ← this file
├── README.md                 ← quick orientation, points here
├── soledadwx-ui/             ← Tauri + React + Rust app (the product)
│   ├── src/                  ← React frontend
│   ├── src-tauri/            ← Rust backend
│   └── src-tauri/.env        ← API keys (gitignored)
├── scripts/                  ← one-off utilities (rescue, importers-in-development)
│   └── rescue_ambient.py
├── Legacy/                   ← all source data, organized by source
│   ├── Cumulus-Historical-Data/      ← 2010–2018 plain-text logs
│   ├── EasyWeatherIP-Historical-Data/← HP2000*.mdb files
│   └── AmbientWeather-Rescue/        ← REST dump (one JSON per page)
├── Dashboard/                ← visual references (barograph imagery, layout sketches)
└── Archive_TracerBullet/     ← deprecated Python/PyQt MVP, kept for reference
```
