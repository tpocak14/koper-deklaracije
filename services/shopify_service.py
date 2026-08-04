import requests
from flask import current_app
import time
import traceback
import json
import os
import re
import threading
from database import get_db

# Predpomnilnik za metafields, da se izognemo ponavljajočim se klicem
_product_metafields_cache = {}
_cache_expiry_time = 300  # 5 minut
_cache_last_cleared = 0

# Samo veljavni myshopify hosti — zavrne '/', '#', '?', ':', '@' (SSRF / token leak).
_SHOP_DOMAIN_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,58}[a-z0-9]\.myshopify\.com$")


def _normalize_shop_domain(shop_domain: str | None) -> str | None:
    if not shop_domain:
        return None
    sd = shop_domain.strip().lower()
    if sd.startswith("https://"):
        sd = sd.replace("https://", "", 1)
    if sd.startswith("http://"):
        sd = sd.replace("http://", "", 1)
    # Odstrani morebitno pot/query, če je prišlo v query string
    sd = sd.split("/")[0].split("?")[0].split("#")[0].split(":")[0]
    if not sd.endswith(".myshopify.com"):
        sd = f"{sd}.myshopify.com"
    if not _SHOP_DOMAIN_RE.match(sd):
        return None
    return sd


def get_shopify_store_config(shop_domain: str | None) -> dict | None:
    """Fetch store config from DB for a given domain."""
    sd = _normalize_shop_domain(shop_domain)
    if not sd:
        return None
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            SELECT shop_domain, access_token, webhook_secret, order_prefix, is_active
            FROM shopify_stores
            WHERE shop_domain = %s AND is_active = TRUE
            """,
            (sd,),
        )
        row = cursor.fetchone()
        return dict(row) if row and not isinstance(row, dict) else row
    except Exception as e:
        current_app.logger.error(f"Shopify store config lookup failed for {sd}: {e}")
        return None
    finally:
        cursor.close()


def upsert_shopify_store_config(shop_domain: str, access_token: str, webhook_secret: str | None = None, order_prefix: str | None = None) -> None:
    """Insert or update store config in DB."""
    sd = _normalize_shop_domain(shop_domain)
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO shopify_stores (shop_domain, access_token, webhook_secret, order_prefix, updated_at)
            VALUES (%s, %s, %s, %s, NOW())
            ON CONFLICT (shop_domain)
            DO UPDATE SET
                access_token = EXCLUDED.access_token,
                webhook_secret = COALESCE(EXCLUDED.webhook_secret, shopify_stores.webhook_secret),
                order_prefix = COALESCE(EXCLUDED.order_prefix, shopify_stores.order_prefix),
                updated_at = NOW()
            """,
            (sd, access_token, webhook_secret, order_prefix),
        )
        db.commit()
    except Exception as e:
        db.rollback()
        current_app.logger.error(f"Shopify store config upsert failed for {sd}: {e}")
    finally:
        cursor.close()


