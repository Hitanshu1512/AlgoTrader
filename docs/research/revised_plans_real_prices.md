# Revised Plan 1 (₹1 lakh, 30% target) and Plan 2 (₹10–25k, 90% target), Re-tested on Real NSE Option Prices

Status: **complete** · Run date: 2026-11-08 · Data: NSE F&O bhavcopies 13 Apr 2020 – 6 Nov 2026

> **Bottom line, before anything else**
> * **Neither target is supported by the historical evidence.** After all costs, no systematic options strategy we could test on real NSE prices reaches 30% a year with controlled risk, or 90% a year at any risk.
> * **Plan 1 as specified (₹1 lakh, 0.5–1% risk per trade) is rejected.** Defined-risk spreads lose money. The only strategy with an out-of-sample edge (expiry-day short straddle) has made ≈ 2–4% a year at 1% risk. Since Dec 2024 it also needs ≈ ₹2 lakh of margin per lot, so ₹1 lakh cannot trade it at all.
> * **Plan 2 as specified (₹10–25k, 90%) is rejected.** Every candidate lost money at that account size: −9% to −44% a year, with 42–95% drawdowns. The one buying strategy with an edge needs ≈ ₹1 lakh per trade today.
> * **Correction to earlier work.** The intraday study behind the partner deck (₹66,700 per lot a year) used modelled prices with an 11:00 entry. On real prices with a 09:15 entry, the same idea makes ≈ ₹13,000–15,000 per lot a year, and the version *with* protective wings lost money. The 11:00 entry cannot be checked with end-of-day data. Until paper trading measures it, **treat the deck's return figures as unconfirmed.**

## 1. What changed in the testing

| | Earlier studies | This study |
|---|---|---|
| Option prices | Modelled minute by minute, anchored to NSE closes | **Real NSE prices actually traded**: each contract's daily open, high, low, close, settlement price and volume |
| Underlyings | Nifty, Bank Nifty | Nifty, Bank Nifty, **FINNIFTY** (from Jan 2021); liquid stock options checked (Jul 2024 →) |
| Period | May 2020 – Dec 2025 (+ 2026 modelled) | **Apr 2020 – 6 Nov 2026**, 1,624 sessions, 7.9 M option rows |
| Lot sizes | Today's, or bhavcopy-derived | Exchange lot of **every contract on every date** (Nifty 75 → 50 → 25 → 75 → 65; Bank Nifty 25 → 15 → 30/35 → 30; FINNIFTY 40 → 25 → 65 → 60) |
| Validation | Fixed split (2020–22 / 2023–25) | **Walk-forward**: 10 six-month test blocks (Jan 2022 – Nov 2026), each traded with parameters chosen only on the previous 20 months |
| Execution | Modelled fills | Signal at the close of day *t*; **entry at the real open of day *t*+1** + slippage. A strike that traded < 100 contracts on day *t*, or didn't trade at the entry open, counts as a missed trade |
| Human behaviour | – | **10% of valid signals missed** (seeded). Daily loss limit, drawdown pause and resume, hard drawdown stop, max positions, margin cap |

**Costs on every order:** brokerage ₹20, STT, NSE transaction charge, SEBI fee, stamp duty and GST, at the rates in force on that date (STT on options sold: 0.05% → 0.0625% → 0.1% → 0.15%). Slippage is max(1% of premium, ₹0.20) per leg per side, doubled in the stress test. Margins use SPAN ≈ 9% + ELM 2% (+2% on expiry day from 20 Nov 2024). Debit spreads use premium + ELM.

**What the data cannot do:**
* Bhavcopies hold daily OHLC only, so intraday entries (11:00, 13:30) cannot be tested on real prices.
* There are no bid/ask quotes, so the spread is modelled as slippage.
* Stops on multi-leg positions are checked at the close (a person checking at ~15:15). Single options and the legs of the expiry-day straddle are checked against their real daily highs and lows.

## 2. Strategies tested (13 families × 3 indices; parameters fixed in advance, 4–8 per family)

