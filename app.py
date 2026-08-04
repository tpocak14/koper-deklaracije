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
    from blueprints.internal_routes import internal_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(webhook_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(stats_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(internal_bp)

    # 5b. Machine-only: UI/login/session API so zaprti (v2 je edini frontend).
    from machine_only import register_machine_only_gate
    register_machine_only_gate(app)

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
        # Po dogovoru (2026-05-26):
        #   - 21:00 batch: tvori PDF + naloži v MK na sales_order (audit + MK
        #     Mandrill trigger ready). Mandrill se NE pošlje takoj, ker naročilo
        #     trenutno ni "Zaključeno" v MK (paket še ni dostavljen + plačan).
        #   - Hourly cron declaration_safety_net_job: scan-a nedavna fulfilled
        #     naročila, preveri MK status, in pošlje Mandrill samo če MK pravi
        #     "Zaključeno" (= dostavljeno + plačano).
        #   - MK Mandrill trigger ostane vklopljen kot backup (idempotency
        #     check v naši app prepreči duplikate).
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
                    rec_limit = int(os.environ.get('RECONCILE_LIMIT', '50') or 50)
                    rec_hours = int(os.environ.get('RECONCILE_HOURS_BACK', '24') or 24)
                    result = reconcile_missing_declarations(hours_back=rec_hours, limit=rec_limit)
                    app.logger.info(f"Declaration reconcile: {result}")
                except Exception as e:
                    app.logger.error(f"Napaka pri deklaracijskem reconciliation jobu: {e}")

        # Kill switch: set DISABLE_RECONCILE_JOB=1 (or DISABLE_BG_JOBS=1) on Heroku
        # to stop the hourly reconciliation entirely without a code deploy.
        _disable_all = (os.environ.get('DISABLE_BG_JOBS', '') or '').strip().lower() in ('1', 'true', 'yes')
        _disable_reconcile = _disable_all or (os.environ.get('DISABLE_RECONCILE_JOB', '') or '').strip().lower() in ('1', 'true', 'yes')
        if not _disable_reconcile:
            _interval_min = int(os.environ.get('RECONCILE_INTERVAL_MIN', '60') or 60)
            scheduler.add_job(declaration_reconcile_job, 'interval', minutes=_interval_min)
        else:
            app.logger.warning("declaration_reconcile_job DISABLED via env (DISABLE_BG_JOBS / DISABLE_RECONCILE_JOB)")
        
        # Nočni import MK računov (vsak dan ob 03:15)
        def sync_mk_bills_job():
            with app.app_context():
                try:
                    # Izklopi idle-in-transaction timeout za to (dolgotrajno) povezavo —
                    # MK sync drži transakcijo med počasnimi MK API klici.
                    from database import get_db as _get_db
                    _get_db(background=True)
                    from services.mk_service import mk_sync_bills, mk_backfill_orders_bill_ids
                    imported = mk_sync_bills(days=1, max_scan_per_type=3000, page_size=200)
                    app.logger.info(f"MK nightly sync: imported/updated {imported} bills")
                    # Po importu poveži račune z naročili (hitra SQL operacija) —
                    # da je mk_bill_id znan takoj na strani naročila, brez klika.
                    linked = mk_backfill_orders_bill_ids(days=60)
                    app.logger.info(f"MK nightly sync: povezanih {linked} naročil z računi")
                except Exception as e:
                    app.logger.error(f"Napaka pri nočnem MK sync-u: {e}")

        scheduler.add_job(sync_mk_bills_job, 'cron', hour=3, minute=15)

        # Pogost povezovalni job (vsakih 30 min): MK račun obstaja že ob
        # fulfillmentu, zato kmalu po njem uvozimo nedavne račune (lahek scan)
        # in jih povežemo z naročili (orders.mk_bill_id). Tako je status MK
        # računa viden skoraj takoj, brez čakanja na nočni sync ali klik na PDF.
        _disable_link = _disable_all or (os.environ.get('DISABLE_MK_BILL_LINK_JOB', '') or '').strip().lower() in ('1', 'true', 'yes')

        def mk_bill_link_job():
            with app.app_context():
                try:
                    from database import get_db as _get_db
                    _get_db(background=True)
                    # Per-order resolucija (zanesljiva za nedavne MK račune, ki jih
                    # bulk date-scan ne doseže). Najprej hitra povezava iz mk_bills,
                    # nato iskanje v živo za preostala nepovezana naročila.
                    from services.mk_service import mk_backfill_orders_bill_ids, mk_link_orders_missing_bills
                    mk_backfill_orders_bill_ids(days=30)
                    win = int(os.environ.get('MK_BILL_LINK_WINDOW_DAYS', '21') or 21)
                    lim = int(os.environ.get('MK_BILL_LINK_LIMIT', '25') or 25)
                    linked = mk_link_orders_missing_bills(days=win, limit=lim)
                    if linked:
                        app.logger.info(f"mk_bill_link_job: povezanih {linked} naročil z MK računi")
                except Exception as e:
                    app.logger.error(f"mk_bill_link_job error: {e}")

        if not _disable_link:
            _link_interval = int(os.environ.get('MK_BILL_LINK_INTERVAL_MIN', '30') or 30)
            scheduler.add_job(mk_bill_link_job, 'interval', minutes=_link_interval)
        else:
            app.logger.warning("mk_bill_link_job DISABLED via env")
        
        # Nočni retail delta import (vsak dan ob 01:30)
        def retail_delta_job():
            with app.app_context():
                try:
                    from database import get_db as _get_db
                    _get_db(background=True)
                    from services.mk_service import mk_import_retail_bills_delta
                    imported = mk_import_retail_bills_delta(hours=24, scan_window=5000)
                    app.logger.info(f"Retail nightly delta: imported {imported} retail bills in last 24h")
                except Exception as e:
                    app.logger.error(f"Napaka pri nočnem retail delta importu: {e}")

        scheduler.add_job(retail_delta_job, 'cron', hour=1, minute=30)

        # Mandrill send job (vsako uro): za vsa fulfilled naročila v zadnjih
        # 7 dneh preveri MK status. Če je MK status = "Zaključeno" (dostavljeno +
        # plačano) in mi še nismo poslali Mandrill, pošlje deklaracijo kupcu.
        # Idempotency: pred sendom preveri Mandrill log po order_id metadata,
        # da ne dupliciramo z MK Mandrill trigger-jem (ki ostane backup).
        def declaration_safety_net_job():
            with app.app_context():
                try:
                    from services.declaration_safety_net import run_safety_net_job
                    window = int(os.environ.get('SAFETY_NET_WINDOW_DAYS', '7') or 7)
                    batch = int(os.environ.get('SAFETY_NET_BATCH_LIMIT', '200') or 200)
                    res = run_safety_net_job(window_days=window, batch_limit=batch)
                    app.logger.info(
                        "declaration_safety_net_job done: scanned=%d, blocked=%d, "
                        "uploaded_mk_only=%d (waiting for MK completed), "
                        "uploaded_and_mandrill=%d (sent to customer), "
                        "returned=%d (Vračilo paketa, skipped), errors=%d",
                        res['scanned'], res['blocked'], res['uploaded_mk_only'],
                        res['uploaded_and_mandrill'], res.get('returned', 0),
                        res['errors'],
                    )
                except Exception as e:
                    app.logger.error(f"declaration_safety_net_job error: {e}", exc_info=True)

        _disable_safety = _disable_all or (os.environ.get('DISABLE_SAFETY_NET_JOB', '') or '').strip().lower() in ('1', 'true', 'yes')
        if not _disable_safety:
            _safety_min = int(os.environ.get('SAFETY_NET_INTERVAL_MIN', '60') or 60)
            scheduler.add_job(declaration_safety_net_job, 'interval', minutes=_safety_min)
        else:
            app.logger.warning("declaration_safety_net_job DISABLED via env")

        # Mandrill verify job (vsako uro, z zamikom 15 min): preveri status
        # nedavnih direktnih Mandrill safety sends — bounce/reject → admin alert.
        def mandrill_verify_job():
            with app.app_context():
                try:
                    from services.declaration_safety_net import run_mandrill_verify_job
                    res = run_mandrill_verify_job()
                    app.logger.info(
                        "mandrill_verify_job done: checked=%d, updated=%d, failures=%d",
                        res['checked'], res['updated'], res['failures'],
                    )
                except Exception as e:
                    app.logger.error(f"mandrill_verify_job error: {e}", exc_info=True)

        if not _disable_safety:
            scheduler.add_job(mandrill_verify_job, 'interval', minutes=60)

        # Aged unsent sweep (1x dnevno): ujame naročila, ki so ostarela izven
        # urnega 7-dnevnega okna, a so še vedno completed + pripravljena in
        # NISO poslana. Privzeto IZKLOPLJEN (DECL_AGED_SWEEP_ENABLED), ker bi
        # sicer ob prvem zagonu poslal obstoječi zaostanek (~259) brez potrditve.
        # Ko želimo zaostanek obdelati: nastavi DECL_AGED_SWEEP_ENABLED=1.
        def aged_unsent_sweep_job():
            with app.app_context():
                try:
                    from services.declaration_safety_net import run_aged_unsent_sweep_job
                    window = int(os.environ.get('DECL_AGED_SWEEP_WINDOW_DAYS', '45') or 45)
                    batch = int(os.environ.get('DECL_AGED_SWEEP_BATCH_LIMIT', '150') or 150)
                    res = run_aged_unsent_sweep_job(window_days=window, batch_limit=batch)
                    app.logger.info(
                        "aged_unsent_sweep_job done: scanned=%d, sent=%d, "
                        "waiting=%d, blocked=%d, returned=%d, errors=%d",
                        res['scanned'], res['uploaded_and_mandrill'],
                        res['uploaded_mk_only'], res['blocked'],
                        res['returned'], res['errors'],
                    )
                except Exception as e:
                    app.logger.error(f"aged_unsent_sweep_job error: {e}", exc_info=True)

        _enable_aged_sweep = (os.environ.get('DECL_AGED_SWEEP_ENABLED', '') or '').strip().lower() in ('1', 'true', 'yes', 'on')
        if not _disable_safety and _enable_aged_sweep:
            scheduler.add_job(aged_unsent_sweep_job, 'cron', hour=22, minute=30, timezone=lj)
            app.logger.info("aged_unsent_sweep_job ENABLED (daily 22:30)")
        else:
            app.logger.info("aged_unsent_sweep_job disabled (set DECL_AGED_SWEEP_ENABLED=1 to enable)")

        # Layer 2 audit (2x dnevno ob 06:00 in 18:00): scan Mandrill log za
        # naročila, ki "izgledajo OK" v Flasku ampak NISO dejansko poslana.
        # Označi te kot kandidate za safety net (reset mk_decl_uploaded_at).
        def mandrill_log_audit_job():
            with app.app_context():
                try:
                    from services.declaration_safety_net import run_mandrill_log_audit_job
                    res = run_mandrill_log_audit_job(days_back=12, batch_limit=80)
                    app.logger.info(
                        "mandrill_log_audit_job done: db_candidates=%d, known_sent=%d, "
                        "cached_already_sent=%d, missing=%d, rejected=%d, "
                        "marked_for_safety_net=%d, errors=%d",
                        res['db_candidates'], res['mandrill_known_sent'],
                        res['cached_already_sent'], res['candidates_missing_mandrill'],
                        res['mandrill_rejected'], res['marked_for_safety_net'],
                        res['errors'],
                    )
                except Exception as e:
                    app.logger.error(f"mandrill_log_audit_job error: {e}", exc_info=True)

        if not _disable_safety:
            scheduler.add_job(mandrill_log_audit_job, 'cron', hour='6,18', minute=0, timezone=lj)

        # Daily digest (vsak dan ob 21:30, po dnevnem batchu): povzetek
        # poslanih + blokiranih + že-prej-poslanih naročil.
        def safety_net_daily_digest_job():
            with app.app_context():
                try:
                    from database import get_db
                    from services.email_service import poslji_safety_net_daily_digest

                    db = get_db()
                    cursor = db.cursor()

                    # 1) Blokirana naročila (ne moremo tvoriti PDF zaradi manjkajočih podatkov)
                    cursor.execute(
                        """
                        SELECT order_number, customer_email AS email,
                               pdf_generation_blocked_codes AS codes,
                               pdf_generation_blocked_reason AS reason,
                               pdf_generation_last_attempt_at AS last_attempt
                          FROM orders
                         WHERE requires_declaration = TRUE
                           AND mandrill_safety_message_id IS NULL
                           AND pdf_generation_blocked_reason IS NOT NULL
                           AND (shopify_fulfilled_at IS NOT NULL OR fulfilled_at IS NOT NULL)
                           AND created_at > NOW() - INTERVAL '14 days'
                         ORDER BY created_at DESC
                         LIMIT 200
                        """
                    )
                    blocked = [dict(r) if not isinstance(r, dict) else r for r in cursor.fetchall()]

                    # 2) Mandrill sends zadnjih 24h (vse poslano kupcu)
                    cursor.execute(
                        """
                        SELECT order_number, mandrill_safety_status AS status,
                               customer_email AS email,
                               mandrill_safety_attempted_at AS sent_at
                          FROM orders
                         WHERE mandrill_safety_attempted_at > NOW() - INTERVAL '24 hours'
                         ORDER BY mandrill_safety_attempted_at DESC
                         LIMIT 500
                        """
                    )
                    sends = [dict(r) if not isinstance(r, dict) else r for r in cursor.fetchall()]

                    # 3) Skupno število fulfilled naročil danes (denominator za "coverage")
                    cursor.execute(
                        """
                        SELECT COUNT(*) AS n
                          FROM orders
                         WHERE requires_declaration = TRUE
                           AND (shopify_fulfilled_at::date = CURRENT_DATE
                                OR fulfilled_at::date = CURRENT_DATE)
                        """
                    )
                    total_today_row = cursor.fetchone()
                    total_today = (total_today_row.get('n') if isinstance(total_today_row, dict)
                                   else total_today_row[0]) if total_today_row else 0
                    cursor.close()

                    poslji_safety_net_daily_digest(
                        stats={
                            'scanned': total_today,
                            'uploaded_mk_only': 0,
                            'uploaded_and_mandrill': len(sends),
                            'blocked_total': len(blocked),
                            'errors': 0,
                        },
                        blocked_orders=blocked,
                        recent_safety_sends=sends,
                    )
                except Exception as e:
                    app.logger.error(f"safety_net_daily_digest_job error: {e}", exc_info=True)

        if not _disable_safety:
            scheduler.add_job(safety_net_daily_digest_job, 'cron', hour=21, minute=30, timezone=lj)

        # MK cache warmup (vsakih 30 min): bulk-napolni mk_sales_order_id +
        # mk_last_status iz MK /search (najnovejši sales_orderji). KLJUČNO za
        # safety-net: brez cache-iranega mk_sales_order_id mora safety-net za
        # vsako naročilo narediti drag-scan (minute/naročilo) → urni job se
        # zatakne in APScheduler (max_instances=1) preskoči vse nadaljnje
        # zagone. Prej je warmup prožil ZUNANJI cron na /api/internal/
        # mk-cache-warmup; ta je ob prehodu domen tiho odpovedal (~2026-06-03),
        # zato so deklaracije prenehale iti ven. Zdaj teče interno (brez zunanje
        # odvisnosti in brez 30s Heroku request limita).
        def mk_cache_warmup_job():
            with app.app_context():
                try:
                    from blueprints.internal_routes import mk_cache_warmup
                    sec = (os.environ.get('CRON_SECRET') or '').strip()
                    pages = int(os.environ.get('MK_WARMUP_PAGES', '6') or 6)
                    with app.test_request_context(
                        f"/api/internal/mk-cache-warmup?secret={sec}&pages={pages}&apply_returns=1"
                    ):
                        resp = mk_cache_warmup()
                    body = resp[0] if isinstance(resp, tuple) else resp
                    try:
                        payload = body.get_json(silent=True) or {}
                        st = payload.get('stats', {}) or {}
                        app.logger.info(
                            "mk_cache_warmup_job done: cached=%s already=%s returned=%s no_match=%s",
                            st.get('orders_cached'), st.get('orders_already_cached'),
                            st.get('returned_detected'), st.get('no_local_match'),
                        )
                    except Exception:
                        app.logger.info("mk_cache_warmup_job done")
                except Exception as e:
                    app.logger.error(f"mk_cache_warmup_job error: {e}", exc_info=True)

        _disable_warmup = _disable_all or (os.environ.get('DISABLE_MK_WARMUP_JOB', '') or '').strip().lower() in ('1', 'true', 'yes')
        if not _disable_warmup:
            _warm_min = int(os.environ.get('MK_WARMUP_INTERVAL_MIN', '30') or 30)
            scheduler.add_job(mk_cache_warmup_job, 'interval', minutes=_warm_min)
            # Enkratni zagon kmalu po startu (ne čakaj polnega intervala), da je
            # cache svež takoj po deployu/restartu.
            try:
                from datetime import datetime as _dtw, timedelta as _tdw
                scheduler.add_job(
                    mk_cache_warmup_job, 'date',
                    run_date=_dtw.now() + _tdw(seconds=90),
                    id='mk_warmup_initial', replace_existing=True,
                )
            except Exception:
                pass

        # Sender watchdog (vsako uro): alert, če pošiljanje deklaracij obstane.
        # Neodvisen DB-only check (brez MK/Mandrill klicev) — zazna, če so
        # dostavljena naročila (delivered_at iz app-v2 pipeline-a) ostala brez
        # poslane deklaracije >3h. Točno to bi ujelo incident 2026-06-09
        # (hung job → preskočeni zagoni → dnevi brez pošiljanja, brez alarma).
        def sender_watchdog_job():
            with app.app_context():
                try:
                    from services.declaration_safety_net import run_sender_watchdog_job
                    hours = int(os.environ.get('SENDER_WATCHDOG_BACKLOG_HOURS', '3') or 3)
                    thr = int(os.environ.get('SENDER_WATCHDOG_THRESHOLD', '3') or 3)
                    res = run_sender_watchdog_job(backlog_hours=hours, threshold=thr)
                    if res.get('alerted'):
                        app.logger.warning(
                            "sender_watchdog_job ALERT: backlog=%d", res.get('backlog'))
                    else:
                        app.logger.info(
                            "sender_watchdog_job ok: backlog=%d", res.get('backlog'))
                except Exception as e:
                    app.logger.error(f"sender_watchdog_job error: {e}", exc_info=True)

        _disable_watchdog = _disable_all or (os.environ.get('DISABLE_SENDER_WATCHDOG', '') or '').strip().lower() in ('1', 'true', 'yes')
        if not _disable_watchdog:
            _wd_min = int(os.environ.get('SENDER_WATCHDOG_INTERVAL_MIN', '60') or 60)
            scheduler.add_job(sender_watchdog_job, 'interval', minutes=_wd_min)

        scheduler.start()

        # Izpostavi globalno preko app.extensions, da lahko blueprints
        # programsko dodajajo one-shot opravila namesto threading.Thread.
        # Heroku dyno cycling lahko killuje proste thread-e mid-execution,
        # APScheduler-jeve job-e pa scheduler obnovi po reload-u (z misfire
        # policy `coalesce=True`). Glej services/scheduler_helpers.py.
        try:
            app.extensions['apscheduler'] = scheduler
        except Exception:
            # app.extensions je dict v Flask-u, ampak za vsak slučaj
            if not hasattr(app, 'extensions'):
                app.extensions = {}
            app.extensions['apscheduler'] = scheduler

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
    # Lokalni zagon — debug samo eksplicitno (nikoli privzeto True).
    port = int(os.getenv('PORT', 5001))
    app.run(host='0.0.0.0', port=port, debug=os.getenv('FLASK_DEBUG') == '1')