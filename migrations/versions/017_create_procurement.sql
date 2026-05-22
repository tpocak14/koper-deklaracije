-- Procurement tables and indexes

CREATE TABLE IF NOT EXISTS perfumes_stock (
    id SERIAL PRIMARY KEY,
    product_no TEXT NOT NULL,
    proizvajalec_id INTEGER NOT NULL REFERENCES proizvajalci(id),
    on_hand INTEGER NOT NULL DEFAULT 0,
    on_order_pending INTEGER NOT NULL DEFAULT 0,
    on_order_committed INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (product_no, proizvajalec_id)
);

CREATE INDEX IF NOT EXISTS idx_perfumes_stock_supplier ON perfumes_stock(proizvajalec_id);

CREATE TABLE IF NOT EXISTS purchase_orders (
    id SERIAL PRIMARY KEY,
    supplier TEXT NOT NULL CHECK (supplier IN ('FLORGARDEN','MISTRAL')),
    status TEXT NOT NULL CHECK (status IN ('DRAFT','SUBMITTED','PARTIAL_RECEIVED','RECEIVED','ARCHIVED','CANCELLED')),
    submitted_at TIMESTAMP NULL,
    received_at TIMESTAMP NULL,
    created_by INTEGER NULL REFERENCES users(id),
    notes TEXT NULL,
    email_pdf_url TEXT NULL,
    email_sent_to TEXT NULL,
    images_json JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_purchase_orders_supplier ON purchase_orders(supplier);
CREATE INDEX IF NOT EXISTS idx_purchase_orders_status ON purchase_orders(status);

CREATE TABLE IF NOT EXISTS purchase_order_items (
    id SERIAL PRIMARY KEY,
    purchase_order_id INTEGER NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
    product_no TEXT NOT NULL,
    proizvajalec_id INTEGER NOT NULL REFERENCES proizvajalci(id),
    requested_qty INTEGER NOT NULL CHECK (requested_qty >= 0),
    received_qty INTEGER NOT NULL DEFAULT 0 CHECK (received_qty >= 0),
    backordered_qty INTEGER NOT NULL DEFAULT 0 CHECK (backordered_qty >= 0),
    unit TEXT NULL DEFAULT 'kos',
    notes TEXT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (purchase_order_id, product_no, proizvajalec_id)
);

CREATE INDEX IF NOT EXISTS idx_poi_po_id ON purchase_order_items(purchase_order_id);
CREATE INDEX IF NOT EXISTS idx_poi_supplier ON purchase_order_items(proizvajalec_id);

ALTER TABLE order_images ADD COLUMN IF NOT EXISTS purchase_order_id INTEGER NULL REFERENCES purchase_orders(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_order_images_po_id ON order_images(purchase_order_id);


