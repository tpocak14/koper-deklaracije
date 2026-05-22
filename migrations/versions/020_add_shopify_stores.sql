-- Migracija: Shopify multi-store + OAuth support
-- Revision ID: 020
-- Revises: 019

-- Orders: add store domain and adjust uniqueness
ALTER TABLE orders ADD COLUMN IF NOT EXISTS shopify_store_domain TEXT;
ALTER TABLE orders DROP CONSTRAINT IF EXISTS orders_shopify_order_id_key;
ALTER TABLE orders ADD CONSTRAINT orders_shopify_store_order_id_key
    UNIQUE (shopify_store_domain, shopify_order_id);
CREATE INDEX IF NOT EXISTS idx_orders_shopify_store_domain ON orders(shopify_store_domain);

-- Stores configuration (OAuth tokens + secrets)
CREATE TABLE IF NOT EXISTS shopify_stores (
    id SERIAL PRIMARY KEY,
    shop_domain TEXT UNIQUE NOT NULL,
    access_token TEXT NOT NULL,
    webhook_secret TEXT,
    order_prefix TEXT DEFAULT '#',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- OAuth states (short-lived)
CREATE TABLE IF NOT EXISTS shopify_oauth_states (
    id SERIAL PRIMARY KEY,
    shop_domain TEXT NOT NULL,
    state TEXT UNIQUE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_shopify_oauth_states_shop ON shopify_oauth_states(shop_domain);
