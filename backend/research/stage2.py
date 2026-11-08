"""Stage 2: ₹1,00,000 paper-trading backtest of the three shortlisted strategies.

* Seven NEW random months (one per year 2020–2026, seed SEED_STAGE2, excluding stage-1 months),
  identical for all strategies; every trading day evaluated; balance carried forward.
* Three accounts per strategy:
    mechanical_original  – original rules (S2/S3 naked), 1 lot per signal if margin fits
    mechanical_defined   – same, with the predefined Δ0.01 protective wings (defined risk)
    disciplined          – defined-risk version + risk & behaviour rules (app/backtesting/account)
* Charges at the rates in force on each trade date; slippage on every fill; exact lot sizes.
* Stress tests: slippage +25%, charges +50%, win rate −10 pp, injected losing streak and
  worst ordering, reduced capital (₹75k / ₹50k), ±2% intraday gap one day per month.

Usage: uv run python -m research.stage2
"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

from app.backtesting.account import AccountResult, DisciplineRules, Signal, run_account
from app.backtesting.charges import Slippage, option_order_cost
from app.backtesting.data import BARS_PER_DAY, CACHE, DayBars
from app.backtesting.margin import LegFill, option_margin
from app.backtesting.strategies import fno
from research.sample_months import SEED_STAGE2, draw, draw_stage2, stage2_eligible
from research.sampled_backtest import build

CAPITAL = 100_000.0
OUT = Path(__file__).resolve().parents[2] / "docs" / "research" / "stage2"
WING = 0.01  # predefined disaster-wing delta (same convention as S1; not tuned on stage-2 data)

STRATS: dict[str, dict[str, Any]] = {
    "S1 Expiry-day hedged straddle": {
        "indices": ["NIFTY", "BANKNIFTY"],
        "kind": "straddle",
        "expiry_only": True,
        "kw": {"sl": 0.5, "entry_bar": 105},
        "orig_hedge": WING,
    },
    "S2 Expiry-day straddle (Nifty)": {
        "indices": ["NIFTY"],
        "kind": "straddle",
        "expiry_only": True,
        "kw": {"sl": 0.3, "entry_bar": 5},
        "orig_hedge": None,
    },
    "S3 9:20 short strangle (Nifty)": {
        "indices": ["NIFTY"],
        "kind": "strangle",
        "expiry_only": False,
        "kw": {"delta": 0.2, "sl": 0.3, "entry_bar": 5},
        "orig_hedge": None,
    },
}


def make_signal(setup: fno.Setup, slip: Slippage, cost_mult: float = 1.0) -> Signal:
    """Planned risk = every short leg stopped at its level (+ exit slippage) + wings expire
    worthless + all charges; margin from the corrected SPAN+ELM model."""
    d = setup.day
    fills, loss = [], 0.0
    charges = 0.0
    for leg in setup.legs:
        px = setup.pricer.quote(leg, setup.entry_bar)
        if leg.qty < 0:
            f = max(px - slip.option(px), 0.05)
            stop = f * (1 + (setup.leg_sl_pct or 0.0))
            loss += stop + slip.option(stop) - f
            charges += option_order_cost(f, setup.lot, "SELL", d) + option_order_cost(
                stop, setup.lot, "BUY", d
            )
        else:
            f = px + slip.option(px)
            loss += f
            charges += option_order_cost(f, setup.lot, "BUY", d) + option_order_cost(
                0.05, setup.lot, "SELL", d
            )
        fills.append(LegFill(leg.strike, leg.is_call, leg.qty, f))
    risk = loss * setup.lot + charges * cost_mult
    margin = option_margin(fills, setup.spot, setup.lot, d, setup.expiry)
    return Signal(setup, margin, risk)


def month_days(ctx: fno.Ctx, months: dict[int, int]) -> list[date]:
    return [d for d in sorted(ctx.bars) if (d.year, d.month) in {(y, m) for y, m in months.items()}]


def build_signals(
    ctxs: dict[str, fno.Ctx],
    spec: dict[str, Any],
    months: dict[int, int],
    hedge: float | None,
    slip: Slippage,
    cost_mult: float = 1.0,
) -> tuple[dict[date, list[Signal]], list[date]]:
    sigs: dict[date, list[Signal]] = {}
    sessions = month_days(ctxs["NIFTY"], months)
    for idx in spec["indices"]:  # priority order: Nifty first
        ctx = ctxs[idx]
        for d in month_days(ctx, months):
            if spec["expiry_only"] and not ctx.cal.is_expiry(d):
                continue
            name = f"{spec['kind']} {idx}"
            if spec["kind"] == "straddle":
                s = fno.straddle_setup(ctx, d, hedge_delta=hedge, name=name, **spec["kw"])
            else:
                s = fno.strangle_setup(ctx, d, hedge_delta=hedge, name=name, **spec["kw"])
            sigs.setdefault(d, []).append(make_signal(s, slip, cost_mult))
    return sigs, sessions


def shocked(ctx: fno.Ctx, days: set[date], entry_bar: int, jump: float) -> fno.Ctx:
    """Copy of ctx where, on ``days``, the index jumps by ``jump`` 60 minutes after entry."""
    bars = dict(ctx.bars)
    k = min(entry_bar + 60, BARS_PER_DAY - 20)
    for d in days:
        b = bars[d]
        m = np.ones(BARS_PER_DAY)
        m[k:] = 1 + jump
        o = b.open * m
        o[k] = b.close[k - 1] * (1 + jump)  # instantaneous gap at the bar's open
        c = b.close * m
        bars[d] = DayBars(
            d,
            o,
            np.maximum(b.high * m, np.maximum(o, c)),
            np.minimum(b.low * m, np.minimum(o, c)),
            c,
            b.missing,
        )
    return replace(ctx, bars=bars)


# ───────────────────────────── metrics ─────────────────────────────


def streaks(nets: list[float]) -> tuple[list[int], list[int]]:
    wins, losses, cur, sign = [], [], 0, 0
    for n in nets:
        s = 1 if n > 0 else -1
        if s == sign:
            cur += 1
        else:
            if sign == 1:
                wins.append(cur)
            elif sign == -1:
                losses.append(cur)
            cur, sign = 1, s
    if sign == 1:
        wins.append(cur)
    elif sign == -1:
        losses.append(cur)
    return wins, losses


def metrics(res: AccountResult, months: dict[int, int], n_signals: int) -> dict[str, Any]:
    tr = res.trades
    nets = [t["net"] for t in tr]
    w = [x for x in nets if x > 0]
    lo = [x for x in nets if x <= 0]
    eq = np.array([CAPITAL] + [e for _, e in res.equity_by_session])
    peak = np.maximum.accumulate(eq)
    dd_r = peak - eq
    dd_p = dd_r / peak
    under, longest = 0, 0
    for v in dd_r:
        under = under + 1 if v > 0 else 0
        longest = max(longest, under)
    daily = np.diff(eq) / eq[:-1]
    win_s, loss_s = streaks(nets)
    skips: dict[str, int] = {}
    for j in res.journal:
        if j["action"] == "SKIP":
            key = j["reason"].split(":")[0].split(" (")[0]
            skips[key] = skips.get(key, 0) + 1
    by_month = {}
    eq_by_day = dict(res.equity_by_session)
    prev_end = res.capital
    for y, m in months.items():
        key = f"{y}-{m:02d}"
        mt = [t for t in tr if t["entry"].startswith(key)]
        days = [dd for dd in eq_by_day if dd.year == y and dd.month == m]
        end = eq_by_day[max(days)] if days else prev_end
        by_month[key] = {
            "trades": len(mt),
            "wins": sum(1 for t in mt if t["net"] > 0),
            "net": float(sum(t["net"] for t in mt)),
            "costs": float(sum(t["costs"] for t in mt)),
            "start": prev_end,
            "end": end,
            "return_pct": 100 * (end / prev_end - 1) if prev_end else 0.0,
            "skipped": sum(
                1 for j in res.journal if j["action"] == "SKIP" and j["date"].startswith(key)
            ),
        }
        prev_end = end
    worst_day = float((np.min(daily) * 100) if len(daily) else 0.0)
    return {
        "initial": res.capital,
        "final": res.final,
        "net": res.final - res.capital,
        "return_pct": 100 * (res.final / res.capital - 1),
        "signals": n_signals,
        "trades": len(tr),
        "wins": len(w),
        "losses": len(lo),
        "win_rate": 100 * len(w) / len(tr) if tr else None,
        "gross_profit": float(sum(w)),
        "gross_loss": float(sum(lo)),
        "pnl_before_costs": float(sum(t["gross_before_costs"] for t in tr)),
        "costs": float(sum(t["costs"] for t in tr)),
        "slippage": float(sum(t["slippage"] for t in tr)),
        "max_dd_pct": float(dd_p.max() * 100),
        "max_dd_rs": float(dd_r.max()),
        "profit_factor": (
            float(sum(w) / -sum(lo)) if lo and sum(lo) < 0 else (float("inf") if w else None)
        ),
        "avg_win": float(np.mean(w)) if w else None,
        "avg_loss": float(np.mean(lo)) if lo else None,
        "largest_win": float(max(w)) if w else None,
        "largest_loss": float(min(lo)) if lo else None,
        "max_consec_losses": max(loss_s, default=0),
        "max_consec_wins": max(win_s, default=0),
        "win_streaks": win_s,
        "loss_streaks": loss_s,
        "risk_reward": (float(np.mean(w) / -np.mean(lo)) if w and lo else None),
        "capital_utilisation_pct": float(
            np.mean([t["margin"] / t["equity_before"] for t in tr]) * 100
        )
        if tr
        else 0.0,
        "planned_risk_pct": float(
            np.mean([t["planned_risk"] / t["equity_before"] for t in tr]) * 100
        )
        if tr
        else 0.0,
        "avg_margin": float(np.mean([t["margin"] for t in tr])) if tr else 0.0,
        "skipped": sum(skips.values()),
        "skip_reasons": skips,
        "pauses": res.pauses,
        "cooloffs": res.cooloffs,
        "longest_underwater_sessions": longest,
        "worst_day_pct": worst_day,
        "daily_sharpe": float(np.mean(daily) / np.std(daily) * np.sqrt(252))
        if len(daily) and np.std(daily) > 0
        else 0.0,
        "by_month": by_month,
        "equity": [(d.isoformat(), e) for d, e in res.equity_by_session],
    }


# ───────────────────────────── stresses on outcome sequences ─────────────────────────────


def recompound(rs: list[float], capital: float = CAPITAL) -> tuple[float, float]:
    eq, peak, dd = capital, capital, 0.0
    for r in rs:
        eq *= 1 + r
        peak = max(peak, eq)
        dd = max(dd, (peak - eq) / peak)
    return eq, 100 * dd


def outcome_stresses(res: AccountResult) -> dict[str, Any]:
    rs = [t["net"] / t["equity_before"] for t in res.trades]
    if not rs:
        return {}
    out: dict[str, Any] = {}
    # Lower win rate: the smallest winners (10% of all trades) become average losers.
    k = math.ceil(0.10 * len(rs))
    losers = [r for r in rs if r <= 0]
    avg_loss = (
        float(np.mean(losers))
        if losers
        else -float(np.mean([t["planned_risk"] / t["equity_before"] for t in res.trades]))
    )
    order = sorted((r, i) for i, r in enumerate(rs) if r > 0)[:k]
    lw = list(rs)
    for _, i in order:
        lw[i] = avg_loss
    out["win_rate_minus_10pp"] = recompound(lw)
    # Losing streak: five consecutive full planned-risk losses before the first trade.
    pr = float(np.median([t["planned_risk"] / t["equity_before"] for t in res.trades]))
    out["five_full_losses_first"] = recompound([-pr] * 5 + rs)
    # Worst ordering of the actual outcomes (all losers first).
    out["worst_order"] = recompound(sorted(rs))
    return out


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("")
        return
    keys: list[str] = []
    for r in rows:
        keys += [k for k in r if k not in keys]
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    months = draw_stage2()
    base_slip = Slippage(historical_rates=True)
    ctxs = {i: build(i, base_slip)[0] for i in ("NIFTY", "BANKNIFTY")}
    OUT.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "seed": SEED_STAGE2,
        "months": months,
        "stage1_months": draw(),
        "eligible": {str(k): v for k, v in stage2_eligible().items()},
        "strategies": {},
    }
    for name, spec in STRATS.items():
        slug = name.split()[0]
        r: dict[str, Any] = {"spec": {k: v for k, v in spec.items()}}
        modes = {
            "mechanical_original": ("mechanical", spec["orig_hedge"]),
            "mechanical_defined": ("mechanical", WING),
            "disciplined": ("disciplined", WING),
        }
        results: dict[str, AccountResult] = {}
        for mode_name, (mode, hedge) in modes.items():
            sigs, sessions = build_signals(ctxs, spec, months, hedge, base_slip)
            res = run_account(sigs, sessions, CAPITAL, mode, base_slip)
            results[mode_name] = res
            n_sig = sum(len(v) for v in sigs.values())
            r[mode_name] = metrics(res, months, n_sig)
            write_csv(OUT / f"{slug}_{mode_name}_ledger.csv", res.trades)
            write_csv(OUT / f"{slug}_{mode_name}_journal.csv", res.journal)
            m = r[mode_name]
            print(
                f"{name:32s} {mode_name:20s} final ₹{m['final']:>10,.0f} ({m['return_pct']:+6.2f}%)"
                f" trades {m['trades']:3d}/{n_sig:3d} skipped {m['skipped']:3d} maxDD "
                f"{m['max_dd_pct']:.1f}% PF {m['profit_factor']}",
                flush=True,
            )
            if mode_name == "disciplined":
                risk_now = [s.risk_per_lot for d, v in sigs.items() for s in v if d.year >= 2025]
                margin_now = [
                    s.margin_per_lot for d, v in sigs.items() for s in v if d.year >= 2025
                ]
                r["capital_for_1pct_rule_2025_26"] = {
                    "median_risk_per_lot": float(np.median(risk_now)) if risk_now else None,
                    "median_margin_per_lot": float(np.median(margin_now)) if margin_now else None,
                    "capital_needed": float(
                        max(np.median(risk_now) / 0.01, np.median(margin_now) / 0.60)
                    )
                    if risk_now
                    else None,
                }
                r["risk_per_lot_by_month"] = {
                    f"{y}-{mm:02d}": float(
                        np.median(
                            [
                                s.risk_per_lot
                                for d, v in sigs.items()
                                for s in v
                                if (d.year, d.month) == (y, mm)
                            ]
                        )
                    )
                    for y, mm in months.items()
                }
        # ── stress tests ──
        stress: dict[str, Any] = {}
        for mode_name in ("mechanical_original", "disciplined"):
            mode, hedge = modes[mode_name]
            st: dict[str, Any] = {"base": (results[mode_name].final, r[mode_name]["max_dd_pct"])}
            slip25 = Slippage(option_pct=0.00625, option_min_points=0.125, historical_rates=True)
            sigs, sessions = build_signals(ctxs, spec, months, hedge, slip25)
            a = run_account(sigs, sessions, CAPITAL, mode, slip25)
            st["slippage_plus_25pct"] = (a.final, metrics(a, months, 0)["max_dd_pct"])
            sigs, sessions = build_signals(ctxs, spec, months, hedge, base_slip, cost_mult=1.5)
            a = run_account(sigs, sessions, CAPITAL, mode, base_slip, cost_mult=1.5)
            st["charges_plus_50pct"] = (a.final, metrics(a, months, 0)["max_dd_pct"])
            sigs, sessions = build_signals(ctxs, spec, months, hedge, base_slip)
            for cap in (75_000.0, 50_000.0):
                a = run_account(sigs, sessions, cap, mode, base_slip)
                st[f"capital_{int(cap / 1000)}k"] = (a.final, cap)
            st.update(outcome_stresses(results[mode_name]))
            gap = {}
            for jump in (0.01, -0.01, 0.02, -0.02):
                sh = {}
                for idx in spec["indices"]:
                    first_days = set()
                    for y, m in months.items():
                        days = [
                            d
                            for d in month_days(ctxs[idx], {y: m})
                            if not spec["expiry_only"] or ctxs[idx].cal.is_expiry(d)
                        ]
                        if days:
                            first_days.add(days[0])
                    sh[idx] = shocked(ctxs[idx], first_days, spec["kw"]["entry_bar"], jump)
                sigs, sessions = build_signals(sh, spec, months, hedge, base_slip)
                a = run_account(sigs, sessions, CAPITAL, mode, base_slip)
                gap[f"{jump:+.0%}"] = (a.final, metrics(a, months, 0)["max_dd_pct"])
            st["gap_1pct_first_signal_each_month"] = min(gap["+1%"], gap["-1%"], key=lambda x: x[0])
            st["gap_2pct_first_signal_each_month"] = min(gap["+2%"], gap["-2%"], key=lambda x: x[0])
            st["gap_detail"] = gap
            stress[mode_name] = st
            print(
                f"   stress {mode_name}: "
                + ", ".join(f"{k} ₹{v[0]:,.0f}" for k, v in st.items() if isinstance(v, tuple)),
                flush=True,
            )
        r["stress"] = stress
        # What-ifs OUTSIDE the stated rules, for context only (not part of the ranking).
        sigs, sessions = build_signals(ctxs, spec, months, WING, base_slip)
        whatif = {}
        for label, cap, rules in (
            (
                "risk_2pct_capital_1L",
                CAPITAL,
                DisciplineRules(risk_per_trade=0.02, reduced_risk_per_trade=0.01),
            ),
            ("risk_1pct_capital_4L", 400_000.0, DisciplineRules()),
        ):
            a = run_account(sigs, sessions, cap, "disciplined", base_slip, rules=rules)
            mm = metrics(a, months, sum(len(v) for v in sigs.values()))
            whatif[label] = {
                k: mm[k]
                for k in (
                    "initial",
                    "final",
                    "net",
                    "return_pct",
                    "trades",
                    "max_dd_pct",
                    "max_dd_rs",
                    "profit_factor",
                    "win_rate",
                    "skipped",
                )
            }
        r["whatif_outside_rules"] = whatif
        print("   what-if:", {k: (round(v["final"]), v["trades"]) for k, v in whatif.items()})
        report["strategies"][name] = r
    (CACHE / "stage2.json").write_text(json.dumps(report, default=str))


if __name__ == "__main__":
    main()
