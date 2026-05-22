-- Migracija: Odstrani UNIQUE constraint za order_number, product_no, proizvajalec_ime
-- Revision ID: 006
-- Revises: 005_remove_declarations_serija_unique_constraint.sql

-- Odstranimo constraint, ki preprečuje več zapisov za isti parfum v istem naročilu
-- To je potrebno za FLORGARDEN, kjer lahko imamo več plastenk iste serije v istem naročilu
DO $$
BEGIN
    -- Preverimo, ali constraint obstaja
    IF EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'declarations_order_number_product_no_proizvajalec_ime_key'
    ) THEN
        -- Odstranimo UNIQUE constraint
        ALTER TABLE declarations 
        DROP CONSTRAINT declarations_order_number_product_no_proizvajalec_ime_key;
        
        RAISE NOTICE 'Constraint declarations_order_number_product_no_proizvajalec_ime_key je bil odstranjen';
    ELSE
        RAISE NOTICE 'Constraint declarations_order_number_product_no_proizvajalec_ime_key ne obstaja';
    END IF;
END $$;
