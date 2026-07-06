"""
Import the AmbientWeather REST rescue dump into the observations table.

Reads every Legacy/AmbientWeather-Rescue/page_*.json (verbatim API pages),
de-duplicates by timestamp (pages overlap at boundaries, and the rescue was
re-run with shifted page boundaries), and inserts long-format rows.

Idempotent: INSERT OR IGNORE on (metric_id, ts_utc, source_id).

Usage:
    python scripts/import_ambient.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wxdb

RESCUE_DIR = wxdb.ROOT / "Legacy" / "AmbientWeather-Rescue"

# Ambient JSON key -> canonical metric name. Identity for most; the derived
# temps get explicit canonical names.
KEY_MAP = {
    "tempf": "tempf",
    "humidity": "humidity",
    "tempinf": "tempinf",
    "humidityin": "humidityin",
    "windspeedmph": "windspeedmph",
    "windgustmph": "windgustmph",
    "maxdailygust": "maxdailygust",
    "winddir": "winddir",
    "baromrelin": "baromrelin",
    "baromabsin": "baromabsin",
    "rainratein": "rainratein",
    "hourlyrainin": "hourlyrainin",
    "dailyrainin": "dailyrainin",
    "weeklyrainin": "weeklyrainin",
    "monthlyrainin": "monthlyrainin",
    "yearlyrainin": "yearlyrainin",
    "solarradiation": "solarradiation",
    "uv": "uv",
    "dewPoint": "dewpointf",
    "windchillf": "windchillf",
    "heatindexf": "heatindexf",
    "feelsLike": "feelslikef",
    "dewPointin": "dewpointinf",
    "feelsLikein": "feelslikeinf",
}


def main() -> int:
    conn = wxdb.get_conn()
    wxdb.ensure_schema(conn)
    mids = wxdb.metric_ids(conn)
    sid = wxdb.source_id(conn, "amb_rest")

    pages = sorted(RESCUE_DIR.glob("page_*.json"))
    if not pages:
        print(f"No pages found in {RESCUE_DIR}")
        return 1

    total_records = 0
    total_inserted = 0
    skipped_keys: set[str] = set()

    for page_path in pages:
        records = json.loads(page_path.read_text(encoding="utf-8"))
        rows = []
        for rec in records:
            ts = rec.get("dateutc")
            if ts is None:
                continue
            ts_sec = int(ts) // 1000
            for key, val in rec.items():
                canon = KEY_MAP.get(key)
                if canon is None:
                    if isinstance(val, (int, float)):
                        skipped_keys.add(key)
                    continue
                if isinstance(val, (int, float)):
                    rows.append((mids[canon], ts_sec, sid, float(val)))
        total_records += len(records)
        total_inserted += wxdb.insert_observations(conn, rows)

    conn.commit()

    n_ts = conn.execute(
        "SELECT COUNT(DISTINCT ts_utc) FROM observations WHERE source_id=?", (sid,)
    ).fetchone()[0]
    n_obs = conn.execute(
        "SELECT COUNT(*) FROM observations WHERE source_id=?", (sid,)
    ).fetchone()[0]
    rng = conn.execute(
        "SELECT datetime(MIN(ts_utc),'unixepoch'), datetime(MAX(ts_utc),'unixepoch') "
        "FROM observations WHERE source_id=?",
        (sid,),
    ).fetchone()

    print(f"Pages read:            {len(pages)}")
    print(f"Records seen:          {total_records} (incl. page-boundary duplicates)")
    print(f"Rows inserted this run:{total_inserted}")
    print(f"Distinct timestamps:   {n_ts}")
    print(f"Total amb_rest rows:   {n_obs}")
    print(f"Time range (UTC):      {rng[0]} -> {rng[1]}")
    if skipped_keys:
        print(f"Unmapped numeric keys: {sorted(skipped_keys)}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
