"""Expiry-day check for cheap out-of-the-money options (what "hero-zero" buyers pay).

For every expiry day, strikes 0.3–1.0% out of the money (calls above, puts below the
opening spot): compare the model's day-low and day-high with the real NSE bhavcopy.
On expiry day an OTM option's low is usually printed in the afternoon, so the day-low
is the closest EOD proxy for the afternoon price a hero-zero buyer pays; the day-high
shows whether the model captures the spikes that make these trades pay off.

Usage: uv run python -m research.validate_otm_expiry
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
        err_low, err_high, lows_model, lows_actual = [], [], [], []
        for d in sessions:
            if d < START or d > END or not cal.is_expiry(d):
                continue
            b = allbars[d]
            pricer = LegPricer(model, Path.from_days([b]))
            s0 = float(b.open[0])
            for is_call, opt in ((True, "CE"), (False, "PE")):
                for frac in (0.003, 0.005, 0.0075, 0.01):
                    k = float(round(s0 * (1 + frac if is_call else 1 - frac) / step) * step)
                    a = actual.get((sym, d, d, k, opt))
                    if a is None or a[2] < 0.5 or a[1] < 1:  # skip sub-₹0.5 lows (tick noise)
                        continue
                    arr = pricer.arrays(Leg(k, is_call, 1, d), 0, BARS_PER_DAY - 1)
                    allpx = np.r_[arr["open"], arr["sh"], arr["sl"]]
                    m_low, m_high = max(float(allpx.min()), 0.05), float(allpx.max())
                    err_low.append(np.log(m_low / a[2]))
                    err_high.append(np.log(m_high / a[1]))
                    lows_model.append(m_low)
                    lows_actual.append(a[2])
        res = {}
        for name, v in (("otm_day_low", err_low), ("otm_day_high", err_high)):
            arr_v = np.array(v)
            res[name] = {
                "n": len(arr_v),
                "median_bias_pct": float(np.median(arr_v) * 100),
                "median_abs_err_pct": float(np.median(np.abs(arr_v)) * 100),
            }
            print(
                f"{sym} expiry-day {name:13s} n={len(arr_v):4d} median bias "
                f"{res[name]['median_bias_pct']:+6.1f}%  median |err| "
                f"{res[name]['median_abs_err_pct']:5.1f}%"
            )
        res["median_low_rupees"] = {
            "model": float(np.median(lows_model)),
            "actual": float(np.median(lows_actual)),
        }
        print(
            f"{sym} median day-low ₹ model {np.median(lows_model):.2f} "
            f"actual {np.median(lows_actual):.2f}"
        )
        out[sym] = res
    cfg["otm_expiry_validation"] = out
    (CACHE / "calibration.json").write_text(json.dumps(cfg, indent=2))


if __name__ == "__main__":
    main()