| For | Strategy | Rules |
|---|---|---|
| Plan 1 | **Trend credit spread** | N days before each expiry, sell the Δ0.20/0.30 put (uptrend: close > rising 20-day EMA) or call (downtrend), buy the strike 2 steps further out. Stop when the cost to close reaches 2× or 2.5× the credit, take profit at 60% |
| Plan 1 | **Iron condor** | Both sides at Δ0.15/0.25, wings 2 steps out, same stop logic, 50% target |
| Plan 1 | **Trend debit spread** | Each expiry cycle: buy the ATM call (put) in an up (down) trend, sell 2–4 steps out. Stop −40/−60%, target +80%, max 3–5 days |
| Plan 1 | **Expiry-day straddle (real prices)** | On each expiry day, sell the ATM call + put at the real open. Stop each leg when its real high reaches +30/+50%, otherwise close at the real close. With and without Δ0.02 wings |
| Plan 2 | **Breakout option buying** | Close beyond the 10/20-day high (low) → buy the ATM call (put) at the next open. Stop −30/−50% on the real low, target +80/+150% on the real high, max 3 days |
| Plan 2 | **Breakout debit spread** | Same signal, buy ATM / sell 4 steps out |
| Plan 2 | **Volatility-expansion straddle** | Narrowest range of 7 days (NR7) **and** ATM implied volatility in the lowest 30% of 120 days → buy the ATM straddle. Target +30/+50%, stop −25/−40%, max 2–4 days |
| Plan 2 | **Event-day straddle** | Buy the ATM straddle at the open of a Union Budget day or the 2024 election-results day, sell at that day's close |

**Liquid stock options were checked and excluded** (`research/stock_options_check.py`). Stock options are monthly only, and one ATM lot costs ₹11,000–16,000 in premium (Reliance ₹12,494, HDFC Bank ₹11,991, ICICI Bank ₹15,750, SBI ₹12,675 median, Jul 2024 – Nov 2026). That is 50–60% of a ₹25,000 account and 11–16% of ₹1 lakh for a single position, which breaks both plans' risk limits.

## 3. Out-of-sample results per lot (walk-forward, Jan 2022 – Nov 2026)

| Strategy | Index | Trades | Net per lot | Per year | Win % | Profit factor | Max DD per lot | With 2× slippage |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Volatility-expansion straddle | FINNIFTY | 35 | **₹95,451** | ₹24,656 | 46% | 2.10 | ₹22,786 | ₹73,220 |
| Expiry-day straddle (no wings) | FINNIFTY | 175 | **₹74,286** | ₹15,443 | 57% | 1.49 | ₹28,214 | ₹58,624 |
| Expiry-day straddle (no wings) | Nifty | 252 | **₹64,081** | ₹13,284 | 52% | 1.22 | ₹29,747 | ₹29,009 |
| Trend debit spread | FINNIFTY | 94 | ₹11,792 | ₹2,942 | 40% | 1.12 | ₹25,117 | −₹10,769 |
| Expiry-day straddle (no wings) | Bank Nifty | 173 | ₹8,797 | ₹1,831 | 54% | 1.04 | ₹43,817 | −₹6,373 |
| Event-day straddle | Bank Nifty | 5 | ₹5,068 | – | 20% | 1.14 | ₹26,727 | ₹2,623 |
| Trend credit spread | Bank Nifty / FINNIFTY / Nifty | 174 / 149 / 214 | −₹12,259 / −₹14,879 / −₹35,407 | | 72% / 72% / 66% | 0.83 / 0.78 / 0.76 | | |
| Iron condor | Bank Nifty / FINNIFTY / Nifty | 173 / 109 / 217 | −₹20,209 / −₹59,057 / −₹89,994 | | 70% / 58% / 60% | 0.81 / 0.45 / 0.61 | | |
| Trend debit spread | Bank Nifty / Nifty | 134 / 183 | −₹46,845 / −₹87,369 | | 41% / 40% | 0.76 / 0.72 | | |
| Breakout option buying | FINNIFTY / Bank Nifty / Nifty | 79 / 154 / 162 | −₹56,044 / −₹87,283 / −₹1,06,674 | | 27% / 25% / 24% | 0.76 / 0.85 / 0.78 | | |
| Breakout debit spread | FINNIFTY / Nifty / Bank Nifty | 64 / 153 / 125 | −₹28,933 / −₹65,312 / −₹78,266 | | 41% / 39% / 38% | 0.71 / 0.75 / 0.59 | | |
| Volatility-expansion straddle | Bank Nifty / Nifty | 55 / 60 | −₹19,062 / −₹51,295 | | 36% / 37% | 0.89 / 0.76 | | |

