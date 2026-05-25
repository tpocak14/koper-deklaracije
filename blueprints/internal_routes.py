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
