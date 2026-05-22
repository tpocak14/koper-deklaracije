-- Procurement stock audit ledger + Shopify idempotency

-- Audit log for every change to proc_products.on_hand
CREATE TABLE IF NOT EXISTS proc_stock_movements (
    id BIGSERIAL PRIMARY KEY,
    supplier_id INTEGER NOT NULL REFERENCES proc_suppliers(id) ON DELETE CASCADE,
    sku TEXT NOT NULL,
    delta INTEGER NOT NULL,
    on_hand_before INTEGER NOT NULL,
    on_hand_after INTEGER NOT NULL,
    source TEXT NOT NULL,
    source_ref TEXT NULL,
    note TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_proc_stock_movements_sku
    ON proc_stock_movements (supplier_id, sku, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_proc_stock_movements_source
    ON proc_stock_movements (source, source_ref);
CREATE INDEX IF NOT EXISTS idx_proc_stock_movements_created
    ON proc_stock_movements (created_at DESC);

-- Idempotency for Shopify-driven stock changes (orders/paid, refunds/create, orders/cancelled)
CREATE TABLE IF NOT EXISTS proc_applied_from_shopify (
    shop_domain TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    event_id    TEXT NOT NULL,
    line_item_id TEXT NOT NULL,
    sku         TEXT NOT NULL,
    qty         INTEGER NOT NULL,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (shop_domain, event_type, event_id, line_item_id, sku)
);

CREATE INDEX IF NOT EXISTS idx_proc_applied_from_shopify_event
    ON proc_applied_from_shopify (shop_domain, event_id);
