-- 027_add_received_quantity.sql
--
-- Doda `received_quantity` v order_send_lines za audit "kar je bilo
-- poslano (quantity)" vs "kar je dejansko prispelo (received_quantity)".
--
-- Privzeto NULL → pomeni "še ni prevzeto" (kolinearno z order_sends.received_at).
-- Po prevzemu se zapiše dejansko prispelo (lahko enako quantity, manj, ali 0).

BEGIN;

ALTER TABLE order_send_lines
    ADD COLUMN IF NOT EXISTS received_quantity INTEGER;

-- Komentar za prihodnje admine
COMMENT ON COLUMN order_send_lines.received_quantity IS
    'Dejansko prispela količina ob prevzemu. NULL = še ni prevzeto. '
    'Lahko se razlikuje od `quantity` (kar smo naročili), če manjka.';

-- Sled migracije
INSERT INTO migrations (version)
VALUES ('027_add_received_quantity')
ON CONFLICT (version) DO NOTHING;

COMMIT;
