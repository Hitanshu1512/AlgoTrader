from datetime import date

import numpy as np

from app.backtesting.calendar import ExpiryCalendar
from app.backtesting.charges import Slippage
from app.backtesting.data import BARS_PER_DAY, DayBars
from app.backtesting.sim import Leg, LegPricer, Path, simulate_options
from app.backtesting.strategies.buying import (
    _cross_dn,
    _cross_up,
    pdh_pdl_breakout,
    rsi,
    run_events,
    supertrend_direction,
)
from app.backtesting.strategies.fno import Ctx
from research.buying_account import run_account, scaled_net
from tests.unit.test_backtesting import DAYS, _flat_day, _model


def _trend_day(d: date, start: float, end: float) -> DayBars:
    close = np.linspace(start, end, BARS_PER_DAY)
    o = np.r_[start, close[:-1]]
    return DayBars(d, o, np.maximum(o, close), np.minimum(o, close), close, 0)


def _ctx(days: list[date], bars: dict[date, DayBars]) -> Ctx:
    return Ctx(
        index="NIFTY",
        sessions=days,
        bars=bars,
        cal=ExpiryCalendar("NIFTY", DAYS),
        model=_model(DAYS),
        lot=65,
        step=50,
    )


def test_cross_helpers_fire_once() -> None:
    a = np.array([1.0, 2.0, 3.0, 2.0, 1.0])
    assert _cross_up(a, 2.5).tolist() == [False, False, True, False, False]
    assert _cross_dn(a, 2.5).tolist() == [False, False, False, True, False]


def test_rsi_and_supertrend_follow_the_trend() -> None:
    up = np.linspace(100, 200, 200)
    assert rsi(up)[-1] > 90
    d = supertrend_direction(up + 0.5, up - 0.5, up)
    assert d[-1] == 1
    down = up[::-1]
    assert supertrend_direction(down + 0.5, down - 0.5, down)[-1] == -1


def test_long_call_stop_caps_loss_at_premium_fraction() -> None:
    d = date(2024, 1, 10)
    path = Path.from_days([_flat_day(d, 21500.0, spike_at=120, spike=-0.01)])
    pricer = LegPricer(_model(DAYS), path)
    leg = Leg(21500, True, 1, date(2024, 1, 11))
    prem = pricer.quote(leg, 5)
    t = simulate_options(
        "t", "NIFTY", pricer, [leg], 5, 360, 65, Slippage(), prem * 65, comb_sl=0.3 * prem * 65
    )
    assert t.exit_reason == "comb_sl"
    assert t.exit_bar == 120
    # A buyer can never lose more than the premium paid (plus charges).
    assert -prem * 65 <= t.gross < -0.3 * prem * 65 * 0.9


def test_pdh_breakout_buys_a_call_on_a_trend_day() -> None:
    d0, d1 = date(2024, 1, 8), date(2024, 1, 9)
    bars = {d0: _flat_day(d0, 21500.0), d1: _trend_day(d1, 21490.0, 21800.0)}
    trades = pdh_pdl_breakout(_ctx([d0, d1], bars))
    assert len(trades) == 1
    t = trades[0]
    assert t.entry_day == d1 and t.fills[0][1] is True  # call
    assert t.net > 0


def test_run_events_one_position_at_a_time_and_reversal() -> None:
    d = date(2024, 1, 9)
    bars = {d: _flat_day(d, 21500.0)}
    long_ev = [np.zeros(BARS_PER_DAY, dtype=bool)]
    short_ev = [np.zeros(BARS_PER_DAY, dtype=bool)]
    long_ev[0][[20, 30]] = True  # second long arrives while the first is open → ignored
    short_ev[0][100] = True  # reversal: closes the long and opens a put
    trades = run_events(
        _ctx([d], bars), "t", long_ev, short_ev, exit_long=short_ev, exit_short=long_ev
    )
    assert [t.fills[0][1] for t in trades] == [True, False]
    assert trades[0].exit_bar == 101 and trades[0].exit_reason == "signal"


def test_account_compounding_and_blow_up() -> None:
    from app.backtesting.sim import Trade

    days = DAYS[:5]
    losers = [
        Trade("t", "NIFTY", d, d, -9_000.0, 50.0, "comb_sl", 9_000.0, 1, orders=2) for d in days
    ]
    r = run_account(losers, 25_000.0, "1 lot", None)
    assert r["trades_taken"] == 2 and r["blown_on"] is not None
    assert scaled_net(losers[0], 2) == 2 * -9_000.0 - (2 * (50.0 - 47.2) + 47.2)
