"""Internal admin/cron endpoints.

Te poti so namenjene ad-hoc admin opravilom in cron klicem (npr. Heroku
Scheduler, GitHub Actions, ročno preko curl). Vse zahtevajo eno od:

  - veljavna admin Flask session (username == 'admin'), ali
  - header `Authorization: Bearer <CRON_SECRET>` oz. query `?secret=...`

Endpoints:
  GET  /api/internal/backfill-fulfillment?days=14&limit=300
       - Pull Shopify fulfillments za naročila brez `fulfilled_at` in
         posodobi DB. Po končanem klicu bo naslednji reconcile / 21:00
         batch normalno generiral PDF + MK upload.
  POST /api/internal/mk-attach/<order_number>
       - Ad-hoc: takoj poskusi naložiti PDF deklaracije v MK za eno
         naročilo (uporabi mk_sales_order_id cache, če obstaja).
  GET  /api/internal/order-status/<order_number>
       - Diagnostika: lokalna DB stanja + MK + Shopify za eno naročilo.
  POST /api/internal/safety-net/run?window=14&batch=50
       - Ročno sprozi safety net job (smart retry za manjkajoče deklaracije).
  POST /api/internal/safety-net/process/<order_number>
       - Procesiraj eno naročilo skozi safety net pipeline (test/recovery).
  POST /api/internal/safety-net/verify
       - Sprozi Mandrill verify job (preveri status nedavnih safety sends).
  POST /api/internal/safety-net/invalidate-parfum/<parfum_id>
       - Smart invalidation: sprosti vsa naročila, blokirana s tem parfumom.
         Klikni iz UI ko vneses novo serijo / popraviš INCI.
  GET  /api/internal/safety-net/blocked
       - Seznam vseh trenutno blokiranih naročil (admin pregled).
"""
from __future__ import annotations

import os
from typing import Any, Dict

from flask import Blueprint, current_app, jsonify, request, session
from database import get_db


internal_bp = Blueprint('internal', __name__, url_prefix='/api/internal')


def _is_authorized() -> bool:
    """Allow if admin session OR shared CRON_SECRET matches."""
    try:
        if session.get('user_id') and session.get('username') == 'admin':
            return True
    except Exception:
        pass
    secret = (os.environ.get('CRON_SECRET') or current_app.config.get('CRON_SECRET') or '').strip()
    if not secret:
        return False
    provided = (
        request.headers.get('X-Cron-Secret')
        or (request.headers.get('Authorization') or '').replace('Bearer ', '').strip()
        or request.args.get('secret', '').strip()
    )
    return bool(provided) and provided == secret


def _unauthorized():
    return jsonify({'ok': False, 'error': 'unauthorized'}), 403


@internal_bp.route('/backfill-fulfillment', methods=['GET', 'POST'])
def backfill_fulfillment():
    if not _is_authorized():
        return _unauthorized()
    try:
        days = int(request.args.get('days', '14') or 14)
    except Exception:
        days = 14
    try:
        limit = int(request.args.get('limit', '300') or 300)
    except Exception:
        limit = 300

    from services.background_service import backfill_fulfillment_from_shopify
    result = backfill_fulfillment_from_shopify(days=days, limit=limit)
    return jsonify({'ok': True, 'days': days, 'limit': limit, **result})


