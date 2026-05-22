-- Dodajanje tabele za uporabnike
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    email VARCHAR(255),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Dodamo privzetega admin uporabnika
INSERT INTO users (username, first_name, last_name, email) 
VALUES ('admin', 'Administrator', 'Sistema', 'admin@amour.si')
ON CONFLICT (username) DO NOTHING;

-- Posodobimo order_images tabelo, da povezuje na users tabelo
ALTER TABLE order_images 
ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE SET NULL;

-- Indeks za hitro iskanje po uporabniku
CREATE INDEX IF NOT EXISTS idx_order_images_user_id ON order_images(user_id);

-- Indeks za hitro iskanje po uporabniškem imenu
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username); 