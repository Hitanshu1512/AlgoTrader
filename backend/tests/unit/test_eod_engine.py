from datetime import date, timedelta

import pandas as pd

from app.backtesting.eod import (
    AccountRules,
    ExitRules,
    OptLeg,
    Slip,
    load_chain,
    run_account,
    simulate,
)
from app.backtesting.margin import LegFill, option_margin

D0 = date(2024, 1, 1)  # Monday
DAYS = [D0 + timedelta(days=i) for i in range(5)]
EXP = DAYS[-1]


def _rows(prices: dict[tuple[float, str], list[tuple[float, float, float, float]]]) -> pd.DataFrame:
    out = []
    for (k, opt), bars in prices.items():
        for d, (o, h, lo, c) in zip(DAYS, bars, strict=True):
            out.append(
                (d, "NIFTY", "OPT", EXP, k, opt, o, h, lo, c, c, 1000.0, 1e5, float("nan"), 25.0)
            )
    for d in DAYS:
        out.append(
            (
                d,
                "NIFTY",
                "FUT",
                EXP,
                0.0,
                "",
                22000,
                22100,
                21900,
                22000,
                22000,
                1e4,
                1e5,
                float("nan"),
                25.0,
            )
        )
    return pd.DataFrame(
        out,
        columns=[
            "date",
            "symbol",
            "inst",
            "expiry",
            "strike",
            "opt",
            "open",
            "high",
            "low",
            "close",
            "settle",
            "contracts",
            "oi",
            "underlying",
            "lot",
        ],
    )


def _chain(extra: dict[tuple[float, str], list[tuple[float, float, float, float]]] | None = None):
    flat = [(100.0, 105.0, 95.0, 100.0)] * 5
    prices = {(22000.0, "CE"): flat, (22000.0, "PE"): flat}
    prices.update(extra or {})
    return load_chain(_rows(prices), "NIFTY")


def test_parity_forward_and_entry_at_next_open() -> None:
    ch = _chain()
    assert abs(ch.fwd[(DAYS[0], EXP)] - 22000.0) < 1e-6
    t = simulate(ch, "t", DAYS[0], EXP, [OptLeg(22000.0, "CE", 1)], ExitRules(), Slip(0.0, 0.0))
    assert not isinstance(t, str)
    assert t.entry_day == DAYS[1] and t.entry_px == [100.0]
    assert t.exit_day == EXP and t.exit_reason == "expiry"


def test_long_option_stop_on_real_low_and_gap_fill() -> None:
    bars = [
        (100, 105, 95, 100),
        (100, 102, 90, 95),
        (70, 72, 60, 65),
        (65, 66, 60, 62),
        (60, 61, 0.5, 1),
    ]
    ch = _chain({(22100.0, "CE"): bars})
    t = simulate(
        ch, "t", DAYS[0], EXP, [OptLeg(22100.0, "CE", 1)], ExitRules(stop=0.4), Slip(0.0, 0.0)
    )
    assert not isinstance(t, str)
    # Entered at 100 on day 1; day 2 opens at 70 (above the 60 stop) and trades down to 60.
    assert t.exit_reason == "stop" and t.exit_px == [60.0]
    assert t.gross_per_lot == (60.0 - 100.0) * 25


def test_credit_spread_close_based_stop_and_defined_max_loss() -> None:
    short = [
        (50, 55, 45, 50),
        (50, 60, 45, 55),
        (55, 140, 50, 130),
        (130, 140, 120, 135),
        (135, 150, 100, 150),
    ]
    long_ = [
        (20, 22, 18, 20),
        (20, 24, 18, 22),
        (22, 70, 20, 65),
        (65, 70, 60, 66),
        (66, 80, 50, 80),
    ]
    ch = _chain({(21900.0, "PE"): short, (21800.0, "PE"): long_})
    legs = [OptLeg(21900.0, "PE", -1), OptLeg(21800.0, "PE", 1)]
    t = simulate(ch, "t", DAYS[0], EXP, legs, ExitRules(stop=1.0), Slip(0.0, 0.0))
    assert not isinstance(t, str)
    assert t.entry_value == -30.0  # credit received
    assert t.exit_reason == "stop" and t.exit_day == DAYS[2]  # cost 65 ≥ 2 × 30
    assert t.max_loss_per_lot == (100 - 30) * 25
    assert t.planned_risk_per_lot == 30 * 25


def test_debit_spread_margin_is_premium_plus_elm() -> None:
    legs = [LegFill(22000, True, 1, 100.0), LegFill(22200, True, -1, 40.0)]
    m = option_margin(legs, 22000.0, 25, DAYS[0], EXP)
    assert m == 0.02 * 22000 * 25 + 60.0 * 25


def test_account_respects_risk_limit_and_compounds() -> None:
    ch = _chain()
    t = simulate(
        ch, "t", DAYS[0], EXP, [OptLeg(22000.0, "CE", 1)], ExitRules(stop=0.5), Slip(0.0, 0.0)
    )
    assert not isinstance(t, str)
    strict = run_account([t], 100_000.0, AccountRules(risk_per_trade=0.01, miss_rate=0.0), ch.days)
    assert strict["skipped"] == {"risk limit: 1 lot too big": 1}  # 1 lot risks 1,250 > 1,000
    loose = run_account(
        [t],
        100_000.0,
        AccountRules(risk_per_trade=0.01, min_lot_risk_cap=0.02, miss_rate=0.0),
        ch.days,
    )
    assert len(loose["log"]) == 1 and loose["log"][0]["lots"] == 1
