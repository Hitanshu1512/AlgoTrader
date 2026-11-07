# 6. Implementation Roadmap & Pre-Live Risk Register

Status: **Phase 1 draft for owner review** · Complexity: S (≤ 3 days) · M (1–2 weeks) · L (2–4 weeks) of focused work

## 6.1 Phase-wise roadmap

| Phase | Deliverables | Depends on | Complexity | Exit criteria (must pass before next phase) |
|---|---|---|---|---|
| **1. Research & architecture** | This document set: requirements, broker comparison, regulatory, architecture, schema, roadmap, risks, API contract outline | — | S | **Owner approval** + answers to open questions |
| **2. Core application** | Monorepo scaffold, Docker Compose (Postgres, Redis, api, frontend, Caddy), config/settings, Alembic migrations of the schema, owner auth (Argon2 + TOTP MFA, sessions), audit log service, dashboard shell (layout, nav, auth pages, WS connection), CI (ruff, mypy, pytest, eslint, tsc) | 1 | M | `docker compose up` gives a login-protected dashboard; CI green; auth + audit tests |
| **3. Broker integration** | `BrokerAdapter` interface, chosen broker adapter (auth flow, funds, holdings, positions, orders, trades, quotes, depth, historical, WS feed, order updates), encrypted credential store, rate limiter, instrument master sync, PaperBroker, read-only reconciliation | 2 | L | Contract tests pass against **sandbox** (if available) and real account in **read-only** mode; no write call possible yet outside sandbox |
| **4. Trading engine** | Indicators (unit-tested vs references), 5 strategies, candle builder + staleness monitor, signal service with dedupe, risk engine (all account- and position-level rules), position sizing, executor with idempotent state machine, exit manager, kill switch, mode control | 3 | L | Trading-safety test suite green: duplicate prevention, timeout→UNKNOWN→reconcile, kill switch, stale data halts, restart recovery, rate cap |
| **5. Backtesting & paper trading** | Historical data ingestion, event-driven backtester reusing strategy/risk code, Indian charges model, slippage model, reports (return, win rate, PF, max DD, avg win/loss, R:R, equity curve), paper-trading environment on live data | 4 | M–L | Backtest/paper parity test (same signals on same data); ≥ 2–4 weeks of paper trading with clean reconciliation logs |
| **6. Dashboard & notifications** | Overview, market watch, portfolio, order management, strategy center, risk page with kill switch, analytics, system monitoring; Telegram notifications with per-event config | 4 (parallel with 5) | L | E2E tests (Playwright) for critical flows: approve order, kill switch, mode change |
| **7. Cloud deployment** | AWS infra (EC2 + Elastic IP, RDS, SSM/KMS, S3, CloudWatch), Caddy TLS, deploy scripts, staging + prod, backups, alarms, runbooks | 2–6 | M | Chaos drills pass: kill processes, reboot host, drop network, expire token, all with safe recovery; restore from backup verified |
| **8. Controlled live trading** | Static IP registered with broker; live adapter enabled with tiny capital and tight limits; Manual mode only → Semi-auto → (optionally) Full-auto per strategy | 7 + paper track record | M (calendar time: 4–8 weeks) | Defined go/no-go checklist per stage (below) |

**Rough total:** about 3–5 months of part-time-equivalent work for a production-quality V1. Phases 5 and 6 can run in parallel.

### Phase 8 staged go-live checklist

1. **Stage 8a, Manual, 1 instrument, ≤ ₹10–25k capital, max 1 position, daily loss cap ~1%.** Two weeks of zero reconciliation drift and zero unexplained order states.
2. **Stage 8b, Semi-auto**, same limits, then gradually widen the instrument list.
3. **Stage 8c, Full-auto per strategy**, only for strategies with ≥ N paper trades and a live record in 8a/8b that matches paper behaviour within tolerance. Explicit owner activation each time.

## 6.2 API contract outline (Phase 2–4 detail to follow)

| Method & path | Purpose |
|---|---|
| `POST /auth/login`, `POST /auth/mfa/verify`, `POST /auth/logout` | Platform auth |
| `GET /broker/login-url`, `GET /broker/callback`, `GET /broker/status` | Official broker auth flow |
| `GET /account/summary`, `/holdings`, `/positions`, `/funds` | Reconciled account data |
| `GET /orders`, `POST /orders` (manual intent), `PATCH /orders/{id}`, `DELETE /orders/{id}` | Order management (all go through the risk gate) |
| `GET /intents?status=AWAITING_APPROVAL`, `POST /intents/{id}/approve`, `/decline` | Approval workflow |
| `GET/PUT /control/mode`, `POST /control/kill-switch`, `POST /control/kill-switch/clear` | Mode & emergency (MFA-fresh session required) |
| `GET/POST /risk/config`, `GET /risk/exposure` | Risk limits (versioned) |
| `GET /strategies`, `GET/POST /strategies/{id}/config`, `POST /strategies/{id}/enable` | Strategy center |
| `POST /backtests`, `GET /backtests/{id}` | Backtesting |
| `GET /analytics/performance` | Analytics |
| `GET /system/health`, `/system/events` | Monitoring |
| `WS /ws` | Topics: `ticks`, `orders`, `positions`, `signals`, `intents`, `account`, `system` |

