from flask import Blueprint, request, jsonify, session, current_app, render_template, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash
from database import get_db
import json
import hashlib
import hmac
import uuid
import requests

auth_bp = Blueprint('auth', __name__)


def _normalize_shop_domain(shop_domain: str | None) -> str | None:
    if not shop_domain:
        return None
    sd = shop_domain.strip()
    if sd.startswith("https://"):
        sd = sd.replace("https://", "", 1)
    if sd.startswith("http://"):
        sd = sd.replace("http://", "", 1)
    if not sd.endswith(".myshopify.com"):
        sd = f"{sd}.myshopify.com"
    return sd


def _verify_shopify_hmac(params, secret: str) -> bool:
    """Verify Shopify HMAC for OAuth install/callback."""
    if not secret:
        return False
    provided = params.get('hmac')
    if not provided:
        return False
    message_parts = []
    # params is MultiDict; iterate sorted keys
    for key in sorted(params.keys()):
        if key in ('hmac', 'signature'):
            continue
        value = params.get(key)
        if value is None:
            continue
        message_parts.append(f"{key}={value}")
    message = "&".join(message_parts)
    digest = hmac.new(secret.encode('utf-8'), message.encode('utf-8'), hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, provided)

def has_permission(permission):
    """Preveri, ali ima trenutni uporabnik določeno dovoljenje."""
    if 'user_id' not in session:
        return False
    
    db = get_db()
    cursor = db.cursor()
    
    try:
        cursor.execute("""
            SELECT role, permissions 
            FROM users 
            WHERE id = %s AND is_active = TRUE
        """, (session['user_id'],))
        
        user_data = cursor.fetchone()
        if not user_data:
            return False

        role = user_data.get('role') if isinstance(user_data, dict) else user_data[0]
        raw_permissions = user_data.get('permissions') if isinstance(user_data, dict) else user_data[1]

        # Admin ima vsa dovoljenja (normaliziraj zapis vloge/uporabnika)
        normalized_role = str(role).strip().lower() if role is not None else ''
        normalized_username = str(session.get('username', '')).strip().lower()
        if normalized_role == 'admin' or normalized_username == 'admin':
            return True

        # Parsiraj permissions (podpira JSONB kot list ali JSON string)
        user_permissions = []
        if isinstance(raw_permissions, list):
            user_permissions = raw_permissions
        elif isinstance(raw_permissions, str) and raw_permissions.strip():
            try:
                user_permissions = json.loads(raw_permissions)
            except (json.JSONDecodeError, TypeError):
                user_permissions = []

        # Preveri specifično dovoljenje
        if permission in user_permissions:
            return True
        
        return False
        
    except Exception as e:
        current_app.logger.error(f"Napaka pri preverjanju dovoljenja: {e}")
        return False
    finally:
        cursor.close()

def require_permission(permission):
    """Decorator za zahtevanje določenega dovoljenja."""
    def decorator(f):
        def decorated_function(*args, **kwargs):
            if not has_permission(permission):
                return jsonify({"error": "Nimate dovoljenja za to akcijo"}), 403
            return f(*args, **kwargs)
        decorated_function.__name__ = f.__name__
        return decorated_function
    return decorator

@auth_bp.route('/login', methods=['POST'])
def login():
    """Prijava uporabnika."""
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    
    if not username or not password:
        return jsonify({"error": "Uporabniško ime in geslo sta obvezna"}), 400
    
    db = get_db()
    cursor = db.cursor()
    
    try:
        cursor.execute("""
            SELECT id, username, first_name, last_name, email, role, permissions, password_hash
            FROM users 
            WHERE username = %s AND is_active = TRUE
        """, (username,))
        
        user = cursor.fetchone()
        
        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            session['permissions'] = user['permissions']
            
            return jsonify({
                "message": "Uspešna prijava",
                "user": {
                    "id": user['id'],
                    "username": user['username'],
                    "first_name": user['first_name'],
                    "last_name": user['last_name'],
                    "email": user['email'],
                    "role": user['role'],
                    "permissions": user['permissions']
                }
            })
        else:
            return jsonify({"error": "Napačno uporabniško ime ali geslo"}), 401
            
    except Exception as e:
        current_app.logger.error(f"Napaka pri prijavi: {e}")
        return jsonify({"error": "Prišlo je do napake pri prijavi"}), 500
    finally:
        cursor.close()

