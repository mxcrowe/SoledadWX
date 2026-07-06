"""
Weather Underground PWS history rescue for KCALAJOL6 ("Mount Soledad South").

The station uploaded to WU from Nov 29, 2012 (old Zephyr instrument) through
Jun 29, 2018, and again from Sep 27, 2018 (WS-1002) onward — same roof, same
site. This is on-site data that patches the archive's gaps (see
data/DATA_REPORT.md §2), including the 2018-2022 holes.

Strategy: query our own archive for days with thin canonical coverage, then
fetch ONLY those days from WU (history/all returns one local day of ~5-min
records per call). Raw JSON saved verbatim to Legacy/WU-Rescue/; importer
comes separately.

Free-tier etiquette: <=30 calls/min, <=1500 calls/day. This script throttles
to ~25/min and stops after MAX_CALLS; re-run tomorrow to continue (existing
files are skipped, so it resumes where it left off).

Usage:
    python scripts/rescue_wunderground.py [max_calls]

Env (soledadwx-ui/src-tauri/.env or environment):
    WU_API_KEY
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wxdb

STATION_ID = "KCALAJOL6"
ENV_FILE = wxdb.ROOT / "soledadwx-ui" / "src-tauri" / ".env"
OUT_DIR = wxdb.ROOT / "Legacy" / "WU-Rescue"
API = "https://api.weather.com/v2/pws/history/all"

WU_START = date(2012, 11, 29)   # first day with table data on WU
WU_END = date(2025, 8, 16)      # after this, amb_rest/amb_ws cover everything
THIN_THRESHOLD = 24             # fewer canonical tempf obs than this = "thin" day
SLEEP_SECONDS = 2.5             # ~24 calls/min
DEFAULT_MAX_CALLS = 1400        # stay under the 1500/day ceiling


def load_key() -> str | None:
    if os.environ.get("WU_API_KEY"):
        return os.environ["WU_API_KEY"]
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if line.strip().startswith("WU_API_KEY="):
                return line.split("=", 1)[1].strip()
    return None


def thin_days(conn) -> list[date]:
    """Days in [WU_START, WU_END] where canonical tempf coverage is thin."""
    # Count per local-ish day (UTC day is fine at this granularity — the gaps
    # are weeks long, an 8-hour edge effect doesn't matter).
    rows = conn.execute(
        """
        SELECT date(o.ts_utc,'unixepoch') AS d, COUNT(*) AS n
        FROM canonical_observations o
        JOIN metrics m ON m.id = o.metric_id
        WHERE m.name = 'tempf'
          AND o.ts_utc >= strftime('%s', ?) AND o.ts_utc < strftime('%s', ?)
        GROUP BY d
        """,
        (WU_START.isoformat(), (WU_END + timedelta(days=1)).isoformat()),
    ).fetchall()
    counts = {r[0]: r[1] for r in rows}
    out = []
    day = WU_START
    while day <= WU_END:
        if counts.get(day.isoformat(), 0) < THIN_THRESHOLD:
            out.append(day)
        day += timedelta(days=1)
    return out


def fetch_day(key: str, day: date) -> dict:
    qs = urllib.parse.urlencode({
        "stationId": STATION_ID,
        "format": "json",
        "units": "e",
        "numericPrecision": "decimal",
        "date": day.strftime("%Y%m%d"),
        "apiKey": key,
    })
    req = urllib.request.Request(f"{API}?{qs}", headers={"User-Agent": "SoledadWX-Rescue/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    key = load_key()
    if not key:
        print("ERROR: WU_API_KEY not set (env or soledadwx-ui/src-tauri/.env)")
        return 1
    max_calls = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_MAX_CALLS
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    conn = wxdb.get_conn()
    wxdb.ensure_schema(conn)
    days = thin_days(conn)
    conn.close()
    todo = [d for d in days if not (OUT_DIR / f"{STATION_ID}_{d:%Y%m%d}.json").exists()]
    print(f"Thin days in WU window: {len(days)}; not yet fetched: {len(todo)}; "
          f"this run will fetch up to {max_calls}.")

    calls = n_obs_total = n_empty = n_err = 0
    started = datetime.now()
    for day in todo:
        if calls >= max_calls:
            print(f"Reached per-run call cap ({max_calls}). Re-run to continue.")
            break
        try:
            data = fetch_day(key, day)
            calls += 1
        except Exception as e:
            calls += 1
            n_err += 1
            print(f"  {day}: ERROR {e}")
            time.sleep(SLEEP_SECONDS)
            continue
        obs = data.get("observations") or []
        fname = OUT_DIR / f"{STATION_ID}_{day:%Y%m%d}.json"
        fname.write_text(json.dumps(data), encoding="utf-8")
        n_obs_total += len(obs)
        if not obs:
            n_empty += 1
        if calls % 50 == 0:
            rate = calls / max(1, (datetime.now() - started).total_seconds() / 60)
            print(f"  ...{calls} calls, {n_obs_total} obs, {n_empty} empty days "
                  f"({rate:.0f} calls/min)")
        time.sleep(SLEEP_SECONDS)

    print(f"DONE this run: {calls} calls, {n_obs_total} observations, "
          f"{n_empty} empty days, {n_err} errors.")
    remaining = len(todo) - calls
    if remaining > 0:
        print(f"{remaining} days remain — re-run (quota resets daily).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
