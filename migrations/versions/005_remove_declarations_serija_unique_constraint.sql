-- Migracija: Odstrani napačen UNIQUE constraint declarations_serija_unique
-- Revision ID: 005
-- Revises: 004_add_declarations_unique_constraint.sql

-- Odstranimo napačen constraint, ki vključuje serijska_stevilka
-- Ta constraint je napačen za FLORGARDEN, ker lahko imamo več plastenk iste serije
DO $$
BEGIN
    -- Preverimo, ali constraint obstaja
    IF EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'declarations_serija_unique'
    ) THEN
        -- Odstranimo UNIQUE constraint za serije
        ALTER TABLE declarations 
        DROP CONSTRAINT declarations_serija_unique;
        
        RAISE NOTICE 'Constraint declarations_serija_unique je bil odstranjen';
    ELSE
        RAISE NOTICE 'Constraint declarations_serija_unique ne obstaja';
    END IF;
END $$;
