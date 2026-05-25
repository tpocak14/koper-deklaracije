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
                   mk_bill_id, mk_bill_type,
                   has_missing_data, missing_data_details,
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
    """Procesiraj eno naročilo skozi safety net pipeline (debug/recovery)."""
    if not _is_authorized():
        return _unauthorized()
    on = (order_number or '').strip()
    if not on:
        return jsonify({'ok': False, 'error': 'missing order_number'}), 400

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
        result = process_one(order_data, c)
        db.commit()
        return jsonify({'ok': True, 'result': result})
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
