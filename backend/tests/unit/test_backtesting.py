from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from app.backtesting.calendar import ExpiryCalendar
from app.backtesting.charges import Slippage, futures_order_cost, option_order_cost
from app.backtesting.data import BARS_PER_DAY, DayBars
from app.backtesting.metrics import summarize
from app.backtesting.pricing import Smile, black76_sd, implied_sd
from app.backtesting.sim import Leg, LegPricer, Path, simulate_options
from app.backtesting.vol import Clock, VolModel

HOLIDAYS = {date(2024, 1, 26), date(2024, 11, 15), date(2024, 12, 25), date(2025, 10, 21)}


def sessions(start: date, end: date) -> list[date]:
    out, d = [], start
    while d <= end:
        if d.weekday() < 5 and d not in HOLIDAYS:
            out.append(d)
        d += timedelta(days=1)
    return out


DAYS = sessions(date(2023, 6, 1), date(2025, 12, 31))


@pytest.mark.parametrize(
    ("index", "on", "expected"),
    [
        ("NIFTY", date(2024, 1, 5), date(2024, 1, 11)),  # weekly Thursday
        ("NIFTY", date(2024, 11, 12), date(2024, 11, 14)),  # normal Thursday expiry
        ("NIFTY", date(2025, 9, 1), date(2025, 9, 2)),  # Tuesday expiry from Sep 2025
        ("NIFTY", date(2025, 10, 15), date(2025, 10, 20)),  # Tue 21 Oct holiday → Mon 20
        ("BANKNIFTY", date(2024, 1, 5), date(2024, 1, 10)),  # weekly Wednesday
        ("BANKNIFTY", date(2024, 11, 14), date(2024, 11, 27)),  # weeklies discontinued
        ("BANKNIFTY", date(2024, 12, 2), date(2024, 12, 24)),  # last Wed 25 Dec holiday
        ("BANKNIFTY", date(2025, 1, 1), date(2025, 1, 30)),  # monthly last Thursday
        ("BANKNIFTY", date(2025, 9, 1), date(2025, 9, 30)),  # monthly last Tuesday
    ],
)
def test_expiry_calendar(index: str, on: date, expected: date) -> None:
    assert ExpiryCalendar(index, DAYS).nearest(on) == expected


def test_no_weekly_contract_in_monthly_expiry_week() -> None:
    # Verified against NSE bhavcopies: Bank Nifty Sep 2023 – Feb 2024 had no Wednesday weekly
    # in the week of the (Thursday) monthly expiry.
    cal = ExpiryCalendar("BANKNIFTY", DAYS)
    for fake, real in (
        (date(2023, 10, 25), date(2023, 10, 26)),
        (date(2023, 11, 29), date(2023, 11, 30)),
        (date(2024, 2, 28), date(2024, 2, 29)),
    ):
        assert not cal.is_expiry(fake)
        assert cal.nearest(fake - timedelta(days=1)) == real


def test_option_charges_breakdown() -> None:
    # ₹100 premium × 65 qty = ₹6,500 turnover.
    sell = option_order_cost(100, 65, "SELL")
    buy = option_order_cost(100, 65, "BUY")
    exch, sebi = 6500 * 0.0003503, 6500 * 10 / 1e7
    gst = 0.18 * (20 + exch + sebi)
    assert sell == pytest.approx(20 + exch + sebi + 6500 * 0.0015 + gst)
    assert buy == pytest.approx(20 + exch + sebi + 6500 * 0.00003 + gst)


def test_futures_stt_is_sell_side_only() -> None:
    notional = 25000 * 65
    diff = futures_order_cost(25000, 65, "SELL") - futures_order_cost(25000, 65, "BUY")
    assert diff == pytest.approx(notional * (0.0005 - 0.00002))


