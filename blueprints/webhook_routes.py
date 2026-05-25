import hmac
import hashlib
import base64
import re
import unicodedata
import json
import traceback
import time
import os
import requests
from flask import Blueprint, request, current_app, jsonify
import threading
from database import get_db
from services.shopify_service import (
    get_bulk_product_details,
    get_shopify_webhook_secret,
    get_all_shopify_stores,
    get_all_products_for_name_sync,
    _get_api_url,
    _get_shopify_headers,
)
from services.proc_stock import (
    apply_decrement as _proc_apply_decrement,
    apply_revert as _proc_apply_revert,
    PERFUME_SUPPLIERS as _PROC_PERFUME_SUPPLIERS,
)


def _ensure_shopify_idempotency_table(c):
    try:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS proc_applied_from_shopify (
                shop_domain TEXT NOT NULL,
                event_type  TEXT NOT NULL,
                event_id    TEXT NOT NULL,
                line_item_id TEXT NOT NULL,
                sku         TEXT NOT NULL,
                qty         INTEGER NOT NULL,
                applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (shop_domain, event_type, event_id, line_item_id, sku)
            );
            """
        )
    except Exception as e:
        try:
            current_app.logger.warning(f"_ensure_shopify_idempotency_table: {e}")
        except Exception:
            pass


def _iter_proc_line_items(line_items):
    """Yield (line_item_id, sku, qty, vendor) for line items eligible for
    procurement decrement (i.e. non-empty SKU + non-perfume vendor).
    """
    if not isinstance(line_items, list):
        return
    for item in line_items:
        if not isinstance(item, dict):
            continue
        sku = str(item.get('sku') or '').strip()
        if not sku:
            continue
        vendor = (item.get('vendor') or '').strip()
        if vendor and vendor.upper() in _PROC_PERFUME_SUPPLIERS:
            continue
        try:
            qty = int(item.get('quantity') or 0)
        except (TypeError, ValueError):
            qty = 0
        if qty <= 0:
            continue
        line_item_id = str(item.get('id') or item.get('line_item_id') or sku)
        yield line_item_id, sku, qty, vendor


def _apply_shopify_decrement(c, payload, *, shop_domain, event_type):
    """Decrement proc_products.on_hand for non-perfume line items in a paid order."""
    if not isinstance(payload, dict):
        return 0
    event_id = str(payload.get('id') or payload.get('order_id') or '')
    if not event_id:
        return 0
    line_items = payload.get('line_items') or []
    if not line_items:
        return 0

    shop = shop_domain or ''
    _ensure_shopify_idempotency_table(c)

    applied_count = 0
    for line_item_id, sku, qty, vendor in _iter_proc_line_items(line_items):
        try:
            c.execute(
                """
                SELECT 1 FROM proc_applied_from_shopify
                WHERE shop_domain = %s AND event_type = %s
                  AND event_id = %s AND line_item_id = %s AND sku = %s
                """,
                (shop, event_type, event_id, line_item_id, sku),
            )
            if c.fetchone():
                continue

            res = _proc_apply_decrement(
                c, sku, qty,
                source=f'shopify_{event_type}',
                source_ref=event_id,
                supplier_hint=vendor or None,
                note=f"order={payload.get('name') or event_id}",
            )
            if not res.get('applied'):
                continue
            c.execute(
                """
                INSERT INTO proc_applied_from_shopify
                    (shop_domain, event_type, event_id, line_item_id, sku, qty)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (shop, event_type, event_id, line_item_id, sku, int(qty)),
            )
            applied_count += 1
            try:
                current_app.logger.info(
                    f"webhook/{event_type} stock decrement sku={sku} qty={qty} "
                    f"on_hand={res.get('on_hand_before')}->{res.get('on_hand_after')} "
                    f"pending={res.get('pending_before')}->{res.get('pending_after')}"
                )
            except Exception:
                pass
        except Exception as e:
            try:
                current_app.logger.error(
                    f"webhook/{event_type} apply error sku={sku} qty={qty}: {e}"
                )
            except Exception:
                pass
    return applied_count


