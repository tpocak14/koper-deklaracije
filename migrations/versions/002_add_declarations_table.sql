-- Migracija: Doda tabelo 'declarations' za shranjevanje podatkov ob kreiranju naročila.
-- Revision ID: 002
-- Revises: 001_initial_schema.sql

CREATE TABLE declarations (
    id SERIAL PRIMARY KEY,
    order_number VARCHAR(255) NOT NULL,
    product_no VARCHAR(255) NOT NULL,
    proizvajalec_ime VARCHAR(255) NOT NULL,
    sestava_inci TEXT,
    rok_uporabe DATE,
    serijska_stevilka VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    -- Povezava na tabelo z naročili za lažje poizvedbe
    order_id INTEGER REFERENCES orders(id) ON DELETE CASCADE,

    -- Zagotovi, da je vsak izdelek v naročilu lahko samo enkrat
    UNIQUE (order_number, product_no, proizvajalec_ime)
);

-- Dodamo indeks za hitrejše iskanje po številki naročila
CREATE INDEX idx_declarations_order_number ON declarations(order_number);

-- Dodamo opombo k tabeli za lažje razumevanje
COMMENT ON TABLE declarations IS 'Shrani "zamrznjen" posnetek podatkov za deklaracijo v trenutku, ko je bilo naročilo ustvarjeno.';