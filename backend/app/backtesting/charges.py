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

BROKERAGE_PER_ORDER = 20.0
GST = 0.18
SEBI_FEE = 10.0 / 1e7

OPT_STT_SELL = 0.0015
OPT_EXCH = 0.0003503
OPT_STAMP_BUY = 0.00003

FUT_STT_SELL = 0.0005
FUT_EXCH = 0.0000173
FUT_STAMP_BUY = 0.00002


def option_order_cost(premium: float, qty: int, side: str) -> float:
    """All statutory charges + brokerage for one executed option order (₹)."""
    turnover = premium * qty
    exch = turnover * OPT_EXCH
    sebi = turnover * SEBI_FEE
    stt = turnover * OPT_STT_SELL if side == "SELL" else 0.0
    stamp = turnover * OPT_STAMP_BUY if side == "BUY" else 0.0
    gst = GST * (BROKERAGE_PER_ORDER + exch + sebi)
    return BROKERAGE_PER_ORDER + exch + sebi + stt + stamp + gst


def futures_order_cost(price: float, qty: int, side: str) -> float:
    turnover = price * qty
    exch = turnover * FUT_EXCH
    sebi = turnover * SEBI_FEE
    stt = turnover * FUT_STT_SELL if side == "SELL" else 0.0
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

    def option(self, price: float) -> float:
        return max(self.option_pct * price, self.option_min_points)

    def futures(self, index: str) -> float:
        pts = self.futures_points or {"NIFTY": 1.0, "BANKNIFTY": 3.0}
        return pts[index] * self.futures_mult
