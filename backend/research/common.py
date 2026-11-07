"""Shared construction of the volatility model for research scripts."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from app.backtesting.data import DayBars
from app.backtesting.pricing import Smile
from app.backtesting.vol import Clock, VolModel

BETA_WINDOW = (date(2017, 4, 1), date(2020, 4, 30))  # calibrated before the main test window


def spot_vol_beta(bars: dict[date, DayBars], vix_close: pd.Series) -> float:
    """−slope of daily Δln(VIX) on daily index log return, over BETA_WINDOW only."""
    s = pd.Series(
        {d: b.close[-1] for d, b in bars.items() if BETA_WINDOW[0] <= d <= BETA_WINDOW[1]}
    ).sort_index()
    v = vix_close.reindex(s.index).ffill()
    df = pd.DataFrame({"r": np.log(s).diff(), "v": np.log(v).diff()}).dropna()
    return float(-np.polyfit(df["r"], df["v"], 1)[0])


def make_model(
    index: str,
    bars: dict[date, DayBars],
    surf: pd.DataFrame,
    vix: pd.DataFrame,
    clock: Clock,
    cfg: dict,
    beta: float | None = None,
) -> VolModel:
    fb = cfg["fallback"][index]
    b = beta if beta is not None else cfg.get("spot_vol_beta", {}).get(index, 0.0)
    return VolModel(
        index,
        surf,
        vix,
        clock,
        fb["k"],
        Smile(fb["s1"], fb["s2"]),
        b,
        day_open={d: float(x.open[0]) for d, x in bars.items()},
        day_close={d: float(x.close[-1]) for d, x in bars.items()},
    )
