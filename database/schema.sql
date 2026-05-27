-- =============================================================================
-- Finance Controller AI System — PostgreSQL Schema
-- Client: Mike (e-commerce/dropshipping)
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ---------------------------------------------------------------------------
-- Core P&L table — one row per store per calendar day
--
-- Multi-store architecture:
--   store_id = 'default' for the current single store.
--   When additional Shopify stores are added, each gets its own store_id
--   (e.g. 'store_nl', 'store_de'). The unique key is (store_id, report_date)
--   so the same date can exist once per store.
--
--   weekly_summary and monthly_summary do NOT have store_id yet — they
--   aggregate across all stores. Add store_id to those tables when
--   per-store reporting is required.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS daily_pl (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    store_id        VARCHAR(100) NOT NULL DEFAULT 'default',
    report_date     DATE         NOT NULL,
    revenue         NUMERIC(14,2),
    cog             NUMERIC(14,2),
    adspend_google     NUMERIC(14,2),
    adspend_pinterest  NUMERIC(14,2),
    mediabuying        NUMERIC(14,2),
    employee_cost   NUMERIC(14,2),
    transaction_fee NUMERIC(14,2),
    profit          NUMERIC(14,2),
    roas            NUMERIC(8,4),
    profit_pct      NUMERIC(8,4),
    cog_pct         NUMERIC(8,4),
    cvr_pct         NUMERIC(8,4),
    cpc             NUMERIC(8,4),
    refunds         NUMERIC(14,2),
    refund_pct      NUMERIC(8,4),
    source          VARCHAR(100) DEFAULT 'google_sheets',
    synced_at       TIMESTAMPTZ  DEFAULT NOW(),
    created_at      TIMESTAMPTZ  DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  DEFAULT NOW(),
    CONSTRAINT uq_daily_pl_store_date UNIQUE (store_id, report_date)
);

CREATE INDEX IF NOT EXISTS idx_daily_pl_report_date ON daily_pl (report_date DESC);
CREATE INDEX IF NOT EXISTS idx_daily_pl_store_id    ON daily_pl (store_id);

-- ---------------------------------------------------------------------------
-- Migration block — idempotent, safe to run on existing installations.
-- Fresh installs: the ADD COLUMN and DROP CONSTRAINT are no-ops because
-- the CREATE TABLE above already has the correct shape.
-- Existing installs (created before store_id was added): this block adds
-- the column and replaces the single-column unique key with the composite one.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    -- Add store_id if the table was created without it
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'daily_pl' AND column_name = 'store_id'
    ) THEN
        ALTER TABLE daily_pl
            ADD COLUMN store_id VARCHAR(100) NOT NULL DEFAULT 'default';
    END IF;

    -- Add adspend_pinterest if not present (added May 2026)
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'daily_pl' AND column_name = 'adspend_pinterest'
    ) THEN
        ALTER TABLE daily_pl
            ADD COLUMN adspend_pinterest NUMERIC(14,2);
    END IF;

    -- Drop the old single-column unique constraint if it still exists
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'daily_pl_report_date_key' AND conrelid = 'daily_pl'::regclass
    ) THEN
        ALTER TABLE daily_pl DROP CONSTRAINT daily_pl_report_date_key;
    END IF;

    -- Add the composite unique constraint if it does not exist yet
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_daily_pl_store_date' AND conrelid = 'daily_pl'::regclass
    ) THEN
        ALTER TABLE daily_pl
            ADD CONSTRAINT uq_daily_pl_store_date UNIQUE (store_id, report_date);
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- Trigger: auto-update updated_at on daily_pl
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_daily_pl_updated_at ON daily_pl;
CREATE TRIGGER trg_daily_pl_updated_at
    BEFORE UPDATE ON daily_pl
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- Weekly summary — auto-calculated aggregates per ISO week
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS weekly_summary (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    week_start      DATE        NOT NULL,
    week_end        DATE        NOT NULL,
    iso_year        INTEGER     NOT NULL,
    iso_week        INTEGER     NOT NULL,
    total_revenue   NUMERIC(14,2),
    total_cog       NUMERIC(14,2),
    total_adspend   NUMERIC(14,2),
    total_mediabuying NUMERIC(14,2),
    total_employee  NUMERIC(14,2),
    total_transaction_fee NUMERIC(14,2),
    total_profit    NUMERIC(14,2),
    avg_roas        NUMERIC(8,4),
    avg_profit_pct  NUMERIC(8,4),
    avg_cog_pct     NUMERIC(8,4),
    avg_cvr_pct     NUMERIC(8,4),
    avg_cpc         NUMERIC(8,4),
    total_refunds   NUMERIC(14,2),
    avg_refund_pct  NUMERIC(8,4),
    days_in_week    INTEGER,
    calculated_at   TIMESTAMPTZ  DEFAULT NOW(),
    UNIQUE (iso_year, iso_week)
);

CREATE INDEX IF NOT EXISTS idx_weekly_summary_week ON weekly_summary (iso_year DESC, iso_week DESC);

