"""
Import neighbor WU PWS gap-fill (Legacy/WU-Neighbors/<STID>/) into observations.

Reuses import_wu.extract() for field mapping. Each station folder maps to its
own source kind so the fill is fully traceable and can be excluded from any
analysis (e.g. the Oracle) that wants on-site data only. Idempotent.

Also refreshes source_priority from wxdb.PRIORITY (neighbors were added).

Usage:
    python scripts/import_wu_neighbor.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wxdb
from import_wu import extract

NEIGHBOR_ROOT = wxdb.ROOT / "Legacy" / "WU-Neighbors"
# folder name -> source kind
STATION_SOURCE = {
    "KCASANDI354": "wu_ksandi354",
    "KCASANDI4366": "wu_ksandi4366",
}


def main() -> int:
    conn = wxdb.get_conn()
    wxdb.ensure_schema(conn)
    # Refresh priority map (neighbors added; INSERT OR IGNORE won't update it).
    conn.execute("DELETE FROM source_priority")
    wxdb.ensure_schema(conn)
    mids = wxdb.metric_ids(conn)

    grand_inserted = 0
    for folder, kind in STATION_SOURCE.items():
        sid = wxdb.source_id(conn, kind)
        files = sorted((NEIGHBOR_ROOT / folder).glob("*.json"))
        n_recs = n_inserted = n_qc = 0
        batch = []
        for f in files:
            for rec in json.loads(f.read_text(encoding="utf-8")).get("observations") or []:
                if rec.get("qcStatus") == 0:
                    n_qc += 1
                    continue
                ts = rec.get("epoch")
                if ts is None:
                    continue
                ts = int(ts)
                if ts > 100_000_000_000:  # ms epochs in older WU records
                    ts //= 1000
                n_recs += 1
                for canon, val in extract(rec):
                    batch.append((mids[canon], ts, sid, val))
            if len(batch) >= 50_000:
                n_inserted += wxdb.insert_observations(conn, batch)
                batch.clear()
        if batch:
            n_inserted += wxdb.insert_observations(conn, batch)
        conn.commit()
        rng = conn.execute(
            "SELECT datetime(MIN(ts_utc),'unixepoch'), datetime(MAX(ts_utc),'unixepoch') "
            "FROM observations WHERE source_id=?", (sid,)
        ).fetchone()
        print(f"{kind:16} files={len(files):3} records={n_recs:5} inserted={n_inserted:6} "
              f"qc_skip={n_qc:4}  {rng[0]} -> {rng[1]}")
        grand_inserted += n_inserted

    print(f"Total neighbor rows inserted: {grand_inserted}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
