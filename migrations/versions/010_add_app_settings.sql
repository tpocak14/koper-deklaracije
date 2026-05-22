-- Migracija 010: Dodaj app_settings tabelo
-- Ustvarjeno: 2025-01-27

-- Ustvari app_settings tabelo
CREATE TABLE IF NOT EXISTS app_settings (
    id SERIAL PRIMARY KEY,
    key VARCHAR(255) UNIQUE NOT NULL,
    value TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Dodaj indeks za hitrejše iskanje
CREATE INDEX IF NOT EXISTS idx_app_settings_key ON app_settings(key);

-- Dodaj privzeto nastavitev za e-mail test način
INSERT INTO app_settings (key, value) 
VALUES ('email_test_mode', 'true')
ON CONFLICT (key) DO NOTHING;

-- Dodaj trigger za avtomatsko posodobitev updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_app_settings_updated_at 
    BEFORE UPDATE ON app_settings 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();
