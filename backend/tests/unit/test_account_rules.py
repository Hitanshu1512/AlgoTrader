from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any

from app.backtesting.account import DisciplineRules, Signal, run_account
from app.backtesting.charges import Slippage
from app.backtesting.sim import Leg, Trade


def _sessions(start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _signal(d: date, risk: float, margin: float, index: str = "NIFTY") -> Signal:
    setup: Any = SimpleNamespace(
        name="test",
        index=index,
        expiry=d,
        entry_bar=105,
        lot=65,
        legs=[Leg(25000, True, -1, d), Leg(25000, False, -1, d)],
    )
    return Signal(setup=setup, margin_per_lot=margin, risk_per_lot=risk)


def _runner(outcomes: dict[date, float], seen: list[tuple[date, int, float | None]]):  # type: ignore[no-untyped-def]
    def run(sig: Signal, lots: int, comb: float | None) -> tuple[Trade, float, float]:
        d = sig.setup.expiry
        seen.append((d, lots, comb))
        net = outcomes[d] * lots
        if comb is not None and net < -comb:  # daily hard stop caps the loss
            net = -comb
        t = Trade("t", "NIFTY", d, d, net, 0.0, "time", 0.0, 2, orders=4)
        return t, net, 0.0

    return run


def test_one_lot_over_risk_budget_is_skipped() -> None:
    days = _sessions(date(2024, 9, 2), 1)
    res = run_account(
        {days[0]: [_signal(days[0], 1500, 20000)]},
        days,
        100_000,
        "disciplined",
        Slippage(),
        run_trade=_runner({}, []),
    )
    assert res.trades == []
    assert "risk limit" in res.journal[0]["reason"]


def test_lots_are_min_of_risk_and_margin_limits() -> None:
    days = _sessions(date(2024, 9, 2), 1)
    seen: list[tuple[date, int, float | None]] = []
    res = run_account(
        {days[0]: [_signal(days[0], 300, 25000)]},
        days,
        100_000,
        "disciplined",
        Slippage(),
        run_trade=_runner({days[0]: 100.0}, seen),
    )
    assert seen[0][1] == 2  # risk allows 3 lots, 60% margin cap allows 2
    assert seen[0][2] == 2000  # hard stop = 2% of the day's starting equity
    assert res.final == 100_200


def test_only_one_position_at_a_time() -> None:
    days = _sessions(date(2024, 9, 2), 1)
    sigs = {days[0]: [_signal(days[0], 300, 10000), _signal(days[0], 300, 10000, "BANKNIFTY")]}
    res = run_account(
        sigs, days, 100_000, "disciplined", Slippage(), run_trade=_runner({days[0]: 10.0}, [])
    )
    assert len(res.trades) == 1
    assert any("one position" in j["reason"] for j in res.journal)


def test_cooloff_after_three_losses() -> None:
    days = _sessions(date(2024, 9, 2), 6)
    sigs = {d: [_signal(d, 300, 10000)] for d in days}
    res = run_account(
        sigs,
        days,
        100_000,
        "disciplined",
        Slippage(),
        run_trade=_runner({d: -100.0 for d in days}, []),
    )
    taken = [t["entry"] for t in res.trades]
    assert taken == [d.isoformat() for d in (days[0], days[1], days[2], days[5])]
    assert res.cooloffs == 1


def test_drawdown_pause_rest_of_month_then_reduced_risk() -> None:
    days = _sessions(date(2024, 9, 9), 20)  # 9 Sep .. 4 Oct
    sigs = {d: [_signal(d, 100, 1000)] for d in days}
    outcomes = {d: (-600.0 if i < 6 else 0.0) for i, d in enumerate(days)}
    seen: list[tuple[date, int, float | None]] = []
    rules = DisciplineRules(loss_streak_for_cooloff=99)
    res = run_account(
        sigs,
        days,
        100_000,
        "disciplined",
        Slippage(),
        rules=rules,
        run_trade=_runner(outcomes, seen),
    )
    assert res.pauses == 1
    september = [s for s in seen if s[0].month == 9]
    october = [s for s in seen if s[0].month == 10]
    assert len(september) == 6  # each day capped at −2%; 6th loss breaches 10% → paused
    assert any("drawdown pause" in j["reason"] for j in res.journal)
    first_oct_equity = res.final  # no P&L after the losses
    assert october[0][1] == int(0.005 * first_oct_equity // 100)  # 0.5% risk until new high


def test_mechanical_takes_one_lot_when_margin_fits() -> None:
    days = _sessions(date(2024, 9, 2), 2)
    sigs = {days[0]: [_signal(days[0], 99999, 50000)], days[1]: [_signal(days[1], 1, 95000)]}
    seen: list[tuple[date, int, float | None]] = []
    res = run_account(
        sigs,
        days,
        100_000,
        "mechanical",
        Slippage(),
        run_trade=_runner({days[0]: 500.0, days[1]: 0.0}, seen),
    )
    assert [s[1] for s in seen] == [1]  # second needs 95k > 90% of equity → skipped
    assert res.final == 100_500