-- ---------------------------------------------------------------------------
-- Monthly summary — auto-calculated aggregates per calendar month
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS monthly_summary (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    year            INTEGER     NOT NULL,
    month           INTEGER     NOT NULL,
    month_start     DATE        NOT NULL,
    month_end       DATE        NOT NULL,
    total_revenue   NUMERIC(14,2),
    total_cog       NUMERIC(14,2),
    total_adspend   NUMERIC(14,2),
    total_mediabuying NUMERIC(14,2),
    total_employee  NUMERIC(14,2),
    total_transaction_fee NUMERIC(14,2),
    total_profit    NUMERIC(14,2),
    avg_roas        NUMERIC(8,4),
    avg_profit_pct  NUMERIC(8,4),
    avg_cog_pct     NUMERIC(8,4),
    avg_cvr_pct     NUMERIC(8,4),
    avg_cpc         NUMERIC(8,4),
    total_refunds   NUMERIC(14,2),
    avg_refund_pct  NUMERIC(8,4),
    days_in_month   INTEGER,
    calculated_at   TIMESTAMPTZ  DEFAULT NOW(),
    UNIQUE (year, month)
);

CREATE INDEX IF NOT EXISTS idx_monthly_summary_ym ON monthly_summary (year DESC, month DESC);

-- ---------------------------------------------------------------------------
-- Reconciliation log — every reconciliation run
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reconciliation_log (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    run_date        DATE        NOT NULL DEFAULT CURRENT_DATE,
    sheet_row_count INTEGER,
    db_row_count    INTEGER,
    mismatches      INTEGER     DEFAULT 0,
    late_invoices   INTEGER     DEFAULT 0,
    status          VARCHAR(20) CHECK (status IN ('ok', 'warning', 'error')) DEFAULT 'ok',
    notes           TEXT,
    agent_name      VARCHAR(100),
    model_used      VARCHAR(100),
    created_at      TIMESTAMPTZ  DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_reconciliation_run_date ON reconciliation_log (run_date DESC);

-- ---------------------------------------------------------------------------
-- Alerts log — every Slack/WhatsApp alert sent
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alerts_log (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_type      VARCHAR(50) NOT NULL,  -- 'daily_report', 'anomaly', 'eod_summary', etc.
    channel         VARCHAR(20) NOT NULL,  -- 'slack', 'whatsapp'
    recipient       VARCHAR(200),
    trigger_metric  VARCHAR(100),
    trigger_value   NUMERIC(14,4),
    threshold_value NUMERIC(14,4),
    message_preview TEXT,
    delivered       BOOLEAN     DEFAULT FALSE,
    error_message   TEXT,
    sent_at         TIMESTAMPTZ  DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_alerts_log_sent_at ON alerts_log (sent_at DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_log_type    ON alerts_log (alert_type);

-- ---------------------------------------------------------------------------
-- Agent runs — monitoring table for every pipeline execution
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agent_runs (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_name      VARCHAR(100) NOT NULL,
    workflow_name   VARCHAR(200),
    trigger_type    VARCHAR(50),  -- 'cron', 'manual', 'webhook', 'n8n'
    status          VARCHAR(20) CHECK (status IN ('running', 'success', 'error', 'warning')) DEFAULT 'running',
    started_at      TIMESTAMPTZ  DEFAULT NOW(),
    finished_at     TIMESTAMPTZ,
    duration_ms     INTEGER,
    rows_processed  INTEGER      DEFAULT 0,
    rows_inserted   INTEGER      DEFAULT 0,
    rows_updated    INTEGER      DEFAULT 0,
    tokens_used     INTEGER,
    error_message   TEXT,
    model           VARCHAR(100),
    metadata        JSONB
);

CREATE INDEX IF NOT EXISTS idx_agent_runs_started  ON agent_runs (started_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_runs_status   ON agent_runs (status);
CREATE INDEX IF NOT EXISTS idx_agent_runs_agent    ON agent_runs (agent_name);

-- ---------------------------------------------------------------------------
-- Shopify orders — stub table for System 2 integration
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS shopify_orders (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    shopify_order_id VARCHAR(100) UNIQUE,
    order_date      DATE,
    order_number    VARCHAR(100),
    customer_email  VARCHAR(300),
    total_price     NUMERIC(14,2),
    subtotal_price  NUMERIC(14,2),
    total_discounts NUMERIC(14,2),
    total_tax       NUMERIC(14,2),
    financial_status VARCHAR(50),
    fulfillment_status VARCHAR(50),
    currency        VARCHAR(10),
    line_items      JSONB,
    raw_payload     JSONB,
    synced_at       TIMESTAMPTZ  DEFAULT NOW(),
    created_at      TIMESTAMPTZ  DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_shopify_orders_date   ON shopify_orders (order_date DESC);
CREATE INDEX IF NOT EXISTS idx_shopify_orders_status ON shopify_orders (financial_status);

-- ---------------------------------------------------------------------------
-- VIEW: latest_7_days — last 7 days of P&L (used by WhatsApp AI agent)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW latest_7_days AS
SELECT
    report_date,
    revenue,
    cog,
    adspend_google,
    adspend_pinterest,
    mediabuying,
    employee_cost,
    transaction_fee,
    profit,
    roas,
    profit_pct,
    cog_pct,
    cvr_pct,
    cpc,
    refunds,
    refund_pct,
    synced_at
FROM daily_pl
WHERE report_date >= CURRENT_DATE - INTERVAL '7 days'
ORDER BY report_date DESC;

-- ---------------------------------------------------------------------------
-- VIEW: mtd_summary — month-to-date aggregates (used in daily Slack report)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW mtd_summary AS
SELECT
    DATE_TRUNC('month', CURRENT_DATE)::DATE           AS month_start,
    CURRENT_DATE                                       AS through_date,
    COUNT(*)                                           AS days_counted,
    SUM(revenue)                                       AS total_revenue,
    SUM(cog)                                           AS total_cog,
    SUM(adspend_google)                                AS total_adspend_google,
    SUM(adspend_pinterest)                             AS total_adspend_pinterest,
    SUM(mediabuying)                                   AS total_mediabuying,
    SUM(employee_cost)                                 AS total_employee_cost,
    SUM(transaction_fee)                               AS total_transaction_fee,
    SUM(profit)                                        AS total_profit,
    ROUND(AVG(roas), 4)                                AS avg_roas,
    ROUND(
        CASE WHEN SUM(revenue) > 0
             THEN (SUM(profit) / SUM(revenue)) * 100
             ELSE 0 END, 4
    )                                                  AS profit_pct,
    SUM(refunds)                                       AS total_refunds,
    ROUND(AVG(refund_pct), 4)                          AS avg_refund_pct
FROM daily_pl
WHERE report_date >= DATE_TRUNC('month', CURRENT_DATE)
  AND report_date <= CURRENT_DATE;

-- ---------------------------------------------------------------------------
-- Slack sync state — tracks last processed message timestamp per channel
-- (used by slack_invoice_reader.py to avoid re-processing messages)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS slack_sync_state (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    channel_id  VARCHAR(100) UNIQUE NOT NULL,
    last_ts     VARCHAR(50),   -- Slack message timestamp string e.g. "1716800000.123456"
    updated_at  TIMESTAMPTZ  DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Stores — master config per Shopify store (multi-currency, multi-store)
--
-- One row per store. All agents read from this table to resolve credentials,
-- URLs, and the native currency for each store.
--
-- Currency rules:
--   USD stores → revenue_eur / profit_eur in daily_pl computed via exchange_rates
--   EUR stores → revenue_eur / profit_eur = revenue / profit (no conversion needed)
--
-- The "default" store is seeded automatically so single-store setups work
-- without any manual INSERT.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stores (
    id                      UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    store_id                VARCHAR(100) UNIQUE NOT NULL,
    display_name            VARCHAR(100) NOT NULL DEFAULT '',
    currency                VARCHAR(3)   NOT NULL DEFAULT 'USD',
    shopify_url             VARCHAR(255),
    google_script_url       TEXT,
    google_ads_sheet_url    TEXT,
    pinterest_ads_sheet_url TEXT,
    slack_channel_id        VARCHAR(50),
    is_active               BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at              TIMESTAMPTZ  DEFAULT NOW(),
    updated_at              TIMESTAMPTZ  DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_stores_store_id ON stores (store_id);

-- Seed the default store (idempotent)
INSERT INTO stores (store_id, display_name, currency)
VALUES ('default', 'FRUGAZE', 'USD')
ON CONFLICT (store_id) DO NOTHING;

-- ---------------------------------------------------------------------------
-- Migration: add currency + EUR conversion columns to daily_pl
-- (idempotent — safe to run on existing installations)
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'daily_pl' AND column_name = 'currency'
    ) THEN
        ALTER TABLE daily_pl ADD COLUMN currency VARCHAR(3) DEFAULT 'USD';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'daily_pl' AND column_name = 'revenue_eur'
    ) THEN
        ALTER TABLE daily_pl ADD COLUMN revenue_eur NUMERIC(12,2);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'daily_pl' AND column_name = 'profit_eur'
    ) THEN
        ALTER TABLE daily_pl ADD COLUMN profit_eur NUMERIC(12,2);
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- Exchange rates — daily FX cache (fetched from exchangerate-api.com)
--
-- Populated by currency_converter.fetch_and_cache_today_rates() at 06:35
-- before all other pipeline pulls. pl_processor.py reads from this table
-- to compute revenue_eur / profit_eur in daily_pl.
--
-- If the API is unavailable, the most-recent cached rate is used.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS exchange_rates (
    id            UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    rate_date     DATE         NOT NULL,
    from_currency VARCHAR(3)   NOT NULL,
    to_currency   VARCHAR(3)   NOT NULL,
    rate          NUMERIC(10,6) NOT NULL,
    fetched_at    TIMESTAMPTZ  DEFAULT NOW(),
    UNIQUE (rate_date, from_currency, to_currency)
);

CREATE INDEX IF NOT EXISTS idx_exchange_rates_date ON exchange_rates (rate_date DESC);