@internal_bp.route('/mk-attach/<path:order_number>', methods=['POST', 'GET'])
def mk_attach(order_number: str):
    if not _is_authorized():
        return _unauthorized()

    from services.mk_service import mk_attach_declaration_for_order

    on = (order_number or '').strip()
    if not on:
        return jsonify({'ok': False, 'error': 'missing order_number'}), 400

    db = get_db()
    c = db.cursor()
    try:
        c.execute(
            """
            SELECT order_number, shopify_order_id, mk_bill_id, mk_bill_type, mk_sales_order_id,
                   pdf_generated_at, mk_decl_uploaded_at, fulfilled_at, shopify_fulfilled_at
            FROM orders
            WHERE order_number = %s OR order_number = %s OR order_number = %s
            LIMIT 1
            """,
            (on, on.lstrip('#'), f"#{on.lstrip('#')}"),
        )
        row = c.fetchone()
        if not row:
            return jsonify({'ok': False, 'error': 'order_not_found', 'order_number': on}), 404

        attach_res = mk_attach_declaration_for_order(
            row.get('order_number') or on,
            shopify_order_id=row.get('shopify_order_id'),
            mk_bill_id=row.get('mk_bill_id'),
            mk_bill_type=row.get('mk_bill_type'),
            mk_sales_order_id=row.get('mk_sales_order_id'),
        )
        if attach_res.get('success'):
            c.execute(
                """
                UPDATE orders
                SET mk_decl_uploaded_at = CURRENT_TIMESTAMP,
                    mk_decl_upload_checked_at = NOW()
                WHERE order_number = %s OR order_number = %s
                """,
                (row.get('order_number'), f"#{(row.get('order_number') or '').lstrip('#')}"),
            )
            db.commit()
        return jsonify({
            'ok': True,
            'order_number': row.get('order_number'),
            'inputs': {
                'mk_sales_order_id': row.get('mk_sales_order_id'),
                'mk_bill_id': row.get('mk_bill_id'),
                'mk_bill_type': row.get('mk_bill_type'),
                'pdf_generated_at': str(row.get('pdf_generated_at')) if row.get('pdf_generated_at') else None,
                'fulfilled_at': str(row.get('fulfilled_at')) if row.get('fulfilled_at') else None,
            },
            'attach_result': attach_res,
        })
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        current_app.logger.error(f"/api/internal/mk-attach error: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        try:
            c.close()
        except Exception:
            pass


@internal_bp.route('/order-status/<path:order_number>', methods=['GET'])
def order_status(order_number: str):
    if not _is_authorized():
        return _unauthorized()
    on = (order_number or '').strip()
    db = get_db()
    c = db.cursor()
    try:
        c.execute(
            """
            SELECT order_number, shopify_order_id, shopify_store_domain, status,
                   fulfilled_at, shopify_fulfilled_at, shopify_fulfillment_id,
                   pdf_generated_at, mk_decl_uploaded_at, mk_decl_upload_checked_at,
                   mk_sales_order_id, mk_status_desc, mk_last_checked_at,
                   mk_last_status_desc, mk_last_status_code, mk_last_status_at,
                   mk_return_detected_at,
                   mk_bill_id, mk_bill_type,
                   has_missing_data, missing_data_details,
                   pdf_generation_blocked_reason, pdf_generation_blocked_codes,
                   mandrill_safety_message_id, mandrill_safety_status,
                   tracking_number, tracking_company, tracking_url,
                   delivered_at, delivered_source, created_at
            FROM orders
            WHERE order_number = %s OR order_number = %s OR order_number = %s
            LIMIT 1
            """,
            (on, on.lstrip('#'), f"#{on.lstrip('#')}"),
        )
        row = c.fetchone()
        if not row:
            return jsonify({'ok': False, 'error': 'order_not_found', 'order_number': on}), 404
        out: Dict[str, Any] = dict(row) if isinstance(row, dict) else {}
        for k, v in list(out.items()):
            if hasattr(v, 'isoformat'):
                out[k] = v.isoformat()
        return jsonify({'ok': True, 'order': out})
    finally:
        try:
            c.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Declaration safety net endpoints
# ---------------------------------------------------------------------------

@internal_bp.route('/safety-net/run', methods=['POST', 'GET'])
def safety_net_run():
    """Ročno sproži safety net job. Vrne stats."""
    if not _is_authorized():
        return _unauthorized()
    try:
        window = int(request.args.get('window', '14') or 14)
    except Exception:
        window = 14
    try:
        batch = int(request.args.get('batch', '50') or 50)
    except Exception:
        batch = 50

    from services.declaration_safety_net import run_safety_net_job
    stats = run_safety_net_job(window_days=window, batch_limit=batch)
    return jsonify({'ok': True, 'window': window, 'batch': batch, 'stats': stats})


@internal_bp.route('/safety-net/process/<path:order_number>', methods=['POST', 'GET'])
def safety_net_process_one(order_number: str):
    """Procesiraj eno naročilo skozi safety net pipeline (debug/recovery).

    Ker MK search v najslabšem primeru traja >30s (Heroku H12), to delamo v
    background-u. Vrnemo 202 takoj. Rezultat lahko spremljaš prek logov
    ali prek /api/internal/order-status/<order_number>.

    Query param `sync=1` za sinhron klic (ne priporočeno za neznana naročila).
    """
    if not _is_authorized():
        return _unauthorized()
    on = (order_number or '').strip()
    if not on:
        return jsonify({'ok': False, 'error': 'missing order_number'}), 400

    sync_mode = request.args.get('sync', '').strip() in ('1', 'true', 'yes')

    from services.declaration_safety_net import process_one
    db = get_db()
    c = db.cursor()
    try:
        c.execute(
            "SELECT * FROM orders WHERE order_number = %s OR order_number = %s OR order_number = %s LIMIT 1",
            (on, on.lstrip('#'), f"#{on.lstrip('#')}"),
        )
        row = c.fetchone()
        if not row:
            return jsonify({'ok': False, 'error': 'order_not_found', 'order_number': on}), 404

        order_data = dict(row) if not isinstance(row, dict) else row

        if sync_mode:
            # Sinhron pot (lahko timeout-a na Heroku)
            result = process_one(order_data, c)
            db.commit()
            return jsonify({'ok': True, 'mode': 'sync', 'result': result})

        # Background: scheduleamo enkratno opravilo v APScheduler.
        # To je bolj robustno kot threading.Thread na Heroku, ker:
        #   - APScheduler ima centraliziran error logging in retry
        #   - z `coalesce=True` se ob restartu dyna job pravilno izvede
        #   - ne tvegamo, da bi dyno cycling sredi thread-a ubilo upload
        # Fallback na threading se zgodi avtomatsko, če scheduler ni na voljo.
        from services.scheduler_helpers import schedule_one_shot

        def _bg_safety_net_process(order_data_inner: dict):
            from database import get_db as _gdb
            inner_db = _gdb()
            inner_c = inner_db.cursor()
            try:
                r = process_one(order_data_inner, inner_c)
                inner_db.commit()
                current_app.logger.info(
                    f"safety-net/process(scheduled) {order_data_inner.get('order_number')}: {r}"
                )
            except Exception as e:
                inner_db.rollback()
                current_app.logger.error(
                    f"safety-net/process(scheduled) {order_data_inner.get('order_number')} error: {e}",
                    exc_info=True
                )
                raise
            finally:
                try:
                    inner_c.close()
                except Exception:
                    pass

        on_clean = (order_data.get('order_number') or '').lstrip('#').strip()
        job_id = schedule_one_shot(
            _bg_safety_net_process,
            args=(order_data,),
            job_id=f"safety-net-process:{on_clean}",
        )
        return jsonify({
            'ok': True,
            'mode': 'scheduled',
            'job_id': job_id,
            'order_number': order_data.get('order_number'),
            'message': 'Scheduled via APScheduler. Check /api/internal/order-status/<order_number> in 1-2 min.'
        }), 202
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        current_app.logger.error(f"/api/internal/safety-net/process error: {e}", exc_info=True)
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        try:
            c.close()
        except Exception:
            pass


@internal_bp.route('/safety-net/verify', methods=['POST', 'GET'])
def safety_net_verify():
    """Sproži Mandrill verify job."""
    if not _is_authorized():
        return _unauthorized()
    from services.declaration_safety_net import run_mandrill_verify_job
    stats = run_mandrill_verify_job()
    return jsonify({'ok': True, 'stats': stats})


@internal_bp.route('/safety-net/audit', methods=['POST', 'GET'])
def safety_net_audit():
    """Layer 2: scan Mandrill log za 'false positive' uploads.

    Query params:
      days_back=10  (koliko dni Mandrill log scan-ati)
      batch_limit=100  (koliko DB kandidatov ovrednotiti)
    """
    if not _is_authorized():
        return _unauthorized()
    try:
        days = int(request.args.get('days_back', '10') or 10)
    except Exception:
        days = 10
    try:
        batch = int(request.args.get('batch_limit', '100') or 100)
    except Exception:
        batch = 100

    from services.declaration_safety_net import run_mandrill_log_audit_job
    stats = run_mandrill_log_audit_job(days_back=days, batch_limit=batch)
    return jsonify({'ok': True, 'stats': stats})


@internal_bp.route('/safety-net/invalidate-parfum/<int:parfum_id>', methods=['POST', 'GET'])
def safety_net_invalidate_parfum(parfum_id: int):
    """Sprosti block flags za vsa naročila, povezana s tem parfumom.

    Klic iz UI ko admin vnese novo serijo ali popravi INCI.
    Query param 'codes' (csv) za omejitev na specifične kode
    (npr. ?codes=expired_serije,missing_inci).
    """
    if not _is_authorized():
        return _unauthorized()
    codes_raw = (request.args.get('codes') or '').strip()
    codes = [c.strip() for c in codes_raw.split(',') if c.strip()] if codes_raw else None

    from services.declaration_safety_net import invalidate_blocks_for_parfum
    n = invalidate_blocks_for_parfum(parfum_id, codes=codes)
    return jsonify({'ok': True, 'parfum_id': parfum_id, 'codes': codes, 'unblocked': n})


@internal_bp.route('/safety-net/blocked', methods=['GET'])
def safety_net_blocked():
    """Seznam vseh trenutno blokiranih naročil za admin pregled."""
    if not _is_authorized():
        return _unauthorized()
    db = get_db()
    c = db.cursor()
    try:
        c.execute(
            """
            SELECT order_number, customer_email, customer_name, created_at,
                   shopify_fulfilled_at, fulfilled_at,
                   pdf_generation_blocked_reason, pdf_generation_blocked_codes,
                   pdf_generation_blocked_parfumi, pdf_generation_last_attempt_at,
                   mandrill_safety_attempted_at, mandrill_safety_status
            FROM orders
            WHERE requires_declaration = TRUE
              AND mk_decl_uploaded_at IS NULL
              AND pdf_generation_blocked_reason IS NOT NULL
            ORDER BY created_at DESC
            LIMIT 500
            """
        )
        rows = c.fetchall()
        out = []
        for r in rows:
            d = dict(r) if not isinstance(r, dict) else r
            for k, v in list(d.items()):
                if hasattr(v, 'isoformat'):
                    d[k] = v.isoformat()
            out.append(d)
        return jsonify({'ok': True, 'count': len(out), 'orders': out})
    finally:
        try:
            c.close()
        except Exception:
            pass


@internal_bp.route('/mk-cache-warmup', methods=['POST', 'GET'])
def mk_cache_warmup():
    """Batch populator za mk_sales_order_id + mk_last_status_{desc,code}.

    Strategy:
      1. Query MK /search z result_type=doc za sales_order, paginating od najnovejših
      2. Vsak row ima v sebi celoten dokument (mk_id, title, buyer_order,
         status_code, status_desc, ...) — ni potrebe po per-row get_document.
      3. Za vsak dokument matchaj proti našemu orders.order_number in cache-aj.
      4. Hkrati zaznaj returned in nastavi mk_return_detected_at.

    Query params:
      - pages=N        (max pages, default 5 → 500 najnovejših sales_order)
      - apply_returns  (default 1 → set mk_return_detected_at za returned)

    Returns: stats po naročilih (cached, returned_detected, no_match)
    """
    if not _is_authorized():
        return _unauthorized()
    try:
        pages = int(request.args.get('pages', '5') or 5)
    except Exception:
        pages = 5
    apply_returns = (request.args.get('apply_returns', '1') or '1').strip() in ('1', 'true', 'yes')

    import requests
    from services.mk_service import _mk_base, _mk_company_id, _mk_secret_key
    from services.declaration_safety_net import classify_mk_status

    base = _mk_base(); company_id = _mk_company_id(); secret = _mk_secret_key()
    if not base or not company_id or not secret:
        return jsonify({'ok': False, 'error': 'mk_config_missing'}), 500

    db = get_db()
    c = db.cursor()
    stats: Dict[str, Any] = {
        'pages_fetched': 0,
        'docs_seen': 0,
        'orders_cached': 0,
        'orders_already_cached': 0,
        'returned_detected': 0,
        'completed_seen': 0,
        'shipped_seen': 0,
        'no_local_match': 0,
        'errors': [],
    }

    try:
        # Preberemo skupno število, da scan-amo OD KONCA (= najnovejša)
        head_payload = {
            'company_id': str(company_id),
            'secret_key': str(secret),
            'doc_type': 'sales_order',
            'offset': 0,
            'limit': 1,
        }
        try:
            r = requests.post(f"{base}/search", json=head_payload, timeout=20)
            r.raise_for_status()
            head = r.json() if isinstance(r.json(), dict) else {}
            total = int(head.get('result_all_records') or 0)
        except Exception as e:
            return jsonify({'ok': False, 'error': f'mk_head_failed: {e}'}), 500

        if not total:
            return jsonify({'ok': True, 'stats': stats, 'note': 'MK reported 0 sales_orders'})

        page_size = 100
        for page in range(pages):
            offset = max(0, total - page_size * (page + 1))
            limit = min(page_size, total - offset)
            if limit <= 0:
                break
            payload = {
                'company_id': str(company_id),
                'secret_key': str(secret),
                'doc_type': 'sales_order',
                'result_type': 'doc',  # vrni cele dokumente, ne samo mk_id-jev
                'offset': offset,
                'limit': limit,
            }
            try:
                resp = requests.post(f"{base}/search", json=payload, timeout=45)
                if not resp.ok:
                    stats['errors'].append(f"page={page} HTTP {resp.status_code}")
                    break
                data = resp.json()
                rows = data if isinstance(data, list) else (
                    data.get('rows') or data.get('result') or data.get('documents') or []
                )
            except Exception as e:
                stats['errors'].append(f"page={page} fetch_error: {e}")
                break

            stats['pages_fetched'] += 1
            for doc in rows or []:
                if not isinstance(doc, dict):
                    continue
                stats['docs_seen'] += 1
                mk_id = doc.get('mk_id') or doc.get('id') or doc.get('doc_id')
                if not mk_id:
                    continue
                title = (doc.get('title') or '').strip()
                buyer = (doc.get('buyer_order') or '').strip()
                status_desc = doc.get('status_desc') or None
                status_code = doc.get('status_code') or None
                category = classify_mk_status(status_desc, status_code)

                if category == 'completed':
                    stats['completed_seen'] += 1
                elif category == 'shipped':
                    stats['shipped_seen'] += 1

                # Najdi local order po title ALI buyer_order (z/brez #)
                candidates = []
                for ref in (title, buyer):
                    if not ref:
                        continue
                    clean = ref.lstrip('#').strip()
                    if not clean:
                        continue
                    candidates.append(clean)
                    candidates.append(f"#{clean}")

                if not candidates:
                    continue

                # SELECT prvi match
                placeholders = ','.join(['%s'] * len(candidates))
                c.execute(
                    f"SELECT order_number, mk_sales_order_id, mk_return_detected_at "
                    f"FROM orders WHERE order_number IN ({placeholders}) LIMIT 1",
                    tuple(candidates),
                )
                row = c.fetchone()
                if not row:
                    stats['no_local_match'] += 1
                    continue

                row_d = dict(row) if not isinstance(row, dict) else row
                order_num_local = row_d.get('order_number')
                already_cached = bool(row_d.get('mk_sales_order_id'))

                # UPDATE cache + last status
                c.execute(
                    """
                    UPDATE orders SET
                        mk_sales_order_id   = COALESCE(mk_sales_order_id, %s),
                        mk_last_status_desc = %s,
                        mk_last_status_code = %s,
                        mk_last_status_at   = NOW(),
                        mk_last_checked_at  = NOW()
                    WHERE order_number = %s
                    """,
                    (str(mk_id), status_desc, status_code, order_num_local),
                )

                if already_cached:
                    stats['orders_already_cached'] += 1
                else:
                    stats['orders_cached'] += 1

                if category == 'returned' and apply_returns and not row_d.get('mk_return_detected_at'):
                    c.execute(
                        "UPDATE orders SET mk_return_detected_at = NOW() WHERE order_number = %s",
                        (order_num_local,),
                    )
                    stats['returned_detected'] += 1

            db.commit()  # commit po vsaki strani

        return jsonify({'ok': True, 'pages_requested': pages, 'stats': stats})
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        try:
            c.close()
        except Exception:
            pass


@internal_bp.route('/mk-raw-search/<path:order_number>', methods=['GET'])
def mk_raw_search(order_number: str):
    """Raw MK search za sales_order po title/buyer_order, brez retry storm-a.

    Vrne SUROVE rezultate iz MK /search endpoint-a (max 20 zapisov),
    BREZ klicanja mk_get_document() za vsak row. To je hitro (1-3s) in
    nam pove, ali MK sploh ima sales_order za to naročilo.
    """
    if not _is_authorized():
        return _unauthorized()
    on = (order_number or '').strip().lstrip('#')
    if not on:
        return jsonify({'ok': False, 'error': 'missing order_number'}), 400

    import requests
    from services.mk_service import _mk_base, _mk_company_id, _mk_secret_key
    base = _mk_base(); company_id = _mk_company_id(); secret = _mk_secret_key()
    if not base or not company_id or not secret:
        return jsonify({'ok': False, 'error': 'mk_config_missing'}), 500

    out: Dict[str, Any] = {'ok': True, 'order_number': on, 'results': {}}
    try:
        for mode in ('title', 'buyer_order'):
            payload = {
                'company_id': str(company_id),
                'secret_key': str(secret),
                'doc_type': 'sales_order',
                mode: on,
                'offset': 0,
                'limit': 20,
            }
            try:
                resp = requests.post(f"{base}/search", json=payload, timeout=15)
                if not resp.ok:
                    out['results'][mode] = {'http_status': resp.status_code, 'body': resp.text[:300]}
                    continue
                data = resp.json()
                rows = data if isinstance(data, list) else (
                    data.get('rows') or data.get('result') or data.get('documents') or []
                )
                # Vrni samo ključna polja (brez celotnega dokumenta)
                slim = [
                    {
                        'mk_id': r.get('mk_id') or r.get('id') or r.get('doc_id'),
                        'title': r.get('title'),
                        'buyer_order': r.get('buyer_order'),
                        'count_code': r.get('count_code'),
                        'status_code': r.get('status_code'),
                        'status_desc': r.get('status_desc'),
                        'doc_date': r.get('doc_date'),
                    }
                    for r in (rows or [])
                ]
                out['results'][mode] = {'count': len(slim), 'rows': slim}
            except Exception as e:
                out['results'][mode] = {'error': str(e)}
        return jsonify(out)
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@internal_bp.route('/mk-status-check/<path:order_number>', methods=['GET', 'POST'])
def mk_status_check(order_number: str):
    """Diagnostika: za eno naročilo poišči mk_sales_order_id, prikliči MK
    status in vrni klasifikacijo (completed/returned/shipped/pending/unknown).

    Brez PDF generiranja, brez Mandrill send-a. Samo MK lookup + classify.
    Sinhrono — odzove se v 5-60s (odvisno od MK search hitrosti).

    Query params:
      - apply=1   → tudi UPDATE orders SET mk_return_detected_at = NOW()
                    če je status returned
    """
    if not _is_authorized():
        return _unauthorized()
    on = (order_number or '').strip()
    apply_flag = (request.args.get('apply') or '').strip() in ('1', 'true', 'yes')

    from services.declaration_safety_net import (
        mk_check_sales_order_status_full,
        classify_mk_status,
        mk_find_and_cache_sales_order_id,
    )

    db = get_db()
    c = db.cursor()
    try:
        c.execute(
            "SELECT order_number, mk_sales_order_id FROM orders "
            "WHERE order_number = %s OR order_number = %s OR order_number = %s LIMIT 1",
            (on, on.lstrip('#'), f"#{on.lstrip('#')}"),
        )
        row = c.fetchone()
        if not row:
            return jsonify({'ok': False, 'error': 'order_not_found', 'order_number': on}), 404

        row_d = dict(row) if not isinstance(row, dict) else row
        order_num_db = row_d.get('order_number')
        mk_id = row_d.get('mk_sales_order_id')
        found_via = 'cache'
        if not mk_id:
            mk_id = mk_find_and_cache_sales_order_id(order_num_db, c)
            db.commit()
            found_via = 'drag_search'

        if not mk_id:
            return jsonify({
                'ok': True,
                'order_number': order_num_db,
                'mk_sales_order_id': None,
                'error': 'mk_sales_order_id_not_found',
                'note': 'MK ni našel sales_order za to naročilo (drag search miss)',
            })

        full = mk_check_sales_order_status_full(mk_id)
        category = classify_mk_status(full.get('status_desc'), full.get('status_code'))

        # Posnemi MK status v lokalno DB
        c.execute(
            """
            UPDATE orders SET
                mk_last_status_desc = %s,
                mk_last_status_code = %s,
                mk_last_status_at   = NOW()
            WHERE order_number = %s
            """,
            (full.get('status_desc'), full.get('status_code'), order_num_db)
        )

        applied = False
        if apply_flag and category == 'returned':
            c.execute(
                "UPDATE orders SET mk_return_detected_at = COALESCE(mk_return_detected_at, NOW()) "
                "WHERE order_number = %s",
                (order_num_db,)
            )
            applied = True
        db.commit()

        return jsonify({
            'ok': True,
            'order_number': order_num_db,
            'mk_sales_order_id': mk_id,
            'mk_id_found_via': found_via,
            'mk_status_desc': full.get('status_desc'),
            'mk_status_code': full.get('status_code'),
            'category': category,
            'applied': applied,
        })
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        try:
            c.close()
        except Exception:
            pass


@internal_bp.route('/migrate/025-mk-return-detection', methods=['POST', 'GET'])
def migrate_025_mk_return_detection():
    """Ad-hoc migration runner za migracijo 025 (Vračilo paketa detection).

    Idempotent — varno klicati večkrat.
    """
    if not _is_authorized():
        return _unauthorized()
    db = get_db()
    c = db.cursor()
    try:
        c.execute(
            """
            ALTER TABLE orders
              ADD COLUMN IF NOT EXISTS mk_return_detected_at TIMESTAMPTZ,
              ADD COLUMN IF NOT EXISTS mk_last_status_desc   TEXT,
              ADD COLUMN IF NOT EXISTS mk_last_status_code   TEXT,
              ADD COLUMN IF NOT EXISTS mk_last_status_at     TIMESTAMPTZ;
            """
        )
        c.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_orders_mk_returned
                ON orders (mk_return_detected_at)
             WHERE mk_return_detected_at IS NOT NULL;
            """
        )
        c.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_orders_mk_last_status_desc
                ON orders (mk_last_status_desc)
             WHERE mk_last_status_desc IS NOT NULL;
            """
        )
        db.commit()
        return jsonify({'ok': True, 'migration': '025_mk_return_detection', 'applied': True})
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        try:
            c.close()
        except Exception:
            pass