@auth_bp.route('/logout', methods=['POST', 'GET'])
def logout():
    """Odjava uporabnika."""
    session.clear()
    
    # Če je POST zahtevek, vrni JSON
    if request.method == 'POST':
        return jsonify({"message": "Uspešna odjava"})
    
    # Če je GET zahtevek, preusmeri na login stran
    return redirect('/login')

@auth_bp.route('/me', methods=['GET'])
def get_current_user():
    """Pridobi podatke o trenutnem uporabniku."""
    if 'user_id' not in session:
        return jsonify({"error": "Uporabnik ni prijavljen"}), 401
    
    db = get_db()
    cursor = db.cursor()
    
    try:
        cursor.execute("""
            SELECT id, username, first_name, last_name, email, role, permissions
            FROM users 
            WHERE id = %s AND is_active = TRUE
        """, (session['user_id'],))
        
        user = cursor.fetchone()
        
        if user:
            return jsonify({
                "user": {
                    "id": user['id'],
                    "username": user['username'],
                    "first_name": user['first_name'],
                    "last_name": user['last_name'],
                    "email": user['email'],
                    "role": user['role'],
                    "permissions": user['permissions']
                }
            })
        else:
            return jsonify({"error": "Uporabnik ni najden"}), 404
            
    except Exception as e:
        current_app.logger.error(f"Napaka pri pridobivanju uporabnika: {e}")
        return jsonify({"error": "Prišlo je do napake"}), 500
    finally:
        cursor.close()

@auth_bp.route('/permissions', methods=['GET'])
@require_permission('view_users')
def get_permissions_list():
    """Pridobi seznam vseh možnih dovoljenj."""
    permissions = [
        {"id": "view_admin_tabs", "name": "Prikaz admin zavihkov", "description": "Lahko vidi admin zavihke (Globalne akcije, Uporabniki)"},
        {"id": "manage_users", "name": "Upravljanje uporabnikov", "description": "Lahko upravlja uporabnike (dodaj, briši, dovoljenja, gesla)"},
        {"id": "send_auto_declarations", "name": "Pošiljanje deklaracij (avtomatsko)", "description": "Lahko generira in pošlje/ponovno pošlje deklaracije iz seznama naročil"},
        {"id": "send_invoice", "name": "Pošiljanje računov (MetaKocka)", "description": "Lahko pošlje račun iz Metakocke (UI gumb pri naročilu)"},
        {"id": "view_global_actions", "name": "Prikaz globalnih akcij", "description": "Lahko vidi zavihek Globalne akcije"},
        {"id": "view_orders", "name": "Pregled naročil", "description": "Lahko si ogleda naročila"},
        {"id": "add_serije", "name": "Dodajanje serij", "description": "Lahko doda nove serije"},
        {"id": "edit_serije", "name": "Urejanje serij", "description": "Lahko ureja obstoječe serije"},
        {"id": "delete_serije", "name": "Brisanje serij", "description": "Lahko briše serije"},
        {"id": "view_perfumes", "name": "Pregled parfumov", "description": "Lahko si ogleda parfume"},
        {"id": "edit_perfumes", "name": "Urejanje parfumov", "description": "Lahko ureja parfume"},
        {"id": "add_perfumes", "name": "Dodajanje parfumov", "description": "Lahko doda nove parfume"},
        {"id": "delete_perfumes", "name": "Brisanje parfumov", "description": "Lahko briše parfume"},
        {"id": "view_proizvajalci", "name": "Pregled proizvajalcev", "description": "Lahko si ogleda proizvajalce"},
        {"id": "edit_proizvajalci", "name": "Urejanje proizvajalcev", "description": "Lahko ureja proizvajalce"},
        {"id": "add_proizvajalci", "name": "Dodajanje proizvajalcev", "description": "Lahko doda nove proizvajalce"},
        {"id": "delete_proizvajalci", "name": "Brisanje proizvajalcev", "description": "Lahko briše proizvajalce"},
        {"id": "view_users", "name": "Pregled uporabnikov", "description": "Lahko si ogleda uporabnike"},
        {"id": "edit_users", "name": "Urejanje uporabnikov", "description": "Lahko ureja uporabnike"},
        {"id": "add_users", "name": "Dodajanje uporabnikov", "description": "Lahko doda nove uporabnike"},
        {"id": "delete_users", "name": "Brisanje uporabnikov", "description": "Lahko briše uporabnike"},
        {"id": "shopify_sync", "name": "Sinhronizacija Shopify", "description": "Lahko sinhronizira s Shopify"},
        {"id": "generate_pdf", "name": "Generiranje PDF", "description": "Lahko generira PDF dokumente"},
        {"id": "send_email", "name": "Pošiljanje e-pošte", "description": "Lahko pošlje e-pošto"}
    ]
    
    return jsonify({"permissions": permissions})

