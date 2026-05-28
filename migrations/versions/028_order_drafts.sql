-- 028_order_drafts.sql
-- Osnutki naročil (Naročilo robe) — en zapis na dobavitelja (single-shop).
-- items_json: { "items": [{ "parfumId", "count", "manualCount"? }], "excluded": [parfumId, ...] }

BEGIN;

CREATE TABLE IF NOT EXISTS order_drafts (
    id SERIAL PRIMARY KEY,
    supplier_id INTEGER NOT NULL REFERENCES proizvajalci(id) ON DELETE CASCADE,
    items_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    updated_by_name VARCHAR(128),
    CONSTRAINT order_drafts_supplier_unique UNIQUE (supplier_id)
);

CREATE INDEX IF NOT EXISTS order_drafts_supplier_idx
    ON order_drafts (supplier_id);

COMMIT;
