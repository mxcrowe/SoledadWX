"""
AmbientWeather REST rescue dump.

Pages backward through the user's full history (free tier ~= 1 year) and writes
each API response verbatim to disk as JSON. No parsing, no schema commitment —
just secure the bytes before they age out of Ambient's rolling window.

Run repeatedly: existing page files are skipped. Stops when the API returns
an empty page (= reached retention horizon).

Usage:
    python scripts/rescue_ambient.py

Env (read from soledadwx-ui/src-tauri/.env):
    AMBIENT_API_KEY
    AMBIENT_APP_KEY
"""

from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / "soledadwx-ui" / "src-tauri" / ".env"
OUT_DIR = ROOT / "Legacy" / "AmbientWeather-Rescue"
LOG_FILE = OUT_DIR / "_rescue.log"

API_BASE = "https://rt.ambientweather.net/v1"
PAGE_LIMIT = 288  # API max
SLEEP_SECONDS = 1.1  # Ambient asks for <= 1 req/sec per key
MAX_PAGES = 2000  # safety stop (~1.5 years at 288/page/day)


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env


def log(msg: str) -> None:
    stamp = datetime.now().strftime("%H:%M:%S")
    line = f"[{stamp}] {msg}"
    print(line, flush=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def http_get_json(url: str) -> list | dict:
    req = urllib.request.Request(url, headers={"User-Agent": "SoledadWX-Rescue/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_devices(api_key: str, app_key: str) -> list:
    qs = urllib.parse.urlencode({"applicationKey": app_key, "apiKey": api_key})
    return http_get_json(f"{API_BASE}/devices?{qs}")


def fetch_page(mac: str, api_key: str, app_key: str, end_date_ms: int | None) -> list:
    params = {
        "applicationKey": app_key,
        "apiKey": api_key,
        "limit": PAGE_LIMIT,
    }
    if end_date_ms is not None:
        params["endDate"] = end_date_ms
    qs = urllib.parse.urlencode(params)
    return http_get_json(f"{API_BASE}/devices/{urllib.parse.quote(mac)}?{qs}")


def fmt_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    env = load_env()
    api_key = env.get("AMBIENT_API_KEY")
    app_key = env.get("AMBIENT_APP_KEY")
    if not api_key or not app_key:
        log("ERROR: missing AMBIENT_API_KEY or AMBIENT_APP_KEY")
        return 1

    log("Listing devices...")
    devices = get_devices(api_key, app_key)
    if not devices:
        log("ERROR: no devices returned")
        return 1
    for d in devices:
        log(f"  device: mac={d.get('macAddress')} name={d.get('info', {}).get('name')}")
    mac = devices[0]["macAddress"]
    log(f"Using MAC: {mac}")
    time.sleep(SLEEP_SECONDS)

    end_date_ms: int | None = None
    pages = 0
    total_records = 0

    while pages < MAX_PAGES:
        page = fetch_page(mac, api_key, app_key, end_date_ms)
        if not page:
            log("Empty page returned — reached retention horizon. Done.")
            break

        # Records are sorted DESC by dateutc — newest first, oldest last.
        newest_ms = page[0]["dateutc"]
        oldest_ms = page[-1]["dateutc"]

        fname = f"page_{pages:04d}_{fmt_iso(oldest_ms)}_to_{fmt_iso(newest_ms)}.json"
        fpath = OUT_DIR / fname
        if fpath.exists():
            log(f"  skip existing {fname} (n={len(page)})")
        else:
            fpath.write_text(json.dumps(page), encoding="utf-8")
            log(f"  wrote {fname} (n={len(page)})")

        total_records += len(page)
        pages += 1

        # Step backward: next page should END just before this page's oldest record.
        # Subtract 1 ms so we don't re-fetch the same boundary record.
        end_date_ms = oldest_ms - 1
        time.sleep(SLEEP_SECONDS)

    log(f"DONE. {pages} pages, ~{total_records} records.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
