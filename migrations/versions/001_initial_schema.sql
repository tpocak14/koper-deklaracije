-- Migracija: Inicialna struktura baze podatkov
-- Revision ID: 001
-- Revises: 

-- Ustvarimo tabelo orders
CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    shopify_order_id BIGINT UNIQUE NOT NULL,
    order_number TEXT NOT NULL,
    customer_name TEXT,
    customer_email TEXT,
    country_code VARCHAR(2),
    status_url TEXT,
    line_items JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMP WITH TIME ZONE,
    email_sent_at TIMESTAMP WITH TIME ZONE,
    email_recipient TEXT,
    fulfilled_at TIMESTAMP WITH TIME ZONE,
    last_notification_at TIMESTAMP WITH TIME ZONE,
    pdf_generated_at TIMESTAMP WITH TIME ZONE
);

-- Ustvarimo tabele za katalog
CREATE TABLE IF NOT EXISTS proizvajalci (
    id SERIAL PRIMARY KEY,
    ime VARCHAR(255) UNIQUE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS parfumi (
    id SERIAL PRIMARY KEY,
    product_no VARCHAR(50) NOT NULL,
    proizvajalec_id INTEGER NOT NULL REFERENCES proizvajalci(id) ON DELETE CASCADE,
    ime_parfuma TEXT NOT NULL,
    sestava_inci TEXT,
    na_zalogi BOOLEAN DEFAULT FALSE,
    sinhroniziraj_s_shopify BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(product_no, proizvajalec_id)
);

CREATE TABLE IF NOT EXISTS serije (
    id SERIAL PRIMARY KEY,
    excel_row_id INTEGER UNIQUE,
    parfum_id INTEGER NOT NULL REFERENCES parfumi(id) ON DELETE CASCADE,
    rok_uporabe DATE,
    serijska_stevilka VARCHAR(255),
    stanje VARCHAR(50) DEFAULT 'NA ZALOGI',
    datum_odprtja DATE,
    je_tester BOOLEAN DEFAULT FALSE,
    vnesel_uporabnik VARCHAR(255),
    created_at_original TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Dodamo indekse za hitrejše iskanje
CREATE INDEX IF NOT EXISTS idx_orders_order_number ON orders(order_number);
CREATE INDEX IF NOT EXISTS idx_orders_shopify_order_id ON orders(shopify_order_id);
CREATE INDEX IF NOT EXISTS idx_parfumi_product_no ON parfumi(product_no);
CREATE INDEX IF NOT EXISTS idx_serije_rok_uporabe ON serije(rok_uporabe); 