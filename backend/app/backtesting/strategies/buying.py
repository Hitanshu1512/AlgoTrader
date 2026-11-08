"""Famous retail index option-*buying* strategies, with community-standard parameters.

All strategies buy options (or, in the ``spread`` variant, a debit spread: buy the signal
option and sell a further out-of-the-money one in the same expiry), so the most a trade can
lose is the premium paid. Capital needed per trade = premium × lot size.

Rules are the commonly published versions; nothing here was tuned on the test data.
Decisions use closed bars only (a signal at a bar's close is executed at the next bar's
open). Indicators run on a continuous 5-minute series (warm-up carries across sessions).

Rules per strategy are listed in docs/research/option_buying_backtest.md §2:
ORB 15-min, PDH/PDL breakout, Supertrend 10,3, EMA 9/21, RSI 60/40, expiry hero-zero,
narrow-CPR ORB and the low-VIX long straddle.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import date

import numpy as np
import pandas as pd

from app.backtesting.data import BARS_PER_DAY
from app.backtesting.sim import Leg, Path, Trade, simulate_options
from app.backtesting.strategies.fno import (
    EXIT_1515,
    Ctx,
    _resample,
    low_vix_long_straddle,
    orb_option_buying,
)

TF = 5
BAR_0930 = 15
BAR_1430 = 315
SPREAD_STEPS = {"NIFTY": 4, "BANKNIFTY": 5}  # short leg 200 pts (Nifty) / 500 pts (Bank Nifty) away


# ───────────────────────── shared machinery ─────────────────────────


class Series5:
    """Continuous 5-minute bars over ``ctx.sessions`` mapped back to (day, 1-min bar)."""

    def __init__(self, ctx: Ctx) -> None:
        self.path = Path.from_days([ctx.bars[d] for d in ctx.sessions])
        self.h, self.l, self.c, self.last = _resample(self.path, TF)
        self.day_i = self.path.day_pos[self.last]
        self.bar = self.path.bar[self.last]  # 1-min bar index of the 5-min bar's last minute

    def per_day(self, flags: np.ndarray, n_days: int) -> list[np.ndarray]:
        """Event flags on 5-min bars → per-day boolean arrays over 1-min bars (at the close)."""
        out = [np.zeros(BARS_PER_DAY, dtype=bool) for _ in range(n_days)]
        for t in np.nonzero(flags)[0]:
            out[self.day_i[t]][self.bar[t]] = True
        return out


def _legs(ctx: Ctx, k: float, is_call: bool, e: date, spread: bool) -> list[Leg]:
    legs = [Leg(k, is_call, 1, e)]
    if spread:
        w = SPREAD_STEPS[ctx.index] * ctx.step
        legs.append(Leg(k + w if is_call else k - w, is_call, -1, e))
    return legs


def _trade(
    ctx: Ctx,
    name: str,
    d: date,
    is_call: bool,
    entry: int,
    *,
    sl_pct: float | None,
    tp_pct: float | None,
    exit_signal: np.ndarray | None,
    spread: bool,
    delta: float | None = None,
) -> Trade:
    e = ctx.cal.nearest(d)
    lot = ctx.lot_for(d, e)
    path, pricer = ctx.day_path(d)
    spot = float(path.open[entry])
    if delta is None:
        k = ctx.atm(spot)
    else:
        k = ctx.by_delta(pricer, d, e, spot, entry, delta, is_call)
    legs = _legs(ctx, k, is_call, e, spread)
    debit = sum(leg.qty * pricer.quote(leg, entry) for leg in legs)
    debit = max(debit, 0.05)
    return simulate_options(
        name + (" (spread)" if spread else ""),
        ctx.index,
        pricer,
        legs,
        entry,
        EXIT_1515,
        lot,
        ctx.slip,
        debit * lot,  # capital needed: premium paid
        comb_sl=sl_pct * debit * lot if sl_pct else None,
        comb_tp=tp_pct * debit * lot if tp_pct else None,
        exit_signal=exit_signal,
    )


def run_events(
    ctx: Ctx,
    name: str,
    long_ev: list[np.ndarray],
    short_ev: list[np.ndarray],
    *,
    exit_long: list[np.ndarray] | None = None,
    exit_short: list[np.ndarray] | None = None,
    sl_pct: float | None = None,
    tp_pct: float | None = None,
    first_bar: int = BAR_0930,
    last_bar: int = BAR_1430,
    max_per_day: int = 99,
    spread: bool = False,
    delta: float | None = None,
    day_ok: Callable[[int, date], bool] | None = None,
) -> list[Trade]:
    """One position at a time; a new entry needs a fresh signal after the previous exit."""
    out: list[Trade] = []
    for i, d in enumerate(ctx.sessions):
        if not ctx.may_enter(d) or (day_ok is not None and not day_ok(i, d)):
            continue
        lo, hi = long_ev[i], short_ev[i]
        start, n = first_bar - 1, 0
        while n < max_per_day:
            window = slice(max(start, first_bar - 1), last_bar)
            cand = np.nonzero(lo[window] | hi[window])[0]
            if not len(cand):
                break
            sig = int(cand[0]) + window.start
            is_call = bool(lo[sig])
            entry = sig + 1
            ex = (exit_long if is_call else exit_short) if exit_long is not None else None
            t = _trade(
                ctx,
                name,
                d,
                is_call,
                entry,
                sl_pct=sl_pct,
                tp_pct=tp_pct,
                exit_signal=ex[i] if ex is not None else None,
                spread=spread,
                delta=delta,
            )
            out.append(t)
            n += 1
            # A signal exit happens at the open after the signal bar: that bar may itself be
            # the opposite entry signal (stop-and-reverse systems).
            start = t.exit_bar - 1 if t.exit_reason == "signal" else t.exit_bar
            if t.exit_bar >= EXIT_1515:
                break
    return out


def _cross_up(a: np.ndarray, b: np.ndarray | float) -> np.ndarray:
    b_arr = np.broadcast_to(b, a.shape)
    prev_a, prev_b = np.r_[a[0], a[:-1]], np.r_[b_arr[0], b_arr[:-1]]
    out: np.ndarray = (a > b_arr) & (prev_a <= prev_b)
    return out


def _cross_dn(a: np.ndarray, b: np.ndarray | float) -> np.ndarray:
    b_arr = np.broadcast_to(b, a.shape)
    prev_a, prev_b = np.r_[a[0], a[:-1]], np.r_[b_arr[0], b_arr[:-1]]
    out: np.ndarray = (a < b_arr) & (prev_a >= prev_b)
    return out


def supertrend_direction(
    h: np.ndarray, lo: np.ndarray, c: np.ndarray, period: int = 10, mult: float = 3.0
) -> np.ndarray:
    prev_c = np.r_[c[0], c[:-1]]
    tr = np.maximum.reduce([h - lo, np.abs(h - prev_c), np.abs(lo - prev_c)])
    atr = pd.Series(tr).ewm(alpha=1 / period, adjust=False).mean().to_numpy()
    mid = (h + lo) / 2
    ub, lb = mid + mult * atr, mid - mult * atr
    fu, fl = ub.copy(), lb.copy()
    direction = np.ones(len(c), dtype=int)
    for t in range(1, len(c)):
        fu[t] = ub[t] if (ub[t] < fu[t - 1] or c[t - 1] > fu[t - 1]) else fu[t - 1]
        fl[t] = lb[t] if (lb[t] > fl[t - 1] or c[t - 1] < fl[t - 1]) else fl[t - 1]
        if direction[t - 1] == 1:
            direction[t] = -1 if c[t] < fl[t] else 1
        else:
            direction[t] = 1 if c[t] > fu[t] else -1
    direction[: 2 * period] = 0  # warm-up
    return direction


def rsi(c: np.ndarray, period: int = 14) -> np.ndarray:
    d = np.diff(c, prepend=c[0])
    up = pd.Series(np.clip(d, 0, None)).ewm(alpha=1 / period, adjust=False).mean()
    dn = pd.Series(np.clip(-d, 0, None)).ewm(alpha=1 / period, adjust=False).mean()
    up_a, dn_a = up.to_numpy(), dn.to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(dn_a > 0, 100 - 100 / (1 + up_a / dn_a), np.where(up_a > 0, 100.0, 50.0))
    out[: 3 * period] = 50.0  # warm-up
    return out


# ───────────────────────── strategies ─────────────────────────


def pdh_pdl_breakout(ctx: Ctx, spread: bool = False) -> list[Trade]:
    s5 = Series5(ctx)
    n = len(ctx.sessions)
    pdh = np.full(len(s5.c), np.nan)
    pdl = np.full(len(s5.c), np.nan)
    for i in range(1, n):
        prev = ctx.bars[ctx.sessions[i - 1]]
        m = s5.day_i == i
        pdh[m], pdl[m] = float(prev.high.max()), float(prev.low.min())
    first_of_day = np.r_[True, s5.day_i[1:] != s5.day_i[:-1]]
    day_open = np.array([float(ctx.bars[ctx.sessions[i]].open[0]) for i in s5.day_i])
    prev_c = np.where(first_of_day, day_open, np.r_[s5.c[0], s5.c[:-1]])
    up = (s5.c > pdh) & (prev_c <= pdh)
    dn = (s5.c < pdl) & (prev_c >= pdl)
    return run_events(
        ctx,
        "PDH/PDL breakout",
        s5.per_day(up, n),
        s5.per_day(dn, n),
        sl_pct=0.30,
        tp_pct=0.60,
        first_bar=5,
        max_per_day=1,
        spread=spread,
    )


def supertrend_buying(ctx: Ctx, spread: bool = False) -> list[Trade]:
    s5 = Series5(ctx)
    n = len(ctx.sessions)
    dirn = supertrend_direction(s5.h, s5.l, s5.c)
    prev = np.r_[0, dirn[:-1]]
    up = (dirn == 1) & (prev == -1)
    dn = (dirn == -1) & (prev == 1)
    up_d, dn_d = s5.per_day(up, n), s5.per_day(dn, n)
    return run_events(
        ctx,
        "Supertrend 10,3 buying",
        up_d,
        dn_d,
        exit_long=dn_d,
        exit_short=up_d,
        spread=spread,
    )


def ema_crossover_buying(ctx: Ctx, spread: bool = False) -> list[Trade]:
    s5 = Series5(ctx)
    n = len(ctx.sessions)
    ef = pd.Series(s5.c).ewm(span=9, adjust=False).mean().to_numpy()
    es = pd.Series(s5.c).ewm(span=21, adjust=False).mean().to_numpy()
    up, dn = _cross_up(ef, es), _cross_dn(ef, es)
    up[:21] = dn[:21] = False
    up_d, dn_d = s5.per_day(up, n), s5.per_day(dn, n)
    return run_events(
        ctx, "EMA 9/21 buying", up_d, dn_d, exit_long=dn_d, exit_short=up_d, spread=spread
    )


def rsi_60_40(ctx: Ctx, spread: bool = False) -> list[Trade]:
    s5 = Series5(ctx)
    n = len(ctx.sessions)
    r = rsi(s5.c)
    up, dn = _cross_up(r, 60.0), _cross_dn(r, 40.0)
    return run_events(
        ctx,
        "RSI 60/40 buying",
        s5.per_day(up, n),
        s5.per_day(dn, n),
        sl_pct=0.30,
        tp_pct=0.60,
        spread=spread,
    )


def expiry_hero_zero(ctx: Ctx, spread: bool = False) -> list[Trade]:
    s5 = Series5(ctx)
    n = len(ctx.sessions)
    # Day's high/low *before* each 5-min bar (running extremes of completed bars).
    run_hi = np.full(len(s5.c), np.nan)
    run_lo = np.full(len(s5.c), np.nan)
    for i in range(n):
        idx = np.nonzero(s5.day_i == i)[0]
        hh = np.maximum.accumulate(s5.h[idx])
        ll = np.minimum.accumulate(s5.l[idx])
        run_hi[idx[1:]], run_lo[idx[1:]] = hh[:-1], ll[:-1]
    up = s5.c > run_hi
    dn = s5.c < run_lo
    expiry = {i for i, d in enumerate(ctx.sessions) if ctx.cal.is_expiry(d)}
    return run_events(
        ctx,
        "Expiry hero-zero",
        s5.per_day(up, n),
        s5.per_day(dn, n),
        sl_pct=0.50,
        first_bar=255,  # 13:30
        last_bar=330,  # 14:45
        max_per_day=1,
        spread=spread,
        delta=0.15,
        day_ok=lambda i, _d: i in expiry,
    )


def narrow_cpr_orb(ctx: Ctx, lookback: int = 50, pct: float = 0.25) -> list[Trade]:
    widths = []
    for i in range(len(ctx.sessions)):
        if i == 0:
            widths.append(np.nan)
            continue
        b = ctx.bars[ctx.sessions[i - 1]]
        h, lo, c = float(b.high.max()), float(b.low.min()), float(b.close[-1])
        p = (h + lo + c) / 3
        bc = (h + lo) / 2
        widths.append(abs(2 * p - 2 * bc) / p)  # |TC − BC| / P with TC = 2P − BC
    w = pd.Series(widths)
    thresh = w.shift(1).rolling(lookback, min_periods=lookback).quantile(pct)
    ok = frozenset(d for d, x, t in zip(ctx.sessions, w, thresh, strict=True) if x <= t)
    days = ok if ctx.entry_days is None else ok & ctx.entry_days
    trades = orb_option_buying(replace(ctx, entry_days=days))
    for t in trades:
        t.strategy = "Narrow-CPR ORB"
    return trades


STRATEGIES: dict[str, Callable[..., list[Trade]]] = {
    "ORB 15-min": orb_option_buying,
    "PDH/PDL breakout": pdh_pdl_breakout,
    "Supertrend 10,3": supertrend_buying,
    "EMA 9/21": ema_crossover_buying,
    "RSI 60/40": rsi_60_40,
    "Expiry hero-zero": expiry_hero_zero,
    "Narrow-CPR ORB": narrow_cpr_orb,
    "Low-VIX long straddle": low_vix_long_straddle,
}
# Strategies that take a ``spread=True`` debit-spread variant.
SPREADABLE = {"PDH/PDL breakout", "Supertrend 10,3", "EMA 9/21", "RSI 60/40", "Expiry hero-zero"}
