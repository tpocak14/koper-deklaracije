import os
import time
from collections import OrderedDict
import json
import requests
import hashlib
import time as _time
from datetime import datetime, timedelta
from flask import (
    Blueprint, render_template, session, redirect, url_for, 
    send_from_directory, current_app, request, Response, make_response
)
from database import get_db
from services.pdf_service import ustvari_pdf
from services.search_service import normalize_query, find_synonym
from services.shopify_service import _get_api_url, _get_shopify_headers, _normalize_shop_domain, get_shopify_store_config

main_bp = Blueprint('main', __name__)


def _resolve_shop_domain_from_request():
    shop = request.headers.get('X-Shopify-Shop-Domain')
    if shop:
        return shop
    shop = request.args.get('shop') or request.args.get('shop_domain')
    if shop:
        return shop
    return None


_INSPIRED_URL_CACHE = {}
_INSPIRED_BLOB_CACHE = OrderedDict()
_INSPIRED_BLOB_TTL_S = 24 * 60 * 60
_INSPIRED_BLOB_MAX_ITEMS = 200
_INSPIRED_URL_TTL_S = 6 * 60 * 60
_INSPIRED_URL_NEGATIVE_TTL_S = 5 * 60


def _cache_get_inspired_url(cache_key: str) -> str | None:
    now = _time.time()
    entry = _INSPIRED_URL_CACHE.get(cache_key)
    if not entry:
        return None
    expires_at, url = entry
    if expires_at < now:
        _INSPIRED_URL_CACHE.pop(cache_key, None)
        return None
    return url


def _cache_set_inspired_url(cache_key: str, url: str | None) -> None:
    ttl = _INSPIRED_URL_TTL_S if url else _INSPIRED_URL_NEGATIVE_TTL_S
    _INSPIRED_URL_CACHE[cache_key] = (_time.time() + ttl, url)


def _cache_get_inspired_blob(cache_key: str):
    entry = _INSPIRED_BLOB_CACHE.get(cache_key)
    if not entry:
        return None
    if (_time.time() - entry["ts"]) > _INSPIRED_BLOB_TTL_S:
        _INSPIRED_BLOB_CACHE.pop(cache_key, None)
        return None
    _INSPIRED_BLOB_CACHE.move_to_end(cache_key)
    return entry


def _cache_set_inspired_blob(cache_key: str, content: bytes, content_type: str, etag: str) -> None:
    _INSPIRED_BLOB_CACHE[cache_key] = {
        "content": content,
        "content_type": content_type,
        "etag": etag,
        "ts": _time.time(),
    }
    _INSPIRED_BLOB_CACHE.move_to_end(cache_key)
    while len(_INSPIRED_BLOB_CACHE) > _INSPIRED_BLOB_MAX_ITEMS:
        _INSPIRED_BLOB_CACHE.popitem(last=False)


def _alias_shop_domain(shop_domain: str | None) -> str | None:
    sd = _normalize_shop_domain(shop_domain)
    if not sd:
        return None
    if sd == "kxugn4-mu.myshopify.com":
        return "amour-parfums-2.myshopify.com"
    if sd == "amour-parfums-2.myshopify.com":
        return "kxugn4-mu.myshopify.com"
    return None

@main_bp.route('/')
def index():
    # Shopify app install/launch flow (OAuth)
    if request.args.get('shop') and request.args.get('hmac'):
        return redirect(url_for('auth.shopify_install', **request.args))

    # Preveri Flask session
    if 'logged_in' not in session:
        return redirect(url_for('auth.login'))
    
    # Dodaj timestamp za force refresh JavaScript
    timestamp = int(time.time())
    current_app.logger.info(f"Rendering index.html with timestamp: {timestamp}")
    response = make_response(render_template('index.html', timestamp=timestamp))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@main_bp.route('/mockup/procurement')
def mockup_procurement():
    """Statični mockup novega dizajna Naročila robe.
    Dostopen brez prijave – samo za pregled in potrditev smeri preden se loti
    redesign produkcijskih predlog. Vrne predogled v ločeni datoteki, da
    obstoječi /index.html ostane nedotaknjen.
    """
    response = make_response(render_template('mockup_procurement.html'))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return response


