"""Sinhronizacija parfumov iz Shopify-ja v lokalno bazo (enako kot app-v2)."""

from __future__ import annotations

import time
from typing import Any

import requests
from flask import current_app

from database import get_db
from services.shopify_service import (
    _get_api_url,
    _get_shopify_headers,
    get_shopify_store_config,
)

DEFAULT_SYNC_STORE = "amour-parfums-2.myshopify.com"

FRAGRANCE_KEYS = (
    "product_fragrance_",
    "product_fragrance",
    "fragrance",
    "product_name",
    "title",
)


def _normalize_shop_domain(shop_domain: str | None) -> str:
    sd = (shop_domain or "").strip().lower()
    if sd.startswith("https://"):
        sd = sd[8:]
    if sd.startswith("http://"):
        sd = sd[7:]
    sd = sd.rstrip("/")
    if sd and not sd.endswith(".myshopify.com"):
        sd = f"{sd}.myshopify.com"
    return sd


def _parse_product_node(node: dict[str, Any]) -> dict[str, Any]:
    mf_map: dict[str, str] = {}
    for edge in (node.get("metafields") or {}).get("edges") or []:
        m = edge.get("node") or {}
        ns = m.get("namespace")
        key = m.get("key")
        if ns and key:
            mf_map[f"{ns}.{key}"] = m.get("value") or ""

    product_no = (mf_map.get("custom.product_no") or "").strip()
    proizvajalec_ime = (mf_map.get("custom.proizvajalec_id") or "").strip()
    sestava_inci = (mf_map.get("custom.sestava_inci") or "").strip()
    na_zalogi_raw = (mf_map.get("custom.na_zalogi") or "").strip().lower()
    na_zalogi = na_zalogi_raw in ("true", "1")

    fragrance = ""
    for key in FRAGRANCE_KEYS:
        val = (mf_map.get(f"custom.{key}") or "").strip()
        if val:
            fragrance = val
            break

    vendor = (node.get("vendor") or "").strip()
    if not proizvajalec_ime and vendor:
        proizvajalec_ime = vendor

    return {
        "product_id": node.get("id") or "",
        "vendor": vendor,
        "product_no": product_no or None,
        "proizvajalec_ime": proizvajalec_ime or None,
        "fragrance": fragrance or None,
        "sestava_inci": sestava_inci or None,
        "na_zalogi": na_zalogi,
    }


def _fetch_products(shop_domain: str) -> tuple[list[dict[str, Any]], list[str]]:
    products: list[dict[str, Any]] = []
    errors: list[str] = []
    cursor: str | None = None
    has_next = True
    safety = 0

    while has_next and safety < 100:
        safety += 1
        after = f', after: "{cursor}"' if cursor else ""
        query = f"""{{
          products(first: 250{after}) {{
            pageInfo {{ hasNextPage endCursor }}
            edges {{
              node {{
                id
                vendor
                metafields(first: 50) {{
                  edges {{
                    node {{ namespace key value }}
                  }}
                }}
              }}
            }}
          }}
        }}"""

        try:
            response = requests.post(
                _get_api_url(shop_domain=shop_domain),
                json={"query": query},
                headers=_get_shopify_headers(shop_domain),
                timeout=60,
            )
        except Exception as exc:
            errors.append(
                f"Network napaka pri fetch (cursor={cursor or 'init'}): {exc}"
            )
            break

        if response.status_code != 200:
            errors.append(
                f"Shopify GraphQL {response.status_code} (cursor={cursor or 'init'}): "
                f"{response.text[:300]}"
            )
            break

        data = response.json()
        if data.get("errors"):
            errors.append(
                f"Shopify GraphQL errors: {str(data['errors'])[:400]}"
            )
            break

        products_data = (data.get("data") or {}).get("products") or {}
        edges = products_data.get("edges") or []
        for edge in edges:
            node = edge.get("node")
            if node and node.get("id"):
                products.append(_parse_product_node(node))

        page_info = products_data.get("pageInfo") or {}
        has_next = bool(page_info.get("hasNextPage"))
        cursor = page_info.get("endCursor")
        if not cursor:
            has_next = False

    return products, errors


