from flask import Blueprint, request, current_app, Response
from api.utils.responses import make_ok, make_err
from database import get_db
from services.stats_compute import compute_points
from services.shopify_service import get_bulk_product_details
from datetime import datetime, timedelta, timezone
import json

stats_bp = Blueprint('stats', __name__, url_prefix='/api/stats')


def _parse_dates():
    start = request.args.get('start')
    end = request.args.get('end')
    group_by = request.args.get('group_by', 'day')
    source = request.args.get('source', 'created')
    tz_name = request.args.get('tz', 'Europe/Ljubljana')
    user_id = request.args.get('user_id')

    if group_by not in ('day', 'week', 'month'):
        group_by = 'day'
    if source not in ('created', 'fulfilled'):
        source = 'created'
    if not start or not end:
        return None, make_err('BAD_REQUEST', 'start and end required')

    try:
        start_d = datetime.strptime(start, '%Y-%m-%d')
        end_d = datetime.strptime(end, '%Y-%m-%d')
    except Exception:
        return None, make_err('BAD_REQUEST', 'Invalid date format, expected YYYY-MM-DD')

    if (end_d - start_d).days > 180:
        return None, make_err('BAD_REQUEST', 'Date range too large (max 180 days)')

    # Convert to UTC window [start, end+1day)
    start_utc = datetime(start_d.year, start_d.month, start_d.day, tzinfo=timezone.utc)
    end_utc = datetime(end_d.year, end_d.month, end_d.day, tzinfo=timezone.utc) + timedelta(days=1)

    return {
        'start': start,
        'end': end,
        'group_by': group_by,
        'source': source,
        'tz_name': tz_name,
        'start_utc': start_utc,
        'end_utc': end_utc,
        'user_id': int(user_id) if user_id else None,
    }, None


