"""Build the volatility surfaces and validate the option-pricing model on real NSE prices.

1. Fit an ATM-variance + smile surface for every (index, day, expiry) from bhavcopy closes.
2. For each candidate variance-clock weighting, use the day-d surface (+ day d+1 VIX move)
   to predict day d+1 closing prices of ATM and ~1% OTM options, and compare with the
   actual NSE closes. The weighting with the smallest error is saved for the study.

Usage: uv run python research/validate_pricing.py
"""

from __future__ import annotations

import json
from datetime import date

import numpy as np
import pandas as pd

from app.backtesting.calendar import STRIKE_STEP
from app.backtesting.data import BARS_PER_DAY, CACHE, load_index_days, load_vix
from app.backtesting.vol import Clock, build_surfaces
from research.common import make_model, spot_vol_beta

START, END = date(2020, 4, 1), date(2025, 12, 31)
BARS: dict = {}
OUT = CACHE / "calibration.json"


def load_inputs() -> tuple[pd.DataFrame, dict[str, dict], pd.DataFrame, pd.DataFrame]:
    eod = pd.read_parquet(CACHE / "option_eod.parquet")
    eod = eod[(eod["date"] >= START) & (eod["date"] <= END)]
    days = {i: load_index_days(i, date(2017, 4, 1), END) for i in ("NIFTY", "BANKNIFTY")}
    global BARS
    BARS = days
    spot = {i: {d: float(b.close[-1]) for d, b in days[i].items()} for i in days}
    surf_path = CACHE / "surfaces.parquet"
    if surf_path.exists():
        surf = pd.read_parquet(surf_path)
    else:
        surf = build_surfaces(eod, spot)
        surf.to_parquet(surf_path, index=False)
    return eod, spot, surf, load_vix()


def main() -> None:
    eod, spot, surf, vix = load_inputs()
    print(
        f"surfaces: {len(surf)} rows, days per index:",
        surf.groupby("symbol")["date"].nunique().to_dict(),
    )
    vix_close = vix["close"]
    result: dict[str, object] = {}

    # Market ATM IV vs India VIX for the nearest expiry, by days-to-expiry.
    nearest = surf.sort_values("expiry").groupby(["symbol", "date"]).head(1).copy()
    nearest["dte"] = [(e - d).days for d, e in zip(nearest["date"], nearest["expiry"], strict=True)]
    nearest["vix"] = [float(vix_close.get(d, np.nan)) / 100 for d in nearest["date"]]
    nearest["ratio"] = nearest["atm_iv_cal"] / nearest["vix"]
    fallback = {}
    for sym, g in nearest.groupby("symbol"):
        g = g[(g["dte"] >= 1) & (g["dte"] <= 8)].dropna()
        fallback[sym] = {
            "k": float(g["ratio"].median()),
            "s1": float(g["s1"].median()),
            "s2": float(g["s2"].median()),
        }
        by_dte = g.groupby("dte")["ratio"].median().round(2).to_dict()
        print(
            f"{sym}: market ATM IV / VIX (nearest expiry, 1–8 DTE) median {fallback[sym]['k']:.2f}"
            f"  by DTE {by_dte}; median smile s1 {fallback[sym]['s1']:+.3f} s2 {fallback[sym]['s2']:+.3f}"
        )
    result["fallback"] = fallback
    result["spot_vol_beta"] = {i: spot_vol_beta(BARS[i], vix_close) for i in ("NIFTY", "BANKNIFTY")}
    print(
        "spot-vol beta (2017-04..2020-04):",
        {k: round(v, 2) for k, v in result["spot_vol_beta"].items()},
    )

    # Actual next-day closes to predict.
    opts = eod[(eod["inst"] == "OPT") & (eod["contracts"] >= 200)]
    actual = {(r.symbol, r.date, r.expiry, r.strike, r.opt): r.close for r in opts.itertuples()}

    grid = [
        (0.0, 0.0),
        (0.15, 0.15),
        (0.3, 0.3),
        (0.3, 0.15),
        (0.5, 0.5),
        (1.0, 1.0),
        (0.15, 0.0),
        (0.3, 0.0),
    ]
    best = None
    for on_w, cd_w in grid:
        errs: dict[str, list[tuple[float, str]]] = {"NIFTY": [], "BANKNIFTY": []}
        for sym in ("NIFTY", "BANKNIFTY"):
            sessions = sorted(spot[sym])
            clock = Clock(sessions, on_w, cd_w)
            model = make_model(sym, BARS[sym], surf, vix, clock, result)
            step = STRIKE_STEP[sym]
            sub = surf[surf["symbol"] == sym]
            for r in sub.itertuples():
                d = r.date
                i = sessions.index(d) if d in spot[sym] else -1
                if i < 0 or i + 1 >= len(sessions):
                    continue
                d1 = sessions[i + 1]
                if r.expiry < d1 or d1 > END:
                    continue
                s1 = spot[sym][d1]
                sigma, smile = model.anchor(d1, r.expiry)
                vm = model.vix_path(d1)
                atm = round(s1 / step) * step
                for k, opt, tag in (
                    (atm, "CE", "atm"),
                    (atm, "PE", "atm"),
                    (round(s1 * 1.01 / step) * step, "CE", "otm"),
                    (round(s1 * 0.99 / step) * step, "PE", "otm"),
                ):
                    a = actual.get((sym, d1, r.expiry, float(k), opt))
                    if a is None or a < 2:
                        continue
                    p = float(
                        model.price(
                            d1,
                            r.expiry,
                            np.array([s1]),
                            float(k),
                            opt == "CE",
                            np.array([BARS_PER_DAY - 1]),
                            sigma,
                            smile,
                            vm,
                        )[0]
                    )
                    if p > 0:
                        errs[sym].append((np.log(p / a), tag))
        summary = {}
        score = 0.0
        for sym, e in errs.items():
            for tag in ("atm", "otm"):
                v = np.array([x for x, t in e if t == tag])
                summary[f"{sym}_{tag}"] = {
                    "n": len(v),
                    "median_bias_pct": float(np.median(v) * 100),
                    "median_abs_err_pct": float(np.median(np.abs(v)) * 100),
                }
                score += abs(np.median(v)) + np.median(np.abs(v))
        print(
            f"clock overnight={on_w:.2f} closed-day={cd_w:.2f} score={score:.3f} "
            + "  ".join(
                f"{k}: bias {v['median_bias_pct']:+.1f}% |err| {v['median_abs_err_pct']:.1f}% (n={v['n']})"
                for k, v in summary.items()
            )
        )
        if best is None or score < best[0]:
            best = (score, on_w, cd_w, summary)
    assert best is not None
    result["clock"] = {"overnight_w": best[1], "closed_day_w": best[2]}
    result["validation"] = best[3]
    print("selected clock:", result["clock"])
    OUT.write_text(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