def sync_parfumi_from_shopify(
    shop_domain: str,
    *,
    dry_run: bool = False,
    update_existing: bool = False,
) -> dict[str, Any]:
    """
    Sinhronizira parfume iz izbrane Shopify trgovine v lokalno bazo.

    Privzeto samo doda manjkajoče parfume (update_existing=False).
    Posodabljanje obstoječih je opt-in.
    """
    t0 = time.time()
    normalized = _normalize_shop_domain(shop_domain) or DEFAULT_SYNC_STORE

    if not normalized.endswith(".myshopify.com"):
        return {
            "ok": False,
            "error": f"Neveljaven shop_domain: '{shop_domain}'. Pričakovano '<name>.myshopify.com'.",
        }

    store = get_shopify_store_config(normalized)
    if not store or not store.get("access_token"):
        return {
            "ok": False,
            "error": (
                f"Shopify trgovina '{normalized}' ni najdena v shopify_stores "
                "ali manjka access_token."
            ),
        }

    result: dict[str, Any] = {
        "ok": False,
        "shop_domain": normalized,
        "fetched": 0,
        "added": 0,
        "updated": 0,
        "skipped": 0,
        "errors": 0,
        "error_messages": [],
        "skipped_samples": [],
        "duration_ms": 0,
        "dry_run": dry_run,
        "update_existing": update_existing,
    }

    products, fetch_errors = _fetch_products(normalized)
    result["fetched"] = len(products)
    if fetch_errors:
        result["errors"] += len(fetch_errors)
        result["error_messages"].extend(fetch_errors[:20])
        if not products:
            result["duration_ms"] = int((time.time() - t0) * 1000)
            return result

    db = get_db()
    cursor = db.cursor()
    proizvajalec_cache: dict[str, int] = {}

    try:
        cursor.execute("SELECT id, ime FROM proizvajalci")
        for row in cursor.fetchall() or []:
            ime = str(row["ime"] if isinstance(row, dict) else row[1]).strip()
            pid = row["id"] if isinstance(row, dict) else row[0]
            proizvajalec_cache[ime.lower()] = pid

        for product in products:
            try:
                vendor = product.get("vendor") or ""
                product_no = product.get("product_no")
                proizvajalec_ime = product.get("proizvajalec_ime")
                fragrance = product.get("fragrance")

                if not vendor or not product_no or not proizvajalec_ime or not fragrance:
                    result["skipped"] += 1
                    if len(result["skipped_samples"]) < 20:
                        missing = []
                        if not vendor:
                            missing.append("vendor")
                        if not product_no:
                            missing.append("product_no")
                        if not proizvajalec_ime:
                            missing.append("proizvajalec")
                        if not fragrance:
                            missing.append("fragrance")
                        result["skipped_samples"].append(
                            {
                                "product_id": product.get("product_id"),
                                "vendor": vendor or "(?)",
                                "product_no": product_no,
                                "reason": f"Manjka: {', '.join(missing)}",
                            }
                        )
                    continue

                cache_key = proizvajalec_ime.strip().lower()
                proizvajalec_id = proizvajalec_cache.get(cache_key)

                if not proizvajalec_id:
                    if dry_run:
                        result["skipped"] += 1
                        if len(result["skipped_samples"]) < 20:
                            result["skipped_samples"].append(
                                {
                                    "product_id": product.get("product_id"),
                                    "vendor": vendor,
                                    "product_no": product_no,
                                    "reason": (
                                        f"Proizvajalec '{proizvajalec_ime}' ne obstaja "
                                        "(dry-run skip)"
                                    ),
                                }
                            )
                        continue

                    cursor.execute(
                        "INSERT INTO proizvajalci (ime) VALUES (%s) ON CONFLICT (ime) DO NOTHING",
                        (proizvajalec_ime,),
                    )
                    cursor.execute(
                        "SELECT id FROM proizvajalci WHERE ime = %s",
                        (proizvajalec_ime,),
                    )
                    row = cursor.fetchone()
                    if not row:
                        result["errors"] += 1
                        if len(result["error_messages"]) < 20:
                            result["error_messages"].append(
                                f"Ne morem najti/kreirati proizvajalca: {proizvajalec_ime}"
                            )
                        continue
                    proizvajalec_id = row["id"] if isinstance(row, dict) else row[0]
                    proizvajalec_cache[cache_key] = proizvajalec_id

                new_name = f"{vendor} - {fragrance}"
                sestava_inci = product.get("sestava_inci")
                na_zalogi = bool(product.get("na_zalogi"))

                cursor.execute(
                    """
                    SELECT id, ime_parfuma, sestava_inci, na_zalogi
                    FROM parfumi
                    WHERE product_no = %s AND proizvajalec_id = %s
                    """,
                    (product_no, proizvajalec_id),
                )
                existing = cursor.fetchone()

                if existing:
                    if not update_existing:
                        result["skipped"] += 1
                        if len(result["skipped_samples"]) < 20:
                            result["skipped_samples"].append(
                                {
                                    "product_id": product.get("product_id"),
                                    "vendor": vendor,
                                    "product_no": product_no,
                                    "reason": "Parfum že obstaja (preskočeno)",
                                }
                            )
                        continue

                    updates: list[str] = []
                    params: list[Any] = []

                    existing_name = existing["ime_parfuma"] if isinstance(existing, dict) else existing[1]
                    existing_inci = existing["sestava_inci"] if isinstance(existing, dict) else existing[2]
                    existing_na_zalogi = existing["na_zalogi"] if isinstance(existing, dict) else existing[3]
                    parfum_id = existing["id"] if isinstance(existing, dict) else existing[0]

                    if existing_name != new_name:
                        updates.append("ime_parfuma = %s")
                        params.append(new_name)
                    if sestava_inci and existing_inci != sestava_inci:
                        updates.append("sestava_inci = %s")
                        params.append(sestava_inci)
                    if existing_na_zalogi != na_zalogi:
                        updates.append("na_zalogi = %s")
                        params.append(na_zalogi)

                    if updates:
                        if not dry_run:
                            params.append(parfum_id)
                            cursor.execute(
                                f"UPDATE parfumi SET {', '.join(updates)}, updated_at = NOW() WHERE id = %s",
                                params,
                            )
                        result["updated"] += 1
                else:
                    if not dry_run:
                        cursor.execute(
                            """
                            INSERT INTO parfumi (
                                product_no, proizvajalec_id, ime_parfuma,
                                sestava_inci, na_zalogi, sinhroniziraj_s_shopify
                            )
                            VALUES (%s, %s, %s, %s, %s, TRUE)
                            ON CONFLICT (product_no, proizvajalec_id) DO NOTHING
                            """,
                            (product_no, proizvajalec_id, new_name, sestava_inci, na_zalogi),
                        )
                        if cursor.rowcount > 0:
                            cursor.execute(
                                """
                                INSERT INTO perfumes_stock (
                                    product_no, proizvajalec_id,
                                    on_hand, on_order_pending, on_order_committed
                                )
                                VALUES (%s, %s, 0, 0, 0)
                                ON CONFLICT (product_no, proizvajalec_id) DO NOTHING
                                """,
                                (product_no, proizvajalec_id),
                            )
                    result["added"] += 1

            except Exception as exc:
                result["errors"] += 1
                if len(result["error_messages"]) < 20:
                    result["error_messages"].append(
                        f"Napaka pri {product.get('product_no') or product.get('product_id')}: "
                        f"{str(exc)[:200]}"
                    )

        if not dry_run:
            db.commit()
        else:
            db.rollback()

        result["ok"] = result["errors"] == 0 or (result["added"] + result["updated"] > 0)
        result["duration_ms"] = int((time.time() - t0) * 1000)
        return result

    except Exception as exc:
        db.rollback()
        current_app.logger.error(f"sync_parfumi_from_shopify failed: {exc}")
        return {
            "ok": False,
            "error": f"Nepričakovana napaka: {exc}",
            "shop_domain": normalized,
        }
    finally:
        cursor.close()
