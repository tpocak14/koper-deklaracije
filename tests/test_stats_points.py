import json
from datetime import datetime, timezone


def fake_get_bulk_product_details(ids):
    return { "111": {"product_type": "Parfumi"}, "222": {"product_type": "Druge"} }


def compute_points_wrapper(records, **kw):
    from services.stats_compute import compute_points
    return compute_points(records, **kw)


def mk_order(prepared_id, nalivalec_id, items):
    return {
        "order_number": "#1001",
        "created_at": datetime(2025, 8, 1, 10, 0, tzinfo=timezone.utc),
        "fulfilled_at": None,
        "line_items": json.dumps(items),
        "prepared_by_id": prepared_id,
        "nalivalec_id": nalivalec_id,
    }


def test_parfumi_same_user_qty3():
    recs = [mk_order(1, 1, [{"product_id": "111", "quantity": 3}])]
    out = compute_points_wrapper(recs, tz_name="Europe/Ljubljana", group_by="day", source="created", product_details=fake_get_bulk_product_details([]))
    u1 = next(s for s in out["summary"] if s["user_id"] == 1)
    assert abs(u1["points"] - 3.0) < 1e-6
    assert u1["pack_count"] == 3 and u1["pour_count"] == 3


def test_parfumi_split_qty2():
    recs = [mk_order(1, 2, [{"product_id": "111", "quantity": 2}])]
    out = compute_points_wrapper(recs, tz_name="Europe/Ljubljana", group_by="day", source="created", product_details=fake_get_bulk_product_details([]))
    u1 = next(s for s in out["summary"] if s["user_id"] == 1)
    u2 = next(s for s in out["summary"] if s["user_id"] == 2)
    assert abs(u1["points"] - 1.0) < 1e-6
    assert abs(u2["points"] - 1.0) < 1e-6
    assert u1["pack_count"] == 2 and u2["pour_count"] == 2


def test_non_parfumi_points_to_prepared():
    recs = [mk_order(3, 4, [{"product_id": "222", "quantity": 1}])]
    out = compute_points_wrapper(recs, tz_name="Europe/Ljubljana", group_by="day", source="created", product_details=fake_get_bulk_product_details([]))
    u3 = next(s for s in out["summary"] if s["user_id"] == 3)
    assert abs(u3["points"] - 1.0) < 1e-6
    assert u3["pack_count"] == 1


def test_parfumi_missing_nalivalec_gives_half_to_prepared():
    recs = [mk_order(5, None, [{"product_id": "111", "quantity": 2}])]
    out = compute_points_wrapper(recs, tz_name="Europe/Ljubljana", group_by="day", source="created", product_details=fake_get_bulk_product_details([]))
    u5 = next(s for s in out["summary"] if s["user_id"] == 5)
    assert abs(u5["points"] - 1.0) < 1e-6  # 0.5 * 2
    assert any("Parfumi brez nalivalca" in w["msg"] for w in out["warnings"])



