-- Add audit fields to serije
ALTER TABLE serije
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS updated_by VARCHAR(255);