def get_all_shopify_stores(include_default: bool = True) -> list[dict]:
    """Return list of shopify stores configured in DB (plus default config if requested)."""
    stores: list[dict] = []
    if include_default:
        shop_name = current_app.config.get('SHOP_NAME')
        token = current_app.config.get('SHOPIFY_API_PASSWORD')
        if shop_name and token:
            stores.append({
                'shop_domain': f"{shop_name}.myshopify.com",
                'access_token': token,
                'webhook_secret': current_app.config.get('SHOPIFY_WEBHOOK_SECRET'),
                'order_prefix': '#',
                'is_default': True,
            })
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            SELECT shop_domain, access_token, webhook_secret, order_prefix
            FROM shopify_stores
            WHERE is_active = TRUE
            ORDER BY shop_domain
            """
        )
        for row in cursor.fetchall() or []:
            rdict = dict(row) if not isinstance(row, dict) else row
            rdict['is_default'] = False
            stores.append(rdict)
    except Exception as e:
        current_app.logger.error(f"Shopify stores list failed: {e}")
    finally:
        cursor.close()
    return stores


def get_shopify_webhook_secret(shop_domain: str | None) -> str | None:
    """Resolve webhook secret for the given shop domain."""
    store = get_shopify_store_config(shop_domain)
    if store and store.get('webhook_secret'):
        return store.get('webhook_secret')
    return current_app.config.get('SHOPIFY_WEBHOOK_SECRET') or current_app.config.get('SHOPIFY_APP_CLIENT_SECRET')

def _get_shopify_headers(shop_domain: str | None = None):
    """Pridobi glavo za avtentikacijo pri Shopify API.

    Če je podan shop_domain, mora biti znan store — sicer ne smeš pasti
    na privzeti SHOPIFY_API_PASSWORD (to bi uhajalo token na tuj host).
    """
    token = None
    if shop_domain:
        sd = _normalize_shop_domain(shop_domain)
        if not sd:
            raise ValueError("Neveljavna Shopify domena")
        store = get_shopify_store_config(sd)
        if not store or not store.get("access_token"):
            # Dovoli privzeti shop iz env (SHOP_NAME), drugače zavrni.
            shop_name = (current_app.config.get("SHOP_NAME") or "").strip().lower()
            default_sd = f"{shop_name}.myshopify.com" if shop_name else None
            if default_sd and sd == default_sd:
                token = current_app.config.get("SHOPIFY_API_PASSWORD")
            else:
                raise ValueError("Neznana Shopify domena")
        else:
            token = store.get("access_token")
    else:
        token = current_app.config.get("SHOPIFY_API_PASSWORD")
    if not token:
        raise ValueError("Konfiguracijska spremenljivka SHOPIFY_API_PASSWORD ni nastavljena!")

    return {
        "Content-Type": "application/json",
        "X-Shopify-Access-Token": token,
    }

def _get_api_url(endpoint="graphql.json", shop_domain: str | None = None):
    """Sestavi URL za Shopify API."""
    sd = _normalize_shop_domain(shop_domain) if shop_domain else None
    if shop_domain and not sd:
        raise ValueError("Neveljavna Shopify domena")
    api_version = os.environ.get('SHOPIFY_API_VERSION') or current_app.config.get('SHOPIFY_API_VERSION', '2025-01')
    if sd:
        return f"https://{sd}/admin/api/{api_version}/{endpoint}"
    shop_name = current_app.config.get('SHOP_NAME')
    if not shop_name:
        raise ValueError("Konfiguracijska spremenljivka SHOP_NAME ni nastavljena!")
    return f"https://{shop_name}.myshopify.com/admin/api/{api_version}/{endpoint}"

# --- Shopify REST rate-limiting helpers ---
_shopify_rate_lock = threading.Lock()
_shopify_next_allowed_at = 0.0


def _get_min_interval_s() -> float:
    # Ne uporabljaj current_app ob importu; beremo ob klicu
    try:
        env_val = os.environ.get('SHOPIFY_MIN_INTERVAL')
        if env_val is not None:
            return float(env_val)
    except Exception:
        pass
    try:
        # current_app may not be available during import; guard access
        cfg = current_app.config.get('SHOPIFY_MIN_INTERVAL')  # type: ignore[attr-defined]
        if cfg is not None:
            return float(cfg)
    except Exception:
        pass
    return 0.3  # privzeto ~3-4 rps


def _respect_rate_limit_before_request():
    global _shopify_next_allowed_at
    with _shopify_rate_lock:
        now = time.time()
        wait_s = max(0.0, _shopify_next_allowed_at - now)
    if wait_s > 0:
        time.sleep(wait_s)


def _bump_after_response(resp):
    """Adjust next_allowed_at based on headers usage and minimum pacing."""
    global _shopify_next_allowed_at
    now = time.time()
    # Always enforce minimum spacing
    next_at = now + max(0.05, _get_min_interval_s())
    try:
        header = resp.headers.get('X-Shopify-Shop-Api-Call-Limit') or ''  # e.g., '10/80'
        if '/' in header:
            used, cap = header.split('/', 1)
            used = int(used.strip()); cap = int(cap.strip())
            # If we're above 70% capacity, slow down a bit more
            if cap > 0 and (used / cap) >= 0.7:
                next_at = max(next_at, now + 0.6)
    except Exception:
        pass
    with _shopify_rate_lock:
        _shopify_next_allowed_at = max(_shopify_next_allowed_at, next_at)


def _shopify_get_with_retry(url: str, *, max_retries: int = 5, timeout: int = 20, shop_domain: str | None = None) -> requests.Response:
    """GET with retry/backoff for Shopify 429/5xx and rate pacing.

    Raises requests.exceptions.HTTPError if non-retriable and not ok after retries.
    """
    backoff = 1.0
    last_exc = None
    for attempt in range(max_retries):
        _respect_rate_limit_before_request()
        try:
            resp = requests.get(url, headers=_get_shopify_headers(shop_domain), timeout=timeout)
        except requests.exceptions.RequestException as e:
            last_exc = e
            time.sleep(backoff)
            backoff = min(backoff * 2.0, 8.0)
            continue

        if resp.status_code == 429:
            # Too many requests – respect Retry-After if present
            ra = resp.headers.get('Retry-After')
            try:
                delay = float(ra)
            except Exception:
                delay = max(2.0, backoff)
            current_app.logger.warning(f"Shopify 429 for {url} – retrying in {delay:.1f}s (attempt {attempt+1}/{max_retries})")
            with _shopify_rate_lock:
                global _shopify_next_allowed_at
                _shopify_next_allowed_at = max(_shopify_next_allowed_at, time.time() + delay)
            time.sleep(delay)
            backoff = min(max(2.0, backoff * 2.0), 16.0)
            continue

        if 500 <= resp.status_code < 600:
            current_app.logger.warning(f"Shopify {resp.status_code} for {url} – retrying in {backoff:.1f}s")
            time.sleep(backoff)
            backoff = min(backoff * 2.0, 8.0)
            continue

        # Success or client error we won't retry
        _bump_after_response(resp)
        resp.raise_for_status()
        return resp

    # Out of retries
    if last_exc:
        raise last_exc
    # Try one final request to raise with details
    resp = requests.get(url, headers=_get_shopify_headers(shop_domain), timeout=timeout)
    _bump_after_response(resp)
    resp.raise_for_status()
    return resp


def _shopify_post_with_retry(
    url: str,
    *,
    json_body: dict,
    max_retries: int = 4,
    timeout: int = 25,
    shop_domain: str | None = None,
) -> requests.Response:
    """POST (GraphQL) z retry/backoff za Shopify 429/5xx in prehodne
    transportne napake (timeout, connection reset) + rate pacing.

    Pomembno za pridobivanje deklaracijskih metafield-ov: brez retryja je en
    sam timeout pomenil prazen rezultat in lažno blokado naročila
    (`pdf_generation_blocked_reason = "Shopify ni vrnil podatkov..."`).

    Vrže requests.exceptions.RequestException, če po vseh poskusih ne uspe.
    """
    backoff = 1.0
    last_exc = None
    for attempt in range(max_retries):
        _respect_rate_limit_before_request()
        try:
            resp = requests.post(
                url,
                json=json_body,
                headers=_get_shopify_headers(shop_domain),
                timeout=timeout,
            )
        except requests.exceptions.RequestException as e:
            last_exc = e
            current_app.logger.warning(
                f"Shopify POST transport napaka za {url} "
                f"(poskus {attempt+1}/{max_retries}): {e}"
            )
            time.sleep(backoff)
            backoff = min(backoff * 2.0, 8.0)
            continue

        if resp.status_code == 429:
            ra = resp.headers.get('Retry-After')
            try:
                delay = float(ra)
            except Exception:
                delay = max(2.0, backoff)
            current_app.logger.warning(
                f"Shopify 429 (POST) za {url} – retry čez {delay:.1f}s "
                f"(poskus {attempt+1}/{max_retries})"
            )
            with _shopify_rate_lock:
                global _shopify_next_allowed_at
                _shopify_next_allowed_at = max(
                    _shopify_next_allowed_at, time.time() + delay
                )
            time.sleep(delay)
            backoff = min(max(2.0, backoff * 2.0), 16.0)
            continue

        if 500 <= resp.status_code < 600:
            current_app.logger.warning(
                f"Shopify {resp.status_code} (POST) za {url} – retry čez {backoff:.1f}s"
            )
            time.sleep(backoff)
            backoff = min(backoff * 2.0, 8.0)
            continue

        _bump_after_response(resp)
        resp.raise_for_status()
        return resp

    # Po vseh poskusih
    if last_exc:
        raise last_exc
    resp = requests.post(
        url,
        json=json_body,
        headers=_get_shopify_headers(shop_domain),
        timeout=timeout,
    )
    _bump_after_response(resp)
    resp.raise_for_status()
    return resp


def clear_product_cache(store_key: str | None = None):
    """Počisti predpomnilnik izdelkov (globalno ali za določen store)."""
    global _product_metafields_cache, _cache_last_cleared
    if store_key:
        _product_metafields_cache.pop(store_key, None)
    else:
        _product_metafields_cache.clear()
    _cache_last_cleared = time.time()
    current_app.logger.info("Shopify product cache cleared.")

def get_bulk_product_details(product_ids, shop_domain: str | None = None):
    """Pridobi podrobnosti za več izdelkov hkrati preko GraphQL.
    Robustno: uporablja cache, pošilja v batchih in ima časovno omejitev, da ne blokira workerjev.
    """
    global _product_metafields_cache, _cache_last_cleared

    # Samodejno čistimo cache le po preteku časa
    if time.time() - _cache_last_cleared > _cache_expiry_time:
        clear_product_cache()

    store_key = _normalize_shop_domain(shop_domain) or current_app.config.get('SHOP_NAME') or 'default'
    store_cache = _product_metafields_cache.setdefault(store_key, {})
    ids_to_fetch = [pid for pid in product_ids if pid not in store_cache]

    if not ids_to_fetch:
        current_app.logger.info("All product details found in cache.")
        return store_cache

    current_app.logger.info(f"Fetching details for {len(ids_to_fetch)} products from Shopify (batched).")

    def _batches(seq, size):
        for i in range(0, len(seq), size):
            yield seq[i:i+size]

    try:
        for batch in _batches(ids_to_fetch, 50):  # varni batchi
            gids = [f'"gid://shopify/Product/{pid}"' for pid in batch]
            query = f"""
            {{
              nodes(ids: [{', '.join(gids)}]) {{
                id
                ... on Product {{
                  productType
                  images(first: 1) {{
                    edges {{ node {{ url }} }}
                  }}
                  product_no: metafield(namespace: "custom", key: "product_no") {{ value }}
                  proizvajalec_id: metafield(namespace: "custom", key: "proizvajalec_id") {{ value }}
                }}
              }}
            }}
            """
            try:
                response = _shopify_post_with_retry(
                    _get_api_url(shop_domain=shop_domain),
                    json_body={'query': query},
                    shop_domain=shop_domain,
                )
                data = response.json()
            except requests.exceptions.RequestException as e:
                current_app.logger.error(f"Shopify batch fetch failed after retries (size={len(batch)}): {e}")
                continue

            if isinstance(data, dict) and 'errors' in data:
                current_app.logger.error(f"Shopify GraphQL errors: {data['errors']}")
                continue

            for node in (data.get('data', {}) or {}).get('nodes', []) if isinstance(data, dict) else []:
                if not node:
                    continue
                product_id = node.get('id', '').split('/')[-1]
                if not product_id:
                    continue
                image_url = None
                try:
                    edges = (((node.get('images') or {}).get('edges')) or [])
                    if edges:
                        image_url = (edges[0].get('node') or {}).get('url')
                except Exception:
                    image_url = None
                store_cache[product_id] = {
                    'product_type': node.get('productType'),
                    'product_no': (node.get('product_no') or {}).get('value') if node.get('product_no') else None,
                    'proizvajalec_id': (node.get('proizvajalec_id') or {}).get('value') if node.get('proizvajalec_id') else None,
                    'image_url': image_url
                }

        return store_cache

    except Exception as e:
        current_app.logger.error(f"An unexpected error occurred in get_bulk_product_details: {e}")
        return store_cache

def get_all_products_for_name_sync(shop_domain: str | None = None):
    """Učinkovito pridobi vse izdelke za sinhronizacijo parfumov z vsemi potrebnimi podatki."""
    products = []
    hasNextPage = True
    cursor = None

    while hasNextPage:
        after_cursor = f', after: "{cursor}"' if cursor else ""
        query = f"""
        {{
          products(first: 250{after_cursor}) {{
            pageInfo {{
              hasNextPage
              endCursor
            }}
            edges {{
              node {{
                id
                vendor
                tags
                metafields(first: 50) {{
                  edges {{
                    node {{
                      namespace
                      key
                      value
                    }}
                  }}
                }}
              }}
            }}
          }}
        }}
        """
        try:
            current_app.logger.info(f"Fetching products from Shopify (cursor: {cursor})")
            response = requests.post(_get_api_url(shop_domain=shop_domain), json={'query': query}, headers=_get_shopify_headers(shop_domain))
            response.raise_for_status()
            data = response.json()

            if 'errors' in data:
                error_msg = f"GraphQL errors: {data['errors']}"
                current_app.logger.error(error_msg)
                raise Exception(error_msg)

            # Preverimo, če je data None ali prazno
            if not data or 'data' not in data:
                current_app.logger.error(f"Invalid response from Shopify: {data}")
                raise Exception("Invalid response from Shopify")

            products_data = data.get('data', {}).get('products', {})
            if not products_data:
                current_app.logger.error(f"No products data in response: {data}")
                raise Exception("No products data in response")

            edges = products_data.get('edges', [])
            current_app.logger.info(f"Retrieved {len(edges)} products from Shopify")

            for edge in edges:
                node = edge.get('node')
                if not node:
                    current_app.logger.warning("Skipping edge with no node")
                    continue
                    
                # Pridobi metafield-e
                metafields = {}
                metafields_data = node.get('metafields', {})
                if metafields_data and 'edges' in metafields_data:
                    for metafield_edge in metafields_data.get('edges', []):
                        metafield_node = metafield_edge.get('node')
                        if metafield_node:
                            namespace = metafield_node.get('namespace', '')
                            key = metafield_node.get('key', '')
                            value = metafield_node.get('value', '')
                            metafields[f"{namespace}.{key}"] = value
                
                # Debug logging za prve 3 izdelke
                if len(products) < 3:
                    current_app.logger.info(f"Product {node.get('id')} metafields: {list(metafields.keys())}")
                    current_app.logger.info(f"Product {node.get('id')} vendor: {node.get('vendor')}")
                    current_app.logger.info(f"Product {node.get('id')} tags: {node.get('tags')}")
                
                # Določimo INCI podatke (najprej my_fields, nato custom)
                inci_value = None
                if 'my_fields.sestava_po_inci' in metafields:
                    inci_value = metafields['my_fields.sestava_po_inci']
                    current_app.logger.debug(f"Found INCI in my_fields.sestava_po_inci for product {node.get('id')}")
                elif 'custom.sestavine_inci' in metafields:
                    inci_value = metafields['custom.sestavine_inci']
                    current_app.logger.debug(f"Found INCI in custom.sestavine_inci for product {node.get('id')}")
                
                # Določimo status zaloge iz tagov
                tags = node.get('tags', [])
                na_zalogi = 'GREEN' in tags
                
                # Dodamo INCI in status v node
                node['sestava_inci'] = {'value': inci_value}
                node['na_zalogi'] = na_zalogi
                
                # Dodamo metafield-e v node za lažji dostop
                node['product_fragrance'] = {'value': metafields.get('custom.product_fragrance_', '')}
                node['deklaracije_vendor'] = {'value': metafields.get('custom.deklaracije_vendor', '')}
                node['product_no'] = {'value': metafields.get('custom.product_no', '')}
                node['proizvajalec_id'] = {'value': metafields.get('custom.proizvajalec_id', '')}
                
                products.append(node)

            page_info = products_data.get('pageInfo', {})
            hasNextPage = page_info.get('hasNextPage', False)
            cursor = page_info.get('endCursor')

        except Exception as e:
            current_app.logger.error(f"Error fetching products for name sync: {e}")
            current_app.logger.error(f"Query: {query}")
            return None
    
    current_app.logger.info(f"Total products retrieved: {len(products)}")
    return products

def get_single_product_details_for_display(product_gid):
    """Pridobi podrobnosti za prikaz imena (vendor, fragrance)."""
    query = f"""
    {{
      node(id: "{product_gid}") {{
        ... on Product {{
          vendor
          product_fragrance: metafield(namespace: "custom", key: "product_fragrance_") {{
            value
          }}
        }}
      }}
    }}
    """
    try:
        response = requests.post(_get_api_url(), json={'query': query}, headers=_get_shopify_headers())
        response.raise_for_status()
        data = response.json()
        if 'errors' in data:
            raise Exception(f"GraphQL errors: {data['errors']}")
        
        node_data = data.get('data', {}).get('node', {})
        if not node_data:
            return None

        return {
            'vendor': node_data.get('vendor'),
            'product_fragrance': node_data.get('product_fragrance', {}).get('value') if node_data.get('product_fragrance') else None
        }
    except Exception as e:
        current_app.logger.error(f"Error fetching single product details for GID {product_gid}: {e}")
        return None

def get_product_tags(product_gid, shop_domain: str | None = None):
    """Pridobi tage za en sam izdelek."""
    query = f"""
    {{
      node(id: "{product_gid}") {{
        ... on Product {{
          tags
        }}
      }}
    }}
    """
    try:
        response = requests.post(_get_api_url(shop_domain=shop_domain), json={'query': query}, headers=_get_shopify_headers(shop_domain))
        response.raise_for_status()
        data = response.json()
        return data.get('data', {}).get('node', {}).get('tags', [])
    except Exception as e:
        current_app.logger.error(f"Error fetching tags for GID {product_gid}: {e}")
        return []

def find_shopify_product_gid(product_no, proizvajalec_id, shop_domain: str | None = None):
    """
    Finds a Shopify product GID by first searching for a unique metafield (product_no)
    and then verifying the second metafield (proizvajalec_id) on the result.
    This works around the Shopify query syntax limitation of not supporting AND between two metafields.
    """
    try:
        from database import get_db
        
        # Najprej pridobimo ime proizvajalca iz baze
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT ime FROM proizvajalci WHERE id = %s", (proizvajalec_id,))
        proizvajalec_result = cursor.fetchone()
        
        if not proizvajalec_result:
            return None, f"Proizvajalec z ID {proizvajalec_id} ni bil najden v bazi"
        
        expected_proizvajalec = proizvajalec_result['ime']
        
        # Step 1: Construct a query to find the product by the reliable 'product_no'
        # using the CORRECT syntax that was proven to work in diagnostics.
        query_string = f"metafield:custom.product_no:'{product_no}'"
        
        query = f"""
        {{
          products(first: 1, query: "{query_string}") {{
            edges {{
              node {{
                id
                proizvajalec_id_metafield: metafield(namespace: "custom", key: "proizvajalec_id") {{
                  value
                }}
              }}
            }}
          }}
        }}
        """
        
        response = requests.post(_get_api_url(shop_domain=shop_domain), json={'query': query}, headers=_get_shopify_headers(shop_domain))
        response.raise_for_status()
        data = response.json()

        if 'errors' in data and data['errors']:
            error_details = json.dumps(data['errors'])
            current_app.logger.error(f"GraphQL error during product search: {error_details}")
            return None, f"GraphQL napaka: {error_details}"

        edges = data.get('data', {}).get('products', {}).get('edges', [])
        if not edges:
            return None, f"Izdelek s stevilko '{product_no}' ni bil najden."

        # Step 2: We found a product. Now verify the manufacturer.
        product_node = edges[0]['node']
        product_gid = product_node['id']
        
        metafield_node = product_node.get('proizvajalec_id_metafield')
        actual_manufacturer = metafield_node.get('value') if metafield_node else None

        # Step 3: Compare the actual manufacturer with the expected one.
        if actual_manufacturer == expected_proizvajalec:
            return product_gid, "Product found and verified."
        else:
            error_msg = f"Izdelek s stevilko '{product_no}' je bil najden, a se proizvajalec ne ujema. Pričakovano: '{expected_proizvajalec}', Dejansko v Shopify: '{actual_manufacturer}'."
            current_app.logger.error(error_msg)
            return None, error_msg

    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"Network error finding Shopify product: {e}")
        return None, "Napaka v omrežju pri povezovanju s Shopify."
    except Exception as e:
        current_app.logger.error(f"Unexpected error in find_shopify_product_gid: {e}")
        traceback.print_exc()
        return None, "Nepričakovana napaka na strežniku."


def update_shopify_inci_metafield(product_gid, inci_string, shop_domain: str | None = None):
    """Posodobi INCI metafield za določen izdelek."""
    mutation = """
    mutation productUpdate($input: ProductInput!) {
      productUpdate(input: $input) {
        product { id }
        userErrors { field message }
      }
    }
    """
    variables = {
        "input": {
            "id": product_gid,
            "metafields": [{
                "namespace": "custom",
                "key": "sestavine_inci",
                "value": inci_string or "",
                "type": "multi_line_text_field"
            }]
        }
    }
    try:
        response = requests.post(_get_api_url(shop_domain=shop_domain), json={'query': mutation, 'variables': variables}, headers=_get_shopify_headers(shop_domain))
        response.raise_for_status()
        data = response.json()
        if data.get('data', {}).get('productUpdate', {}).get('userErrors', []):
            errors = data['data']['productUpdate']['userErrors']
            return False, ", ".join([e['message'] for e in errors])
        return True, "Uspešno posodobljeno."
    except Exception as e:
        current_app.logger.error(f"Error updating INCI metafield: {e}")
        return False, str(e)

def update_stock_status_in_shopify(product_gid, is_in_stock, shop_domain: str | None = None):
    """Posodobi tage (GREEN/RED) in metafield 'data.status' glede na zalogo."""
    try:
        current_tags = set(get_product_tags(product_gid, shop_domain=shop_domain))

        if is_in_stock:
            current_tags.add("GREEN")
            current_tags.discard("RED")
            metafield_value = "Na zalogi"
        else:
            current_tags.add("RED")
            current_tags.discard("GREEN")
            metafield_value = "Ni na zalogi"

        mutation = """
        mutation productUpdate($input: ProductInput!) {
          productUpdate(input: $input) {
            product { id tags }
            userErrors { field message }
          }
        }
        """
        variables = {
            "input": {
                "id": product_gid,
                "tags": list(current_tags),
                "metafields": [{
                    "namespace": "data",
                    "key": "status",
                    "value": metafield_value,
                    "type": "single_line_text_field"
                }]
            }
        }
        
        response = requests.post(_get_api_url(shop_domain=shop_domain), json={'query': mutation, 'variables': variables}, headers=_get_shopify_headers(shop_domain))
        response.raise_for_status()
        data = response.json()

        if data.get('data', {}).get('productUpdate', {}).get('userErrors', []):
            errors = data['data']['productUpdate']['userErrors']
            return False, ", ".join([e['message'] for e in errors])
        
        return True, "Status zaloge uspešno posodobljen v Shopify (tags in metafield)."

    except Exception as e:
        current_app.logger.error(f"Error updating stock status in Shopify: {e}")
        traceback.print_exc()
        return False, str(e)

def _update_data_status_metafield(product_gid, new_status, shop_domain: str | None = None):
    """Helper funkcija za posodobitev samo 'data.status' metapolja."""
    mutation = """
    mutation productUpdate($input: ProductInput!) {
      productUpdate(input: $input) {
        product { id }
        userErrors { field message }
      }
    }
    """
    variables = {
        "input": {
            "id": product_gid,
            "metafields": [{
                "namespace": "data",
                "key": "status",
                "value": new_status,
                "type": "single_line_text_field"
            }]
        }
    }
    try:
        # Povečamo timeout za posamezen klic, da smo bolj robustni
        response = requests.post(_get_api_url(shop_domain=shop_domain), json={'query': mutation, 'variables': variables}, headers=_get_shopify_headers(shop_domain), timeout=20)
        response.raise_for_status()
        data = response.json()
        if data.get('data', {}).get('productUpdate', {}).get('userErrors', []):
            errors = data['data']['productUpdate']['userErrors']
            current_app.logger.error(f"Error updating data.status for {product_gid}: {errors}")
            return False
        return True
    except Exception as e:
        current_app.logger.error(f"Exception updating data.status for {product_gid}: {e}")
        return False

def sync_all_stock_metafields(shop_domain: str | None = None):
    """
    Pregleda vse izdelke in popravi neskladja med tagi (GREEN/RED)
    in metapoljem 'data.status'.
    """
    checked_count = 0
    fixed_count = 0
    error_count = 0
    hasNextPage = True
    cursor = None

    current_app.logger.info("Starting full data.status metafield audit...")

    while hasNextPage:
        after_cursor = f', after: "{cursor}"' if cursor else ""
        query = f"""
        {{
          products(first: 100{after_cursor}) {{
            pageInfo {{
              hasNextPage
              endCursor
            }}
            edges {{
              node {{
                id
                tags
                data_status: metafield(namespace: "data", key: "status") {{
                  value
                }}
              }}
            }}
          }}
        }}
        """
        try:
            # Povečamo timeout za pridobivanje strani, da smo bolj robustni
            response = requests.post(_get_api_url(shop_domain=shop_domain), json={'query': query}, headers=_get_shopify_headers(shop_domain), timeout=30)
            response.raise_for_status()
            data = response.json().get('data', {}).get('products', {})
            
            if not data.get('edges'):
                current_app.logger.warning("Received empty edges from Shopify, stopping sync.")
                break

            for edge in data.get('edges', []):
                checked_count += 1
                node = edge['node']
                product_gid = node['id']
                tags = node.get('tags', [])
                
                actual_status_node = node.get('data_status')
                actual_status = actual_status_node.get('value') if actual_status_node else None
                
                expected_status = None
                if "GREEN" in tags:
                    expected_status = "Na zalogi"
                elif "RED" in tags:
                    expected_status = "Ni na zalogi"
                
                # Popravi samo, če je pričakovan status definiran in se ne ujema z dejanskim
                if expected_status and actual_status != expected_status:
                    current_app.logger.warning(f"Fixing mismatch for {product_gid}. Tags: {tags}, Actual: '{actual_status}', Expected: '{expected_status}'")
                    if _update_data_status_metafield(product_gid, expected_status, shop_domain=shop_domain):
                        fixed_count += 1
                    else:
                        error_count += 1
                    # Odstranimo pavzo, da pospešimo proces v ozadju
                    # time.sleep(0.5)

            hasNextPage = data.get('pageInfo', {}).get('hasNextPage', False)
            cursor = data.get('pageInfo', {}).get('endCursor')
            current_app.logger.info(f"Processed page, total checked: {checked_count}, fixed: {fixed_count}, errors: {error_count}")

        except Exception as e:
            error_message = f"Error during data.status sync batch: {e}"
            current_app.logger.error(error_message)
            traceback.print_exc()
            # V primeru napake prekinemo, da se izognemo zanki
            hasNextPage = False

    success_message = f"Sinhronizacija končana. Pregledanih {checked_count} izdelkov, popravljenih {fixed_count} neskladij, napak: {error_count}."
    current_app.logger.info(success_message)
    return checked_count, fixed_count, success_message

def get_inci_from_shopify(product_no, proizvajalec_id, shop_domain: str | None = None):
    """
    Pridobi INCI podatke iz Shopify metafield-a za določen parfum.
    Vrne (success, inci_string, error_message)
    """
    try:
        # Najprej poiščemo Shopify product GID
        product_gid, message = find_shopify_product_gid(product_no, proizvajalec_id, shop_domain=shop_domain)
        if not product_gid:
            return False, None, f"Ni bilo mogoče najti izdelka v Shopify: {message}"
        
        # Pridobimo INCI metafield - poskusimo različne možnosti
        query = f"""
        {{
          node(id: "{product_gid}") {{
            ... on Product {{
              sestavine_inci: metafield(namespace: "custom", key: "sestavine_inci") {{
                value
              }}
              sestava_po_inci: metafield(namespace: "my_fields", key: "sestava_po_inci") {{
                value
              }}
            }}
          }}
        }}
        """
        
        response = requests.post(_get_api_url(shop_domain=shop_domain), json={'query': query}, headers=_get_shopify_headers(shop_domain))
        response.raise_for_status()
        data = response.json()
        
        if 'errors' in data:
            return False, None, f"GraphQL napaka: {data['errors']}"
        
        node_data = data.get('data', {}).get('node', {})
        if not node_data:
            return False, None, "Izdelek ni bil najden v Shopify"
        
        # Poskusimo najprej my_fields.sestava_po_inci, nato custom.sestavine_inci
        inci_value = None
        
        # 1. Poskusimo my_fields.sestava_po_inci
        sestava_po_inci_metafield = node_data.get('sestava_po_inci', {})
        if sestava_po_inci_metafield and sestava_po_inci_metafield.get('value'):
            inci_value = sestava_po_inci_metafield.get('value')
            current_app.logger.info(f"INCI najden v my_fields.sestava_po_inci za product_no {product_no}")
        
        # 2. Če ni najden, poskusimo custom.sestavine_inci
        if not inci_value:
            sestavine_inci_metafield = node_data.get('sestavine_inci', {})
            if sestavine_inci_metafield and sestavine_inci_metafield.get('value'):
                inci_value = sestavine_inci_metafield.get('value')
                current_app.logger.info(f"INCI najden v custom.sestavine_inci za product_no {product_no}")
        
        if not inci_value or inci_value.strip() == '':
            return False, None, "INCI podatki v Shopify so prazni ali ne obstajajo"
        
        return True, inci_value.strip(), None
        
    except Exception as e:
        current_app.logger.error(f"Napaka pri pridobivanju INCI iz Shopify: {e}")
        return False, None, str(e)

def update_inci_in_database(product_no, proizvajalec_id, inci_string):
    """
    Posodobi INCI podatke v bazi za določen parfum.
    Vrne (success, message)
    """
    try:
        from database import get_db
        
        db = get_db()
        cursor = db.cursor()
        
        # Posodobimo INCI v parfumi tabeli
        cursor.execute("""
            UPDATE parfumi 
            SET sestava_inci = %s, updated_at = CURRENT_TIMESTAMP
            WHERE product_no = %s AND proizvajalec_id = %s
        """, (inci_string, product_no, proizvajalec_id))
        
        if cursor.rowcount == 0:
            return False, f"Parfum z product_no={product_no} in proizvajalec_id={proizvajalec_id} ni bil najden"
        
        db.commit()
        return True, f"INCI uspešno posodobljen za parfum {product_no}"
        
    except Exception as e:
        current_app.logger.error(f"Napaka pri posodabljanju INCI v bazi: {e}")
        return False, str(e)

def sync_inci_from_shopify(product_no, proizvajalec_id):
    """
    Sinhronizira INCI podatke iz Shopify-ja v bazo.
    Vrne (success, message)
    """
    try:
        # 1. Pridobi INCI iz Shopify-ja
        success, inci_value, error = get_inci_from_shopify(product_no, proizvajalec_id)
        if not success:
            return False, f"Napaka pri pridobivanju INCI iz Shopify: {error}"
        
        # 2. Posodobi bazo
        success, message = update_inci_in_database(product_no, proizvajalec_id, inci_value)
        if not success:
            return False, f"Napaka pri posodabljanju baze: {message}"
        
        return True, f"INCI uspešno sinhroniziran iz Shopify: {inci_value[:50]}..."
        
    except Exception as e:
        current_app.logger.error(f"Napaka pri sinhronizaciji INCI: {e}")
        return False, str(e)

def get_orders_fulfillment_status(shopify_order_id, shop_domain: str | None = None):
    """Preveri, ali je naročilo fulfilled v Shopify-ju."""
    try:
        current_app.logger.info(f"Preverjam fulfilled status za naročilo {shopify_order_id}")
        
        # Uporabi REST API za preverjanje fulfillment statusa
        url = f"{_get_api_url('orders', shop_domain=shop_domain)}/{shopify_order_id}.json"
        current_app.logger.info(f"Kličem Shopify API: {url}")
        
        response = _shopify_get_with_retry(url, timeout=15, shop_domain=shop_domain)
        response.raise_for_status()
        
        order_data = response.json()
        order = order_data.get('order', {})
        
        current_app.logger.info(f"Shopify odgovor za naročilo {shopify_order_id}: fulfillments={len(order.get('fulfillments', []))}, fulfillment_status={order.get('fulfillment_status')}")
        
        # Preveri, ali ima naročilo fulfillment-e
        fulfillments = order.get('fulfillments', [])
        
        if fulfillments:
            # Če ima fulfillment-e, je fulfilled
            current_app.logger.info(f"Naročilo {shopify_order_id} je fulfilled (ima {len(fulfillments)} fulfillment-ov)")
            return True
        else:
            # Preveri tudi fulfillment_status
            fulfillment_status = order.get('fulfillment_status')
            is_fulfilled = fulfillment_status == 'fulfilled'
            current_app.logger.info(f"Naročilo {shopify_order_id} fulfillment_status={fulfillment_status}, is_fulfilled={is_fulfilled}")
            return is_fulfilled
            
    except Exception as e:
        current_app.logger.error(f"Error checking fulfillment status for order {shopify_order_id}: {e}")
        return False

def get_order_fulfillment_details(shopify_order_id, shop_domain: str | None = None):
    """Pridobi podrobnosti o fulfillment-u naročila iz Shopify-ja."""
    try:
        current_app.logger.info(f"Pridobivam fulfillment podrobnosti za naročilo {shopify_order_id}")
        
        # Uporabi REST API za pridobivanje fulfillment podrobnosti
        url = f"{_get_api_url('orders', shop_domain=shop_domain)}/{shopify_order_id}/fulfillments.json"
        current_app.logger.info(f"Kličem Shopify fulfillment API: {url}")
        
        response = _shopify_get_with_retry(url, timeout=15, shop_domain=shop_domain)
        response.raise_for_status()
        
        fulfillment_data = response.json()
        fulfillments = fulfillment_data.get('fulfillments', [])
        
        current_app.logger.info(f"Shopify fulfillment odgovor za naročilo {shopify_order_id}: {len(fulfillments)} fulfillment-ov")
        
        if fulfillments:
            # Vrni podrobnosti prvega fulfillment-a
            fulfillment = fulfillments[0]
            current_app.logger.info(f"Fulfillment podrobnosti za naročilo {shopify_order_id}: created_at={fulfillment.get('created_at')}, id={fulfillment.get('id')}")
            return fulfillment
        else:
            current_app.logger.info(f"Ni fulfillment-ov za naročilo {shopify_order_id}")
            return None
            
    except Exception as e:
        current_app.logger.error(f"Error getting fulfillment details for order {shopify_order_id}: {e}")
        return None


def get_shopify_order_data(shopify_order_id: str | int, shop_domain: str | None = None):
    """Vrne osnovne podatke o Shopify naročilu (email, order_status_url, shipping_address, line_items).

    To je kompatibilen nadomestek za klic v background_service.
    """
    try:
        url = f"{_get_api_url('orders', shop_domain=shop_domain)}/{shopify_order_id}.json"
        resp = _shopify_get_with_retry(url, timeout=20, shop_domain=shop_domain)
        resp.raise_for_status()
        data = resp.json().get('order', {})
        # Normaliziraj minimalen nabor polj, ki jih pričakuje background_service
        return {
            'email': data.get('email'),
            'order_status_url': data.get('order_status_url'),
            'shipping_address': {
                'country_code': (data.get('shipping_address') or {}).get('country_code')
            },
            'line_items': [
                {
                    'title': li.get('title'),
                    'quantity': li.get('quantity'),
                    'price': li.get('price'),
                    'sku': li.get('sku')
                } for li in (data.get('line_items') or [])
            ]
        }
    except Exception as e:
        current_app.logger.error(f"Error fetching Shopify order data for {shopify_order_id}: {e}")
        return None

def register_webhooks(shop_domain: str | None = None):
    """Registrira potrebne webhook-e v Shopify-ju."""
    try:
        current_app.logger.info("Registriram webhook-e v Shopify-ju...")
        
        # URL-ji za webhook-e
        base_url = current_app.config.get('WEBHOOK_BASE_URL', 'https://deklaracije.eu')
        
        # Seznam webhook-ov, ki jih želimo registrirati.
        #
        # POMEMBNO za multi-store setup:
        # - `orders/partially_fulfilled` je KLJUČEN za trgovine, kjer
        #   naročila vsebujejo non-shippable line item (npr. CODFEE,
        #   plačilo po povzetju). Ta naročila Shopify označi kot
        #   "Partially fulfilled" in NE pošlje `orders/fulfilled`.
        # - `fulfillments/create` / `fulfillments/update` so noviše
        #   Shopify topica — nekatere trgovine jih še ne podpirajo
        #   (vrnejo 422 "Invalid topic"). V tem primeru gracefully
        #   ignoriramo error in nadaljujemo z ostalimi.
        webhooks_to_register = [
            {
                'topic': 'orders/create',
                'address': f"{base_url}/webhook/order-created",
                'format': 'json'
            },
            {
                'topic': 'orders/fulfilled',
                'address': f"{base_url}/webhook/order-fulfilled",
                'format': 'json'
            },
            {
                'topic': 'orders/partially_fulfilled',
                'address': f"{base_url}/webhook/order-fulfilled",
                'format': 'json'
            },
            {
                'topic': 'fulfillments/create',
                'address': f"{base_url}/webhook/order-fulfilled",
                'format': 'json'
            },
            {
                'topic': 'fulfillments/update',
                'address': f"{base_url}/webhook/order-fulfilled",
                'format': 'json'
            },
            {
                'topic': 'products/update',
                'address': f"{base_url}/webhook/product-update",
                'format': 'json'
            }
        ]
        
        # Najprej pridobi obstoječe webhook-e
        url = f"{_get_api_url('webhooks', shop_domain=shop_domain)}.json"
        response = _shopify_get_with_retry(url, timeout=15, shop_domain=shop_domain)
        response.raise_for_status()
        
        existing_webhooks = response.json().get('webhooks', [])
        current_app.logger.info(f"Našel {len(existing_webhooks)} obstoječih webhook-ov")
        
        # Preveri, katere webhook-e že imamo
        existing_topics = {webhook['topic'] for webhook in existing_webhooks}
        
        for webhook_data in webhooks_to_register:
            topic = webhook_data['topic']
            
            if topic in existing_topics:
                current_app.logger.info(f"Webhook za {topic} že obstaja")
                continue
            
            # Registriraj nov webhook
            current_app.logger.info(f"Registriram webhook za {topic}...")
            
            response = requests.post(
                f"{_get_api_url('webhooks', shop_domain=shop_domain)}.json",
                headers=_get_shopify_headers(shop_domain),
                json={'webhook': webhook_data}
            )
            
            if response.status_code == 201:
                webhook_info = response.json().get('webhook', {})
                current_app.logger.info(f"Webhook za {topic} uspešno registriran (ID: {webhook_info.get('id')})")
            else:
                current_app.logger.error(f"Napaka pri registraciji webhook-a za {topic}: {response.status_code} - {response.text}")
        
        current_app.logger.info("Registracija webhook-ov končana")
        return True
        
    except Exception as e:
        current_app.logger.error(f"Napaka pri registraciji webhook-ov: {e}")
        return False

def list_webhooks(shop_domain: str | None = None):
    """Pridobi seznam vseh webhook-ov iz Shopify-ja."""
    try:
        url = f"{_get_api_url('webhooks', shop_domain=shop_domain)}.json"
        response = _shopify_get_with_retry(url, timeout=15, shop_domain=shop_domain)
        response.raise_for_status()
        
        webhooks = response.json().get('webhooks', [])
        current_app.logger.info(f"Našel {len(webhooks)} webhook-ov v Shopify-ju:")
        
        for webhook in webhooks:
            current_app.logger.info(f"  - {webhook['topic']}: {webhook['address']} (ID: {webhook['id']})")
        
        return webhooks
        
    except Exception as e:
        current_app.logger.error(f"Napaka pri pridobivanju webhook-ov: {e}")
        return []