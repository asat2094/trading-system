CREATE TABLE IF NOT EXISTS jrn_trades (
    id               BIGSERIAL PRIMARY KEY,
    broker           TEXT NOT NULL,
    source           TEXT NOT NULL,
    source_format    TEXT NOT NULL DEFAULT 'pdf',
    fill_grain       TEXT NOT NULL DEFAULT 'wap',
    source_file      TEXT,
    contract_note_no TEXT,
    is_revised       BOOLEAN DEFAULT FALSE,
    order_no         TEXT,
    order_time       TIME,
    trade_id         TEXT,
    trade_date       DATE NOT NULL,
    trade_time       TIME,
    symbol           TEXT NOT NULL,
    raw_symbol       TEXT NOT NULL,
    underlying       TEXT NOT NULL,
    strike           INTEGER,
    option_type      TEXT,
    expiry           DATE,
    instrument       TEXT,
    exchange         TEXT NOT NULL,
    segment          TEXT NOT NULL,
    product_type     TEXT,
    trade_type       TEXT NOT NULL,
    quantity         INTEGER NOT NULL,
    lot_size         INTEGER,
    lots             INTEGER,
    price            NUMERIC(12,4) NOT NULL,
    brokerage        NUMERIC(10,4) DEFAULT 0,
    closing_rate     NUMERIC(12,4),
    gross_amount     NUMERIC(14,4),
    status           TEXT DEFAULT 'filled',
    remark           TEXT,
    is_force_squared BOOLEAN DEFAULT FALSE,
    chart_snapshot_id BIGINT,
    trade_notes      TEXT,
    imported_at      TIMESTAMPTZ DEFAULT NOW()
);
-- API fills: dedup on trade_id
CREATE UNIQUE INDEX IF NOT EXISTS idx_jt_api_uniq
    ON jrn_trades(broker, trade_id) WHERE trade_id IS NOT NULL;
-- PDF WAP rows: content key dedup (fill_grain='fill' rows dedup via idx_jt_api_uniq instead)
CREATE UNIQUE INDEX IF NOT EXISTS idx_jt_pdf_uniq
    ON jrn_trades(broker, contract_note_no, raw_symbol, trade_type, quantity)
    WHERE source = 'pdf' AND fill_grain = 'wap';
CREATE INDEX IF NOT EXISTS idx_jt_date   ON jrn_trades(trade_date);
CREATE INDEX IF NOT EXISTS idx_jt_sym    ON jrn_trades(symbol);
CREATE INDEX IF NOT EXISTS idx_jt_order  ON jrn_trades(order_no, broker);
CREATE INDEX IF NOT EXISTS idx_jt_broker ON jrn_trades(broker, trade_date);

CREATE TABLE IF NOT EXISTS jrn_trade_pairs (
    id               BIGSERIAL PRIMARY KEY,
    broker           TEXT,
    symbol           TEXT NOT NULL,
    underlying       TEXT NOT NULL,
    strike           INTEGER,
    option_type      TEXT,
    expiry           DATE,
    exchange         TEXT,
    segment          TEXT,
    product_type     TEXT,
    side             TEXT NOT NULL,
    quantity         INTEGER NOT NULL,
    lots             INTEGER,
    lot_size         INTEGER,
    open_date        DATE NOT NULL,
    open_time        TIME,
    entry_price      NUMERIC(12,4) NOT NULL,
    entry_trade_ids  BIGINT[],
    close_date       DATE,
    close_time       TIME,
    exit_price       NUMERIC(12,4),
    exit_trade_ids   BIGINT[],
    gross_pnl        NUMERIC(12,4),
    charges          JSONB,
    net_pnl          NUMERIC(12,4),
    hold_seconds     INTEGER,
    is_intraday      BOOLEAN,
    force_squared    BOOLEAN DEFAULT FALSE,
    chart_snapshot_id       BIGINT,
    exit_chart_snapshot_id  BIGINT,
    trade_rationale  TEXT,
    trade_mistakes   TEXT,
    session_notes    TEXT
);
CREATE INDEX IF NOT EXISTS idx_jtp_date   ON jrn_trade_pairs(open_date);
CREATE INDEX IF NOT EXISTS idx_jtp_sym    ON jrn_trade_pairs(symbol);
CREATE INDEX IF NOT EXISTS idx_jtp_broker ON jrn_trade_pairs(broker, open_date);

CREATE TABLE IF NOT EXISTS jrn_day_summary (
    id                   BIGSERIAL PRIMARY KEY,
    trade_date           DATE NOT NULL,
    broker               TEXT,
    fiscal_year          TEXT,
    total_fills          INTEGER DEFAULT 0,
    total_orders         INTEGER DEFAULT 0,
    total_lots           INTEGER DEFAULT 0,
    failed_order_count   INTEGER DEFAULT 0,
    force_squared_count  INTEGER DEFAULT 0,
    first_trade_time     TIME,
    last_trade_time      TIME,
    avg_hold_seconds     INTEGER,
    time_bucket_pnl      JSONB,
    gross_pnl            NUMERIC(12,4) DEFAULT 0,
    total_brokerage      NUMERIC(12,4) DEFAULT 0,
    total_charges        NUMERIC(12,4) DEFAULT 0,
    net_pnl              NUMERIC(12,4) DEFAULT 0,
    win_pairs            INTEGER DEFAULT 0,
    loss_pairs           INTEGER DEFAULT 0,
    open_pairs           INTEGER DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_jds_date_broker
    ON jrn_day_summary(trade_date, COALESCE(broker, ''));

CREATE TABLE IF NOT EXISTS jrn_rules (
    id          BIGSERIAL PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    rule_type   TEXT NOT NULL,
    enabled     BOOLEAN DEFAULT TRUE,
    config      JSONB NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS jrn_analyses (
    id            BIGSERIAL PRIMARY KEY,
    scope         TEXT NOT NULL,
    scope_id      TEXT NOT NULL,
    triggered_by  TEXT NOT NULL,
    rule_ids      BIGINT[],
    response      TEXT,
    model         TEXT,
    tokens_in     INTEGER,
    tokens_out    INTEGER,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS jrn_chart_snapshots (
    id            BIGSERIAL PRIMARY KEY,
    trade_pair_id BIGINT REFERENCES jrn_trade_pairs(id),
    snapshot_type TEXT,
    symbol        TEXT,
    timeframe     TEXT,
    snapshot_time TIMESTAMPTZ,
    candle_data   JSONB,
    indicators    JSONB,
    image_path    TEXT,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);
