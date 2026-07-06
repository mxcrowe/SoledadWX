"""
MSDSD (Mt Soledad mesonet) historical rescue via the Synoptic Data API.

MSDSD sits ~0.5 km from the station — same ridge, same microclimate — and
reports temp/dewpoint/RH/wind (no rain, solar, or pressure). Its archive is
the primary gap-fill for the 2018-2022 holes documented in data/DATA_REPORT.md.

Same philosophy as rescue_ambient.py: dump raw API responses verbatim to
Legacy/MSDSD-Rescue/, one file per calendar year, no parsing and no schema
commitment. The importer comes later, once we've eyeballed the format.

Run repeatedly: complete past years are skipped; the current year re-fetches.

Usage:
    python scripts/rescue_msdsd.py [start_year] [end_year]
    (defaults: 2009 -> current year)

Env (read from soledadwx-ui/src-tauri/.env or the environment):
    SYNOPTIC_TOKEN
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / "soledadwx-ui" / "src-tauri" / ".env"
OUT_DIR = ROOT / "Legacy" / "MSDSD-Rescue"
STATION = "MSDSD"
API = "https://api.synopticdata.com/v2/stations/timeseries"
META_API = "https://api.synopticdata.com/v2/stations/metadata"
SLEEP_SECONDS = 2.0  # be polite; free tier


def load_token() -> str | None:
    if os.environ.get("SYNOPTIC_TOKEN"):
        return os.environ["SYNOPTIC_TOKEN"]
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if line.strip().startswith("SYNOPTIC_TOKEN="):
                return line.split("=", 1)[1].strip()
    return None


def get(url: str, params: dict) -> dict:
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{url}?{qs}", headers={"User-Agent": "SoledadWX-Rescue/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    token = load_token()
    if not token:
        print("ERROR: SYNOPTIC_TOKEN not set (env or soledadwx-ui/src-tauri/.env)")
        return 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    this_year = datetime.now(tz=timezone.utc).year
    start_year = int(sys.argv[1]) if len(sys.argv) > 1 else 2009
    end_year = int(sys.argv[2]) if len(sys.argv) > 2 else this_year

    # Metadata first: period of record tells us which years even exist.
    meta = get(META_API, {"token": token, "stid": STATION, "complete": "1"})
    (OUT_DIR / "_metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    try:
        st = meta["STATION"][0]
        por = st.get("PERIOD_OF_RECORD", {})
        print(f"Station: {st.get('NAME')} ({st.get('STID')})  "
              f"lat={st.get('LATITUDE')} lon={st.get('LONGITUDE')} elev={st.get('ELEVATION')} ft")
        print(f"Period of record: {por.get('start')} -> {por.get('end')}")
    except (KeyError, IndexError):
        print("WARNING: unexpected metadata shape; see _metadata.json")

    total = 0
    for year in range(start_year, end_year + 1):
        fname = OUT_DIR / f"msdsd_{year}.json"
        if fname.exists() and year < this_year:
            print(f"  skip {year} (already on disk)")
            continue
        params = {
            "token": token,
            "stid": STATION,
            "start": f"{year}01010000",
            "end": f"{year}12312359",
            "obtimezone": "utc",
            "units": "english",
        }
        try:
            data = get(API, params)
        except Exception as e:
            print(f"  {year}: request failed ({e}) — continuing")
            time.sleep(SLEEP_SECONDS)
            continue
        summary = data.get("SUMMARY", {})
        n = summary.get("NUMBER_OF_OBJECTS", 0)
        if data.get("STATION"):
            n_obs = len(data["STATION"][0].get("OBSERVATIONS", {}).get("date_time", []))
        else:
            n_obs = 0
        fname.write_text(json.dumps(data), encoding="utf-8")
        total += n_obs
        print(f"  {year}: {n_obs} observations ({summary.get('RESPONSE_MESSAGE', 'OK')})")
        time.sleep(SLEEP_SECONDS)

    print(f"DONE. ~{total} observations fetched this run -> {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
