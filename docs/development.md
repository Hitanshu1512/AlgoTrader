# Development Guide

## Prerequisites

| Tool | Version | Check |
|---|---|---|
| Docker + Docker Compose | Docker 24+, Compose v2 | `docker compose version` |
| Python | 3.12+ | `python3 --version` |
| uv | 0.5+ | `uv --version` (install: `curl -LsSf https://astral.sh/uv/install.sh \| sh`) |
| Node.js | 22 LTS | `node --version` |
| PostgreSQL 16 + Redis 7 | Only for running the backend outside Docker | |

## Option A: Run the whole stack in Docker (closest to production)

```bash
cp .env.example .env            # then edit POSTGRES_PASSWORD
./scripts/init-secrets.sh       # creates secrets/master_key (gitignored, back it up)
docker compose up -d --build
docker compose exec api algotrader create-owner --email you@example.com
```

Open **https://localhost** (accept Caddy's local certificate the first time, or run
`docker compose exec caddy caddy trust`). Log in, scan the QR code with an authenticator
app, and enter the 6-digit code. MFA is mandatory.

Useful commands:

```bash
docker compose ps                          # all services healthy?
docker compose logs -f api                 # backend logs (JSON, secrets redacted)
docker compose exec api algotrader --help  # admin CLI
docker compose down                        # stop (data volumes are kept)
```

## Option B: Run backend and frontend locally (fast iteration)

Start Postgres and Redis (Docker or local installs), then:

```bash
cd backend
uv sync
export ALGOTRADER_DATABASE_URL=postgresql+asyncpg://algotrader:algotrader@localhost:5432/algotrader
export ALGOTRADER_COOKIE_SECURE=false ALGOTRADER_PUBLIC_ORIGIN=http://localhost:3000 ALGOTRADER_LOG_JSON=false
export ALGOTRADER_MASTER_KEY_FILE=../secrets/master_key
uv run alembic upgrade head
uv run algotrader create-owner --email you@example.com
uv run uvicorn app.main:create_app --factory --reload --port 8000
```

In a second terminal:

```bash
cd frontend
npm install
NEXT_PUBLIC_WS_URL=ws://localhost:8000/api/ws npm run dev
```

Open **http://localhost:3000**. The Next dev server proxies `/api` to port 8000.
Interactive API docs: http://localhost:8000/api/docs (development only).

## Tests and checks

The backend tests need a PostgreSQL database called `algotrader_test` and Redis
(they use Redis DB 15 and wipe it).

```bash
cd backend
uv run ruff check . && uv run ruff format --check .
uv run mypy app
uv run pytest -q
```

```bash
cd frontend
npm run lint && npm run typecheck && npm run build
```

Expected: `50 passed` for the backend; no lint/type errors; a successful Next build.
CI (`.github/workflows/ci.yml`) runs the same checks, verifies migrations match the
models, builds both Docker images and runs a secret scan.

## Admin CLI

| Command | Purpose |
|---|---|
| `algotrader create-owner --email E` | Create the single owner account (refused if one exists) |
| `algotrader reset-mfa --email E` | Lost authenticator: clears MFA and revokes all sessions |
| `algotrader change-password --email E` | Change password and revoke all sessions |
| `algotrader generate-master-key` | Print a new random master key |

Passwords are read interactively (or from `ALGOTRADER_OWNER_PASSWORD` for automation).
Every command writes an audit entry.

## Security model (Phase 2)

- **Login:** password (Argon2id) → mandatory TOTP. A password-only session can reach only
  MFA endpoints and expires after 10 minutes.
- **Sessions:** opaque random token in an httpOnly, `SameSite=Strict` cookie (`__Host-`
  prefixed over HTTPS). Only a SHA-256 hash is stored. The token rotates when MFA succeeds.
  60-minute idle timeout, 12-hour absolute lifetime.
- **CSRF:** double-submit token header on every state-changing request.
- **Brute force:** 5 failed logins per 15 minutes per email and per IP; TOTP codes are single-use.
- **Step-up MFA:** recent TOTP (15 min) required for sensitive actions (used from Phase 4:
  mode changes, approvals, kill-switch clear).
- **Secrets at rest:** AES-256-GCM envelope encryption with context binding. Local master key
  now, AWS KMS in Phase 7.
- **Audit log:** append-only (DB trigger blocks UPDATE/DELETE/TRUNCATE) and hash-chained.
  Verify it from the System page or `GET /api/audit/verify`.
- **Logs:** JSON with automatic redaction of passwords, tokens, secrets and bearer/JWT strings.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `service "migrate" didn't complete successfully` + `Permission denied: /run/secrets/master_key` | Re-run `./scripts/init-secrets.sh` (it sets the file to 644 inside a 700 directory) |
| `POSTGRES_PASSWORD` error from compose | Create `.env` from `.env.example` |
| Login returns 429 | 5 failed attempts in 15 min. Wait, or restart Redis in development |
| "Invalid or already-used code" with a correct code | Server or phone clock drift > 30 s (enable NTP), or the code was already used. Wait for the next code |
| MFA codes stop working after a restart (local dev) | No master key configured, so an ephemeral one was used. Set `ALGOTRADER_MASTER_KEY_FILE` and run `algotrader reset-mfa` |
| Dashboard shows "Live closed" | API down or session expired. Check `docker compose ps`; log in again |
| Browser warns about the certificate on https://localhost | Expected for Caddy's local CA. Run `docker compose exec caddy caddy trust` or accept it |
| Port 80/443 already in use | Stop the other web server, or change the published ports in `docker-compose.yml` |
