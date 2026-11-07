"""Sampled-month, capital-constrained backtest of the shortlisted strategies.

* One random month per year 2020–2026 (research/sample_months.py, fixed seed), identical
  for every strategy and both indices.
* Each (strategy, index) is an independent paper account starting at ₹30,000.
* Lots per trade = floor(0.90 × equity / margin per lot) with the *actual* exchange lot size
  of the contract on the trade date; a trade that cannot be margined is skipped and logged.
* Original strategy rules/parameters; charges at the rates in force on each trade date.

Usage: uv run python -m research.sampled_backtest
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import replace
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from app.backtesting.calendar import STRIKE_STEP, ExpiryCalendar
from app.backtesting.charges import Slippage, fixed_cost_per_order
from app.backtesting.data import CACHE, load_index_days, load_vix
from app.backtesting.margin import LegFill, futures_margin, option_margin
from app.backtesting.sim import Trade
from app.backtesting.strategies import fno
from app.backtesting.vol import Clock
from research.common import make_model
from research.sample_months import ELIGIBLE, SEED, draw

START_CAPITAL = 30_000.0
MARGIN_UTILISATION = 0.90
VALID_LOTS = (15, 20, 25, 30, 35, 50, 65, 75)
DATA_END = {"NIFTY": date(2026, 11, 6), "BANKNIFTY": date(2026, 4, 22)}

STRATEGIES: list[tuple[str, Any, dict[str, Any]]] = [
    ("920 short strangle", fno.strangle_920, {}),
    ("920 hedged strangle", fno.strangle_920, {"hedge_delta": 0.05, "name": "920 hedged strangle"}),
    (
        "Expiry-day straddle",
        fno.straddle_920,
        {"sl": 0.3, "expiry_only": True, "name": "Expiry-day straddle"},
    ),
    ("920 short straddle", fno.straddle_920, {}),
    ("Supertrend futures", fno.supertrend_futures, {}),
    ("Weekly iron condor", fno.iron_condor, {}),
    (
        "Expiry-day hedged straddle",
        fno.straddle_920,
        {
            "sl": 0.5,
            "expiry_only": True,
            "entry_bar": 105,
            "hedge_delta": 0.01,
            "name": "Expiry-day hedged straddle",
        },
    ),
]


def lot_lookup(index: str) -> tuple[Any, dict[str, int]]:
    tbl = pd.read_csv(CACHE / "lot_by_date.csv", parse_dates=["date", "expiry"])
    tbl = tbl[tbl["symbol"] == index]
    exact = {
        (r.date.date(), r.expiry.date()): min(VALID_LOTS, key=lambda v: abs(v - r.lot))
        for r in tbl.itertuples()
    }
    by_expiry: dict[date, list[tuple[date, int]]] = defaultdict(list)
    for (d, e), v in exact.items():
        by_expiry[e].append((d, v))
    stats = {"exact": 0, "nearest_date": 0}

    def fn(d: date, e: date) -> int:
        if (d, e) in exact:
            stats["exact"] += 1
            return exact[(d, e)]
        cands = by_expiry.get(e)
        if not cands:
            raise KeyError(f"no lot size for {index} expiry {e} on {d}")
        stats["nearest_date"] += 1
        return min(cands, key=lambda x: abs((x[0] - d).days))[1]

    return fn, stats


def build(index: str, slip: Slippage) -> tuple[fno.Ctx, dict[str, int]]:
    cfg = json.loads((CACHE / "calibration.json").read_text())
    surf = pd.read_parquet(CACHE / "surfaces.parquet")
    vix = load_vix(include_proxy=True)
    bars = load_index_days(index, date(2017, 4, 1), DATA_END[index])
    days = sorted(bars)
    future = [days[-1] + timedelta(days=i) for i in range(1, 120)]
    clock = Clock(days + [d for d in future if d.weekday() < 5], **cfg["clock"])
    model = make_model(index, bars, surf, vix, clock, cfg)
    lot_fn, stats = lot_lookup(index)
    ctx = fno.Ctx(
        index=index,
        sessions=days,
        bars=bars,
        cal=ExpiryCalendar(index, days),
        model=model,
        lot=0,
        step=STRIKE_STEP[index],
        slip=slip,
        vix_close=vix["close"],
        lot_fn=lot_fn,
    )
    return ctx, stats


def month_ctx(ctx: fno.Ctx, y: int, m: int) -> fno.Ctx:
    days = [d for d in ctx.bars if d.year == y and d.month == m]
    allday = sorted(ctx.bars)
    i0, i1 = allday.index(days[0]), allday.index(days[-1])
    window = allday[max(0, i0 - 60) : i1 + 26]  # warm-up before, room for exits after
    return replace(ctx, sessions=window, entry_days=frozenset(days))


def margin_per_lot(t: Trade) -> float:
    if not t.fills:  # futures
        return futures_margin(t.entry_spot, t.lot)
    legs = [LegFill(k, c, q, px) for k, c, q, px in t.fills]
    assert t.expiry is not None
    return option_margin(legs, t.entry_spot, t.lot, t.entry_day, t.expiry)


def replay(
    trades: list[Trade],
    months: dict[int, int],
    margin_mult: float = 1.0,
    utilisation: float = MARGIN_UTILISATION,
) -> dict[str, Any]:
    """Run one ₹30,000 account through the trades in time order."""
    equity = START_CAPITAL
    executed, skipped = [], []
    daily_equity: dict[date, float] = {}
    for t in sorted(trades, key=lambda x: (x.entry_day, x.exit_day)):
        m1 = margin_per_lot(t) * margin_mult
        lots = math.floor(utilisation * equity / m1) if equity > 0 else 0
        if lots < 1:
            skipped.append(
                {
                    "day": t.entry_day.isoformat(),
                    "margin_per_lot": round(m1),
                    "equity": round(equity),
                    "lot_size": t.lot,
                }
            )
            continue
        fixed = t.orders * fixed_cost_per_order()
        costs = fixed + lots * (t.costs - fixed)
        gross = lots * t.gross
        start_eq = equity
        for d, mark in sorted(t.daily_mtm.items()):
            daily_equity[d] = start_eq + lots * mark - fixed  # MTM incl. entry charges
        equity += gross - costs
        daily_equity[t.exit_day] = equity
        executed.append(
            {
                "entry": t.entry_day.isoformat(),
                "exit": t.exit_day.isoformat(),
                "lots": lots,
                "lot_size": t.lot,
                "margin_per_lot": round(m1),
                "gross": gross,
                "costs": costs,
                "net": gross - costs,
                "equity_after": equity,
                "reason": t.exit_reason,
            }
        )
    nets = np.array([e["net"] for e in executed]) if executed else np.array([])
    wins, losses = nets[nets > 0], nets[nets <= 0]
    # Equity curve over executed-trade marks (start at capital).
    curve = [START_CAPITAL] + [v for _, v in sorted(daily_equity.items())]
    peak, max_dd = curve[0], 0.0
    for v in curve:
        peak = max(peak, v)
        max_dd = max(max_dd, (peak - v) / peak)
    by_month: dict[str, dict[str, Any]] = {}
    for y, m in months.items():
        key = f"{y}-{m:02d}"
        ex = [e for e in executed if e["entry"].startswith(key)]
        sk = [s for s in skipped if s["day"].startswith(key)]
        by_month[key] = {
            "executed": len(ex),
            "skipped": len(sk),
            "net": float(sum(e["net"] for e in ex)),
            "gross": float(sum(e["gross"] for e in ex)),
            "costs": float(sum(e["costs"] for e in ex)),
            "wins": int(sum(1 for e in ex if e["net"] > 0)),
            "min_margin_needed": min((s["margin_per_lot"] for s in sk), default=None),
        }
    return {
        "initial_capital": START_CAPITAL,
        "final_capital": equity,
        "signals": len(trades),
        "executed": len(executed),
        "skipped": len(skipped),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": 100 * len(wins) / len(nets) if len(nets) else None,
        "gross_pnl": float(sum(e["gross"] for e in executed)),
        "costs": float(sum(e["costs"] for e in executed)),
        "net_pnl": float(nets.sum()) if len(nets) else 0.0,
        "net_return_pct": 100 * (equity / START_CAPITAL - 1),
        "max_drawdown_pct": 100 * max_dd,
        "profit_factor": (
            float(wins.sum() / -losses.sum())
            if len(losses) and losses.sum() < 0
            else (float("inf") if len(wins) else None)
        ),
        "avg_win": float(wins.mean()) if len(wins) else None,
        "avg_loss": float(losses.mean()) if len(losses) else None,
        "margin_per_lot_median": float(np.median([margin_per_lot(t) for t in trades]))
        if trades
        else None,
        "margin_per_lot_min": float(min(margin_per_lot(t) for t in trades)) if trades else None,
        "by_month": by_month,
        "executed_trades": executed,
        "skipped_trades": skipped,
    }


def unconstrained(trades: list[Trade], months: dict[int, int]) -> dict[str, Any]:
    """Reference only: every signal at 1 lot, with each month's account sized to that
    month's largest margin need (capital-adequate view)."""
    net = np.array([t.net for t in trades])
    w, lo = net[net > 0], net[net <= 0]
    monthly = {}
    for y, m in months.items():
        key = f"{y}-{m:02d}"
        tm = [t for t in trades if t.entry_day.strftime("%Y-%m") == key]
        need = max((margin_per_lot(t) for t in tm), default=0.0) / MARGIN_UTILISATION
        pnl = float(sum(t.net for t in tm))
        monthly[key] = {
            "trades": len(tm),
            "net": pnl,
            "capital_needed": need,
            "return_pct": 100 * pnl / need if need else 0.0,
        }
    rets = np.array([v["return_pct"] for v in monthly.values()]) / 100
    eq = np.cumprod(1 + rets)
    dd = float(np.max(1 - eq / np.maximum.accumulate(np.r_[1.0, eq])[1:])) if len(eq) else 0.0
    return {
        "signals": len(trades),
        "net_pnl": float(net.sum()),
        "gross_pnl": float(sum(t.gross for t in trades)),
        "costs": float(sum(t.costs for t in trades)),
        "win_rate_pct": 100 * len(w) / len(net) if len(net) else None,
        "profit_factor": float(w.sum() / -lo.sum()) if lo.sum() < 0 else None,
        "monthly": monthly,
        "compounded_return_pct": float(100 * (eq[-1] - 1)) if len(eq) else 0.0,
        "positive_months": int((rets > 0).sum()),
        "worst_month_pct": float(rets.min() * 100) if len(rets) else 0.0,
        "monthly_sharpe": float(rets.mean() / rets.std() * np.sqrt(12)) if rets.std() > 0 else 0.0,
        "max_dd_pct_monthly": 100 * dd,
        "capital_needed_current_regime": max(
            (v["capital_needed"] for k, v in monthly.items() if k >= "2025"), default=0.0
        ),
    }


