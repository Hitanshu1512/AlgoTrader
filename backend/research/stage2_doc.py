"""Assemble docs/research/stage2_paper_trading_backtest.md from stage-2 results."""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.backtesting.data import CACHE
from research.stage2_report import ind

DOCS = Path(__file__).resolve().parents[2] / "docs" / "research"


def rs(v: float) -> str:
    s = f"₹{ind(v)}"
    return ("−" + s) if v < 0 else s


def sg(v: float) -> str:
    return ("+" + rs(v)) if v > 0 else rs(v)


def main() -> None:
    d = json.loads((CACHE / "stage2.json").read_text())
    tables = (DOCS / "stage2" / "tables.md").read_text()
    sec = {}
    for block in re.split(r"(?m)^### ", tables):
        if block.strip():
            t, b = block.split("\n", 1)
            sec[t.strip()] = b.strip()
    S = d["strategies"]
    s1, s2, s3 = (S[k] for k in S)
    m = {
        k: f"{['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][v - 1]} {k}"
        for k, v in ((int(k), int(v)) for k, v in d["months"].items())
    }
    m1 = {
        k: f"{['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][v - 1]} {k}"
        for k, v in ((int(k), int(v)) for k, v in d["stage1_months"].items())
    }
    st = lambda x, mode, k: x["stress"][mode][k][0]  # noqa: E731
    w = lambda x, k: x["whatif_outside_rules"][k]  # noqa: E731
    cap = lambda x: x["capital_for_1pct_rule_2025_26"]["capital_needed"]  # noqa: E731

    doc = (
        f"""# Stage 2: ₹1,00,000 Paper-Trading Backtest of the Shortlisted F&O Strategies

Status: **complete** · Run date: 2026-11-08 · Follows the [sampled-month study](sampled_month_backtest.md) and the [full-period study](fno_strategy_backtest.md)

> Option prices are modelled from real 1-minute index prices and anchored every day to real NSE closing option prices (validated on ~45,000 real prices: full-period study §2.3). Margins use a documented SPAN + ELM approximation. Nothing here is invented: where data did not exist, it is stated.

## Answers to your eight questions

All amounts are from a ₹1,00,000 starting balance, carried through the seven new random months.
* **Mechanical** = every valid signal at 1 lot, when the margin fits.
* **Disciplined** = your risk-management and behaviour rules applied in full.

**1. How much did each strategy generate?**

| Strategy | Mechanical (original rules) | Mechanical (defined-risk wings) | Disciplined (your rules) |
|---|---:|---:|---:|
| S1 Expiry-day hedged straddle (Nifty + Bank Nifty) | **{rs(s1["mechanical_original"]["final"])}** ({sg(s1["mechanical_original"]["net"])}) | same (already hedged) | **{rs(s1["disciplined"]["final"])}** (₹0: no trade passed the 1% risk rule) |
| S2 Expiry-day straddle (Nifty) | {rs(s2["mechanical_original"]["final"])} ({sg(s2["mechanical_original"]["net"])}) | **{rs(s2["mechanical_defined"]["final"])}** ({sg(s2["mechanical_defined"]["net"])}) | **{rs(s2["disciplined"]["final"])}** (₹0: no trade passed the 1% risk rule) |
| S3 9:20 short strangle (Nifty) | {rs(s3["mechanical_original"]["final"])} ({sg(s3["mechanical_original"]["net"])}) | {rs(s3["mechanical_defined"]["final"])} ({sg(s3["mechanical_defined"]["net"])}) | **{rs(s3["disciplined"]["final"])}** ({sg(s3["disciplined"]["net"])}) |

**2. Highest net profit:** **S1**, {sg(s1["mechanical_original"]["net"])} with mechanical execution. Under the disciplined rules **no strategy made money**: S1 and S2 could not place a single trade, and S3 lost {rs(-s3["disciplined"]["net"])}.

**3. Lowest drawdown:** among strategies with a meaningful number of trades, **S2 with defined-risk wings**: {s2["mechanical_defined"]["max_dd_pct"]:.1f}% ({rs(s2["mechanical_defined"]["max_dd_rs"])}), against {s1["mechanical_original"]["max_dd_pct"]:.1f}% for S1 and {s3["mechanical_defined"]["max_dd_pct"]:.1f}% for S3. The disciplined S1/S2 accounts show 0% only because they never traded.

**4. Most consistent:** **S2 with defined-risk wings**, profitable in **5 of the 5** months it could trade (+2.2% to +4.1% each). S1 was profitable in 4 of 5 (Nov 2020: −3.2%). S3 was profitable in 3 of 6.

**5. Easiest to execute with ₹1 lakh:** under your 1% risk rule, **none**. One lot's planned stop-loss risk exceeded the 1% budget (≈ ₹1,000) on every S1 and S2 signal, and on 103 of 143 S3 signals; another 8 S3 signals failed the 60% margin cap and 4 fell in a cooling-off period. Mechanically, S2 with wings was the easiest (21 of 30 signals marginable, one trade a week). But at **2025–26 lot sizes neither S1 nor S2 could be margined with ₹1 lakh at all**: zero trades in Dec 2025 and Feb 2026.

**6. Best after costs and risk management:** **none.** With your rules, S1 and S2 cannot trade and S3 lost money. After costs alone (mechanical), S1 was best: {rs(s1["mechanical_original"]["costs"])} of charges on {rs(s1["mechanical_original"]["pnl_before_costs"])} of pre-charge profit.

**7. Would I deploy real capital?** **No, not with ₹1 lakh.**
* Under the 1% risk rule the account cannot trade S1 or S2.
* At today's lot sizes even 1-lot mechanical trading cannot be margined: about ₹1.2 lakh is needed per lot on expiry day.
* The profitable mechanical runs risk 1.6–2.8% of equity per trade (S2 naked 1.6%, S2 with wings 2.3%, S1 2.8%), which is outside your 0.5–1% limit.
* The mechanical runs are exposed to gaps: one adverse 2% jump on the first expiry of each month turns S1's {rs(s1["mechanical_original"]["final"])} into {rs(st(s1, "mechanical_original", "gap_2pct_first_signal_each_month"))}.
* S3 lost money in every mode.
* To follow your rules at 2025–26 lot sizes you need about **{rs(cap(s1))} for S1** (≈ ₹{cap(s1) / 1e5:.1f} lakh), {rs(cap(s2))} for S2 (≈ ₹{cap(s2) / 1e5:.1f} lakh) and {rs(cap(s3))} for S3 (≈ ₹{cap(s3) / 1e5:.1f} lakh). For context only: at ₹4 lakh and 1% risk, S1 would have ended at {rs(w(s1, "risk_1pct_capital_4L")["final"])} ({sg(w(s1, "risk_1pct_capital_4L")["net"])}, max drawdown {w(s1, "risk_1pct_capital_4L")["max_dd_pct"]:.1f}%).

**8. My selection:**
* **Primary: S1, the expiry-day hedged straddle (Nifty first).** Highest profit and profit factor ({s1["mechanical_original"]["profit_factor"]:.2f}). Defined risk. Positive across the full-period study, stage 1 (7/7 months) and stage 2 (4/5 tradeable months).
* **Alternative 1: S2 with defined-risk wings.** The most consistent strategy here and the lowest drawdown. It is the same expiry-day family as S1, so it adds little diversification.
* **Alternative 2: S3, the 9:20 strangle, for paper trading only, not capital.** It lost money in every mode of this test.
* **In practice: keep paper-trading S1 and do not trade real money until the account can follow the 1% rule (≈ ₹{cap(s1) / 1e5:.1f} lakh).**

## 1. Test design

### 1.1 Months: one new random month per year (fixed seed {d["seed"]})

The draw excludes the stage-1 months ({", ".join(m1.values())}) and is limited to months where complete data exists for both indices, as in stage 1 (2020 from May; 2026 to March):

| Year | Stage-1 month (excluded) | **Stage-2 month** |
|---|---|---|
"""
        + "\n".join(f"| {y} | {m1[y]} | **{m[y]}** |" for y in m)
        + f"""

The same months are used for every strategy and every mode. Every trading day was evaluated: {s3["mechanical_original"]["signals"]} trading days, {s2["mechanical_original"]["signals"]} Nifty expiry days and {s1["mechanical_original"]["signals"] - s2["mechanical_original"]["signals"]} Bank Nifty expiry days. The balance is carried from month to month; no capital is added and nothing is reset.

**Disclosure:** these months are new relative to the stage-1 sample. Apart from Feb 2026, though, they fall inside the 2020–2025 period of the original full-period study. Strategy parameters were **not** changed for this test.

### 1.2 Strategies (rules unchanged)

| Strategy | Rules | Instruments |
|---|---|---|
| **S1** Expiry-day hedged straddle | On each index's expiry day: sell ATM CE + PE at 11:00, buy ~Δ0.01 CE + PE wings; stop each short leg at +50% of its premium; close everything at 15:15 | Nifty and Bank Nifty (Nifty first when both expire the same day) |
| **S2** Expiry-day straddle | Nifty expiry days: sell ATM CE + PE at 9:20; 30% stop per leg; exit 15:15. Defined-risk version adds ~Δ0.01 wings | Nifty |
| **S3** 9:20 short strangle | Every day: sell ~Δ0.20 CE + PE of the nearest expiry at 9:20; 30% stop per leg; exit 15:15. Defined-risk version adds ~Δ0.01 wings | Nifty |

The defined-risk version follows your instruction to use defined risk wherever possible. It uses the same ~Δ0.01 "disaster wing" convention as S1, fixed before this test and not tuned on stage-2 data.

**Instruments not tested:**
* **FINNIFTY:** no 1-minute FINNIFTY data exists in any source reachable from this environment, and its weekly options were discontinued in Nov 2024.
* **Stock F&O:** these are index-option strategies. Stock options have no weekly expiries and too little intraday liquidity for them, so they were not applicable.

### 1.3 Realistic execution

| Item | Treatment |
|---|---|
| Lot sizes | **Exact exchange lot of each contract on each trade date**, read from NSE bhavcopies. Nifty: 75 (Nov 2020, Apr 2021), 50 (Jul 2022, Oct 2023), 25 (Sep 2024), 75/65 (Dec 2025), 65 (Feb 2026). Bank Nifty: 25, 25, 25, 15, 15, 35, 30 |
| Margin | SPAN + ELM approximation (`app/backtesting/margin.py`): naked ≈ 11% of notional; hedged = min(max loss, naked SPAN) + 2% ELM + wing premium; **+2% expiry-day ELM from 20 Nov 2024** |
| Charges | Rates in force on each trade date: ₹20/order brokerage (Upstox); STT 0.05% → 0.0625% (Apr 2023) → 0.1% (Oct 2024) on option premium sold; NSE transaction charges; SEBI ₹10/crore; stamp 0.003% on buys; GST 18% |
| Slippage / bid-ask | max(0.5% of premium, ₹0.10) per option fill, on every entry and exit, reported separately |
| Stops | Checked against each minute's worst price; filled at the stop level, or at the bar's open if the market gapped through it |
| Expiry | All positions are closed at 15:15, so there is no exercise and no exercise STT. Expiry-day ELM is included. Bank Nifty weeklies are used only while they existed (to Nov 2024); after that the monthly expiry is used |
| Look-ahead | Decisions use only closed bars and the previous day's option surface |

### 1.4 The three execution modes

| Rule | Mechanical | Disciplined (all predefined and measurable) |
|---|---|---|
| Which signals | Every valid signal | Every valid signal that passes the checks below |
| Size | 1 lot | ⌊1% × equity ÷ planned risk per lot⌋; skip if < 1 lot |
| Planned risk per lot | — | All short legs stopped at their stop level + exit slippage + wings expiring worthless + all charges |
| Margin | ≤ 90% of equity | ≤ 60% of equity (≥ 40% kept free for MTM swings) |
| Daily loss limit | none | 2% of the day's starting equity: no new entries, and a hard stop that closes any open position when reached |
| Drawdown | none | 10% from peak → pause for the rest of the month and review; resume at 0.5% risk until a new equity high; another pause at each further 10% |
| Losing streak | none | 3 consecutive losses → 2-session cooling-off |
| Overtrading | — | One open position at a time; one entry per setup; no re-entry, no averaging down, no martingale; size never increases after losses |
| Journal | Every entry, exit and skip, with reason | Same |

Not simulated: "emotional mistakes" (per your instruction), random misses and FOMO entries. The strategies only trade at predefined times, so FOMO entries cannot occur.

## 2. Headline results

{sec["Headline: ₹1,00,000 → final balance"]}

## 3. Individual strategy reports

### S1: Expiry-day hedged straddle (Nifty + Bank Nifty)

{sec["S1 Expiry-day hedged straddle"]}

### S2: Expiry-day straddle (Nifty)

{sec["S2 Expiry-day straddle (Nifty)"]}

### S3: 9:20 short strangle (Nifty)

{sec["S3 9:20 short strangle (Nifty)"]}

**Why S3's disciplined account did worse than the mechanical ones:** the 1% filter only lets through days when one lot's planned risk is small. Those are low-premium days, where the wing cost and charges take a large share of a small credit. The filter therefore selects S3's weakest days. The same pattern appears in the context-only ₹4 lakh what-if below, where S3 makes money once most of its signals can be taken.

## 4. Stress tests

Gap scenario: an instantaneous ±1% or ±2% index jump one hour after entry on the **first signal day of each month** (S1: both indices, 14 events; S2 and S3: 7 events). The worse direction is shown. Stops fill after the jump.

{sec["Stress tests (final balance from ₹1,00,000 unless stated)"]}

**What survives adverse conditions:**
* **S1 (mechanical)** stays profitable under +25% slippage, +50% charges, a 10-point lower win rate, a 5-trade full-risk losing streak, the worst possible ordering and reduced capital (₹75k → {rs(st(s1, "mechanical_original", "capital_75k"))}; ₹50k → {rs(st(s1, "mechanical_original", "capital_50k"))}).
* **S1 is not robust to gaps:** ±1% gaps take the account to {rs(st(s1, "mechanical_original", "gap_1pct_first_signal_each_month"))} and ±2% gaps to {rs(st(s1, "mechanical_original", "gap_2pct_first_signal_each_month"))}. At today's lot sizes a single 2% jump costs about ₹33–35k on one lot even with the wings.
* **S2** (naked, mechanical) survives the cost stresses but not the losing streak or the gaps. It cannot trade at all with ₹75k or ₹50k.
* **S3** loses in every scenario.

## 5. What it would take to follow your rules

{sec["Capital needed to follow the 1% rule at 2025–26 contract sizes"]}

{sec["What-ifs outside the stated rules (context only, not ranked)"]}

These what-ifs break your stated rules. They are shown only to answer "what would make these strategies tradeable" and are not part of the ranking.

## 6. Consolidated comparison and ranking

{sec["Disciplined execution with ₹1 lakh: status (not rankable)"]}

Under your rules, S1 and S2 cannot trade and S3 loses money, so a ranking of the disciplined results would only rank "did nothing" against "lost money". The eight-criterion ranking therefore uses the **mechanical defined-risk** results. That is the realistic 1-lot execution of each strategy, with margin, costs and defined risk, but without the 1% cap.

{sec["Consolidated ranking: Mechanical (defined-risk), 1 lot per signal"]}

Psychological sustainability combines the longest run of consecutive losses, the worst single day and the longest time under water. Weekly strategies (S1, S2) also need far less screen time than the daily S3.

## 7. Limitations

* **Seven months, small samples:** 6–76 trades per account. Treat results as evidence, not forecasts.
* **Only two sampled months (Dec 2025, Feb 2026) use today's contract sizes,** and in both, S1 and S2 could not be margined with ₹1 lakh. **The mechanical profits all come from 2020–2024,** when lots were smaller.
* **Modelled option prices** (validated daily anchor; modelled intraday path). The main untested risk remains real afternoon decay on expiry days (full-period study §6.4).
* **Approximate margins:** not NSE SPAN files. Brokers may charge more.
* **Gap stresses are deterministic scenarios,** not forecasts of how often gaps happen.
* **Not modelled:** order rejections, partial fills and broker outages. The wings bound, but do not remove, the cost of a stop failing.
* **Calendar correction:** while preparing this stage, a Bank Nifty expiry-calendar bug (6 non-existent Wednesdays between Sep 2023 and Feb 2024) was found and fixed. The calendar now matches NSE's actual expiries exactly (Nifty 316/316 and Bank Nifty 258/258 dates, Apr 2020 – Apr 2026). Earlier reports were re-run; see the note in the full-period study.

## 8. Trade ledger, journal and code

* Ledgers (every executed trade: lots, quantity, margin, planned risk, pre-charge P&L, charges, slippage, net, equity after): `docs/research/stage2/S*_<mode>_ledger.csv`
* Journals (every entry, exit, skip and rule trigger, with its reason): `docs/research/stage2/S*_<mode>_journal.csv`
* Account rules: `backend/app/backtesting/account.py` (tests: `backend/tests/unit/test_account_rules.py`)
* Runner and report: `backend/research/stage2.py`, `backend/research/stage2_report.py`, `backend/research/stage2_doc.py`

```bash
./scripts/fetch_research_data.sh
```

```bash
cd backend && uv run python -m research.lot_table 2 && uv run python -m research.stage2 && uv run python -m research.stage2_report && uv run python -m research.stage2_doc
```
"""
    )
    (DOCS / "stage2_paper_trading_backtest.md").write_text(doc)
    print(len(doc))


if __name__ == "__main__":
    main()