def _apply_shopify_revert_order(c, payload, *, shop_domain, event_type):
    """Return all decrement quantities for an order back to on_hand
    (orders/cancelled).
    """
    if not isinstance(payload, dict):
        return 0
    event_id = str(payload.get('id') or payload.get('order_id') or '')
    if not event_id:
        return 0
    shop = shop_domain or ''
    _ensure_shopify_idempotency_table(c)

    # Find prior decrement events for this order (paid, fulfilled, ...) that
    # have not yet been reverted by a matching `cancel` row.
    c.execute(
        """
        SELECT line_item_id, sku, qty
        FROM proc_applied_from_shopify
        WHERE shop_domain = %s
          AND event_id = %s
          AND event_type IN ('orders/paid', 'orders/fulfilled')
        """,
        (shop, event_id),
    )
    prior = c.fetchall() or []
    if not prior:
        return 0

    reverted = 0
    for row in prior:
        line_item_id = row['line_item_id'] if isinstance(row, dict) else row[0]
        sku = row['sku'] if isinstance(row, dict) else row[1]
        qty = int(row['qty'] if isinstance(row, dict) else row[2])
        # Skip if already reverted for this event_type
        c.execute(
            """
            SELECT 1 FROM proc_applied_from_shopify
            WHERE shop_domain = %s AND event_type = %s
              AND event_id = %s AND line_item_id = %s AND sku = %s
            """,
            (shop, event_type, event_id, line_item_id, sku),
        )
        if c.fetchone():
            continue
        res = _proc_apply_revert(
            c, sku, qty,
            source=f'shopify_{event_type}',
            source_ref=event_id,
            note=f"cancel order={event_id}",
        )
        if not res.get('applied'):
            continue
        c.execute(
            """
            INSERT INTO proc_applied_from_shopify
                (shop_domain, event_type, event_id, line_item_id, sku, qty)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (shop, event_type, event_id, line_item_id, sku, qty),
        )
        reverted += 1
    return reverted


def _apply_shopify_refund(c, payload, *, shop_domain):
    """Partial revert for refunds/create webhook.

    Shopify refund payload contains `refund_line_items[*].line_item_id` and
    `quantity`. We need to look up the original line item to find sku + vendor.
    """
    if not isinstance(payload, dict):
        return 0
    refund_id = str(payload.get('id') or '')
    order_id = str(payload.get('order_id') or '')
    if not refund_id or not order_id:
        return 0

    shop = shop_domain or ''
    _ensure_shopify_idempotency_table(c)

    refund_items = payload.get('refund_line_items') or []
    line_items_raw = payload.get('line_items') or []
    by_id = {}
    for li in line_items_raw:
        if isinstance(li, dict) and li.get('id'):
            by_id[str(li.get('id'))] = li
    # Some payloads only carry refund_line_items with embedded line_item
    for rli in refund_items:
        if isinstance(rli, dict):
            li = rli.get('line_item')
            if isinstance(li, dict) and li.get('id'):
                by_id.setdefault(str(li.get('id')), li)

    reverted = 0
    for rli in refund_items:
        if not isinstance(rli, dict):
            continue
        try:
            qty = int(rli.get('quantity') or 0)
        except (TypeError, ValueError):
            qty = 0
        if qty <= 0:
            continue
        li_id = str(rli.get('line_item_id') or '')
        if not li_id:
            continue
        li = by_id.get(li_id) or {}
        sku = (li.get('sku') or '').strip()
        vendor = (li.get('vendor') or '').strip()
        if not sku:
            continue
        if vendor and vendor.upper() in _PROC_PERFUME_SUPPLIERS:
            continue
        # Idempotency keyed by refund id to allow multiple refunds per order
        event_type = 'refunds/create'
        event_id = refund_id
        c.execute(
            """
            SELECT 1 FROM proc_applied_from_shopify
            WHERE shop_domain = %s AND event_type = %s
              AND event_id = %s AND line_item_id = %s AND sku = %s
            """,
            (shop, event_type, event_id, li_id, sku),
        )
        if c.fetchone():
            continue
        res = _proc_apply_revert(
            c, sku, qty,
            source='shopify_refund',
            source_ref=f"refund={refund_id}, order={order_id}",
            supplier_hint=vendor or None,
            note=f"refund {refund_id}",
        )
        if not res.get('applied'):
            continue
        c.execute(
            """
            INSERT INTO proc_applied_from_shopify
                (shop_domain, event_type, event_id, line_item_id, sku, qty)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (shop, event_type, event_id, li_id, sku, qty),
        )
        reverted += 1
    return reverted

# Globalne spremenljivke za sledenje webhook naročil
last_webhook_order = None
last_fulfilled_order = None

webhook_bp = Blueprint('webhook', __name__, url_prefix='/webhook')

def _normalize_hmac_header(hmac_header) -> str | None:
    if not hmac_header:
        return None
    if isinstance(hmac_header, bytes):
        try:
            hmac_header = hmac_header.decode('utf-8')
        except Exception:
            return None
    return hmac_header.strip()

def _normalize_secret(secret) -> str | None:
    if not secret:
        return None
    if isinstance(secret, bytes):
        try:
            secret = secret.decode('utf-8')
        except Exception:
            return None
    secret = secret.strip()
    return secret or None


def verify_webhook(data, hmac_header, shop_domain: str | None = None):
    """Preveri, ali je webhook prišel iz Shopifyja s primerjavo HMAC-SHA256 podpisa."""
    hmac_header = _normalize_hmac_header(hmac_header)
    if not hmac_header:
        return False
    try:
        secret = _normalize_secret(get_shopify_webhook_secret(shop_domain))
        if not secret:
            return False
        digest = hmac.new(secret.encode('utf-8'), data, hashlib.sha256).digest()
        computed_hmac = base64.b64encode(digest).decode('utf-8')
        return hmac.compare_digest(computed_hmac, hmac_header)
    except Exception as e:
        current_app.logger.error(f"Napaka pri preverjanju webhooka: {e}")
        return False


def verify_hmac_env_secret(data: bytes, hmac_header: str | None) -> bool:
    """Verify Shopify HMAC using env SHOPIFY_WEBHOOK_SECRET."""
    hmac_header = _normalize_hmac_header(hmac_header)
    if not hmac_header:
        return False
    secret = _normalize_secret(current_app.config.get('SHOPIFY_WEBHOOK_SECRET'))
    if not secret:
        return False
    digest = hmac.new(secret.encode('utf-8'), data, hashlib.sha256).digest()
    computed = base64.b64encode(digest).decode('utf-8')
    return hmac.compare_digest(computed, hmac_header)

def _compare_hmac(data: bytes, hmac_header: str, secret: str) -> bool:
    hmac_header = _normalize_hmac_header(hmac_header)
    if not hmac_header:
        return False
    secret = _normalize_secret(secret)
    if not secret:
        return False
    digest = hmac.new(secret.encode('utf-8'), data, hashlib.sha256).digest()
    computed = base64.b64encode(digest).decode('utf-8')
    return hmac.compare_digest(computed, hmac_header)


