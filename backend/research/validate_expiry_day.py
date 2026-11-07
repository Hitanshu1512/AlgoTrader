"""Expiry-day (0DTE) check: model vs actual NSE open/high/low for ATM options on expiry days.

Also compares *ATM straddle premium at the open* (model vs actual) — the premium an
expiry-day seller actually collects — and the high-of-day of each leg (stop realism).
"""

from __future__ import annotations

import json
from datetime import date

import numpy as np

from app.backtesting.calendar import STRIKE_STEP, ExpiryCalendar
from app.backtesting.data import BARS_PER_DAY, CACHE, load_index_days
from app.backtesting.sim import Leg, LegPricer, Path
from app.backtesting.vol import Clock
from research.common import make_model
from research.validate_pricing import END, START, load_inputs


def main() -> None:
    eod, _spot, surf, vix = load_inputs()
    cfg = json.loads((CACHE / "calibration.json").read_text())
    opts = eod[(eod["inst"] == "OPT") & (eod["contracts"] >= 500)]
    actual = {
        (r.symbol, r.date, r.expiry, r.strike, r.opt): (r.open, r.high, r.low, r.close)
        for r in opts.itertuples()
    }
    out = {}
    for sym in ("NIFTY", "BANKNIFTY"):
        allbars = load_index_days(sym, date(2017, 4, 1), END)
        sessions = sorted(allbars)
        model = make_model(sym, allbars, surf, vix, Clock(sessions, **cfg["clock"]), cfg)
        cal = ExpiryCalendar(sym, sessions)
        step = STRIKE_STEP[sym]
        e_open, e_high, straddle_open = [], [], []
        for d in sessions:
            if d < START or d > END or not cal.is_expiry(d):
                continue
            b = allbars[d]
            path = Path.from_days([b])
            pricer = LegPricer(model, path)
            k = float(round(b.open[0] / step) * step)
            legs = {}
            for is_call, opt in ((True, "CE"), (False, "PE")):
                a = actual.get((sym, d, d, k, opt))
                if a is None or a[0] < 1:
                    continue
                arr = pricer.arrays(Leg(k, is_call, -1, d), 0, BARS_PER_DAY - 1)
                hi = max(arr["sh"].max(), arr["sl"].max(), arr["open"][0])
                e_open.append(np.log(arr["open"][0] / a[0]))
                e_high.append(np.log(hi / a[1]))
                legs[opt] = (arr["open"][0], a[0])
            if len(legs) == 2:
                straddle_open.append(
                    np.log(sum(v[0] for v in legs.values()) / sum(v[1] for v in legs.values()))
                )
        res = {}
        for name, v in (
            ("leg_open", e_open),
            ("leg_day_high", e_high),
            ("straddle_open", straddle_open),
        ):
            v = np.array(v)
            res[name] = {
                "n": len(v),
                "median_bias_pct": float(np.median(v) * 100),
                "median_abs_err_pct": float(np.median(np.abs(v)) * 100),
                "mean_bias_pct": float(np.mean(v) * 100),
            }
            print(
                f"{sym} expiry-day {name:14s} n={len(v):3d} median bias {res[name]['median_bias_pct']:+6.1f}%"
                f"  mean bias {res[name]['mean_bias_pct']:+6.1f}%  median |err| {res[name]['median_abs_err_pct']:5.1f}%"
            )
        out[sym] = res
    cfg["expiry_day_validation"] = out
    (CACHE / "calibration.json").write_text(json.dumps(cfg, indent=2))


if __name__ == "__main__":
    main()