The full table, including every parameter set's full-period result, is in [revised_plans/tables.md](revised_plans/tables.md).

**What this shows:**
1. **High win rates don't mean profit.** Credit spreads and condors win 58–72% of trades and still lose. The occasional full-width loss outweighs many small gains after 2024–26 charges.
2. **Directional option buying loses on every index.** Win rates are 24–27%, and the winners do not pay for the losers.
3. **The only consistent edge is selling expiry-day time value**, and only without bought wings. Wings bought at the real opening price cost more than they save.
4. **The volatility-expansion straddle on FINNIFTY is real but concentrated.** Of its +₹95,451 per lot, +₹1.03 lakh came in 2025–26; 2022–24 was −₹7,300. It also lost on Nifty and Bank Nifty.

## 4. Accounts with all risk rules

These use the out-of-sample trades from Jan 2022 to 6 Nov 2026, with 10% of signals missed.

| Account | Start | End | CAGR | ≈ per month | Max drawdown | Trades / month | Win % | PF | Worst trade | Longest losing run | Risk / trade |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **P1** defined-risk spreads (9 strategy-index pairs), 1% rule | ₹1,00,000 | ₹82,018 | **−4.0%** | −0.34% | 26% (hard stop hit) | 0.6 | 44% | 0.64 | −₹19,308 | 4 | 0.8% |
| **P1** FINNIFTY trend debit spread, 1% rule | ₹1,00,000 | ₹1,07,221 | **+1.4%** | +0.12% | 8% | 0.6 | 46% | 1.32 | −₹2,051 | 6 | 0.8% |
| **P1** expiry-day straddle, 1 lot even above 1% risk (up to 6%) | ₹1,00,000 | ₹1,71,668 | **+11.8%** | +0.93% | 17% | 4.6 | 55% | 1.34 | −₹4,601 | 5 | 1.2% |
| **P1** expiry-day straddle, 1% rule | ₹2,50,000 | ₹2,73,166 | **+1.8%** | +0.15% | 9% | 3.3 | 52% | 1.13 | −₹3,027 | 5 | 0.8% |
| **P1** expiry-day straddle, 1% rule | ₹4,00,000 | ₹4,34,531 | **+1.7%** | +0.14% | 14% | 5.1 | 53% | 1.08 | −₹5,171 | 4 | 0.8% |
| **P2** volatility-expansion straddle (FINNIFTY) | ₹25,000 | ₹6,307 | **−24.7%** | −2.34% | 84% | 0.3 | 27% | 0.49 | −₹6,062 | 5 | 10% |
| **P2** breakout option buying (3 indices) | ₹25,000 | ₹1,476 | **−44.2%** | −4.75% | 95% | 0.4 | 22% | 0.54 | −₹4,852 | 5 | 21% |
| **P2** breakout debit spread (3 indices) | ₹25,000 | ₹13,399 | **−12.1%** | −1.07% | 53% | 0.4 | 36% | 0.65 | −₹3,470 | 5 | 6% |
| **P2** volatility-expansion straddle (FINNIFTY) | ₹10,000 | ₹6,416 | −8.8% | −0.76% | 42% | 1 trade | – | – | −₹3,584 | – | 22% |
| **P2** breakout option buying (3 indices) | ₹10,000 | ₹2,825 | −23.0% | −2.15% | 89% | 0.2 | 27% | 0.50 | −₹2,613 | 3 | 25% |
| *Reference:* P2 volatility-expansion straddle (FINNIFTY) | ₹1,00,000 | ₹1,91,632 | +14.4% | +1.12% | **69%** | 0.5 | 43% | 1.56 | −₹19,643 | 5 | 9% |

