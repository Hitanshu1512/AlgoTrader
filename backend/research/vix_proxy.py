"""India VIX substitute for 2026 (our VIX file ends 31 Dec 2025).

India VIX is computed by NSE from Nifty option prices, so we rebuild a 30-day ATM implied
volatility from the real bhavcopy surfaces, calibrate VIX ≈ a + b·IV30 on 2020–2025 only,
and apply it to 2026. The 2026 "open" is the previous close moved by the overnight Nifty gap
through the spot–vol beta (no intraday VIX open exists for these days).

Also extends data/cache/surfaces.parquet with 2026 option surfaces.
Output: data/cache/vix_2026_proxy.csv
"""

from __future__ import annotations

import json
from datetime import date

import numpy as np
import pandas as pd

from app.backtesting.data import CACHE, load_index_days, load_vix
from app.backtesting.vol import build_surfaces


def iv30(surf: pd.DataFrame) -> pd.Series:
    out = {}
    for d, g in surf[surf["symbol"] == "NIFTY"].groupby("date"):
        t = np.array([(e - d).days for e in g["expiry"]], dtype=float)
        w = (g["atm_iv_cal"].to_numpy() ** 2) * t / 365  # calendar total variance
        order = np.argsort(t)
        t, w = t[order], w[order]
        if t.min() > 30 or t.max() < 30:
            continue
        out[d] = float(np.sqrt(np.interp(30, t, w) * 365 / 30))
    return pd.Series(out).sort_index()


def main() -> None:
    surf = pd.read_parquet(CACHE / "surfaces.parquet")
    eod = pd.read_parquet(CACHE / "option_eod.parquet")
    new = eod[eod["date"] > date(2025, 12, 31)]
    if not (surf["date"] > date(2025, 12, 31)).any() and len(new):
        spot = {
            i: {
                d: float(b.close[-1])
                for d, b in load_index_days(i, date(2025, 12, 1), date(2026, 12, 31)).items()
            }
            for i in ("NIFTY", "BANKNIFTY")
        }
        add = build_surfaces(new, spot)
        surf = pd.concat([surf, add], ignore_index=True)
        surf.to_parquet(CACHE / "surfaces.parquet", index=False)
        print(f"added {len(add)} surfaces for 2026 ({add['date'].nunique()} days)")
    vix = load_vix()
    x = iv30(surf)
    hist = pd.DataFrame({"iv30": x, "vix": vix["close"].reindex(x.index)}).dropna()
    b, a = np.polyfit(hist["iv30"] * 100, hist["vix"], 1)
    fit = a + b * hist["iv30"] * 100
    resid = hist["vix"] - fit
    r2 = 1 - resid.var() / hist["vix"].var()
    print(
        f"calibration 2020–2025: VIX = {a:.2f} + {b:.3f}·IV30  (n={len(hist)}, R²={r2:.3f}, "
        f"residual sd {resid.std():.2f} VIX pts, median abs {resid.abs().median():.2f})"
    )
    cfg = json.loads((CACHE / "calibration.json").read_text())
    beta = cfg["spot_vol_beta"]["NIFTY"]
    nifty = load_index_days("NIFTY", date(2025, 12, 1), date(2026, 12, 31))
    rows = []
    prev_close = float(vix["close"].iloc[-1])
    prev_spot = float(nifty[max(d for d in nifty if d <= vix.index[-1])].close[-1])
    for d in sorted(k for k in x.index if k > vix.index[-1]):
        if d not in nifty:
            continue
        gap = np.log(nifty[d].open[0] / prev_spot)
        o = prev_close * np.exp(-beta * gap)
        c = float(a + b * x[d] * 100)
        rows.append((d, o, c))
        prev_close, prev_spot = c, float(nifty[d].close[-1])
    out = pd.DataFrame(rows, columns=["date", "open", "close"])
    (CACHE / "vix_2026_proxy.csv").write_text(out.to_csv(index=False))
    cfg["vix_proxy"] = {
        "a": a,
        "b": b,
        "r2": r2,
        "resid_sd": float(resid.std()),
        "n": len(hist),
        "days": len(out),
    }
    (CACHE / "calibration.json").write_text(json.dumps(cfg, indent=2))
    print(out.head(25).round(2).to_string(index=False))


if __name__ == "__main__":
    main()
