"""Volatility surface for index options, anchored to real NSE closing prices.

For each trading day *d* and expiry *E*, the bhavcopy of *d* gives the market's ATM
total variance ``w = σ²·T`` and smile ``(s1, s2)`` (see ``build_surfaces``). Options are
then priced on day *d+1* using **only day-d information** plus the intraday India VIX move:

    total_sd(t) = sqrt(w_d / τ_d) · (VIX(t) / VIX_close(d)) · sqrt(τ(t))

``τ`` is a *variance clock* measured in trading sessions: every trading minute counts
1/375, each overnight between sessions counts ``overnight_w`` and every non-trading
calendar day (weekend/holiday) counts ``closed_day_w``. The weights are chosen empirically
(research/validate_pricing.py) by how well day-d surfaces predict day-(d+1) closing prices.

Where no surface exists (before Apr 2020 or a missing day) a VIX-based fallback is used:
σ_ATM = k_index · VIX, with k_index the median market/VIX ratio measured 2020–2025.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd
from scipy.special import ndtr

from app.backtesting.data import BARS_PER_DAY
from app.backtesting.pricing import DIV_YIELD, RISK_FREE, Smile, black76_sd, implied_sd


@dataclass
class Clock:
    sessions: list[date]
    overnight_w: float = 0.3
    closed_day_w: float = 0.3
    _pos: dict[date, int] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.sessions = sorted(self.sessions)
        self._pos = {d: i for i, d in enumerate(self.sessions)}

    def _sessions_between(self, d: date, e: date) -> tuple[int, int]:
        """(# sessions in (d, e], # closed calendar days in (d, e))."""
        i = bisect.bisect_right(self.sessions, d)
        j = bisect.bisect_right(self.sessions, e)
        n_sess = j - i
        closed = (e - d).days - n_sess
        return n_sess, max(closed, 0)

    def tau(self, d: date, e: date, bar_close_idx: np.ndarray | int) -> np.ndarray:
        """Variance-clock time from the close of bar ``bar_close_idx`` on ``d`` to E 15:30."""
        rest_today = (BARS_PER_DAY - 1 - np.asarray(bar_close_idx, dtype=float)) / BARS_PER_DAY
        if e <= d:
            return np.maximum(rest_today, 0.0) if e == d else np.zeros_like(rest_today)
        n_sess, closed = self._sessions_between(d, e)
        return rest_today + n_sess * (1 + self.overnight_w) + closed * self.closed_day_w


def calendar_years(d: date, e: date, bar_close_idx: np.ndarray | int) -> np.ndarray:
    """Calendar time in years (for discounting / forward only)."""
    minutes_left_today = BARS_PER_DAY - 1 - np.asarray(bar_close_idx, dtype=float)
    return np.maximum(((e - d).days * 1440 + minutes_left_today) / (365 * 1440), 0.0)


@dataclass(frozen=True)
class DayVol:
    open_rel: float  # VIX open / previous VIX close
    s_open: float  # index open of the day
    beta: float
    resid: float

    def mult(self, spot: np.ndarray, bar_close_idx: np.ndarray) -> np.ndarray:
        frac = (np.asarray(bar_close_idx, dtype=float) + 1) / BARS_PER_DAY
        spot_term = (
            -self.beta * np.log(np.asarray(spot, dtype=float) / self.s_open)
            if self.s_open > 0
            else 0.0
        )
        return np.asarray(self.open_rel * np.exp(spot_term + self.resid * frac))


@dataclass(frozen=True)
class Surface:
    w: float  # ATM total variance at the close of `day` for `expiry`
    tau: float  # clock time at that close
    smile: Smile
    vix_close: float


def build_surfaces(
    eod: pd.DataFrame, spot_close: dict[str, dict[date, float]], min_contracts: int = 50
) -> pd.DataFrame:
    """Fit ATM total variance and smile per (symbol, day, expiry) from bhavcopy closes."""
    rows = []
    opts = eod[(eod["inst"] == "OPT") & (eod["contracts"] >= min_contracts) & (eod["close"] >= 0.5)]
    for (sym, d, e), g in opts.groupby(["symbol", "date", "expiry"], sort=False):
        if e <= d or (e - d).days > 70:
            continue
        s = spot_close[sym].get(d)
        if s is None:
            continue
        t = (e - d).days / 365
        f = s * np.exp((RISK_FREE - DIV_YIELD[sym]) * t)
        k = g["strike"].to_numpy(float)
        call = (g["opt"] == "CE").to_numpy()
        otm = (call & (k >= f)) | (~call & (k <= f))
        k, call, px = k[otm], call[otm], g["close"].to_numpy(float)[otm]
        near = np.abs(np.log(k / f)) < 0.08
        k, call, px = k[near], call[near], px[near]
        if len(k) < 6 or k.min() > f or k.max() < f:
            continue
        sd = implied_sd(px, f, k, call, np.exp(-RISK_FREE * t))
        ok = np.isfinite(sd)
        k, sd = k[ok], sd[ok]
        if len(k) < 6:
            continue
        order = np.argsort(k)
        k, sd = k[order], sd[order]
        atm_sd = float(np.interp(f, k, sd))
        x = np.log(k / f) / atm_sd
        y = sd / atm_sd - 1
        m = np.abs(x) <= 3
        if m.sum() < 5:
            continue
        s1, s2 = np.linalg.lstsq(np.c_[x[m], x[m] ** 2], y[m], rcond=None)[0]
        rows.append((sym, d, e, atm_sd**2, float(s1), float(s2), int(m.sum()), atm_sd / np.sqrt(t)))
    return pd.DataFrame(
        rows, columns=["symbol", "date", "expiry", "w", "s1", "s2", "n", "atm_iv_cal"]
    )


class VolModel:
    """Look-ahead-free option pricer for one index."""

    def __init__(
        self,
        index: str,
        surfaces: pd.DataFrame,
        vix: pd.DataFrame,
        clock: Clock,
        fallback_k: float,
        fallback_smile: Smile,
        spot_vol_beta: float = 0.0,
        day_open: dict[date, float] | None = None,
        day_close: dict[date, float] | None = None,
    ) -> None:
        self.index = index
        self.beta = spot_vol_beta
        # Stress knob: on expiry day, IV ramps up linearly to (1 + ramp) by the close,
        # i.e. options hold premium later into the day than the base model assumes.
        self.expiry_iv_ramp = 0.0
        self.expiry_ramp_start_bar = 0  # ramp begins here (set to the strategy's entry bar)
        self._day_open = day_open or {}
        self._day_close = day_close or {}
        self.clock = clock
        self.vix = vix
        self.fallback_k = fallback_k
        self.fallback_smile = fallback_smile
        sub = surfaces[surfaces["symbol"] == index]
        self._surf: dict[tuple[date, date], tuple[float, float, float]] = {
            (r.date, r.expiry): (r.w, r.s1, r.s2) for r in sub.itertuples()
        }
        self._vix_dates = list(vix.index)
        self.fallback_used = 0
        self.surface_used = 0

    def _vix_close(self, d: date) -> float:
        i = bisect.bisect_right(self._vix_dates, d) - 1
        return float(self.vix["close"].iloc[max(i, 0)])

    def _vix_open(self, d: date) -> float:
        if d in self.vix.index:
            return float(self.vix.at[d, "open"])
        return self._vix_close(d - timedelta(days=1))

    def prev_session(self, d: date) -> date:
        i = bisect.bisect_left(self.clock.sessions, d)
        return self.clock.sessions[max(i - 1, 0)]

    def anchor(self, d: date, e: date) -> tuple[float, Smile]:
        """(σ per clock-unit, smile) known at the open of ``d`` for expiry ``e``."""
        p = self.prev_session(d)
        hit = self._surf.get((p, e))
        if hit is not None:
            w, s1, s2 = hit
            tau_p = float(self.clock.tau(p, e, BARS_PER_DAY - 1))
            if tau_p > 0:
                self.surface_used += 1
                return float(np.sqrt(w / tau_p)), Smile(s1, s2)
        self.fallback_used += 1
        # VIX is calendar-annualised; convert to clock units via 252 sessions ≈ 1 year.
        sigma_clock = (
            self.fallback_k
            * self._vix_close(p)
            / 100
            / np.sqrt(252 * (1 + self.clock.overnight_w) + 113 * self.clock.closed_day_w)
        )
        return float(sigma_clock), self.fallback_smile

    def vix_path(self, d: date) -> DayVol:
        """Intraday volatility multiplier context for day ``d``.

        mult(S, t) = VIX_open/VIX_prev · exp(−β·ln(S/S_open) + resid·t/375)

        The spot term reproduces the spot–vol effect (IV rises as the index falls, also
        inside a bar when pricing at its low); ``resid`` makes the multiplier end the day at
        the actual VIX close.
        """
        prev = self._vix_close(self.prev_session(d))
        o, c = self._vix_open(d), self._vix_close(d)
        s_open = self._day_open.get(d)
        s_close = self._day_close.get(d)
        r_close = np.log(s_close / s_open) if s_open and s_close else 0.0
        resid = float(np.log(c / o) + self.beta * r_close)
        return DayVol(o / prev, float(s_open or 0.0), self.beta, resid)

    def price(
        self,
        d: date,
        e: date,
        spot: np.ndarray,
        k: np.ndarray | float,
        is_call: bool,
        bar_close_idx: np.ndarray,
        sigma: float,
        smile: Smile,
        vix_ext: DayVol,
    ) -> np.ndarray:
        """Model price at the close of ``bar_close_idx`` (−1 = the session open)."""
        bar_close_idx = np.asarray(bar_close_idx)
        tau = self.clock.tau(d, e, bar_close_idx)
        t_cal = calendar_years(d, e, bar_close_idx)
        f = np.asarray(spot, dtype=float) * np.exp((RISK_FREE - DIV_YIELD[self.index]) * t_cal)
        atm_sd = sigma * vix_ext.mult(spot, bar_close_idx) * np.sqrt(tau)
        if self.expiry_iv_ramp and e == d:
            start = self.expiry_ramp_start_bar
            frac = np.clip((bar_close_idx + 1 - start) / (BARS_PER_DAY - start), 0.0, 1.0)
            atm_sd = atm_sd * (1 + self.expiry_iv_ramp * frac)
        x = np.log(k / f) / np.maximum(atm_sd, 1e-6)
        sd = atm_sd * smile.multiplier(x)
        intrinsic = np.maximum(f - k, 0) if is_call else np.maximum(k - f, 0)
        px = black76_sd(f, k, sd, np.exp(-RISK_FREE * t_cal), is_call)
        return np.where(tau <= 0, intrinsic, px)

    def delta(
        self,
        d: date,
        e: date,
        spot: float,
        k: np.ndarray,
        is_call: bool,
        bar_close_idx: int,
        sigma: float,
        smile: Smile,
        vix_ext: DayVol,
    ) -> np.ndarray:
        tau = float(self.clock.tau(d, e, bar_close_idx))
        t_cal = float(calendar_years(d, e, bar_close_idx))
        f = spot * np.exp((RISK_FREE - DIV_YIELD[self.index]) * t_cal)
        atm_sd = float(
            sigma
            * vix_ext.mult(np.array([spot]), np.array([bar_close_idx]))[0]
            * np.sqrt(max(tau, 1e-9))
        )
        sd = atm_sd * smile.multiplier(np.log(k / f) / max(atm_sd, 1e-6))
        d1 = (np.log(f / k) + 0.5 * sd * sd) / np.maximum(sd, 1e-6)
        disc = np.exp(-RISK_FREE * t_cal)
        return np.asarray(disc * (ndtr(d1) if is_call else ndtr(d1) - 1))
