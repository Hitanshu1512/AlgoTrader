"""Tables + charts for the sampled-month backtest. Usage: uv run python -m research.sampled_report"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from app.backtesting.data import CACHE
from research.report import AXIS, GRID, INK, INK2, MUTED, S1, S2, SURFACE, style

DOCS = Path(__file__).resolve().parents[2] / "docs" / "research"
IMG = DOCS / "img"
OUTDIR = DOCS / "sampled_months"
IDX = {"NIFTY": "Nifty 50", "BANKNIFTY": "Bank Nifty"}
DESIGN_MONTHS = {"2020-05", "2021-10", "2022-05"}  # inside 2020–22 parameter-selection window
# Diverging pair (reference palette): blue ↔ red, neutral grey midpoint.
DIV = ["#b2242a", "#e34948", "#f3a6a0", "#f0efec", "#9ec5f4", "#3987e5", "#184f95"]


def inr(v: float | None, signed: bool = True) -> str:
    if v is None:
        return "—"
    s = f"{abs(v):,.0f}"
    return ("−₹" if v < 0 else ("+₹" if signed and v > 0 else "₹")) + s


def pct(v: float | None) -> str:
    return "—" if v is None else f"{v:+.1f}%"


def num(v: float | None, d: int = 2) -> str:
    if v is None:
        return "—"
    return "∞" if v == float("inf") else f"{v:.{d}f}"


def main() -> None:
    d = json.loads((CACHE / "study_sampled.json").read_text())
    months = [f"{y}-{int(m):02d}" for y, m in d["months"].items()]
    res = d["results"]
    names = list(res)
    lines: list[str] = []
    add = lines.append

    add("### Summary with ₹30,000 per account (capital-constrained)\n")
    for idx in ("NIFTY", "BANKNIFTY"):
        add(f"**{IDX[idx]}**\n")
        add(
            "| Strategy | Initial | Final | Signals | Executed | Skipped (margin) | Won / lost | Win rate | Gross P&L | Costs | Net P&L | Net return | Max DD | Profit factor | Avg win | Avg loss |"
        )
        add("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for n in names:
            r = res[n][idx]
            add(
                f"| {n} | ₹30,000 | ₹{r['final_capital']:,.0f} | {r['signals']} | {r['executed']} | {r['skipped']} | "
                f"{r['wins']} / {r['losses']} | {pct(r['win_rate_pct']).lstrip('+') if r['win_rate_pct'] is not None else '—'} | "
                f"{inr(r['gross_pnl'])} | ₹{r['costs']:,.0f} | {inr(r['net_pnl'])} | {pct(r['net_return_pct'])} | "
                f"{r['max_drawdown_pct']:.1f}% | {num(r['profit_factor'])} | {inr(r['avg_win'])} | {inr(r['avg_loss'])} |"
            )
        add("")

    add("### Month-wise (= year-wise: one sampled month per year), ₹30,000 accounts\n")
    add(
        "Cells show net P&L (executed / skipped trades). Skipped = margin per lot exceeded 90% of equity.\n"
    )
    for idx in ("NIFTY", "BANKNIFTY"):
        add(f"**{IDX[idx]}**\n")
        add("| Strategy | " + " | ".join(months) + " |")
        add("|---|" + "---:|" * len(months))
        for n in names:
            bm = res[n][idx]["by_month"]
            cells = [
                f"{inr(bm[m]['net']) if bm[m]['executed'] else '₹0'} ({bm[m]['executed']}/{bm[m]['skipped']})"
                for m in months
            ]
            add(f"| {n} | " + " | ".join(cells) + " |")
        add("")

    add("### Margin needed per lot vs ₹30,000\n")
    add(
        "Smallest margin per lot (₹) required by any signal in the month; ✅ = at least one trade fit within ₹27,000 (90% of ₹30,000).\n"
    )
    for idx in ("NIFTY", "BANKNIFTY"):
        add(f"**{IDX[idx]}**\n")
        add("| Strategy | " + " | ".join(months) + " |")
        add("|---|" + "---:|" * len(months))
        for n in names:
            bm = res[n][idx]["by_month"]
            cells = []
            for m in months:
                b = bm[m]
                cells.append(
                    "✅"
                    if b["executed"]
                    else (f"₹{b['min_margin_needed']:,.0f}" if b["min_margin_needed"] else "—")
                )
            add(f"| {n} | " + " | ".join(cells) + " |")
        add("")

    add("### Sensitivity of executability to the margin model\n")
    add(
        "| Strategy | Index | Executed (base) | Executed (margins −20%, 100% utilisation) | Final capital (lenient) | Executed (margins +20%) |"
    )
    add("|---|---|---:|---:|---:|---:|")
    for n in names:
        for idx in ("NIFTY", "BANKNIFTY"):
            r = res[n][idx]
            lo = r["sensitivity"]["margins_minus_20pct_util_100pct"]
            hi = r["sensitivity"]["margins_plus_20pct"]
            add(
                f"| {n} | {IDX[idx]} | {r['executed']}/{r['signals']} | {lo['executed']} | ₹{lo['final_capital']:,.0f} | {hi['executed']} |"
            )
    add("")

    add(
        "### Capital-adequate reference (every signal at 1 lot; each month's account sized to that month's margin need)\n"
    )
    add(
        "| Strategy | Index | Positive months | Compounded return (7 months) | Worst month | Monthly Sharpe (ann.) | Max DD (monthly) | Profit factor | Win rate | 1-lot net P&L | Costs | Capital needed per lot (2025–26 months) |"
    )
    add("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    rows = []
    for n in names:
        for idx in ("NIFTY", "BANKNIFTY"):
            u = res[n][idx]["unconstrained_1_lot"]
            rows.append((n, idx, u))
            add(
                f"| {n} | {IDX[idx]} | {u['positive_months']}/7 | {pct(u['compounded_return_pct'])} | {pct(u['worst_month_pct'])} | "
                f"{u['monthly_sharpe']:.2f} | {u['max_dd_pct_monthly']:.1f}% | {num(u['profit_factor'])} | {u['win_rate_pct']:.0f}% | "
                f"{inr(u['net_pnl'])} | ₹{u['costs']:,.0f} | ₹{u['capital_needed_current_regime']:,.0f} |"
            )
    add("")

    # Ranking (capital-adequate): average of ranks on 4 criteria
    crit = {
        "risk_adjusted": lambda u: u["monthly_sharpe"],
        "consistency": lambda u: u["positive_months"],
        "profitability": lambda u: u["compounded_return_pct"],
        "drawdown": lambda u: -u["max_dd_pct_monthly"],
    }
    ranks = {}
    for k, f in crit.items():
        order = sorted(rows, key=lambda r: -f(r[2]))
        for n, idx, u in order:
            # average rank for ties
            same = [j for j, rr in enumerate(order) if f(rr[2]) == f(u)]
            ranks.setdefault((n, idx), {})[k] = float(np.mean(same)) + 1
    comp = sorted(rows, key=lambda r: np.mean(list(ranks[(r[0], r[1])].values())))
    add("### Consolidated ranking (capital-adequate view)\n")
    add("Average of the four ranks (1 = best of 14). ₹30k column: trades executed with ₹30,000.\n")
    add(
        "| Rank | Strategy | Index | Risk-adjusted (Sharpe) | Consistency (+months) | Profitability (return) | Drawdown | Composite | Executable with ₹30k |"
    )
    add("|---:|---|---|---:|---:|---:|---:|---:|---:|")
    for i, (n, idx, _u) in enumerate(comp, 1):
        rk = ranks[(n, idx)]
        r30 = res[n][idx]
        add(
            f"| {i} | {n} | {IDX[idx]} | {rk['risk_adjusted']:.1f} | {rk['consistency']:.1f} | {rk['profitability']:.1f} | "
            f"{rk['drawdown']:.1f} | **{np.mean(list(rk.values())):.2f}** | {r30['executed']}/{r30['signals']} |"
        )
    add("")

    # Out-of-sample months only for the expiry-day hedged straddle
    add("### Expiry-day hedged straddle: months outside its 2020–22 parameter-selection window\n")
    add("| Index | Month | Trades | Net P&L (1 lot) | Return on month's capital need |")
    add("|---|---|---:|---:|---:|")
    for idx in ("NIFTY", "BANKNIFTY"):
        mo = res["Expiry-day hedged straddle"][idx]["unconstrained_1_lot"]["monthly"]
        for m in months:
            if m in DESIGN_MONTHS:
                continue
            v = mo[m]
            add(f"| {IDX[idx]} | {m} | {v['trades']} | {inr(v['net'])} | {pct(v['return_pct'])} |")
    add("")

    OUTDIR.mkdir(parents=True, exist_ok=True)
    (OUTDIR / "tables.md").write_text("\n".join(lines))
    # Trade-level CSVs (₹30k accounts)
    with (OUTDIR / "executed_trades_30k.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(
            [
                "strategy",
                "index",
                "entry",
                "exit",
                "lots",
                "lot_size",
                "margin_per_lot",
                "gross",
                "costs",
                "net",
                "equity_after",
                "exit_reason",
            ]
        )
        for n in names:
            for idx in ("NIFTY", "BANKNIFTY"):
                for e in res[n][idx]["executed_trades"]:
                    w.writerow(
                        [
                            n,
                            idx,
                            e["entry"],
                            e["exit"],
                            e["lots"],
                            e["lot_size"],
                            e["margin_per_lot"],
                            round(e["gross"], 2),
                            round(e["costs"], 2),
                            round(e["net"], 2),
                            round(e["equity_after"], 2),
                            e["reason"],
                        ]
                    )
    with (OUTDIR / "skipped_signals_30k.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["strategy", "index", "day", "margin_per_lot", "equity", "lot_size"])
        for n in names:
            for idx in ("NIFTY", "BANKNIFTY"):
                for s in res[n][idx]["skipped_trades"]:
                    w.writerow([n, idx, s["day"], s["margin_per_lot"], s["equity"], s["lot_size"]])

    # Chart 1: share of signals executable with ₹30k
    f, ax = plt.subplots(figsize=(8.5, 4.6), dpi=160)
    f.patch.set_facecolor(SURFACE)
    style(ax)
    y = np.arange(len(names))
    for off, idx, col in ((-0.19, "NIFTY", S1), (0.19, "BANKNIFTY", S2)):
        v = [100 * res[n][idx]["executed"] / max(res[n][idx]["signals"], 1) for n in names]
        ax.barh(y + off, v, height=0.36, color=col, label=IDX[idx], edgecolor=SURFACE)
        for yi, vi in zip(y + off, v, strict=True):
            ax.text(vi + 0.8, yi, f"{vi:.0f}%", va="center", fontsize=8, color=INK2)
    ax.set_yticks(y, names, color=INK)
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel(
        "Share of strategy signals that could be margined with ₹30,000 (7 sampled months)",
        color=INK2,
        fontsize=9,
    )
    ax.legend(frameon=False, fontsize=9, loc="lower right", labelcolor=INK)
    ax.set_title("Executable with ₹30,000?", loc="left", color=INK, fontsize=12)
    f.tight_layout()
    f.savefig(IMG / "sampled_executable_share.png", facecolor=SURFACE)
    plt.close(f)

    # Chart 2: capital-adequate monthly returns heatmap (diverging)
    labels = [f"{n} · {'N' if idx == 'NIFTY' else 'BN'}" for n, idx, _ in rows]
    m = np.array([[u["monthly"][mm]["return_pct"] for mm in months] for _, _, u in rows])
    f, ax = plt.subplots(figsize=(9.5, 6.4), dpi=160)
    f.patch.set_facecolor(SURFACE)
    style(ax)
    ax.grid(False)
    cmap = matplotlib.colors.LinearSegmentedColormap.from_list("div", DIV)
    lim = 30
    ax.imshow(np.clip(m, -lim, lim), cmap=cmap, vmin=-lim, vmax=lim, aspect="auto")
    for i in range(m.shape[0]):
        for j in range(m.shape[1]):
            v = m[i, j]
            ax.text(
                j,
                i,
                f"{v:+.1f}",
                ha="center",
                va="center",
                fontsize=7.5,
                color="#ffffff" if abs(v) > 18 else INK,
            )
    ax.set_xticks(range(len(months)), months, color=INK2)
    ax.set_yticks(range(len(labels)), labels, color=INK, fontsize=8.5)
    ax.set_title(
        "Monthly return (%) on that month's required capital, 1 lot per signal",
        loc="left",
        color=INK,
        fontsize=11,
    )
    f.text(
        0.01,
        0.01,
        "Blue = profit, red = loss, grey ≈ 0. Values clipped at ±30% for colour only.",
        color=MUTED,
        fontsize=8,
    )
    f.tight_layout(rect=(0, 0.03, 1, 1))
    f.savefig(IMG / "sampled_monthly_heatmap.png", facecolor=SURFACE)
    plt.close(f)
    _ = (AXIS, GRID)
    print("\n".join(lines))


if __name__ == "__main__":
    main()
