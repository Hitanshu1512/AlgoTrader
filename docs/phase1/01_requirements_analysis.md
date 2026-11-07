# 1. Requirements Analysis

Status: **Phase 1 draft for owner review** · Last updated: 2026-11-07

## 1.1 What we are actually building

A **single-owner, cloud-hosted trading system** that acts on *one* personal Indian
brokerage account through the broker's official API. It does five things:

1. **Observe**: pull market data (WebSocket ticks + historical candles) and the account state (funds, holdings, positions, orders, trades).
2. **Decide**: run independent, configurable rule-based strategies on closed candles to produce *signals*.
3. **Gate**: every signal becomes an *order intent* that must pass a backend risk engine and, depending on mode, a human approval.
4. **Act**: submit, modify and cancel orders exactly once, then confirm the outcome from broker data. Never from our own assumptions.
5. **Protect and report**: manage exits (SL, target, trailing, time, emergency), keep the kill switch, write an audit trail, and push live state to a dashboard and Telegram.

## 1.2 Requirement classification

| Priority | Area | Non-negotiable properties |
|---|---|---|
| P0 | Broker integration | Official API only, official auth flow, daily session handling, static-IP egress for order calls, reconciliation |
| P0 | Execution reliability | Idempotent submission, no blind retry after timeout, persisted order intents, crash recovery, partial-fill handling |
| P0 | Risk management | Backend-enforced limits, fail-closed on stale data or unknown state, kill switch, default **Manual** mode |
| P0 | Security | No secrets in code/logs/frontend, encryption at rest, MFA for dashboard, audit logs |
| P1 | Backtesting & paper trading | Same strategy and risk code as live; paper broker is a separate adapter that physically cannot reach the real broker |
| P1 | Dashboard & notifications | Real-time over WebSocket, every control mirrored by a backend check |
| P2 | Analytics | Strategy-level and account-level performance |
| P3 | AI features | Advisory only; no path to the order gateway that bypasses risk/approval |

## 1.3 Key insights that shape the design

1. **Regulation now dictates parts of the architecture.** Since 1 April 2026, Indian brokers require order API calls to come from a **registered static IP**, sessions expire daily, and many brokers convert market orders into limit orders with market price protection. A serverless or autoscaled design whose egress IP changes would simply stop working. See `03_regulatory_compliance.md`.
2. **The broker is the source of truth, not us.** Our database records *intent* and *observations*. Order state is final only once a broker order update or order-book fetch confirms it.
3. **"Exactly once" order placement is the single hardest engineering problem here.** The design uses a persisted intent log with a unique client tag on each order, a single-writer execution service, and an "UNKNOWN" order state that blocks retries until reconciliation resolves it.
4. **Daily re-authentication is unavoidable.** The platform must open each day in a safe "broker disconnected" state and ask the owner to log in. We will **not** automate the broker login by storing the PIN or TOTP seed (see the broker comparison for the one partial exception and why we still avoid it).
5. **A single trading-engine instance is a feature, not a limitation.** Two engines running at the same time is the classic cause of duplicate orders. The engine runs as an enforced singleton (a lease with a fencing token).
6. **Backtest/live parity.** Strategies are pure functions of closed candles plus their parameters. The same code runs in the backtester, the paper trader and live trading, which removes a whole class of "it worked in backtest" bugs.

## 1.4 Explicit scope for Version 1

**In scope:** one owner, one broker, NSE/BSE equity cash (intraday + delivery), index watch (Nifty 50, Bank Nifty, Sensex), five strategies, the full risk engine, paper and live adapters, a dashboard, Telegram alerts, single-region cloud deployment.

**Deferred until V1 is stable:** F&O execution (options need Greeks, lot sizes, expiry handling and higher margin risk), commodities, multiple users, a second broker adapter, AI features.

These deferrals are proposals. See the questions in `07_open_questions.md`.

## 1.5 Requirements that are technically possible but deliberately constrained

| Requested | Constraint applied | Reason |
|---|---|---|
| Fully automated trading | Off by default. Needs a typed confirmation, MFA re-check and a passing pre-flight checklist, and auto-reverts to Manual after the kill switch or a daily-loss breach | Owner safety requirement |
| Run unattended in the cloud | The daily broker login is still manual (owner taps a login link or approves a notification) | Broker ToS and SEBI 2FA requirements |
| Market orders | Sent as broker-supported market orders with protection, or as marketable limit orders | Exchange/broker MPP rules |
| High-frequency signals | Internal hard cap well below 10 orders/second | Exceeding 10 OPS requires exchange algo registration |
| Sharing the platform with others | Not supported | Offering algos to other people requires broker/exchange empanelment and registration |
