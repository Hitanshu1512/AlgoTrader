"""Ten widely-used Indian index F&O strategies, with community-standard parameters.

Every function returns a list of ``Trade``. Decisions use only information available at
the decision time (closed bars, previous-day closes, previous-day option surface).
Bar indices: 0 = 09:15, 5 = 09:20, 15 = 09:30, 360 = 15:15.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from app.backtesting.calendar import ExpiryCalendar
from app.backtesting.charges import Slippage
from app.backtesting.data import BARS_PER_DAY, DayBars
from app.backtesting.sim import Leg, LegPricer, Path, Trade, simulate_futures, simulate_options
from app.backtesting.vol import VolModel

ENTRY_920 = 5
EXIT_1515 = 360
NAKED_MARGIN = 0.11  # ≈ SPAN + exposure for a short index straddle/strangle, % of notional
EXPIRY_ELM = 0.02  # additional extreme-loss margin on expiry day (SEBI, Nov 2024)


@dataclass
class Ctx:
    index: str
    sessions: list[date]  # study sessions (sorted)
    bars: dict[date, DayBars]
    cal: ExpiryCalendar
    model: VolModel
    lot: int
    step: int
    slip: Slippage = field(default_factory=Slippage)
    vix_close: pd.Series | None = None
    # Optional per-(trade date, expiry) exchange lot size; defaults to ``lot``.
    lot_fn: Callable[[date, date], int] | None = None
    # Optional restriction of entry days (e.g. sampled months); exits may fall later.
    entry_days: frozenset[date] | None = None

    def lot_for(self, d: date, e: date) -> int:
        return self.lot_fn(d, e) if self.lot_fn else self.lot

    def may_enter(self, d: date) -> bool:
        return self.entry_days is None or d in self.entry_days

    def day_path(self, d: date) -> tuple[Path, LegPricer]:
        path = Path.from_days([self.bars[d]])
        return path, LegPricer(self.model, path)

    def span_path(self, i: int, j: int) -> tuple[Path, LegPricer]:
        path = Path.from_days([self.bars[d] for d in self.sessions[i : j + 1]])
        return path, LegPricer(self.model, path)

    def atm(self, spot: float) -> float:
        return float(round(spot / self.step) * self.step)

    def by_delta(
        self,
        pricer: LegPricer,
        d: date,
        e: date,
        spot: float,
        at_bar: int,
        target: float,
        is_call: bool,
    ) -> float:
        m = self.model
        sigma, smile = m.anchor(d, e)
        atm = self.atm(spot)
        offs = np.arange(1, 60) * self.step
        k = atm + offs if is_call else atm - offs
        delta = np.abs(m.delta(d, e, spot, k, is_call, at_bar - 1, sigma, smile, m.vix_path(d)))
        return float(k[np.argmin(np.abs(delta - target))])


def _naked_margin(ctx: Ctx, spot: float, d: date, lot: int) -> float:
    return (NAKED_MARGIN + (EXPIRY_ELM if ctx.cal.is_expiry(d) else 0.0)) * spot * lot


# ───────────────────────── intraday short premium ─────────────────────────


@dataclass
class Setup:
    """A fully specified entry decided at ``entry_bar`` (legs priced per 1 lot)."""

    name: str
    index: str
    day: date
    expiry: date
    legs: list[Leg]
    entry_bar: int
    exit_bar: int
    leg_sl_pct: float | None
    lot: int
    spot: float
    path: Path
    pricer: LegPricer

    def run(
        self,
        lots: int = 1,
        slip: Slippage | None = None,
        comb_sl: float | None = None,
        margin: float = 0.0,
    ) -> Trade:
        return simulate_options(
            self.name,
            self.index,
            self.pricer,
            self.legs,
            self.entry_bar,
            self.exit_bar,
            self.lot * lots,
            slip or Slippage(),
            margin,
            leg_sl_pct=self.leg_sl_pct,
            comb_sl=comb_sl,
        )


def _wings(
    ctx: Ctx,
    pricer: LegPricer,
    d: date,
    e: date,
    spot: float,
    entry_bar: int,
    hedge_delta: float,
    kc: float,
    kp: float,
) -> list[Leg]:
    hc = max(ctx.by_delta(pricer, d, e, spot, entry_bar, hedge_delta, True), kc + ctx.step)
    hp = min(ctx.by_delta(pricer, d, e, spot, entry_bar, hedge_delta, False), kp - ctx.step)
    return [Leg(hc, True, 1, e), Leg(hp, False, 1, e)]


def straddle_setup(
    ctx: Ctx,
    d: date,
    sl: float,
    entry_bar: int = ENTRY_920,
    hedge_delta: float | None = None,
    name: str = "straddle",
) -> Setup:
    e = ctx.cal.nearest(d)
    lot = ctx.lot_for(d, e)
    path, pricer = ctx.day_path(d)
    spot = float(path.open[entry_bar])
    k = ctx.atm(spot)
    legs = [Leg(k, True, -1, e), Leg(k, False, -1, e)]
    if hedge_delta is not None:
        legs += _wings(ctx, pricer, d, e, spot, entry_bar, hedge_delta, k, k)
    return Setup(name, ctx.index, d, e, legs, entry_bar, EXIT_1515, sl, lot, spot, path, pricer)


def strangle_setup(
    ctx: Ctx,
    d: date,
    delta: float,
    sl: float,
    entry_bar: int = ENTRY_920,
    hedge_delta: float | None = None,
    name: str = "strangle",
) -> Setup:
    e = ctx.cal.nearest(d)
    lot = ctx.lot_for(d, e)
    path, pricer = ctx.day_path(d)
    spot = float(path.open[entry_bar])
    kc = ctx.by_delta(pricer, d, e, spot, entry_bar, delta, True)
    kp = ctx.by_delta(pricer, d, e, spot, entry_bar, delta, False)
    legs = [Leg(kc, True, -1, e), Leg(kp, False, -1, e)]
    if hedge_delta is not None:
        legs += _wings(ctx, pricer, d, e, spot, entry_bar, hedge_delta, kc, kp)
    return Setup(name, ctx.index, d, e, legs, entry_bar, EXIT_1515, sl, lot, spot, path, pricer)


def _legacy_margin(ctx: Ctx, s: Setup) -> float:
    if len(s.legs) == 2:
        return _naked_margin(ctx, s.spot, s.day, s.lot)
    short = [x.strike for x in s.legs if x.qty < 0]
    wings = [x.strike for x in s.legs if x.qty > 0]
    return max(wings[0] - short[0], short[1] - wings[1]) * s.lot * 1.1


def straddle_920(
    ctx: Ctx,
    sl: float = 0.25,
    expiry_only: bool = False,
    name: str = "920 short straddle",
    entry_bar: int = ENTRY_920,
    hedge_delta: float | None = None,
) -> list[Trade]:
    """Sell the ATM straddle at ``entry_bar`` with a per-leg stop; exit 15:15.
    Optional long wings at ``hedge_delta`` cap the loss if a stop fails and cut margin."""
    out = []
    for d in ctx.sessions:
        if not ctx.may_enter(d):
            continue
        if expiry_only and not ctx.cal.is_expiry(d):
            continue
        s = straddle_setup(ctx, d, sl, entry_bar, hedge_delta, name)
        out.append(s.run(1, ctx.slip, margin=_legacy_margin(ctx, s)))
    return out


def strangle_920(
    ctx: Ctx,
    delta: float = 0.2,
    sl: float = 0.3,
    hedge_delta: float | None = None,
    entry_bar: int = ENTRY_920,
    name: str = "920 short strangle",
) -> list[Trade]:
    """Sell ~``delta`` call and put; per-leg stop. Optional long wings at ``hedge_delta``
    (bought for protection and the hedged-margin benefit; the wings are held to 15:15)."""
    out = []
    for d in ctx.sessions:
        if not ctx.may_enter(d):
            continue
        s = strangle_setup(ctx, d, delta, sl, entry_bar, hedge_delta, name)
        out.append(s.run(1, ctx.slip, margin=_legacy_margin(ctx, s)))
    return out


def iron_fly_920(ctx: Ctx, sl_frac: float = 0.35, name: str = "920 iron fly") -> list[Trade]:
    """Short ATM straddle hedged with wings at ± the straddle premium; combined stop."""
    out = []
    for d in ctx.sessions:
        if not ctx.may_enter(d):
            continue
        e = ctx.cal.nearest(d)
        lot = ctx.lot_for(d, e)
        path, pricer = ctx.day_path(d)
        spot = float(path.open[ENTRY_920])
        k = ctx.atm(spot)
        prem = pricer.quote(Leg(k, True, -1, e), ENTRY_920) + pricer.quote(
            Leg(k, False, -1, e), ENTRY_920
        )
        w = max(ctx.step, round(prem / ctx.step) * ctx.step)
        legs = [
            Leg(k, True, -1, e),
            Leg(k, False, -1, e),
            Leg(k + w, True, 1, e),
            Leg(k - w, False, 1, e),
        ]
        credit = prem - pricer.quote(legs[2], ENTRY_920) - pricer.quote(legs[3], ENTRY_920)
        out.append(
            simulate_options(
                name,
                ctx.index,
                pricer,
                legs,
                ENTRY_920,
                EXIT_1515,
                lot,
                ctx.slip,
                w * lot,
                comb_sl=sl_frac * credit * lot,
            )
        )
    return out


# ───────────────────────── positional short premium ─────────────────────────


def _series_entries(ctx: Ctx, max_dte: int, min_dte: int = 1) -> list[tuple[int, date]]:
    """(session index, expiry): first session within ``max_dte`` days of each expiry."""
    seen: set[date] = set()
    out = []
    for i, d in enumerate(ctx.sessions):
        e = ctx.cal.nearest(d, min_days=1)
        dte = (e - d).days
        if e in seen or dte > max_dte or dte < min_dte or e > ctx.sessions[-1]:
            continue
        if not ctx.may_enter(d):
            continue
        seen.add(e)
        out.append((i, e))
    return out


def _session_of(ctx: Ctx, e: date) -> int:
    return ctx.sessions.index(e)


def iron_condor(
    ctx: Ctx,
    short_delta: float = 0.16,
    wing_pct: float = 0.02,
    tp: float = 0.5,
    sl_mult: float = 1.5,
    max_dte: int = 9,
) -> list[Trade]:
    out = []
    for i, e in _series_entries(ctx, max_dte):
        if e not in ctx.bars:
            continue
        j = _session_of(ctx, e)
        path, pricer = ctx.span_path(i, j)
        d = ctx.sessions[i]
        lot = ctx.lot_for(d, e)
        spot = float(path.open[ENTRY_920])
        kc = ctx.by_delta(pricer, d, e, spot, ENTRY_920, short_delta, True)
        kp = ctx.by_delta(pricer, d, e, spot, ENTRY_920, short_delta, False)
        w = max(ctx.step, round(wing_pct * spot / ctx.step) * ctx.step)
        legs = [
            Leg(kc, True, -1, e),
            Leg(kp, False, -1, e),
            Leg(kc + w, True, 1, e),
            Leg(kp - w, False, 1, e),
        ]
        credit = sum(-leg.qty * pricer.quote(leg, ENTRY_920) for leg in legs)
        if credit <= 0:
            continue
        exit_bar = path.index(j - i, EXIT_1515)
        out.append(
            simulate_options(
                "Weekly iron condor",
                ctx.index,
                pricer,
                legs,
                ENTRY_920,
                exit_bar,
                lot,
                ctx.slip,
                w * lot,
                comb_sl=sl_mult * credit * lot,
                comb_tp=tp * credit * lot,
            )
        )
    return out


def trend_credit_spread(
    ctx: Ctx,
    short_delta: float = 0.25,
    width_pct: float = 0.015,
    tp: float = 0.5,
    sl_mult: float = 1.5,
    ema_days: int = 20,
    max_dte: int = 9,
) -> list[Trade]:
    closes = pd.Series({d: float(ctx.bars[d].close[-1]) for d in ctx.sessions})
    ema = closes.ewm(span=ema_days, adjust=False).mean()
    out = []
    for i, e in _series_entries(ctx, max_dte):
        if i == 0 or e not in ctx.bars:
            continue
        prev = ctx.sessions[i - 1]
        bullish = closes[prev] > ema[prev]  # known at the previous close
        j = _session_of(ctx, e)
        path, pricer = ctx.span_path(i, j)
        d = ctx.sessions[i]
        lot = ctx.lot_for(d, e)
        spot = float(path.open[ENTRY_920])
        w = max(ctx.step, round(width_pct * spot / ctx.step) * ctx.step)
        if bullish:
            kp = ctx.by_delta(pricer, d, e, spot, ENTRY_920, short_delta, False)
            legs = [Leg(kp, False, -1, e), Leg(kp - w, False, 1, e)]
        else:
            kc = ctx.by_delta(pricer, d, e, spot, ENTRY_920, short_delta, True)
            legs = [Leg(kc, True, -1, e), Leg(kc + w, True, 1, e)]
        credit = sum(-leg.qty * pricer.quote(leg, ENTRY_920) for leg in legs)
        if credit <= 0:
            continue
        exit_bar = path.index(j - i, EXIT_1515)
        out.append(
            simulate_options(
                "Trend credit spread",
                ctx.index,
                pricer,
                legs,
                ENTRY_920,
                exit_bar,
                lot,
                ctx.slip,
                w * lot,
                comb_sl=sl_mult * credit * lot,
                comb_tp=tp * credit * lot,
            )
        )
    return out


# ───────────────────────── long premium ─────────────────────────


def orb_option_buying(
    ctx: Ctx, range_bars: int = 15, last_entry: int = 225, target_mult: float = 2.0
) -> list[Trade]:
    """15-min opening-range breakout: buy ATM CE/PE on a close outside the range.
    Stop: spot closes back beyond the opposite end; target: 2× range beyond breakout."""
    out = []
    for d in ctx.sessions:
        if not ctx.may_enter(d):
            continue
        b = ctx.bars[d]
        hi, lo = float(b.high[:range_bars].max()), float(b.low[:range_bars].min())
        c = b.close
        up = np.nonzero(c[range_bars:last_entry] > hi)[0]
        dn = np.nonzero(c[range_bars:last_entry] < lo)[0]
        first_up = up[0] + range_bars if len(up) else BARS_PER_DAY
        first_dn = dn[0] + range_bars if len(dn) else BARS_PER_DAY
        if first_up == first_dn == BARS_PER_DAY:
            continue
        long_ = first_up < first_dn
        sig = min(first_up, first_dn)
        entry = sig + 1
        e = ctx.cal.nearest(d)
        lot = ctx.lot_for(d, e)
        path, pricer = ctx.day_path(d)
        k = ctx.atm(float(path.open[entry]))
        rng = hi - lo
        if long_:
            exit_sig = (c < lo) | (c >= hi + target_mult * rng)
        else:
            exit_sig = (c > hi) | (c <= lo - target_mult * rng)
        leg = Leg(k, long_, 1, e)
        prem = pricer.quote(leg, entry)
        out.append(
            simulate_options(
                "ORB option buying",
                ctx.index,
                pricer,
                [leg],
                entry,
                EXIT_1515,
                lot,
                ctx.slip,
                prem * lot,
                exit_signal=exit_sig,
            )
        )
    return out


def low_vix_long_straddle(
    ctx: Ctx,
    pct: float = 0.2,
    lookback: int = 252,
    tp: float = 0.4,
    sl: float = 0.35,
    max_dte: int = 9,
) -> list[Trade]:
    assert ctx.vix_close is not None
    vix = ctx.vix_close
    out = []
    for i, e in _series_entries(ctx, max_dte, min_dte=3):
        if i == 0:
            continue
        prev = ctx.sessions[i - 1]
        hist = vix[vix.index <= prev].tail(lookback)
        if len(hist) < lookback // 2 or hist.iloc[-1] > hist.quantile(pct):
            continue
        j = max(_session_of(ctx, e) - 1, i)  # exit the session before expiry
        path, pricer = ctx.span_path(i, j)
        d = ctx.sessions[i]
        lot = ctx.lot_for(d, e)
        k = ctx.atm(float(path.open[ENTRY_920]))
        legs = [Leg(k, True, 1, e), Leg(k, False, 1, e)]
        prem = sum(pricer.quote(leg, ENTRY_920) for leg in legs)
        out.append(
            simulate_options(
                "Low-VIX long straddle",
                ctx.index,
                pricer,
                legs,
                ENTRY_920,
                path.index(j - i, EXIT_1515),
                lot,
                ctx.slip,
                prem * lot,
                comb_sl=sl * prem * lot,
                comb_tp=tp * prem * lot,
            )
        )
        _ = d
    return out


# ───────────────────────── futures trend following ─────────────────────────


def _resample(path: Path, minutes: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Per-session bars of ``minutes`` (starting 09:15). Returns (high, low, close, last_idx)."""
    per = BARS_PER_DAY // minutes + (BARS_PER_DAY % minutes > 0)
    hs, ls, cs, idx = [], [], [], []
    for i in range(len(path.days)):
        base = i * BARS_PER_DAY
        for j in range(per):
            a, b = base + j * minutes, min(base + (j + 1) * minutes, base + BARS_PER_DAY) - 1
            hs.append(path.high[a : b + 1].max())
            ls.append(path.low[a : b + 1].min())
            cs.append(path.close[b])
            idx.append(b)
    return np.array(hs), np.array(ls), np.array(cs), np.array(idx)


