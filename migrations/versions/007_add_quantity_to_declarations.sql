-- Migracija: Dodaj quantity polje v declarations tabelo
-- Revision ID: 007
-- Revises: 006_remove_declarations_order_unique_constraint.sql

-- Dodamo quantity polje za pravilno prikazovanje količin v PDF-ju
ALTER TABLE declarations 
ADD COLUMN quantity INTEGER DEFAULT 1;

-- Posodobimo obstoječe zapise z quantity = 1
UPDATE declarations 
SET quantity = 1 
WHERE quantity IS NULL;

-- Naredimo quantity polje obvezno
ALTER TABLE declarations 
ALTER COLUMN quantity SET NOT NULL;
