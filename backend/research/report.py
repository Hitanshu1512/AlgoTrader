"""Final-strategy metrics + report charts. Usage: uv run python -m research.report"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from app.backtesting.charges import Slippage
from app.backtesting.data import CACHE
from app.backtesting.metrics import daily_pnl, summarize
from app.backtesting.strategies import fno
from research.run_deep import DESIGN, HOLDOUT, POST_RULES, bootstrap_dd, compact, window
from research.run_fno_study import EXTENDED, MAIN, build_ctx

IMG = Path(__file__).resolve().parents[2] / "docs" / "research" / "img"
FINAL = {
    "sl": 0.5,
    "expiry_only": True,
    "entry_bar": 105,
    "hedge_delta": 0.01,
    "name": "Final: Nifty expiry-day hedged straddle",
}
DEFAULT = {
    "sl": 0.3,
    "expiry_only": True,
    "entry_bar": 5,
    "name": "Expiry-day straddle (9:20, 30%)",
}

# Reference palette (light surface)
SURFACE, INK, INK2, MUTED, GRID, AXIS = (
    "#fcfcfb",
    "#0b0b0b",
    "#52514e",
    "#898781",
    "#e1e0d9",
    "#c3c2b7",
)
S1, S2 = "#2a78d6", "#eb6834"
SEQ = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]


def style(ax: plt.Axes) -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(AXIS)
    ax.tick_params(colors=INK2, labelsize=9)
    ax.grid(color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def fig(w: float, h: float) -> tuple[plt.Figure, plt.Axes]:
    f, ax = plt.subplots(figsize=(w, h), dpi=160)
    f.patch.set_facecolor(SURFACE)
    style(ax)
    return f, ax


def chart_screen() -> None:
    d = json.loads((CACHE / "study_screen.json").read_text())
    names = sorted(d, key=lambda n: d[n]["NIFTY"]["net_pnl"] + d[n]["BANKNIFTY"]["net_pnl"])
    y = np.arange(len(names))
    f, ax = fig(8.5, 5.2)
    for off, idx, col, lab in (
        (0.19, "NIFTY", S1, "Nifty 50"),
        (-0.19, "BANKNIFTY", S2, "Bank Nifty"),
    ):
        v = [max(d[n][idx]["net_pnl"] / 1e5, -10) for n in names]
        ax.barh(y + off, v, height=0.36, color=col, label=lab, edgecolor=SURFACE, linewidth=1)
    ax.axvline(0, color=AXIS, linewidth=1)
    ax.set_yticks(y, names, color=INK)
    ax.set_xlabel(
        "Net P&L per lot after all charges, May 2020 – Dec 2025 (₹ lakh; clipped at −10)",
        color=INK2,
        fontsize=9,
    )
    ax.grid(axis="y", visible=False)
    ax.legend(frameon=False, loc="lower right", fontsize=9, labelcolor=INK)
    ax.set_title("Screen: 10 popular index F&O strategies", loc="left", color=INK, fontsize=12)
    f.tight_layout()
    f.savefig(IMG / "screen_net_pnl.png", facecolor=SURFACE)
    plt.close(f)


def chart_final(sessions: list[date], eq_final: np.ndarray, eq_default: np.ndarray) -> None:
    f, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(8.5, 5.6), dpi=160, sharex=True, gridspec_kw={"height_ratios": [3, 1.3]}
    )
    f.patch.set_facecolor(SURFACE)
    for ax in (ax1, ax2):
        style(ax)
    x = np.array(sessions, dtype="datetime64[D]")
    ax1.plot(
        x, eq_final / 1e5, color=S1, linewidth=2, label="Final: 11:00 entry, 50% stop, Δ0.01 wings"
    )
    ax1.plot(x, eq_default / 1e5, color=S2, linewidth=2, label="Community default: 9:20, 30% stop")
    ax1.axvspan(np.datetime64(HOLDOUT[0]), x[-1], color=GRID, alpha=0.35, linewidth=0)
    ax1.text(
        np.datetime64(HOLDOUT[0]),
        ax1.get_ylim()[1] * 0.97,
        "  holdout 2023–25 (parameters\n  chosen on 2020–22 only)",
        color=MUTED,
        fontsize=8,
        va="top",
    )
    ax1.set_ylabel("Cumulative net P&L\nper lot (₹ lakh)", color=INK2, fontsize=9)
    ax1.legend(frameon=False, fontsize=9, loc="upper left", labelcolor=INK)
    ax1.set_title(
        "Nifty 50 expiry-day straddle, 1 lot (65), after all charges and slippage",
        loc="left",
        color=INK,
        fontsize=12,
    )
    dd = eq_final - np.maximum.accumulate(np.r_[0.0, eq_final])[1:]
    ax2.fill_between(x, dd / 1e3, 0, color=S1, alpha=0.35, linewidth=0)
    ax2.plot(x, dd / 1e3, color=S1, linewidth=1.2)
    ax2.set_ylabel("Drawdown\n(₹ thousand)", color=INK2, fontsize=9)
    f.tight_layout()
    f.savefig(IMG / "final_equity.png", facecolor=SURFACE)
    plt.close(f)


def chart_heatmap() -> None:
    d = json.loads((CACHE / "study_expiry_grid.json").read_text())["NIFTY"]
    entries = list(dict.fromkeys(r["entry"] for r in d))
    sls = list(dict.fromkeys(r["sl"] for r in d))
    m = np.array(
        [
            [next(r["holdout_sharpe"] for r in d if r["entry"] == e and r["sl"] == s) for s in sls]
            for e in entries
        ]
    )
    f, ax = fig(6.4, 3.8)
    ax.grid(False)
    cmap = matplotlib.colors.LinearSegmentedColormap.from_list("seq", SEQ)
    ax.imshow(m, cmap=cmap, vmin=0, vmax=4.5, aspect="auto")
    for i in range(len(entries)):
        for j in range(len(sls)):
            ax.text(
                j,
                i,
                f"{m[i, j]:.2f}",
                ha="center",
                va="center",
                fontsize=9,
                color="#ffffff" if m[i, j] > 2.6 else INK,
            )
    ax.set_xticks(range(len(sls)), [("none" if s > 5 else f"{s:.0%}") for s in sls])
    ax.set_yticks(range(len(entries)), entries)
    ax.set_xlabel("Per-leg stop-loss", color=INK2, fontsize=9)
    ax.set_ylabel("Entry time (IST)", color=INK2, fontsize=9)
    ax.set_title(
        "Holdout (2023–25) Sharpe by entry time and stop — Nifty",
        loc="left",
        color=INK,
        fontsize=11,
    )
    i, j = entries.index("11:00"), sls.index(0.5)
    ax.add_patch(plt.Rectangle((j - 0.5, i - 0.5), 1, 1, fill=False, edgecolor=S2, linewidth=2.5))
    f.tight_layout()
    f.savefig(IMG / "final_param_heatmap.png", facecolor=SURFACE)
    plt.close(f)


def chart_yearly(by_year: dict[str, float]) -> None:
    f, ax = fig(7.0, 3.2)
    years = [f"{y}\n(May–Dec)" if i == 0 else y for i, y in enumerate(by_year)]
    vals = [v / 1e3 for v in by_year.values()]
    ax.bar(years, vals, color=S1, width=0.6, edgecolor=SURFACE)
    for xi, v in zip(years, vals, strict=True):
        ax.text(xi, v + (1 if v >= 0 else -4), f"₹{v:.0f}k", ha="center", fontsize=8, color=INK2)
    ax.axhline(0, color=AXIS, linewidth=1)
    ax.grid(axis="x", visible=False)
    ax.set_ylabel("Net P&L per lot (₹ thousand)", color=INK2, fontsize=9)
    ax.set_title(
        "Final strategy (Nifty) — net P&L by calendar year", loc="left", color=INK, fontsize=11
    )
    f.tight_layout()
    f.savefig(IMG / "final_by_year.png", facecolor=SURFACE)
    plt.close(f)


def main() -> None:
    IMG.mkdir(parents=True, exist_ok=True)
    stress = Slippage(option_pct=0.01, option_min_points=0.2, sl_fill_worst=True)
    out = {}
    for index in ("NIFTY", "BANKNIFTY"):
        base, ext = build_ctx(index, MAIN), build_ctx(index, EXTENDED)
        tr = fno.straddle_920(base, **FINAL)
        res = {
            "main": summarize(tr, base.sessions),
            "bootstrap_dd": bootstrap_dd(daily_pnl(tr, base.sessions)),
        }
        for label, c in (
            ("design_2020_22", window(base, DESIGN)),
            ("holdout_2023_25", window(base, HOLDOUT)),
            ("post_rules_2024_11", window(base, POST_RULES)),
            ("stress_2x_slip_worst_fill", replace(base, slip=stress)),
            ("extended_2017_20_vix_model", ext),
            ("covid_crash_feb_apr_2020", window(ext, (date(2020, 2, 1), date(2020, 4, 30)))),
        ):
            res[label] = compact(summarize(fno.straddle_920(c, **FINAL), c.sessions))
        res["exit_reasons"] = {
            r: sum(1 for t in tr if t.exit_reason == r) for r in {t.exit_reason for t in tr}
        }
        res["costs_per_trade"] = float(np.mean([t.costs for t in tr]))
        out[index] = res
        if index == "NIFTY":
            dflt = fno.straddle_920(base, **DEFAULT)
            chart_final(
                base.sessions,
                np.cumsum(daily_pnl(tr, base.sessions)),
                np.cumsum(daily_pnl(dflt, base.sessions)),
            )
            chart_yearly(res["main"]["by_year"])
        m = res["main"]
        print(
            f"{index}: trades {m['trades']} net ₹{m['net_pnl']:,.0f} annual ₹{m['annual_pnl']:,.0f}"
            f" margin ₹{m['avg_margin']:,.0f} ({m['annual_return_on_margin_pct']:.1f}%/yr)"
            f" maxDD ₹{m['max_drawdown']:,.0f} sharpe {m['sharpe']:.2f} win {m['win_rate_pct']:.0f}%"
            f" PF {m['profit_factor']:.2f} avgW ₹{m['avg_win']:,.0f} avgL ₹{m['avg_loss']:,.0f}"
            f" worst ₹{m['worst_trade']:,.0f} costs/trade ₹{res['costs_per_trade']:,.0f}"
            f" ({m['cost_pct_of_gross']:.0f}% of gross) | by year {m['by_year']}"
        )
        for k in (
            "design_2020_22",
            "holdout_2023_25",
            "post_rules_2024_11",
            "stress_2x_slip_worst_fill",
            "extended_2017_20_vix_model",
            "covid_crash_feb_apr_2020",
        ):
            r = res[k]
            print(
                f"   {k:28s} n={r['trades']:3d} net ₹{r['net_pnl']:>9,.0f} sharpe {r['sharpe']:.2f}"
                f" PF {r['profit_factor']:.2f} maxDD ₹{r['max_drawdown']:,.0f} worst ₹{r['worst_trade']:,.0f}"
            )
        print(
            "   bootstrap DD",
            {k: round(v) for k, v in res["bootstrap_dd"].items()},
            "exits",
            res["exit_reasons"],
        )
    out["NIFTY"]["main"].pop("equity", None)
    out["BANKNIFTY"]["main"].pop("equity", None)
    (CACHE / "study_final.json").write_text(json.dumps(out, default=str))
    chart_screen()
    chart_heatmap()


if __name__ == "__main__":
    main()
