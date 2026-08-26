"""
Recover Zephyr-era humidity by calibrating it against MSDSD.

THE PROBLEM. The Zephyr hygrometer (source 1, 2009-2018) does not have an
offset or a drift. It has a SLOPE error pivoting near 55% RH: it reads too
dry in dry air and too wet in moist air, over-responding in between. Measured
against MSDSD by RH bin:

    MSDSD RH   original(2011-14)  healthy(Dec16-Jun17)  drifting(2017-18)
    20-30%          -11.7               -11.5                -11.8
    40-50%           -7.4                -7.0                 -0.1
    60-70%          +15.2                -2.7                +15.5
    70-80%          +21.6                -0.4                +17.1
    90-100%          -1.6                +4.0                 +5.1

The November 2016 replacement flattened the slope; it did not remove it. The
dry-end bias is present in all three eras, healthy included.

WHY THIS IS RECOVERABLE. A slope error is monotonic and measurable, so it is
invertible. Saturation is not — once a sensor rails at 100 there is no
information left to recover. This one never railed; it distorted. We have
~168,000 Zephyr readings paired to MSDSD within 10 minutes to learn the
distortion from.

WHAT THIS IS NOT. It is not substitution. Replacing Zephyr's values with
MSDSD's would throw away the thing Zephyr uniquely has: readings at its own
timestamps, catching local variation a station 559 m away never sampled.
(The dry line of 2026-08-26 is the standing proof that 559 m and 187 ft of
elevation is enough to put two stations in different air.) So the reading is
KEPT and its transfer function corrected.

METHOD, per calendar month:
  1. Pair each Zephyr RH sample to the nearest MSDSD sample within 10 min.
  2. Refuse the month unless it is actually recoverable — see REFUSAL below.
  3. Quantile-map: match the month percentiles of the Zephyr distribution onto the
     same percentiles of MSDSD's, piecewise-linear between knots. This undoes
     a monotonic distortion without assuming its shape.
  4. That lands us in MSDSD's frame, which is 559 m away and 187 ft lower, so
     add back the genuine site difference measured in the HEALTHY window
     (Dec 2016 - Jun 2017) as a function of RH. The result is an estimate of
     what a working hygrometer AT THIS SITE would have read.

REFUSAL. A month is left uncorrected when the sensor had too little dynamic
range or agreement left for the mapping to mean anything:
    - fewer than MIN_PAIRS paired samples
    - Pearson r below MIN_R against MSDSD
    - Zephyr's own interquartile range below MIN_IQR points
This is the important part. Mid-2016, when the sensor sat at 14-26% while
MSDSD read 76-80%, is not a distortion to invert — it is an absence of
signal, and "correcting" it would be fabrication with a straight face.
Refused months are reported and skipped, not silently passed through.

OUTPUT. Corrected values are written as a SEPARATE SOURCE ('zephyr_rh_cal'),
never over the originals. Source 1 stays byte-identical and authoritative
until someone deliberately says otherwise.

Note this is the one case where source_priority genuinely substitutes rather
than adds: the corrected rows carry the SAME ts_utc as the originals, so
`canonical_observations` partitions them together and rank actually
arbitrates. That is exactly what was NOT true of MSDSD's own rows (different
sampling grid -> additive injection; see BACKLOG). Priority rows are still
NOT added by default — pass --activate deliberately.

DOWNSTREAM. dewpointf / heatindexf / apparenttempf / humidexf / wetbulbf for
source 1 were all derived from the bad humidity and remain wrong. Re-run
derive_apparent_temp.py against the corrected source once this is activated.

Idempotent via INSERT OR IGNORE. Safe to re-run.

Usage:
    python scripts/calibrate_zephyr_humidity.py --dry-run    # report only
    python scripts/calibrate_zephyr_humidity.py              # write source
    python scripts/calibrate_zephyr_humidity.py --activate   # + priority rows
"""

from __future__ import annotations

import bisect
import statistics as st
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wxdb

ZEPHYR_SRC = 1
MSDSD_SRC = 8
CAL_SOURCE = "zephyr_rh_cal"

PAIR_WINDOW_S = 600         # nearest MSDSD sample must be within 10 min
MIN_PAIRS = 200             # per month
MIN_R = 0.50                # Pearson correlation with MSDSD
MIN_IQR = 6.0               # Zephyr's own spread, RH points
MIN_DISTINCT = 15           # distinct RH values the sensor still resolves
MAX_DUP_KNOTS = 0.50        # fraction of INTERIOR quantile knots allowed to tie
MEAN_TOLERANCE = 5.0        # corrected monthly mean must land this close to
                            # MSDSD's mean adjusted by the site difference

# The window where the replacement hygrometer agreed with MSDSD to within a
# couple of points. Used to learn the genuine site-to-site difference, so the
# correction targets THIS SITE rather than MSDSD's ridge position.
HEALTHY = ("2016-12-01", "2017-07-01")

