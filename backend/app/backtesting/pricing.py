"""Option pricing for index F&O research.

Black-76 on the forward ``F = S·exp((r−q)·T)`` with a parametric volatility smile anchored
to India VIX:

    σ(K) = σ_ATM · clip(1 + s1·x + s2·x², 0.6, 2.5),   x = ln(K/F) / (σ_ATM·√T)

* σ_ATM for NIFTY = India VIX interpolated linearly from the day's open to its close.
* σ_ATM for BANKNIFTY = NIFTY σ_ATM × the trailing 60-day realized-volatility ratio
  BANKNIFTY/NIFTY (computed from *previous* closes only — no look-ahead).
* s1, s2 (skew, convexity) are calibrated on a real NSE bhavcopy; see research/calibrate.py.

This is a model, not market data: it captures time decay, gamma and VIX-level effects of
the real index path, but not bid/ask, intraday IV spikes or event-specific pricing.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.special import ndtr

RISK_FREE = 0.065
DIV_YIELD = {"NIFTY": 0.012, "BANKNIFTY": 0.008}
MIN_T = 1.0 / (365 * 24 * 60)  # one minute, avoids division by zero at expiry
TICK = 0.05


@dataclass(frozen=True)
class Smile:
    s1: float  # negative → puts (low strikes) richer than calls
    s2: float  # positive → wings richer than ATM

    def multiplier(self, x: np.ndarray) -> np.ndarray:
        return np.asarray(np.clip(1.0 + self.s1 * x + self.s2 * x * x, 0.6, 2.5))


# Calibrated on NSE bhavcopy 05-Jan-2024 (research/calibrate.py); overwritten if recalibrated.
SMILES: dict[str, Smile] = {"NIFTY": Smile(-0.08, 0.025), "BANKNIFTY": Smile(-0.08, 0.025)}


def forward(index: str, spot: np.ndarray | float, t: np.ndarray | float) -> np.ndarray:
    return np.asarray(np.asarray(spot) * np.exp((RISK_FREE - DIV_YIELD[index]) * np.asarray(t)))


def black76(
    f: np.ndarray,
    k: np.ndarray | float,
    t: np.ndarray | float,
    sigma: np.ndarray | float,
    is_call: bool,
) -> np.ndarray:
    f = np.asarray(f, dtype=float)
    t = np.maximum(np.asarray(t, dtype=float), MIN_T)
    sigma = np.maximum(np.asarray(sigma, dtype=float), 1e-4)
    vol = sigma * np.sqrt(t)
    d1 = (np.log(f / k) + 0.5 * vol * vol) / vol
    d2 = d1 - vol
    disc = np.exp(-RISK_FREE * t)
    if is_call:
        price = disc * (f * ndtr(d1) - k * ndtr(d2))
    else:
        price = disc * (k * ndtr(-d2) - f * ndtr(-d1))
    return np.asarray(np.maximum(price, TICK / 2))


def smile_iv(index: str, f: np.ndarray, k: float, t: np.ndarray, atm: np.ndarray) -> np.ndarray:
    t = np.maximum(t, MIN_T)
    x = np.log(k / f) / (atm * np.sqrt(t))
    return np.asarray(atm * SMILES[index].multiplier(x))


def option_price(
    index: str, spot: np.ndarray, k: float, t: np.ndarray, atm_iv: np.ndarray, is_call: bool
) -> np.ndarray:
    f = forward(index, spot, t)
    return black76(f, k, t, smile_iv(index, f, k, t, atm_iv), is_call)


def black76_sd(
    f: np.ndarray | float,
    k: np.ndarray | float,
    sd: np.ndarray | float,
    disc: np.ndarray | float,
    is_call: bool | np.ndarray,
) -> np.ndarray:
    """Black-76 parameterised by total standard deviation ``sd = σ·√T``."""
    f = np.asarray(f, dtype=float)
    sd = np.maximum(np.asarray(sd, dtype=float), 1e-6)
    d1 = (np.log(f / k) + 0.5 * sd * sd) / sd
    d2 = d1 - sd
    call = disc * (f * ndtr(d1) - k * ndtr(d2))
    put = disc * (k * ndtr(-d2) - f * ndtr(-d1))
    return np.asarray(np.maximum(np.where(is_call, call, put), TICK / 2))


def implied_sd(
    price: np.ndarray, f: float, k: np.ndarray, is_call: np.ndarray, disc: float, iters: int = 60
) -> np.ndarray:
    """Vectorised bisection for total standard deviation; NaN where no solution."""
    lo = np.full(len(k), 1e-4)
    hi = np.full(len(k), 1.5)
    p_lo = black76_sd(f, k, lo, disc, is_call)
    p_hi = black76_sd(f, k, hi, disc, is_call)
    valid = (price > p_lo) & (price < p_hi)
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        too_high = black76_sd(f, k, mid, disc, is_call) > price
        hi = np.where(too_high, mid, hi)
        lo = np.where(too_high, lo, mid)
    return np.where(valid, 0.5 * (lo + hi), np.nan)


def implied_vol(price: float, f: float, k: float, t: float, is_call: bool) -> float | None:
    """Bisection inverse of Black-76 (for calibration only)."""
    lo, hi = 1e-3, 3.0
    if price <= float(black76(np.array(f), k, t, lo, is_call)):
        return None
    if price >= float(black76(np.array(f), k, t, hi, is_call)):
        return None
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if float(black76(np.array(f), k, t, mid, is_call)) > price:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)
