-- Dodajanje dovoljenj uporabnikom
-- Dodamo permissions stolpec v users tabelo
ALTER TABLE users 
ADD COLUMN permissions JSONB DEFAULT '[]'::jsonb;

-- Dodamo role stolpec za hitro preverjanje
ALTER TABLE users 
ADD COLUMN role VARCHAR(50) DEFAULT 'user' CHECK (role IN ('admin', 'user'));

-- Nastavimo admin uporabnika z vsemi dovoljenji
UPDATE users 
SET role = 'admin', 
    permissions = '[
        "view_orders", "add_serije", "edit_serije", "delete_serije",
        "view_perfumes", "edit_perfumes", "add_perfumes", "delete_perfumes",
        "view_proizvajalci", "edit_proizvajalci", "add_proizvajalci", "delete_proizvajalci",
        "view_users", "edit_users", "add_users", "delete_users",
        "shopify_sync", "generate_pdf", "send_email"
    ]'::jsonb
WHERE username = 'admin';

-- Indeks za hitro iskanje po roli
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);

-- Indeks za hitro iskanje po dovoljenjih (GIN indeks za JSONB)
CREATE INDEX IF NOT EXISTS idx_users_permissions ON users USING GIN (permissions); 