## 6.3 Pre-live risk register

Severity: 🔴 critical · 🟠 high · 🟡 medium. **All 🔴 items must be closed before Phase 8.**

### Execution & financial risks
| # | Risk | Sev | Mitigation |
|---|---|---|---|
| E1 | Duplicate orders from retries, double engines, or replayed events | 🔴 | Persisted intent before submit, unique client tag, UNKNOWN state, singleton lease + fencing, dedupe keys, safety tests |
| E2 | Timeout treated as failure → re-submit | 🔴 | Never retry submit; reconcile by tag first |
| E3 | Position left unprotected (process crash, network loss) | 🔴 | Broker-side SL immediately after fill; startup reconciliation; alert if any open position lacks a protective order |
| E4 | Partial fills mis-tracked (wrong SL quantity) | 🟠 | SL quantity follows `filled_quantity` from broker updates; reconciler cross-checks |
| E5 | Market-protection/limit conversion leaves exit unfilled in fast markets | 🟠 | Exit loop re-prices with bounded aggression; escalation alert |
| E6 | Strategy overfit / not profitable live | 🟠 | Walk-forward backtests, paper period, tiny initial capital, consecutive-loss and weekly-loss breakers |
| E7 | Wrong instrument token (expired master, symbol change) | 🟠 | Daily instrument master refresh with version; reject orders on tokens not in today's master |
| E8 | Charges/slippage underestimated → backtest overstates returns | 🟡 | Versioned charges model; compare paper vs live costs |
| E9 | Manual trades in the broker app conflict with the bot | 🟡 | Reconciler detects external changes → pauses automation on that instrument and alerts |

### Data & operational risks
| # | Risk | Sev | Mitigation |
|---|---|---|---|
| O1 | Stale or missing market data → bad signals | 🔴 | Staleness monitor; no entries if stale; gap backfill before evaluation; candle completeness flag |
| O2 | Broker API/WS outage | 🔴 | Fail-closed for entries; exits allowed; reconnect with backoff; broker-side stops already in place |
| O3 | Daily token expiry missed → no trading or failing calls | 🟠 | Morning login reminder; dashboard banner; system stays safe while disconnected |
| O4 | Host failure / restart mid-session | 🟠 | Docker restart policies, recovery sequence (D6), CloudWatch alarm on health check |
| O5 | Static IP changes (instance replaced) → order calls rejected | 🟠 | Elastic IP kept separately from the instance; documented re-attach procedure; staging uses secondary IP |
| O6 | Market holidays / special sessions | 🟡 | Exchange calendar table; scheduler refuses to start sessions on holidays |
| O7 | Clock drift → wrong candle boundaries | 🟡 | chrony/NTP on host; candles keyed on exchange timestamps |
| O8 | Database loss | 🟠 | RDS PITR + S3 dumps + restore drill |

### Security risks
| # | Risk | Sev | Mitigation |
|---|---|---|---|
| S1 | Broker credential/token leak | 🔴 | KMS envelope encryption, SSM, no secrets in env files committed, log redaction filter, secret scanning in CI |
| S2 | Dashboard account takeover → attacker places trades | 🔴 | Argon2id + mandatory TOTP, short sessions, MFA re-check for mode changes/approvals, login alerts on Telegram, IP rate limiting |
| S3 | Telegram used as a control channel and spoofed | 🟠 | Telegram is notify-only in V1; approvals happen in the authenticated dashboard |
| S4 | Server compromise | 🟠 | No SSH port (SSM Session Manager), least-privilege IAM, patched images, no PIN/TOTP seed stored |
| S5 | CSRF/XSS on dashboard | 🟠 | SameSite=strict httpOnly cookies, CSRF tokens, strict CSP, React escaping |
| S6 | Supply-chain risk (malicious packages) | 🟡 | Pinned lockfiles, Dependabot, minimal dependencies |

### Regulatory risks
| # | Risk | Sev | Mitigation |
|---|---|---|---|
| R1 | Exceeding 10 OPS → unregistered algo | 🔴 | Hard cap ≤ 5/s (DB constraint `BETWEEN 1 AND 9`, default 5) |
| R2 | Orders from non-registered IP | 🟠 | All order calls from the Elastic IP host only; startup check compares public egress IP to the registered one |
| R3 | Rule changes by SEBI/exchange/broker | 🟡 | Quarterly review of broker announcements; compliance notes in `docs/` |
| R4 | Sharing access with others | 🟡 | Single-owner design; documented restriction |
