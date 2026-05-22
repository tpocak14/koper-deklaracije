-- Migration 006: Add shopify_fulfilled_at column to orders table
-- This column stores the Shopify fulfillment timestamp for orders

ALTER TABLE orders ADD COLUMN IF NOT EXISTS shopify_fulfilled_at TIMESTAMP WITH TIME ZONE;

-- Add an index for better performance when querying by shopify_fulfilled_at
CREATE INDEX IF NOT EXISTS idx_orders_shopify_fulfilled_at ON orders(shopify_fulfilled_at);

-- Add a comment to document the column
COMMENT ON COLUMN orders.shopify_fulfilled_at IS 'Timestamp when the order was fulfilled in Shopify (from Shopify API)'; 