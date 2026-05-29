"""Sinhronizacija parfumov iz Shopify-ja v lokalno bazo."""

from __future__ import annotations

import re
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

INCI_METAFIELD_KEYS = (
    "custom.sestava_inci",
    "my_fields.sestava_po_inci",
    "custom.sestavine_inci",
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


def _metafields_map(node: dict[str, Any]) -> dict[str, str]:
    mf_map: dict[str, str] = {}
    for edge in (node.get("metafields") or {}).get("edges") or []:
        m = edge.get("node") or {}
        ns = m.get("namespace")
        key = m.get("key")
        if ns and key:
            mf_map[f"{ns}.{key}"] = m.get("value") or ""
    return mf_map


def _resolve_inci(mf_map: dict[str, str]) -> str | None:
    for key in INCI_METAFIELD_KEYS:
        val = (mf_map.get(key) or "").strip()
        if val:
            return val
    return None


def _resolve_ime_parfuma(mf_map: dict[str, str]) -> str | None:
    """Za nove parfume: custom.inspiration (vendor + ime brez pomišljaja; pomišljaj se doda ročno)."""
    val = (mf_map.get("custom.inspiration") or "").strip()
    return val or None


def parse_product_node(node: dict[str, Any]) -> dict[str, Any]:
    mf_map = _metafields_map(node)

    product_no = (mf_map.get("custom.product_no") or "").strip()
    proizvajalec_ime = (mf_map.get("custom.proizvajalec_id") or "").strip()
    deklaracije_vendor = (mf_map.get("custom.deklaracije_vendor") or "").strip() or None
    ime_parfuma = _resolve_ime_parfuma(mf_map)
    sestava_inci = _resolve_inci(mf_map)

    return {
        "product_id": node.get("id") or "",
        "shopify_vendor": (node.get("vendor") or "").strip(),
        "deklaracije_vendor": deklaracije_vendor,
        "product_no": product_no or None,
        "proizvajalec_ime": proizvajalec_ime or None,
        "ime_parfuma": ime_parfuma,
        "sestava_inci": sestava_inci,
    }


def _parse_product_node(node: dict[str, Any]) -> dict[str, Any]:
    return parse_product_node(node)


def _product_gid(product_id: str) -> str:
    pid = str(product_id).strip()
    if pid.startswith("gid://"):
        return pid
    numeric = re.sub(r"\D", "", pid)
    return f"gid://shopify/Product/{numeric}"


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
            errors.append(f"Shopify GraphQL errors: {str(data['errors'])[:400]}")
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


def _fetch_products_by_ids(
    shop_domain: str, product_ids: list[str]
) -> tuple[list[dict[str, Any]], list[str]]:
    products: list[dict[str, Any]] = []
    errors: list[str] = []

    for raw_id in product_ids:
        gid = _product_gid(raw_id)
        query = f"""{{
          product(id: "{gid}") {{
            id
            vendor
            metafields(first: 50) {{
              edges {{
                node {{ namespace key value }}
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
            errors.append(f"Network napaka za {raw_id}: {exc}")
            continue

        if response.status_code != 200:
            errors.append(f"Shopify {response.status_code} za {raw_id}")
            continue

        data = response.json()
        if data.get("errors"):
            errors.append(f"GraphQL napaka za {raw_id}: {str(data['errors'])[:200]}")
            continue

        node = (data.get("data") or {}).get("product")
        if not node:
            errors.append(f"Izdelek {raw_id} ni najden v Shopify")
            continue

        products.append(_parse_product_node(node))

    return products, errors


def sync_parfumi_from_shopify(
    shop_domain: str,
    *,
    dry_run: bool = False,
    update_existing: bool = False,
    product_ids: list[str] | None = None,
) -> dict[str, Any]:
    """
    Sinhronizira parfume iz izbrane Shopify trgovine v lokalno bazo.

    App je vir resnice za ime_parfuma in na_zalogi — obstoječih ne prepisujemo.
    - Novi parfumi: začetno ime iz custom.inspiration (pomišljaj se doda ročno), INCI iz Shopify
    - Obstoječi (update_existing): samo sestava_inci

    Privzeto samo doda manjkajoče (update_existing=False).
    Če je podan product_ids, posodobi INCI na obstoječih (ne ime, ne zalogo).
    """
    t0 = time.time()
    normalized = _normalize_shop_domain(shop_domain) or DEFAULT_SYNC_STORE
    targeted = bool(product_ids)
    if targeted:
        update_existing = True

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
        "targeted_product_ids": product_ids or [],
    }

    if product_ids:
        products, fetch_errors = _fetch_products_by_ids(normalized, product_ids)
    else:
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
                product_no = product.get("product_no")
                proizvajalec_ime = product.get("proizvajalec_ime")
                new_name = product.get("ime_parfuma")
                sestava_inci = product.get("sestava_inci")

                if not product_no or not proizvajalec_ime:
                    result["skipped"] += 1
                    if len(result["skipped_samples"]) < 20:
                        missing = []
                        if not product_no:
                            missing.append("product_no")
                        if not proizvajalec_ime:
                            missing.append("proizvajalec_id")
                        result["skipped_samples"].append(
                            {
                                "product_id": product.get("product_id"),
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

                cursor.execute(
                    """
                    SELECT id, ime_parfuma, sestava_inci
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
                                    "product_no": product_no,
                                    "reason": "Parfum že obstaja (preskočeno)",
                                }
                            )
                        continue

                    existing_inci = existing["sestava_inci"] if isinstance(existing, dict) else existing[2]
                    parfum_id = existing["id"] if isinstance(existing, dict) else existing[0]

                    if sestava_inci and existing_inci != sestava_inci:
                        if not dry_run:
                            cursor.execute(
                                """
                                UPDATE parfumi
                                SET sestava_inci = %s, updated_at = NOW()
                                WHERE id = %s
                                """,
                                (sestava_inci, parfum_id),
                            )
                        result["updated"] += 1
                    else:
                        result["skipped"] += 1
                        if len(result["skipped_samples"]) < 20:
                            result["skipped_samples"].append(
                                {
                                    "product_id": product.get("product_id"),
                                    "product_no": product_no,
                                    "reason": "INCI enak ali manjka v Shopify",
                                }
                            )
                else:
                    if not new_name:
                        result["skipped"] += 1
                        if len(result["skipped_samples"]) < 20:
                            result["skipped_samples"].append(
                                {
                                    "product_id": product.get("product_id"),
                                    "product_no": product_no,
                                    "reason": "Manjka: inspiration",
                                }
                            )
                        continue

                    if not dry_run:
                        cursor.execute(
                            """
                            INSERT INTO parfumi (
                                product_no, proizvajalec_id, ime_parfuma,
                                sestava_inci, na_zalogi, sinhroniziraj_s_shopify
                            )
                            VALUES (%s, %s, %s, %s, FALSE, TRUE)
                            ON CONFLICT (product_no, proizvajalec_id) DO NOTHING
                            """,
                            (
                                product_no,
                                proizvajalec_id,
                                new_name,
                                sestava_inci,
                            ),
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
