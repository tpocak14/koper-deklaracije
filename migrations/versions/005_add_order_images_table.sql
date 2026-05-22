-- Dodajanje tabele za slike naročil
CREATE TABLE IF NOT EXISTS order_images (
    id SERIAL PRIMARY KEY,
    order_number VARCHAR(50) NOT NULL,
    cloudinary_public_id VARCHAR(255) NOT NULL,
    cloudinary_url VARCHAR(500) NOT NULL,
    uploaded_by VARCHAR(100) NOT NULL,
    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indeks za hitro iskanje po številki naročila
CREATE INDEX IF NOT EXISTS idx_order_images_order_number ON order_images(order_number);

-- Indeks za hitro iskanje po času nalaganja
CREATE INDEX IF NOT EXISTS idx_order_images_uploaded_at ON order_images(uploaded_at); 