-- AlgoTrader — PostgreSQL 16 schema DRAFT (Phase 1 design artifact)
-- This file is a design reference. Phase 2 implements it as Alembic migrations.
-- Conventions: UUID PKs (gen_random_uuid), timestamptz in UTC, money as NUMERIC(18,4),
-- quantities as BIGINT, enums as CHECK-constrained TEXT for easy evolution.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ───────────────────────── Identity & access ─────────────────────────
CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,                 -- Argon2id
    mfa_secret_enc  BYTEA,                         -- envelope-encrypted TOTP seed for *platform* login
    mfa_enabled     BOOLEAN NOT NULL DEFAULT FALSE,
    role            TEXT NOT NULL DEFAULT 'owner' CHECK (role IN ('owner','viewer')),
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE user_sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash      BYTEA NOT NULL UNIQUE,         -- SHA-256 of opaque session token
    mfa_verified_at TIMESTAMPTZ,
    ip              INET,
    user_agent      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ NOT NULL,
    revoked_at      TIMESTAMPTZ
);
CREATE INDEX ON user_sessions (user_id, expires_at);

-- ───────────────────────── Broker accounts & secrets ─────────────────────────
CREATE TABLE broker_accounts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id),
    broker          TEXT NOT NULL CHECK (broker IN ('upstox','zerodha','angelone','dhan','fyers','paper')),
    environment     TEXT NOT NULL CHECK (environment IN ('live','paper','sandbox')),
    client_code_masked TEXT NOT NULL,              -- e.g. "AB****12" — never the full ID in logs/UI
    registered_static_ip INET,
    status          TEXT NOT NULL DEFAULT 'disconnected'
                    CHECK (status IN ('disconnected','connected','expired','error')),
    last_login_at   TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, broker, environment)
);

-- Only ciphertext lives here. Data-encryption keys are wrapped by AWS KMS (envelope encryption).
-- API key/secret are long-lived; access tokens are daily and purged by the scheduler after session close.
CREATE TABLE encrypted_credentials (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    broker_account_id UUID NOT NULL REFERENCES broker_accounts(id) ON DELETE CASCADE,
    kind            TEXT NOT NULL CHECK (kind IN ('api_key','api_secret','access_token','refresh_token','feed_token')),
    ciphertext      BYTEA NOT NULL,
    wrapped_dek     BYTEA NOT NULL,
    kms_key_id      TEXT NOT NULL,
    expires_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (broker_account_id, kind)
);

-- ───────────────────────── Reference data ─────────────────────────
CREATE TABLE instruments (
    id              BIGSERIAL PRIMARY KEY,
    broker          TEXT NOT NULL,
    broker_token    TEXT NOT NULL,                 -- broker's instrument key/token
    exchange        TEXT NOT NULL CHECK (exchange IN ('NSE','BSE','NFO','BFO','MCX')),
    segment         TEXT NOT NULL,                 -- EQ, INDEX, FUT, OPT
    symbol          TEXT NOT NULL,
    isin            TEXT,
    name            TEXT,
    sector          TEXT,
    lot_size        INTEGER NOT NULL DEFAULT 1,
    tick_size       NUMERIC(10,4) NOT NULL,
    expiry          DATE,
    strike          NUMERIC(18,4),
    option_type     TEXT CHECK (option_type IN ('CE','PE')),
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    master_date     DATE NOT NULL,                 -- instrument-master version; guards against stale tokens
    UNIQUE (broker, broker_token, master_date)
);
CREATE INDEX ON instruments (exchange, symbol) WHERE is_active;

CREATE TABLE exchange_calendar (
    exchange        TEXT NOT NULL,
    trade_date      DATE NOT NULL,
    is_trading_day  BOOLEAN NOT NULL,
    open_time       TIME,                          -- IST
    close_time      TIME,
    note            TEXT,                          -- holiday name / special session (e.g. Muhurat)
    PRIMARY KEY (exchange, trade_date)
);

CREATE TABLE watchlists (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id),
    name            TEXT NOT NULL,
    UNIQUE (user_id, name)
);
CREATE TABLE watchlist_items (
    watchlist_id    UUID NOT NULL REFERENCES watchlists(id) ON DELETE CASCADE,
    instrument_id   BIGINT NOT NULL REFERENCES instruments(id),
    position        INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (watchlist_id, instrument_id)
);