**Why the ₹1 lakh expiry-straddle account (+11.8%) is not the answer:**
* It made +₹60,820 in 2022, +₹13,485 in 2023, −₹781 in 2024 and −₹1,856 in 2025.
* It took no trade after 30 Jan 2025. From Dec 2024 the Nifty lot (75, then 65) and the expiry-day ELM pushed margin to ≈ ₹1.9–2.0 lakh per lot (₹1,95,225 on 19 Oct 2026).
* It also needed up to 6% risk per trade, against your 1% limit.

**Rules used:**

| | Plan 1 | Plan 2 |
|---|---|---|
| Risk per trade | 1% of equity (planned loss at the stop). The variant labelled "up to 6%" allows 1 lot up to 6% | 10% of equity; 1 lot allowed up to 30% |
| Maximum loss per position | Defined-risk only (wings / debit), except the expiry-straddle accounts, which are undefined-risk and are labelled as such | Defined (premium paid). The whole pot is the maximum loss |
| Daily loss limit | 2%: no new entries the next session | 30% |
| Drawdown | Pause 10 sessions at −10%, then resume. **Hard stop at −25%** (−35% in the "up to 6%" variant) | Pause 20 sessions at −50% |
| Positions / margin | Up to 2 open, margin ≤ 90% (100% in the "up to 6%" variant) | 1 open, margin ≤ 100% |
| Averaging, martingale, re-entry after a stop | Never | Never |

## 5. How much risk would the targets need?

This uses the out-of-sample trades as multiples of their planned risk, with fractional lots and margin ignored. That is the best case for sizing alone.

| Candidate | Risk per trade | Historical CAGR | Historical max DD | P(loss in a year) | P(hit target in a year) | P(−50% at some point) |
|---|---:|---:|---:|---:|---:|---:|
| Plan 1 · expiry-day straddle (Nifty + FINNIFTY) | 1% | +4.1% | 21% | 30% | 0% (30%) | 0% |
| | 2% | +7.6% | 38% | 33% | 11% | 0% |
| | 3% | +10.2% | 52% | 34% | 24% | 0% |
| | **5% (best CAGR)** | **+13.1%** | **73%** | 38% | 36% | 4% |
| | 10% | +5.2% | 95% | 48% | 38% | 33% |
| | 20% | −49.8% | 100% | 68% | 27% | 75% |
| Plan 2 · FINNIFTY volatility-expansion straddle | 5% | +7.6% | 38% | 41% | 2% (90%) | 0% |
| | **10% (best CAGR)** | **+10.2%** | **64%** | 44% | 10% | 3% |
| | 20% | +1.5% | 90% | 51% | 21% | 31% |
| | 30% | −21.2% | 98% | 60% | 22% | 54% |
| Plan 2 · breakout option buying | any | −4.6% (0.5%) to −100% (30%) | 28–100% | 71–100% | ≤ 6% | 0–100% |

**More risk does not reach the targets.** The edges are small: on average the Plan 1 straddle earns about 5% of its planned risk per trade, and the Plan 2 straddle about 28%. Growth peaks at 5% (Plan 1) and 10% (Plan 2) risk per trade. Beyond that, larger losses shrink the account faster than wins grow it. Raising risk mainly raises the chance of the target in a *lucky* year, while the median result and the drawdowns get worse.

## 6. Final recommendation

