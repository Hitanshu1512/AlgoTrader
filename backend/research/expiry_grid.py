"""Extended parameter surface for the expiry-day straddle (design vs holdout vs stress)."""

from __future__ import annotations

import json
from dataclasses import replace

from app.backtesting.charges import Slippage
from app.backtesting.data import CACHE
from app.backtesting.metrics import summarize
from app.backtesting.strategies import fno
from research.run_deep import DESIGN, HOLDOUT, window
from research.run_fno_study import EXTENDED, MAIN, build_ctx

ENTRIES = {"09:20": 5, "10:00": 45, "11:00": 105, "12:00": 165, "13:00": 225}
SLS = [0.3, 0.5, 0.75, 1.0, 9.0]  # 9.0 ≈ no stop


def main() -> None:
    stress = Slippage(option_pct=0.01, option_min_points=0.2, sl_fill_worst=True)
    out = {}
    for index in ("NIFTY", "BANKNIFTY"):
        base = build_ctx(index, MAIN)
        ext = build_ctx(index, EXTENDED)
        des, hold = window(base, DESIGN), window(base, HOLDOUT)
        st = replace(base, slip=stress)
        rows = []
        for el, eb in ENTRIES.items():
            for sl in SLS:
                kw = {"sl": sl, "expiry_only": True, "entry_bar": eb, "name": "x"}
                r = {
                    w: summarize(fno.straddle_920(c, **kw), c.sessions)
                    for w, c in (
                        ("design", des),
                        ("holdout", hold),
                        ("stress", st),
                        ("ext2017_20", ext),
                    )
                }
                rows.append(
                    {
                        "entry": el,
                        "sl": sl,
                        **{
                            f"{w}_{m}": r[w][m]
                            for w in r
                            for m in ("net_pnl", "sharpe", "max_drawdown", "worst_trade")
                        },
                    }
                )
                x = rows[-1]
                print(
                    f"{index:9s} entry {el} SL {'none' if sl > 5 else f'{sl:.0%}':>4s} | design ₹{x['design_net_pnl']:>8,.0f} sh {x['design_sharpe']:.2f}"
                    f" | holdout ₹{x['holdout_net_pnl']:>8,.0f} sh {x['holdout_sharpe']:.2f} DD ₹{x['holdout_max_drawdown']:>7,.0f}"
                    f" | stress sh {x['stress_sharpe']:.2f} | 2017-20 sh {x['ext2017_20_sharpe']:.2f} worst ₹{x['ext2017_20_worst_trade']:>7,.0f}"
                    f" | worst trade ₹{min(x['design_worst_trade'], x['holdout_worst_trade']):>7,.0f}",
                    flush=True,
                )
        out[index] = rows
    (CACHE / "study_expiry_grid.json").write_text(json.dumps(out))


if __name__ == "__main__":
    main()