-- Candles only (ticks stay in Redis). Range-partitioned monthly.
CREATE TABLE market_data_candles (
    instrument_id   BIGINT NOT NULL REFERENCES instruments(id),
    timeframe       TEXT NOT NULL CHECK (timeframe IN ('1m','3m','5m','15m','30m','1h','1d')),
    ts              TIMESTAMPTZ NOT NULL,          -- candle OPEN time
    open            NUMERIC(18,4) NOT NULL,
    high            NUMERIC(18,4) NOT NULL,
    low             NUMERIC(18,4) NOT NULL,
    close           NUMERIC(18,4) NOT NULL,
    volume          BIGINT NOT NULL,
    oi              BIGINT,
    source          TEXT NOT NULL CHECK (source IN ('broker_hist','live_built')),
    is_complete     BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (instrument_id, timeframe, ts)
) PARTITION BY RANGE (ts);
-- Partitions created by a scheduler job, e.g.:
-- CREATE TABLE market_data_candles_2026_11 PARTITION OF market_data_candles
--   FOR VALUES FROM ('2026-11-01') TO ('2026-12-01');

-- ───────────────────────── Strategies ─────────────────────────
CREATE TABLE strategies (
    id              TEXT PRIMARY KEY,              -- 'ma_crossover', 'rsi', 'macd', 'vwap_intraday', 'breakout'
    name            TEXT NOT NULL,
    description     TEXT,
    code_version    TEXT NOT NULL                  -- git SHA of strategy implementation
);

CREATE TABLE strategy_configurations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id),
    strategy_id     TEXT NOT NULL REFERENCES strategies(id),
    version         INTEGER NOT NULL,              -- immutable versions; edits create a new row
    is_enabled      BOOLEAN NOT NULL DEFAULT FALSE,
    environment     TEXT NOT NULL CHECK (environment IN ('paper','live')),
    params          JSONB NOT NULL,                -- validated by Pydantic model per strategy
    timeframe       TEXT NOT NULL,
    instrument_ids  BIGINT[] NOT NULL,
    product         TEXT NOT NULL CHECK (product IN ('INTRADAY','DELIVERY')),
    max_trades_per_day   INTEGER NOT NULL DEFAULT 2,
    max_capital_alloc    NUMERIC(18,4) NOT NULL,
    stop_loss_rule  JSONB NOT NULL,                -- {type: 'atr'|'pct'|'swing', value: ...}
    target_rule     JSONB NOT NULL,
    trailing_rule   JSONB,
    time_exit       TIME,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by_session UUID REFERENCES user_sessions(id),
    UNIQUE (user_id, strategy_id, environment, version)
);
-- Only one enabled version per strategy per environment:
CREATE UNIQUE INDEX one_enabled_config
    ON strategy_configurations (user_id, strategy_id, environment) WHERE is_enabled;

