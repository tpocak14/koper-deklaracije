-- Dodajamo UNIQUE constraint na product_no, proizvajalec_ime, rok_uporabe in serijska_stevilka za serije
DO $$
BEGIN
    -- Preverimo, ali constraint že obstaja
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'declarations_serija_unique'
    ) THEN
        -- Dodamo UNIQUE constraint za serije
        ALTER TABLE declarations 
        ADD CONSTRAINT declarations_serija_unique 
        UNIQUE (product_no, proizvajalec_ime, rok_uporabe, serijska_stevilka);
    END IF;
END $$; 