| # | Question | Answer |
|---|---|---|
| 1 | **Plan 1 strategy** | **Expiry-day short straddle on Nifty (weekly) + FINNIFTY (monthly).** Sell the ATM call and put at the expiry-day open, place SL-M stops at the broker on each leg at +50% of its fill, close at 15:15. 1 lot when the planned loss (50% of the premium) is ≤ 1% of equity. **No wings** (on real prices they lost money). Undefined risk: a gap through a stop can lose more than planned. *With ₹1 lakh and defined risk only:* the FINNIFTY trend debit spread, which is essentially break-even (+1.4% a year). |
| 2 | **Plan 2 strategy** | **None with ₹10–25k.** The only buying strategy with an out-of-sample edge is the **FINNIFTY volatility-expansion straddle**: after an NR7 day with ATM IV in its lowest 30% of 120 days, buy the ATM straddle; +30% target, −25% stop, max 2 days. It lost money at ₹10–25k because it could only afford 2022–24's small, losing trades. Since 2025 one trade costs ₹21,000–47,000. |
| 3 | **Minimum executable capital** | Plan 1: **≈ ₹2.5 lakh** to margin 1 lot (≈ ₹1.95 lakh on expiry day), and **≈ ₹5–6.5 lakh** to keep 1 lot within 1% risk (planned loss ₹4,800–6,400 per lot, Oct–Nov 2026). Plan 2 (vol-expansion): **≈ ₹50,000** to afford one trade, **≈ ₹1 lakh** to keep a stop-loss within ~10%. |
| 4 | **Expected net profit (evidence-based)** | Plan 1 at ₹4 lakh, 1% risk: **≈ ₹7,000 a year (+1.7%)**. At 2% risk ≈ +7.6% (≈ ₹30,000) with a ~38% historical drawdown. Plan 2 at ₹25,000: **−₹6,000 a year (−24.7%)**. At ₹1 lakh: +14.4% a year historically, but the Monte Carlo median is +8.9% with a 42% chance of losing in a year. |
| 5 | **Maximum risk and drawdown** | Plan 1 (₹4 lakh, 1%): 14% max drawdown, worst trade −₹5,171. **Plus gap risk**: a sudden 2% index jump through the stops costs an unhedged straddle ≈ ₹20,000–30,000 per lot (≈ 460–520 points × 65, less the premium collected). Plan 2 (₹25k): 84% max drawdown. At ₹1 lakh: 69%. |
| 6 | **Sample trades** | See §7 |
| 7 | **Best for long-term consistency** | Expiry-day short straddle (Nifty + FINNIFTY), 1 lot, 1% risk. Positive out of sample, robust to 2× slippage, but small: ≈ 2–4% a year at your risk limits |
| 8 | **Best for aggressive returns** | FINNIFTY volatility-expansion straddle, **only with ≥ ₹1 lakh** and accepting 60–70% drawdowns. Its edge comes mostly from 2025–26 and one index |
| 9 | **Reject either plan?** | **Reject both plans as specified.** Plan 1: 30% at ₹1 lakh with 0.5–1% risk is not achievable. Plan 2: 90% at ₹10–25k loses money in every version tested. Paper-trade the two strategies above before any real money. |

### Probability summary (Monte Carlo, 5,000 one-year paths of resampled months)

| | Plan 1 · straddle, ₹4 lakh, 1% risk | Plan 2 · vol-expansion, ₹25,000 | Plan 2 · breakout buying, ₹25,000 | Plan 2 · vol-expansion, ₹1 lakh |
|---|---:|---:|---:|---:|
| P(any loss over the year) | 37% | 75% | 79% | 42% |
| P(hitting the target) | **0%** (30%) | **0%** (90%) | 3% | 13% |
| P(falling 25% at some point) | 0% | 53% | 76% | 27% |
| P(falling 50%) | 0% | 13% | 45% | 1% |
| P(falling 90%, effectively total loss) | 0% | 0% | 2% | 0% |

## 7. Sample trades (real prices, real lot, all charges)

**Plan 1: Nifty expiry-day straddle, Monday 19 Oct 2026 (expiry; lot 65)**

| Leg | Entry (open − slippage) | Stop level (+50%) | Exit | P&L |
|---|---:|---:|---:|---:|
| SELL 23100 CE | ₹138.45 | ₹207.68 | ₹0.70 (15:15 close) | +₹8,954 |
| SELL 23100 PE | ₹26.09 | ₹39.14 | ₹39.52 (stop hit, + slippage) | −₹873 |
| **Total** | credit ₹164.54 × 65 = ₹10,695 | planned loss ₹5,347 | | gross +₹8,081; charges ₹116; **net +₹7,965** |

Margin blocked: ₹1,95,225. A losing week for comparison: **3 Nov 2026**, sold 23350 CE/PE for ₹197.85. The CE was stopped at ₹254.97, the PE closed at ₹0.45: **net −₹3,869**.

