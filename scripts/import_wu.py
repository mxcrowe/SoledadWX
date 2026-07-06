"""
Import Weather Underground PWS history (KCALAJOL6) into the observations table.

Reads Legacy/WU-Rescue/KCALAJOL6_YYYYMMDD.json (one file per fetched day, raw
API responses from scripts/rescue_wunderground.py). Records are 5-minute
aggregates; we take Avg for level metrics and High for gusts/solar/UV.
Already imperial. `epoch` is UTC seconds. Records with qcStatus == 0 (failed
WU quality control) are skipped; -1 (unchecked) and 1 (passed) are kept.

Also refreshes the source_priority map from wxdb.PRIORITY (the map gained
wu_pws rows; old seeded rows must be replaced, not merged).

Idempotent via INSERT OR IGNORE.

Usage:
    python scripts/import_wu.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wxdb

RESCUE_DIR = wxdb.ROOT / "Legacy" / "WU-Rescue"

BOUNDS = {
    "tempf": (20.0, 130.0), "dewpointf": (-40.0, 100.0),
    "windchillf": (-40.0, 130.0), "heatindexf": (-40.0, 150.0),
    "humidity": (1.0, 100.0),
    "windspeedmph": (0.0, 150.0), "windgustmph": (0.0, 200.0),
    "winddir": (0.0, 360.0), "baromrelin": (27.0, 32.0),
    "rainratein": (0.0, 12.0), "dailyrainin": (0.0, 15.0),
    "solarradiation": (0.0, 1500.0), "uv": (0.0, 13.0),
}


def extract(rec: dict) -> list[tuple[str, float]]:
    imp = rec.get("imperial") or {}
    out = []

    def add(canon: str, val):
        if val is None:
            return
        v = float(val)
        lo, hi = BOUNDS[canon]
        if lo <= v <= hi:
            out.append((canon, v))

    add("tempf", imp.get("tempAvg"))
    add("humidity", rec.get("humidityAvg"))
    add("dewpointf", imp.get("dewptAvg"))
    add("windspeedmph", imp.get("windspeedAvg"))
    add("windgustmph", imp.get("windgustHigh"))
    add("winddir", rec.get("winddirAvg"))
    add("windchillf", imp.get("windchillAvg"))
    add("heatindexf", imp.get("heatindexAvg"))
    add("solarradiation", rec.get("solarRadiationHigh"))
    add("uv", rec.get("uvHigh"))
    add("rainratein", imp.get("precipRate"))
    add("dailyrainin", imp.get("precipTotal"))
    pmax, pmin = imp.get("pressureMax"), imp.get("pressureMin")
    if pmax is not None and pmin is not None:
        add("baromrelin", (float(pmax) + float(pmin)) / 2.0)
    return out


def main() -> int:
    conn = wxdb.get_conn()
    wxdb.ensure_schema(conn)
    # Refresh the priority map: the seeded rows changed (wu_pws added,
    # sdcard retired) and ensure_schema's INSERT OR IGNORE won't replace them.
    conn.execute("DELETE FROM source_priority")
    wxdb.ensure_schema(conn)

    mids = wxdb.metric_ids(conn)
    sid = wxdb.source_id(conn, "wu_pws")

    files = sorted(RESCUE_DIR.glob("KCALAJOL6_*.json"))
    n_files = n_recs = n_inserted = n_qc_fail = 0
    batch = []
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        obs = data.get("observations") or []
        n_files += 1
        for rec in obs:
            if rec.get("qcStatus") == 0:
                n_qc_fail += 1
                continue
            ts = rec.get("epoch")
            if ts is None:
                continue
            ts = int(ts)
            if ts > 100_000_000_000:  # older WU records use millisecond epochs
                ts //= 1000
            n_recs += 1
            for canon, val in extract(rec):
                batch.append((mids[canon], int(ts), sid, val))
        if len(batch) >= 50_000:
            n_inserted += wxdb.insert_observations(conn, batch)
            batch.clear()
    if batch:
        n_inserted += wxdb.insert_observations(conn, batch)
    conn.commit()

    n_ts = conn.execute(
        "SELECT COUNT(DISTINCT ts_utc) FROM observations WHERE source_id=?", (sid,)
    ).fetchone()[0]
    rng = conn.execute(
        "SELECT datetime(MIN(ts_utc),'unixepoch'), datetime(MAX(ts_utc),'unixepoch') "
        "FROM observations WHERE source_id=?", (sid,)
    ).fetchone()

    print(f"Files read:             {n_files}")
    print(f"Records kept:           {n_recs} (qc-failed skipped: {n_qc_fail})")
    print(f"Rows inserted this run: {n_inserted}")
    print(f"Distinct timestamps:    {n_ts}")
    print(f"Time range (UTC):       {rng[0]} -> {rng[1]}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
