"""Paper-trading account simulation with explicit risk-management and discipline rules.

Two execution modes over the same stream of strategy signals:

* **Mechanical** – every valid signal is taken at a fixed 1 lot if the margin fits
  (``margin ≤ 90%`` of equity). No risk-per-trade cap, no loss limits, no pauses.
* **Disciplined** – predefined, measurable rules only (no simulated "emotions"):
  - position size from stop-loss distance: lots = ⌊risk% × equity ÷ planned risk per lot⌋;
    if one lot exceeds the risk budget the trade is skipped;
  - risk% = 1% of current equity; 0.5% after a drawdown pause until a new equity high;
  - margin used ≤ 60% of equity (≥ 40% kept free for MTM swings);
  - daily loss limit 2% of the day's starting equity: no new entries once reached, and any
    open position is closed when the day's loss reaches it (hard stop);
  - 10% drawdown from peak → trading paused for the rest of that month ("pause & review"),
    then resumed at 0.5% risk; a further pause at each additional 10% of drawdown depth;
  - 3 consecutive losing trades → 2-session cooling-off; size never rises after losses;
  - one open position at a time; one entry per signal (no re-entry, no averaging, no
    martingale); only predefined setups are traded.

Every decision (entry, exit, skip) is written to a journal with its reason.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.backtesting.charges import Slippage, fixed_cost_per_order
from app.backtesting.sim import Trade
from app.backtesting.strategies.fno import Setup


@dataclass(frozen=True)
class DisciplineRules:
    risk_per_trade: float = 0.01
    reduced_risk_per_trade: float = 0.005
    margin_cap: float = 0.60
    daily_loss_limit: float = 0.02
    max_drawdown_pause: float = 0.10
    loss_streak_for_cooloff: int = 3
    cooloff_sessions: int = 2
    max_open_positions: int = 1


@dataclass(frozen=True)
class MechanicalRules:
    lots: int = 1
    margin_cap: float = 0.90


@dataclass
class Signal:
    setup: Setup
    margin_per_lot: float
    risk_per_lot: float  # planned loss if every short leg stops (+ wings lost + charges)


@dataclass
class AccountResult:
    capital: float
    final: float
    trades: list[dict[str, Any]] = field(default_factory=list)
    journal: list[dict[str, Any]] = field(default_factory=list)
    equity_by_session: list[tuple[date, float]] = field(default_factory=list)
    pauses: int = 0
    cooloffs: int = 0


def _execute(
    sig: Signal, lots: int, slip: Slippage, cost_mult: float, comb_sl: float | None
) -> tuple[Trade, float, float]:
    t = sig.setup.run(lots, slip, comb_sl=comb_sl, margin=sig.margin_per_lot * lots)
    costs = t.costs * cost_mult
    return t, t.gross - costs, costs


def run_account(
    signals: dict[date, list[Signal]],
    sessions: list[date],
    capital: float,
    mode: str,
    slip: Slippage,
    rules: DisciplineRules | None = None,
    mech: MechanicalRules | None = None,
    cost_mult: float = 1.0,
    run_trade: Callable[[Signal, int, float | None], tuple[Trade, float, float]] | None = None,
) -> AccountResult:
    """Simulate one account over ``sessions`` (ordered). ``signals`` maps day → signals in
    priority order. ``run_trade`` can override execution (used by stress tests)."""
    rules = rules or DisciplineRules()
    mech = mech or MechanicalRules()
    res = AccountResult(capital=capital, final=capital)
    equity = peak = capital
    reduced_until_high: float | None = None
    streak = 0
    cooloff_left = 0
    paused_month: tuple[int, int] | None = None
    next_pause_dd = rules.max_drawdown_pause  # pause again only if drawdown deepens by 10%

    def log(d: date, sig: Signal | None, action: str, reason: str, **kw: Any) -> None:
        row = {
            "date": d.isoformat(),
            "instrument": sig.setup.index if sig else "",
            "strategy": sig.setup.name if sig else "",
            "action": action,
            "reason": reason,
            "equity": round(equity, 2),
        }
        if sig is not None:
            s = sig.setup
            row.update(
                {
                    "expiry": s.expiry.isoformat(),
                    "entry_time": _clock(s.entry_bar),
                    "legs": "; ".join(
                        f"{'S' if leg.qty < 0 else 'B'} {leg.strike:.0f}"
                        f"{'CE' if leg.is_call else 'PE'}"
                        for leg in s.legs
                    ),
                    "lot_size": s.lot,
                    "risk_per_lot": round(sig.risk_per_lot, 2),
                    "margin_per_lot": round(sig.margin_per_lot, 2),
                }
            )
        row.update(kw)
        res.journal.append(row)

    execute = run_trade or (lambda sig, lots, comb: _execute(sig, lots, slip, cost_mult, comb))

    for d in sessions:
        day_sigs = signals.get(d, [])
        day_start = equity
        day_pnl = 0.0
        open_positions = 0
        if mode == "disciplined":
            if paused_month == (d.year, d.month):
                for s in day_sigs:
                    log(d, s, "SKIP", "drawdown pause (≥10% from peak): review before resuming")
                res.equity_by_session.append((d, equity))
                continue
            if cooloff_left > 0:
                for s in day_sigs:
                    log(
                        d,
                        s,
                        "SKIP",
                        f"cooling-off after {rules.loss_streak_for_cooloff} consecutive losses",
                    )
                cooloff_left -= 1
                res.equity_by_session.append((d, equity))
                continue
        settled: list[float] = []
        for sig in day_sigs:
            if mode == "mechanical":
                need = sig.margin_per_lot * mech.lots
                used = sum(t["margin"] for t in res.trades if t["entry"] == d.isoformat())
                if need + used > mech.margin_cap * equity:
                    log(
                        d,
                        sig,
                        "SKIP",
                        f"insufficient margin: need ₹{need:,.0f}, available "
                        f"₹{mech.margin_cap * equity - used:,.0f}",
                    )
                    continue
                t, net, costs = execute(sig, mech.lots, None)
                lots = mech.lots
            else:
                if open_positions >= rules.max_open_positions:
                    log(d, sig, "SKIP", "one position at a time (avoid overtrading)")
                    continue
                allowance = rules.daily_loss_limit * day_start + day_pnl
                if allowance <= 0:
                    log(d, sig, "SKIP", "daily loss limit reached")
                    continue
                risk_pct = (
                    rules.reduced_risk_per_trade
                    if reduced_until_high is not None
                    else rules.risk_per_trade
                )
                budget = risk_pct * equity
                lots_risk = math.floor(budget / sig.risk_per_lot) if sig.risk_per_lot > 0 else 0
                if lots_risk < 1:
                    log(
                        d,
                        sig,
                        "SKIP",
                        f"risk limit: 1 lot risks ₹{sig.risk_per_lot:,.0f} > "
                        f"{risk_pct:.1%} budget ₹{budget:,.0f}",
                    )
                    continue
                lots_margin = math.floor(rules.margin_cap * equity / sig.margin_per_lot)
                if lots_margin < 1:
                    log(
                        d,
                        sig,
                        "SKIP",
                        f"margin limit: 1 lot needs ₹{sig.margin_per_lot:,.0f} > "
                        f"{rules.margin_cap:.0%} of equity ₹{rules.margin_cap * equity:,.0f}",
                    )
                    continue
                lots = min(lots_risk, lots_margin)
                t, net, costs = execute(sig, lots, allowance)
                open_positions += 1
            margin = sig.margin_per_lot * lots
            log(
                d,
                sig,
                "ENTER",
                "predefined setup at its scheduled time",
                lots=lots,
                qty=lots * sig.setup.lot,
                margin_used=round(margin, 2),
                planned_risk=round(sig.risk_per_lot * lots, 2),
            )
            res.trades.append(
                {
                    "entry": d.isoformat(),
                    "exit": t.exit_day.isoformat(),
                    "index": sig.setup.index,
                    "strategy": sig.setup.name,
                    "expiry": sig.setup.expiry.isoformat(),
                    "lots": lots,
                    "qty": lots * sig.setup.lot,
                    "lot_size": sig.setup.lot,
                    "margin": margin,
                    "equity_before": equity,
                    "planned_risk": sig.risk_per_lot * lots,
                    "gross_before_costs": t.gross,
                    "costs": costs,
                    "slippage": t.slippage,
                    "fixed_costs": t.orders * fixed_cost_per_order() * cost_mult,
                    "net": net,
                    "exit_reason": t.exit_reason,
                }
            )
            settled.append(net)
            day_pnl += net
            reason = {
                "leg_sl": "stop-loss honoured on a short leg; rest closed 15:15",
                "comb_sl": "daily loss limit hard stop",
                "time": "time exit 15:15",
            }.get(t.exit_reason, t.exit_reason)
            log(d, sig, "EXIT", reason, net_pnl=round(net, 2), charges=round(costs, 2))
        first_today = len(res.trades) - len(settled)
        for i, net in enumerate(settled):
            equity += net
            res.trades[first_today + i]["equity_after"] = equity
            streak = streak + 1 if net < 0 else 0
        if mode == "disciplined":
            if streak >= rules.loss_streak_for_cooloff:
                cooloff_left = rules.cooloff_sessions
                res.cooloffs += 1
                streak = 0
                log(
                    d,
                    None,
                    "RULE",
                    f"{rules.loss_streak_for_cooloff} consecutive losses → "
                    f"cooling-off for {rules.cooloff_sessions} sessions",
                )
            if equity > peak:
                peak = equity
                next_pause_dd = rules.max_drawdown_pause
                if reduced_until_high is not None and equity > reduced_until_high:
                    reduced_until_high = None
                    log(d, None, "RULE", "new equity high → risk back to 1%")
            if equity <= (1 - next_pause_dd) * peak:
                paused_month = (d.year, d.month)
                reduced_until_high = peak
                res.pauses += 1
                log(
                    d,
                    None,
                    "RULE",
                    f"drawdown reached {next_pause_dd:.0%} → pause for rest of month and "
                    "review; resume next month at 0.5% risk until a new equity high",
                )
                next_pause_dd += rules.max_drawdown_pause
        else:
            peak = max(peak, equity)
        res.equity_by_session.append((d, equity))
    res.final = equity
    return res


def _clock(bar: int) -> str:
    minutes = 9 * 60 + 15 + bar
    return f"{minutes // 60:02d}:{minutes % 60:02d}"