def _resolve_shop_domain_from_hmac(
    data: bytes,
    hmac_header: str | None,
    shop_domain: str | None
) -> tuple[str | None, str | None]:
    """Return (preferred_api_domain, matched_store_domain)."""
    hmac_header = _normalize_hmac_header(hmac_header)
    if not hmac_header:
        return None, None
    # 1) Try provided shop domain first (normal flow)
    if shop_domain and verify_webhook(data, hmac_header, shop_domain=shop_domain):
        return shop_domain, shop_domain
    # 2) Try all known store secrets (fallback for domain aliasing/mismatch)
    try:
        env_secret = _normalize_secret(current_app.config.get('SHOPIFY_WEBHOOK_SECRET'))
        app_secret = _normalize_secret(current_app.config.get('SHOPIFY_APP_CLIENT_SECRET'))
        for store in get_all_shopify_stores(include_default=True):
            store_secret = _normalize_secret(store.get('webhook_secret'))
            candidates = [store_secret, env_secret, app_secret]
            for secret in [s for s in candidates if s]:
                if _compare_hmac(data, hmac_header, secret):
                    # Prefer header domain for API calls; keep matched store for fallback.
                    return shop_domain or store.get('shop_domain'), store.get('shop_domain')
    except Exception as e:
        current_app.logger.error(f"webhooks/products: store-secret fallback failed: {e}")
    # 3) Try config secrets even if no stores matched
    try:
        env_secret = _normalize_secret(current_app.config.get('SHOPIFY_WEBHOOK_SECRET'))
        app_secret = _normalize_secret(current_app.config.get('SHOPIFY_APP_CLIENT_SECRET'))
        for secret in [s for s in [env_secret, app_secret] if s]:
            if _compare_hmac(data, hmac_header, secret):
                return shop_domain, shop_domain
    except Exception as e:
        current_app.logger.error(f"webhooks/products: env-secret fallback failed: {e}")
    return None, None


def normalize_tag_value(value: str) -> str:
    v = (value or '').strip().lower()
    if not v:
        return ''
    v = unicodedata.normalize('NFKD', v)
    v = v.encode('ascii', 'ignore').decode('ascii')
    v = re.sub(r'[^a-z0-9]+', '-', v)
    v = re.sub(r'-{2,}', '-', v).strip('-')
    return v[:80]

def _is_mf_tag(tag: str) -> bool:
    tl = (tag or '').strip().lower()
    return (
        tl.startswith("mf_dv-")
        or tl.startswith("mf_pf-")
        or tl.startswith("mf_dv:")
        or tl.startswith("mf_pf:")
    )


def _should_remove_mf_tag(tag: str, has_dv: bool, has_pf: bool) -> bool:
    return False


