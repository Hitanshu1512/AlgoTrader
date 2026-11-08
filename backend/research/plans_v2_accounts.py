"""Plan 1 (₹1 lakh) and Plan 2 (₹10–25k) accounts on the walk-forward (out-of-sample) trades.

* Trades: out-of-sample walk-forward record Jan 2022 – Nov 2026 from ``plans_v2`` (real
  option prices, next-open entries, real lots, historical charges, slippage).
* Human execution: 10% of valid signals are missed (seeded), every rule below is applied.
* Monte Carlo: calendar months of the account's trade returns (each trade's P&L ÷ the
  equity it was sized on) are resampled with replacement to build 1-, 2-, 3- and 5-year
  paths (5,000 paths).

Usage: uv run python -m research.plans_v2_accounts '<plan json>'
       plan json = {"name": ..., "capital": ..., "keys": ["Family|SYMBOL", ...], "rules": {...}}
Writes data/cache/plans_v2_accounts.json (merged per plan name)
"""

from __future__ import annotations

import json
import pickle
import sys
from collections import defaultdict
from datetime import date
from typing import Any

import numpy as np

from app.backtesting.data import CACHE
from app.backtesting.eod import AccountRules, EodTrade, run_account

START = date(2022, 1, 1)
END = date(2026, 11, 6)
PATHS = 5_000


def business_days(a: date, b: date) -> list[date]:
    import pandas as pd

    return [x.date() for x in pd.bdate_range(a, b)]


def monte_carlo(log: list[dict[str, Any]], target: float, seed: int = 11) -> dict[str, Any]:
    by_month: dict[str, list[float]] = defaultdict(list)
    for r in log:
        before = r["equity_after"] - r["net"]
        by_month[r["exit"][:7]].append(r["net"] / before if before > 0 else -1.0)
    months = []
    y, m = START.year, START.month
    while (y, m) <= (END.year, END.month):
        months.append(by_month.get(f"{y:04d}-{m:02d}", []))  # empty months count (no trades)
        m += 1
        if m > 12:
            y, m = y + 1, 1
    rng = np.random.default_rng(seed)
    out: dict[str, Any] = {}
    for years in (1, 2, 3, 5):
        finals, mins = np.empty(PATHS), np.empty(PATHS)
        for p in range(PATHS):
            eq, low = 1.0, 1.0
            for idx in rng.integers(0, len(months), 12 * years):
                for r in months[idx]:
                    eq *= 1 + r
                    low = min(low, eq)
                if eq <= 0.0:
                    eq = 0.0
                    break
            finals[p], mins[p] = eq, low
        q = np.quantile(finals, [0.05, 0.25, 0.5, 0.75, 0.95])
        out[f"{years}y"] = {
            "p5": float(q[0]),
            "p25": float(q[1]),
            "median": float(q[2]),
            "p75": float(q[3]),
            "p95": float(q[4]),
            "prob_loss": float(np.mean(finals < 1.0)),
            "prob_target": float(np.mean(finals >= (1 + target) ** years)),
            "prob_dd25": float(np.mean(mins <= 0.75)),
            "prob_dd50": float(np.mean(mins <= 0.50)),
            "prob_dd90": float(np.mean(mins <= 0.10)),
        }
    return out


