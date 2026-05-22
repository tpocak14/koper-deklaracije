-- Dodaj tabelo za sledenje opozorilom
CREATE TABLE IF NOT EXISTS notification_log (
    id SERIAL PRIMARY KEY,
    order_number VARCHAR(255) NOT NULL,
    notification_type VARCHAR(100) NOT NULL,
    missing_data_hash VARCHAR(255) NOT NULL,
    sent_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Dodaj indeks za hitro iskanje
CREATE INDEX IF NOT EXISTS idx_notification_log_order_type_hash ON notification_log(order_number, notification_type, missing_data_hash);
CREATE INDEX IF NOT EXISTS idx_notification_log_sent_at ON notification_log(sent_at);

-- Dodaj komentarje
COMMENT ON TABLE notification_log IS 'Tabela za sledenje pošiljanju opozoril o manjkajočih podatkih';
COMMENT ON COLUMN notification_log.order_number IS 'Številka naročila';
COMMENT ON COLUMN notification_log.notification_type IS 'Tip opozorila (missing_data, expiration_warning, itd.)';
COMMENT ON COLUMN notification_log.missing_data_hash IS 'Hash manjkajočih podatkov za preverjanje duplikatov';
COMMENT ON COLUMN notification_log.sent_at IS 'Čas pošiljanja opozorila';
COMMENT ON COLUMN notification_log.created_at IS 'Čas ustvarjanja zapisa';