@stats_bp.route('/workers', methods=['GET'])
def workers_stats():
    params, err = _parse_dates()
    if err:
        return err

    db = get_db()
    c = db.cursor()
    try:
        source = params['source']
        user_id = params['user_id']
        start_utc = params['start_utc']
        end_utc = params['end_utc']

        # Build SQL (with prepared_at if column exists, otherwise fallback)
        # Build dynamic WHERE to avoid NULL traps
        where_clauses = []
        params_list = []
        if source == 'fulfilled':
            where_clauses.append("o.fulfilled_at BETWEEN %s AND %s")
            params_list += [start_utc, end_utc]
        else:
            # created or prepared window
            where_clauses.append("(o.created_at BETWEEN %s AND %s OR (SELECT TRUE FROM information_schema.columns WHERE table_name='orders' AND column_name='prepared_at' LIMIT 1) IS TRUE AND o.prepared_at BETWEEN %s AND %s)")
            params_list += [start_utc, end_utc, start_utc, end_utc]
        where_clauses.append("(o.prepared_by IS NOT NULL OR o.nalivalec_id IS NOT NULL)")
        if user_id is not None:
            where_clauses.append("(u.id = %s OR o.nalivalec_id = %s)")
            params_list += [user_id, user_id]
        where_sql = ' AND '.join(where_clauses)
        sql = (
            "WITH base AS ("
            " SELECT o.id, o.order_number, o.created_at, o.fulfilled_at, o.line_items,"
            "        o.prepared_by, o.nalivalec_id,"
            "        u.id AS prepared_by_id, u.first_name, u.last_name, u.username"
            "   FROM orders o"
            "   LEFT JOIN users u ON u.username = o.prepared_by"
            f"  WHERE {where_sql}"
            ") SELECT * FROM base"
        )
        c.execute(sql, tuple(params_list))
        rows = c.fetchall()

        # Prepare records and product ids
        import json
        product_ids = set()
        records = []
        # Collect usernames to backfill prepared_by_id if join failed
        usernames = set()
        for r in rows:
            d = dict(r)
            # Normalize inputs for compute
            d['prepared_by_id'] = d.get('prepared_by_id')
            if not d.get('prepared_by_id') and d.get('prepared_by'):
                usernames.add(str(d.get('prepared_by')))
            # collect product ids
            try:
                items = json.loads(d.get('line_items') or '[]')
            except Exception:
                items = []
            for it in items or []:
                pid = it.get('product_id')
                if pid:
                    product_ids.add(str(pid))
            records.append(d)

        # Build image info map for all orders: has_images and last uploader
        try:
            ord_nums_all = [d.get('order_number', '').lstrip('#') for d in records if d.get('order_number')]
            if ord_nums_all:
                c.execute(
                    """
                    SELECT oi.order_number,
                           COUNT(*) > 0 AS has_images,
                           (ARRAY_AGG(oi.user_id ORDER BY oi.uploaded_at DESC))[1] as last_uid
                    FROM order_images oi
                    WHERE oi.order_number = ANY(%s)
                    GROUP BY oi.order_number
                    """,
                    (ord_nums_all,)
                )
                img_info_map = {row['order_number']: {'has_images': row['has_images'], 'last_uid': row['last_uid']} for row in c.fetchall()}
            else:
                img_info_map = {}
        except Exception as e:
            current_app.logger.error(f"order_images info fetch failed: {e}")
            img_info_map = {}

        # Backfill prepared_by_id from usernames if possible
        if usernames:
            try:
                # Pull broader mapping (username and full name) for resilient backfill
                c.execute("SELECT id, username, LOWER(username) AS luser, LOWER(CONCAT(COALESCE(first_name,''),' ',COALESCE(last_name,''))) AS lname FROM users")
                maps = c.fetchall()
                uname_to_id = {}
                full_to_id = {}
                for row in maps:
                    uname_to_id[row['luser']] = row['id']
                    if row.get('lname'):
                        full_to_id[row['lname']] = row['id']
                for d in records:
                    if not d.get('prepared_by_id'):
                        raw = (d.get('prepared_by') or '')
                        key = str(raw).strip().lower()
                        uid = uname_to_id.get(key) or full_to_id.get(key)
                        if uid:
                            d['prepared_by_id'] = uid
            except Exception as e:
                current_app.logger.error(f"username backfill failed: {e}")

        # Use image info to standardize prepared_by_id: if images exist and last uploader exists, set prepared_by_id to last uploader.
        # If no images exist for the order, do not credit packing (null out prepared_by_id).
        for d in records:
            key = (d.get('order_number') or '').lstrip('#')
            ii = img_info_map.get(key)
            if ii and ii.get('has_images') and ii.get('last_uid'):
                d['prepared_by_id'] = ii.get('last_uid')
            elif not (ii and ii.get('has_images')):
                d['prepared_by_id'] = None

        product_details = {}
        try:
            if product_ids:
                product_details = get_bulk_product_details(list(product_ids)) or {}
        except Exception as e:
            current_app.logger.error(f"product details fetch failed: {e}")

        comp = compute_points(records, tz_name=params['tz_name'], group_by=params['group_by'], source=source, product_details=product_details)

        # Enrich summary with names
        users_map = {}
        try:
            c.execute("SELECT id, first_name, last_name, username FROM users WHERE id = ANY(%s)", ([s['user_id'] for s in comp['summary']] or [0],))
            for ur in c.fetchall():
                users_map[ur['id']] = ur
        except Exception:
            pass
        for s in comp['summary']:
            u = users_map.get(s['user_id'])
            full = ((u.get('first_name') or '') + ' ' + (u.get('last_name') or '')).strip() if u else None
            s['username'] = u.get('username') if u else None
            s['full_name'] = full or s.get('full_name') or s.get('username') or f"User {s['user_id']}"

        total_prepared_orders = sum(1 for d in records if d.get('prepared_by_id'))
        return make_ok({
            'summary': comp['summary'],
            'timeseries': comp['timeseries'],
            'meta': { 'start': params['start'], 'end': params['end'], 'group_by': params['group_by'], 'tz': params['tz_name'], 'total_orders': len(records), 'total_prepared_orders': total_prepared_orders },
            'warnings': comp['warnings'],
        })
    except Exception as e:
        current_app.logger.error(f"stats workers error: {e}")
        return make_err('SERVER_ERROR', 'Napaka pri izračunu statistike', status=500)
    finally:
        c.close()