-- ───────────────────────── Signals, intents, orders ─────────────────────────
CREATE TABLE trading_signals (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_config_id UUID NOT NULL REFERENCES strategy_configurations(id),
    instrument_id   BIGINT NOT NULL REFERENCES instruments(id),
    side            TEXT NOT NULL CHECK (side IN ('BUY','SELL')),
    signal_type     TEXT NOT NULL CHECK (signal_type IN ('ENTRY','EXIT')),
    candle_ts       TIMESTAMPTZ NOT NULL,          -- closed candle that produced it
    entry_price     NUMERIC(18,4),
    stop_loss       NUMERIC(18,4),
    target          NUMERIC(18,4),
    suggested_qty   BIGINT,
    risk_reward     NUMERIC(8,3),
    reasoning       JSONB NOT NULL,                -- indicator values that triggered it
    dedupe_key      TEXT NOT NULL UNIQUE,          -- prevents duplicate signals
    status          TEXT NOT NULL DEFAULT 'NEW'
                    CHECK (status IN ('NEW','INTENT_CREATED','IGNORED','EXPIRED')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON trading_signals (created_at DESC);

CREATE TABLE order_intents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    broker_account_id UUID NOT NULL REFERENCES broker_accounts(id),
    signal_id       UUID REFERENCES trading_signals(id),     -- NULL for manual orders
    position_id     UUID,                                    -- set for exits/SL orders
    origin          TEXT NOT NULL CHECK (origin IN ('STRATEGY','MANUAL','EXIT_MANAGER','KILL_SWITCH','RECONCILER')),
    mode_at_creation TEXT NOT NULL CHECK (mode_at_creation IN ('MANUAL','SEMI_AUTO','FULL_AUTO')),
    instrument_id   BIGINT NOT NULL REFERENCES instruments(id),
    side            TEXT NOT NULL CHECK (side IN ('BUY','SELL')),
    quantity        BIGINT NOT NULL CHECK (quantity > 0),
    order_type      TEXT NOT NULL CHECK (order_type IN ('MARKET','LIMIT','SL','SL-M')),
    product         TEXT NOT NULL CHECK (product IN ('INTRADAY','DELIVERY')),
    limit_price     NUMERIC(18,4),
    trigger_price   NUMERIC(18,4),
    status          TEXT NOT NULL CHECK (status IN (
                       'PENDING_RISK','REJECTED_RISK','AWAITING_APPROVAL','APPROVED',
                       'DECLINED','EXPIRED','SUBMITTED','CANCELLED')),
    risk_result     JSONB,                         -- every rule evaluated + values
    approved_by_session UUID REFERENCES user_sessions(id),
    approved_at     TIMESTAMPTZ,
    expires_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON order_intents (status, created_at);

CREATE TABLE orders (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    intent_id       UUID NOT NULL REFERENCES order_intents(id),
    broker_account_id UUID NOT NULL REFERENCES broker_accounts(id),
    client_order_id TEXT NOT NULL,                 -- sent as broker tag; idempotency anchor
    broker_order_id TEXT,
    instrument_id   BIGINT NOT NULL REFERENCES instruments(id),
    side            TEXT NOT NULL,
    quantity        BIGINT NOT NULL,
    filled_quantity BIGINT NOT NULL DEFAULT 0,
    avg_fill_price  NUMERIC(18,4),
    order_type      TEXT NOT NULL,
    limit_price     NUMERIC(18,4),
    trigger_price   NUMERIC(18,4),
    status          TEXT NOT NULL CHECK (status IN (
                       'SUBMITTING','UNKNOWN','OPEN','TRIGGER_PENDING','PARTIALLY_FILLED',
                       'FILLED','CANCELLED','REJECTED_BROKER','FAILED_NOT_PLACED')),
    reject_reason   TEXT,
    fencing_token   BIGINT NOT NULL,               -- executor lease token at write time
    submitted_at    TIMESTAMPTZ,
    last_broker_update_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (broker_account_id, client_order_id),
    UNIQUE (broker_account_id, broker_order_id)
);
CREATE INDEX ON orders (status) WHERE status IN ('SUBMITTING','UNKNOWN','OPEN','TRIGGER_PENDING','PARTIALLY_FILLED');

CREATE TABLE order_events (                         -- append-only
    id              BIGSERIAL PRIMARY KEY,
    order_id        UUID NOT NULL REFERENCES orders(id),
    event_type      TEXT NOT NULL,                 -- SUBMIT_REQUEST, SUBMIT_TIMEOUT, BROKER_UPDATE, MODIFY, CANCEL_REQUEST, RECONCILED...
    from_status     TEXT,
    to_status       TEXT,
    payload         JSONB NOT NULL,                -- sanitized broker response (no tokens)
    latency_ms      INTEGER,
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON order_events (order_id, occurred_at);

CREATE TABLE trades (                               -- broker fills (trade book)
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id        UUID NOT NULL REFERENCES orders(id),
    broker_trade_id TEXT NOT NULL,
    quantity        BIGINT NOT NULL,
    price           NUMERIC(18,4) NOT NULL,
    charges         NUMERIC(18,4),
    traded_at       TIMESTAMPTZ NOT NULL,
    UNIQUE (order_id, broker_trade_id)
);

-- ───────────────────────── Positions & holdings ─────────────────────────
CREATE TABLE positions (                            -- our managed trade lifecycle (entry → exit)
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    broker_account_id UUID NOT NULL REFERENCES broker_accounts(id),
    strategy_config_id UUID REFERENCES strategy_configurations(id),
    instrument_id   BIGINT NOT NULL REFERENCES instruments(id),
    product         TEXT NOT NULL,
    side            TEXT NOT NULL CHECK (side IN ('LONG','SHORT')),
    quantity_open   BIGINT NOT NULL,
    avg_entry_price NUMERIC(18,4) NOT NULL,
    stop_loss       NUMERIC(18,4),
    target          NUMERIC(18,4),
    trailing_state  JSONB,
    protective_order_id UUID REFERENCES orders(id),   -- broker-side SL
    realized_pnl    NUMERIC(18,4) NOT NULL DEFAULT 0,
    status          TEXT NOT NULL CHECK (status IN ('OPEN','CLOSING','CLOSED')),
    exit_reason     TEXT CHECK (exit_reason IN ('TARGET','STOP_LOSS','TRAILING_SL','TIME_EXIT','SIGNAL','MANUAL','KILL_SWITCH','EXTERNAL')),
    opened_at       TIMESTAMPTZ NOT NULL,
    closed_at       TIMESTAMPTZ
);
CREATE INDEX ON positions (broker_account_id, status);
ALTER TABLE order_intents ADD CONSTRAINT order_intents_position_fk
    FOREIGN KEY (position_id) REFERENCES positions(id);

CREATE TABLE broker_position_snapshots (            -- raw broker view for reconciliation
    id              BIGSERIAL PRIMARY KEY,
    broker_account_id UUID NOT NULL REFERENCES broker_accounts(id),
    taken_at        TIMESTAMPTZ NOT NULL,
    kind            TEXT NOT NULL CHECK (kind IN ('positions','holdings','funds')),
    data            JSONB NOT NULL
);
CREATE INDEX ON broker_position_snapshots (broker_account_id, kind, taken_at DESC);

CREATE TABLE holdings (                             -- latest reconciled holdings
    broker_account_id UUID NOT NULL REFERENCES broker_accounts(id),
    instrument_id   BIGINT NOT NULL REFERENCES instruments(id),
    quantity        BIGINT NOT NULL,
    avg_price       NUMERIC(18,4) NOT NULL,
    last_price      NUMERIC(18,4),
    synced_at       TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (broker_account_id, instrument_id)
);

-- ───────────────────────── Risk & control state ─────────────────────────
CREATE TABLE risk_configurations (                  -- versioned, immutable rows
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    broker_account_id UUID NOT NULL REFERENCES broker_accounts(id),
    version         INTEGER NOT NULL,
    max_auto_capital        NUMERIC(18,4) NOT NULL,
    max_per_trade_value     NUMERIC(18,4) NOT NULL,
    max_risk_per_trade_pct  NUMERIC(6,3)  NOT NULL,   -- % of equity
    max_daily_loss          NUMERIC(18,4) NOT NULL,
    max_weekly_loss         NUMERIC(18,4) NOT NULL,
    max_trades_per_day      INTEGER NOT NULL,
    max_open_positions      INTEGER NOT NULL,
    max_instrument_exposure_pct NUMERIC(6,3) NOT NULL,
    max_sector_exposure_pct NUMERIC(6,3) NOT NULL,
    max_margin_utilization_pct NUMERIC(6,3) NOT NULL,
    max_consecutive_losses  INTEGER NOT NULL,
    min_risk_reward         NUMERIC(6,3) NOT NULL,
    max_data_staleness_ms   INTEGER NOT NULL DEFAULT 5000,
    max_orders_per_second   INTEGER NOT NULL DEFAULT 5 CHECK (max_orders_per_second BETWEEN 1 AND 9),
    kill_switch_position_policy TEXT NOT NULL DEFAULT 'PROTECT_ONLY' CHECK (kill_switch_position_policy IN ('FLATTEN_ALL','PROTECT_ONLY')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by_session UUID REFERENCES user_sessions(id),
    UNIQUE (broker_account_id, version)
);

CREATE TABLE trading_control_state (                -- one row per account; every change audited
    broker_account_id UUID PRIMARY KEY REFERENCES broker_accounts(id),
    mode            TEXT NOT NULL DEFAULT 'MANUAL' CHECK (mode IN ('MANUAL','SEMI_AUTO','FULL_AUTO')),
    trading_halted  BOOLEAN NOT NULL DEFAULT FALSE,
    kill_switch_active BOOLEAN NOT NULL DEFAULT FALSE,
    halt_reason     TEXT,
    active_risk_config_id UUID REFERENCES risk_configurations(id),
    version         BIGINT NOT NULL DEFAULT 1,     -- optimistic locking
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ───────────────────────── Performance ─────────────────────────
CREATE TABLE account_snapshots (
    id              BIGSERIAL PRIMARY KEY,
    broker_account_id UUID NOT NULL REFERENCES broker_accounts(id),
    taken_at        TIMESTAMPTZ NOT NULL,
    equity          NUMERIC(18,4) NOT NULL,
    available_cash  NUMERIC(18,4) NOT NULL,
    margin_used     NUMERIC(18,4) NOT NULL,
    unrealized_pnl  NUMERIC(18,4) NOT NULL,
    realized_pnl_today NUMERIC(18,4) NOT NULL
);
CREATE INDEX ON account_snapshots (broker_account_id, taken_at DESC);

CREATE TABLE daily_performance (
    broker_account_id UUID NOT NULL REFERENCES broker_accounts(id),
    trade_date      DATE NOT NULL,
    strategy_config_id UUID REFERENCES strategy_configurations(id),  -- NULL = account total
    gross_pnl       NUMERIC(18,4) NOT NULL,
    charges         NUMERIC(18,4) NOT NULL,
    net_pnl         NUMERIC(18,4) NOT NULL,
    trades          INTEGER NOT NULL,
    wins            INTEGER NOT NULL,
    losses          INTEGER NOT NULL,
    max_drawdown    NUMERIC(18,4)
);
CREATE UNIQUE INDEX daily_performance_uq ON daily_performance
    (broker_account_id, trade_date, COALESCE(strategy_config_id, '00000000-0000-0000-0000-000000000000'::uuid));

CREATE TABLE backtest_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_id     TEXT NOT NULL REFERENCES strategies(id),
    params          JSONB NOT NULL,
    code_version    TEXT NOT NULL,
    period_start    DATE NOT NULL,
    period_end      DATE NOT NULL,
    assumptions     JSONB NOT NULL,                -- slippage, charges table version, capital
    metrics         JSONB,
    equity_curve    JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ───────────────────────── Notifications, logs, audit ─────────────────────────
CREATE TABLE notifications (
    id              BIGSERIAL PRIMARY KEY,
    user_id         UUID NOT NULL REFERENCES users(id),
    channel         TEXT NOT NULL CHECK (channel IN ('telegram','email','dashboard')),
    event_type      TEXT NOT NULL,
    payload         JSONB NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('PENDING','SENT','FAILED')),
    attempts        INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    sent_at         TIMESTAMPTZ
);

CREATE TABLE system_events (                        -- operational events (connectivity, errors); app logs go to CloudWatch
    id              BIGSERIAL PRIMARY KEY,
    service         TEXT NOT NULL,
    level           TEXT NOT NULL CHECK (level IN ('INFO','WARN','ERROR','CRITICAL')),
    event_type      TEXT NOT NULL,
    message         TEXT NOT NULL,
    context         JSONB,
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON system_events (occurred_at DESC);

CREATE TABLE audit_logs (                           -- append-only, hash-chained for tamper evidence
    id              BIGSERIAL PRIMARY KEY,
    user_id         UUID REFERENCES users(id),
    session_id      UUID REFERENCES user_sessions(id),
    actor           TEXT NOT NULL,                 -- 'user' | 'engine' | 'executor' | 'reconciler' | 'scheduler'
    action          TEXT NOT NULL,                 -- MODE_CHANGE, KILL_SWITCH_ON, RISK_CONFIG_UPDATE, ORDER_APPROVE, BROKER_LOGIN...
    entity_type     TEXT,
    entity_id       TEXT,
    before          JSONB,
    after           JSONB,
    ip              INET,
    prev_hash       BYTEA,
    row_hash        BYTEA NOT NULL,                -- sha256(prev_hash || canonical row)
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON audit_logs (occurred_at DESC);
-- Application DB role gets INSERT/SELECT only on audit_logs and order_events (no UPDATE/DELETE).
