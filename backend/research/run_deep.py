"""Robustness tests for the shortlisted strategies (see docs/research report).

Usage: uv run python -m research.run_deep
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from typing import Any

import numpy as np

from app.backtesting.charges import Slippage
from app.backtesting.data import CACHE
from app.backtesting.metrics import daily_pnl, summarize
from app.backtesting.strategies import fno
from research.run_fno_study import EXTENDED, INDICES, MAIN, build_ctx

DESIGN = (date(2020, 5, 1), date(2022, 12, 31))
HOLDOUT = (date(2023, 1, 1), date(2025, 12, 31))
POST_RULES = (date(2024, 11, 21), date(2025, 12, 31))  # after SEBI weekly-expiry curbs

SHORTLIST: dict[str, tuple[Any, dict[str, Any], list[dict[str, Any]]]] = {
    "920 short strangle": (
        fno.strangle_920,
        {},
        [{"delta": dl, "sl": sl} for dl in (0.15, 0.2, 0.25) for sl in (0.2, 0.3, 0.4, 0.5)],
    ),
    "920 hedged strangle": (
        fno.strangle_920,
        {"hedge_delta": 0.05, "name": "920 hedged strangle"},
        [
            {"delta": dl, "sl": sl, "hedge_delta": hd, "name": "920 hedged strangle"}
            for dl in (0.15, 0.2, 0.25)
            for sl in (0.2, 0.3, 0.4)
            for hd in (0.03, 0.05)
        ],
    ),
    "Expiry-day straddle": (
        fno.straddle_920,
        {"sl": 0.3, "expiry_only": True, "name": "Expiry-day straddle"},
        [
            {"sl": sl, "expiry_only": True, "entry_bar": eb, "name": "Expiry-day straddle"}
            for sl in (0.2, 0.3, 0.4, 0.5)
            for eb in (5, 45, 105)
        ],
    ),
    "920 short straddle": (
        fno.straddle_920,
        {},
        [{"sl": sl, "entry_bar": eb} for sl in (0.15, 0.2, 0.25, 0.3, 0.4) for eb in (5, 15, 45)],
    ),
    "Supertrend futures": (
        fno.supertrend_futures,
        {},
        [
            {"period": p, "mult": m, "tf": tf}
            for p, m in ((7, 2.0), (10, 3.0), (14, 3.0), (10, 4.0))
            for tf in (15, 30, 60)
        ],
    ),
    "Weekly iron condor": (
        fno.iron_condor,
        {},
        [
            {"short_delta": sd, "tp": tp, "sl_mult": sm}
            for sd in (0.1, 0.16, 0.25)
            for tp in (0.5, 0.75)
            for sm in (1.0, 1.5, 2.0)
        ],
    ),
}


def window(ctx: fno.Ctx, w: tuple[date, date]) -> fno.Ctx:
    return replace(ctx, sessions=[d for d in ctx.sessions if w[0] <= d <= w[1]])


def bootstrap_dd(pnl: np.ndarray, sims: int = 2000, block: int = 20, seed: int = 7) -> dict:
    """Block-bootstrap the daily P&L to estimate the distribution of max drawdown."""
    rng = np.random.default_rng(seed)
    n = len(pnl)
    starts_max = n - block
    dds = []
    for _ in range(sims):
        idx = np.concatenate(
            [np.arange(s, s + block) for s in rng.integers(0, starts_max, size=n // block + 1)]
        )[:n]
        eq = np.cumsum(pnl[idx])
        dds.append(float(-(eq - np.maximum.accumulate(np.r_[0.0, eq])[1:]).min()))
    return {
        "p50": float(np.percentile(dds, 50)),
        "p95": float(np.percentile(dds, 95)),
        "p99": float(np.percentile(dds, 99)),
    }


def compact(r: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in r.items() if k != "equity"}


def main() -> None:
    out: dict[str, Any] = {}
    stress = Slippage(option_pct=0.01, option_min_points=0.2, sl_fill_worst=True, futures_mult=2.0)
    for index in INDICES:
        base = build_ctx(index, MAIN)
        ext = build_ctx(index, EXTENDED)
        stressed = replace(base, slip=stress)
        for name, (fn, kw, grid) in SHORTLIST.items():
            res: dict[str, Any] = {}
            trades = fn(base, **kw)
            full = summarize(trades, base.sessions)
            res["main"] = full
            res["bootstrap_dd"] = bootstrap_dd(daily_pnl(trades, base.sessions))
            for label, w in (
                ("design_2020_22", DESIGN),
                ("holdout_2023_25", HOLDOUT),
                ("post_rules_2024_11", POST_RULES),
            ):
                sub = window(base, w)
                res[label] = compact(summarize(fn(sub, **kw), sub.sessions))
            res["stress_2x_slip_worst_fill"] = compact(
                summarize(fn(stressed, **kw), stressed.sessions)
            )
            res["extended_2017_20_vix_model"] = compact(summarize(fn(ext, **kw), ext.sessions))
            covid = window(ext, (date(2020, 2, 1), date(2020, 4, 30)))
            res["covid_crash_feb_apr_2020"] = compact(summarize(fn(covid, **kw), covid.sessions))
            grid_res = []
            for g in grid:
                r = summarize(fn(base, **g), base.sessions)
                grid_res.append(
                    {
                        "params": {k: v for k, v in g.items() if k != "name"},
                        "net_pnl": r.get("net_pnl", 0.0),
                        "sharpe": r.get("sharpe", 0.0),
                        "max_drawdown": r.get("max_drawdown", 0.0),
                        "annual_return_on_margin_pct": r.get("annual_return_on_margin_pct", 0.0),
                    }
                )
            res["grid"] = grid_res
            out.setdefault(name, {})[index] = res
            pos = sum(1 for g in grid_res if g["net_pnl"] > 0)
            print(
                f"{index:9s} {name:22s} main ₹{full['net_pnl']:>9,.0f} sh {full['sharpe']:.2f}"
                f" | design ₹{res['design_2020_22'].get('net_pnl', 0):>9,.0f}"
                f" holdout ₹{res['holdout_2023_25'].get('net_pnl', 0):>9,.0f}"
                f" post-rules ₹{res['post_rules_2024_11'].get('net_pnl', 0):>8,.0f}"
                f" | stress ₹{res['stress_2x_slip_worst_fill'].get('net_pnl', 0):>9,.0f}"
                f" | 2017-20 ₹{res['extended_2017_20_vix_model'].get('net_pnl', 0):>9,.0f}"
                f" covid ₹{res['covid_crash_feb_apr_2020'].get('net_pnl', 0):>8,.0f}"
                f" | grid +{pos}/{len(grid_res)} | DD p95 ₹{res['bootstrap_dd']['p95']:>8,.0f}",
                flush=True,
            )
    (CACHE / "study_deep.json").write_text(json.dumps(out, default=str))


if __name__ == "__main__":
    main()
