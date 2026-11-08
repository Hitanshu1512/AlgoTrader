"""Option-buying study: famous retail long-option strategies on Nifty and Bank Nifty.

Per lot at today's lot sizes (65 / 30) and 1 Apr 2026 charges, May 2020 – Dec 2025, the
same pricing model and fill rules as the full-period F&O study.

Usage: uv run python -m research.run_buying_study
Writes backend/data/cache/study_buying.json
"""

from __future__ import annotations

import json
import time
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from app.backtesting.charges import Slippage
from app.backtesting.data import CACHE
from app.backtesting.metrics import summarize
from app.backtesting.sim import Trade
from app.backtesting.strategies.buying import SPREADABLE, STRATEGIES
from app.backtesting.strategies.fno import Ctx
from research.run_fno_study import INDICES, MAIN, build_ctx

WINDOWS = {
    "2020_22": (date(2020, 5, 1), date(2022, 12, 31)),
    "2023_25": (date(2023, 1, 1), date(2025, 12, 31)),
    "post_2024_11": (date(2024, 11, 21), date(2025, 12, 31)),
}
STRESS = Slippage(option_pct=0.01, option_min_points=0.20, sl_fill_worst=True)


def summary(trades: list[Trade], sessions: list[date]) -> dict[str, Any]:
    r = summarize(trades, sessions)
    if not trades:
        return r
    r.pop("equity", None)
    net = np.array([t.net for t in trades])
    r["avg_premium_paid"] = float(np.mean([t.margin for t in trades]))
    r["max_premium_paid"] = float(np.max([t.margin for t in trades]))
    r["trades_per_year"] = len(trades) / (len(sessions) / 252)
    r["exit_reasons"] = pd.Series([t.exit_reason for t in trades]).value_counts().to_dict()
    r["slippage"] = float(sum(t.slippage for t in trades))
    # Longest losing streak (trades) and the share of trades that lost ≥ 90% of premium.
    streak = best = 0
    for x in net:
        streak = streak + 1 if x < 0 else 0
        best = max(best, streak)
    r["max_losing_streak"] = best
    r["big_win_share_of_profit"] = (
        float(np.sort(net)[::-1][: max(1, len(net) // 10)].sum() / net[net > 0].sum())
        if (net > 0).any()
        else float("nan")
    )
    return r


def windowed(trades: list[Trade], ctx: Ctx) -> dict[str, Any]:
    out = {}
    for k, (a, b) in WINDOWS.items():
        ss = [d for d in ctx.sessions if a <= d <= b]
        tt = [t for t in trades if a <= t.entry_day <= b]
        out[k] = summary(tt, ss)
    return out


def line(index: str, name: str, r: dict[str, Any]) -> str:
    if not r.get("trades"):
        return f"{index:9s} {name:34s} no trades"
    return (
        f"{index:9s} {name:34s} n {r['trades']:5d}  net ₹{r['net_pnl']:>10,.0f}"
        f"  gross ₹{r['gross_pnl']:>10,.0f}  costs ₹{r['costs']:>8,.0f}"
        f"  maxDD ₹{r['max_drawdown']:>9,.0f}  sh {r['sharpe']:5.2f}  win {r['win_rate_pct']:4.1f}%"
        f"  PF {r['profit_factor']:.2f}  prem ₹{r['avg_premium_paid']:>6,.0f}"
        f"  yrs+ {r['positive_years']}/{r['years']}"
    )


def main() -> None:
    out: dict[str, Any] = {}
    for index in INDICES:
        ctx = build_ctx(index, MAIN)
        stress_ctx = build_ctx(index, MAIN, slip=STRESS)
        for name, fn in STRATEGIES.items():
            variants: list[tuple[str, dict[str, Any]]] = [("", {})]
            if name in SPREADABLE:
                variants.append((" (spread)", {"spread": True}))
            for suffix, kw in variants:
                t0 = time.time()
                trades = fn(ctx, **kw)
                base = summary(trades, ctx.sessions)
                stress = summary(fn(stress_ctx, **kw), ctx.sessions)
                key = name + suffix
                out.setdefault(key, {})[index] = {
                    "main": base,
                    "windows": windowed(trades, ctx),
                    "stress": stress,
                    "runtime_s": round(time.time() - t0, 1),
                }
                print(
                    line(index, key, base),
                    f" | stress net ₹{stress.get('net_pnl', 0):,.0f}",
                    f"({time.time() - t0:.0f}s)",
                    flush=True,
                )
        (CACHE / "study_buying.json").write_text(json.dumps(out, default=str))


if __name__ == "__main__":
    main()
