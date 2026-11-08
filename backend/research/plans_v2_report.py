"""Tables for docs/research/revised_plans_real_prices.md (from plans_v2*.json).

Usage: uv run python -m research.plans_v2_report
"""

from __future__ import annotations

import json
from pathlib import Path

from app.backtesting.data import CACHE
from research.stage2_report import ind

DOCS = Path(__file__).resolve().parents[2] / "docs" / "research" / "revised_plans"


def r(x: float) -> str:
    return ("−₹" if x < 0 else "₹") + ind(abs(x))


def main() -> None:
    study = json.loads((CACHE / "plans_v2.json").read_text())["results"]
    acc = json.loads((CACHE / "plans_v2_accounts.json").read_text())
    lev = json.loads((CACHE / "plans_v2_leverage.json").read_text())
    out: list[str] = []
    out.append("## Walk-forward out-of-sample results per lot (Jan 2022 – Nov 2026)\n")
    out.append(
        "| Strategy | Index | Trades | Net per lot | Per year | Win % | Profit factor | "
        "Max DD per lot | 2× slippage | Every parameter set, full period (min / median / max) |"
    )
    out.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---|")
    rows = sorted(study.items(), key=lambda kv: -kv[1]["oos"].get("net", -1e18))
    for key, v in rows:
        fam, sym = key.split("|")
        o, s = v["oos"], v["oos_stress"]
        full = sorted(x.get("net", 0.0) for x in v["full_period_each_param"])
        if not o.get("trades"):
            continue
        out.append(
            f"| {fam} | {sym} | {o['trades']} | **{r(o['net'])}** | {r(o['net_per_year'])} | "
            f"{100 * o['win_rate']:.0f}% | {o['profit_factor']:.2f} | {r(o['max_dd'])} | "
            f"{r(s.get('net', 0))} | {r(full[0])} / {r(full[len(full) // 2])} / {r(full[-1])} |"
        )
    out.append("\n## Accounts (out-of-sample trades, all rules, 10% of signals missed)\n")
    out.append(
        "| Account | Start | End (6 Nov 2026) | CAGR | ≈ per month | Max drawdown | Trades / month | "
        "Win % | PF | Worst trade | Longest losing run | Median risk / trade |"
    )
    out.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for name, a in acc.items():
        out.append(
            f"| {name} | {r(a['capital'])} | {r(a['final'])} | {100 * a['cagr']:+.1f}% | "
            f"{100 * a['monthly_equiv']:+.2f}% | {100 * a['max_dd']:.0f}% | {a['trades_per_month']:.1f} | "
            f"{100 * a['win_rate']:.0f}% | {a['profit_factor']:.2f} | {r(a['worst_trade'])} | "
            f"{a['max_losing_streak']} | {100 * a['median_risk_pct']:.1f}% |"
        )
    out.append("\n## Monte Carlo (5,000 paths of resampled months; capital multiple)\n")
    out.append(
        "| Account | Horizon | Conservative (25th pct) | Base (median) | Optimistic (75th pct) | "
        "P(loss) | P(target) | P(−25% at some point) | P(−50%) | P(−90%) |"
    )
    out.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for name, a in acc.items():
        for h in ("1y", "2y", "3y", "5y"):
            m = a["monte_carlo"][h]
            out.append(
                f"| {name} | {h} | ×{m['p25']:.2f} | ×{m['median']:.2f} | ×{m['p75']:.2f} | "
                f"{100 * m['prob_loss']:.0f}% | {100 * m['prob_target']:.0f}% | "
                f"{100 * m['prob_dd25']:.0f}% | {100 * m['prob_dd50']:.0f}% | {100 * m['prob_dd90']:.0f}% |"
            )
    out.append("\n## Risk per trade needed to chase the targets\n")
    out.append(
        "| Candidate | Risk per trade | Historical CAGR | Historical max DD | 1-yr median | "
        "P(loss in a year) | P(hit target in a year) | P(−50%) | P(−90%) |"
    )
    out.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for name, v in lev.items():
        for x in v["rows"]:
            out.append(
                f"| {name} | {100 * x['risk_per_trade']:.1f}% | {100 * x['hist_cagr']:+.1f}% | "
                f"{100 * x['hist_max_dd']:.0f}% | {100 * x['mc_median_1y']:+.1f}% | "
                f"{100 * x['p_loss']:.0f}% | {100 * x['p_target']:.0f}% | {100 * x['p_dd50']:.0f}% | "
                f"{100 * x['p_dd90']:.0f}% |"
            )
    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "tables.md").write_text("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
