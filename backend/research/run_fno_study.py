"""F&O strategy study: screen 10 strategies, then stress-test a shortlist.

Usage:
  uv run python -m research.run_fno_study screen            # all 10, main window
  uv run python -m research.run_fno_study deep S1 S2 ...    # robustness for a shortlist
Results are written to backend/data/cache/study_*.json (charts/report built separately).
"""

from __future__ import annotations

import json
import sys
import time
from datetime import date, timedelta
from typing import Any

import pandas as pd

from app.backtesting.calendar import LOT_SIZE, STRIKE_STEP, ExpiryCalendar
from app.backtesting.charges import Slippage
from app.backtesting.data import CACHE, load_index_days, load_vix
from app.backtesting.metrics import summarize
from app.backtesting.strategies.fno import STRATEGIES, Ctx
from app.backtesting.vol import Clock
from research.common import make_model

MAIN = (date(2020, 5, 1), date(2025, 12, 31))  # option prices anchored to real NSE surfaces
EXTENDED = (date(2017, 4, 3), date(2020, 4, 30))  # VIX-only pricing (includes the COVID crash)
INDICES = ("NIFTY", "BANKNIFTY")


def build_ctx(index: str, window: tuple[date, date], slip: Slippage | None = None) -> Ctx:
    cfg = json.loads((CACHE / "calibration.json").read_text())
    surf = pd.read_parquet(CACHE / "surfaces.parquet")
    vix = load_vix()
    bars = load_index_days(index, date(2017, 4, 1), date(2025, 12, 31))
    data_days = sorted(bars)
    future = [data_days[-1] + timedelta(days=i) for i in range(1, 120)]
    clock_days = data_days + [d for d in future if d.weekday() < 5]
    clock = Clock(clock_days, **cfg["clock"])
    model = make_model(index, bars, surf, vix, clock, cfg)
    sessions = [d for d in data_days if window[0] <= d <= window[1]]
    return Ctx(
        index=index,
        sessions=sessions,
        bars=bars,
        cal=ExpiryCalendar(index, data_days),
        model=model,
        lot=LOT_SIZE[index],
        step=STRIKE_STEP[index],
        slip=slip or Slippage(),
        vix_close=vix["close"],
    )


def run(name: str, ctx: Ctx, **kwargs: Any) -> dict[str, Any]:
    t0 = time.time()
    fn = STRATEGIES[name]
    trades = fn(ctx, **kwargs) if kwargs else fn(ctx)
    res = summarize(trades, ctx.sessions)
    res["runtime_s"] = round(time.time() - t0, 1)
    res["exit_reasons"] = pd.Series([t.exit_reason for t in trades]).value_counts().to_dict()
    return res


def screen() -> None:
    results: dict[str, dict[str, Any]] = {}
    for index in INDICES:
        ctx = build_ctx(index, MAIN)
        for name in STRATEGIES:
            r = run(name, ctx)
            results.setdefault(name, {})[index] = r
            print(
                f"{index:9s} {name:28s} trades {r['trades']:5d}  net ₹{r['net_pnl']:>10,.0f}"
                f"  ann {r['annual_return_on_margin_pct']:6.1f}%  maxDD ₹{r['max_drawdown']:>9,.0f}"
                f"  sharpe {r['sharpe']:5.2f}  win {r['win_rate_pct']:4.1f}%  PF {r['profit_factor']:.2f}"
                f"  costs {r['cost_pct_of_gross']:5.1f}%  yrs+ {r['positive_years']}/{r['years']}"
                f"  ({r['runtime_s']}s)",
                flush=True,
            )
        print(
            f"  {index}: surface-anchored prices {ctx.model.surface_used}, VIX fallback "
            f"{ctx.model.fallback_used}"
        )
    (CACHE / "study_screen.json").write_text(json.dumps(results, default=str))


if __name__ == "__main__":
    {"screen": screen}[sys.argv[1]]()