def stats(res: dict[str, Any], capital: float) -> dict[str, Any]:
    log = res["log"]
    net = np.array([r["net"] for r in log]) if log else np.array([0.0])
    years = (END - START).days / 365.25
    final = res["final"]
    cagr = (final / capital) ** (1 / years) - 1 if final > 0 else -1.0
    wins, losses = net[net > 0], net[net <= 0]
    streak = best = 0
    for v in net:
        streak = streak + 1 if v <= 0 else 0
        best = max(best, streak)
    by_year: dict[str, float] = defaultdict(float)
    eq_start: dict[str, float] = {}
    for r in log:
        y = r["exit"][:4]
        eq_start.setdefault(y, r["equity_after"] - r["net"])
        by_year[y] += r["net"]
    curve = res["curve"]
    month_end: dict[str, float] = {}
    for d, v in curve:
        month_end[f"{d:%Y-%m}"] = v
    mvals = list(month_end.values())
    mrets = [mvals[i] / mvals[i - 1] - 1 for i in range(1, len(mvals)) if mvals[i - 1] > 0]
    return {
        "capital": capital,
        "final": final,
        "cagr": cagr,
        "monthly_equiv": (1 + cagr) ** (1 / 12) - 1 if cagr > -1 else -1.0,
        "max_dd": res["max_dd"],
        "trades": len(log),
        "trades_per_month": len(log) / (years * 12),
        "win_rate": float(len(wins) / max(len(net), 1)),
        "profit_factor": float(wins.sum() / -losses.sum()) if losses.sum() < 0 else float("inf"),
        "worst_trade": float(net.min()),
        "best_trade": float(net.max()),
        "max_losing_streak": best,
        "by_year_pct": {y: 100 * v / eq_start[y] for y, v in sorted(by_year.items())},
        "by_year_rupees": {y: round(v) for y, v in sorted(by_year.items())},
        "months_positive": int(sum(1 for r in mrets if r > 0)),
        "months": len(mrets),
        "worst_month": float(min(mrets)) if mrets else 0.0,
        "best_month": float(max(mrets)) if mrets else 0.0,
        "skipped": res["skipped"],
        "median_lots": float(np.median([r["lots"] for r in log])) if log else 0.0,
        "median_risk_pct": float(
            np.median([r["planned_risk"] / (r["equity_after"] - r["net"]) for r in log])
        )
        if log
        else 0.0,
    }


def main(spec: dict[str, Any]) -> None:
    with open(CACHE / "plans_v2_trades.pkl", "rb") as fh:
        store = pickle.load(fh)  # noqa: S301 - our own locally generated cache file
    variant = spec.get("variant", "oos")
    trades: list[EodTrade] = []
    for k in spec["keys"]:
        trades.extend(t for t in store[k][variant] if START <= t.signal_day <= END)
    rules = AccountRules(**spec["rules"])
    res = run_account(trades, spec["capital"], rules, business_days(START, END))
    st = stats(res, spec["capital"])
    st["monte_carlo"] = monte_carlo(res["log"], spec["target"])
    st["spec"] = spec
    st["log"] = res["log"]
    st["curve"] = [(d.isoformat(), round(v, 2)) for d, v in res["curve"]]
    path = CACHE / "plans_v2_accounts.json"
    allres = json.loads(path.read_text()) if path.exists() else {}
    allres[spec["name"]] = st
    path.write_text(json.dumps(allres, default=str))
    mc = st["monte_carlo"]["1y"]
    print(
        f"{spec['name']:44s} ₹{spec['capital']:,.0f} → ₹{st['final']:,.0f}  CAGR {st['cagr']:+.1%} "
        f"(≈{st['monthly_equiv']:+.2%}/mo)  maxDD {st['max_dd']:.1%}  trades {st['trades']} "
        f"({st['trades_per_month']:.1f}/mo)  win {st['win_rate']:.0%}  PF {st['profit_factor']:.2f}  "
        f"worst ₹{st['worst_trade']:,.0f}  streak {st['max_losing_streak']}  "
        f"risk/trade {st['median_risk_pct']:.1%}  by year {st['by_year_pct']}\n"
        f"    MC 1y: median {mc['median'] - 1:+.1%}  P(loss) {mc['prob_loss']:.0%}  "
        f"P(≥target) {mc['prob_target']:.0%}  P(−25%) {mc['prob_dd25']:.0%}  "
        f"P(−50%) {mc['prob_dd50']:.0%}  P(−90%) {mc['prob_dd90']:.0%}   skipped {st['skipped']}",
        flush=True,
    )


if __name__ == "__main__":
    main(json.loads(sys.argv[1]))
