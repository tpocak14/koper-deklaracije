-- Popravi dovoljenja za obstoječe uporabnike
-- Dodaj osnovna dovoljenja za uporabnike, ki nimajo nobenih dovoljenj

-- Nastavi osnovna dovoljenja za vse uporabnike z role = 'user' in praznimi dovoljenji
UPDATE users 
SET permissions = '[
    "view_orders", "view_perfumes", "view_proizvajalci", 
    "add_serije", "edit_serije", "generate_pdf", "send_email"
]'::jsonb
WHERE role = 'user' 
  AND (permissions IS NULL OR permissions = '[]'::jsonb OR permissions = 'null'::jsonb);

-- Nastavi osnovna dovoljenja za uporabnike brez role (če obstajajo)
UPDATE users 
SET role = 'user',
    permissions = '[
        "view_orders", "view_perfumes", "view_proizvajalci", 
        "add_serije", "edit_serije", "generate_pdf", "send_email"
    ]'::jsonb
WHERE role IS NULL 
  AND (permissions IS NULL OR permissions = '[]'::jsonb OR permissions = 'null'::jsonb);

-- Posodobi admin uporabnika z vsemi dovoljenji (če še ni nastavljen)
UPDATE users 
SET role = 'admin', 
    permissions = '[
        "view_global_actions",
        "view_orders", "add_serije", "edit_serije", "delete_serije",
        "view_perfumes", "edit_perfumes", "add_perfumes", "delete_perfumes",
        "view_proizvajalci", "edit_proizvajalci", "add_proizvajalci", "delete_proizvajalci",
        "view_users", "edit_users", "add_users", "delete_users",
        "shopify_sync", "generate_pdf", "send_email"
    ]'::jsonb
WHERE username = 'admin';
