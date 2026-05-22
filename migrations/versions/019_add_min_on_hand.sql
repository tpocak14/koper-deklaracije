-- Add min_on_hand threshold to perfumes_stock for auto-suggestion

ALTER TABLE perfumes_stock
    ADD COLUMN IF NOT EXISTS min_on_hand INTEGER NOT NULL DEFAULT 0;

-- Index to help supplier queries that might filter by threshold state
CREATE INDEX IF NOT EXISTS idx_perfumes_stock_min_on_hand ON perfumes_stock(min_on_hand);


