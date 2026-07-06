# SoledadWX

A desktop weather station application for Mount Soledad, La Jolla.

Two modes in one app: a photorealistic skeuomorphic dashboard for ambient viewing ("Bermuda Fish Tank"), and a data-dense analytical interface for diving into 17 years of hyper-local history ("Analyst"). Capstoned by hyper-local AI forecasting trained on that archive.

The full vision, technology choices, and data architecture are in **[ARCHITECTURE.md](ARCHITECTURE.md)** — start there.

---

## Status — May 2026

**Phase 0–2 complete: the data engine is built.** *(July 2026 sprint)*

The archive holds **11.7M observations spanning Sep 2009 → present**, assembled from three sources, unit-verified, gap-mapped, and continuously extended by a live recorder inside the Tauri app. See `data/DATA_REPORT.md` for the validation report. Next up: KSAN gap-fill, SD card recovery, and the Fish Tank UI (Phase 1 visuals — deliberately deferred; the aesthetic needs iterative design, not sprint coding).

| Component | Status |
|---|---|
| Live AmbientWeather WebSocket (Rust) | ✅ Working |
| Live recorder (WebSocket → SQLite archive) | ✅ Working — every reading persisted |
| Telemetry firehose UI + archive status bar | ✅ Working (placeholder, not the final design) |
| AmbientWeather REST historical rescue | ✅ Complete (Aug 2025 → Jul 2026, re-runnable) |
| HP2000-history.mdb (2020–2025) | ✅ Verified readable via ODBC |
| Cumulus historical logs (2009–2018) | ✅ Confirmed solid via Cumulus app; file-level inventory pending |
| SQLite archive (11.7M observations, 2009→present) | ✅ Built + validated — see `data/DATA_REPORT.md` |
| Historical importers (Cumulus, MDB, Ambient) | ✅ Complete, idempotent, unit-verified |
| Canonical resolver + resampler | ✅ Working (`scripts/wxquery.py`) |
| WU KCALAJOL6 gap-fill (same roof, 2012-2025) | ✅ Imported — 1,596 missing days reduced to 340; 185 days await next WU quota |
| WS-1002 SD card | ❌ Dead end — card checked, no data |
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
