import os
from dotenv import load_dotenv

# Naloži spremenljivke okolja iz .env datoteke
load_dotenv()

class Config:
    # --- Osnovne nastavitve ---
    SECRET_KEY = os.getenv('SECRET_KEY', 'a_default_secret_key_for_development')
    DATABASE_URL = os.getenv('DATABASE_URL')
    
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