"""Systematic option strategies on real end-of-day NSE option prices (see ``eod.py``).

Plan 1 candidates (regular, defined-risk):
* ``credit_spread`` – trend-following weekly credit spread: N trading days before each
  expiry, sell the ~Δ put (uptrend) or call (downtrend) and buy the strike ``width`` away.
* ``iron_condor`` – both sides, no trend view.
* ``debit_spread`` – trend-following debit spread once per expiry cycle.

Plan 2 candidates (small capital, convex):
* ``breakout_buy`` – buy the ATM option (or a debit spread) on a close beyond the N-day
  high / low.
* ``vol_expansion`` – buy the ATM straddle after an NR7 day when ATM IV is in the lowest
  30% of the past 120 sessions.
* ``event_straddle`` – buy the ATM straddle at the open of a scheduled event day (Union
  Budget, general-election results) and sell it at that day's close.

All decisions use data up to the signal day's close; entries are at the next open.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from app.backtesting.eod import STEP, Chain, EodTrade, ExitRules, OptLeg, Slip, simulate

EVENTS = [  # scheduled, market-moving, dates fixed in advance (Union Budget; election results)
    date(2021, 2, 1),
    date(2022, 2, 1),
    date(2023, 2, 1),
    date(2024, 2, 1),
    date(2024, 6, 4),
    date(2024, 7, 23),
    date(2025, 2, 1),
    date(2026, 2, 1),
]


def _ema(x: pd.Series, n: int) -> pd.Series:
    return x.ewm(span=n, adjust=False).mean()


def _trend(ch: Chain, n: int = 20) -> pd.Series:
    """+1 above a rising EMA, −1 below a falling one, 0 otherwise (known at each close)."""
    c = ch.bars["close"]
    e = _ema(c, n)
    up = (c > e) & (e > e.shift(1))
    dn = (c < e) & (e < e.shift(1))
    return pd.Series(np.where(up, 1, np.where(dn, -1, 0)), index=c.index)


def _cycle_entries(ch: Chain, dte: int) -> list[tuple[date, date]]:
    """(signal day, expiry) so that entry (next open) is ``dte`` trading days before expiry
    and the expiry is the nearest listed one at entry."""
    out = []
    seen: set[date] = set()
    for i in range(1, len(ch.days)):
        entry, sig = ch.days[i], ch.days[i - 1]
        e = ch.nearest_expiry(entry, 0)
        if e is None or e in seen or sig not in ch.bars.index:
            continue
        if ch.trading_days_to(entry, e) == dte:
            out.append((sig, e))
            seen.add(e)
    return out


def _run(
    ch: Chain,
    name: str,
    specs: list[tuple[date, date, list[OptLeg]]],
    rules: ExitRules,
    slip: Slip,
    stress: bool,
    misses: dict[str, int] | None,
) -> list[EodTrade]:
    out: list[EodTrade] = []
    busy_until: date | None = None
    for sig, e, legs in specs:
        if busy_until is not None and sig < busy_until:
            continue
        r = simulate(ch, name, sig, e, legs, rules, slip, stress=stress)
        if isinstance(r, str):
            if misses is not None:
                misses[r] = misses.get(r, 0) + 1
            continue
        out.append(r)
        busy_until = r.exit_day
    return out


def credit_spread(
    ch: Chain,
    delta: float = 0.25,
    dte: int = 3,
    width: int = 2,
    stop: float = 1.0,
    target: float = 0.6,
    slip: Slip | None = None,
    stress: bool = False,
    misses: dict[str, int] | None = None,
    name: str = "Trend credit spread",
) -> list[EodTrade]:
    tr = _trend(ch)
    w = width * STEP[ch.symbol]
    specs = []
    for sig, e in _cycle_entries(ch, dte):
        t = int(tr.get(sig, 0))
        if t == 0:
            continue
        is_call = t < 0
        k = ch.strike_by_delta(sig, e, delta, is_call)
        if k is None:
            continue
        hedge = k + w if is_call else k - w
        opt = "CE" if is_call else "PE"
        specs.append((sig, e, [OptLeg(k, opt, -1), OptLeg(hedge, opt, 1)]))
    return _run(
        ch, name, specs, ExitRules(stop=stop, target=target), slip or Slip(), stress, misses
    )


def iron_condor(
    ch: Chain,
    delta: float = 0.20,
    dte: int = 3,
    width: int = 2,
    stop: float = 1.0,
    target: float = 0.5,
    slip: Slip | None = None,
    stress: bool = False,
    misses: dict[str, int] | None = None,
    name: str = "Iron condor",
) -> list[EodTrade]:
    w = width * STEP[ch.symbol]
    specs = []
    for sig, e in _cycle_entries(ch, dte):
        kc = ch.strike_by_delta(sig, e, delta, True)
        kp = ch.strike_by_delta(sig, e, delta, False)
        if kc is None or kp is None:
            continue
        legs = [
            OptLeg(kc, "CE", -1),
            OptLeg(kc + w, "CE", 1),
            OptLeg(kp, "PE", -1),
            OptLeg(kp - w, "PE", 1),
        ]
        specs.append((sig, e, legs))
    return _run(
        ch, name, specs, ExitRules(stop=stop, target=target), slip or Slip(), stress, misses
    )


def debit_spread(
    ch: Chain,
    dte: int = 4,
    width: int = 4,
    stop: float = 0.5,
    target: float = 0.8,
    max_days: int = 5,
    slip: Slip | None = None,
    stress: bool = False,
    misses: dict[str, int] | None = None,
    name: str = "Trend debit spread",
) -> list[EodTrade]:
    tr = _trend(ch)
    w = width * STEP[ch.symbol]
    specs = []
    for sig, e in _cycle_entries(ch, dte):
        t = int(tr.get(sig, 0))
        if t == 0:
            continue
        f = ch.fwd.get((sig, e))
        k = ch.strike_near(sig, e, f) if f else None
        if k is None:
            continue
        if t > 0:
            legs = [OptLeg(k, "CE", 1), OptLeg(k + w, "CE", -1)]
        else:
            legs = [OptLeg(k, "PE", 1), OptLeg(k - w, "PE", -1)]
        specs.append((sig, e, legs))
    rules = ExitRules(stop=stop, target=target, max_days=max_days)
    return _run(ch, name, specs, rules, slip or Slip(), stress, misses)


def breakout_buy(
    ch: Chain,
    lookback: int = 20,
    stop: float = 0.4,
    target: float = 1.0,
    max_days: int = 3,
    min_dte: int = 3,
    spread_width: int = 0,
    slip: Slip | None = None,
    stress: bool = False,
    misses: dict[str, int] | None = None,
    name: str = "Breakout option buying",
) -> list[EodTrade]:
    b = ch.bars
    hh = b["high"].shift(1).rolling(lookback).max()
    ll = b["low"].shift(1).rolling(lookback).min()
    up = b["close"] > hh
    dn = b["close"] < ll
    specs = []
    w = spread_width * STEP[ch.symbol]
    for sig in b.index[(up | dn).to_numpy()]:
        i = ch.day_ix.get(sig)
        if i is None or i + 1 >= len(ch.days):
            continue
        e = ch.nearest_expiry(ch.days[i + 1], min_dte)
        f = ch.fwd.get((sig, e)) if e else None
        k = ch.strike_near(sig, e, f) if (e and f) else None
        if e is None or k is None:
            continue
        is_call = bool(up.loc[sig])
        opt = "CE" if is_call else "PE"
        legs = [OptLeg(k, opt, 1)]
        if spread_width:
            legs.append(OptLeg(k + w if is_call else k - w, opt, -1))
        specs.append((sig, e, legs))
    rules = ExitRules(stop=stop, target=target, max_days=max_days)
    return _run(ch, name, specs, rules, slip or Slip(), stress, misses)


def vol_expansion(
    ch: Chain,
    nr: int = 7,
    iv_pct: float = 0.30,
    iv_lookback: int = 120,
    target: float = 0.3,
    stop: float = 0.25,
    max_days: int = 3,
    min_dte: int = 3,
    slip: Slip | None = None,
    stress: bool = False,
    misses: dict[str, int] | None = None,
    name: str = "Volatility-expansion straddle",
) -> list[EodTrade]:
    b = ch.bars
    rng = b["high"] - b["low"]
    nr_day = rng <= rng.rolling(nr).min()
    ivs = {}
    for d in b.index:
        e = ch.nearest_expiry(d, min_dte)
        if e is not None and (d, e) in ch.atm_iv:
            ivs[d] = ch.atm_iv[(d, e)]
    iv = pd.Series(ivs).reindex(b.index)
    low_iv = iv <= iv.shift(1).rolling(iv_lookback, min_periods=iv_lookback // 2).quantile(iv_pct)
    specs = []
    for sig in b.index[(nr_day & low_iv).to_numpy()]:
        i = ch.day_ix[sig]
        if i + 1 >= len(ch.days):
            continue
        e = ch.nearest_expiry(ch.days[i + 1], min_dte)
        f = ch.fwd.get((sig, e)) if e else None
        k = ch.strike_near(sig, e, f) if (e and f) else None
        if e is None or k is None:
            continue
        specs.append((sig, e, [OptLeg(k, "CE", 1), OptLeg(k, "PE", 1)]))
    rules = ExitRules(stop=stop, target=target, max_days=max_days)
    return _run(ch, name, specs, rules, slip or Slip(), stress, misses)


def event_straddle(
    ch: Chain,
    slip: Slip | None = None,
    stress: bool = False,
    misses: dict[str, int] | None = None,
    name: str = "Event-day straddle",
) -> list[EodTrade]:
    specs = []
    for ev in EVENTS:
        if ev not in ch.day_ix:
            if misses is not None:
                misses["no session on event day"] = misses.get("no session on event day", 0) + 1
            continue
        sig = ch.days[ch.day_ix[ev] - 1]
        e = ch.nearest_expiry(ev, 1)
        f = ch.fwd.get((sig, e)) if e else None
        k = ch.strike_near(sig, e, f) if (e and f) else None
        if e is None or k is None:
            continue
        specs.append((sig, e, [OptLeg(k, "CE", 1), OptLeg(k, "PE", 1)]))
    return _run(ch, name, specs, ExitRules(max_days=0), slip or Slip(), stress, misses)


FAMILIES = {
    "Trend credit spread": credit_spread,
    "Iron condor": iron_condor,
    "Trend debit spread": debit_spread,
    "Breakout option buying": breakout_buy,
    "Breakout debit spread": lambda ch, **kw: breakout_buy(
        ch, **{"spread_width": 4, "name": "Breakout debit spread", **kw}
    ),
    "Volatility-expansion straddle": vol_expansion,
    "Event-day straddle": event_straddle,
}

# Small, pre-declared walk-forward grids (textbook values; 4–8 combinations each).
GRIDS: dict[str, list[dict[str, Any]]] = {
    "Trend credit spread": [
        {"delta": d, "dte": n, "stop": s} for d in (0.2, 0.3) for n in (2, 4) for s in (1.0, 1.5)
    ],
    "Iron condor": [
        {"delta": d, "dte": n, "stop": s} for d in (0.15, 0.25) for n in (2, 4) for s in (1.0, 1.5)
    ],
    "Trend debit spread": [
        {"width": w, "max_days": m, "stop": s} for w in (2, 4) for m in (3, 5) for s in (0.4, 0.6)
    ],
    "Breakout option buying": [
        {"lookback": lb, "stop": s, "target": t}
        for lb in (10, 20)
        for s in (0.3, 0.5)
        for t in (0.8, 1.5)
    ],
    "Breakout debit spread": [
        {"lookback": lb, "stop": s, "target": t}
        for lb in (10, 20)
        for s in (0.3, 0.5)
        for t in (0.6, 0.9)
    ],
    "Volatility-expansion straddle": [
        {"target": t, "stop": s, "max_days": m}
        for t in (0.3, 0.5)
        for s in (0.25, 0.4)
        for m in (2, 4)
    ],
    "Event-day straddle": [{}],
}
DEFAULTS: dict[str, dict[str, Any]] = {k: {} for k in FAMILIES}


# ───────────────────────── expiry-day short premium on real prices ─────────────────────────


def expiry_day_straddle(
    ch: Chain,
    sl: float = 0.5,
    wing_delta: float | None = 0.02,
    slip: Slip | None = None,
    stress: bool = False,
    misses: dict[str, int] | None = None,
    name: str = "Expiry-day straddle (real prices)",
) -> list[EodTrade]:
    """On each expiry day: sell the ATM call + put at the **real opening price**, buy wings
    (chosen at the previous close by delta), stop each short leg when its **real day-high**
    reaches (1 + sl) × entry, close everything at the real closing price.

    Legs are independent, so each short leg's stop can be checked on its own real high (the
    only intraday information in a bhavcopy). Entry is at 09:15 here, not 11:00 as in the
    intraday study, because only the open is known."""
    from app.backtesting.charges import fixed_cost_per_order, option_order_cost
    from app.backtesting.margin import LegFill, option_margin

    slip = slip or Slip()
    out: list[EodTrade] = []
    for e in sorted({x for xs in ch.expiries.values() for x in xs}):
        if e not in ch.day_ix or ch.day_ix[e] == 0:
            continue
        sig = ch.days[ch.day_ix[e] - 1]
        f = ch.fwd.get((sig, e))
        k = ch.strike_near(sig, e, f) if f else None
        if k is None:
            continue
        legs = [OptLeg(k, "CE", -1), OptLeg(k, "PE", -1)]
        if wing_delta is not None:
            kc = ch.strike_by_delta(sig, e, wing_delta, True)
            kp = ch.strike_by_delta(sig, e, wing_delta, False)
            if kc is None or kp is None:
                if misses is not None:
                    misses["no wing strike"] = misses.get("no wing strike", 0) + 1
                continue
            legs += [OptLeg(kc, "CE", 1), OptLeg(kp, "PE", 1)]
        qs = [ch.quote(e, e, leg.strike, leg.opt) for leg in legs]
        q0 = [ch.quote(sig, e, leg.strike, leg.opt) for leg in legs]
        if any(q is None or q[0] <= 0 or q[5] <= 0 for q in qs) or any(q is None for q in q0):
            if misses is not None:
                misses["leg did not trade at entry"] = (
                    misses.get("leg did not trade at entry", 0) + 1
                )
            continue
        lot = int(qs[0][6])  # type: ignore[index]
        fills, exits, reasons = [], [], []
        for leg, q in zip(legs, qs, strict=True):
            o, h, _lo, c = q[0], q[1], q[2], q[3]  # type: ignore[index]
            s = slip.of(o)
            if leg.qty < 0:
                fill = max(o - s, 0.05)
                level = fill * (1 + sl)
                if h >= level:
                    x = level + slip.of(level) * (2 if stress else 1)
                    reasons.append("stop")
                else:
                    x = c + slip.of(c)
                    reasons.append("close")
            else:
                fill = o + s
                x = max(c - slip.of(c), 0.0)
                reasons.append("close")
            fills.append(fill)
            exits.append(x)
        gross = sum(leg.qty * (x - p) for leg, p, x in zip(legs, fills, exits, strict=True)) * lot
        fixed = fixed_cost_per_order()
        var = 0.0
        for leg, p, x in zip(legs, fills, exits, strict=True):
            var += option_order_cost(p, lot, "BUY" if leg.qty > 0 else "SELL", e) - fixed
            if x > 0:
                var += option_order_cost(x, lot, "SELL" if leg.qty > 0 else "BUY", e) - fixed
        credit = -sum(leg.qty * p for leg, p in zip(legs, fills, strict=True))
        lf = [
            LegFill(leg.strike, leg.opt == "CE", leg.qty, p)
            for leg, p in zip(legs, fills, strict=True)
        ]
        margin = option_margin(lf, f, lot, e, e)  # type: ignore[arg-type]
        short_prem = sum(p for leg, p in zip(legs, fills, strict=True) if leg.qty < 0)
        wing_cost = sum(p for leg, p in zip(legs, fills, strict=True) if leg.qty > 0)
        planned = (sl * short_prem + wing_cost) * lot
        if wing_delta is not None:
            width = max(abs(legs[2].strike - k), abs(k - legs[3].strike))
            max_loss = (width - credit) * lot
        else:
            max_loss = float("inf")
        marks = {e: gross}
        out.append(
            EodTrade(
                name,
                ch.symbol,
                sig,
                e,
                e,
                e,
                legs,
                fills,
                exits,
                lot,
                gross,
                var,
                len(legs) + sum(1 for x in exits if x > 0),
                margin,
                planned,
                max_loss,
                "stop" if "stop" in reasons else "close",
                0,
                -credit,
                marks,
            )
        )
    return out


FAMILIES["Expiry-day straddle (real prices)"] = expiry_day_straddle
GRIDS["Expiry-day straddle (real prices)"] = [
    {"sl": s, "wing_delta": w} for s in (0.3, 0.5) for w in (None, 0.02)
]
