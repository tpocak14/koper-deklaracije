import os
from dotenv import load_dotenv

# Naloži spremenljivke okolja iz .env datoteke
load_dotenv()

class Config:
    # --- Osnovne nastavitve ---
    # V produkciji (Heroku DYNO) SECRET_KEY mora biti nastavljen — sicer boot pade.
    _secret = os.getenv('SECRET_KEY', '').strip()
    _default_dev_secret = 'a_default_secret_key_for_development'
    if os.environ.get('DYNO') or os.getenv('FLASK_ENV') == 'production':
        if not _secret or _secret == _default_dev_secret:
            raise RuntimeError(
                'SECRET_KEY mora biti nastavljen v produkciji (močan naključni niz).'
            )
    SECRET_KEY = _secret or _default_dev_secret
    DATABASE_URL = os.getenv('DATABASE_URL')

    # Seja — utrjena pred CSRF / krajo piškotka
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = bool(os.environ.get('DYNO') or os.getenv('FLASK_ENV') == 'production')
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 12  # 12 ur
    
    # --- Shopify ---
    SHOP_NAME = os.getenv('SHOP_NAME', 'parfumerija-amour')
    SHOPIFY_WEBHOOK_SECRET = os.getenv('SHOPIFY_WEBHOOK_SECRET')
    # Pravilna spremenljivka za Shopify API geslo
    SHOPIFY_API_PASSWORD = os.getenv('SHOPIFY_API_PASSWORD')
    # URL za webhook-e
    WEBHOOK_BASE_URL = os.getenv('WEBHOOK_BASE_URL', 'https://deklaracije.eu')
    # OAuth app (Dev Dashboard)
    SHOPIFY_APP_CLIENT_ID = os.getenv('SHOPIFY_APP_CLIENT_ID')
    SHOPIFY_APP_CLIENT_SECRET = os.getenv('SHOPIFY_APP_CLIENT_SECRET')
    SHOPIFY_APP_SCOPES = os.getenv('SHOPIFY_APP_SCOPES', 'read_orders,read_products,write_products')
    APP_BASE_URL = os.getenv('APP_BASE_URL', WEBHOOK_BASE_URL)
    
    # --- Avtentikacija ---
    ADMIN_USERNAME = os.getenv('ADMIN_USERNAME')
    ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD')
    
    # --- E-pošta ---
    MAIL_SERVER = os.getenv('MAIL_SERVER')
    MAIL_PORT = int(os.getenv('MAIL_PORT', 587))
    MAIL_USERNAME = os.getenv('MAIL_USERNAME')
    MAIL_PASSWORD = os.getenv('MAIL_PASSWORD')
    MAIL_SENDER_NAME = os.getenv('MAIL_SENDER_NAME')
    ADMIN_NOTIFICATION_EMAIL = os.getenv('ADMIN_NOTIFICATION_EMAIL')
    ADMIN_EMAIL = os.getenv('ADMIN_NOTIFICATION_EMAIL')  # Dodano za kompatibilnost
    TEST_RECIPIENT_EMAIL = os.getenv('TEST_RECIPIENT_EMAIL')

    # --- PDFKit Konfiguracija ---
    # Na Heroku je pot do binarne datoteke fiksna
    if 'DYNO' in os.environ:
        WKHTMLTOPDF_PATH = '/app/bin/wkhtmltopdf'
    else:
        # Za lokalni razvoj pustimo, da sistem sam najde pot
        WKHTMLTOPDF_PATH = None
    
    # --- Microsoft Graph API (OneDrive) Podatki ---
    CLIENT_ID = os.getenv('CLIENT_ID')
    CLIENT_SECRET = os.getenv('CLIENT_SECRET')
    TENANT_ID = os.getenv('TENANT_ID')
    EXCEL_FILE_ID = os.getenv('EXCEL_FILE_ID')
    DRIVE_ID = os.getenv('DRIVE_ID')
    
    # --- Amazon S3 (za shranjevanje slik) ---
    AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID')
    AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')
    AWS_REGION = os.getenv('AWS_REGION', 'eu-west-1')
    S3_BUCKET_NAME = os.getenv('S3_BUCKET_NAME')