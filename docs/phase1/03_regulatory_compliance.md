# 3. Indian Regulatory & Compliance Considerations

Status: **Phase 1 draft** · Researched: 2026-11-07

> This is an engineering compliance summary, **not legal advice**. The primary documents
> are the SEBI circular *"Safer participation of retail investors in Algorithmic
> trading"* (4 Feb 2025), SEBI's extension circular (30 Sep 2025), and the NSE/BSE
> implementation standards and FAQs (May 2025 onward, incl. NSE circular INVG/67858).
> Several details below were confirmed only through broker announcements implementing
> those circulars. Before live trading (Phase 8) we confirm the current position with
> the chosen broker's compliance/API desk and record their answer in the repo.

## 3.1 The framework in one paragraph

From **1 April 2026** the retail algo framework applies to all stock brokers. Retail
clients may use broker APIs for algorithmic trading. Brokers act as principals and are
responsible for algos run through their APIs. Every API order is tagged with an algo
identifier by the broker/exchange. Order APIs accept calls only from a **static IP
registered** to the client. API access must use the broker's authenticated, vendor-specific
APIs (no "open" APIs) with 2FA, and API sessions are logged out daily. A **self-built algo
for personal use** (self and immediate family) running **below the exchange
orders-per-second (OPS) threshold of 10 orders/second** does not need exchange
registration. Above the threshold, the algo must be registered through the broker.

## 3.2 Feature-by-feature status

| Feature | Status for this project | How the design complies |
|---|---|---|
| Personal algo trading via official broker API | ✅ **Permitted** | Only official SDKs/endpoints; one owner |
| Self-built strategies for own account | ✅ **Permitted** without exchange registration **if < 10 OPS** | Hard internal cap at 5 orders/s and 200/min, enforced in the execution service; alert if approached |
| Exceeding 10 orders/second | ⚠ **Requires algo registration** via broker/exchange | Not supported in V1. Cap cannot be raised from the UI |
| Static IP for order calls | ✅ **Mandatory** (in force since 1 Apr 2026) | All order calls go out through one cloud Elastic/Static IP registered with the broker; staging uses the broker's secondary IP slot if available |
| Market data from non-registered IPs | ✅ Generally permitted (static IP applies to order endpoints) | Data workers may run anywhere, but in V1 everything runs on the same host anyway |
| Daily session logout / re-login with 2FA | ✅ **Mandatory** | Morning login flow in dashboard; tokens encrypted, expire automatically, purged at end of day |
| Automating broker login (stored PIN/TOTP, headless browser) | ❌ **Not used**: against broker ToS (most brokers) and the spirit of 2FA | Owner completes the official login each day |
| Market orders | ⚠ **Restricted**: brokers apply Market Price Protection or convert to limit orders | Execution layer sends protected/marketable-limit orders and handles partial fills |
| Order tagging / audit | ✅ Broker/exchange applies the algo ID; we add our own client tag | Every order has an `client_order_id` and `strategy_id`; full audit log kept ≥ 5 years (see schema) |
| Providing the platform/strategies to others (friends, paid users) | ❌ **Requires** broker empanelment + exchange registration (and potentially SEBI Research Analyst registration for "black-box" algos) | Single-owner system; no multi-tenant onboarding in V1 |
| Family use (spouse, dependent children, parents) | ⚠ Permitted under the framework per broker guidance, each through their **own** account and API key | Out of scope for V1 |
| Cloud hosting | ✅ Permitted. No rule mandates on-prem hosting | Static IP egress; host in India (Mumbai region) for latency |
| Intraday auto square-off, circuit limits, price bands, F&O position limits | Exchange/broker rules apply as usual | Risk engine checks price bands and session timings; we exit our own intraday positions before broker square-off time |

## 3.3 Other rules the engine must respect

- **Trading sessions and holidays.** NSE/BSE holiday calendars are loaded into an `exchange_calendar` table, refreshed yearly and checked daily. No new orders outside session windows (pre-open 09:00–09:15 handled separately; normal 09:15–15:30 IST for equity).
- **Price bands / circuit limits.** Limit orders outside the band are rejected by the exchange. The risk engine pre-checks with quote data where available.
- **Auto square-off.** Brokers square off intraday (MIS) positions around 15:15–15:25 with a fee. Our time-based exit defaults to 15:10.
- **Taxes and charges.** STT, exchange transaction charges, SEBI fee, stamp duty, GST and brokerage are modelled in backtests and paper trading through a versioned charges table.

## 3.4 Open compliance items to confirm with the broker before Phase 8

1. Exact OPS measurement (per client, per exchange, per second) and whether the broker's own limit is lower.
2. Whether the broker requires an algo name/strategy declaration header (e.g. Upstox app "algo name") for self-built algos.
3. Process and lead time for registering/changing the static IP, and whether a secondary IP is permitted for staging.
4. Whether GTT/broker-side stop orders placed via API are subject to the same static-IP check (Upstox: yes).
5. The broker's daily session logout time.

## Sources

- SEBI framework overview (secondary, cites primary circulars): https://algobulls.com/blog/industry-insights-and-updates/sebi-new-algotrading-regulations-for-retail-investors-2026
- Tradejini summary of rules effective April 2026: https://www.tradejini.com/blogs/what-sebis-new-algo-trading-rules-mean-for-you
- Fyers support: new SEBI rules from 1 April 2026 — https://support.fyers.in/portal/en/kb/articles/what-are-the-new-sebi-rules-for-retail-algo-trading-from-april-01-2026
- Upstox community: mandates effective 1 April 2026 (links NSE circular INVG/67858) — https://community.upstox.com/t/important-new-sebi-exchange-mandates-for-api-trading-effective-1st-april-2026/14822
- Upstox community: static IP regardless of OPS — https://community.upstox.com/t/when-will-be-static-ip-mandatory-for-algo-trades/13646
- DhanHQ: < 10 OPS needs no exchange registration; static IP; MPP — https://madefortrade.in/t/dhanhq-update-safer-participation-of-retail-investors-in-algo-trading-static-ip-mpp-rate-limits/61689
- Angel One: SmartAPI changes from 1 April 2026 — https://www.angelone.in/news/market-updates/what-s-changing-in-angel-one-s-smartapi-access-from-april-1-2026
- QuantInsti overview: https://www.quantinsti.com/articles/algorithmic-trading-india/
