"""Small-capital account test for option-buying strategies.

* Accounts start with ₹25,000 or ₹50,000 on 1 May 2020 and run to the end of the data
  (Nifty: Nov 2026; Bank Nifty: Apr 2026). Jan 2026 onwards was **not** used in the
  strategy screen, so it is an out-of-sample check (2026 VIX is rebuilt from option prices).
* Actual exchange lot size on each trade date; charges at the rates in force on that date.
* Two sizing modes, both "high-risk" plans:
  - **1 lot**: one lot per signal if the premium fits in the cash balance;
  - **compounding**: lots = ⌊5% of equity ÷ planned loss per lot⌋ (planned loss = stop % ×
    premium, or the whole premium when the exit is an indicator flip); at least 1 lot if the
    premium fits and the planned loss is ≤ 10% of equity.
* Daily loss limit 10% of the day's opening equity: no new entries once reached.
* The account is "blown" when it can no longer pay for one lot of a typical signal.

Usage: uv run python -m research.buying_account "<strategy>:<INDEX>" ...
Writes backend/data/cache/buying_account.json
"""

from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from dataclasses import replace
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from app.backtesting.charges import Slippage, fixed_cost_per_order
from app.backtesting.data import CACHE
from app.backtesting.sim import Trade
from app.backtesting.strategies.buying import STRATEGIES
from research.sampled_backtest import VALID_LOTS, build

START = date(2020, 5, 1)
CAPITALS = (25_000.0, 50_000.0)
RISK_PCT = 0.05
MAX_RISK_1LOT = 0.10
DAILY_LOSS = 0.10
PLANNED_SL = {
    "PDH/PDL breakout": 0.30,
    "RSI 60/40": 0.30,
    "Expiry hero-zero": 0.50,
    "Low-VIX long straddle": 0.35,
}


def with_fallback(index: str, fn: Any) -> Any:
    """Exact (date, expiry) lot from the bhavcopies; if that expiry is missing from the
    archive (a few data gaps), the lot of the nearest-expiry contract on the nearest date."""
    tbl = pd.read_csv(CACHE / "lot_by_date.csv", parse_dates=["date", "expiry"])
    tbl = tbl[tbl["symbol"] == index].sort_values(["date", "expiry"])
    first = tbl.groupby("date").first()["lot"]
    dates = np.array([d.date() for d in first.index])
    vals = first.to_numpy()
    fallback = {"n": 0}

    def lot(d: date, e: date) -> int:
        try:
            return int(fn(d, e))
        except KeyError:
            fallback["n"] += 1
            i = int(np.argmin([abs((x - d).days) for x in dates]))
            return int(min(VALID_LOTS, key=lambda v: abs(v - vals[i])))

    lot.fallback = fallback  # type: ignore[attr-defined]
    return lot


def scaled_net(t: Trade, lots: int) -> float:
    fixed = t.orders * fixed_cost_per_order()
    return lots * t.gross - (lots * (t.costs - fixed) + fixed)


def run_account(
    trades: list[Trade], capital: float, mode: str, sl_pct: float | None
) -> dict[str, Any]:
    equity = peak = capital
    max_dd = 0.0
    curve: list[tuple[str, float]] = []
    by_year: dict[int, float] = defaultdict(float)
    taken = skipped = 0
    day_start: dict[date, float] = {}
    blown_on: str | None = None
    min_cost = np.median([t.margin for t in trades]) if trades else 0.0
    for t in sorted(trades, key=lambda x: (x.entry_day, x.exit_bar)):
        d = t.entry_day
        day_start.setdefault(d, equity)
        if equity - day_start[d] <= -DAILY_LOSS * day_start[d]:
            skipped += 1
            continue
        premium = t.margin  # ₹ for one lot
        planned = (sl_pct or 1.0) * premium
        if premium > equity:
            skipped += 1
            if equity < min_cost and blown_on is None:
                blown_on = d.isoformat()
            continue
        if mode == "1 lot":
            lots = 1
        else:
            lots = math.floor(RISK_PCT * equity / planned) if planned > 0 else 0
            if lots < 1:
                lots = 1 if planned <= MAX_RISK_1LOT * equity else 0
            lots = min(lots, math.floor(equity / premium))
            if lots < 1:
                skipped += 1
                continue
        net = scaled_net(t, lots)
        equity += net
        taken += 1
        by_year[t.exit_day.year] += net
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak)
        curve.append((t.exit_day.isoformat(), round(equity, 2)))
    return {
        "capital": capital,
        "mode": mode,
        "final": equity,
        "return_pct": 100 * (equity / capital - 1),
        "max_drawdown_pct": 100 * max_dd,
        "trades_taken": taken,
        "skipped": skipped,
        "blown_on": blown_on,
        "by_year": {str(k): round(v) for k, v in sorted(by_year.items())},
        "curve": curve,
    }


def main(specs: list[str]) -> None:
    out: dict[str, Any] = {}
    ctxs: dict[str, Any] = {}
    for spec in specs:
        name, index = spec.split(":")
        kw: dict[str, Any] = {}
        if name.endswith(" (spread)"):
            name, kw = name[: -len(" (spread)")], {"spread": True}
        if index not in ctxs:
            c, _ = build(index, Slippage(historical_rates=True))
            ctxs[index] = replace(c, lot_fn=with_fallback(index, c.lot_fn))
        ctx = ctxs[index]

        sess = [d for d in ctx.sessions if d >= START]
        trades = STRATEGIES[name](replace(ctx, sessions=sess), **kw)
        res = []
        for cap in CAPITALS:
            for mode in ("1 lot", "compounding"):
                r = run_account(trades, cap, mode, PLANNED_SL.get(name))
                res.append(r)
                print(
                    f"{spec:36s} ₹{cap:>7,.0f} {mode:11s} → ₹{r['final']:>12,.0f} "
                    f"({r['return_pct']:+8.1f}%)  maxDD {r['max_drawdown_pct']:5.1f}%  "
                    f"trades {r['trades_taken']}  skipped {r['skipped']}  blown {r['blown_on']}  "
                    f"{r['by_year']}",
                    flush=True,
                )
        oos = [t for t in trades if t.entry_day >= date(2026, 1, 1)]
        per_lot = {
            "trades": len(trades),
            "net_1lot_hist_lots": float(sum(t.net for t in trades)),
            "oos_2026_trades": len(oos),
            "oos_2026_net_1lot": float(sum(t.net for t in oos)),
            "oos_2026_win_rate": float(np.mean([t.net > 0 for t in oos])) if oos else None,
            "median_premium_per_lot": float(np.median([t.margin for t in trades])),
            "lot_fallbacks": ctx.lot_fn.fallback["n"],
        }
        print(f"{spec:36s} per lot (historical lots): {per_lot}", flush=True)
        out[spec] = {"accounts": res, "per_lot": per_lot}
    (CACHE / "buying_account.json").write_text(json.dumps(out, default=str))


if __name__ == "__main__":
    main(sys.argv[1:])
