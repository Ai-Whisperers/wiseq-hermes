"""Portable SQL schema for the WiseQ operations database.

One schema, two dialects. The tiny template variables let the same DDL run on
SQLite (local dev / CI) and PostgreSQL (Supabase production) without drift:

    ${TS}      -> TIMESTAMPTZ | TEXT
    ${UUID}    -> uuid        | TEXT
    ${JSONB}   -> jsonb       | TEXT
    ${NOW}     -> now()       | CURRENT_TIMESTAMP

Tables
------
components      114 decoded component SKUs (source of truth for titles)
bundles         25 composite bundles with decomposition into components
products        sellable catalogue (components + bundles) with EAN coverage
ean_registry    GS1/EAN status per product - the 0/230 problem, tracked
schools         B2B customers
orders          school / B2B order pipeline
order_lines     order lines with resolved shipping rule + tariff
shipping_rules  15 client shipping-rule templates (incl. NEEDS_CONFIRMATION)
shipping_tariffs carrier / size-class / country / weight-band tariffs
purchase_intel  rolling 6-month purchase statistics per EAN
stock           inventory position per SKU
reviews         review invitations + triage state (draft-first)
assortment      bol.com listing content-quality scores
audit_log       append-only audit trail for every agent action
agent_runs      per-run execution record
approvals       human approval gate for high-impact actions

Supervision (added with the worker supervision work):
scheduler_heartbeats  one row per scheduler loop iteration -- the liveness proof
scheduler_job_state   per-job counters that survive a restart of the scheduler

Access control (added with the RBAC work):
api_tokens            rotating API tokens, stored as a hash -- never as the token
"""
from __future__ import annotations

