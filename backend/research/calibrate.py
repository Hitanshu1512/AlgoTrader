"""Calibrate / validate the option-pricing model against a real NSE F&O bhavcopy.

Usage: uv run python research/calibrate.py
Prints per-strike model vs actual prices and the fitted smile parameters.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from app.backtesting.data import RAW, load_index_days, load_vix
from app.backtesting.pricing import Smile, black76, forward, implied_vol

DAY = date(2024, 1, 5)
EXPIRY = {"NIFTY": date(2024, 1, 11), "BANKNIFTY": date(2024, 1, 10)}
OUT = Path(__file__).resolve().parents[1] / "data" / "cache" / "calibration.json"


def realized_ratio(day: date) -> float:
    closes = {}
    for idx in ("NIFTY", "BANKNIFTY"):
        days = load_index_days(idx, date(2023, 9, 1), day)
        s = pd.Series({d: b.close[-1] for d, b in days.items() if d < day}).sort_index()
        closes[idx] = np.log(s).diff().dropna().tail(60)
    return float(closes["BANKNIFTY"].std() / closes["NIFTY"].std())


def main() -> None:
    bhav = pd.read_csv(RAW / "bhavcopy" / "fo05JAN2024bhav.csv")
    vix = load_vix().loc[DAY]
    ratio = realized_ratio(DAY)
    results = {}
    for idx in ("NIFTY", "BANKNIFTY"):
        spot = load_index_days(idx, DAY, DAY)[DAY].close[-1]
        exp = EXPIRY[idx]
        t = (
            datetime.combine(exp, datetime.min.time()).replace(hour=15, minute=30)
            - datetime.combine(DAY, datetime.min.time()).replace(hour=15, minute=30)
        ).total_seconds() / (365 * 86400)
        f = float(forward(idx, spot, t))
        rows = bhav[
            (bhav.INSTRUMENT == "OPTIDX")
            & (bhav.SYMBOL == idx)
            & (pd.to_datetime(bhav.EXPIRY_DT, format="%d-%b-%Y").dt.date == exp)
        ]
        rows = rows[(rows.CONTRACTS > 100) & (abs(rows.STRIKE_PR / spot - 1) < 0.06)]
        pts = []
        for r in rows.itertuples():
            # Use out-of-the-money options only (most liquid, cleanest IV).
            is_call = r.OPTION_TYP == "CE"
            if (is_call and r.STRIKE_PR < f) or (not is_call and r.STRIKE_PR > f):
                continue
            iv = implied_vol(float(r.CLOSE), f, float(r.STRIKE_PR), t, is_call)
            if iv:
                pts.append((float(r.STRIKE_PR), is_call, float(r.CLOSE), iv))
        k = np.array([p[0] for p in pts])
        iv = np.array([p[3] for p in pts])
        atm_iv = float(np.interp(f, k, iv))
        x = np.log(k / f) / (atm_iv * np.sqrt(t))
        y = iv / atm_iv - 1
        s1, s2 = np.linalg.lstsq(np.c_[x, x * x], y, rcond=None)[0]
        model_atm = vix["close"] / 100 * (ratio if idx == "BANKNIFTY" else 1.0)
        smile = Smile(float(s1), float(s2))
        model_px = [
            float(
                black76(
                    np.array(f),
                    kk,
                    t,
                    model_atm
                    * smile.multiplier(np.array(np.log(kk / f) / (model_atm * np.sqrt(t)))),
                    c,
                )
            )
            for kk, c, _, _ in pts
        ]
        actual = np.array([p[2] for p in pts])
        err = np.array(model_px) - actual
        results[idx] = {
            "spot": spot,
            "expiry": exp.isoformat(),
            "t_days": t * 365,
            "market_atm_iv": atm_iv,
            "model_atm_iv": model_atm,
            "vix_close": float(vix["close"]),
            "bn_rv_ratio": ratio if idx == "BANKNIFTY" else None,
            "s1": float(s1),
            "s2": float(s2),
            "n_strikes": len(pts),
            "mean_abs_err_pts": float(np.mean(np.abs(err))),
            "median_pct_err": float(np.median(err / actual) * 100),
            "atm_straddle_actual": None,
            "points": [
                {"strike": kk, "type": "CE" if c else "PE", "actual": a, "model": m}
                for (kk, c, a, _), m in zip(pts, model_px, strict=True)
            ],
        }
        print(
            f"{idx}: spot {spot:.1f} F {f:.1f} T {t * 365:.1f}d  market ATM IV {atm_iv:.2%}"
            f"  model ATM IV {model_atm:.2%} (VIX {vix['close']:.2f}"
            f"{f', BN/N RV ratio {ratio:.2f}' if idx == 'BANKNIFTY' else ''})"
        )
        print(
            f"   smile fit s1={s1:+.3f} s2={s2:+.3f}  strikes={len(pts)}"
            f"  mean |model−actual| = {np.mean(np.abs(err)):.2f} pts,"
            f" median error {np.median(err / actual) * 100:+.1f}%"
        )
        for (kk, c, a, _), m in list(zip(pts, model_px, strict=True))[:: max(1, len(pts) // 10)]:
            print(f"     {kk:>8.0f} {'CE' if c else 'PE'}  actual {a:8.2f}  model {m:8.2f}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
