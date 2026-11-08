"""Tables + charts for the stage-2 ₹1 lakh backtest. Usage: uv run python -m research.stage2_report"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from app.backtesting.data import CACHE
from research.report import INK, INK2, MUTED, SURFACE, style

DOCS = Path(__file__).resolve().parents[2] / "docs" / "research"
IMG = DOCS / "img"
OUT = DOCS / "stage2"
MODES = {
    "mechanical_original": "Mechanical (original rules)",
    "mechanical_defined": "Mechanical (defined-risk)",
    "disciplined": "Disciplined (risk + behaviour rules)",
}
COLORS = {
    "mechanical_original": "#2a78d6",
    "mechanical_defined": "#eb6834",
    "disciplined": "#1baf7a",
}


def ind(v: float) -> str:
    """Indian digit grouping: 1,23,456."""
    s = f"{round(abs(v))}"
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join(groups) + "," + tail


def rs(v: float | None, sign: bool = False) -> str:
    if v is None:
        return "—"
    if v == float("inf"):
        return "∞"
    s = f"₹{ind(v)}"
    if v < 0:
        return "−" + s
    return ("+" + s) if sign and v > 0 else s


def pc(v: float | None, sign: bool = False) -> str:
    if v is None:
        return "—"
    return f"{v:+.2f}%" if sign else f"{v:.1f}%"


def num(v: float | None) -> str:
    if v is None:
        return "—"
    return "∞" if v == float("inf") else f"{v:.2f}"


def strategy_tables(name: str, s: dict[str, Any], months: list[str]) -> list[str]:
    L: list[str] = []
    modes = [m for m in MODES if not (m == "mechanical_defined" and name.startswith("S1"))]
    hdr = "| Performance metric | " + " | ".join(MODES[m] for m in modes) + " |"
    L += [hdr, "|---|" + "---:|" * len(modes)]

    def row(label: str, f: Any) -> None:
        L.append(f"| {label} | " + " | ".join(f(s[m]) for m in modes) + " |")

    row("Initial capital", lambda m: rs(m["initial"]))
    row("**Final capital**", lambda m: f"**{rs(m['final'])}**")
    row("Net profit / loss", lambda m: rs(m["net"], True))
    row("Total return", lambda m: pc(m["return_pct"], True))
    row("Valid signals", lambda m: str(m["signals"]))
    row("Total trades", lambda m: str(m["trades"]))
    row("Winning trades", lambda m: str(m["wins"]))
    row("Losing trades", lambda m: str(m["losses"]))
    row("Win rate", lambda m: pc(m["win_rate"]))
    row("Gross profit (winning trades, after charges)", lambda m: rs(m["gross_profit"]))
    row("Gross loss (losing trades, after charges)", lambda m: rs(m["gross_loss"]))
    row("P&L before charges", lambda m: rs(m["pnl_before_costs"], True))
    row("Transaction costs (brokerage, STT, exchange, GST, SEBI, stamp)", lambda m: rs(m["costs"]))
    row("Slippage / bid-ask (already inside P&L)", lambda m: rs(m["slippage"]))
    row("Maximum drawdown", lambda m: f"{m['max_dd_pct']:.1f}% ({rs(m['max_dd_rs'])})")
    row("Profit factor", lambda m: num(m["profit_factor"]))
    row("Average profit per winning trade", lambda m: rs(m["avg_win"]))
    row("Average loss per losing trade", lambda m: rs(m["avg_loss"]))
    row("Largest winning trade", lambda m: rs(m["largest_win"]))
    row("Largest losing trade", lambda m: rs(m["largest_loss"]))
    row("Maximum consecutive losses", lambda m: str(m["max_consec_losses"]))
    row("Maximum consecutive wins", lambda m: str(m["max_consec_wins"]))
    row("Risk-to-reward (avg win ÷ avg loss)", lambda m: num(m["risk_reward"]))
    row(
        "Capital utilisation (avg margin ÷ equity, per trade)",
        lambda m: pc(m["capital_utilisation_pct"]),
    )
    row("Planned risk per trade (avg, % of equity)", lambda m: pc(m["planned_risk_pct"]))
    row("Trades skipped due to risk / margin / rules", lambda m: str(m["skipped"]))
    row("Drawdown pauses / cooling-off periods", lambda m: f"{m['pauses']} / {m['cooloffs']}")
    row("Longest time under water (sessions)", lambda m: str(m["longest_underwater_sessions"]))
    row("Worst day (% of equity)", lambda m: pc(m["worst_day_pct"], True))
    L.append("")
    L.append("**Why signals were skipped**\n")
    L.append("| Mode | Reasons (count) |")
    L.append("|---|---|")
    for m in modes:
        reasons = ", ".join(f"{k}: {v}" for k, v in s[m]["skip_reasons"].items()) or "none"
        L.append(f"| {MODES[m]} | {reasons} |")
    L.append("")
    L.append("**Month-wise (= year-wise; one sampled month per year)**\n")
    L.append(
        "| Month | "
        + " | ".join(f"{MODES[m]}: trades · net · month return · end balance" for m in modes)
        + " |"
    )
    L.append("|---|" + "---|" * len(modes))
    for mo in months:
        cells = []
        for m in modes:
            b = s[m]["by_month"][mo]
            cells.append(
                f"{b['trades']} · {rs(b['net'], True)} · {pc(b['return_pct'], True)} · "
                f"{rs(b['end'])}"
            )
        L.append(f"| {mo} | " + " | ".join(cells) + " |")
    L.append("")
    L.append("**Winning / losing streaks** (lengths in order of occurrence)\n")
    L.append("| Mode | Winning streaks | Losing streaks |")
    L.append("|---|---|---|")
    for m in modes:
        L.append(f"| {MODES[m]} | {s[m]['win_streaks'] or '—'} | {s[m]['loss_streaks'] or '—'} |")
    L.append("")
    return L


def chart(name: str, slug: str, s: dict[str, Any], months: list[str]) -> None:
    modes = [m for m in MODES if not (m == "mechanical_defined" and name.startswith("S1"))]
    f, (a1, a2) = plt.subplots(
        2, 1, figsize=(9, 5.6), dpi=160, sharex=True, gridspec_kw={"height_ratios": [3, 1.4]}
    )
    f.patch.set_facecolor(SURFACE)
    for a in (a1, a2):
        style(a)
    n = 0
    for m in modes:
        eq = np.array([100_000.0] + [e for _, e in s[m]["equity"]])
        x = np.arange(len(eq))
        n = len(eq)
        lab = MODES[m] + (
            " (= defined-risk; S1 is already hedged)"
            if name.startswith("S1") and m == "mechanical_original"
            else ""
        )
        a1.plot(x, eq / 1e3, color=COLORS[m], linewidth=2, label=lab)
        peak = np.maximum.accumulate(eq)
        a2.plot(x, -100 * (peak - eq) / peak, color=COLORS[m], linewidth=1.5)
    days = [d for d, _ in s[modes[0]]["equity"]]
    starts = [0] + [i + 1 for i in range(1, len(days)) if days[i][:7] != days[i - 1][:7]]
    for a in (a1, a2):
        for st in starts[1:]:
            a.axvline(st, color=MUTED, linewidth=0.6, alpha=0.6)
    a2.set_xticks(
        [st + 3 for st in starts],
        [days[max(st - 1, 0)][:7] for st in starts],
        fontsize=8,
        color=INK2,
    )
    a1.axhline(100, color=MUTED, linewidth=0.8, linestyle="--")
    a1.set_ylabel("Account equity (₹ thousand)", color=INK2, fontsize=9)
    a2.set_ylabel("Drawdown (%)", color=INK2, fontsize=9)
    a1.legend(frameon=False, fontsize=8, labelcolor=INK, loc="best")
    a1.set_title(
        f"{name}: ₹1,00,000 account across the 7 sampled months", loc="left", color=INK, fontsize=11
    )
    a2.set_xlim(0, n)
    f.tight_layout()
    f.savefig(IMG / f"stage2_{slug}_equity.png", facecolor=SURFACE)
    plt.close(f)


def ranking(d: dict[str, Any], mode: str) -> tuple[list[str], list[tuple[str, float]]]:
    rows = []
    for name, s in d["strategies"].items():
        m = s[mode]
        traded_months = [v for v in m["by_month"].values() if v["trades"]]
        pos = sum(1 for v in traded_months if v["net"] > 0)
        crit = {
            "Net profit (₹)": m["net"],
            "Risk-adjusted (daily Sharpe)": m["daily_sharpe"],
            "Max drawdown (lower better)": -m["max_dd_pct"] if m["trades"] else -1e9,
            "Consistency (profitable months)": pos,
            "Profit factor": (
                m["profit_factor"]
                if m["profit_factor"] not in (None, float("inf"))
                else (99.0 if m["profit_factor"] == float("inf") else 0.0)
            ),
            "Capital efficiency (net ÷ avg margin)": m["net"] / m["avg_margin"]
            if m["avg_margin"]
            else 0.0,
            "Practical execution (% signals taken)": 100 * m["trades"] / max(m["signals"], 1),
            "Psychological sustainability": -(
                m["max_consec_losses"]
                + abs(m["worst_day_pct"])
                + m["longest_underwater_sessions"] / 10
            ),
        }
        rows.append((name, m, crit, pos, len(traded_months)))
    keys = list(rows[0][2])
    ranks: dict[str, dict[str, float]] = {r[0]: {} for r in rows}
    for k in keys:
        vals = sorted({r[2][k] for r in rows}, reverse=True)
        for r in rows:
            ranks[r[0]][k] = vals.index(r[2][k]) + 1
    L = ["| Criterion | " + " | ".join(r[0] for r in rows) + " |", "|---|" + "---|" * len(rows)]

    def show(k: str, r: tuple[Any, ...]) -> str:
        m = r[1]
        val = {
            "Net profit (₹)": rs(m["net"], True),
            "Risk-adjusted (daily Sharpe)": f"{m['daily_sharpe']:.2f}",
            "Max drawdown (lower better)": f"{m['max_dd_pct']:.1f}%"
            if m["trades"]
            else "no trades",
            "Consistency (profitable months)": f"{r[3]}/{r[4]} traded months",
            "Profit factor": num(m["profit_factor"]),
            "Capital efficiency (net ÷ avg margin)": (
                f"{m['net'] / m['avg_margin']:.2f}" if m["avg_margin"] else "—"
            ),
            "Practical execution (% signals taken)": f"{100 * m['trades'] / max(m['signals'], 1):.0f}%",
            "Psychological sustainability": (
                f"max {m['max_consec_losses']} losses in a row, worst "
                f"day {m['worst_day_pct']:+.1f}%, "
                f"{m['longest_underwater_sessions']} sessions under water"
            ),
        }[k]
        return f"{val} (#{ranks[r[0]][k]})"

    for k in keys:
        L.append(f"| {k} | " + " | ".join(show(k, r) for r in rows) + " |")
    avg = [(r[0], float(np.mean(list(ranks[r[0]].values())))) for r in rows]
    L.append("| **Average rank** | " + " | ".join(f"**{a:.2f}**" for _, a in avg) + " |")
    return L, sorted(avg, key=lambda x: x[1])


def main() -> None:
    d = json.loads((CACHE / "stage2.json").read_text())
    months = [f"{y}-{int(m):02d}" for y, m in d["months"].items()]
    L: list[str] = []
    L.append("### Headline: ₹1,00,000 → final balance\n")
    L.append("| Strategy | " + " | ".join(MODES.values()) + " |")
    L.append("|---|---:|---:|---:|")
    for name, s in d["strategies"].items():
        cells = []
        for m in MODES:
            x = s[m]
            cells.append(f"{rs(x['final'])} ({rs(x['net'], True)}; {x['trades']} trades)")
        L.append(f"| {name} | " + " | ".join(cells) + " |")
    L.append("")
    for name, s in d["strategies"].items():
        slug = name.split()[0]
        L.append(f"### {name}\n")
        L += strategy_tables(name, s, months)
        chart(name, slug, s, months)
        L.append(f"![{name} equity and drawdown](img/stage2_{slug}_equity.png)\n")
    L.append("### Stress tests (final balance from ₹1,00,000 unless stated)\n")
    keys = [
        ("base", "Base case"),
        ("slippage_plus_25pct", "Slippage +25%"),
        ("charges_plus_50pct", "Transaction charges +50%"),
        ("win_rate_minus_10pp", "Win rate −10 pp (smallest winners become average losers)"),
        ("five_full_losses_first", "Losing streak: 5 full planned-risk losses first"),
        ("worst_order", "Worst ordering of actual trades (all losses first)"),
        ("capital_75k", "Reduced capital: start ₹75,000"),
        ("capital_50k", "Reduced capital: start ₹50,000"),
        (
            "gap_1pct_first_signal_each_month",
            "Gap ±1% one hour after entry, first signal each month",
        ),
        (
            "gap_2pct_first_signal_each_month",
            "Gap ±2% one hour after entry, first signal each month",
        ),
    ]
    names = list(d["strategies"])
    L.append(
        "| Scenario | "
        + " | ".join(f"{n.split()[0]} mechanical | {n.split()[0]} disciplined" for n in names)
        + " |"
    )
    L.append("|---|" + "---:|" * (2 * len(names)))
    for k, label in keys:
        cells = []
        for n in names:
            for mode in ("mechanical_original", "disciplined"):
                st = d["strategies"][n]["stress"][mode]
                if k not in st:
                    cells.append("n/a (no trades)")
                    continue
                v = st[k]
                start = v[1] if k.startswith("capital_") else 100_000.0
                final = v[0]
                mark = "✅" if final > start + 1 else ("➖" if abs(final - start) <= 1 else "❌")
                dd = "" if k.startswith("capital_") else f", DD {v[1]:.1f}%"
                cells.append(f"{rs(final)} {mark}{dd}")
        L.append(f"| {label} | " + " | ".join(cells) + " |")
    L.append("")
    L.append("✅ profitable · ➖ no trades/unchanged · ❌ loss versus the starting balance.\n")
    L.append("### What-ifs outside the stated rules (context only, not ranked)\n")
    L.append("| Strategy | 2% risk per trade, ₹1 lakh | 1% risk per trade, ₹4 lakh |")
    L.append("|---|---|---|")
    for n, s in d["strategies"].items():
        w = s["whatif_outside_rules"]
        a, b = w["risk_2pct_capital_1L"], w["risk_1pct_capital_4L"]
        L.append(
            f"| {n} | {rs(a['final'])} ({rs(a['net'], True)}, {a['trades']} trades, max DD "
            f"{a['max_dd_pct']:.1f}%) | {rs(b['final'])} ({rs(b['net'], True)}, {b['trades']} "
            f"trades, max DD {b['max_dd_pct']:.1f}%) |"
        )
    L.append("")
    L.append("### Capital needed to follow the 1% rule at 2025–26 contract sizes\n")
    L.append(
        "| Strategy | Median planned risk per lot | Median margin per lot | Capital needed (risk ÷ 1%, margin ÷ 60%) |"
    )
    L.append("|---|---:|---:|---:|")
    for n, s in d["strategies"].items():
        c = s["capital_for_1pct_rule_2025_26"]
        L.append(
            f"| {n} | {rs(c['median_risk_per_lot'])} | {rs(c['median_margin_per_lot'])} | "
            f"**{rs(c['capital_needed'])}** |"
        )
    L.append("")
    L.append("| Strategy | " + " | ".join(months) + " |")
    L.append("|---|" + "---:|" * len(months))
    for n, s in d["strategies"].items():
        L.append(
            f"| {n}: median planned risk per lot | "
            + " | ".join(rs(s["risk_per_lot_by_month"][mo]) for mo in months)
            + " |"
        )
    L.append("")
    L.append("### Disciplined execution with ₹1 lakh: status (not rankable)\n")
    L.append("| Strategy | Signals | Trades taken | Final balance | Status |")
    L.append("|---|---:|---:|---:|---|")
    for n, s in d["strategies"].items():
        m = s["disciplined"]
        status = (
            "**Not executable**: one lot's planned stop-loss risk exceeded 1% of equity "
            "on every signal"
            if m["trades"] == 0
            else ("Executable, **loss-making**" if m["net"] < 0 else "Executable, profitable")
        )
        L.append(
            f"| {n} | {m['signals']} | {m['trades']} | {rs(m['final'])} "
            f"({rs(m['net'], True)}) | {status} |"
        )
    L.append("")
    L.append("### Consolidated ranking: Mechanical (defined-risk), 1 lot per signal\n")
    tbl, order = ranking(d, "mechanical_defined")
    L += tbl
    L.append("")
    L.append(
        "Order: "
        + " → ".join(f"{n} ({a:.2f})" for n, a in order)
        + ". Ties are broken by criterion 1 (net profit).\n"
    )
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "tables.md").write_text("\n".join(L))
    print("\n".join(L))


if __name__ == "__main__":
    main()
