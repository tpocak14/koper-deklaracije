-- Migracija: Posodobi obstoječo tabelo declarations na novo strukturo
-- Revision ID: 003
-- Revises: 002

-- Najprej preverimo, ali tabela obstaja z staro strukturo
DO $$
BEGIN
    -- Če tabela obstaja z staro strukturo (product_id), jo posodobimo
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'declarations' 
        AND column_name = 'product_id'
    ) THEN
        -- Dodamo manjkajoče stolpce
        ALTER TABLE declarations ADD COLUMN IF NOT EXISTS id SERIAL;
        ALTER TABLE declarations ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;
        ALTER TABLE declarations ADD COLUMN IF NOT EXISTS order_id INTEGER;
        
        -- Preimenujemo stolpce
        ALTER TABLE declarations RENAME COLUMN product_id TO product_no;
        ALTER TABLE declarations RENAME COLUMN proizvajalec TO proizvajalec_ime;
        
        -- Dodamo foreign key constraint (brez IF NOT EXISTS)
        BEGIN
            ALTER TABLE declarations ADD CONSTRAINT fk_declarations_order_id 
                FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE;
        EXCEPTION
            WHEN duplicate_object THEN
                -- Constraint že obstaja, nič ne naredimo
                NULL;
        END;
        
        -- Dodamo indeks
        CREATE INDEX IF NOT EXISTS idx_declarations_order_number ON declarations(order_number);
        
        -- Nastavimo primary key na id stolpec
        ALTER TABLE declarations DROP CONSTRAINT IF EXISTS declarations_pkey;
        ALTER TABLE declarations ADD PRIMARY KEY (id);
        
        -- Dodamo unique constraint (brez IF NOT EXISTS)
        BEGIN
            ALTER TABLE declarations ADD CONSTRAINT unique_declaration_item 
                UNIQUE (order_number, product_no, proizvajalec_ime);
        EXCEPTION
            WHEN duplicate_object THEN
                -- Constraint že obstaja, nič ne naredimo
                NULL;
        END;
            
        RAISE NOTICE 'Tabela declarations uspešno posodobljena';
    ELSE
        RAISE NOTICE 'Tabela declarations že ima novo strukturo';
    END IF;
END $$; 