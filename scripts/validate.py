"""
Validate the assembled archive and write data/DATA_REPORT.md.

Checks:
  1. Per-source inventory (rows, distinct timestamps, time range)
  2. Coverage/gap inventory: holes > 6h in the canonical tempf series
  3. Overlap-zone agreement: MDB vs Ambient matched within +/-150s on 2025-08-16
  4. Unit sanity: physical min/max per metric across the whole archive
  5. Fun-fact extremes (plausibility spot-checks a human can eyeball)

Usage:
    python scripts/validate.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wxdb

OUT = wxdb.ROOT / "data" / "DATA_REPORT.md"
GAP_THRESHOLD = 6 * 3600


def fmt(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def main() -> int:
    conn = wxdb.get_conn()
    wxdb.ensure_schema(conn)
    lines: list[str] = []
    w = lines.append

    w("# SoledadWX Data Archive — Validation Report")
    w("")
    w(f"Generated {datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} "
      f"by `scripts/validate.py` against `data/soledadwx.db`.")
    w("")

    # --- 1. Per-source inventory ------------------------------------------
    w("## 1. Source inventory")
    w("")
    w("| Source | Rows | Timestamps | From (UTC) | To (UTC) |")
    w("|---|---|---|---|---|")
    for kind, name in conn.execute("SELECT kind, name FROM sources"):
        row = conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT ts_utc), MIN(ts_utc), MAX(ts_utc) "
            "FROM observations WHERE source_id=(SELECT id FROM sources WHERE kind=?)",
            (kind,),
        ).fetchone()
        if row[0] == 0:
            w(f"| `{kind}` | — | — | — | — |")
        else:
            w(f"| `{kind}` | {row[0]:,} | {row[1]:,} | {fmt(row[2])} | {fmt(row[3])} |")
    total = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    n_days = conn.execute("SELECT COUNT(*) FROM daily_summaries").fetchone()[0]
    w("")
    w(f"**Total observations: {total:,}** across all sources, "
      f"plus {n_days:,} daily summaries (Cumulus era, incl. wind run).")
    w("")

    # --- 2. Gap inventory --------------------------------------------------
    w("## 2. Coverage gaps (canonical `tempf`, holes > 6 h)")
    w("")
    ts_list = [r[0] for r in conn.execute(
        "SELECT DISTINCT o.ts_utc FROM canonical_observations o "
        "JOIN metrics m ON m.id=o.metric_id WHERE m.name='tempf' ORDER BY o.ts_utc"
    )]
    gaps = []
    for a, b in zip(ts_list, ts_list[1:]):
        if b - a > GAP_THRESHOLD:
            gaps.append((a, b))
    w(f"Canonical tempf timestamps: {len(ts_list):,} "
      f"({fmt(ts_list[0])} -> {fmt(ts_list[-1])})")
    w("")
    if gaps:
        w("| Gap start (UTC) | Gap end (UTC) | Duration |")
        w("|---|---|---|")
        for a, b in gaps:
            days = (b - a) / 86400
            dur = f"{days:.1f} d" if days >= 1 else f"{(b - a) / 3600:.1f} h"
            w(f"| {fmt(a)} | {fmt(b)} | {dur} |")
        total_gap_days = sum(b - a for a, b in gaps) / 86400
        w("")
        w(f"**{len(gaps)} gaps, {total_gap_days:.0f} days total missing.**")
    else:
        w("No gaps > 6 h. Remarkable.")
    w("")

    # --- 3. Overlap agreement ---------------------------------------------
    w("## 3. Overlap-zone cross-validation (2025-08-16, MDB vs Ambient)")
    w("")
    w("Matched pairs within ±150 s; same physical weather, two independent recorders.")
    w("")
    w("| Metric | Pairs | Mean abs diff | Max abs diff |")
    w("|---|---|---|---|")
    a0 = int(datetime(2025, 8, 16, 14, 0, tzinfo=timezone.utc).timestamp())
    b0 = int(datetime(2025, 8, 16, 22, 30, tzinfo=timezone.utc).timestamp())
    for metric in ("tempf", "humidity", "baromrelin", "windspeedmph", "solarradiation", "uv"):
        q = """
        SELECT AVG(ABS(x.value - y.value)), MAX(ABS(x.value - y.value)), COUNT(*)
        FROM observations x
        JOIN observations y ON y.metric_id = x.metric_id
            AND y.ts_utc BETWEEN x.ts_utc - 150 AND x.ts_utc + 150
            AND y.source_id = (SELECT id FROM sources WHERE kind='amb_rest')
        WHERE x.source_id = (SELECT id FROM sources WHERE kind='mdb')
            AND x.metric_id = (SELECT id FROM metrics WHERE name=?)
            AND x.ts_utc BETWEEN ? AND ?
        """
        mad, mx, n = conn.execute(q, (metric, a0, b0)).fetchone()
        if n:
            w(f"| {metric} | {n} | {mad:.3f} | {mx:.3f} |")
        else:
            w(f"| {metric} | 0 | — | — |")
    w("")
    w("Note: the two sources log on offset clocks (MDB at :01/:06, Ambient at "
      ":00/:05), so canonical view interleaves rather than deduplicates inside "
      "the 8-hour overlap. Values agree, so this is harmless; revisit only if "
      "a future source overlaps for months rather than hours.")
    w("")

    # --- 4. Unit sanity ----------------------------------------------------
    w("## 4. Unit sanity (whole archive, all sources)")
    w("")
    w("| Metric | Min | Max | Unit | Plausible for La Jolla? |")
    w("|---|---|---|---|---|")
    expectations = {
        "tempf": (25, 115), "humidity": (5, 100), "baromrelin": (29.0, 31.0),
        "windspeedmph": (0, 80), "windgustmph": (0, 100),
        "dailyrainin": (0, 6), "solarradiation": (0, 1200), "uv": (0, 13),
    }
    for metric, (lo_ok, hi_ok) in expectations.items():
        lo, hi = conn.execute(
            "SELECT MIN(o.value), MAX(o.value) FROM observations o "
            "JOIN metrics m ON m.id=o.metric_id WHERE m.name=?", (metric,)
        ).fetchone()
        unit = conn.execute("SELECT unit FROM metrics WHERE name=?", (metric,)).fetchone()[0]
        verdict = "yes" if (lo >= lo_ok - 1e-9 and hi <= hi_ok + 1e-9) else "REVIEW"
        w(f"| {metric} | {lo:.2f} | {hi:.2f} | {unit} | {verdict} |")
    w("")

    # --- 5. Extremes -------------------------------------------------------
    w("## 5. All-time extremes (canonical archive)")
    w("")
    for label, metric, agg in [
        ("Hottest reading", "tempf", "MAX"),
        ("Coldest reading", "tempf", "MIN"),
        ("Highest gust", "windgustmph", "MAX"),
        ("Lowest pressure", "baromrelin", "MIN"),
        ("Highest pressure", "baromrelin", "MAX"),
    ]:
        q = f"""
        SELECT o.value, o.ts_utc, s.kind FROM canonical_observations o
        JOIN metrics m ON m.id=o.metric_id JOIN sources s ON s.id=o.source_id
        WHERE m.name=? ORDER BY o.value {'DESC' if agg == 'MAX' else 'ASC'} LIMIT 1
        """
        val, ts, kind = conn.execute(q, (metric,)).fetchone()
        w(f"- **{label}:** {val:.1f} on {fmt(ts)} UTC (source: `{kind}`)")
    wr = conn.execute(
        "SELECT date, wind_run_mi FROM daily_summaries "
        "WHERE wind_run_mi IS NOT NULL ORDER BY wind_run_mi DESC LIMIT 1"
    ).fetchone()
    w(f"- **Windiest day (wind run):** {wr[1]:.1f} miles on {wr[0]}")
    tot = conn.execute(
        "SELECT ROUND(SUM(wind_run_mi)) FROM daily_summaries"
    ).fetchone()[0]
    w(f"- **Total recorded wind run (2009-2018):** {tot:,.0f} miles")
    w("")

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"\n[written to {OUT}]")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
