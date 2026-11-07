# AlgoTrader

A cloud-hosted, broker-connected algorithmic trading platform for the Indian markets (NSE/BSE), built for one owner's personal brokerage account.

> **Status: Phase 2 (core application) complete.** Login with mandatory 2FA, audit trail, dashboard shell with live status, Docker stack and CI. **No broker connection yet** (Upstox adapter is Phase 3). Live trading stays disabled until the platform passes testing, reconciliation and risk-control validation (Phase 8).

## Quick start

```bash
cp .env.example .env            # set POSTGRES_PASSWORD
./scripts/init-secrets.sh
docker compose up -d --build
docker compose exec api algotrader create-owner --email you@example.com
```

Then open https://localhost. Full instructions, tests and troubleshooting: [docs/development.md](docs/development.md).

| Path | Contents |
|---|---|
| `backend/` | FastAPI app (Python 3.12, SQLAlchemy 2 async, Alembic, uv) |
| `frontend/` | Next.js 15 dashboard (TypeScript, Tailwind) |
| `infrastructure/docker/` | Caddy reverse proxy config |
| `docs/` | Architecture, decisions, development guide |

## Phase 1 documents (architecture)

| # | Document |
|---|---|
| 1 | [Requirements analysis](docs/phase1/01_requirements_analysis.md) |
| 2 | [Indian broker API comparison & recommendation](docs/phase1/02_broker_api_comparison.md) |
| 3 | [Regulatory & compliance (SEBI retail algo framework)](docs/phase1/03_regulatory_compliance.md) |
| 4 | [System architecture & cloud deployment](docs/phase1/04_architecture.md) |
| 5 | [Database design](docs/phase1/05_database_schema.md) · [DDL draft](docs/phase1/schema_draft.sql) |
| 6 | [Roadmap & pre-live risk register](docs/phase1/06_roadmap_and_risks.md) |
| 7 | [Open questions for the owner](docs/phase1/07_open_questions.md) · [Decision log](docs/decisions.md) |

## Safety principles

- **Manual mode by default.** Full automation needs explicit, MFA-confirmed activation.
- Every order passes a **backend risk engine**. Unknown state means no new entries (fail closed).
- **No blind retries.** A timed-out order is reconciled with the broker before anything else happens.
- **Kill switch** halts entries, cancels pending orders, and applies a configured position policy.
- Official broker APIs and auth flows only. Secrets are encrypted and never logged or committed.
