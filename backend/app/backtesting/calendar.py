"""NSE index-derivative expiry schedules, including historical rule changes.

Sources (see docs/research/fno_strategy_backtest.md for links):
* Nifty weekly options launched Feb 2019 (Thursday expiry).
* Bank Nifty weekly expiry: Thursday (2016) → Wednesday (Sep 2023) → discontinued after
  13 Nov 2024 (SEBI: one weekly benchmark per exchange). Bank Nifty monthly expiry moved to
  the last Wednesday for Mar–Dec 2024, back to Thursday from Jan 2025.
* From 1 Sep 2025 NSE expiries moved to Tuesday (weekly Nifty, monthly Bank Nifty).
A scheduled expiry that falls on a holiday moves to the previous trading day.
"""

from __future__ import annotations

import bisect
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

MON, TUE, WED, THU, FRI = 0, 1, 2, 3, 4


@dataclass(frozen=True)
class ExpiryRule:
    kind: str  # "weekly" | "monthly"
    weekday: int
    start: date  # rule applies to scheduled expiry dates in [start, end]
    end: date | None


RULES: dict[str, list[ExpiryRule]] = {
    "NIFTY": [
        ExpiryRule("monthly", THU, date(2000, 1, 1), date(2025, 8, 31)),
        ExpiryRule("weekly", THU, date(2019, 2, 11), date(2025, 8, 31)),
        ExpiryRule("monthly", TUE, date(2025, 9, 1), None),
        ExpiryRule("weekly", TUE, date(2025, 9, 1), None),
    ],
    "BANKNIFTY": [
        ExpiryRule("monthly", THU, date(2000, 1, 1), date(2024, 2, 29)),
        ExpiryRule("weekly", THU, date(2016, 5, 27), date(2023, 9, 3)),
        ExpiryRule("weekly", WED, date(2023, 9, 4), date(2024, 11, 13)),
        ExpiryRule("monthly", WED, date(2024, 3, 1), date(2024, 12, 31)),
        ExpiryRule("monthly", THU, date(2025, 1, 1), date(2025, 8, 31)),
        ExpiryRule("monthly", TUE, date(2025, 9, 1), None),
    ],
}

# Strike intervals used for ATM/OTM strike selection.
STRIKE_STEP = {"NIFTY": 50, "BANKNIFTY": 100}
# Exchange lot sizes in force since the January 2026 series (NSE circular FAOP70616).
LOT_SIZE = {"NIFTY": 65, "BANKNIFTY": 30}


def _last_weekday(year: int, month: int, weekday: int) -> date:
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    d = nxt - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _scheduled(rule: ExpiryRule, first: date, last: date) -> Iterable[date]:
    lo = max(rule.start, first)
    hi = min(rule.end or last, last)
    if lo > hi:
        return []
    out: list[date] = []
    if rule.kind == "weekly":
        d = lo + timedelta(days=(rule.weekday - lo.weekday()) % 7)
        while d <= hi:
            out.append(d)
            d += timedelta(days=7)
    else:
        y, m = lo.year, lo.month
        while date(y, m, 1) <= hi:
            d = _last_weekday(y, m, rule.weekday)
            if lo <= d <= hi:
                out.append(d)
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def expiry_dates(index: str, trading_days: Sequence[date]) -> list[date]:
    """All expiries for ``index`` within the span of ``trading_days``, holiday-adjusted."""
    days = sorted(trading_days)
    if not days:
        return []
    first, last = days[0], days[-1] + timedelta(days=40)
    tset = set(days)
    out: set[date] = set()
    for rule in RULES[index]:
        for d in _scheduled(rule, first, last):
            adj = d
            if d <= days[-1]:
                while adj not in tset and adj >= first:
                    adj -= timedelta(days=1)
                if adj < first:
                    continue
            out.add(adj)
    return sorted(out)


class ExpiryCalendar:
    def __init__(self, index: str, trading_days: Sequence[date]) -> None:
        self.index = index
        self.expiries = expiry_dates(index, trading_days)

    def nearest(self, d: date, min_days: int = 0) -> date:
        """First expiry on/after ``d + min_days`` calendar days."""
        i = bisect.bisect_left(self.expiries, d + timedelta(days=min_days))
        return self.expiries[i]

    def is_expiry(self, d: date) -> bool:
        i = bisect.bisect_left(self.expiries, d)
        return i < len(self.expiries) and self.expiries[i] == d