SCHEMA_TEMPLATE = """
${PRAGMA}
CREATE TABLE IF NOT EXISTS components (
    component_sku   ${UUID} PRIMARY KEY,
    sku_text        TEXT NOT NULL UNIQUE,
    title           TEXT NOT NULL,
    product_type    TEXT NOT NULL DEFAULT 'component',
    created_at      ${TS} NOT NULL DEFAULT ${NOW}
);

CREATE TABLE IF NOT EXISTS bundles (
    bundle_key      TEXT PRIMARY KEY,
    bundle_sku      TEXT NOT NULL UNIQUE,
    title           TEXT NOT NULL,
    component_skus  TEXT NOT NULL,          -- JSON array of component SKUs
    needs_format_fix BOOLEAN NOT NULL DEFAULT 0,
    source          TEXT NOT NULL DEFAULT 'wiseq-bundle-spine.csv',
    created_at      ${TS} NOT NULL DEFAULT ${NOW}
);

CREATE TABLE IF NOT EXISTS products (
    sku             ${UUID} PRIMARY KEY,
    sku_text        TEXT NOT NULL UNIQUE,
    title           TEXT NOT NULL,
    product_type    TEXT NOT NULL,          -- component | bundle
    ean             TEXT,
    has_ean         BOOLEAN NOT NULL DEFAULT 0,
    price_eur       NUMERIC(10,2) NOT NULL DEFAULT 0,
    weight_gram     INTEGER NOT NULL DEFAULT 0,
    category        TEXT,
    synthetic_price BOOLEAN NOT NULL DEFAULT 1,
    created_at      ${TS} NOT NULL DEFAULT ${NOW},
    updated_at      ${TS} NOT NULL DEFAULT ${NOW}
);
CREATE INDEX IF NOT EXISTS idx_products_type ON products(product_type);
CREATE INDEX IF NOT EXISTS idx_products_ean  ON products(ean);

CREATE TABLE IF NOT EXISTS ean_registry (
    -- Business SKU, matching products.sku_text.
    sku             TEXT PRIMARY KEY,
    ean             TEXT,
    status          TEXT NOT NULL DEFAULT 'missing',  -- missing|pending|registered|waived
    gs1_reference  TEXT,
    source          TEXT,
    updated_at      ${TS} NOT NULL DEFAULT ${NOW}
);

CREATE TABLE IF NOT EXISTS shipping_rules (
    rule_key        TEXT PRIMARY KEY,
    category        TEXT NOT NULL UNIQUE,
    clone_note      TEXT,
    template_ean    TEXT,
    notes           TEXT,
    validation_status TEXT NOT NULL,        -- OK | NEEDS_CONFIRMATION | CASE_BY_CASE | HERZIEN
    source_effective TEXT,
    updated_at      ${TS} NOT NULL DEFAULT ${NOW}
);

CREATE TABLE IF NOT EXISTS shipping_tariffs (
    tariff_key      TEXT PRIMARY KEY,
    carrier         TEXT NOT NULL,
    shipment_type   TEXT NOT NULL,
    size_class      TEXT,          -- LVB rows use 3XS/2XS/XS/S/M
    article_kind    TEXT,
    country         TEXT NOT NULL DEFAULT 'NL',
    weight_band     TEXT,
    cost_eur        NUMERIC(10,2),
    discount_eur    NUMERIC(10,2),
    lvb_storage_eur NUMERIC(10,2),
    notes           TEXT
);
CREATE INDEX IF NOT EXISTS idx_tariffs_lookup
    ON shipping_tariffs(carrier, country, shipment_type);

-- Order-level fees that are not carrier tariffs.
--
-- The live storefront publishes a fixed "Administratie- en verzendkosten"
-- line of EUR 2,95 ex-vat (EUR 3,57 incl.) per business order.  It is not a
-- shipping tariff -- no carrier carries it and no weight band applies -- so
-- it gets its own table rather than being forced into shipping_tariffs
-- where it would break the carrier enum.
CREATE TABLE IF NOT EXISTS order_rules (
    rule_key        TEXT PRIMARY KEY,
    rule_type       TEXT NOT NULL,     -- b2b_surcharge | school_internal
    description     TEXT,
    amount_eur      NUMERIC(10,2) NOT NULL DEFAULT 0,
    applies_to      TEXT NOT NULL DEFAULT 'b2b_order',
    source          TEXT,
    observed_at     TEXT,
    updated_at      ${TS} NOT NULL DEFAULT ${NOW}
);

CREATE TABLE IF NOT EXISTS schools (
    school_id       ${UUID} PRIMARY KEY,
    name            TEXT NOT NULL,
    contact_person  TEXT,
    email           TEXT NOT NULL,
    phone           TEXT,
    city            TEXT,
    country         TEXT NOT NULL DEFAULT 'NL',
    is_stichting    BOOLEAN NOT NULL DEFAULT 0,
    segment         TEXT NOT NULL DEFAULT 'school',
    created_at      ${TS} NOT NULL DEFAULT ${NOW}
);

CREATE TABLE IF NOT EXISTS orders (
    order_id        ${UUID} PRIMARY KEY,
    order_number    TEXT NOT NULL UNIQUE,
    customer_id     ${UUID},
    channel         TEXT NOT NULL DEFAULT 'b2b_school',
    status          TEXT NOT NULL DEFAULT 'received',
    total_eur       NUMERIC(12,2) NOT NULL DEFAULT 0,
    shipping_eur    NUMERIC(12,2) NOT NULL DEFAULT 0,
    discount_pct    NUMERIC(5,2) NOT NULL DEFAULT 0,
    source_email    TEXT,
    offer_number    TEXT,
    invoice_number  TEXT,
    myparcel_label  TEXT,
    review_due_at   ${TS},
    created_at      ${TS} NOT NULL DEFAULT ${NOW},
    updated_at      ${TS} NOT NULL DEFAULT ${NOW}
);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);

CREATE TABLE IF NOT EXISTS order_lines (
    line_id         ${UUID} PRIMARY KEY,
    order_id        ${UUID} NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
    sku             TEXT NOT NULL,
    title           TEXT NOT NULL,
    quantity        INTEGER NOT NULL DEFAULT 1,
    unit_price_eur  NUMERIC(10,2) NOT NULL DEFAULT 0,
    line_total_eur  NUMERIC(12,2) NOT NULL DEFAULT 0,
    rule_key        TEXT,
    carrier         TEXT,
    tariff_key      TEXT,
    shipping_eur    NUMERIC(12,2) NOT NULL DEFAULT 0,
    framing_status  TEXT NOT NULL DEFAULT 'framed',   -- framed|unfranked|needs_confirmation
    is_bundle       BOOLEAN NOT NULL DEFAULT 0,
    created_at      ${TS} NOT NULL DEFAULT ${NOW}
);
CREATE INDEX IF NOT EXISTS idx_lines_order ON order_lines(order_id);

CREATE TABLE IF NOT EXISTS purchase_intel (
    -- Keyed by the *business* SKU (the client's own product code), not by an
    -- internal UUID: this table is joined against order_lines.sku, which is
    -- the business SKU.
    sku             TEXT PRIMARY KEY,
    ean             TEXT,
    avg_qty_6m      NUMERIC(12,2) NOT NULL DEFAULT 0,
    avg_unit_cost_eur NUMERIC(10,2) NOT NULL DEFAULT 0,
    last_purchase_at ${TS},
    stock_qty       INTEGER NOT NULL DEFAULT 0,
    reorder_point   INTEGER NOT NULL DEFAULT 0,
    suggested_qty   INTEGER NOT NULL DEFAULT 0,
    price_bracket   TEXT,
    computed_at     ${TS} NOT NULL DEFAULT ${NOW}
);

CREATE TABLE IF NOT EXISTS stock (
    -- Business SKU, matching order_lines.sku and purchase_intel.sku.
    sku             TEXT PRIMARY KEY,
    on_hand         INTEGER NOT NULL DEFAULT 0,
    reserved        INTEGER NOT NULL DEFAULT 0,
    updated_at      ${TS} NOT NULL DEFAULT ${NOW}
);

CREATE TABLE IF NOT EXISTS reviews (
    review_id       ${UUID} PRIMARY KEY,
    order_id        ${UUID} REFERENCES orders(order_id) ON DELETE CASCADE,
    channel         TEXT NOT NULL,           -- bol.com | trustpilot
    customer_email  TEXT NOT NULL,
    order_number    TEXT,
    status          TEXT NOT NULL DEFAULT 'drafted',
    drafted_body    TEXT,
    sent_at         ${TS},
    suppression     BOOLEAN NOT NULL DEFAULT 0,
    created_at      ${TS} NOT NULL DEFAULT ${NOW}
);
CREATE INDEX IF NOT EXISTS idx_reviews_status ON reviews(status);

CREATE TABLE IF NOT EXISTS search_keywords (
    keyword       TEXT PRIMARY KEY,
    volume        NUMERIC(12,2) NOT NULL DEFAULT 0,
    intent        TEXT,
    position      INTEGER,
    cpc           NUMERIC(10,2),
    competition  NUMERIC(10,2),
    source        TEXT NOT NULL DEFAULT 'google-search-volume'
);

CREATE TABLE IF NOT EXISTS assortment (
    listing_id      TEXT PRIMARY KEY,
    account         TEXT NOT NULL,
    sku             TEXT,
    title           TEXT,
    title_len       INTEGER NOT NULL DEFAULT 0,
    description_len INTEGER NOT NULL DEFAULT 0,
    image_px        INTEGER NOT NULL DEFAULT 0,
    keyword_score   NUMERIC(5,2) NOT NULL DEFAULT 0,
    content_score   NUMERIC(5,2) NOT NULL DEFAULT 0,
    online          BOOLEAN NOT NULL DEFAULT 1,
    issues          TEXT,
    updated_at      ${TS} NOT NULL DEFAULT ${NOW}
);

CREATE TABLE IF NOT EXISTS outbox (
    outbox_id      TEXT PRIMARY KEY,
    sent_to        TEXT NOT NULL,
    intended_to    TEXT,
    subject        TEXT NOT NULL,
    body           TEXT NOT NULL,
    category       TEXT,
    delivered      INTEGER NOT NULL DEFAULT 0,
    error          TEXT,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS audit_log (
    audit_id        ${UUID} PRIMARY KEY,
    actor           TEXT NOT NULL,
    action          TEXT NOT NULL,
    entity_type     TEXT,
    entity_id       TEXT,
    detail          TEXT,
    requires_human  BOOLEAN NOT NULL DEFAULT 0,
    created_at      ${TS} NOT NULL DEFAULT ${NOW}
);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action);

CREATE TABLE IF NOT EXISTS agent_runs (
    run_id          ${UUID} PRIMARY KEY,
    agent_name      TEXT NOT NULL,
    started_at      ${TS} NOT NULL DEFAULT ${NOW},
    finished_at     ${TS},
    status          TEXT NOT NULL DEFAULT 'running',
    processed       INTEGER NOT NULL DEFAULT 0,
    escalated       INTEGER NOT NULL DEFAULT 0,
    summary         TEXT
);

CREATE TABLE IF NOT EXISTS approvals (
    approval_id     ${UUID} PRIMARY KEY,
    agent_name      TEXT NOT NULL,
    action_type     TEXT NOT NULL,
    payload         TEXT,
    risk            TEXT NOT NULL DEFAULT 'medium',
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending|approved|rejected
    requested_at    ${TS} NOT NULL DEFAULT ${NOW},
    decided_at      ${TS},
    decided_by      TEXT
);

-- Liveness proof for the scheduler process.
--
-- One row per loop iteration.  The newest row's age is what decides
-- "alive" vs "stale"; without it a crashed scheduler is indistinguishable
-- from a healthy one with a long job interval.
--
-- `jobs` holds the registered job names as a JSON array so a reader can
-- tell "the scheduler is alive but running a different set of jobs" (a
-- misconfigured deployment) from "the scheduler is alive".
--
-- The heartbeat is a WRITE on every iteration.  That is deliberate: it is
-- the only evidence that the process is doing anything at all, and a
-- cheap write on a short interval is cheaper than a silent outage.
CREATE TABLE IF NOT EXISTS scheduler_heartbeats (
    heartbeat_id  ${UUID} PRIMARY KEY,
    pid           INTEGER NOT NULL,
    jobs          TEXT NOT NULL,          -- JSON array of registered job names
    job_count     INTEGER NOT NULL DEFAULT 0,
    iteration     INTEGER NOT NULL DEFAULT 0,
    -- 'running' while the loop is up.  A 'stopped' row is written on a
    -- clean shutdown so a reader can tell a clean stop from a crash.
    status        TEXT NOT NULL DEFAULT 'running',
    created_at    ${TS} NOT NULL DEFAULT ${NOW}
);
CREATE INDEX IF NOT EXISTS idx_heartbeats_created ON scheduler_heartbeats(created_at);

-- Per-job supervision counters.
--
-- These live in the database rather than in the Scheduler object because a
-- restarted scheduler has no memory of the previous process: the counters
-- have to survive the restart for "too many CONSECUTIVE failures" to mean
-- anything across a crash-and-restart cycle.
CREATE TABLE IF NOT EXISTS scheduler_job_state (
    job_name              TEXT PRIMARY KEY,
    last_run_at           ${TS},
    last_success_at       ${TS},
    last_failure_at       ${TS},
    last_error            TEXT,
    last_status           TEXT,            -- ok|failed|timed_out|timeout
    run_count             INTEGER NOT NULL DEFAULT 0,
    failure_count         INTEGER NOT NULL DEFAULT 0,
    timeout_count         INTEGER NOT NULL DEFAULT 0,
    -- Consecutive failures WITHOUT an intervening success.  Reset to zero
    -- by any successful run.  This is the counter the exit decision uses.
    consecutive_failures  INTEGER NOT NULL DEFAULT 0,
    updated_at            ${TS} NOT NULL DEFAULT ${NOW}
);

-- Rotating API tokens.
--
-- Only the SHA-256 hash of each token is stored.  A database dump, a
-- backup, or a colleague with read access to the database must not be
-- able to reconstruct a live credential: the hash cannot be reversed.
--
-- `rotated_from` records which token this one replaced, so a rotation
-- can be traced.  `expires_at` is what makes a rotation safe: the old
-- token keeps a short overlap window and then stops working on its own,
-- with no cleanup job required.
CREATE TABLE IF NOT EXISTS api_tokens (
    token_id      TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    role          TEXT NOT NULL,
    scopes        TEXT NOT NULL,          -- JSON array of scope names
    token_hash    TEXT NOT NULL UNIQUE,   -- SHA-256 of the token, never the token
    issued_at     ${TS} NOT NULL DEFAULT ${NOW},
    expires_at    ${TS},
    revoked_at    ${TS},
    rotated_from  TEXT,
    last_used_at  ${TS}
);
CREATE INDEX IF NOT EXISTS idx_api_tokens_hash ON api_tokens(token_hash);
"""

