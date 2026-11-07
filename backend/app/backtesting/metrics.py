"""Performance metrics computed from daily mark-to-market P&L."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

import numpy as np

from app.backtesting.sim import Trade


def daily_pnl(trades: list[Trade], sessions: list[date]) -> np.ndarray:
    inc: dict[date, float] = defaultdict(float)
    for t in trades:
        prev = 0.0
        for d in sorted(t.daily_mtm):
            inc[d] += t.daily_mtm[d] - prev
            prev = t.daily_mtm[d]
        inc[t.exit_day] += t.net - prev
    return np.array([inc.get(d, 0.0) for d in sessions])


def summarize(trades: list[Trade], sessions: list[date]) -> dict[str, Any]:
    if not trades:
        return {"trades": 0}
    pnl = daily_pnl(trades, sessions)
    eq = np.cumsum(pnl)
    dd = eq - np.maximum.accumulate(np.r_[0.0, eq])[1:]
    years = len(sessions) / 252
    net = np.array([t.net for t in trades])
    wins, losses = net[net > 0], net[net <= 0]
    margin = float(np.mean([t.margin for t in trades]))
    annual = float(eq[-1] / years)
    max_dd = float(-dd.min())
    worst5 = np.sort(pnl)[: max(1, len(pnl) // 20)]
    by_year: dict[int, float] = defaultdict(float)
    for d, v in zip(sessions, pnl, strict=True):
        by_year[d.year] += float(v)
    gross = float(sum(t.gross for t in trades))
    costs = float(sum(t.costs for t in trades))
    return {
        "trades": len(trades),
        "net_pnl": float(eq[-1]),
        "annual_pnl": annual,
        "avg_margin": margin,
        "annual_return_on_margin_pct": 100 * annual / margin if margin else float("nan"),
        "max_drawdown": max_dd,
        "max_dd_pct_margin": 100 * max_dd / margin if margin else float("nan"),
        "calmar": annual / max_dd if max_dd > 0 else float("inf"),
        "sharpe": float(pnl.mean() / pnl.std() * np.sqrt(252)) if pnl.std() > 0 else 0.0,
        "win_rate_pct": 100 * len(wins) / len(net),
        "profit_factor": float(wins.sum() / -losses.sum()) if losses.sum() < 0 else float("inf"),
        "avg_win": float(wins.mean()) if len(wins) else 0.0,
        "avg_loss": float(losses.mean()) if len(losses) else 0.0,
        "worst_trade": float(net.min()),
        "worst_day": float(pnl.min()),
        "cvar95_day": float(worst5.mean()),
        "gross_pnl": gross,
        "costs": costs,
        "cost_pct_of_gross": 100 * costs / gross if gross > 0 else float("nan"),
        "positive_years": int(sum(1 for v in by_year.values() if v > 0)),
        "years": len(by_year),
        "by_year": {str(k): round(v) for k, v in sorted(by_year.items())},
        "equity": eq.tolist(),
    }
