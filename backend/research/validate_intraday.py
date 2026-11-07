"""Check the model's intraday option high/low against real NSE daily option high/low.

For the ATM CE and PE of the nearest expiry, price every minute of day d+1 (using the
day-d surface) at the bar's spot extremes and compare the day's model max/min with the
actual bhavcopy HIGH/LOW. Stop-loss realism depends on this.
"""

from __future__ import annotations

import json
from datetime import date

import numpy as np

from app.backtesting.calendar import STRIKE_STEP
from app.backtesting.data import BARS_PER_DAY, CACHE, load_index_days
from app.backtesting.sim import Leg, LegPricer, Path
from app.backtesting.vol import Clock
from research.common import make_model
from research.validate_pricing import END, START, load_inputs


def main() -> None:
    eod, spot, surf, vix = load_inputs()
    cfg = json.loads((CACHE / "calibration.json").read_text())
    opts = eod[(eod["inst"] == "OPT") & (eod["contracts"] >= 500)]
    actual = {
        (r.symbol, r.date, r.expiry, r.strike, r.opt): (r.open, r.high, r.low, r.close)
        for r in opts.itertuples()
    }
    out = {}
    for sym in ("NIFTY", "BANKNIFTY"):
        bars = load_index_days(sym, START, END)
        sessions = sorted(spot[sym])
        clock = Clock(sessions, **cfg["clock"])
        allbars = load_index_days(sym, date(2017, 4, 1), END)
        model = make_model(sym, allbars, surf, vix, clock, cfg)
        step = STRIKE_STEP[sym]
        errs: dict[str, list[float]] = {
            "high": [],
            "low": [],
            "open": [],
            "close": [],
            "put_high_down_day": [],
            "call_high_up_day": [],
        }
        for d in sorted(bars):
            pass
            exp = model.prev_session(d)
            cand = surf[(surf.symbol == sym) & (surf.date == exp)]
            if cand.empty:
                continue
            e = min(x for x in cand.expiry if x >= d)
            path = Path.from_days([bars[d]])
            pricer = LegPricer(model, path)
            k = round(float(bars[d].open[0]) / step) * step
            for is_call, opt in ((True, "CE"), (False, "PE")):
                a = actual.get((sym, d, e, float(k), opt))
                if a is None or min(a) < 2 or a[2] <= 0:
                    continue
                arr = pricer.arrays(Leg(float(k), is_call, -1, e), 0, BARS_PER_DAY - 1)
                hi = max(arr["sh"].max(), arr["sl"].max(), arr["open"][0])
                lo = min(arr["sh"].min(), arr["sl"].min(), arr["open"][0])
                errs["high"].append(np.log(hi / a[1]))
                errs["low"].append(np.log(lo / a[2]))
                errs["open"].append(np.log(arr["open"][0] / a[0]))
                errs["close"].append(np.log(arr["close"][-1] / a[3]))
                ret = bars[d].close[-1] / bars[d].open[0] - 1
                if not is_call and ret < -0.01:
                    errs["put_high_down_day"].append(np.log(hi / a[1]))
                if is_call and ret > 0.01:
                    errs["call_high_up_day"].append(np.log(hi / a[1]))
        out[sym] = {
            k: {
                "n": len(v),
                "median_bias_pct": float(np.median(v) * 100),
                "median_abs_err_pct": float(np.median(np.abs(v)) * 100),
                "p10_pct": float(np.percentile(v, 10) * 100),
                "p90_pct": float(np.percentile(v, 90) * 100),
            }
            for k, v in errs.items()
        }
        for k, v in out[sym].items():
            print(
                f"{sym} ATM day-{k}: n={v['n']} median bias {v['median_bias_pct']:+.1f}%"
                f"  median |err| {v['median_abs_err_pct']:.1f}%  p10/p90 {v['p10_pct']:+.0f}%/"
                f"{v['p90_pct']:+.0f}%"
            )
    cfg["intraday_validation"] = out
    (CACHE / "calibration.json").write_text(json.dumps(cfg, indent=2))


if __name__ == "__main__":
    main()
