-- 029_add_outbound_email_log.sql
--
-- Skupna tabela (deljena z app-v2) za AUDIT vseh odhodnih e-mailov
-- (vsebina + priloga), da lahko kopijo pregledamo v aplikaciji (app-v2 admin
-- zavihek) namesto zanašanja na BCC.
--
-- Beleženje je NON-FATAL: napaka pri zapisu ne sme nikoli prekiniti dejanskega
-- pošiljanja e-pošte (glej services/outbound_email_log.py).
--
-- Dodatno (aditivno, idempotentno): tabelo v runtime-u ustvari tudi
-- services/outbound_email_log.ensure_outbound_email_log_table() (enak vzorec kot
-- _ensure_*_table() helperji v services/mk_service.py), ter interni endpoint
-- POST /api/internal/migrate/029-outbound-email-log.
--
-- Aditivno: samo CREATE TABLE / INDEX IF NOT EXISTS. Nikoli DROP / ALTER
-- obstoječih tabel ali stolpcev.

BEGIN;

CREATE TABLE IF NOT EXISTS outbound_email_log (
  id BIGSERIAL PRIMARY KEY,
  email_type TEXT NOT NULL,            -- 'declaration' | 'manual_declaration' | 'procurement'
  channel TEXT,                        -- 'flask' | 'vercel'
  sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  recipient_to TEXT,
  recipient_bcc TEXT,
  subject TEXT,
  from_email TEXT,
  from_name TEXT,
  mandrill_message_id TEXT,
  status TEXT,                         -- 'sent' | 'error' | mandrill status
  error TEXT,
  order_number TEXT,
  order_send_id INTEGER,
  html_content TEXT,
  text_content TEXT,
  template_name TEXT,
  merge_vars JSONB,
  attachment_name TEXT,
  attachment_mime TEXT,
  attachment_content BYTEA,
  sent_by_user_id INTEGER,
  sent_by_name TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_outbound_email_log_sent_at ON outbound_email_log (sent_at DESC);
CREATE INDEX IF NOT EXISTS idx_outbound_email_log_type ON outbound_email_log (email_type, sent_at DESC);
CREATE INDEX IF NOT EXISTS idx_outbound_email_log_order ON outbound_email_log (order_number);

-- Sled migracije (Flask pattern; run_migrations() jo označi kot izvedeno)
INSERT INTO migrations (version)
VALUES ('029_add_outbound_email_log')
ON CONFLICT (version) DO NOTHING;

COMMIT;