def _monthly(ctx: Ctx) -> list[date]:
    out, by_month = [], {}
    for e in ctx.cal.expiries:
        by_month[(e.year, e.month)] = e
    out = sorted(by_month.values())
    return out


def supertrend_futures(ctx: Ctx, period: int = 10, mult: float = 3.0, tf: int = 15) -> list[Trade]:
    path = Path.from_days([ctx.bars[d] for d in ctx.sessions])
    h, lo, c, last = _resample(path, tf)
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
    target = np.zeros(len(path.close), dtype=int)
    for t in range(period * 2, len(c)):
        end = last[t + 1] if t + 1 < len(c) else len(path.close) - 1
        target[last[t] : end] = direction[t]
    lot = ctx.lot
    if ctx.entry_days is not None:
        # Indicator warms up on earlier data; positions only on entry days, and every
        # position is flattened at 15:15 on the last entry day of each contiguous block.
        active = np.array([d in ctx.entry_days for d in path.days])
        bar_active = np.repeat(active, BARS_PER_DAY)
        nxt_active = np.r_[active[1:], False]
        last_block_day = np.repeat(active & ~nxt_active, BARS_PER_DAY)
        target = np.where(bar_active & ~(last_block_day & (path.bar >= EXIT_1515 - 1)), target, 0)
        first = next(d for d in path.days if d in ctx.entry_days)
        lot = ctx.lot_for(first, ctx.cal.nearest(first))
    return simulate_futures(
        "Supertrend futures", ctx.index, path, target, lot, ctx.slip, _monthly(ctx)
    )


