CREATE TABLE IF NOT EXISTS warehouses (
    code VARCHAR(32) PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    city VARCHAR(64) NOT NULL,
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    odoo_location_id INTEGER
);

CREATE TABLE IF NOT EXISTS suppliers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    lead_time_days INTEGER NOT NULL CHECK (lead_time_days >= 1),
    moq INTEGER NOT NULL DEFAULT 1 CHECK (moq >= 1),
    odoo_partner_id INTEGER
);

CREATE TABLE IF NOT EXISTS skus (
    sku VARCHAR(64) PRIMARY KEY,
    name VARCHAR(256) NOT NULL,
    odoo_product_id INTEGER
);

CREATE TABLE IF NOT EXISTS sku_suppliers (
    sku VARCHAR(64) NOT NULL REFERENCES skus (sku) ON DELETE CASCADE,
    supplier_id INTEGER NOT NULL REFERENCES suppliers (id) ON DELETE CASCADE,
    PRIMARY KEY (sku, supplier_id)
);

CREATE TABLE IF NOT EXISTS warehouse_stock (
    warehouse_code VARCHAR(32) NOT NULL REFERENCES warehouses (code) ON DELETE CASCADE,
    sku VARCHAR(64) NOT NULL REFERENCES skus (sku) ON DELETE CASCADE,
    available_qty INTEGER NOT NULL CHECK (available_qty >= 0),
    PRIMARY KEY (warehouse_code, sku)
);

CREATE TABLE IF NOT EXISTS sales_history (
    warehouse_code VARCHAR(32) NOT NULL REFERENCES warehouses (code) ON DELETE CASCADE,
    sku VARCHAR(64) NOT NULL REFERENCES skus (sku) ON DELETE CASCADE,
    sale_date DATE NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity >= 0),
    PRIMARY KEY (warehouse_code, sku, sale_date)
);

CREATE TABLE IF NOT EXISTS processed_webhooks (
    id SERIAL PRIMARY KEY,
    event_id VARCHAR(128) NOT NULL UNIQUE,
    channel VARCHAR(64) NOT NULL,
    order_id VARCHAR(128) NOT NULL,
    response_status INTEGER NOT NULL,
    response_body JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (channel, order_id)
);

CREATE TABLE IF NOT EXISTS stock_movements (
    id BIGSERIAL PRIMARY KEY,
    warehouse_code VARCHAR(32) NOT NULL,
    sku VARCHAR(64) NOT NULL,
    delta INTEGER NOT NULL,
    reason VARCHAR(64) NOT NULL,
    channel VARCHAR(64),
    order_id VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS purchase_orders (
    id SERIAL PRIMARY KEY,
    warehouse_code VARCHAR(32) NOT NULL,
    sku VARCHAR(64) NOT NULL,
    quantity INTEGER NOT NULL,
    odoo_po_id INTEGER,
    odoo_po_reference VARCHAR(64),
    state VARCHAR(32) NOT NULL DEFAULT 'draft',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (warehouse_code, sku, odoo_po_reference)
);

CREATE TABLE IF NOT EXISTS odoo_outbox (
    id BIGSERIAL PRIMARY KEY,
    job_type VARCHAR(32) NOT NULL,
    payload JSONB NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    processed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_stock_movements_sku_wh ON stock_movements (warehouse_code, sku, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_purchase_orders_open ON purchase_orders (warehouse_code, sku) WHERE state IN ('draft', 'sent', 'purchase');
CREATE INDEX IF NOT EXISTS idx_odoo_outbox_pending ON odoo_outbox (created_at) WHERE processed_at IS NULL;