"""End-of-day option backtesting on **real traded NSE option prices** (bhavcopies).

Every price used here was actually printed on NSE: daily open / high / low / close (and
the exchange settlement price) of each option contract, with its traded volume and the
contract's exchange lot size on that date. Nothing is modelled except slippage.

Execution conventions (conservative, no look-ahead):

* A signal is computed from data known at the **close of day t** (underlying close, option
  closes, previous volume). The trade is entered at the **open of day t+1** at each leg's
  actual opening price, plus slippage. A leg that did not trade on the entry day, or whose
  strike traded fewer than ``min_contracts`` on day t, cannot be filled → missed trade.
* Single-leg long options: stop-loss / target are checked against the option's actual
  daily low / high. A day that touches both is booked as a stop. A gap through a level
  fills at the open.
* Multi-leg positions: checked once a day at the close (a person checking at ~15:15) and
  closed at that close. ``stress=True`` instead triggers stops on the adverse intraday
  extremes of all legs at once (long legs at their low, short legs at their high) and
  fills there, which is a worst-case bound.
* Positions still open are closed at the close of their exit day (at the latest, expiry day:
  squared off before 15:30 rather than left to exercise).
* Charges: brokerage, STT, exchange, SEBI, stamp duty and GST at the rates in force on each
  order's date. Margin: ``margin.option_margin`` (SPAN + ELM approximation).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np
import pandas as pd
from scipy.special import ndtr

from app.backtesting.charges import fixed_cost_per_order, option_order_cost
from app.backtesting.margin import LegFill, option_margin

STEP = {"NIFTY": 50.0, "BANKNIFTY": 100.0, "FINNIFTY": 50.0}
# Lot sizes NSE has used for these indices; values inferred from legacy files are snapped.
VALID_LOTS = (15, 20, 25, 30, 35, 40, 50, 60, 65, 75)


def snap_lot(x: float) -> float:
    if not np.isfinite(x) or x <= 0:
        return float("nan")
    return float(min(VALID_LOTS, key=lambda v: abs(v - x)))


@dataclass(frozen=True)
class Slip:
    """Adverse fill vs the printed price, per leg per order: max(pct × price, min_points)."""

    pct: float = 0.01
    min_points: float = 0.20

    def of(self, px: float) -> float:
        return max(self.pct * px, self.min_points)


@dataclass
class Chain:
    """All option rows of one underlying, indexed for fast lookups."""

    symbol: str
    days: list[date]
    rows: dict[
        tuple[date, date, float, str], tuple[float, float, float, float, float, float, float]
    ]
    expiries: dict[date, list[date]]  # trading day → listed expiries (sorted)
    strikes: dict[tuple[date, date], np.ndarray]  # (day, expiry) → strikes (sorted)
    fwd: dict[tuple[date, date], float]  # (day, expiry) → put-call-parity forward at close
    atm_iv: dict[tuple[date, date], float]  # (day, expiry) → ATM implied vol at close
    bars: pd.DataFrame  # daily underlying bars: open, high, low, close (nearest-expiry forward)
    day_ix: dict[date, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.day_ix = {d: i for i, d in enumerate(self.days)}

    def quote(self, d: date, e: date, k: float, opt: str) -> tuple[float, ...] | None:
        return self.rows.get((d, e, k, opt))

    def nearest_expiry(self, d: date, min_days: int = 0) -> date | None:
        """Nearest listed expiry at least ``min_days`` trading days after ``d``."""
        i = self.day_ix[d]
        for e in self.expiries.get(d, []):
            if e < d:
                continue
            n = sum(1 for x in self.days[i : i + 40] if x <= e) - 1
            if n >= min_days:
                return e
        return None

    def trading_days_to(self, d: date, e: date) -> int:
        i = self.day_ix[d]
        return sum(1 for x in self.days[i : i + 60] if x <= e) - 1

    def strike_near(self, d: date, e: date, target: float) -> float | None:
        ks = self.strikes.get((d, e))
        if ks is None or not len(ks):
            return None
        return float(ks[np.argmin(np.abs(ks - target))])

    def strike_by_delta(self, d: date, e: date, delta: float, is_call: bool) -> float | None:
        f, iv = self.fwd.get((d, e)), self.atm_iv.get((d, e))
        ks = self.strikes.get((d, e))
        if f is None or iv is None or ks is None or not np.isfinite(iv):
            return None
        t = max((e - d).days, 0.5) / 365.0
        sd = iv * math.sqrt(t)
        d1 = (np.log(f / ks) + 0.5 * sd * sd) / sd
        dl = ndtr(d1) if is_call else ndtr(d1) - 1.0
        side = ks > f if is_call else ks < f
        if not side.any():
            return None
        cand = ks[side]
        return float(cand[np.argmin(np.abs(np.abs(dl[side]) - delta))])


# ───────────────────────── loading ─────────────────────────


def load_chain(eod: pd.DataFrame, symbol: str, max_days: int = 45, band: float = 0.10) -> Chain:
    df = eod[(eod["symbol"] == symbol) & (eod["inst"] == "OPT")].copy()
    df["dte"] = (pd.to_datetime(df["expiry"]) - pd.to_datetime(df["date"])).dt.days
    df = df[(df["dte"] >= 0) & (df["dte"] <= max_days)]
    # Put-call parity forward per (day, expiry) from the strike where |C − P| is smallest.
    piv = df.pivot_table(
        index=["date", "expiry", "strike"], columns="opt", values="close", aggfunc="first"
    ).dropna()
    vol = df.pivot_table(
        index=["date", "expiry", "strike"], columns="opt", values="contracts", aggfunc="first"
    ).reindex(piv.index)
    piv = piv[(vol["CE"] > 0) & (vol["PE"] > 0)]
    piv = piv.assign(diff=(piv["CE"] - piv["PE"]).abs())
    best = piv.loc[piv.groupby(level=[0, 1])["diff"].idxmin()]
    fwd_s = best.index.get_level_values(2) + best["CE"] - best["PE"]
    fwd = {(d, e): float(v) for (d, e, _k), v in fwd_s.items()}
    # ATM implied vol (average of call and put at the parity strike).
    atm_iv: dict[tuple[date, date], float] = {}
    for (d, e, k), r in best.iterrows():
        f = fwd[(d, e)]
        t = max((e - d).days, 0.5) / 365.0
        ivs = []
        for px, is_call in ((r["CE"], True), (r["PE"], False)):
            lo, hi = 1e-3, 3.0
            for _ in range(50):
                mid = 0.5 * (lo + hi)
                sd = mid * math.sqrt(t)
                d1 = (math.log(f / k) + 0.5 * sd * sd) / sd
                d2 = d1 - sd
                p = f * ndtr(d1) - k * ndtr(d2) if is_call else k * ndtr(-d2) - f * ndtr(-d1)
                if p > px:
                    hi = mid
                else:
                    lo = mid
            ivs.append(0.5 * (lo + hi))
        atm_iv[(d, e)] = float(np.mean(ivs))
    # Keep strikes within ±band of the forward.
    df["f"] = [fwd.get((d, e), np.nan) for d, e in zip(df["date"], df["expiry"], strict=True)]
    df = df[(df["strike"] - df["f"]).abs() <= band * df["f"]]
    rows = {
        (r.date, r.expiry, float(r.strike), r.opt): (
            float(r.open),
            float(r.high),
            float(r.low),
            float(r.close),
            float(r.settle),
            float(r.contracts),
            snap_lot(float(r.lot)),
        )
        for r in df.itertuples()
    }
    expiries: dict[date, list[date]] = {}
    strikes: dict[tuple[date, date], np.ndarray] = {}
    for (d, e), g in df.groupby(["date", "expiry"]):
        expiries.setdefault(d, []).append(e)
        strikes[(d, e)] = np.sort(g["strike"].unique().astype(float))
    for d in expiries:
        expiries[d].sort()
    days = sorted(expiries)
    # Daily underlying bars: nearest-expiry forward close; open/high/low from the near-month
    # future scaled to that forward (removes the futures basis).
    fut = eod[(eod["symbol"] == symbol) & (eod["inst"] == "FUT")].copy()
    fut = fut.sort_values(["date", "expiry"]).groupby("date").first()
    recs = []
    for d in days:
        e = next((x for x in expiries[d] if (d, x) in fwd), None)
        if e is None or d not in fut.index:
            continue
        c = fwd[(d, e)]
        fr = fut.loc[d]
        s = c / float(fr["close"]) if fr["close"] > 0 else 1.0
        recs.append((d, fr["open"] * s, fr["high"] * s, fr["low"] * s, c))
    bars = pd.DataFrame(recs, columns=["date", "open", "high", "low", "close"]).set_index("date")
    days = [d for d in days if d in bars.index]
    return Chain(symbol, days, rows, expiries, strikes, fwd, atm_iv, bars)


# ───────────────────────── simulation ─────────────────────────


@dataclass(frozen=True)
class OptLeg:
    strike: float
    opt: str  # "CE" / "PE"
    qty: int  # +1 bought / −1 sold (per strategy lot)


@dataclass
class EodTrade:
    strategy: str
    symbol: str
    signal_day: date
    entry_day: date
    exit_day: date
    expiry: date
    legs: list[OptLeg]
    entry_px: list[float]
    exit_px: list[float]
    lot: int
    gross_per_lot: float  # ₹ per lot after slippage, before charges
    var_cost_per_lot: float  # quantity-proportional charges per lot
    orders: int
    margin_per_lot: float
    planned_risk_per_lot: float  # loss if the stop is hit at its level
    max_loss_per_lot: float  # worst case for defined-risk structures (debit / width − credit)
    exit_reason: str
    days_held: int
    entry_value: float  # net premium per unit (+ debit paid / − credit received)
    marks: dict[date, float] = field(default_factory=dict)  # per-lot open P&L at each close

    def net(self, lots: int = 1) -> float:
        return (
            lots * (self.gross_per_lot - self.var_cost_per_lot)
            - self.orders * fixed_cost_per_order()
        )


@dataclass(frozen=True)
class ExitRules:
    stop: float | None = (
        None  # debit: exit if value ≤ (1−stop)·debit; credit: if cost ≥ (1+stop)·credit
    )
    target: float | None = None  # debit: value ≥ (1+target)·debit; credit: cost ≤ (1−target)·credit
    max_days: int = 99  # trading days after entry (exit at that close)
    exit_before_expiry: int = 0  # trading days before expiry to exit (0 = on expiry day)


def _px(q: tuple[float, ...] | None, field_: str) -> float | None:
    if q is None:
        return None
    o, h, lo, c, s, n, _lot = q
    if field_ == "open":
        return o if n > 0 and o > 0 else None
    if field_ == "close":
        return c if n > 0 and c > 0 else (s if s > 0 else None)
    if field_ == "high":
        return h if n > 0 and h > 0 else (s if s > 0 else None)
    if field_ == "low":
        return lo if n > 0 and lo > 0 else (s if s > 0 else None)
    raise ValueError(field_)


def _all_px(qs: list[tuple[float, ...] | None], field_: str) -> list[float] | None:
    out = [_px(q, field_) for q in qs]
    vals = [x for x in out if x is not None]
    return vals if len(vals) == len(out) else None


def simulate(
    ch: Chain,
    name: str,
    signal_day: date,
    expiry: date,
    legs: list[OptLeg],
    rules: ExitRules,
    slip: Slip,
    min_contracts: float = 100.0,
    stress: bool = False,
) -> EodTrade | str:
    """Simulate one position. Returns an EodTrade, or the reason it could not be entered."""
    i0 = ch.day_ix[signal_day]
    if i0 + 1 >= len(ch.days):
        return "no next day"
    entry = ch.days[i0 + 1]
    if entry > expiry:
        return "expired"
    for leg in legs:
        q0 = ch.quote(signal_day, expiry, leg.strike, leg.opt)
        if q0 is None or q0[5] < min_contracts:
            return "illiquid strike"
    fills, lot = [], 0
    for leg in legs:
        q = ch.quote(entry, expiry, leg.strike, leg.opt)
        o = _px(q, "open")
        if o is None or q is None:
            return "leg did not trade at entry"
        lot = int(q[6]) if np.isfinite(q[6]) else 0
        s = slip.of(o)
        fills.append(o + s if leg.qty > 0 else max(o - s, 0.05))
    if lot <= 0:
        return "unknown lot"
    entry_value = sum(leg.qty * p for leg, p in zip(legs, fills, strict=True))  # + debit / − credit
    debit = entry_value > 0
    base = abs(entry_value)
    single = len(legs) == 1
    # Exit schedule.
    last_ix = min(i0 + 1 + rules.max_days, len(ch.days) - 1)
    exp_ix = max(j for j, d in enumerate(ch.days) if d <= expiry)
    last_ix = min(last_ix, exp_ix - rules.exit_before_expiry)
    last_ix = max(last_ix, i0 + 1)
    exit_px: list[float] | None = None
    reason = "time"
    marks: dict[date, float] = {}
    j = i0 + 1
    for j in range(i0 + 1, last_ix + 1):
        d = ch.days[j]
        qs = [ch.quote(d, expiry, leg.strike, leg.opt) for leg in legs]
        cl = _all_px(qs, "close")
        if cl is not None:
            marks[d] = lot * sum(
                leg.qty * (c - e) for leg, c, e in zip(legs, cl, fills, strict=True)
            )
        if single and debit:
            q = qs[0]
            lo, hi, op = _px(q, "low"), _px(q, "high"), _px(q, "open")
            if lo is not None and hi is not None:
                stop_lv = base * (1 - rules.stop) if rules.stop is not None else None
                tgt_lv = base * (1 + rules.target) if rules.target is not None else None
                if j > i0 + 1 and op is not None:
                    if stop_lv is not None and op <= stop_lv:
                        exit_px, reason = [op], "stop (gap)"
                        break
                    if tgt_lv is not None and op >= tgt_lv:
                        exit_px, reason = [op], "target (gap)"
                        break
                if stop_lv is not None and lo <= stop_lv:
                    exit_px, reason = [stop_lv], "stop"
                    break
                if tgt_lv is not None and hi >= tgt_lv:
                    exit_px, reason = [tgt_lv], "target"
                    break
        else:
            closes = _all_px(qs, "close")
            if closes is None:
                continue
            value = sum(leg.qty * c for leg, c in zip(legs, closes, strict=True))
            if stress and rules.stop is not None:
                adv_raw = [
                    _px(q, "low" if leg.qty > 0 else "high")
                    for leg, q in zip(legs, qs, strict=True)
                ]
                adv = [a for a in adv_raw if a is not None]
                if len(adv) == len(legs):
                    adv_value = sum(leg.qty * a for leg, a in zip(legs, adv, strict=True))
                    hit = (
                        adv_value <= base * (1 - rules.stop)
                        if debit
                        else -adv_value >= base * (1 + rules.stop)
                    )
                    if hit:
                        exit_px, reason = adv, "stop (intraday worst)"
                        break
            if rules.stop is not None:
                hit = (
                    value <= base * (1 - rules.stop) if debit else -value >= base * (1 + rules.stop)
                )
                if hit:
                    exit_px, reason = [c for c in closes], "stop"
                    break
            if rules.target is not None:
                hit = (
                    value >= base * (1 + rules.target)
                    if debit
                    else -value <= base * (1 - rules.target)
                )
                if hit:
                    exit_px, reason = [c for c in closes], "target"
                    break
    if exit_px is None:
        d = ch.days[last_ix]
        j = last_ix
        exit_px = []
        for leg in legs:
            c = _px(ch.quote(d, expiry, leg.strike, leg.opt), "close")
            if c is None:  # untraded and no settlement price: worthless if OTM at expiry
                f = ch.fwd.get((d, expiry)) or float(ch.bars["close"].get(d, np.nan))
                c = max(0.0, (f - leg.strike) if leg.opt == "CE" else (leg.strike - f))
            exit_px.append(c)
        reason = "expiry" if ch.days[last_ix] == expiry else "time"
    exit_day = ch.days[j]
    # Exit slippage and P&L.
    exits = []
    for leg, p in zip(legs, exit_px, strict=True):
        s = slip.of(p)
        exits.append(max(p - s, 0.0) if leg.qty > 0 else p + s)
    gross_unit = sum(leg.qty * (x - e) for leg, e, x in zip(legs, fills, exits, strict=True))
    var = 0.0
    fixed = fixed_cost_per_order()
    for leg, e, x in zip(legs, fills, exits, strict=True):
        var += option_order_cost(e, lot, "BUY" if leg.qty > 0 else "SELL", entry) - fixed
        if x > 0:
            var += option_order_cost(x, lot, "SELL" if leg.qty > 0 else "BUY", exit_day) - fixed
    orders = len(legs) + sum(1 for x in exits if x > 0)
    f0 = ch.fwd.get((signal_day, expiry), float(ch.bars["close"].get(signal_day, np.nan)))
    lf = [
        LegFill(leg.strike, leg.opt == "CE", leg.qty, p) for leg, p in zip(legs, fills, strict=True)
    ]
    margin = max(
        option_margin(lf, f0, lot, entry, expiry), option_margin(lf, f0, lot, expiry, expiry)
    )
    if debit:
        max_loss = base
        planned = base * (rules.stop if rules.stop is not None else 1.0)
    else:
        widths = []
        for opt in ("CE", "PE"):
            sh = [leg.strike for leg in legs if leg.opt == opt and leg.qty < 0]
            lg = [leg.strike for leg in legs if leg.opt == opt and leg.qty > 0]
            if sh and lg:
                widths.append(max(abs(a - b) for a in sh for b in lg))
            elif sh:
                widths.append(float("inf"))
        max_loss = (max(widths) - base) if widths else float("inf")
        planned = min(base * (rules.stop if rules.stop is not None else 99.0), max_loss)
    return EodTrade(
        name,
        ch.symbol,
        signal_day,
        entry,
        exit_day,
        expiry,
        legs,
        fills,
        exits,
        lot,
        gross_unit * lot,
        var,
        orders,
        margin,
        planned * lot,
        max_loss * lot,
        reason,
        j - (i0 + 1),
        entry_value,
        marks,
    )


# ───────────────────────── account ─────────────────────────


@dataclass(frozen=True)
class AccountRules:
    risk_per_trade: float = 0.01  # planned loss per trade, fraction of equity
    min_lot_risk_cap: float | None = None  # allow 1 lot if its planned risk ≤ this fraction
    max_positions: int = 2
    margin_cap: float = 0.70  # total margin of open positions ≤ this × equity
    daily_loss: float = 0.02  # no new entries after this loss in a day (realised)
    dd_pause: float = 0.15  # pause new entries for 10 sessions at this drawdown from peak
    pause_days: int = 10
    max_lots: int = 50
    miss_rate: float = 0.10  # human execution: share of valid signals not taken
    seed: int = 7
    allow_undefined_risk: bool = False  # allow positions without a defined maximum loss
    hard_stop_dd: float | None = None  # stop trading for good at this drawdown from peak


def run_account(
    trades: list[EodTrade], capital: float, rules: AccountRules, days: list[date]
) -> dict[str, Any]:
    """Chronological account with concurrent positions, compounding through position size."""
    rng = np.random.default_rng(rules.seed)
    by_entry: dict[date, list[EodTrade]] = {}
    for t in sorted(trades, key=lambda x: (x.entry_day, x.symbol, x.strategy)):
        by_entry.setdefault(t.entry_day, []).append(t)
    equity = peak = hi_water = capital
    open_pos: list[tuple[EodTrade, int]] = []
    log: list[dict[str, Any]] = []
    curve: list[tuple[date, float]] = []
    pause_until = -1
    paused_once = False
    stopped = False
    max_dd = 0.0
    skipped: dict[str, int] = {}
    day_loss: dict[date, float] = {}

    def skip(r: str) -> None:
        skipped[r] = skipped.get(r, 0) + 1

    for di, d in enumerate(days):
        # Settle positions whose exit day has passed (realised at their exit close).
        still = []
        for t, lots in open_pos:
            if t.exit_day < d:
                net = t.net(lots)
                equity += net
                day_loss[t.exit_day] = day_loss.get(t.exit_day, 0.0) + min(net, 0.0)
                log.append(_row(t, lots, net, equity))
            else:
                still.append((t, lots))
        open_pos = still
        if paused_once and di == pause_until + 1:
            peak = equity  # review done: resume, measuring drawdown from here
            paused_once = False
        if equity <= (1 - rules.dd_pause) * peak and di > pause_until:
            pause_until = di + rules.pause_days
            paused_once = True
        if rules.hard_stop_dd is not None and equity <= (1 - rules.hard_stop_dd) * hi_water:
            stopped = True
        for t in by_entry.get(d, []):
            if stopped:
                skip("hard stop: maximum drawdown reached")
                continue
            if di <= pause_until:
                skip("drawdown pause")
                continue
            if rng.random() < rules.miss_rate:
                skip("missed by trader")
                continue
            if len(open_pos) >= rules.max_positions:
                skip("max positions")
                continue
            prev = days[di - 1] if di else d
            if day_loss.get(prev, 0.0) <= -rules.daily_loss * equity:
                skip("daily loss limit (previous session)")
                continue
            if any(o.symbol == t.symbol and o.strategy == t.strategy for o, _ in open_pos):
                skip("already in this trade")
                continue
            budget = rules.risk_per_trade * equity
            lots = math.floor(budget / t.planned_risk_per_lot) if t.planned_risk_per_lot > 0 else 0
            if lots < 1 and rules.min_lot_risk_cap is not None:
                lots = 1 if t.planned_risk_per_lot <= rules.min_lot_risk_cap * equity else 0
            if lots < 1:
                skip("risk limit: 1 lot too big")
                continue
            used = sum(o.margin_per_lot * n for o, n in open_pos)
            lots = min(
                lots,
                rules.max_lots,
                math.floor((rules.margin_cap * equity - used) / t.margin_per_lot),
            )
            if lots < 1:
                skip("margin limit")
                continue
            if not rules.allow_undefined_risk and t.max_loss_per_lot * lots > equity:
                skip("max loss above equity")
                continue
            open_pos.append((t, lots))
        mtm = equity + sum(n * _mark(o, d) for o, n in open_pos)
        peak = max(peak, mtm)
        hi_water = max(hi_water, mtm)
        max_dd = max(max_dd, 1 - mtm / hi_water)
        curve.append((d, mtm))
    for t, lots in open_pos:
        net = t.net(lots)
        equity += net
        log.append(_row(t, lots, net, equity))
    if curve:
        curve[-1] = (curve[-1][0], equity)
    return {"final": equity, "max_dd": max_dd, "log": log, "curve": curve, "skipped": skipped}


def _mark(t: EodTrade, d: date) -> float:
    if d in t.marks:
        return t.marks[d]
    past = [k for k in t.marks if k <= d]
    return t.marks[max(past)] if past else 0.0


def _row(t: EodTrade, lots: int, net: float, equity: float) -> dict[str, Any]:
    return {
        "strategy": t.strategy,
        "symbol": t.symbol,
        "signal": t.signal_day.isoformat(),
        "entry": t.entry_day.isoformat(),
        "exit": t.exit_day.isoformat(),
        "expiry": t.expiry.isoformat(),
        "legs": "; ".join(f"{'B' if x.qty > 0 else 'S'} {x.strike:.0f}{x.opt}" for x in t.legs),
        "entry_px": [round(p, 2) for p in t.entry_px],
        "exit_px": [round(p, 2) for p in t.exit_px],
        "lot": t.lot,
        "lots": lots,
        "margin": round(t.margin_per_lot * lots, 2),
        "planned_risk": round(t.planned_risk_per_lot * lots, 2),
        "net": round(net, 2),
        "reason": t.exit_reason,
        "equity_after": round(equity, 2),
    }


StrategyFn = Callable[..., list[EodTrade]]
