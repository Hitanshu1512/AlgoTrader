"""Minute-level trade simulation for index options and futures.

Fill conventions (conservative):
* Orders fill at the *open* of the decision bar plus adverse slippage.
* Stop-losses are checked against the bar's worst point (spot high for short calls,
  spot low for short puts; both extremes for combined positions). A triggered stop fills at
  the stop level, or at the bar's open if the market gapped through it, plus slippage.
* Targets are checked on bar closes only.
* All statutory charges + brokerage (``charges.py``) are deducted per executed order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np

from app.backtesting.charges import Slippage, futures_order_cost, option_order_cost
from app.backtesting.data import BARS_PER_DAY, DayBars
from app.backtesting.pricing import Smile
from app.backtesting.vol import DayVol, VolModel


@dataclass
class Path:
    """Consecutive sessions flattened into one bar array."""

    days: list[date]
    day_pos: np.ndarray  # index into days for each bar
    bar: np.ndarray  # 0..374 within its session
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray

    @classmethod
    def from_days(cls, bars: list[DayBars]) -> Path:
        n = len(bars)
        return cls(
            days=[b.day for b in bars],
            day_pos=np.repeat(np.arange(n), BARS_PER_DAY),
            bar=np.tile(np.arange(BARS_PER_DAY), n),
            open=np.concatenate([b.open for b in bars]),
            high=np.concatenate([b.high for b in bars]),
            low=np.concatenate([b.low for b in bars]),
            close=np.concatenate([b.close for b in bars]),
        )

    def index(self, day_i: int, bar: int) -> int:
        return day_i * BARS_PER_DAY + bar


@dataclass
class Leg:
    strike: float
    is_call: bool
    qty: int  # +lots bought, −lots sold
    expiry: date


@dataclass
class Trade:
    strategy: str
    index: str
    entry_day: date
    exit_day: date
    gross: float
    costs: float
    exit_reason: str
    margin: float
    legs: int
    daily_mtm: dict[date, float] = field(default_factory=dict)  # cumulative P&L at closes
    lot: int = 0  # exchange lot size used (quantity per strategy lot)
    entry_spot: float = 0.0
    fills: list[tuple[float, bool, int, float]] = field(
        default_factory=list
    )  # strike, call, qty, px
    expiry: date | None = None
    orders: int = 0
    slippage: float = 0.0  # ₹ lost to modelled bid-ask spread / impact (already in gross)

    @property
    def net(self) -> float:
        return self.gross - self.costs


class LegPricer:
    """Prices legs along a Path with per-day, look-ahead-free vol anchors."""

    def __init__(self, model: VolModel, path: Path) -> None:
        self.model = model
        self.path = path
        self._anchor: dict[tuple[int, date], tuple[float, Smile, DayVol]] = {}

    def _day(self, i: int, e: date) -> tuple[float, Smile, DayVol]:
        key = (i, e)
        if key not in self._anchor:
            d = self.path.days[i]
            sigma, smile = self.model.anchor(d, e)
            self._anchor[key] = (sigma, smile, self.model.vix_path(d))
        return self._anchor[key]

    def arrays(self, leg: Leg, lo: int, hi: int) -> dict[str, np.ndarray]:
        """Prices for bars [lo, hi]: at open, at spot-high, at spot-low, at close."""
        p = self.path
        out = {k: np.empty(hi - lo + 1) for k in ("open", "sh", "sl", "close")}
        pos = 0
        for i in range(p.day_pos[lo], p.day_pos[hi] + 1):
            a = max(lo, i * BARS_PER_DAY)
            b = min(hi, (i + 1) * BARS_PER_DAY - 1)
            d = p.days[i]
            sigma, smile, vix = self._day(i, leg.expiry)
            bars = p.bar[a : b + 1]
            m = self.model
            for key, spot, t in (
                ("open", p.open, bars - 1),
                ("sh", p.high, bars),
                ("sl", p.low, bars),
                ("close", p.close, bars),
            ):
                out[key][pos : pos + len(bars)] = m.price(
                    d, leg.expiry, spot[a : b + 1], leg.strike, leg.is_call, t, sigma, smile, vix
                )
            pos += len(bars)
        return out

    def quote(self, leg: Leg, at: int, field_: str = "open") -> float:
        return float(self.arrays(leg, at, at)[field_][0])


def simulate_options(
    name: str,
    index: str,
    pricer: LegPricer,
    legs: list[Leg],
    entry: int,
    exit_: int,
    lot: int,
    slip: Slippage,
    margin: float,
    leg_sl_pct: float | None = None,
    comb_sl: float | None = None,
    comb_tp: float | None = None,
    exit_signal: np.ndarray | None = None,
) -> Trade:
    """Simulate one multi-leg option position from bar ``entry`` to at most ``exit_``.

    ``comb_sl``/``comb_tp`` are ₹ amounts for the whole position; ``exit_signal`` is a
    boolean array over the path (True at a bar close → exit at the next bar's open).
    """
    path = pricer.path
    arrs = [pricer.arrays(leg, entry, exit_) for leg in legs]
    n = exit_ - entry + 1
    fills0 = []
    costs = 0.0
    slip_cost = 0.0
    entry_day = path.days[path.day_pos[entry]]
    exit_day_holder = [entry_day]

    def on(day: date) -> date | None:
        return day if slip.historical_rates else None

    for leg, a in zip(legs, arrs, strict=True):
        px = a["open"][0]
        fill = px - slip.option(px) if leg.qty < 0 else px + slip.option(px)
        fills0.append(max(fill, 0.05))
        slip_cost += slip.option(px) * abs(leg.qty) * lot
        costs += option_order_cost(
            fill, abs(leg.qty) * lot, "SELL" if leg.qty < 0 else "BUY", on(entry_day)
        )
    q = np.array([leg.qty * lot for leg in legs], dtype=float)
    p0 = np.array(fills0)
    open_ = np.ones(len(legs), dtype=bool)
    realized = 0.0
    reason = "time"
    exit_pos = n - 1  # relative bar index where remaining legs exit at open

    def leg_exit(j: int, px: float) -> float:
        nonlocal costs, slip_cost
        fill = px + slip.option(px) if legs[j].qty < 0 else max(px - slip.option(px), 0.05)
        slip_cost += abs(fill - px) * abs(legs[j].qty) * lot
        costs += option_order_cost(
            fill,
            abs(legs[j].qty) * lot,
            "BUY" if legs[j].qty < 0 else "SELL",
            on(exit_day_holder[0]),
        )
        return float(q[j] * (fill - p0[j]))

    # Per-leg stop trigger bars (relative), evaluated against the adverse extreme.
    leg_trig = np.full(len(legs), n, dtype=int)
    leg_level = np.zeros(len(legs))
    if leg_sl_pct is not None:
        for j, (leg, a) in enumerate(zip(legs, arrs, strict=True)):
            if leg.qty > 0:
                continue  # per-leg stops protect short legs only; hedges are held
            adverse = a["sh"] if leg.is_call else a["sl"]
            level = p0[j] * (1 + leg_sl_pct)
            hit = np.nonzero(adverse[: n - 1] >= level)[0]
            leg_level[j] = level
            if len(hit):
                leg_trig[j] = int(hit[0])

    sig_rel = n
    if exit_signal is not None:
        s = np.nonzero(exit_signal[entry:exit_])[0]
        if len(s):
            sig_rel = int(s[0]) + 1  # exit at the next bar's open

    t = 0
    daily: dict[date, float] = {}
    while True:
        open_idx: list[int] = np.nonzero(open_)[0].tolist()
        if len(open_idx) == 0:
            break
        nxt_leg = min((leg_trig[j], j) for j in open_idx)
        comb_t = n
        comb_kind = ""
        if comb_sl is not None or comb_tp is not None:
            sh = sum(q[j] * (arrs[j]["sh"] - p0[j]) for j in open_idx)
            sl_ = sum(q[j] * (arrs[j]["sl"] - p0[j]) for j in open_idx)
            cl = sum(q[j] * (arrs[j]["close"] - p0[j]) for j in open_idx)
            worst = realized + np.minimum(sh, sl_)
            best_close = realized + cl
            rng = np.arange(n)
            valid = (rng >= t) & (rng < n - 1)
            if comb_sl is not None:
                hit = np.nonzero(valid & (worst <= -comb_sl))[0]
                if len(hit):
                    comb_t, comb_kind = int(hit[0]), "comb_sl"
            if comb_tp is not None:
                hit = np.nonzero(valid & (best_close >= comb_tp))[0]
                if len(hit) and hit[0] < comb_t:
                    comb_t, comb_kind = int(hit[0]), "target"
        first = int(min(nxt_leg[0], comb_t, sig_rel, n - 1))
        exit_day_holder[0] = path.days[path.day_pos[entry + first]]
        if nxt_leg[0] == first and nxt_leg[0] < n - 1 and nxt_leg[0] <= comb_t:
            j = nxt_leg[1]
            a = arrs[j]
            if slip.sl_fill_worst:
                if legs[j].qty < 0:
                    px = (a["sh"] if legs[j].is_call else a["sl"])[first]
                else:
                    px = (a["sl"] if legs[j].is_call else a["sh"])[first]
            elif legs[j].qty < 0:
                px = max(leg_level[j], a["open"][first])
            else:
                px = min(leg_level[j], a["open"][first])
            realized += leg_exit(j, px)
            open_[j] = False
            reason = "leg_sl"
            t = first
            continue
        if comb_t == first and comb_t < n - 1:
            if comb_kind == "comb_sl":
                assert comb_sl is not None
                open_mtm = realized + sum(q[j] * (arrs[j]["open"][first] - p0[j]) for j in open_idx)
                if open_mtm <= -comb_sl:  # gapped through the stop
                    for j in open_idx:
                        realized += leg_exit(j, arrs[j]["open"][first])
                elif slip.sl_fill_worst:
                    worst_at = (
                        "sh"
                        if float(sum(q[j] * (arrs[j]["sh"][first] - p0[j]) for j in open_idx))
                        <= float(sum(q[j] * (arrs[j]["sl"][first] - p0[j]) for j in open_idx))
                        else "sl"
                    )
                    for j in open_idx:
                        realized += leg_exit(j, arrs[j][worst_at][first])
                else:
                    # Stop filled at its level: total P&L = −comb_sl, less exit slippage.
                    exit_slip = 0.0
                    for j in open_idx:
                        px = arrs[j]["close"][first]
                        leg_exit(j, px)  # books the exit order's charges
                        exit_slip += abs(q[j]) * slip.option(px)
                    realized = -comb_sl - exit_slip
                reason = "comb_sl"
            else:
                for j in open_idx:
                    realized += leg_exit(j, arrs[j]["close"][first])
                reason = "target"
            open_[open_idx] = False
            exit_pos = first
            break
        # Signal exit or time exit at the open of bar `first`.
        for j in open_idx:
            realized += leg_exit(j, arrs[j]["open"][first])
        open_[open_idx] = False
        reason = (
            "signal"
            if first == sig_rel and sig_rel < n - 1
            else (reason if reason == "leg_sl" else "time")
        )
        exit_pos = first
        break

    # Daily marks (cumulative P&L at each session close while the trade was open).
    last_day_i = path.day_pos[entry + exit_pos]
    for i in range(path.day_pos[entry], last_day_i):
        close_rel = (i + 1) * 375 - 1 - entry
        mark = sum(q[j] * (arrs[j]["close"][close_rel] - p0[j]) for j in range(len(legs)))
        daily[path.days[i]] = float(mark)
    return Trade(
        name,
        index,
        path.days[path.day_pos[entry]],
        path.days[last_day_i],
        float(realized),
        float(costs),
        reason,
        margin,
        len(legs),
        daily,
        lot=lot,
        entry_spot=float(path.open[entry]),
        fills=[(leg.strike, leg.is_call, leg.qty, float(p0[j])) for j, leg in enumerate(legs)],
        expiry=min(leg.expiry for leg in legs),
        orders=2 * len(legs),
        slippage=float(slip_cost),
    )


def simulate_futures(
    name: str,
    index: str,
    path: Path,
    signals: np.ndarray,
    lot: int,
    slip: Slippage,
    monthly_expiries: list[date],
    margin_pct: float = 0.12,
    carry: float = 0.053,
) -> list[Trade]:
    """Trade index futures from a target-position array (−1/0/+1 per bar, decided at the
    bar close → executed at the next bar's open).

    Futures are modelled as spot plus cost of carry: a long pays ``carry`` p.a. of notional
    while held (the futures premium decays to spot) and a short earns it. Positions held
    through a monthly expiry pay one roll (two orders + slippage).
    """
    trades: list[Trade] = []
    pos, entry_px, entry_i, costs = 0, 0.0, 0, 0.0
    sl = slip.futures(index)
    session_close = {
        i: float(path.close[(i + 1) * BARS_PER_DAY - 1]) for i in range(len(path.days))
    }

    def on(day: date) -> date | None:
        return day if slip.historical_rates else None

    def close_trade(i_exit: int, px: float) -> None:
        nonlocal costs
        fill = px - sl * pos
        d0, d1 = path.days[path.day_pos[entry_i]], path.days[path.day_pos[i_exit]]
        costs += futures_order_cost(fill, lot, "SELL" if pos > 0 else "BUY", on(d1))
        rolls = sum(1 for e in monthly_expiries if d0 <= e < d1)
        costs += rolls * (
            futures_order_cost(px, lot, "BUY", on(d1))
            + futures_order_cost(px, lot, "SELL", on(d1))
            + 2 * sl * lot
        )
        carry_cost = carry * entry_px * lot * (d1 - d0).days / 365 * pos
        gross = (fill - entry_px) * lot * pos - carry_cost
        marks = {
            path.days[k]: (session_close[k] - entry_px) * lot * pos
            for k in range(path.day_pos[entry_i], path.day_pos[i_exit])
        }
        trades.append(
            Trade(
                name,
                index,
                d0,
                d1,
                gross,
                costs,
                "signal",
                margin_pct * entry_px * lot,
                1,
                marks,
                lot=lot,
                entry_spot=entry_px,
                orders=2 + 4 * rolls,
            )
        )
        costs = 0.0

    for i in range(len(signals) - 1):
        target = int(signals[i])
        if target == pos:
            continue
        px = float(path.open[i + 1])
        if pos != 0:
            close_trade(i + 1, px)
        if target != 0:
            entry_px = px + sl * target
            entry_i = i + 1
            costs = futures_order_cost(
                entry_px, lot, "BUY" if target > 0 else "SELL", on(path.days[path.day_pos[i + 1]])
            )
        pos = target
    if pos != 0:
        close_trade(len(signals) - 1, float(path.close[-1]))
    return trades
