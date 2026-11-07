"""Approximate NSE margin requirements for index F&O positions (per lot).

NSE margin = SPAN (worst-case scenario loss) + Extreme Loss Margin (ELM). SPAN files are
not part of our dataset, so this is a documented approximation:

* Naked short index options (straddle/strangle): SPAN ≈ 9% of notional (one side; the
  other side is offset) + ELM 2% of notional → ≈ 11%. Cross-check: for Nifty at lot 65,
  published 2026 figures of ₹1.6–1.9 lakh (normal day) and ₹2.0–2.3 lakh (expiry day) for a
  short ATM straddle are ≈ 10–12% / 13–14% of notional.
* Hedged (defined-risk) positions: SPAN ≈ min(maximum loss, naked SPAN); ELM still applies
  to the short legs (2% of notional, one side); premium paid for long legs must be funded.
* Additional ELM of 2% of notional on short options on their expiry day (SEBI, effective
  20 Nov 2024).
* Index futures: ≈ 11% of notional (SPAN + ELM).
* Full (NRML) margin is required for intraday trades as well (SEBI peak-margin rules, fully
  phased in by Sep 2021). Brokers' lower intraday margins before that are ignored, which is
  conservative for May 2020.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

SPAN_PCT = 0.09
ELM_PCT = 0.02
EXPIRY_ELM_PCT = 0.02
EXPIRY_ELM_FROM = date(2024, 11, 20)
FUTURES_PCT = 0.11


@dataclass(frozen=True)
class LegFill:
    strike: float
    is_call: bool
    qty: int  # +lots bought / −lots sold (per 1 strategy lot)
    price: float


def option_margin(legs: list[LegFill], spot: float, lot: int, on: date, expiry: date) -> float:
    """Margin (₹) to open one strategy lot of ``legs``."""
    notional = spot * lot
    shorts = [x for x in legs if x.qty < 0]
    longs = [x for x in legs if x.qty > 0]
    if not shorts:
        return sum(x.price * x.qty for x in longs) * lot
    sides = max(
        sum(-x.qty for x in shorts if x.is_call), sum(-x.qty for x in shorts if not x.is_call)
    )
    naked_span = SPAN_PCT * notional * sides
    span = naked_span
    if longs:
        credit = sum(-x.qty * x.price for x in legs)
        widths = []
        for is_call in (True, False):
            s = [x for x in shorts if x.is_call == is_call]
            hedge = [x for x in longs if x.is_call == is_call]
            if s and hedge:
                widths.append(max(abs(h.strike - x.strike) for x in s for h in hedge))
            elif s:
                widths.append(float("inf"))  # an unhedged side keeps the naked SPAN
        max_loss = (max(widths) - credit) * lot if widths else 0.0
        span = min(max(max_loss, 0.0), naked_span)
    elm = ELM_PCT * notional * sides
    if on >= EXPIRY_ELM_FROM and on == expiry:
        elm += EXPIRY_ELM_PCT * notional * sides
    long_premium = sum(x.price * x.qty for x in longs) * lot
    return span + elm + long_premium


def futures_margin(price: float, lot: int) -> float:
    return FUTURES_PCT * price * lot
