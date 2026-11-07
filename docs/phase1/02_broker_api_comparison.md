# 2. Indian Broker API Comparison

Status: **Phase 1 draft** · Researched: 2026-11-07

> **Accuracy note.** Broker pricing, rate limits and regulatory implementation changed
> several times between 2025 and 2026. Figures below come from broker support pages,
> official developer forums and community announcements found during research. Items
> marked ⚠ could only be confirmed from secondary sources. **Before Phase 3 we re-verify
> every number against the chosen broker's current official docs** and record the
> result in `docs/broker_integration.md`.

## 2.1 Summary matrix

| | **Zerodha Kite Connect** | **Upstox API (v2/v3)** | **Angel One SmartAPI** | **Dhan (DhanHQ v2)** | **Fyers API v3** |
|---|---|---|---|---|---|
| API cost | Personal plan: **free** (orders, portfolio; **no** live or historical data). Connect plan: **₹500/month per app** incl. live + historical data | Trading + data APIs **free**. Upstox staff posts (Oct 2026) mention **₹10 per executed API order till 31 Dec 2026** ⚠ | API + historical data **free** | Trading API **free**; Data APIs **~₹499 + tax / 30 days** ⚠ | API, quotes, historical data **free** |
| Auth | OAuth-style browser login → `request_token` → `access_token`. Manual login daily | OAuth 2 login → access token; also an official "token request" flow approved by the user in the Upstox app ⚠ | Client code + PIN + TOTP via API (officially supported) → JWT + feed token | Access token generated from the web portal, or OAuth-style consent flow; ~24h validity | OAuth-style auth code → access token, daily |
| Session expiry | Daily (~6 AM next day) | Daily (~3:30 AM) | Daily | ~24 h | Daily |
| Live data WebSocket | Yes (KiteTicker, binary; up to 3 connections × 3000 instruments) — paid plan only | Yes (Market Data Feed v3, protobuf) + portfolio/order update stream | Yes (SmartStream WebSocket 2.0) + order updates | Yes (live feed, 20-level depth on some segments) + order updates — data plan | Yes (data + order WebSockets) |
| Order types | Market, limit, SL, SL-M, AMO, iceberg, cover, **GTT** | Market, limit, SL, SL-M, AMO, GTT, multi-order | Market, limit, SL, SL-M, AMO, robo/GTT | Market, limit, SL, SL-M, **Super Order** (entry+SL+target), Forever/GTT | Market, limit, SL, SL-M, cover, bracket, GTT |
| Modify / cancel | Yes | Yes | Yes | Yes | Yes |
| Holdings / positions / trade book | Yes | Yes | Yes | Yes | Yes |
| Historical candles | Yes (paid plan) | Yes (v3, minute→monthly) | Yes | Yes (data plan) | Yes |
| Order rate limit | ~10/s, per API key ⚠ | ~10 orders/s (regulatory) ⚠ | ~10 orders/s (regulatory) ⚠ | **10/s, 250/min, 1000/h, 7000/day** (Dhan FAQ) | ~10/s ⚠ |
| Static IP (orders) | Required for place/modify/cancel since 1 Apr 2026; data endpoints unrestricted | Required since 1 Apr 2026 for place/modify/cancel/multi/GTT; primary + optional secondary IP; IP changeable once a week (invalidates tokens) | Required since 1 Apr 2026; orders accepted only from the registered primary IP | Required; backup IP allowed; IP locked for ~7 days once set ⚠ | Required since 1 Apr 2026 ⚠ "one app, one IP" |
| Market orders | Market protection parameter required | MPP enabled by default; market orders reported as no longer permitted as-is | Converted with protection ⚠ | Converted to limit orders with MPP before reaching exchange | Per SEBI framework ⚠ |
| Sandbox | No (test with tiny quantities) | **Yes**, for order APIs | No | **Yes** | Limited ⚠ |
| Python SDK | `kiteconnect` (official, mature) | `upstox-python-sdk` (official) | `smartapi-python` (official) | `dhanhq` (official) | `fyers-apiv3` (official) |
| Documentation maturity | **Best**. Long history, very active forum | Good, improving fast | Adequate, forum-driven | Good | Good |

## 2.2 Per-broker notes

**Zerodha Kite Connect.** The most battle-tested retail API in India. Clean REST design, very good docs, stable WebSocket, GTT for broker-side protective exits. The downsides: ₹500/month for data, and the login is a browser redirect every morning. Automating that login (headless browser + TOTP) breaks Zerodha's terms and SEBI's 2FA intent, so we won't do it. The free "Personal" plan lacks market data, which makes it unusable for strategies unless you add another data source.

**Upstox.** Strongest cost/feature balance for a personal project: free data and trading APIs, an **official order sandbox** (very valuable for Phase 3), a v3 market-data feed, a portfolio-update stream, and a primary + secondary static IP (helpful for a staging host). Watch-outs: a temporary per-order API fee, and IP changes are limited to once a week and invalidate tokens.

