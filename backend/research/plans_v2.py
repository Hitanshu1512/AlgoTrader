"""Revised Plan 1 / Plan 2 study on real NSE option prices (2020–2026).

Stage A – every strategy family × underlying × pre-declared parameter set, per lot, over
          the whole history (real daily option OHLC, next-open entries, real lot sizes,
          charges in force on each date, slippage).
Stage B – walk-forward: for each 6-month test block from Jan 2022, pick the parameter set
          with the best training result over the previous 20 months, and trade it unchanged
          in the test block. The concatenated test blocks are the out-of-sample record.

Usage: uv run python -m research.plans_v2
Writes data/cache/plans_v2_trades.pkl and data/cache/plans_v2.json
"""

from __future__ import annotations

import json
import pickle
import time
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from app.backtesting.data import CACHE
from app.backtesting.eod import Chain, EodTrade, Slip, load_chain
from app.backtesting.strategies.eod_strats import FAMILIES, GRIDS

SYMBOLS = ("NIFTY", "BANKNIFTY", "FINNIFTY")
TRAIN_MONTHS = 20
BLOCKS = [  # out-of-sample test blocks (start, end)
    (date(y, m, 1), date(y + (m == 7), 1 if m == 7 else 7, 1))
    for y in range(2022, 2027)
    for m in (1, 7)
]
BASE_SLIP = Slip()
STRESS_SLIP = Slip(pct=0.02, min_points=0.40)


def per_lot(trades: list[EodTrade]) -> dict[str, Any]:
    if not trades:
        return {"trades": 0}
    t = sorted(trades, key=lambda x: x.exit_day)
    net = np.array([x.net() for x in t])
    eq = np.cumsum(net)
    dd = float((np.maximum.accumulate(np.r_[0.0, eq])[1:] - eq).max())
    years = max((t[-1].exit_day - t[0].entry_day).days / 365.25, 0.25)
    wins, losses = net[net > 0], net[net <= 0]
    by_year: dict[str, float] = {}
    for x, v in zip(t, net, strict=True):
        by_year[str(x.exit_day.year)] = by_year.get(str(x.exit_day.year), 0.0) + float(v)
    streak = best = 0
    for v in net:
        streak = streak + 1 if v <= 0 else 0
        best = max(best, streak)
    return {
        "trades": len(t),
        "trades_per_month": len(t) / (years * 12),
        "net": float(net.sum()),
        "net_per_year": float(net.sum() / years),
        "win_rate": float(len(wins) / len(net)),
        "profit_factor": float(wins.sum() / -losses.sum()) if losses.sum() < 0 else float("inf"),
        "avg_net": float(net.mean()),
        "worst": float(net.min()),
        "best": float(net.max()),
        "max_dd": dd,
        "max_losing_streak": best,
        "median_margin": float(np.median([x.margin_per_lot for x in t])),
        "median_planned_risk": float(np.median([x.planned_risk_per_lot for x in t])),
        "median_max_loss": float(np.median([x.max_loss_per_lot for x in t])),
        "median_premium": float(np.median([abs(x.entry_value) * x.lot for x in t])),
        "by_year": {k: round(v) for k, v in sorted(by_year.items())},
        "exit_reasons": pd.Series([x.exit_reason for x in t]).value_counts().to_dict(),
    }


def score(trades: list[EodTrade]) -> float:
    """Training objective: net per lot ÷ (max drawdown + average |risk|); needs ≥ 8 trades."""
    if len(trades) < 8:
        return -np.inf
    m = per_lot(trades)
    return m["net"] / (m["max_dd"] + abs(m["median_planned_risk"]) + 1.0)


def in_window(trades: list[EodTrade], a: date, b: date) -> list[EodTrade]:
    return [t for t in trades if a <= t.signal_day < b]


def months_back(d: date, n: int) -> date:
    y, m = d.year, d.month - n
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1)


def walk_forward(runs: list[list[EodTrade]]) -> tuple[list[EodTrade], list[dict[str, Any]]]:
    oos: list[EodTrade] = []
    picks = []
    for a, b in BLOCKS:
        tr0 = months_back(a, TRAIN_MONTHS)
        scores = [score(in_window(r, tr0, a)) for r in runs]
        best = int(np.argmax(scores))
        chosen = in_window(runs[best], a, b)
        oos.extend(chosen)
        picks.append(
            {
                "block": f"{a:%Y-%m}",
                "param_index": best,
                "train_score": float(scores[best]) if np.isfinite(scores[best]) else None,
                "test_trades": len(chosen),
                "test_net_per_lot": float(sum(t.net() for t in chosen)),
            }
        )
    return oos, picks


def main() -> None:
    eod = pd.read_parquet(CACHE / "option_eod_v2.parquet")
    out: dict[str, Any] = {"blocks": [f"{a:%Y-%m}" for a, _ in BLOCKS], "results": {}}
    store: dict[str, Any] = {}
    for sym in SYMBOLS:
        t0 = time.time()
        ch: Chain = load_chain(eod, sym)
        print(
            f"{sym}: {len(ch.days)} sessions {ch.days[0]} → {ch.days[-1]} ({time.time() - t0:.0f}s)"
        )
        for fam, fn in FAMILIES.items():
            grid = GRIDS[fam]
            runs, misses_all = [], []
            for params in grid:
                misses: dict[str, int] = {}
                runs.append(fn(ch, slip=BASE_SLIP, misses=misses, **params))
                misses_all.append(misses)
            oos, picks = walk_forward(runs)
            # Robustness of the walk-forward record: same picks, but 2× slippage and
            # (for spreads) stops on the intraday worst case.
            stress_runs = {
                p["param_index"]: fn(ch, slip=STRESS_SLIP, **grid[p["param_index"]]) for p in picks
            }
            oos_stress = []
            for (a, b), p in zip(BLOCKS, picks, strict=True):
                oos_stress.extend(in_window(stress_runs[p["param_index"]], a, b))
            key = f"{fam}|{sym}"
            out["results"][key] = {
                "grid": grid,
                "full_period_each_param": [per_lot(r) for r in runs],
                "misses": misses_all[0],
                "oos": per_lot(oos),
                "oos_stress": per_lot(oos_stress),
                "picks": picks,
                "first_data_day": ch.days[0].isoformat(),
                "last_data_day": ch.days[-1].isoformat(),
            }
            store[key] = {"oos": oos, "oos_stress": oos_stress, "runs": runs}
            o = out["results"][key]["oos"]
            full = [r.get("net", 0) for r in out["results"][key]["full_period_each_param"]]
            print(
                f"  {fam:30s} OOS n={o.get('trades', 0):4d} net/lot ₹{o.get('net', 0):>10,.0f} "
                f"win {o.get('win_rate', 0):.0%} PF {o.get('profit_factor', 0):.2f} "
                f"| stress ₹{out['results'][key]['oos_stress'].get('net', 0):>10,.0f} "
                f"| full-period grid min/median/max ₹{min(full):,.0f} / ₹{np.median(full):,.0f} / ₹{max(full):,.0f}",
                flush=True,
            )
    (CACHE / "plans_v2.json").write_text(json.dumps(out, default=str))
    with open(CACHE / "plans_v2_trades.pkl", "wb") as fh:
        pickle.dump(store, fh)


if __name__ == "__main__":
    main()
