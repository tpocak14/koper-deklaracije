-- Popravi admin dovoljenja
UPDATE users 
SET permissions = '["view_global_actions", "view_orders", "add_serije", "edit_serije", "delete_serije", "view_perfumes", "edit_perfumes", "add_perfumes", "delete_perfumes", "view_proizvajalci", "edit_proizvajalci", "add_proizvajalci", "delete_proizvajalci", "view_users", "edit_users", "add_users", "delete_users", "shopify_sync", "generate_pdf", "send_email"]'::jsonb
WHERE username = 'admin';

-- Popravi user dovoljenja
UPDATE users 
SET permissions = '["view_global_actions", "view_orders", "view_perfumes", "view_proizvajalci", "view_users", "add_serije", "edit_serije", "generate_pdf", "send_email"]'::jsonb
WHERE role = 'user' AND username != 'admin';