def test_black76_put_call_parity_and_inverse() -> None:
    f, k, sd, disc = 25000.0, np.array([24500.0, 25000.0, 25500.0]), 0.02, 0.999
    c = black76_sd(f, k, sd, disc, True)
    p = black76_sd(f, k, sd, disc, False)
    np.testing.assert_allclose(c - p, disc * (f - k), atol=1e-6)
    back = implied_sd(c, f, k, np.array([True] * 3), disc)
    np.testing.assert_allclose(back, sd, rtol=1e-4)


def test_smile_multiplier_is_clipped() -> None:
    m = Smile(-0.05, 0.05).multiplier(np.array([-50.0, 0.0, 50.0]))
    assert m[1] == 1.0 and m.max() <= 2.5 and m.min() >= 0.6


def test_clock_decreases_and_hits_zero_at_expiry_close() -> None:
    clock = Clock(DAYS, 0.3, 0.3)
    d, e = date(2024, 1, 8), date(2024, 1, 11)
    taus = clock.tau(d, e, np.arange(BARS_PER_DAY))
    assert np.all(np.diff(taus) < 0)
    assert float(clock.tau(e, e, BARS_PER_DAY - 1)) == 0.0
    # Friday close → Thursday expiry spans a weekend (2 closed days) and 4 sessions.
    fri = float(clock.tau(date(2024, 1, 5), e, BARS_PER_DAY - 1))
    assert fri == pytest.approx(4 * 1.3 + 2 * 0.3)


def _flat_day(d: date, spot: float, spike_at: int | None = None, spike: float = 0.0) -> DayBars:
    close = np.full(BARS_PER_DAY, spot)
    if spike_at is not None:
        close[spike_at:] = spot * (1 + spike)
    o = np.r_[spot, close[:-1]]
    return DayBars(d, o, np.maximum(o, close), np.minimum(o, close), close, 0)


def _model(days: list[date]) -> VolModel:
    vix = pd.DataFrame({"open": 15.0, "close": 15.0}, index=days)
    return VolModel(
        "NIFTY",
        pd.DataFrame(columns=["symbol", "date", "expiry", "w", "s1", "s2"]),
        vix,
        Clock(days, 0.3, 0.3),
        1.0,
        Smile(0.0, 0.0),
    )


def test_short_straddle_decays_profitably_in_a_flat_market() -> None:
    d = date(2024, 1, 11)  # expiry day
    model = _model(DAYS)
    path = Path.from_days([_flat_day(d, 21500.0)])
    legs = [Leg(21500, True, -1, d), Leg(21500, False, -1, d)]
    t = simulate_options(
        "t", "NIFTY", LegPricer(model, path), legs, 5, 360, 65, Slippage(), 1.0, leg_sl_pct=0.5
    )
    assert t.exit_reason == "time"
    assert t.gross > 0 and t.net < t.gross


def test_per_leg_stop_triggers_on_a_spike() -> None:
    d = date(2024, 1, 11)
    model = _model(DAYS)
    path = Path.from_days([_flat_day(d, 21500.0, spike_at=120, spike=0.01)])
    pricer = LegPricer(model, path)
    call = Leg(21500, True, -1, d)
    entry = pricer.quote(call, 5)
    t = simulate_options("t", "NIFTY", pricer, [call], 5, 360, 65, Slippage(), 1.0, leg_sl_pct=0.5)
    assert t.exit_reason == "leg_sl"
    # Loss ≈ 50% of premium + slippage (gap through the stop fills at the bar open).
    assert t.gross < -0.5 * entry * 65 * 0.9


def test_summarize_drawdown() -> None:
    from app.backtesting.sim import Trade

    days = DAYS[:4]
    trades = [
        Trade("t", "NIFTY", days[i], days[i], g, 0.0, "time", 100.0, 1)
        for i, g in enumerate([100.0, -300.0, 50.0, 400.0])
    ]
    r = summarize(trades, days)
    assert r["net_pnl"] == 250.0
    assert r["max_drawdown"] == 300.0
    assert r["win_rate_pct"] == 75.0
