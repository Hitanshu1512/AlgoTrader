from datetime import date

import pytest

from app.backtesting.charges import fixed_cost_per_order, option_order_cost, rates_on
from app.backtesting.margin import LegFill, futures_margin, option_margin
from research.sample_months import ELIGIBLE, draw


def test_stt_schedule_follows_finance_acts() -> None:
    assert rates_on(date(2022, 5, 10)).opt_stt_sell == 0.0005
    assert rates_on(date(2023, 4, 1)).opt_stt_sell == 0.000625
    assert rates_on(date(2024, 10, 1)).opt_stt_sell == 0.001
    assert rates_on(date(2026, 4, 1)).opt_stt_sell == 0.0015
    assert rates_on(date(2024, 9, 30)).fut_stt_sell == 0.000125


def test_cost_is_fixed_plus_proportional() -> None:
    one = option_order_cost(100, 65, "SELL", date(2025, 6, 5))
    two = option_order_cost(100, 130, "SELL", date(2025, 6, 5))
    fixed = fixed_cost_per_order()
    assert two - fixed == pytest.approx(2 * (one - fixed))


def test_naked_straddle_margin_includes_expiry_elm_after_nov_2024() -> None:
    legs = [LegFill(25000, True, -1, 100.0), LegFill(25000, False, -1, 100.0)]
    normal = option_margin(legs, 25000, 65, date(2026, 1, 5), date(2026, 1, 6))
    expiry = option_margin(legs, 25000, 65, date(2026, 1, 6), date(2026, 1, 6))
    old_expiry = option_margin(legs, 20000, 50, date(2023, 2, 23), date(2023, 2, 23))
    assert normal == pytest.approx(0.11 * 25000 * 65)
    assert expiry == pytest.approx(0.13 * 25000 * 65)
    assert old_expiry == pytest.approx(0.11 * 20000 * 50)  # no extra ELM before 20 Nov 2024


def test_hedged_margin_uses_max_loss_plus_elm_plus_wing_premium() -> None:
    legs = [
        LegFill(25000, True, -1, 100.0),
        LegFill(25000, False, -1, 100.0),
        LegFill(25200, True, 1, 30.0),
        LegFill(24800, False, 1, 30.0),
    ]
    m = option_margin(legs, 25000, 65, date(2026, 1, 5), date(2026, 1, 6))
    credit = 200 - 60
    assert m == pytest.approx((200 - credit) * 65 + 0.02 * 25000 * 65 + 60 * 65)
    naked = option_margin(legs[:2], 25000, 65, date(2026, 1, 5), date(2026, 1, 6))
    assert m < naked


def test_futures_margin() -> None:
    assert futures_margin(25000, 65) == pytest.approx(0.11 * 25000 * 65)


def test_month_sample_is_fixed_and_eligible() -> None:
    a, b = draw(), draw()
    assert a == b  # deterministic seed
    assert set(a) == set(range(2020, 2027))
    assert all(m in ELIGIBLE[y] for y, m in a.items())