def main() -> None:
    months = draw()
    slip = Slippage(historical_rates=True)
    out: dict[str, Any] = {
        "seed": SEED,
        "months": months,
        "eligible": {str(k): v for k, v in ELIGIBLE.items()},
        "results": {},
    }
    for index in ("NIFTY", "BANKNIFTY"):
        ctx, lot_stats = build(index, slip)
        for name, fn, kw in STRATEGIES:
            trades: list[Trade] = []
            for y, m in months.items():
                trades += fn(month_ctx(ctx, y, m), **kw)
            res = replay(trades, months)
            res["unconstrained_1_lot"] = unconstrained(trades, months)
            res["sensitivity"] = {
                label: {
                    k: replay(trades, months, mm, ut)[k]
                    for k in (
                        "executed",
                        "skipped",
                        "final_capital",
                        "net_return_pct",
                        "max_drawdown_pct",
                    )
                }
                for label, mm, ut in (
                    ("margins_minus_20pct_util_100pct", 0.8, 1.0),
                    ("margins_plus_20pct", 1.2, MARGIN_UTILISATION),
                )
            }
            out["results"].setdefault(name, {})[index] = res
            pf = res["profit_factor"]
            print(
                f"{index:9s} {name:28s} signals {res['signals']:4d} executed {res['executed']:4d}"
                f" skipped {res['skipped']:4d} | final ₹{res['final_capital']:>9,.0f}"
                f" ({res['net_return_pct']:+6.1f}%) maxDD {res['max_drawdown_pct']:5.1f}%"
                f" PF {pf if pf is None else round(pf, 2)} | margin/lot median ₹"
                f"{res['margin_per_lot_median'] or 0:,.0f} min ₹{res['margin_per_lot_min'] or 0:,.0f}"
                f" | 1-lot ref net ₹{res['unconstrained_1_lot']['net_pnl']:,.0f}"
                f" | lenient margins: executed {res['sensitivity']['margins_minus_20pct_util_100pct']['executed']}",
                flush=True,
            )
        out.setdefault("lot_lookup", {})[index] = dict(lot_stats)
        out.setdefault("model_usage", {})[index] = {
            "surface": ctx.model.surface_used,
            "vix_fallback": ctx.model.fallback_used,
        }
    (CACHE / "study_sampled.json").write_text(json.dumps(out, default=str))
    print("lot lookups:", out["lot_lookup"], "| pricing anchors:", out["model_usage"])


if __name__ == "__main__":
    main()