def ema_crossover_intraday(
    ctx: Ctx, fast: int = 9, slow: int = 21, tf: int = 5, start_bar: int = 15, flat_bar: int = 359
) -> list[Trade]:
    path = Path.from_days([ctx.bars[d] for d in ctx.sessions])
    _h, _l, c, last = _resample(path, tf)
    ef = pd.Series(c).ewm(span=fast, adjust=False).mean().to_numpy()
    es = pd.Series(c).ewm(span=slow, adjust=False).mean().to_numpy()
    sign = np.sign(ef - es).astype(int)
    target = np.zeros(len(path.close), dtype=int)
    for t in range(slow, len(c)):
        end = last[t + 1] if t + 1 < len(c) else len(path.close) - 1
        target[last[t] : end] = sign[t]
    in_session = (path.bar >= start_bar - 1) & (path.bar < flat_bar)
    target = np.where(in_session, target, 0)
    return simulate_futures(
        "EMA 9/21 intraday futures", ctx.index, path, target, ctx.lot, ctx.slip, []
    )


STRATEGIES: dict[str, Callable[[Ctx], list[Trade]]] = {
    "920 short straddle": straddle_920,
    "920 short strangle": strangle_920,
    "920 iron fly": iron_fly_920,
    "Expiry-day straddle": lambda ctx: straddle_920(
        ctx, sl=0.30, expiry_only=True, name="Expiry-day straddle"
    ),
    "Weekly iron condor": iron_condor,
    "Trend credit spread": trend_credit_spread,
    "ORB option buying": orb_option_buying,
    "Low-VIX long straddle": low_vix_long_straddle,
    "Supertrend futures": supertrend_futures,
    "EMA 9/21 intraday futures": ema_crossover_intraday,
}