def sync_product_tags_from_metafields(shop_domain: str, product_id: str) -> dict:
    query = """
    query ($id: ID!) {
      product(id: $id) {
        id
        tags
        deklaracije_vendor: metafield(namespace: "custom", key: "deklaracije_vendor") { value }
        product_fragrance: metafield(namespace: "custom", key: "product_fragrance_") { value }
      }
    }
    """
    gid = f"gid://shopify/Product/{product_id}"
    resp = requests.post(
        _get_api_url(shop_domain=shop_domain),
        headers=_get_shopify_headers(shop_domain),
        json={"query": query, "variables": {"id": gid}},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("errors"):
        raise RuntimeError(f"GraphQL errors: {data['errors']}")

    product = (data.get("data") or {}).get("product") or {}
    tags = product.get("tags") or []
    dv = normalize_tag_value((product.get("deklaracije_vendor") or {}).get("value") or "")
    pf = normalize_tag_value((product.get("product_fragrance") or {}).get("value") or "")
    has_dv = bool(dv)
    has_pf = bool(pf)

    # Keep all existing mf_* tags to allow manual additions; only append computed tags if missing.
    filtered = list(tags)

    new_tags = list(filtered)
    if has_dv:
        new_tags.append(f"mf_dv-{dv}")
    if has_pf:
        new_tags.append(f"mf_pf-{pf}")
    new_tags = list(dict.fromkeys(new_tags))

    if new_tags == tags:
        return {"changed": False, "tags": tags}

    mutation = """
    mutation ($input: ProductInput!) {
      productUpdate(input: $input) {
        product { id tags }
        userErrors { field message }
      }
    }
    """
    resp2 = requests.post(
        _get_api_url(shop_domain=shop_domain),
        headers=_get_shopify_headers(shop_domain),
        json={"query": mutation, "variables": {"input": {"id": gid, "tags": new_tags}}},
        timeout=20,
    )
    resp2.raise_for_status()
    mdata = resp2.json()
    if (mdata.get("data") or {}).get("productUpdate", {}).get("userErrors"):
        raise RuntimeError(f"userErrors: {mdata['data']['productUpdate']['userErrors']}")

    return {"changed": True, "tags": new_tags}


def sync_all_product_tags_from_metafields(shop_domain: str, sleep_seconds: float = 0.0) -> dict:
    products = get_all_products_for_name_sync(shop_domain=shop_domain)
    if products is None:
        return {"ok": False, "error": "Failed to fetch products"}

    changed_count = 0
    unchanged_count = 0
    error_count = 0

    mutation = """
    mutation ($input: ProductInput!) {
      productUpdate(input: $input) {
        product { id tags }
        userErrors { field message }
      }
    }
    """

    for product in products:
        try:
            product_gid = product.get("id")
            if not product_gid:
                error_count += 1
                continue

            tags = product.get("tags") or []
            dv = normalize_tag_value((product.get("deklaracije_vendor") or {}).get("value") or "")
            pf = normalize_tag_value((product.get("product_fragrance") or {}).get("value") or "")
            has_dv = bool(dv)
            has_pf = bool(pf)
            filtered = list(tags)

            new_tags = list(filtered)
            if has_dv:
                new_tags.append(f"mf_dv-{dv}")
            if has_pf:
                new_tags.append(f"mf_pf-{pf}")
            new_tags = list(dict.fromkeys(new_tags))

            if new_tags == tags:
                unchanged_count += 1
                continue

            resp = requests.post(
                _get_api_url(shop_domain=shop_domain),
                headers=_get_shopify_headers(shop_domain),
                json={"query": mutation, "variables": {"input": {"id": product_gid, "tags": new_tags}}},
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
            user_errors = (data.get("data") or {}).get("productUpdate", {}).get("userErrors") or []
            if user_errors:
                raise RuntimeError(f"userErrors: {user_errors}")

            changed_count += 1
            if sleep_seconds:
                time.sleep(sleep_seconds)
        except Exception as e:
            error_count += 1
            current_app.logger.error(f"sync_all_product_tags_from_metafields error: {e}")

    return {
        "ok": True,
        "changed": changed_count,
        "unchanged": unchanged_count,
        "errors": error_count,
        "total": len(products),
    }

@webhook_bp.route('/order-created', methods=['POST'])
def handle_order_created_webhook():
    """Preusmeritev za stari webhook URL"""
    current_app.logger.info("=== ORDER-CREATED WEBHOOK PRIMLJEN ===")
    current_app.logger.info(f"Headers: {dict(request.headers)}")
    current_app.logger.info(f"Data: {request.get_data()}")
    current_app.logger.info("Preusmerjam na glavni webhook handler")
    try:
        result = handle_shopify_webhook()
        current_app.logger.info("Glavni webhook handler uspešno izveden")
        return result
    except Exception as e:
        current_app.logger.error(f"Napaka v glavnem webhook handler-ju: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 200

@webhook_bp.route('/order-fulfilled', methods=['POST'])
def handle_order_fulfilled_webhook():
    """Preusmeritev za order-fulfilled webhook URL"""
    current_app.logger.info("Order-fulfilled webhook URL prejet, preusmerjam na novi")
    current_app.logger.info(f"Headers: {dict(request.headers)}")
    current_app.logger.info(f"Data: {request.get_data()}")
    return handle_shopify_webhook()

@webhook_bp.route('/order-updated', methods=['POST'])
def handle_order_updated_webhook():
    """Preusmeritev za order-updated webhook URL"""
    current_app.logger.info("Order-updated webhook URL prejet, preusmerjam na novi")
    current_app.logger.info(f"Headers: {dict(request.headers)}")
    current_app.logger.info(f"Data: {request.get_data()}")
    return handle_shopify_webhook()

@webhook_bp.route('/product-update', methods=['POST'])
def handle_product_update_webhook():
    """Preusmeritev za product-update webhook URL"""
    current_app.logger.info("Product-update webhook URL prejet, preusmerjam na novi")
    current_app.logger.info(f"Headers: {dict(request.headers)}")
    current_app.logger.info(f"Data: {request.get_data()}")
    # Defer tag sync to background to avoid H12 timeouts
    try:
        app = current_app._get_current_object()
        data = request.get_data()
        hmac_header = request.headers.get('X-Shopify-Hmac-Sha256')
        shop_domain = request.headers.get('X-Shopify-Shop-Domain')
        threading.Thread(
            target=_process_product_webhook_in_background,
            args=(app, data, hmac_header, shop_domain),
            daemon=True
        ).start()
        current_app.logger.info("webhook/product-update: queued tag sync in background")
    except Exception as e:
        current_app.logger.warning(f"webhook/product-update: failed to queue tag sync: {e}")
    return handle_shopify_webhook()

def _process_shopify_webhook_in_background(app, topic, data_bytes, shop_domain: str | None = None):
    """Heavy webhook processing executed in background to avoid request timeouts."""
    with app.app_context():
        try:
            payload = json.loads(data_bytes)
        except Exception:
            payload = {}
        db = get_db()
        cursor = db.cursor()
        try:
            # Existing heavy logic extracted from handler
            # NOTE: kept identical to prior code but without immediate returns
            if topic == 'orders/create':
                current_app.logger.info("=== OBDELAVA ORDERS/CREATE WEBHOOK (BG) ===")
                line_items = [{
                    'product_id': item.get('product_id'), 'variant_id': item.get('variant_id'),
                    'title': item.get('title'), 'quantity': item.get('quantity'),
                    'sku': item.get('sku'), 'vendor': item.get('vendor'),
                    'price': item.get('price'), 'image_url': item.get('image_url'),
                    'product_type': item.get('product_type')
                } for item in payload.get('line_items', [])]
                customer_data = payload.get('customer', {})
                shipping_address = payload.get('shipping_address', {})
                if shop_domain:
                    cursor.execute(
                        "UPDATE orders SET shopify_store_domain = %s WHERE shopify_order_id = %s AND shopify_store_domain IS NULL",
                        (shop_domain, payload.get('id')),
                    )

                order_data = (
                    payload.get('id'),
                    payload.get('name'),
                    payload.get('email'),
                    json.dumps(line_items),
                    payload.get('order_status_url'),
                    shipping_address.get('country_code', 'N/A'),
                    f"{customer_data.get('first_name', '')} {customer_data.get('last_name', '')}".strip(),
                    payload.get('created_at'),
                    shop_domain
                )
                cursor.execute(
                    """
                    INSERT INTO orders (
                        shopify_order_id, order_number, customer_email, line_items, 
                        status_url, country_code, customer_name, created_at, shopify_store_domain
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (shopify_store_domain, shopify_order_id) DO NOTHING;
                    """,
                    order_data
                )
                global last_webhook_order
                last_webhook_order = {'order_number': payload.get('name'), 'timestamp': time.time()}

            elif topic in ('orders/fulfilled', 'orders/partially_fulfilled'):
                # `orders/partially_fulfilled` pošlje Shopify, ko je naročilo
                # delno fulfilled (npr. zaradi CODFEE non-shippable line itema).
                # Za naše potrebe (PDF deklaracija + MK upload) ga obravnavamo
                # enako kot polno `orders/fulfilled`, ker je perfume del že
                # odpremljen.
                current_app.logger.info(f"=== OBDELAVA {topic.upper()} WEBHOOK (BG) ===")
                shopify_fulfilled_at = payload.get('created_at') if isinstance(payload, dict) else None
                order_id = None
                for key in ['order_id', 'id', 'order_number', 'name']:
                    if isinstance(payload, dict) and key in payload:
                        order_id = payload[key]
                        break
                if order_id:
                    if shop_domain:
                        cursor.execute(
                            "UPDATE orders SET shopify_store_domain = %s WHERE shopify_order_id = %s AND shopify_store_domain IS NULL",
                            (shop_domain, str(order_id)),
                        )
                    cursor.execute(
                        """
                        UPDATE orders
                        SET fulfilled_at = NOW(), shopify_fulfilled_at = %s
                        WHERE shopify_order_id = %s
                          AND (shopify_store_domain = %s OR shopify_store_domain IS NULL)
                        """,
                        (shopify_fulfilled_at, str(order_id), shop_domain)
                    )
                    global last_fulfilled_order
                    order_number = payload.get('name', f"#{order_id}") if isinstance(payload, dict) else f"#{order_id}"
                    last_fulfilled_order = {'order_number': order_number, 'timestamp': time.time()}

                # The existing additional fulfillment checks and declaration/email flow remain,
                # but are executed in background to avoid blocking the request.
                # Dodatna obdelava v notranjem try, da ujamemo napake in ne prekinemo handlerja
                try:
                    from services.shopify_service import get_orders_fulfillment_status, get_order_fulfillment_details, clear_product_cache, get_bulk_product_details
                    cursor.execute(
                        """
                        SELECT shopify_order_id, order_number
                        FROM orders
                        WHERE fulfilled_at IS NULL
                          AND shopify_store_domain = %s
                        LIMIT 3
                        """,
                        (shop_domain,)
                    )
                    for order in cursor.fetchall():
                        try:
                            if get_orders_fulfillment_status(order['shopify_order_id'], shop_domain=shop_domain):
                                try:
                                    details = get_order_fulfillment_details(order['shopify_order_id'], shop_domain=shop_domain)
                                    shopify_fulfilled_at2 = details.get('created_at') if details else None
                                except Exception:
                                    shopify_fulfilled_at2 = None
                                cursor.execute(
                                    """
                                    UPDATE orders
                                    SET fulfilled_at = NOW(), shopify_fulfilled_at = %s
                                    WHERE shopify_order_id = %s
                                      AND (shopify_store_domain = %s OR shopify_store_domain IS NULL)
                                    """,
                                    (shopify_fulfilled_at2, order['shopify_order_id'], shop_domain)
                                )
                                db.commit()
                        except Exception as ie:
                            current_app.logger.error(f"BG fulfilled check error: {ie}")

                    # Declaration generation and email send, unchanged logic guarded with try/except
                    cursor.execute(
                        """
                        SELECT order_number, line_items, email_sent_at
                        FROM orders
                        WHERE shopify_order_id = %s
                          AND (shopify_store_domain = %s OR shopify_store_domain IS NULL)
                        """,
                        (str(order_id), shop_domain)
                    )
                    order_data = cursor.fetchone()
                    if order_data and not order_data['email_sent_at']:
                        line_items = json.loads(order_data['line_items']) if isinstance(order_data['line_items'], str) else (order_data['line_items'] or [])
                        product_ids = [str(item.get('product_id')) for item in line_items if item and item.get('product_id')]
                        if product_ids:
                            clear_product_cache()
                            shopify_details = get_bulk_product_details(product_ids, shop_domain=shop_domain)
                            items_for_declaration = []
                            for item in line_items:
                                if not item or not item.get('product_id'): continue
                                details = shopify_details.get(str(item.get('product_id')), {})
                                if (details.get('product_type') or '').strip().lower() != 'parfumi':
                                    continue
                                if details.get('image_url'):
                                    item['image_url'] = details['image_url']
                                if details.get('product_no') and details.get('proizvajalec_id'):
                                    items_for_declaration.append({
                                        'title': item.get('title'),
                                        'product_no': details['product_no'],
                                        'proizvajalec_ime': details['proizvajalec_id'].upper()
                                    })
                            if items_for_declaration:
                                from blueprints.api_routes import _pridobi_podatke_za_deklaracijo, _shrani_deklaracijo_v_bazo
                                declaration_items, missing, warnings = _pridobi_podatke_za_deklaracijo(items_for_declaration, cursor)
                                if not missing:
                                    if _shrani_deklaracijo_v_bazo(order_data['order_number'], declaration_items, cursor):
                                        try:
                                            from services.pdf_service import ustvari_pdf
                                            from services.email_service import poslji_email_s_pdf, send_invoice_email
                                            cursor.execute(
                                                "SELECT customer_email, country_code, status_url FROM orders WHERE order_number = %s",
                                                (order_data['order_number'],)
                                            )
                                            order_details = cursor.fetchone()
                                            if order_details:
                                                pdf_path, pdf_message = ustvari_pdf(
                                                    declaration_items,
                                                    line_items,
                                                    order_details['country_code'],
                                                    order_data['order_number']
                                                )
                                                if pdf_path:
                                                    email_success = poslji_email_s_pdf(
                                                        recipient_email=order_details['customer_email'],
                                                        order_number=order_data['order_number'],
                                                        shopify_order_id=str(order_id),
                                                        pdf_path=pdf_path,
                                                        declaration_items=declaration_items,
                                                        status_url=order_details['status_url'],
                                                        shop_url=f"https://{shop_domain}" if shop_domain else f"https://{current_app.config['SHOP_NAME']}.myshopify.com",
                                                        country_code=order_details['country_code'],
                                                        line_items=line_items
                                                    )
                                                    if email_success:
                                                        cursor.execute(
                                                            "UPDATE orders SET email_sent_at = NOW(), email_recipient = %s, status = 'email_poslan', pdf_generated_at = NOW() WHERE order_number = %s",
                                                            (order_details['customer_email'], order_data['order_number'])
                                                        )
                                                    # TEST: samodejno pošlji uradni RAČUN (MK PDF) po fulfilled (adminu)
                                                    try:
                                                        from services.mk_service import mk_find_bill_any, mk_is_published, mk_print_bill_pdf
                                                        bill = mk_find_bill_any(order_data['order_number'])
                                                        if bill and mk_is_published(bill):
                                                            found_type = bill.get('_doc_type') or 'sales_bill_domestic'
                                                            official_pdf = mk_print_bill_pdf(found_type, bill.get('mk_id'))
                                                            if official_pdf:
                                                                import tempfile
                                                                with tempfile.NamedTemporaryFile(suffix=f"_{order_data['order_number']}_invoice.pdf", delete=False) as itmp:
                                                                    itmp.write(official_pdf)
                                                                    inv_pdf_path = itmp.name
                                                                try:
                                                                    send_invoice_email(
                                                                        current_app.config.get('ADMIN_EMAIL'),
                                                                        order_data['order_number'],
                                                                        inv_pdf_path,
                                                                        country_code=order_details['country_code'],
                                                                        status_url=order_details['status_url'],
                                                                        store_url=f"https://{shop_domain}" if shop_domain else f"https://{current_app.config['SHOP_NAME']}.myshopify.com",
                                                                        items=line_items,
                                                                        skip_test_redirect=False
                                                                    )
                                                                finally:
                                                                    try:
                                                                        if os.path.exists(inv_pdf_path):
                                                                            os.remove(inv_pdf_path)
                                                                    except Exception:
                                                                        pass
                                                        else:
                                                            current_app.logger.info(f"Auto invoice: bill not published or not found for order {order_data['order_number']}")
                                                    except Exception as _ie:
                                                        current_app.logger.warning(f"Auto send invoice (admin) failed: {_ie}")
                                                    try:
                                                        if os.path.exists(pdf_path):
                                                            os.remove(pdf_path)
                                                    except Exception:
                                                        pass
                                        except Exception as email_err:
                                            current_app.logger.error(f"Napaka pri generiranju PDF/pošiljanju emaila: {email_err}")
                                            traceback.print_exc()
                                        db.commit()
                except Exception as e:
                    current_app.logger.error(f"Napaka v notranji BG obdelavi fulfilled webhooka: {e}")
                    traceback.print_exc()
            elif topic in ('fulfillments/create', 'fulfillments/update'):
                # Modern Shopify topic, ki nadomešča stari `orders/fulfilled`.
                # Payload je en fulfillment record:
                #   { id, order_id, status, created_at, updated_at,
                #     tracking_number, tracking_company, shipment_status, ... }
                #
                # Posodobimo samo fulfilled_at/shopify_fulfilled_at na orders;
                # PDF + MK upload prevzame 21:00 batch (ali hourly reconcile).
                # Tako tudi ne podvajamo logike z `orders/fulfilled` blokom in
                # se izognemo race-conditionom (oba topica lahko prispeta).
                current_app.logger.info(f"=== OBDELAVA {topic.upper()} WEBHOOK (BG) ===")
                if not isinstance(payload, dict):
                    pass
                else:
                    order_id = payload.get('order_id') or payload.get('order', {}).get('id') if isinstance(payload.get('order'), dict) else payload.get('order_id')
                    if not order_id:
                        # Fallback: nekateri payload-i imajo 'order_id' v vgnezdeni strukturi
                        for k in ('order_id', 'orderId'):
                            v = payload.get(k)
                            if v:
                                order_id = v
                                break
                    fulfillment_status = (payload.get('status') or '').strip().lower()
                    shipment_status = (payload.get('shipment_status') or '').strip().lower()
                    created_at = payload.get('created_at')
                    fulfillment_id = payload.get('id')
                    tracking_no = (
                        payload.get('tracking_number')
                        or (payload.get('tracking_numbers') or [None])[0]
                    )
                    tracking_company = payload.get('tracking_company')
                    tracking_url = (
                        payload.get('tracking_url')
                        or (payload.get('tracking_urls') or [None])[0]
                    )

                    if order_id:
                        try:
                            if shop_domain:
                                cursor.execute(
                                    "UPDATE orders SET shopify_store_domain = %s WHERE shopify_order_id = %s AND shopify_store_domain IS NULL",
                                    (shop_domain, str(order_id)),
                                )

                            # fulfilled_at označimo, samo če je status 'success' (Shopify aktivni fulfillment)
                            # in lokalni fulfilled_at je še prazen — da ne overwrite-amo ročno vnesene vrednosti.
                            if fulfillment_status in ('success', 'open'):
                                cursor.execute(
                                    """
                                    UPDATE orders
                                    SET fulfilled_at = COALESCE(fulfilled_at, NOW()),
                                        shopify_fulfilled_at = COALESCE(shopify_fulfilled_at, %s),
                                        shopify_fulfillment_id = COALESCE(shopify_fulfillment_id, %s),
                                        tracking_number = COALESCE(tracking_number, %s),
                                        tracking_company = COALESCE(tracking_company, %s),
                                        tracking_url = COALESCE(tracking_url, %s)
                                    WHERE shopify_order_id = %s
                                      AND (shopify_store_domain = %s OR shopify_store_domain IS NULL)
                                    """,
                                    (
                                        created_at,
                                        str(fulfillment_id) if fulfillment_id else None,
                                        tracking_no,
                                        tracking_company,
                                        tracking_url,
                                        str(order_id),
                                        shop_domain,
                                    ),
                                )
                            elif fulfillment_status == 'cancelled':
                                # Če je fulfillment storniran, ne brisemo fulfilled_at avtomatsko
                                # (admin lahko ima delni fulfillment). Samo logiramo.
                                current_app.logger.info(
                                    f"Fulfillment {fulfillment_id} for order {order_id} cancelled — fulfilled_at not cleared."
                                )

                            # delivered → tudi to označimo, da bomo zdaj lahko sprožili MK pipeline
                            if shipment_status == 'delivered':
                                cursor.execute(
                                    """
                                    UPDATE orders
                                    SET delivered_at = COALESCE(delivered_at, NOW()),
                                        delivered_source = COALESCE(delivered_source, 'shopify_webhook')
                                    WHERE shopify_order_id = %s
                                      AND (shopify_store_domain = %s OR shopify_store_domain IS NULL)
                                    """,
                                    (str(order_id), shop_domain),
                                )

                            db.commit()
                            current_app.logger.info(
                                f"Webhook {topic} → order_id={order_id}, fulfillment={fulfillment_id}, "
                                f"status={fulfillment_status}, shipment={shipment_status}, tracking={tracking_no}"
                            )
                            # `last_fulfilled_order` je že deklariran kot global
                            # v zgornjem `orders/fulfilled` bloku iste funkcije,
                            # zato ga tukaj samo prisvojimo (Python prepoveduje
                            # dvojni `global X` v isti funkciji).
                            try:
                                last_fulfilled_order = {  # noqa: F841
                                    'order_number': f"shopify:{order_id}",
                                    'timestamp': time.time(),
                                    'via': topic,
                                }
                            except Exception:
                                pass
                        except Exception as e:
                            current_app.logger.error(f"Napaka pri obdelavi {topic} za order {order_id}: {e}")
                            traceback.print_exc()
                            try:
                                db.rollback()
                            except Exception:
                                pass

            elif topic == 'products/update':
                product_id = str(payload.get('id')) if isinstance(payload, dict) else None
                if product_id:
                    tags = {tag.strip().upper() for tag in (payload.get('tags', '') if isinstance(payload, dict) else '').split(',')}
                    na_zalogi = 'GREEN' in tags
                    from services.shopify_service import get_bulk_product_details
                    details = get_bulk_product_details([product_id], shop_domain=shop_domain)
                    product_details = details.get(product_id)
                    if product_details and product_details.get('product_no') and product_details.get('proizvajalec_id'):
                        cursor.execute(
                            """
                            UPDATE parfumi p SET na_zalogi = %s
                            FROM proizvajalci pr
                            WHERE p.proizvajalec_id = pr.id
                            AND p.product_no = %s AND pr.ime = %s
                            """,
                            (na_zalogi, product_details['product_no'], product_details['proizvajalec_id'].upper())
                        )

            elif topic == 'orders/paid':
                # Decrement proc_products.on_hand for non-perfume line items.
                # Triggered on payment so the inventory is accurate even before
                # fulfillment. Idempotent via proc_applied_from_shopify.
                try:
                    n = _apply_shopify_decrement(
                        cursor, payload,
                        shop_domain=shop_domain, event_type='orders/paid',
                    )
                    if n:
                        current_app.logger.info(
                            f"webhook/orders/paid: applied stock decrement for {n} item(s)"
                        )
                except Exception as e:
                    current_app.logger.error(f"webhook/orders/paid stock decrement error: {e}")
                    traceback.print_exc()

            elif topic == 'orders/cancelled':
                # Return any previously-decremented stock back to on_hand.
                try:
                    n = _apply_shopify_revert_order(
                        cursor, payload,
                        shop_domain=shop_domain, event_type='orders/cancelled',
                    )
                    if n:
                        current_app.logger.info(
                            f"webhook/orders/cancelled: reverted stock for {n} item(s)"
                        )
                except Exception as e:
                    current_app.logger.error(f"webhook/orders/cancelled revert error: {e}")
                    traceback.print_exc()

            elif topic == 'refunds/create':
                try:
                    n = _apply_shopify_refund(
                        cursor, payload, shop_domain=shop_domain,
                    )
                    if n:
                        current_app.logger.info(
                            f"webhook/refunds/create: reverted stock for {n} item(s)"
                        )
                except Exception as e:
                    current_app.logger.error(f"webhook/refunds/create error: {e}")
                    traceback.print_exc()

            db.commit()
        except Exception as e:
            db.rollback()
            current_app.logger.error(f"Napaka v BG obdelavi webhooka za topic '{topic}': {e}")
            traceback.print_exc()
        finally:
            try:
                cursor.close()
            except Exception:
                pass


@webhook_bp.route('/shopify', methods=['POST'])
def handle_shopify_webhook():
    """
    Enotna in robustna točka za obdelavo VSEH webhookov iz Shopifyja.
    Vedno vrne status 200, da prepreči ponovne poskuse s strani Shopifyja.
    """
    import time
    current_app.logger.info("=== SHOPIFY WEBHOOK PRIMLJEN ===")
    current_app.logger.info("Začenjam obdelavo webhook-a...")
    current_app.logger.info(f"Headers: {dict(request.headers)}")
    current_app.logger.info(f"Method: {request.method}")
    current_app.logger.info(f"URL: {request.url}")
    
    # 1. Takoj preveri veljavnost klica.
    hmac_header = request.headers.get('X-Shopify-Hmac-Sha256')
    data = request.get_data()
    shop_domain = request.headers.get('X-Shopify-Shop-Domain') or request.args.get('shop')
    
    current_app.logger.info(f"HMAC header: {hmac_header}")
    current_app.logger.info(f"Data length: {len(data)} bytes")
    
    if hmac_header:
        current_app.logger.info(f"HMAC header prisoten: {hmac_header}")
        api_domain, matched_domain = _resolve_shop_domain_from_hmac(data, hmac_header, shop_domain)
        if not api_domain:
            current_app.logger.warning("Neveljaven webhook klic zavrnjen (napačen podpis ali manjkajoč secret).")
            # Kljub napaki vrnemo 200, da Shopify ne pošilja znova. Napaka je zabeležena.
            return jsonify({"status": "error", "message": "Invalid signature"}), 200
        if shop_domain and matched_domain and shop_domain != matched_domain:
            current_app.logger.info(f"webhook: domain mismatch {shop_domain} -> {matched_domain}")
        shop_domain = api_domain
    else:
        current_app.logger.info("HMAC header manjka - nadaljujem brez preverjanja")

    # 2. Preberi minimalne podatke in obdelaj v ozadju.
    topic = request.headers.get('X-Shopify-Topic')
    app = current_app._get_current_object()
    threading.Thread(target=_process_shopify_webhook_in_background, args=(app, topic, data, shop_domain), daemon=True).start()
    # 3. Takoj odgovorimo 200, da Shopify ne ponavlja in da se izognemo H12 timeoutom.
    return jsonify({"status": "accepted"}), 200

@webhook_bp.route('/check-new-orders', methods=['GET'])
def check_webhook_orders():
    """Preveri, ali so nova naročila ali fulfilled naročila preko webhookov"""
    global last_webhook_order, last_fulfilled_order
    
    # Preveri nova naročila
    if last_webhook_order is not None and time.time() - last_webhook_order['timestamp'] < 300:  # 5 minut
        order_info = last_webhook_order.copy()
        last_webhook_order = None  # Reset, da se ne pošlje večkrat
        return jsonify({
            "has_new_orders": True,
            "order_number": order_info['order_number'],
            "timestamp": order_info['timestamp']
        })
    
    # Preveri fulfilled naročila
    if last_fulfilled_order is not None and time.time() - last_fulfilled_order['timestamp'] < 300:  # 5 minut
        order_info = last_fulfilled_order.copy()
        last_fulfilled_order = None  # Reset, da se ne pošlje večkrat
        return jsonify({
            "has_fulfilled_orders": True,
            "order_number": order_info['order_number'],
            "timestamp": order_info['timestamp']
        })
    
    return jsonify({"has_new_orders": False, "has_fulfilled_orders": False})


@webhook_bp.route('/webhooks/products', methods=['POST'])
def webhook_products():
    data = request.get_data()
    hmac_header = request.headers.get('X-Shopify-Hmac-Sha256')
    shop_domain = request.headers.get('X-Shopify-Shop-Domain')

    api_domain, matched_domain = _resolve_shop_domain_from_hmac(data, hmac_header, shop_domain)
    if not api_domain:
        current_app.logger.warning("webhooks/products: invalid HMAC")
        return jsonify({"error": "Invalid HMAC"}), 401

    # Defer heavy tag sync to background
    app = current_app._get_current_object()
    threading.Thread(
        target=_process_product_webhook_in_background,
        args=(app, data, hmac_header, shop_domain),
        daemon=True
    ).start()
    return jsonify({"status": "accepted"}), 200


def _process_product_webhook_in_background(app, data_bytes: bytes, hmac_header: str | None, shop_domain: str | None):
    with app.app_context():
        api_domain, matched_domain = _resolve_shop_domain_from_hmac(data_bytes, hmac_header, shop_domain)
        if not api_domain:
            current_app.logger.warning("webhooks/products: invalid HMAC (bg)")
            return
        payload = {}
        try:
            payload = json.loads(data_bytes)
        except Exception:
            pass
        product_id = payload.get('id')
        if not product_id:
            current_app.logger.warning("webhooks/products: missing product id (bg)")
            return
        try:
            if shop_domain and matched_domain and shop_domain != matched_domain:
                current_app.logger.info(f"webhooks/products: domain mismatch {shop_domain} -> {matched_domain}")
            current_app.logger.info(f"webhooks/products: processing product {product_id} on {api_domain} (bg)")
            try:
                res = sync_product_tags_from_metafields(api_domain, str(product_id))
            except Exception as e:
                if matched_domain and matched_domain != api_domain:
                    current_app.logger.warning(
                        f"webhooks/products: API failed on {api_domain}, retrying with {matched_domain}: {e}"
                    )
                    res = sync_product_tags_from_metafields(matched_domain, str(product_id))
                else:
                    raise
            if res.get("changed"):
                current_app.logger.info(f"webhooks/products: product {product_id} tags updated (bg)")
            else:
                current_app.logger.info(f"webhooks/products: product {product_id} no change (bg)")
        except Exception as e:
            current_app.logger.error(f"webhooks/products: Shopify API error (bg): {e}")