DIALECTS = {
    # PRAGMA enables SQLite's foreign-key enforcement; PostgreSQL has it on
    # by default and does not understand the statement.
    "sqlite": {"TS": "TEXT", "UUID": "TEXT", "JSONB": "TEXT",
               "NOW": "CURRENT_TIMESTAMP", "PRAGMA": "PRAGMA foreign_keys = ON;\n"},
    "postgresql": {"TS": "TIMESTAMPTZ", "UUID": "uuid", "JSONB": "jsonb",
                   "NOW": "now()", "PRAGMA": ""},
}


def render_schema(dialect: str = "sqlite") -> str:
    if dialect not in DIALECTS:
        raise ValueError(f"unsupported dialect: {dialect}")
    out = SCHEMA_TEMPLATE
    for key, value in DIALECTS[dialect].items():
        out = out.replace("${" + key + "}", value)
    if dialect == "postgresql":
        # SQLite accepts 0/1 as a boolean default; PostgreSQL requires a
        # boolean literal. Rewrite the defaults rather than the column types
        # so the two dialects keep the same logical schema.
        out = out.replace("BOOLEAN NOT NULL DEFAULT 0", "BOOLEAN NOT NULL DEFAULT FALSE")
        out = out.replace("BOOLEAN NOT NULL DEFAULT 1", "BOOLEAN NOT NULL DEFAULT TRUE")
        out = out.replace("BOOLEAN DEFAULT 0", "BOOLEAN DEFAULT FALSE")
        out = out.replace("BOOLEAN DEFAULT 1", "BOOLEAN DEFAULT TRUE")
    return out