@main_bp.route('/favicon.ico')
def favicon():
    """Postreže favicon.ico iz mape static."""
    return send_from_directory(os.path.join(current_app.root_path, 'static'),
                               'favicon.ico', mimetype='image/vnd.microsoft.icon')

@main_bp.route('/sw.js')
def service_worker():
    """Postreže datoteko service workerja."""
    return send_from_directory(os.path.join(current_app.root_path, 'static'), 'sw.js')

@main_bp.route('/manifest.json')
def manifest():
    """Postreže manifest.json."""
    return send_from_directory(os.path.join(current_app.root_path, 'static'), 'manifest.json')


@main_bp.route('/apps/deklaracije/search')
def search_rewrite():
    q = (request.args.get('q') or '').strip()
    if not q:
        return redirect('/search')

    shop_domain = _resolve_shop_domain_from_request()
    if not shop_domain:
        return redirect(f"/search?q={q}")

    norm = normalize_query(q)
    if not norm:
        return redirect('/search')

    code = find_synonym(shop_domain, norm)
    if code:
        return redirect(f"/search?q=mf_inspo:{code.lower()}")
    return redirect(f"/search?q={q}")


def _fetch_inspired_image_url(shop_domain: str, product_id: str) -> str | None:
    deadline = time.monotonic() + 6.0

    def _time_left() -> float:
        return max(0.5, deadline - time.monotonic())

    cache_key = f"{shop_domain}:{product_id}"
    cached = _cache_get_inspired_url(cache_key)
    if cached is not None:
        return cached

    gid = f"gid://shopify/Product/{product_id}"
    query = """
    query ($id: ID!) {
      product(id: $id) {
        inspired_by: metafield(namespace: "custom", key: "inspired_by") {
          type
          value
          reference {
            ... on MediaImage {
              image { url }
            }
            ... on GenericFile {
              url
            }
          }
        }
      }
    }
    """
    def _fetch_node_url(sd: str, file_gid: str) -> str | None:
        node_query = """
        query ($id: ID!) {
          node(id: $id) {
            ... on MediaImage {
              image { url }
            }
            ... on GenericFile {
              url
            }
          }
        }
        """
        if _time_left() <= 0.5:
            raise RuntimeError("deadline exceeded (node query)")
        resp = requests.post(
            _get_api_url(shop_domain=sd),
            headers=_get_shopify_headers(sd),
            json={"query": node_query, "variables": {"id": file_gid}},
            timeout=min(4, _time_left()),
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("errors"):
            raise RuntimeError(f"GraphQL errors: {data['errors']}")
        node = (data.get("data") or {}).get("node") or {}
        if node.get("image") and node["image"].get("url"):
            return node["image"]["url"]
        if node.get("url"):
            return node["url"]
        return None

    def _query(sd: str) -> str | None:
        if _time_left() <= 0.5:
            raise RuntimeError("deadline exceeded (product query)")
        resp = requests.post(
            _get_api_url(shop_domain=sd),
            headers=_get_shopify_headers(sd),
            json={"query": query, "variables": {"id": gid}},
            timeout=min(4, _time_left()),
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("errors"):
            raise RuntimeError(f"GraphQL errors: {data['errors']}")
        product = (data.get("data") or {}).get("product") or {}
        inspired_field = product.get("inspired_by") or {}
        inspired_ref = inspired_field.get("reference") or {}
        if inspired_ref.get("image") and inspired_ref["image"].get("url"):
            return inspired_ref["image"]["url"]
        if inspired_ref.get("url"):
            return inspired_ref["url"]
        value = (inspired_field.get("value") or "").strip()
        if value.startswith("http://") or value.startswith("https://"):
            _cache_set_inspired_url(cache_key, value)
            return value
        if value.startswith("gid://"):
            url = _fetch_node_url(sd, value)
            _cache_set_inspired_url(cache_key, url)
            return url
        return None

    sd = _normalize_shop_domain(shop_domain) or shop_domain
    if sd:
        try:
            url = _query(sd)
            _cache_set_inspired_url(cache_key, url)
            return url
        except Exception as e:
            current_app.logger.warning(f"inspired_by query failed for {sd}: {e}")

    alias = _alias_shop_domain(sd or shop_domain)
    if alias and alias != sd and _time_left() > 0.5:
        try:
            url = _query(alias)
            _cache_set_inspired_url(cache_key, url)
            return url
        except Exception as e:
            current_app.logger.warning(f"inspired_by query failed for alias {alias}: {e}")
    _cache_set_inspired_url(cache_key, None)
    return None


@main_bp.route('/apps/deklaracije/inspired-image')
def inspired_image_proxy():
    product_id = (request.args.get('product_id') or '').strip()
    shop_domain = _resolve_shop_domain_from_request()
    width = (request.args.get('width') or '').strip()
    if not product_id or not shop_domain:
        return Response("Missing product_id or shop", status=400)
    try:
        url = _fetch_inspired_image_url(shop_domain, product_id)
        if not url:
            return Response("Not found", status=404)
        if width.isdigit():
            sep = '&' if '?' in url else '?'
            url = f"{url}{sep}width={width}"
        cache_key = url
        cached_blob = _cache_get_inspired_blob(cache_key)
        if cached_blob:
            if request.headers.get('If-None-Match') == cached_blob["etag"]:
                return Response(status=304)
            return Response(
                cached_blob["content"],
                headers={
                    'Content-Type': cached_blob["content_type"],
                    'Cache-Control': 'public, max-age=86400',
                    'ETag': cached_blob["etag"],
                    'X-Robots-Tag': 'noindex, nofollow, noimageindex',
                }
            )
        img_resp = requests.get(url, timeout=(3, 7))
        if img_resp.status_code != 200:
            return Response("Upstream error", status=502)
        content = img_resp.content
        etag = hashlib.md5(content).hexdigest()
        _cache_set_inspired_blob(
            cache_key,
            content,
            img_resp.headers.get('Content-Type', 'image/jpeg'),
            etag,
        )
        if request.headers.get('If-None-Match') == etag:
            return Response(status=304)
        headers = {
            'Content-Type': img_resp.headers.get('Content-Type', 'image/jpeg'),
            'Cache-Control': 'public, max-age=86400',
            'ETag': etag,
            'X-Robots-Tag': 'noindex, nofollow, noimageindex',
        }
        return Response(content, headers=headers)
    except Exception as e:
        current_app.logger.error(f"inspired_image_proxy error: {e}")
        return Response("Error", status=500)

@main_bp.route('/prenesi_pdf')
def prenesi_pdf():
    """Omogoči prenos generiranega PDF-ja."""
    if 'logged_in' not in session:
        return redirect(url_for('auth.login'))
    
    filename = request.args.get('filename')
    if not filename:
        return "Manjka ime datoteke.", 400
    
    # Varnostni preverbi, da se prepreči dostop do nezaželenih datotek
    if '..' in filename or filename.startswith('/'):
        return "Neveljavno ime datoteke.", 400

    pdf_dir = os.path.join(current_app.root_path, 'pdf')
    
    try:
        return send_from_directory(directory=pdf_dir, path=filename, as_attachment=False)
    except FileNotFoundError:
        return "Datoteka ni najdena.", 404

@main_bp.route('/generiraj_pdf/<order_number>')
def generiraj_pdf(order_number):
    """Dinamično generira PDF iz podatkov iz baze declarations."""
    if 'logged_in' not in session:
        return redirect(url_for('auth.login'))
    
    # Dodaj # prefix, če ga ni
    if not order_number.startswith('#'):
        order_number_with_hash = f"#{order_number}"
    else:
        order_number_with_hash = order_number
    
    db = get_db()
    cursor = db.cursor()
    
    try:
        # Pridobi podatke naročila
        cursor.execute("SELECT * FROM orders WHERE order_number = %s", (order_number_with_hash,))
        order = cursor.fetchone()
        if not order:
            return "Naročilo ni najdeno.", 404
        
        # Pridobi podatke deklaracije iz baze - uporabi podatke, ki so bili shranjeni ob prvotnem pošiljanju
        cursor.execute("""
            SELECT product_no, proizvajalec_ime, sestava_inci, rok_uporabe, serijska_stevilka, quantity
            FROM declarations 
            WHERE order_number = %s 
            ORDER BY created_at
        """, (order_number_with_hash,))
        declaration_data = cursor.fetchall()
        
        if not declaration_data:
            return "Podatki deklaracije niso najdeni.", 404
        
        # Pretvorimo podatke v format, ki ga pričakuje PDF servis
        declaration_items = []
        for item in declaration_data:
            # rok_uporabe je že shranjen kot string v bazi, zato ga ne pretvarjamo
            declaration_items.append({
                'title': f"{item['product_no']} - {item['proizvajalec_ime']}",
                'product_no': item['product_no'],
                'proizvajalec_ime': item['proizvajalec_ime'],
                'sestava_inci': item['sestava_inci'],
                'rok_uporabe': item['rok_uporabe'] if item['rok_uporabe'] else None,
                'serijska_stevilka': item['serijska_stevilka'] or 'N/A',
                'quantity': item.get('quantity', 1)
            })
        
        # Pripravimo email_line_items iz order podatkov
        line_items_raw = order.get('line_items', '[]')
        line_items = json.loads(line_items_raw) if isinstance(line_items_raw, str) else (line_items_raw or [])
        
        email_line_items = []
        for item in line_items:
            if not item: continue
            try:
                price = float(item.get('price', 0.0))
            except (ValueError, TypeError):
                price = 0.0

            email_line_items.append({
                'title': item.get('title', 'N/A'),
                'quantity': item.get('quantity', 1),
                'price': price,
                'image_url': 'https://cdn.shopify.com/s/files/1/0533/2089/files/placeholder-images-image_large.png?v=1529089297'
            })
        
        # Preveri rok uporabe (blokada < 60 dni)
        expiration_warnings = []
        today = datetime.utcnow().date()
        warn_date = today + timedelta(days=60)
        for item in declaration_data:
            rok = item.get('rok_uporabe')
            if isinstance(rok, str):
                try:
                    rok = datetime.strptime(rok, '%d.%m.%Y').date()
                except Exception:
                    rok = None
            if isinstance(rok, datetime):
                rok = rok.date()
            if rok and rok < warn_date:
                expiration_warnings.append(
                    f"{item.get('product_no', 'N/A')}: Rok uporabe ({rok.strftime('%d.%m.%Y')}) poteče v manj kot 60 dneh."
                )

        # Generiraj PDF
        pdf_path, pdf_msg = ustvari_pdf(
            declaration_items,
            email_line_items,
            order['country_code'],
            order_number_with_hash,
            expiration_warnings
        )
        
        if not pdf_path:
            return f"Napaka pri generiranju PDF-ja: {pdf_msg}", 500
        
        # Preberi generirani PDF in ga pošlji kot response
        try:
            with open(pdf_path, 'rb') as pdf_file:
                pdf_content = pdf_file.read()
            
            # Pošlji PDF kot response
            response = Response(pdf_content, mimetype='application/pdf')
            response.headers['Content-Disposition'] = f'inline; filename="{order_number_with_hash.replace("#", "")}.pdf"'
            return response
            
        except FileNotFoundError:
            return "PDF datoteka ni bila uspešno generirana.", 500
        finally:
            # Počisti začasno datoteko
            try:
                if os.path.exists(pdf_path):
                    os.remove(pdf_path)
            except:
                pass
                
    except Exception as e:
        current_app.logger.error(f"Napaka pri generiranju PDF-ja: {e}")
        return f"Prišlo je do napake pri generiranju PDF-ja: {str(e)}", 500
    finally:
        cursor.close()