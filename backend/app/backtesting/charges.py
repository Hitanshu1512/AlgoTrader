"""Indian exchange-traded F&O transaction costs (rates in force from 1 April 2026).

Applied to *every* period of the backtest so results reflect what trading costs today.

| Item | Options | Futures |
|---|---|---|
| Brokerage (Upstox) | ₹20 per executed order | ₹20 per executed order |
| STT | 0.15% of premium, sell side | 0.05% of value, sell side |
| NSE transaction charge | 0.03503% of premium | 0.00173% of value |
| SEBI turnover fee | ₹10 per crore | ₹10 per crore |
| Stamp duty | 0.003% of premium, buy side | 0.002% of value, buy side |
| GST | 18% on brokerage + exchange + SEBI fees | same |

Slippage is modelled separately (see ``Slippage``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

BROKERAGE_PER_ORDER = 20.0
GST = 0.18
SEBI_FEE = 10.0 / 1e7

OPT_STT_SELL = 0.0015
OPT_EXCH = 0.0003503
OPT_STAMP_BUY = 0.00003

FUT_STT_SELL = 0.0005
FUT_EXCH = 0.0000173
FUT_STAMP_BUY = 0.00002


@dataclass(frozen=True)
class Rates:
    opt_stt_sell: float
    opt_exch: float
    fut_stt_sell: float
    fut_exch: float


CURRENT = Rates(OPT_STT_SELL, OPT_EXCH, FUT_STT_SELL, FUT_EXCH)

# Rates in force on a trade date (for historical backtests). STT changes are statutory
# (Finance Acts 2023, 2024, 2026). Before Oct 2024 NSE's option transaction charge varied
# between ~0.0495% and 0.053% of premium; the higher value is used (conservative).
_SCHEDULE: list[tuple[date, Rates]] = [
    (date(2016, 6, 1), Rates(0.0005, 0.00053, 0.0001, 0.00002)),
    (date(2023, 4, 1), Rates(0.000625, 0.00053, 0.000125, 0.00002)),
    (date(2024, 10, 1), Rates(0.001, 0.0003503, 0.0002, 0.0000173)),
    (date(2026, 4, 1), CURRENT),
]


def rates_on(on: date | None) -> Rates:
    if on is None:
        return CURRENT
    current = _SCHEDULE[0][1]
    for start, r in _SCHEDULE:
        if on >= start:
            current = r
    return current


def fixed_cost_per_order() -> float:
    """The part of each order's cost that does not scale with quantity (brokerage + GST)."""
    return BROKERAGE_PER_ORDER * (1 + GST)


def option_order_cost(premium: float, qty: int, side: str, on: date | None = None) -> float:
    """All statutory charges + brokerage for one executed option order (₹).

    ``on`` selects the rates in force on that date; ``None`` = current (Apr 2026) rates.
    """
    r = rates_on(on)
    turnover = premium * qty
    exch = turnover * r.opt_exch
    sebi = turnover * SEBI_FEE
    stt = turnover * r.opt_stt_sell if side == "SELL" else 0.0
    stamp = turnover * OPT_STAMP_BUY if side == "BUY" else 0.0
    gst = GST * (BROKERAGE_PER_ORDER + exch + sebi)
    return BROKERAGE_PER_ORDER + exch + sebi + stt + stamp + gst


def futures_order_cost(price: float, qty: int, side: str, on: date | None = None) -> float:
    r = rates_on(on)
    turnover = price * qty
    exch = turnover * r.fut_exch
    sebi = turnover * SEBI_FEE
    stt = turnover * r.fut_stt_sell if side == "SELL" else 0.0
    stamp = turnover * FUT_STAMP_BUY if side == "BUY" else 0.0
    gst = GST * (BROKERAGE_PER_ORDER + exch + sebi)
    return BROKERAGE_PER_ORDER + exch + sebi + stt + stamp + gst


@dataclass(frozen=True)
class Slippage:
    """Adverse fill vs model price: max(pct × price, min_points) per option fill."""

    option_pct: float = 0.005
    option_min_points: float = 0.10
    futures_points: dict[str, float] | None = None
    # Stress mode: a triggered stop fills at the worst price seen in that minute.
    sl_fill_worst: bool = False
    futures_mult: float = 1.0
    # Charge rates in force on each trade date (True) or today's rates for all dates (False).
    historical_rates: bool = False

    def option(self, price: float) -> float:
        return max(self.option_pct * price, self.option_min_points)

    def futures(self, index: str) -> float:
        pts = self.futures_points or {"NIFTY": 1.0, "BANKNIFTY": 3.0}
        return pts[index] * self.futures_mult