**Angel One SmartAPI.** Free, with full data. Notable because programmatic login (PIN + TOTP) is officially supported, which allows unattended daily login. But it would require storing your **trading PIN and TOTP seed in the cloud**, which turns a server compromise into full account takeover. We would still require a human-triggered login even on Angel One. The API has historically had more forum-reported instability than Kite or Upstox ⚠.

**Dhan.** Free trading API with clear published limits, a sandbox, and Super Orders (entry + SL + target in one broker-side order, useful as a safety net). Data needs a paid plan. The strict 7-day IP lock makes migrating cloud hosts slower.

**Fyers.** Free API and free data, decent docs and WebSockets. A reasonable choice, but a smaller ecosystem than Kite or Upstox.

## 2.3 Recommendation

**The most important factor is which broker you already hold an account with.** Opening a new demat account just for an API is rarely worth it, and the platform is broker-agnostic by design (see `BrokerAdapter` in `04_architecture.md`).

If you have no strong preference, my recommendation for **V1 is Upstox**, with **Zerodha Kite Connect as the close alternative**:

| Criterion | Why Upstox for V1 |
|---|---|
| Safe testing | Official order sandbox: we can test order placement, modification and cancellation without real money before Phase 8 |
| Cost | Free trading + market data. Kite needs ₹500/month for data |
| Cloud fit | Primary + secondary static IP → production + staging can both be whitelisted |
| Real-time | WebSocket market feed and a separate order/portfolio update stream, which is exactly what reconciliation needs |
| Daily login | Official, user-approved token flow; no stored PIN/TOTP |

**Choose Zerodha instead if** you already trade on Zerodha, or you value the most mature documentation and community over the ₹500/month cost. The Kite adapter is equally well supported by this design.

**Avoid as the first adapter:** Angel One (only because its convenient login encourages storing PIN + TOTP seed). It is fine as a second adapter later.

Whichever broker is chosen, V1 also ships a **PaperBroker** adapter (simulated fills on live data) and a **ReplayBroker** for backtests.

## 2.4 Capability gaps the design must handle (regardless of broker)

- **No exactly-once guarantee from brokers.** We attach a unique client tag (Kite `tag`, Upstox `tag`, Dhan `correlationId`, etc.) to every order and search the order book for it after a timeout.
- **Rate limits** are per key/app and include a 10 orders/second regulatory ceiling. We enforce a local token bucket set below the limit (default 5 orders/s, 200/min).
- **Market protection** means a "market" exit may not fill fully in a fast market. Exit logic must handle partial fills and re-price.
- **Broker-side stop-losses** (SL-M, GTT, Super Orders) survive our outages. Where supported, every live position gets a broker-side protective stop, not just an in-memory one.
- **Session expiry** will break the WebSocket and REST calls overnight. The system treats this as an expected daily state, not an error.

## Sources

- Zerodha support: Kite Connect plans and sign-up — https://support.zerodha.com/category/trading-and-markets/kite-web-and-mobile/kite-api/articles/how-do-i-sign-up-for-kite-connect
- Kite forum: fee revision ₹2000 → ₹500 — https://kite.trade/forum/discussion/comment/49609/
- Kite forum: preparing for SEBI retail algo rules (static IP, rate limits, order types) — https://kite.trade/forum/discussion/comment/52171
- Upstox: algo trading circular — https://upstox.com/developer/api-documentation/announcements/algo-trading-circular
- Upstox community: new SEBI/exchange mandates from 1 April 2026 — https://community.upstox.com/t/important-new-sebi-exchange-mandates-for-api-trading-effective-1st-april-2026/14822
- Upstox community: regulatory changes now live — https://community.upstox.com/t/important-update-regulatory-changes-for-api-and-algo-trading-are-now-live/14874
- Angel One: SmartAPI changes from 1 April 2026 — https://www.angelone.in/news/market-updates/what-s-changing-in-angel-one-s-smartapi-access-from-april-1-2026
- Dhan: API rate limits — https://dhan.co/support/platforms/dhanhq-api/what-are-the-api-rate-limits-for-dhan/
- Dhan: market orders via API — https://dhan.co/support/platforms/dhanhq-api/what-happens-when-i-place-a-market-order-through-the-api/
- DhanHQ: static IP, MPP and rate limits — https://madefortrade.in/t/dhanhq-update-safer-participation-of-retail-investors-in-algo-trading-static-ip-mpp-rate-limits/61689
- Fyers: new SEBI rules from 1 April 2026 — https://support.fyers.in/portal/en/kb/articles/what-are-the-new-sebi-rules-for-retail-algo-trading-from-april-01-2026
- Secondary comparison (verify before relying): https://onetradejournal.com/trading-apis , https://algotest.in/blog/best-brokers-for-algo-trading-in-india.md