**Plan 2: FINNIFTY volatility-expansion straddle (lot 60)**

* Signal 21 Sep 2026 (NR7 day, low IV). Bought the 25600 CE at ₹171.70 and the 25600 PE at ₹186.34 at the 22 Sep open: premium **₹21,482**. Stop: value −25% (₹16,112). Target: +30% (₹27,927).
* 24 Sep close: CE ₹27.03, PE ₹747.75, so the position was worth ₹46,487 and the target was exceeded. **Net +₹24,811** after ₹193 of charges.
* Typical losers: 7 Aug 2026, −₹6,296, and 12 Aug 2026, −₹7,087 (time exits).

## 8. Projections (compounded; from the Monte Carlo, not promises)

**Backtested** = the account results in §4. **Projected** = resampled out-of-sample months. Both assume the future resembles Jan 2022 – Nov 2026.

| Plan | Capital | Scenario | 1 year | 2 years | 3 years | 5 years |
|---|---:|---|---:|---:|---:|---:|
| Plan 1 · straddle, 1% risk | ₹4,00,000 | Conservative (25th pct) | ₹3,92,000 | ₹3,92,000 | ₹3,96,000 | ₹4,00,000 |
| | | Base (median) | ₹4,08,000 | ₹4,12,000 | ₹4,20,000 | ₹4,32,000 |
| | | Optimistic (75th pct) | ₹4,20,000 | ₹4,36,000 | ₹4,48,000 | ₹4,68,000 |
| Plan 2 · vol-expansion | ₹25,000 | Conservative | ₹15,500 | ₹10,750 | ₹7,750 | ₹3,750 |
| | | Base | ₹19,500 | ₹14,750 | ₹11,250 | ₹6,500 |
| | | Optimistic | ₹24,250 | ₹19,750 | ₹16,000 | ₹10,250 |
| *Reference:* Plan 2 · vol-expansion | ₹1,00,000 | Conservative / base / optimistic | ₹84,000 / ₹1,09,000 / ₹1,46,000 | ₹86,000 / ₹1,26,000 / ₹1,92,000 | ₹87,000 / ₹1,41,000 / ₹2,41,000 | ₹99,000 / ₹1,89,000 / ₹3,64,000 |
| *Your targets* | | 30% / 90% a year | ₹1.30 L / ₹47,500 (on ₹25k) | ₹1.69 L / ₹90,250 | ₹2.20 L / ₹1.71 L | ₹3.71 L / ₹6.19 L |

## 9. What would have to change

* **For Plan 1** to make sense, the expiry-day edge needs to be confirmed at a better entry time (the 11:00 entry from the intraday study) using **real intraday option prices**. That can come from Upstox historical candles (Phase 3) or from paper trading. The intraday model said ≈ ₹66,700 per lot a year; real prices at the open say ≈ ₹13,000–15,000. That gap must be measured before any capital is committed.
* **For Plan 2**, no tested strategy turns ₹10–25k into a growth engine. A small pot can only make big percentage gains through very concentrated bets, and the history above shows those lose most of the time.
* **Realistic framing for a partner:** systematic index-options trading with retail capital and 2026 costs has, on real data, delivered **low single-digit to low double-digit annual returns with significant drawdowns**. It has not delivered 30–90%.

## 10. Reproduce

```bash
cd backend
uv run python -m research.build_eod_v2                 # real option prices + lot sizes (Apr 2020 – Nov 2026)
uv run python -m research.stock_options_check          # stock-option affordability
uv run python -m research.plans_v2                     # 13 families × 3 indices, walk-forward, stress
uv run python -m research.plans_v2_accounts '<plan json>'   # accounts + Monte Carlo (see revised_plans/tables.md)
uv run python -m research.plans_v2_leverage            # risk-per-trade analysis
uv run python -m research.plans_v2_report              # tables
```

Code: `app/backtesting/eod.py` (real-price engine), `app/backtesting/strategies/eod_strats.py` (strategies, grids), tests in `tests/unit/test_eod_engine.py`.
