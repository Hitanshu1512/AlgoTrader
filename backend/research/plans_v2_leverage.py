"""What risk per trade would the 30% / 90% targets require?

Uses the out-of-sample trades of a candidate as R-multiples (net P&L ÷ planned risk, per
lot) and grows an account that risks a fixed fraction f of equity on every trade (fractional
lots, margin ignored — an upper bound on what sizing alone can do). Reports, for each f,
the historical CAGR and maximum drawdown, and Monte Carlo (5,000 one-year paths built from
resampled calendar months) median return, P(loss), P(target), P(−50%), P(−90%).

Usage: uv run python -m research.plans_v2_leverage
"""

from __future__ import annotations

import json
import pickle
from collections import defaultdict
from datetime import date

import numpy as np

from app.backtesting.data import CACHE

START, END = date(2022, 1, 1), date(2026, 11, 6)
CANDIDATES = {
    "Plan 1 · expiry-day straddle (Nifty + FINNIFTY)": (
        ["Expiry-day straddle (real prices)|NIFTY", "Expiry-day straddle (real prices)|FINNIFTY"],
        0.30,
    ),
    "Plan 1 · FINNIFTY trend debit spread": (["Trend debit spread|FINNIFTY"], 0.30),
    "Plan 2 · FINNIFTY volatility-expansion straddle": (
        ["Volatility-expansion straddle|FINNIFTY"],
        0.90,
    ),
    "Plan 2 · breakout option buying (3 indices)": (
        [f"Breakout option buying|{s}" for s in ("NIFTY", "BANKNIFTY", "FINNIFTY")],
        0.90,
    ),
}
FRACTIONS = (0.005, 0.01, 0.02, 0.03, 0.05, 0.10, 0.15, 0.20, 0.30)


def main() -> None:
    with open(CACHE / "plans_v2_trades.pkl", "rb") as fh:
        store = pickle.load(fh)  # noqa: S301 - our own locally generated cache file
    years = (END - START).days / 365.25
    out = {}
    rng = np.random.default_rng(3)
    for label, (keys, target) in CANDIDATES.items():
        tr = sorted(
            (t for k in keys for t in store[k]["oos"] if START <= t.signal_day <= END),
            key=lambda t: t.entry_day,
        )
        r = np.array([t.net() / t.planned_risk_per_lot for t in tr if t.planned_risk_per_lot > 0])
        months: dict[str, list[float]] = defaultdict(list)
        for t in tr:
            if t.planned_risk_per_lot > 0:
                months[f"{t.exit_day:%Y-%m}"].append(t.net() / t.planned_risk_per_lot)
        allm = []
        y, m = START.year, START.month
        while (y, m) <= (END.year, END.month):
            allm.append(months.get(f"{y:04d}-{m:02d}", []))
            m += 1
            if m > 12:
                y, m = y + 1, 1
        rows = []
        for f in FRACTIONS:
            eq, peak, dd = 1.0, 1.0, 0.0
            for x in r:
                eq = max(eq * (1 + f * x), 0.0)
                peak = max(peak, eq)
                dd = max(dd, 1 - eq / peak if peak > 0 else 1)
            cagr = eq ** (1 / years) - 1 if eq > 0 else -1.0
            finals, lows = [], []
            for _ in range(5000):
                e, lo = 1.0, 1.0
                for i in rng.integers(0, len(allm), 12):
                    for x in allm[i]:
                        e = max(e * (1 + f * x), 0.0)
                        lo = min(lo, e)
                finals.append(e)
                lows.append(lo)
            fa, la = np.array(finals), np.array(lows)
            rows.append(
                {
                    "risk_per_trade": f,
                    "hist_cagr": cagr,
                    "hist_max_dd": dd,
                    "mc_median_1y": float(np.median(fa) - 1),
                    "p_loss": float(np.mean(fa < 1)),
                    "p_target": float(np.mean(fa >= 1 + target)),
                    "p_dd50": float(np.mean(la <= 0.5)),
                    "p_dd90": float(np.mean(la <= 0.1)),
                }
            )
            print(
                f"{label[:46]:46s} risk {f:5.1%}: hist CAGR {cagr:+7.1%} maxDD {dd:5.1%} | 1y MC median "
                f"{rows[-1]['mc_median_1y']:+7.1%} P(loss) {rows[-1]['p_loss']:.0%} "
                f"P(≥{target:.0%}) {rows[-1]['p_target']:.0%} P(−50%) {rows[-1]['p_dd50']:.0%} "
                f"P(−90%) {rows[-1]['p_dd90']:.0%}"
            )
        out[label] = {
            "trades": len(r),
            "mean_R": float(r.mean()),
            "median_R": float(np.median(r)),
            "win_rate": float(np.mean(r > 0)),
            "rows": rows,
        }
        print(f"   {label}: {len(r)} trades, mean R {r.mean():+.3f}, win {np.mean(r > 0):.0%}")
    (CACHE / "plans_v2_leverage.json").write_text(json.dumps(out))


if __name__ == "__main__":
    main()
