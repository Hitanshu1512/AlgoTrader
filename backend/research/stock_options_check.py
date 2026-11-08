"""Are liquid stock options usable with ₹10k–₹1 lakh? Real premiums × lot sizes, Jul 2024 – Nov 2026.

For each stock and trading day: nearest monthly expiry with ≥ 5 days left, ATM call and put
(strike nearest the underlying), premium × lot, contract notional, and the traded volume.
Usage: uv run python -m research.stock_options_check
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from app.backtesting.data import CACHE
from research.build_eod_v2 import STOCKS


def main() -> None:
    d = pd.read_parquet(CACHE / "option_eod_v2.parquet")
    d = d[d["symbol"].isin(STOCKS) & (d["inst"] == "OPT")].copy()
    d["dte"] = (pd.to_datetime(d["expiry"]) - pd.to_datetime(d["date"])).dt.days
    d = d[d["dte"] >= 5]
    near = d.groupby(["symbol", "date"])["expiry"].transform("min")
    d = d[d["expiry"] == near]
    d["dist"] = (d["strike"] - d["underlying"]).abs()
    atm = d.loc[d.groupby(["symbol", "date", "opt"])["dist"].idxmin()]
    out = {}
    for sym, g in atm.groupby("symbol"):
        prem = g["close"] * g["lot"]
        notional = g["underlying"] * g["lot"]
        out[sym] = {
            "lot_latest": int(g.sort_values("date")["lot"].iloc[-1]),
            "median_atm_premium_per_lot": float(prem.median()),
            "p10_atm_premium_per_lot": float(prem.quantile(0.1)),
            "median_notional_per_lot": float(notional.median()),
            "median_contracts_atm": float(g["contracts"].median()),
        }
        print(
            f"{sym:11s} lot {out[sym]['lot_latest']:5d}  ATM monthly premium per lot: median "
            f"₹{out[sym]['median_atm_premium_per_lot']:>8,.0f} (10th pct ₹{out[sym]['p10_atm_premium_per_lot']:>7,.0f})"
            f"  notional ₹{out[sym]['median_notional_per_lot'] / 1e5:5.1f} lakh"
            f"  ATM contracts/day {out[sym]['median_contracts_atm']:,.0f}"
        )
    idx = {}
    v2 = pd.read_parquet(
        CACHE / "option_eod_v2.parquet", filters=[("date", ">=", pd.Timestamp("2025-11-01").date())]
    )
    for sym in ("NIFTY", "BANKNIFTY", "FINNIFTY"):
        g = v2[(v2["symbol"] == sym) & (v2["inst"] == "OPT")].copy()
        g["dte"] = (pd.to_datetime(g["expiry"]) - pd.to_datetime(g["date"])).dt.days
        g = g[g["dte"] >= 3]
        g = g[g["expiry"] == g.groupby("date")["expiry"].transform("min")]
        g["dist"] = (g["strike"] - g["underlying"]).abs()
        a = g.loc[g.groupby(["date", "opt"])["dist"].idxmin()]
        idx[sym] = float(np.median(a["close"] * a["lot"]))
        print(
            f"{sym:11s} ATM premium per lot (nearest expiry ≥ 3 days, Nov 2025 – Nov 2026): median ₹{idx[sym]:,.0f}"
        )
    (CACHE / "stock_options_check.json").write_text(json.dumps({"stocks": out, "indices": idx}))


if __name__ == "__main__":
    main()