@auth_bp.route('/login', methods=['GET'])
def login_page():
    """Prikaži login stran."""
    return render_template('login.html')


@auth_bp.route('/shopify/install', methods=['GET'])
def shopify_install():
    """Start Shopify OAuth install flow."""
    shop = _normalize_shop_domain(request.args.get('shop'))
    if not shop:
        return jsonify({"error": "Missing shop parameter"}), 400

    client_id = current_app.config.get('SHOPIFY_APP_CLIENT_ID')
    client_secret = current_app.config.get('SHOPIFY_APP_CLIENT_SECRET')
    if not client_id or not client_secret:
        return jsonify({"error": "Shopify OAuth app credentials are not configured"}), 500

    if not _verify_shopify_hmac(request.args, client_secret):
        return jsonify({"error": "Invalid HMAC signature"}), 400

    state = uuid.uuid4().hex
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            "INSERT INTO shopify_oauth_states (shop_domain, state) VALUES (%s, %s) ON CONFLICT (state) DO NOTHING",
            (shop, state),
        )
        db.commit()
    except Exception as e:
        db.rollback()
        current_app.logger.error(f"OAuth state insert failed for {shop}: {e}")
        return jsonify({"error": "OAuth state init failed"}), 500
    finally:
        cursor.close()

    base_url = current_app.config.get('APP_BASE_URL') or current_app.config.get('WEBHOOK_BASE_URL', 'https://deklaracije.eu')
    redirect_uri = f"{base_url}/shopify/callback"
    scopes = current_app.config.get('SHOPIFY_APP_SCOPES', 'read_orders,read_products,write_products')
    authorize_url = (
        f"https://{shop}/admin/oauth/authorize"
        f"?client_id={client_id}"
        f"&scope={scopes}"
        f"&redirect_uri={redirect_uri}"
        f"&state={state}"
    )
    return redirect(authorize_url)


@auth_bp.route('/shopify/callback', methods=['GET'])
def shopify_callback():
    """Handle Shopify OAuth callback and store access token."""
    shop = _normalize_shop_domain(request.args.get('shop'))
    code = request.args.get('code')
    state = request.args.get('state')
    if not shop or not code or not state:
        return jsonify({"error": "Missing OAuth parameters"}), 400

    client_id = current_app.config.get('SHOPIFY_APP_CLIENT_ID')
    client_secret = current_app.config.get('SHOPIFY_APP_CLIENT_SECRET')
    if not client_id or not client_secret:
        return jsonify({"error": "Shopify OAuth app credentials are not configured"}), 500

    if not _verify_shopify_hmac(request.args, client_secret):
        return jsonify({"error": "Invalid HMAC signature"}), 400

    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            "SELECT id FROM shopify_oauth_states WHERE shop_domain = %s AND state = %s",
            (shop, state),
        )
        row = cursor.fetchone()
        if not row:
            return jsonify({"error": "Invalid OAuth state"}), 400

        # Exchange code for access token
        token_url = f"https://{shop}/admin/oauth/access_token"
        resp = requests.post(
            token_url,
            json={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
            },
            timeout=20,
        )
        resp.raise_for_status()
        access_token = resp.json().get('access_token')
        if not access_token:
            return jsonify({"error": "Missing access token in response"}), 500

        from services.shopify_service import upsert_shopify_store_config
        upsert_shopify_store_config(shop, access_token, webhook_secret=client_secret, order_prefix="#SI")

        cursor.execute("DELETE FROM shopify_oauth_states WHERE shop_domain = %s", (shop,))
        db.commit()
    except Exception as e:
        db.rollback()
        current_app.logger.error(f"OAuth callback failed for {shop}: {e}")
        return jsonify({"error": "OAuth callback failed"}), 500
    finally:
        cursor.close()

    return redirect(url_for('auth.login'))