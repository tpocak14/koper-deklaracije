-- 026_add_procurement_orders.sql
--
-- Procurement (Naročilo robe): pošiljanje naročil dobaviteljem
-- (MISTRAL, FLORGARDEN) na podlagi polnjenj iz `serije`.
--
-- Single-shop model: Amour Parfums ima 1 fizično trgovino, zato za razliko
-- od deklaracije.si ne potrebujemo shop_id stolpca.
--
-- Tabeli:
--   order_sends       — en zapis = ena poslana naročilnica (email + XLSX)
--   order_send_lines  — postavke (parfum_id + količina) za vsako naročilnico
--
-- Vir polnjenj za auto-preview: `serije` (created_at v intervalu, supplier
-- preko parfumi.proizvajalec_id).

BEGIN;

CREATE TABLE IF NOT EXISTS order_sends (
    id SERIAL PRIMARY KEY,
    supplier_id INTEGER NOT NULL REFERENCES proizvajalci(id) ON DELETE RESTRICT,
    period_from TIMESTAMPTZ NOT NULL,
    period_to   TIMESTAMPTZ NOT NULL,
    sent_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sent_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    sent_by_name  VARCHAR(128),
    sent_by_email VARCHAR(255),
    recipient_email VARCHAR(255) NOT NULL,
    perfume_count INTEGER NOT NULL,
    total_refills INTEGER NOT NULL,
    -- Mandrill _id iz odgovora pri pošiljanju (ekvivalent resend_id v reference repu)
    mandrill_message_id VARCHAR(64),
    -- Prevzem v predal (Faza 2). Dokler NULL — naročilo na poti.
    received_at TIMESTAMPTZ,
    received_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    received_by_name VARCHAR(128),
    -- Točna XLSX vsebina, ki je bila poslana — da lahko admin ponovno
    -- prenese natanko tisto verzijo.
    xlsx_content BYTEA,
    xlsx_filename VARCHAR(160),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS order_sends_last_idx
    ON order_sends (supplier_id, sent_at DESC);

CREATE INDEX IF NOT EXISTS order_sends_received_idx
    ON order_sends (supplier_id, received_at)
    WHERE received_at IS NULL;

CREATE TABLE IF NOT EXISTS order_send_lines (
    id SERIAL PRIMARY KEY,
    order_send_id INTEGER NOT NULL REFERENCES order_sends(id) ON DELETE CASCADE,
    parfum_id INTEGER NOT NULL REFERENCES parfumi(id) ON DELETE RESTRICT,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS order_send_lines_order_idx
    ON order_send_lines (order_send_id);

CREATE INDEX IF NOT EXISTS order_send_lines_parfum_idx
    ON order_send_lines (parfum_id);

-- Tracker tabela (Flask pattern)
INSERT INTO migrations (version)
VALUES ('026_add_procurement_orders')
ON CONFLICT (version) DO NOTHING;

COMMIT;
