from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, Iterable, List, Tuple
from zoneinfo import ZoneInfo
from datetime import timedelta


def _bucket_key(dt_utc: datetime, tz_name: str, group_by: str) -> str:
    tz = ZoneInfo(tz_name)
    local = dt_utc.astimezone(tz)
    if group_by == "day":
        return local.strftime("%Y-%m-%d")
    if group_by == "week":
        # ISO week start date (Monday)
        # Get Monday of this week
        monday = (local - timedelta(days=(local.weekday()))).date()
        return monday.isoformat()
    if group_by == "month":
        return local.strftime("%Y-%m-01")
    return local.strftime("%Y-%m-%d")


def compute_points(
    records: Iterable[Dict[str, Any]],
    *,
    tz_name: str = "Europe/Ljubljana",
    group_by: str = "day",
    source: str = "created",
    product_details: Dict[str, Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """
    records: iterable of dicts with keys:
      - order_number, prepared_by_id, nalivalec_id, line_items (JSON string or list)
      - created_at (UTC), fulfilled_at (UTC)

    product_details: optional pre-fetched mapping { product_id_str: { product_type: ... } }
    """
    import json
    # timezone imported at module level

    # Aggregate structures
    summary: Dict[int, Dict[str, Any]] = defaultdict(
        lambda: {
            "user_id": 0,
            "points": 0.0,
            "pack_count": 0,
            "pour_count": 0,
            "parfumi_items": 0,
            "non_parfumi_items": 0,
            "orders_count": 0,
        }
    )
    timeseries: List[Dict[str, Any]] = []
    warnings: List[Dict[str, str]] = []
    # Track unique prepared orders per user
    prepared_orders_seen: Dict[int, set] = defaultdict(set)

    # If product_details not given, build list and let caller resolve once
    # Here we expect caller to provide product_details; if not, we will resolve none and warn.
    def resolve_product_type(pid: Any) -> str | None:
        if pid is None:
            return None
        key = str(pid)
        if product_details and key in product_details:
            return (product_details[key] or {}).get("product_type")
        return None

    def is_cod_fee_item(item: Dict[str, Any]) -> bool:
        """Return True if the item represents COD fee service which must be excluded from packing stats."""
        try:
            sku = str(item.get("sku") or "").strip().upper()
            title = str(item.get("title") or "").strip().lower()
            # Primary check via SKU; fallback by title keywords
            if sku == "CODFEE":
                return True
            if "po povzetju" in title or "cod" in title:
                return True
        except Exception:
            pass
        return False

    for rec in records:
        order_number = rec.get("order_number") or ""
        prepared_by_id = rec.get("prepared_by_id")
        nalivalec_id = rec.get("nalivalec_id")
        line_items_raw = rec.get("line_items")
        created_at = rec.get("created_at")
        fulfilled_at = rec.get("fulfilled_at")

        # Pick time according to source
        dt_utc: datetime = fulfilled_at if (source == "fulfilled" and fulfilled_at) else created_at
        if not isinstance(dt_utc, datetime):
            # skip if no usable time
            continue

        # Track prepared orders per user (unique by order_number)
        if prepared_by_id and order_number:
            try:
                prepared_orders_seen[int(prepared_by_id)].add(str(order_number))
            except Exception:
                pass

        # Parse items
        if isinstance(line_items_raw, str):
            try:
                items = json.loads(line_items_raw)
            except Exception:
                items = []
        elif isinstance(line_items_raw, list):
            items = line_items_raw
        else:
            items = []

        bucket = _bucket_key(dt_utc, tz_name, group_by)

        for item in items or []:
            product_id = item.get("product_id")
            qty = item.get("quantity") or 1
            try:
                qty = int(qty)
            except Exception:
                qty = 1

            ptype = item.get("product_type") or resolve_product_type(product_id)

            if ptype == "Parfumi":
                # parfumi rules
                if prepared_by_id and nalivalec_id and nalivalec_id == prepared_by_id:
                    # same user: full point to that user
                    s = summary[prepared_by_id]
                    s["user_id"] = prepared_by_id
                    s["points"] += 1.0 * qty
                    s["pack_count"] += qty
                    s["pour_count"] += qty
                    s["parfumi_items"] += qty
                    timeseries.append({"date": bucket, "user_id": prepared_by_id, "points": 1.0 * qty})
                else:
                    # split or missing one side
                    if prepared_by_id:
                        s_prep = summary[prepared_by_id]
                        s_prep["user_id"] = prepared_by_id
                        s_prep["parfumi_items"] += qty
                        s_prep["pack_count"] += qty
                        add_prep = 0.5 * qty
                        s_prep["points"] += add_prep
                        timeseries.append({"date": bucket, "user_id": prepared_by_id, "points": add_prep})
                    else:
                        # prepared_by_id missing but nalivalec present → dodeli polovico nalivalcu
                        if nalivalec_id:
                            warnings.append({"order": str(order_number), "msg": "Parfumi brez pripravljalca → polovica točk pripisana nalivalcu"})
                    if nalivalec_id:
                        s_pour = summary[nalivalec_id]
                        s_pour["user_id"] = nalivalec_id
                        s_pour["parfumi_items"] += qty
                        s_pour["pour_count"] += qty
                        add_pour = 0.5 * qty
                        s_pour["points"] += add_pour
                        timeseries.append({"date": bucket, "user_id": nalivalec_id, "points": add_pour})
                    else:
                        warnings.append({
                            "order": str(order_number),
                            "msg": "Parfumi brez nalivalca → polovica točk manjkajoča"
                        })
            else:
                # non-parfumi → points to prepared_by (exclude COD fee service items)
                if is_cod_fee_item(item):
                    continue
                if prepared_by_id:
                    s = summary[prepared_by_id]
                    s["user_id"] = prepared_by_id
                    s["points"] += 1.0 * qty
                    s["pack_count"] += qty
                    s["non_parfumi_items"] += qty
                    timeseries.append({"date": bucket, "user_id": prepared_by_id, "points": 1.0 * qty})

    # Finalize summary metrics: parfumi_share_pct
    out_summary: List[Dict[str, Any]] = []
    for uid, s in summary.items():
        total_items = s["parfumi_items"] + s["non_parfumi_items"]
        parfumi_share_pct = round((s["parfumi_items"] / total_items * 100.0) if total_items else 0.0, 1)
        orders_count = len(prepared_orders_seen.get(uid, set()))
        out_summary.append({
            **s,
            "parfumi_share_pct": parfumi_share_pct,
            "orders_count": orders_count,
        })

    return {
        "summary": sorted(out_summary, key=lambda x: (-x["points"], x["user_id"])),
        "timeseries": timeseries,
        "warnings": warnings,
    }


