import os
import psycopg
from psycopg.rows import dict_row
from flask import g, current_app, cli
import click

# Privzeti `idle_in_transaction_session_timeout` (ms) za navadne (request)
# povezave. Spletne zahteve nikoli ne smejo legitimno viseti "idle in
# transaction" >60s, zato je to varovalka proti puščanju povezav (glej commit
# 9775564). Override prek env `PG_IDLE_TX_TIMEOUT_MS`.
_DEFAULT_IDLE_TX_TIMEOUT_MS = os.environ.get('PG_IDLE_TX_TIMEOUT_MS', '60000')

# Za BACKGROUND opravila (safety net, reconcile, MK sync ...) je timeout
# IZKLOPLJEN (0). Ti jobi legitimno držijo transakcijo odprto, medtem ko
# kličejo POČASNE zunanje API-je (MetaKocka iskanje/attach, Shopify), kar
# pogosto preseže 60s. S 60s timeoutom je Postgres prekinil povezavo sredi
# joba ("terminating connection due to idle-in-transaction timeout") in job
# se je sesul → deklaracije se niso pošiljale. Override: `PG_BG_IDLE_TX_TIMEOUT_MS`.
_BG_IDLE_TX_TIMEOUT_MS = os.environ.get('PG_BG_IDLE_TX_TIMEOUT_MS', '0')


def get_db(background: bool = False):
    """Vrne povezavo na bazo podatkov, shranjeno v g kontekstu.

    Args:
        background: če True, je `idle_in_transaction_session_timeout` izklopljen
            (oz. `PG_BG_IDLE_TX_TIMEOUT_MS`). Uporabi v dolgotrajnih batch jobih,
            ki držijo transakcijo odprto med počasnimi zunanjimi API klici.
            Sicer velja `PG_IDLE_TX_TIMEOUT_MS` (privzeto 60s) za request povezave.
    """
    timeout_ms = _BG_IDLE_TX_TIMEOUT_MS if background else _DEFAULT_IDLE_TX_TIMEOUT_MS
    if 'db' not in g:
        g.db = psycopg.connect(
            current_app.config['DATABASE_URL'],
            row_factory=dict_row,
            options=f'-c idle_in_transaction_session_timeout={timeout_ms}',
        )
    elif background:
        # Povezava že obstaja (npr. ročni klic joba iz request konteksta) —
        # sprosti timeout za to sejo, da dolgotrajni job ne bo prekinjen.
        try:
            with g.db.cursor() as c:
                c.execute(f"SET idle_in_transaction_session_timeout = {int(timeout_ms)}")
            g.db.commit()
        except Exception:
            pass
    return g.db

def close_db(e=None):
    """Zapre povezavo na bazo podatkov.

    Pred zaprtjem naredimo rollback morebitne nepotrjene transakcije, da se
    povezava sprosti v čistem stanju in ne ostane v "idle in transaction".
    """
    db = g.pop('db', None)
    if db is not None:
        try:
            db.rollback()
        except Exception:
            pass
        db.close()

def init_db():
    """Pobriše obstoječe podatke in ustvari nove tabele."""
    db = psycopg.connect(current_app.config['DATABASE_URL'])
    cursor = db.cursor()

    print("ℹ️  Brisanje obstoječih tabel (serije, parfumi, proizvajalci, declarations)...")
    cursor.execute("DROP TABLE IF EXISTS serije CASCADE;")
    cursor.execute("DROP TABLE IF EXISTS parfumi CASCADE;")
    cursor.execute("DROP TABLE IF EXISTS proizvajalci CASCADE;")
    cursor.execute("DROP TABLE IF EXISTS declarations CASCADE;")
    print("✅ Stare tabele uspešno pobrisane.")

    print("ℹ️  Preverjam in ustvarjam tabelo 'orders' (če ne obstaja)...")
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id SERIAL PRIMARY KEY,
            shopify_order_id BIGINT UNIQUE NOT NULL,
            order_number TEXT NOT NULL,
            customer_name TEXT,
            customer_email TEXT,
            country_code VARCHAR(2),
            status_url TEXT,
            line_items JSONB,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            processed_at TIMESTAMP WITH TIME ZONE,
            email_sent_at TIMESTAMP WITH TIME ZONE,
            email_recipient TEXT,
            fulfilled_at TIMESTAMP WITH TIME ZONE,
            shopify_fulfilled_at TIMESTAMP WITH TIME ZONE,
            last_notification_at TIMESTAMP WITH TIME ZONE,
            pdf_generated_at TIMESTAMP WITH TIME ZONE
        );
    ''')

    print("ℹ️  Ustvarjam tabelo 'declarations'...")
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS declarations (
            id SERIAL PRIMARY KEY,
            order_number VARCHAR(255) NOT NULL,
            product_no VARCHAR(255) NOT NULL,
            proizvajalec_ime VARCHAR(255) NOT NULL,
            sestava_inci TEXT,
            rok_uporabe DATE,
            serijska_stevilka VARCHAR(255),
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            
            -- Povezava na tabelo z naročili za lažje poizvedbe
            order_id INTEGER REFERENCES orders(id) ON DELETE CASCADE,

            -- Zagotovi, da je vsak izdelek v naročilu lahko samo enkrat
            UNIQUE (order_number, product_no, proizvajalec_ime)
        );
    ''')
    
    # Dodamo indeks za hitrejše iskanje po številki naročila
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_declarations_order_number ON declarations(order_number);')
    
    print("ℹ️  Ustvarjam tabele za katalog (proizvajalci, parfumi, serije)...")
    cursor.execute('''
        CREATE TABLE proizvajalci (
            id SERIAL PRIMARY KEY,
            ime VARCHAR(255) UNIQUE NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        );
    ''')
    cursor.execute('''
        CREATE TABLE parfumi (
            id SERIAL PRIMARY KEY,
            product_no VARCHAR(50) NOT NULL,
            proizvajalec_id INTEGER NOT NULL REFERENCES proizvajalci(id) ON DELETE CASCADE,
            ime_parfuma TEXT NOT NULL,
            sestava_inci TEXT,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(product_no, proizvajalec_id)
        );
    ''')
    cursor.execute('''
        CREATE TABLE serije (
            id SERIAL PRIMARY KEY,
            excel_row_id INTEGER UNIQUE,
            parfum_id INTEGER NOT NULL REFERENCES parfumi(id) ON DELETE CASCADE,
            rok_uporabe DATE,
            serijska_stevilka VARCHAR(255),
            stanje VARCHAR(50) DEFAULT 'NA ZALOGI',
            datum_odprtja DATE,
            je_tester BOOLEAN DEFAULT FALSE,
            vnesel_uporabnik VARCHAR(255),
            created_at_original TIMESTAMP WITH TIME ZONE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        );
    ''')
    print("✅ Nove tabele uspešno ustvarjene.")

    print("ℹ️  Vstavljanje začetnih podatkov...")
    cursor.execute("INSERT INTO proizvajalci (ime) VALUES ('MISTRAL'), ('FLORGARDEN') ON CONFLICT (ime) DO NOTHING;")

    db.commit()
    cursor.close()
    db.close()
    print("✅ Baza podatkov uspešno inicializirana.")

@click.command('init-db')
def init_db_command():
    """Inicializira shemo baze podatkov."""
    init_db()
    click.echo('✅ Baza podatkov uspešno inicializirana.')

def init_app(app):
    """Registrira funkcije za upravljanje z bazo v Flask aplikaciji."""
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)