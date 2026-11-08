"""Regenerate the screen and robustness tables in docs/research/fno_strategy_backtest.md
from the current result files (used after the Bank Nifty calendar correction)."""

from __future__ import annotations

import json
from pathlib import Path

from app.backtesting.data import CACHE

DOC = Path(__file__).resolve().parents[2] / "docs" / "research" / "fno_strategy_backtest.md"


def lk(v: float) -> str:
    return f"{v / 1e5:+.2f}".replace("-", "−")


def inr(v: float) -> str:
    from research.stage2_report import ind

    return ind(v)


def main() -> None:
    screen = json.loads((CACHE / "study_screen.json").read_text())
    deep = json.loads((CACHE / "study_deep.json").read_text())
    lines = doc_lines = DOC.read_text().split("\n")
    order = sorted(
        screen, key=lambda n: -(screen[n]["NIFTY"]["sharpe"] + screen[n]["BANKNIFTY"]["sharpe"])
    )
    screen_rows = []
    for n in order:
        a, b = screen[n]["NIFTY"], screen[n]["BANKNIFTY"]
        screen_rows.append(
            f"| {n} | {lk(a['net_pnl'])} | {a['sharpe']:.2f} | {inr(a['max_drawdown'])} | {lk(b['net_pnl'])} | "
            f"{b['sharpe']:.2f} | {inr(b['max_drawdown'])} | {a['win_rate_pct']:.0f} / {b['win_rate_pct']:.0f} | "
            f"{a['positive_years']}/{a['years']} · {b['positive_years']}/{b['years']} |".replace(
                "| -", "| −"
            )
        )
    deep_rows = []
    for n in deep:
        for idx in ("NIFTY", "BANKNIFTY"):
            r = deep[n][idx]
            g = r["grid"]
            f = lambda k, r=r: lk(r[k].get("net_pnl", 0))  # noqa: E731
            bold = n == "Expiry-day straddle" and idx == "NIFTY"
            cells = [
                n,
                "Nifty" if idx == "NIFTY" else "Bank Nifty",
                lk(r["main"]["net_pnl"]),
                f("design_2020_22"),
                f("holdout_2023_25"),
                f("post_rules_2024_11"),
                f("stress_2x_slip_worst_fill"),
                f("extended_2017_20_vix_model"),
                f("covid_crash_feb_apr_2020"),
                f"{sum(1 for x in g if x['net_pnl'] > 0)}/{len(g)}",
                f"₹{inr(r['bootstrap_dd']['p95'])}",
            ]
            if bold:
                cells = [f"**{c}**" for c in cells]
            elif n == "920 short straddle":
                cells[6] = f"**{cells[6]}**"  # fails the execution stress
            elif n == "Supertrend futures" and idx == "NIFTY":
                cells[4] = f"**{cells[4]}**"  # loses in the 2023–25 holdout
            elif n == "Weekly iron condor":
                cells[9] = f"**{cells[9]}**"  # no profitable setting
            deep_rows.append("| " + " | ".join(cells) + " |")

    def replace_table(header_prefix: str, rows: list[str]) -> None:
        i = next(k for k, ln in enumerate(lines) if ln.startswith(header_prefix))
        j = i + 2
        while j < len(lines) and lines[j].startswith("|"):
            j += 1
        lines[i + 2 : j] = rows

    replace_table("| Strategy | Nifty net (₹ lakh) |", screen_rows)
    replace_table("| Strategy | Index | Full | 2020–22 |", deep_rows)
    DOC.write_text("\n".join(doc_lines))
    print("tables updated")


if __name__ == "__main__":
    main()
