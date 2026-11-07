"""Walk-forward check: pick parameters on 2020–22 only, evaluate on 2023–25 only."""

from __future__ import annotations

import json

from app.backtesting.data import CACHE
from app.backtesting.metrics import summarize
from research.run_deep import DESIGN, HOLDOUT, SHORTLIST, window
from research.run_fno_study import MAIN, build_ctx


def main() -> None:
    out = {}
    for index in ("NIFTY", "BANKNIFTY"):
        base = build_ctx(index, MAIN)
        des, hold = window(base, DESIGN), window(base, HOLDOUT)
        for name in ("Expiry-day straddle", "920 short strangle"):
            fn, default, grid = SHORTLIST[name]
            scored = [(summarize(fn(des, **g), des.sessions)["sharpe"], g) for g in grid]
            best_s, best = max(scored, key=lambda x: x[0])
            tuned = summarize(fn(hold, **best), hold.sessions)
            dflt = (
                summarize(fn(hold, **default), hold.sessions)
                if default
                else summarize(fn(hold), hold.sessions)
            )
            out[f"{index}/{name}"] = {
                "chosen_on_design": {k: v for k, v in best.items() if k != "name"},
                "design_sharpe": best_s,
                "holdout_tuned": {k: tuned[k] for k in ("net_pnl", "sharpe", "max_drawdown")},
                "holdout_default": {k: dflt[k] for k in ("net_pnl", "sharpe", "max_drawdown")},
            }
            print(index, name, json.dumps(out[f"{index}/{name}"], default=lambda x: round(x, 2)))
    (CACHE / "study_walkforward.json").write_text(json.dumps(out))


if __name__ == "__main__":
    main()
