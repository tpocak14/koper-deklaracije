-- 025_add_mk_return_detection.sql
-- Detect & remember "Vračilo paketa" (returned package) v MK.
--
-- Logika:
--   - Ko MK preide v "Vračilo paketa" (status_code) / "returned" (status_desc),
--     paket se vrača nazaj k nam. Kupec ne potrebuje deklaracije (paketa ne
--     dobi), Shopify se NE označi kot Delivered.
--   - Naša safety net mora takšna naročila preskočiti, da ne pošlje deklaracije
--     po pomoti in da ne zapravlja MK API klicev na ponavljanje.
--   - mk_return_detected_at = idempotent flag (set enkrat, naslednji run skip).

ALTER TABLE orders
  ADD COLUMN IF NOT EXISTS mk_return_detected_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS mk_last_status_desc   TEXT,
  ADD COLUMN IF NOT EXISTS mk_last_status_code   TEXT,
  ADD COLUMN IF NOT EXISTS mk_last_status_at     TIMESTAMPTZ;

-- Index za skip vračil v safety net selectu
CREATE INDEX IF NOT EXISTS idx_orders_mk_returned
    ON orders (mk_return_detected_at)
 WHERE mk_return_detected_at IS NOT NULL;

-- Index za hitro razvrščanje po MK statusu (za UI filtere kasneje)
CREATE INDEX IF NOT EXISTS idx_orders_mk_last_status_desc
    ON orders (mk_last_status_desc)
 WHERE mk_last_status_desc IS NOT NULL;
