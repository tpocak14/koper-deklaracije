import os
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler
import click

def create_app():
    """Application Factory: ustvari in konfigurira Flask aplikacijo."""
    app = Flask(__name__)

    # 1. Naloži konfiguracijo
    # To bo potegnilo SECRET_KEY in druge nastavitve iz config.py
    app.config.from_object('config.Config')

    # 2. Inicializira bazo podatkov
    from database import init_app as init_db_app
    init_db_app(app)

    # 3. Inicializira ukaze za migracijo
    from migrations import init_app as init_migrations_app
    init_migrations_app(app)
    
    # 4. Izvedi migracije (samo v produkciji)
    if not app.debug and not app.testing:
        try:
            from migrations import run_migrations
            with app.app_context():
                run_migrations()
                # One-time migration of legacy email logs into app_logs
                try:
                    from services.mk_service import (
                        migrate_invoice_email_log_to_app_logs,
                        migrate_declaration_email_orders_to_app_logs,
                    )
                    migrated_inv = migrate_invoice_email_log_to_app_logs()
                    migrated_dec = migrate_declaration_email_orders_to_app_logs()
                    if migrated_inv:
                        app.logger.info(f"Migriranih invoice email logov v app_logs: {migrated_inv}")
                    if migrated_dec:
                        app.logger.info(f"Migriranih declaration email logov v app_logs: {migrated_dec}")
                except Exception as me:
                    app.logger.error(f"Napaka pri migracijah email logov: {me}")
        except Exception as e:
            app.logger.error(f"Napaka pri izvajanju migracij: {e}")

    # 5. Registrira Blueprints (spletne poti)
    from blueprints.main_routes import main_bp
    from blueprints.webhook_routes import webhook_bp
    from blueprints.api_routes import api_bp
    from blueprints.stats_routes import stats_bp
    from blueprints.auth_routes import auth_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(webhook_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(stats_bp)
    app.register_blueprint(auth_bp)
    
    # 6. Naredi funkcije za preverjanje dovoljenj globalno dostopne
    from blueprints.auth_routes import has_permission, require_permission
    app.jinja_env.globals['has_permission'] = has_permission
    app.jinja_env.globals['require_permission'] = require_permission # <-- DODANO
    
    # 7. Nastavi S3 CORS konfiguracijo (samo v produkciji)
    if not app.debug and not app.testing:
        try:
            from services.s3_service import setup_s3_cors
            with app.app_context():
                setup_s3_cors()
                app.logger.info("S3 CORS konfiguracija uspešno nastavljena")
        except Exception as e:
            app.logger.error(f"Napaka pri nastavljanju S3 CORS: {e}")

    # 8. Nastavi periodična opravila (samo v produkciji)
    if not app.debug and not app.testing:
        scheduler = BackgroundScheduler(daemon=True)
        
        # Periodično procesiranje fulfilled naročil (vsakih 5 minut) - samo za backup
        def process_fulfilled_orders():
            with app.app_context():
                try:
                    from services.background_service import process_fulfilled_orders_background
                    process_fulfilled_orders_background()
                except Exception as e:
                    app.logger.error(f"Napaka pri periodičnem procesiranju fulfilled naročil: {e}")
        
        scheduler.add_job(process_fulfilled_orders, 'interval', minutes=5)

        # Daily declarations batch at 21:00 (Europe/Ljubljana)
        def daily_declarations_job():
            with app.app_context():
                try:
                    from services.background_service import process_fulfilled_orders_daily
                    process_fulfilled_orders_daily(window_days=2)
                except Exception as e:
                    app.logger.error(f"Napaka pri dnevnem generiranju deklaracij: {e}")

        try:
            from zoneinfo import ZoneInfo
            lj = ZoneInfo("Europe/Ljubljana")
        except Exception:
            lj = None
        scheduler.add_job(daily_declarations_job, 'cron', hour=21, minute=0, timezone=lj)

        # Hourly reconciliation to ensure no fulfilled order is missing declaration/MK upload
        def declaration_reconcile_job():
            with app.app_context():
                try:
                    from services.background_service import reconcile_missing_declarations
                    result = reconcile_missing_declarations(hours_back=72, limit=500)
                    app.logger.info(f"Declaration reconcile: {result}")
                except Exception as e:
                    app.logger.error(f"Napaka pri deklaracijskem reconciliation jobu: {e}")

        scheduler.add_job(declaration_reconcile_job, 'interval', minutes=60)
        
        # Nočni import MK računov (vsak dan ob 03:15)
        def sync_mk_bills_job():
            with app.app_context():
                try:
                    from services.mk_service import mk_sync_bills
                    imported = mk_sync_bills(days=1, max_scan_per_type=3000, page_size=200)
                    app.logger.info(f"MK nightly sync: imported/updated {imported} bills")
                except Exception as e:
                    app.logger.error(f"Napaka pri nočnem MK sync-u: {e}")

        scheduler.add_job(sync_mk_bills_job, 'cron', hour=3, minute=15)
        
        # Nočni retail delta import (vsak dan ob 01:30)
        def retail_delta_job():
            with app.app_context():
                try:
                    from services.mk_service import mk_import_retail_bills_delta
                    imported = mk_import_retail_bills_delta(hours=24, scan_window=5000)
                    app.logger.info(f"Retail nightly delta: imported {imported} retail bills in last 24h")
                except Exception as e:
                    app.logger.error(f"Napaka pri nočnem retail delta importu: {e}")

        scheduler.add_job(retail_delta_job, 'cron', hour=1, minute=30)
        
        scheduler.start()

    return app

# Ustvari instanco aplikacije za Gunicorn/WSGI strežnik
app = create_app()

@app.cli.command('migrate-perfumes')
def migrate_perfumes_command():
    """Migrira parfume iz Excel datoteke."""
    from migrations import migrate_perfumes_from_excel
    if migrate_perfumes_from_excel():
        click.echo('✅ Migracija parfumov uspešno končana!')
    else:
        click.echo('❌ Migracija parfumov ni uspela!')

@app.cli.command('mk-debug-retail-fetch')
@click.option('--take', default=5, help='Koliko računov prebrati iz prve retail strani in fetchati', type=int)
def mk_debug_retail_fetch(take: int):
    """Debug: /search retail (brez datumov), nato get_document za prve N in izpiši JSON [{mk_id,publish_ts,items_len}]."""
    from services.mk_service import debug_fetch_retail_first_n
    try:
        out = debug_fetch_retail_first_n(max(1, int(take)))
        click.echo(__import__('json').dumps(out, ensure_ascii=False))
    except Exception as e:
        click.echo(f"Napaka: {e}")

@app.cli.command('import:retail_last7')
def import_retail_last7_command():
    """Uvozi maloprodajne račune za zadnjih 7 dni in izpiše statistiko (JSON)."""
    from services.mk_service import sync_retail_bills_last_7d
    try:
        stats = sync_retail_bills_last_7d()
        click.echo(__import__('json').dumps(stats, ensure_ascii=False))
    except Exception as e:
        click.echo(f"Napaka: {e}")

@app.cli.command('mk-sync-decl-uploads')
@click.option('--days', default=7, help='Kako daleč nazaj (dni)', type=int)
@click.option('--limit', default=200, help='Maks število naročil', type=int)
@click.option('--include-already', is_flag=True, default=False, help='Vključi že označene')
@click.option('--order', multiple=True, help='Posamezna številka naročila (lahko večkrat)')
def mk_sync_decl_uploads(days: int, limit: int, include_already: bool, order: tuple):
    """Sync MK declaration upload timestamps into orders."""
    from services.mk_service import sync_mk_declaration_uploads
    try:
        order_numbers = list(order) if order else None
        result = sync_mk_declaration_uploads(
            days_back=days,
            limit=limit,
            include_already=include_already,
            order_numbers=order_numbers,
        )
        click.echo(f"Checked: {result.get('checked')} Updated: {result.get('updated')}")
        if result.get('orders'):
            click.echo("Orders: " + ", ".join(result.get('orders')))
    except Exception as e:
        click.echo(f"Napaka: {e}")

if __name__ == '__main__':
    # Zažene aplikacijo v razvojnem načinu
    port = int(os.getenv('PORT', 5001))
    app.run(host='0.0.0.0', port=port, debug=True)