@stats_bp.route('/workers/export.csv', methods=['GET'])
def workers_stats_export():
    params, err = _parse_dates()
    if err:
        return err

    # Reuse API to build result
    with current_app.test_request_context():
        resp = workers_stats()
        if resp.status_code != 200:
            return resp
        data = resp.get_json().get('data', {})
        summary = data.get('summary', [])

    # Build CSV
    import csv, io
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['user_id','username','full_name','points','pack_count','pour_count','parfumi_items','non_parfumi_items','parfumi_share_pct'])
    for r in summary:
        writer.writerow([
            r.get('user_id'), r.get('username'), r.get('full_name'),
            r.get('points'), r.get('pack_count'), r.get('pour_count'),
            r.get('parfumi_items'), r.get('non_parfumi_items'), r.get('parfumi_share_pct')
        ])
    csv_data = output.getvalue()
    output.close()
    return Response(csv_data, mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename="workers_summary.csv"'})


@stats_bp.route('/workers/<int:user_id>/details', methods=['GET'])
def worker_details(user_id):
    params, err = _parse_dates()
    if err:
        return err

    db = get_db()
    c = db.cursor()
    try:
        source = params['source']
        start_utc = params['start_utc']
        end_utc = params['end_utc']

        # Get user info
        c.execute("SELECT id, first_name, last_name, username FROM users WHERE id = %s", (user_id,))
        user = c.fetchone()
        if not user:
            return make_err('NOT_FOUND', 'Uporabnik ne obstaja')

        # Get orders prepared by this user (use last uploader as ground truth)
        prepared_orders = []
        if source == 'fulfilled':
            c.execute(
                """
                WITH last_up AS (
                    SELECT oi.order_number, (ARRAY_AGG(oi.user_id ORDER BY oi.uploaded_at DESC))[1] AS last_uid
                    FROM order_images oi
                    GROUP BY oi.order_number
                )
                SELECT o.id, o.order_number, o.created_at, o.fulfilled_at, o.line_items, o.prepared_by
                FROM orders o
                JOIN last_up lu ON lu.order_number = REPLACE(o.order_number,'#','')
                WHERE o.fulfilled_at BETWEEN %s AND %s
                AND lu.last_uid = %s
                ORDER BY o.fulfilled_at DESC
                """,
                (start_utc, end_utc, user_id),
            )
        else:
            c.execute(
                """
                WITH last_up AS (
                    SELECT oi.order_number, (ARRAY_AGG(oi.user_id ORDER BY oi.uploaded_at DESC))[1] AS last_uid
                    FROM order_images oi
                    GROUP BY oi.order_number
                )
                SELECT o.id, o.order_number, o.created_at, o.fulfilled_at, o.line_items, o.prepared_by
                FROM orders o
                JOIN last_up lu ON lu.order_number = REPLACE(o.order_number,'#','')
                WHERE (o.created_at BETWEEN %s AND %s OR o.prepared_at BETWEEN %s AND %s)
                AND lu.last_uid = %s
                ORDER BY COALESCE(o.prepared_at, o.created_at) DESC
                """,
                (start_utc, end_utc, start_utc, end_utc, user_id),
            )
        
        for row in c.fetchall():
            order = dict(row)
            # Build admin URL if possible
            try:
                shop = current_app.config.get('SHOP_NAME')
                if shop and order.get('id'):
                    # id here is internal DB id; prefer shopify_order_id if available
                    # We don't have shopify_order_id in this query; attempt to fetch it
                    c2 = db.cursor()
                    try:
                        c2.execute("SELECT shopify_order_id FROM orders WHERE id = %s", (order['id'],))
                        row2 = c2.fetchone()
                        if row2 and row2.get('shopify_order_id'):
                            order['order_admin_url'] = f"https://admin.shopify.com/store/{shop}/orders/{row2['shopify_order_id']}"
                    finally:
                        c2.close()
            except Exception:
                pass
            # Parse line items to count products (use quantities)
            try:
                def _is_cod_fee(item):
                    sku = str(item.get('sku') or '').strip().upper()
                    title = str(item.get('title') or '').strip().lower()
                    return sku == 'CODFEE' or ('po povzetju' in title) or ('cod' in title)

                raw_items = order.get('line_items', '[]')
                items = json.loads(raw_items) if isinstance(raw_items, str) else (raw_items or [])
                non_parfum_qty = 0
                parfum_qty = 0
                for it in items or []:
                    qty = it.get('quantity') or 1
                    try:
                        qty = int(qty)
                    except Exception:
                        qty = 1
                    ptype = str(it.get('product_type') or '').strip().lower()
                    if ptype in ('parfum', 'parfumi'):
                        parfum_qty += qty
                    else:
                        if not _is_cod_fee(it):
                            non_parfum_qty += qty
                order['product_count'] = parfum_qty + non_parfum_qty
                order['parfumi_count'] = parfum_qty
            except Exception:
                order['product_count'] = 0
                order['parfumi_count'] = 0
            prepared_orders.append(order)

        # Get orders where this user was nalivalec (apply source filter consistently)
        nalivalec_orders = []
        if source == 'fulfilled':
            c.execute(
                """
                SELECT o.id, o.order_number, o.created_at, o.fulfilled_at, o.line_items, o.nalivalec_id
                FROM orders o
                WHERE o.nalivalec_id = %s
                AND o.fulfilled_at BETWEEN %s AND %s
                ORDER BY o.fulfilled_at DESC
                """,
                (user_id, start_utc, end_utc),
            )
        else:
            c.execute(
                """
                SELECT o.id, o.order_number, o.created_at, o.fulfilled_at, o.line_items, o.nalivalec_id
                FROM orders o
                WHERE o.nalivalec_id = %s
                AND (o.created_at BETWEEN %s AND %s OR o.prepared_at BETWEEN %s AND %s)
                ORDER BY COALESCE(o.prepared_at, o.created_at) DESC
                """,
                (user_id, start_utc, end_utc, start_utc, end_utc),
            )
        
        for row in c.fetchall():
            order = dict(row)
            # Build admin URL if possible
            try:
                shop = current_app.config.get('SHOP_NAME')
                if shop and order.get('id'):
                    c2 = db.cursor()
                    try:
                        c2.execute("SELECT shopify_order_id FROM orders WHERE id = %s", (order['id'],))
                        row2 = c2.fetchone()
                        if row2 and row2.get('shopify_order_id'):
                            order['order_admin_url'] = f"https://admin.shopify.com/store/{shop}/orders/{row2['shopify_order_id']}"
                    finally:
                        c2.close()
            except Exception:
                pass
            # Parse line items to count products for nalivanja (count ONLY perfumes, using quantities)
            try:
                raw_items = order.get('line_items', '[]')
                items = json.loads(raw_items) if isinstance(raw_items, str) else (raw_items or [])
                parfum_qty = 0
                for it in items or []:
                    qty = it.get('quantity') or 1
                    try:
                        qty = int(qty)
                    except Exception:
                        qty = 1
                    ptype = str(it.get('product_type') or '').strip().lower()
                    if ptype in ('parfum', 'parfumi'):
                        parfum_qty += qty
                # For nalivanja, product_count reflects only perfumes
                order['product_count'] = parfum_qty
                order['parfumi_count'] = parfum_qty
            except Exception:
                order['product_count'] = 0
                order['parfumi_count'] = 0
            nalivalec_orders.append(order)

        # Calculate summary stats
        total_prepared_orders = len(prepared_orders)
        prepared_parfumi_qty = sum(o.get('parfumi_count', 0) for o in prepared_orders)
        prepared_non_parfumi_qty = sum(max(0, o.get('product_count', 0) - o.get('parfumi_count', 0)) for o in prepared_orders)
        prepared_total_qty = prepared_parfumi_qty + prepared_non_parfumi_qty
        poured_parfumi_qty = sum(o.get('parfumi_count', 0) for o in nalivalec_orders)

        return make_ok({
            'user': {
                'id': user['id'],
                'first_name': user['first_name'],
                'last_name': user['last_name'],
                'username': user['username'],
                'full_name': f"{user['first_name'] or ''} {user['last_name'] or ''}".strip() or user['username']
            },
            'period': {
                'start': params['start'],
                'end': params['end'],
                'source': source
            },
            'summary': {
                'total_prepared_orders': total_prepared_orders,
                'prepared_parfumi_qty': prepared_parfumi_qty,
                'prepared_non_parfumi_qty': prepared_non_parfumi_qty,
                'prepared_total_qty': prepared_total_qty,
                'poured_parfumi_qty': poured_parfumi_qty
            },
            'prepared_orders': prepared_orders,
            'nalivalec_orders': nalivalec_orders
        })

    except Exception as e:
        current_app.logger.error(f"worker details error: {e}")
        return make_err('SERVER_ERROR', 'Napaka pri pridobivanju podrobnosti', status=500)
    finally:
        c.close()


