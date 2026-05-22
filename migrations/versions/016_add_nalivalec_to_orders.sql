-- Add nalivalec_id to orders to track perfume filler
ALTER TABLE orders ADD COLUMN IF NOT EXISTS nalivalec_id INTEGER;

-- Optional FK to users(id) if table exists (ignore errors if not)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables 
        WHERE table_name = 'users'
    ) THEN
        BEGIN
            ALTER TABLE orders
            ADD CONSTRAINT IF NOT EXISTS fk_orders_nalivalec
            FOREIGN KEY (nalivalec_id) REFERENCES users(id) ON DELETE SET NULL;
        EXCEPTION WHEN others THEN
            -- ignore if cannot add (e.g., permission or existing)
            NULL;
        END;
    END IF;
END$$;