KNOTS = [2, 5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 98]


def pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 3:
        return 0.0
    mx, my = st.fmean(xs), st.fmean(ys)
    num = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    dx = sum((a - mx) ** 2 for a in xs) ** 0.5
    dy = sum((b - my) ** 2 for b in ys) ** 0.5
    return num / (dx * dy) if dx and dy else 0.0


def pct(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * p / 100.0
    lo, hi = int(k), min(int(k) + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


def interp(x: float, xs: list[float], ys: list[float]) -> float:
    """Piecewise-linear, clamped at the ends. xs must be non-decreasing."""
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    i = bisect.bisect_right(xs, x) - 1
    x0, x1 = xs[i], xs[i + 1]
    if x1 == x0:
        return ys[i]
    f = (x - x0) / (x1 - x0)
    return ys[i] + (ys[i + 1] - ys[i]) * f


def load_pairs(conn, mid_rh: int):
    """Zephyr RH paired to nearest MSDSD RH within PAIR_WINDOW_S, by month."""
    ms = conn.execute(
        "SELECT ts_utc, value FROM observations WHERE metric_id=? AND source_id=? ORDER BY ts_utc",
        (mid_rh, MSDSD_SRC),
    ).fetchall()
    mt = [r[0] for r in ms]
    mv = [r[1] for r in ms]

    out = defaultdict(list)   # "YYYY-MM" -> [(ts, zephyr, msdsd), ...]
    cur = conn.execute(
        "SELECT ts_utc, value FROM observations WHERE metric_id=? AND source_id=? ORDER BY ts_utc",
        (mid_rh, ZEPHYR_SRC),
    )
    for ts, z in cur:
        i = bisect.bisect_left(mt, ts)
        best, bd = None, PAIR_WINDOW_S + 1
        for k in range(max(0, i - 1), min(len(mt), i + 2)):
            d = abs(mt[k] - ts)
            if d < bd:
                bd, best = d, k
        if best is None or bd > PAIR_WINDOW_S:
            continue
        month = datetime.fromtimestamp(ts).strftime("%Y-%m")
        out[month].append((ts, z, mv[best]))
    return out


def healthy_delta(pairs_by_month):
    """
    Genuine site difference (Zephyr minus MSDSD) as a function of MSDSD RH,
    learned only from the window where the replacement sensor was healthy.
    Returned as (knot_rh, knot_delta) for interpolation.
    """
    a = datetime.fromisoformat(HEALTHY[0]).timestamp()
    b = datetime.fromisoformat(HEALTHY[1]).timestamp()
    rows = [p for m, ps in pairs_by_month.items() for p in ps if a <= p[0] < b]
    bins = defaultdict(list)
    for _, z, m in rows:
        bins[int(m // 10) * 10].append(z - m)
    xs, ys = [], []
    for lo in sorted(bins):
        if len(bins[lo]) < 30:
            continue
        xs.append(lo + 5.0)
        ys.append(st.median(bins[lo]))
    if not xs:
        raise SystemExit("healthy window produced no usable bins — check HEALTHY dates")
    return xs, ys, len(rows)


def main() -> int:
    dry = "--dry-run" in sys.argv
    activate = "--activate" in sys.argv

    conn = wxdb.get_conn()
    wxdb.ensure_schema(conn)
    mids = wxdb.metric_ids(conn)
    rh = mids["humidity"]

    print("pairing Zephyr to MSDSD (this takes a moment)…")
    by_month = load_pairs(conn, rh)
    hx, hy, n_healthy = healthy_delta(by_month)
    print(f"healthy-window site difference learned from {n_healthy:,} pairs:")
    print("   " + "  ".join(f"{x:.0f}%:{y:+.1f}" for x, y in zip(hx, hy)))

    print(f"\n{'month':>8} {'pairs':>7} {'r':>6} {'IQR':>6}  {'raw':>6} {'corr':>6} {'shift':>7}  verdict")
    total_rows = 0
    batch = []
    sid = None
    if not dry:
        conn.execute(
            "INSERT OR IGNORE INTO sources(name, kind) VALUES (?,?)",
            (CAL_SOURCE, "derived"),
        )
        conn.commit()
        sid = wxdb.source_id(conn, CAL_SOURCE)

    n_ok = n_refused = 0
    for month in sorted(by_month):
        ps = by_month[month]
        zs = [p[1] for p in ps]
        ms_ = [p[2] for p in ps]
        r = pearson(zs, ms_)
        zs_sorted = sorted(zs)
        iqr = pct(zs_sorted, 75) - pct(zs_sorted, 25)

        why = None
        if len(ps) < MIN_PAIRS:
            why = f"only {len(ps)} pairs"
        elif r < MIN_R:
            why = f"r={r:.2f} — no shared signal"
        elif iqr < MIN_IQR:
            why = f"IQR={iqr:.1f} — sensor flat"
        elif len(set(zs)) < MIN_DISTINCT:
            why = f"only {len(set(zs))} distinct values — quantised"

        raw_mean = st.fmean(zs)
        if why:
            n_refused += 1
            print(f"{month:>8} {len(ps):>7,} {r:>6.2f} {iqr:>6.1f}  {raw_mean:>6.1f} {'—':>6} {'—':>7}  REFUSED: {why}")
            continue

        # Quantile map this month's Zephyr distribution onto MSDSD's.
        ms_sorted = sorted(ms_)
        zk = [pct(zs_sorted, p) for p in KNOTS]
        mk = [pct(ms_sorted, p) for p in KNOTS]
        # A railed sensor produces TIED quantile knots. Padding those apart
        # to force invertibility does not recover information — it collapses
        # the mapping so that almost every reading clamps to the bottom knot,
        # which is how the first version of this script "corrected" Oct 2011
        # from 89% to 57% while MSDSD sat at 75%. Count the ties and refuse
        # instead of papering over them.
        # Count ties only among INTERIOR knots. The 95th/98th percentile of
        # RH legitimately sits at 99 in a marine climate, so ties up there
        # are physics, not a failed sensor — the first version of this guard
        # refused Dec 2016 (r=0.99, plainly healthy) on exactly that.
        lo_i = next(i for i, k in enumerate(KNOTS) if k >= 10)
        hi_i = next(i for i, k in enumerate(KNOTS) if k >= 90)
        interior = range(lo_i + 1, hi_i + 1)
        dup = sum(1 for i in interior if zk[i] <= zk[i - 1])
        if dup / max(1, len(list(interior))) > MAX_DUP_KNOTS:
            n_refused += 1
            print(f"{month:>8} {len(ps):>7,} {r:>6.2f} {iqr:>6.1f}  {raw_mean:>6.1f} {'—':>6} {'—':>7}"
                  f"  REFUSED: {dup}/{len(list(interior))} interior knots tied — sensor railed")
            continue
        for i in range(1, len(zk)):
            zk[i] = max(zk[i], zk[i - 1] + 1e-6)
            mk[i] = max(mk[i], mk[i - 1] + 1e-6)

        # Held aside until every check passes — a month that fails the
        # post-hoc sanity test must contribute nothing at all.
        pending = []
        corrected = []
        for ts, z, _m in ps:
            in_msdsd_frame = interp(z, zk, mk)
            v = in_msdsd_frame + interp(in_msdsd_frame, hx, hy)
            v = min(100.0, max(1.0, v))
            corrected.append(v)
            pending.append((rh, ts, sid, v))

        corr_mean = st.fmean(corrected)

        # Independent sanity check on the result rather than on the inputs:
        # a correct mapping must land the month's mean near MSDSD's mean,
        # shifted by the genuine site difference. Anything else means the
        # mapping misbehaved, whatever the input diagnostics said.
        ms_mean = st.fmean(ms_)
        expected = ms_mean + interp(ms_mean, hx, hy)
        if abs(corr_mean - expected) > MEAN_TOLERANCE:
            n_refused += 1
            print(f"{month:>8} {len(ps):>7,} {r:>6.2f} {iqr:>6.1f}  {raw_mean:>6.1f} {corr_mean:>6.1f} {corr_mean-raw_mean:>+7.1f}"
                  f"  REFUSED: lands {corr_mean-expected:+.1f} off expected {expected:.1f}")
            continue

        n_ok += 1
        total_rows += len(corrected)
        if not dry:
            batch.extend(pending)
        print(f"{month:>8} {len(ps):>7,} {r:>6.2f} {iqr:>6.1f}  {raw_mean:>6.1f} {corr_mean:>6.1f} {corr_mean-raw_mean:>+7.1f}  ok")

        if not dry and len(batch) >= 20000:
            wxdb.insert_observations(conn, batch)
            batch.clear()

    if not dry and batch:
        wxdb.insert_observations(conn, batch)
    if not dry:
        conn.commit()

    print(f"\n{n_ok} months corrected, {n_refused} refused, {total_rows:,} rows"
          + ("  (dry run — nothing written)" if dry else f" written to source '{CAL_SOURCE}'"))

    if activate and not dry:
        print("\n--activate given: adding source_priority rows.")
        print("  Corrected rows share the originals' exact timestamps, so priority")
        print("  SUBSTITUTES here rather than adding. Verify canonical counts after.")
        # left deliberately manual — see BACKLOG before wiring this in
        print("  NOT IMPLEMENTED YET: inspect the dry-run table first, then decide")
        print("  the date spans to activate. Blanket activation is the wrong default.")

    if not dry:
        print("\nNext:  python scripts/build_rollups.py")
        print("       (and re-derive source-1 moist metrics once activated)")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
