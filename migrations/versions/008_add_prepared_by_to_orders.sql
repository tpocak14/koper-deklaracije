-- Dodaj polje prepared_by v orders tabelo
ALTER TABLE orders ADD COLUMN prepared_by VARCHAR(255);
ALTER TABLE orders ADD COLUMN prepared_at TIMESTAMP;

-- Dodaj komentar
COMMENT ON COLUMN orders.prepared_by IS 'Uporabnik, ki je pripravil naročilo (naložil slike)';
COMMENT ON COLUMN orders.prepared_at IS 'Čas, ko je bilo naročilo pripravljeno';
