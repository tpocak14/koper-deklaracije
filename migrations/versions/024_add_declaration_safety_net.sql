-- 024_add_declaration_safety_net.sql
-- Safety net za PDF deklaracije, ki niso bile naložene v MK (in posledično jih
-- Mandrill ne pošlje kupcu zaradi "Attachment is required, mail skipped").
--
-- Logika:
--   1. requires_declaration: ali naročilo POTREBUJE deklaracijo (TRUE za parfume,
--      FALSE za CODFEE/donations/samo dostavo). Določeno iz line items.
--   2. pdf_generation_blocked_reason: human-readable razlog, zakaj PDF ni bil generiran
--      (npr. "Manjka INCI za AP123, Ni veljavne serije za AP456").
--   3. pdf_generation_blocked_codes: structured array kod (expired_serije,
--      missing_inci, missing_metafields, parfum_not_in_db, shopify_unreachable).
--      Uporablja se za smart retry invalidation - npr. ko admin vnese novo serijo,
--      najdemo vsa naročila z 'expired_serije' za ta parfum in jih invalidiramo.
--   4. pdf_generation_last_attempt_at: zadnji poskus generiranja PDF (za debugging).
--   5. mandrill_safety_*: ko MK status='completed' ampak priponka manjka, naša app
--      direktno pošlje prek Mandrill API z istim template-om 'deklaracije_si'.
--   6. critical_alert_sent_at: idempotent flag, da admin ne dobi 50 enakih emailov.
--
-- Idempotent: ALTER ADD COLUMN IF NOT EXISTS, INDEX IF NOT EXISTS.

ALTER TABLE orders
  ADD COLUMN IF NOT EXISTS requires_declaration BOOLEAN NOT NULL DEFAULT TRUE,
  ADD COLUMN IF NOT EXISTS pdf_generation_blocked_reason TEXT,
  ADD COLUMN IF NOT EXISTS pdf_generation_blocked_codes TEXT[],
  ADD COLUMN IF NOT EXISTS pdf_generation_blocked_parfumi INTEGER[],
  ADD COLUMN IF NOT EXISTS pdf_generation_last_attempt_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS mandrill_safety_attempted_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS mandrill_safety_message_id TEXT,
  ADD COLUMN IF NOT EXISTS mandrill_safety_status TEXT,
  ADD COLUMN IF NOT EXISTS critical_alert_sent_at TIMESTAMPTZ;

-- Backfill: vsa naročila, ki imajo status='brez_parfumov', NE potrebujejo deklaracije
UPDATE orders
   SET requires_declaration = FALSE
 WHERE status = 'brez_parfumov'
   AND requires_declaration IS DISTINCT FROM FALSE;

-- Index za hitro iskanje kandidatov za safety net retry
CREATE INDEX IF NOT EXISTS idx_orders_safety_net_candidates
    ON orders (created_at DESC)
 WHERE requires_declaration = TRUE
   AND mk_decl_uploaded_at IS NULL;

-- Index za invalidation queries: kateri orderi so blokirani s katerim parfumom
CREATE INDEX IF NOT EXISTS idx_orders_blocked_parfumi
    ON orders USING GIN (pdf_generation_blocked_parfumi)
 WHERE pdf_generation_blocked_codes IS NOT NULL;

-- Index za Mandrill verify job
CREATE INDEX IF NOT EXISTS idx_orders_mandrill_safety_pending
    ON orders (mandrill_safety_attempted_at)
 WHERE mandrill_safety_message_id IS NOT NULL
   AND mandrill_safety_status IN ('sent', 'queued', 'scheduled');
