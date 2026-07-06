# SoledadWX

A desktop weather station application for Mount Soledad, La Jolla.

Two modes in one app: a photorealistic skeuomorphic dashboard for ambient viewing ("Bermuda Fish Tank"), and a data-dense analytical interface for diving into 17 years of hyper-local history ("Analyst"). Capstoned by hyper-local AI forecasting trained on that archive.

The full vision, technology choices, and data architecture are in **[ARCHITECTURE.md](ARCHITECTURE.md)** — start there.

---

## Status — May 2026

**Phase 0 — Data archaeology** *(active)*

The live-data pipeline works end-to-end (Rust WebSocket → React UI), but no persistence layer or visual design has been built yet. Current focus is cataloging every source of historical weather data and rescuing at-risk data before it ages out of providers' rolling windows.

| Component | Status |
|---|---|
| Live AmbientWeather WebSocket (Rust) | ✅ Working |
| Telemetry firehose UI (React) | ✅ Working (placeholder, not the final design) |
| AmbientWeather REST historical rescue | ✅ Complete (267 pages, ~76,548 records, Aug 2025 → May 2026) |
| HP2000-history.mdb (2020–2025) | ✅ Verified readable via ODBC |
| Cumulus historical logs (2009–2018) | ✅ Confirmed solid via Cumulus app; file-level inventory pending |
| SQLite archive (11.7M observations, 2009→present) | ✅ Built + validated — see `data/DATA_REPORT.md` |
| Historical importers (Cumulus, MDB, Ambient) | ✅ Complete, idempotent, unit-verified |
| Canonical resolver + resampler | ✅ Working (`scripts/wxquery.py`) |
| KSAN METAR gap-fill (1,596 missing days, mostly 2018–2022) | ⏳ Planned via NOAA/NCEI |
| WS-1002 SD card | ⏳ Not yet pulled — now essential (MDB era has big internal holes) |
| Photorealistic gauge UI | ⏳ Phase 1 |
| Historical importers | ⏳ Phase 3 |
| Analyst UI | ⏳ Phase 4 |
| AI forecasting | ⏳ Phase 5 |

---

## Stack

- **Frontend:** Tauri + React (TypeScript)
- **Backend:** Rust
- **Storage:** SQLite (planned)
- **AI/ML:** Python sidecar (Phase 5+)

See [ARCHITECTURE.md §2](ARCHITECTURE.md#2-technology-stack) for rationale.

---

## Running the app

Prerequisites: Node.js 20+, Rust toolchain, Tauri prerequisites for Windows ([tauri.app](https://tauri.app/start/prerequisites/)).

```powershell
cd soledadwx-ui
npm install
npm run tauri dev
```

The app expects `soledadwx-ui/src-tauri/.env` with:

```
AMBIENT_API_KEY=...
AMBIENT_APP_KEY=...
```

Get keys at [ambientweather.net/account](https://ambientweather.net/account).

---

## Repository layout

See [ARCHITECTURE.md §6](ARCHITECTURE.md#6-repository-layout).

---

## License

To be determined.
