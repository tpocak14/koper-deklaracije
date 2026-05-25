-- 023_add_tracking_to_orders.sql
-- Dodaj tracking polja na orders tabelo, da jih lahko polnimo iz Shopify
-- fulfillments/create webhook payload-a (in tudi iz MK extra_column.tracking_number).
--
-- Te informacije rabimo za:
--   1) Prikaz tracking podatkov v Next.js admin UI (detail page)
--   2) Diagnostiko / "Manjkajo podatki" indicator
--   3) Možno bodočo automation (npr. tracking link v e-pošti)
--
-- Idempotent: kolumne se dodajo le, če še ne obstajajo.

ALTER TABLE orders ADD COLUMN IF NOT EXISTS tracking_number TEXT NULL;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS tracking_company TEXT NULL;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS tracking_url TEXT NULL;

CREATE INDEX IF NOT EXISTS idx_orders_tracking_number ON orders (tracking_number)
  WHERE tracking_number IS NOT NULL;
