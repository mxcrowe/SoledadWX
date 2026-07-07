"""
Fetch specific gap windows from neighbor WU PWS stations on Mount Soledad.

Unlike rescue_wunderground.py (which pulls the primary station KCALAJOL6's
whole history), this grabs only the date ranges needed to fill the archive's
remaining station-dark gaps, from nearby (~1 km) stations sharing the same
marine-layer microclimate. Each fetch carries a 1-day margin so boundary days
overlap existing data for cross-validation.

Raw JSON saved verbatim to Legacy/WU-Neighbors/<STID>/. Idempotent.

Usage:
    python scripts/rescue_wu_neighbor.py
"""

from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wxdb
from rescue_wunderground import load_key

OUT_ROOT = wxdb.ROOT / "Legacy" / "WU-Neighbors"
API = "https://api.weather.com/v2/pws/history/all"
SLEEP = 2.5

# station -> list of (start, end) inclusive windows to fetch (1-day margin
# already baked into these bounds vs the DATA_REPORT gap edges).
PLAN: dict[str, list[tuple[str, str]]] = {
    "KCASANDI354":  [("2016-05-23", "2016-06-24")],           # 2016 gap
    "KCASANDI4366": [("2018-07-07", "2018-07-17"),            # 2018 July gap
                     ("2018-08-27", "2018-09-28")],           # 2018 instrument swap
}


def daterange(a: str, b: str):
    d0 = date.fromisoformat(a)
    d1 = date.fromisoformat(b)
    while d0 <= d1:
        yield d0
        d0 += timedelta(days=1)


def fetch(key: str, stid: str, d: date) -> dict | None:
    qs = urllib.parse.urlencode({
        "stationId": stid, "format": "json", "units": "e",
        "numericPrecision": "decimal", "date": d.strftime("%Y%m%d"), "apiKey": key,
    })
    req = urllib.request.Request(f"{API}?{qs}", headers={"User-Agent": "SoledadWX-Rescue/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    key = load_key()
    if not key:
        print("ERROR: WU_API_KEY not set")
        return 1

    total_obs = calls = 0
    for stid, windows in PLAN.items():
        out = OUT_ROOT / stid
        out.mkdir(parents=True, exist_ok=True)
        for a, b in windows:
            for d in daterange(a, b):
                fname = out / f"{stid}_{d:%Y%m%d}.json"
                if fname.exists():
                    continue
                try:
                    data = fetch(key, stid, d)
                    calls += 1
                except Exception as e:
                    print(f"  {stid} {d}: ERROR {e}")
                    time.sleep(SLEEP)
                    continue
                obs = data.get("observations") or []
                fname.write_text(json.dumps(data), encoding="utf-8")
                total_obs += len(obs)
                time.sleep(SLEEP)
        n_files = len(list(out.glob("*.json")))
        print(f"{stid}: {n_files} day-files on disk")
    print(f"DONE. {calls} calls this run, {total_obs} observations fetched.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
