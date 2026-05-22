-- Initialize perfumes_stock with existing perfumes
INSERT INTO perfumes_stock (product_no, proizvajalec_id, on_hand, on_order_pending, on_order_committed)
SELECT p.product_no, p.proizvajalec_id, 0, 0, 0
FROM parfumi p
ON CONFLICT (product_no, proizvajalec_id) DO NOTHING;

