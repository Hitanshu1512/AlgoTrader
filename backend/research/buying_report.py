"""Tables and charts for docs/research/option_buying_backtest.md.

Usage: uv run python -m research.buying_report  (after run_buying_study and buying_account)
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from app.backtesting.data import CACHE
from research.stage2_report import ind

DOCS = Path(__file__).resolve().parents[2] / "docs" / "research"
IMG = DOCS / "img"


def rupees(x: float) -> str:
    s = ind(abs(x))
    return f"−₹{s}" if x < 0 else f"₹{s}"


def main() -> None:
    study = json.loads((CACHE / "study_buying.json").read_text())
    acct = json.loads((CACHE / "buying_account.json").read_text())
    lines: list[str] = []

    lines.append("### Screen table\n")
    lines.append(
        "| Strategy | Index | Trades / yr | Premium per lot (avg) | Net P&L per lot | "
        "Before charges | Charges | Win % | Profit factor | Profitable years | "
        "2× slippage + worst fills |"
    )
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    rows = []
    for name, by_ix in study.items():
        for ix, v in by_ix.items():
            m = v["main"]
            rows.append((m["net_pnl"], name, ix, m, v["stress"]))
    for _net, name, ix, m, st in sorted(rows, key=lambda r: -r[0]):
        lines.append(
            f"| {name} | {'Nifty' if ix == 'NIFTY' else 'Bank Nifty'} | {m['trades_per_year']:.0f} | "
            f"{rupees(m['avg_premium_paid'])} | **{rupees(m['net_pnl'])}** | {rupees(m['gross_pnl'])} | "
            f"{rupees(m['costs'])} | {m['win_rate_pct']:.0f}% | {m['profit_factor']:.2f} | "
            f"{m['positive_years']}/{m['years']} | {rupees(st['net_pnl'])} |"
        )

    lines.append("\n### Windows\n")
    lines.append("| Strategy | Index | 2020–22 | 2023–25 | Since 21 Nov 2024 |")
    lines.append("|---|---|---:|---:|---:|")
    for _net, name, ix, _m, _st in sorted(rows, key=lambda r: -r[0])[:10]:
        w = study[name][ix]["windows"]
        cells = [
            f"{rupees(w[k]['net_pnl'])} ({w[k]['trades']})" if w[k].get("trades") else "–"
            for k in ("2020_22", "2023_25", "post_2024_11")
        ]
        lines.append(
            f"| {name} | {'Nifty' if ix == 'NIFTY' else 'Bank Nifty'} | " + " | ".join(cells) + " |"
        )

    lines.append("\n### Accounts\n")
    lines.append(
        "| Strategy | Start | Sizing | End balance | Return | Worst fall from peak | Trades | "
        "2026 (unseen) per lot |"
    )
    lines.append("|---|---:|---|---:|---:|---:|---:|---:|")
    for spec, v in acct.items():
        pl = v["per_lot"]
        for r in v["accounts"]:
            lines.append(
                f"| {spec.replace(':', ' · ')} | {rupees(r['capital'])} | {r['mode']} | "
                f"**{rupees(r['final'])}** | {r['return_pct']:+.0f}% | {r['max_drawdown_pct']:.0f}% | "
                f"{r['trades_taken']} | {rupees(pl['oos_2026_net_1lot'])} ({pl['oos_2026_trades']} trades) |"
            )
    (DOCS / "option_buying" / "tables.md").parent.mkdir(exist_ok=True)
    (DOCS / "option_buying" / "tables.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))

    # Chart 1: net per lot, all strategies.
    df = pd.DataFrame(
        [
            {"label": f"{n} · {'N' if ix == 'NIFTY' else 'BN'}", "net": m["net_pnl"] / 1e5}
            for _x, n, ix, m, _s in rows
        ]
    ).sort_values("net")
    fig, ax = plt.subplots(figsize=(9, 8))
    colors = ["#2F7A4D" if x > 0 else "#B03A2E" for x in df["net"]]
    ax.barh(df["label"], df["net"], color=colors)
    ax.axvline(0, color="#1B2333", lw=0.8)
    ax.set_xlabel("Net P&L per lot, May 2020 – Dec 2025 (₹ lakh, after all charges)")
    ax.set_title("Famous option-buying strategies: almost all lose after costs")
    ax.grid(axis="x", alpha=0.3)
    fig.tight_layout()
    fig.savefig(IMG / "buying_screen.png", dpi=130)
    plt.close(fig)

    # Chart 2: ₹25,000 accounts (1 lot and compounding) for the two picks.
    fig, ax = plt.subplots(figsize=(9, 4.5))
    for spec, color in (
        ("Expiry hero-zero (spread):BANKNIFTY", "#2F7A4D"),
        ("Expiry hero-zero:NIFTY", "#C8611E"),
        ("Supertrend 10,3:NIFTY", "#B03A2E"),
    ):
        if spec not in acct:
            continue
        for r in acct[spec]["accounts"]:
            if r["capital"] != 25_000:
                continue
            c = pd.DataFrame(r["curve"], columns=["d", "eq"])
            c["d"] = pd.to_datetime(c["d"])
            ax.plot(
                c["d"],
                c["eq"] / 1e3,
                color=color,
                ls="-" if r["mode"] == "1 lot" else "--",
                label=f"{spec.split(':')[0]} · {spec.split(':')[1].title()} · {r['mode']}",
            )
    ax.axhline(25, color="#1B2333", lw=0.8)
    ax.set_yscale("log")
    ax.set_ylabel("Account balance (₹ thousand, log scale)")
    ax.set_title("₹25,000 accounts, actual lot sizes and charges, May 2020 – 2026")
    ax.legend(fontsize=7)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(IMG / "buying_accounts.png", dpi=130)
    plt.close(fig)


if __name__ == "__main__":
    main()
