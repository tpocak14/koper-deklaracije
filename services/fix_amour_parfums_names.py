"""Popravi ime_parfuma kjer je napačen prefix AMOUR PARFUMS - (uporabi custom.deklaracije_vendor)."""

from __future__ import annotations

import re
from typing import Any

import requests
from flask import current_app

from database import get_db
from services.shopify_service import (
    _get_api_url,
    _get_shopify_headers,
    get_shopify_store_config,
)

DEFAULT_SHOP = "amour-parfums-2.myshopify.com"
AMOUR_PREFIX = re.compile(r"^AMOUR\s+PARFUMS\s*-\s*", re.IGNORECASE)


def _build_shopify_lookup(shop_domain: str) -> dict[tuple[str, str], dict[str, str]]:
    """Ključ: (product_no_upper, proizvajalec_upper) → metafield podatki."""
    lookup: dict[tuple[str, str], dict[str, str]] = {}
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
                metafields(first: 50) {{
                  edges {{
                    node {{ namespace key value }}
                  }}
                }}
              }}
            }}
          }}
        }}"""
        resp = requests.post(
            _get_api_url(shop_domain=shop_domain),
            json={"query": query},
            headers=_get_shopify_headers(shop_domain),
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("errors"):
            raise RuntimeError(str(data["errors"])[:400])

        products_data = (data.get("data") or {}).get("products") or {}
        for edge in products_data.get("edges") or []:
            node = edge.get("node") or {}
            mf: dict[str, str] = {}
            for me in (node.get("metafields") or {}).get("edges") or []:
                m = (me or {}).get("node") or {}
                ns, key = m.get("namespace"), m.get("key")
                if ns and key:
                    mf[f"{ns}.{key}"] = (m.get("value") or "").strip()

            product_no = (mf.get("custom.product_no") or "").strip().upper()
            proizvajalec = (mf.get("custom.proizvajalec_id") or "").strip().upper()
            if not product_no or not proizvajalec:
                continue

            lookup[(product_no, proizvajalec)] = {
                "deklaracije_vendor": (mf.get("custom.deklaracije_vendor") or "").strip(),
                "product_fragrance": (mf.get("custom.product_fragrance_") or "").strip(),
            }

        page_info = products_data.get("pageInfo") or {}
        has_next = bool(page_info.get("hasNextPage"))
        cursor = page_info.get("endCursor")
        if not cursor:
            has_next = False

    return lookup


def _proposed_name(current: str, shopify: dict[str, str] | None) -> tuple[str | None, str]:
    if not AMOUR_PREFIX.match(current or ""):
        return None, "ni_amour_parfums_prefix"

    fragrance = AMOUR_PREFIX.sub("", current or "").strip()
    if not fragrance:
        return None, "prazno_ime_po_prefixu"

    if not shopify:
        return None, "ni_v_shopify"

    vendor = (shopify.get("deklaracije_vendor") or "").strip()
    if not vendor:
        return None, "manjka_deklaracije_vendor"

    proposed = f"{vendor} - {fragrance}"
    return proposed, "deklaracije_vendor"


def preview_fix_amour_parfums_names(
    shop_domain: str = DEFAULT_SHOP,
) -> dict[str, Any]:
    """Predogled popravkov — ne piše v bazo."""
    store = get_shopify_store_config(shop_domain)
    if not store or not store.get("access_token"):
        return {"ok": False, "error": f"Trgovina {shop_domain} ni konfigurirana."}

    lookup = _build_shopify_lookup(shop_domain)

    db = get_db()
    cursor = db.cursor()
    result: dict[str, Any] = {
        "ok": True,
        "shop_domain": shop_domain,
        "shopify_products_indexed": len(lookup),
        "candidates": 0,
        "would_update": 0,
        "unchanged": 0,
        "skipped": 0,
        "changes": [],
        "skipped_items": [],
    }

    try:
        cursor.execute(
            """
            SELECT p.id, p.product_no, p.proizvajalec_id, pr.ime AS proizvajalec,
                   p.ime_parfuma
            FROM parfumi p
            JOIN proizvajalci pr ON pr.id = p.proizvajalec_id
            WHERE p.ime_parfuma ILIKE 'AMOUR PARFUMS -%'
            ORDER BY pr.ime, p.product_no
            """
        )
        rows = cursor.fetchall() or []
        result["candidates"] = len(rows)

        for row in rows:
            rid = row["id"] if isinstance(row, dict) else row[0]
            product_no = row["product_no"] if isinstance(row, dict) else row[1]
            proizvajalec_id = row["proizvajalec_id"] if isinstance(row, dict) else row[2]
            proizvajalec = row["proizvajalec"] if isinstance(row, dict) else row[3]
            current = row["ime_parfuma"] if isinstance(row, dict) else row[4]

            key = (str(product_no or "").strip().upper(), str(proizvajalec or "").strip().upper())
            shopify = lookup.get(key)
            proposed, reason = _proposed_name(current, shopify)

            if proposed and proposed != current:
                result["would_update"] += 1
                result["changes"].append(
                    {
                        "id": rid,
                        "product_no": product_no,
                        "proizvajalec": proizvajalec,
                        "proizvajalec_id": proizvajalec_id,
                        "from": current,
                        "to": proposed,
                        "deklaracije_vendor": (shopify or {}).get("deklaracije_vendor"),
                    }
                )
            elif proposed == current:
                result["unchanged"] += 1
            else:
                result["skipped"] += 1
                if len(result["skipped_items"]) < 50:
                    result["skipped_items"].append(
                        {
                            "id": rid,
                            "product_no": product_no,
                            "proizvajalec": proizvajalec,
                            "ime_parfuma": current,
                            "reason": reason,
                        }
                    )
    finally:
        cursor.close()

    return result


def apply_fix_amour_parfums_names(
    shop_domain: str = DEFAULT_SHOP,
    *,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Uporabi preview in po potrebi posodobi ime_parfuma v bazi."""
    preview = preview_fix_amour_parfums_names(shop_domain)
    if not preview.get("ok"):
        return preview

    preview["dry_run"] = dry_run
    preview["applied"] = 0

    if dry_run:
        return preview

    db = get_db()
    cursor = db.cursor()
    try:
        for ch in preview.get("changes") or []:
            cursor.execute(
                "UPDATE parfumi SET ime_parfuma = %s, updated_at = NOW() WHERE id = %s",
                (ch["to"], ch["id"]),
            )
            preview["applied"] += 1
        db.commit()
        return preview
    except Exception as exc:
        db.rollback()
        current_app.logger.error(f"apply_fix_amour_parfums_names failed: {exc}")
        preview["ok"] = False
        preview["error"] = str(exc)
        return preview
    finally:
        cursor.close()
