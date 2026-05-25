"""
Background Service Module

Vsebuje funkcije za periodično procesiranje, ki se izvajajo v ozadju
preko APScheduler-ja. Te funkcije se izvajajo izven HTTP request konteksta,
zato ne smejo uporabljati Flask funkcionalnosti, ki potrebujejo request context.
"""

import json
import traceback
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from flask import current_app
from database import get_db
from services.pdf_service import generate_declaration_pdf
from services.email_service import poslji_email_s_pdf
from services.shopify_service import get_shopify_order_data


def process_fulfilled_orders_background():
    """
    Procesira vsa fulfilled naročila, ki še niso bila procesirana.
    
    Ta funkcija se izvaja v ozadju preko APScheduler-ja in ne potrebuje
    HTTP request konteksta. Je kopija logike iz API endpoint-a, vendar
    brez Flask specifičnih elementov.
    """
    current_app.logger.info("=== BACKGROUND: Začenjam procesiranje neprocesiranih fulfilled naročil ===")
    
    db = get_db()
    cursor = db.cursor()
    
    try:
        # Zagotovi, da je transakcija v pravilnem stanju
        db.rollback()
        
        # Pridobi vsa fulfilled naročila, ki še niso bila procesirana
        cursor.execute("""
            SELECT o.*, d.id as declaration_id 
            FROM orders o 
            LEFT JOIN declarations d ON o.order_number = d.order_number 
            WHERE o.fulfilled_at IS NOT NULL 
            AND (o.pdf_generated_at IS NULL OR o.email_sent_at IS NULL)
            ORDER BY o.fulfilled_at DESC
            LIMIT 10
        """)
        unprocessed_orders = cursor.fetchall()
        
        if not unprocessed_orders:
            current_app.logger.info("BACKGROUND: Ni neprocesiranih fulfilled naročil")
            return
        
        current_app.logger.info(f"BACKGROUND: Našel {len(unprocessed_orders)} neprocesiranih fulfilled naročil")
        
        processed_count = 0
        
        for order_data in unprocessed_orders:
            try:
                order_number = order_data['order_number']
                shopify_order_id = order_data['shopify_order_id']
                
                current_app.logger.info(f"BACKGROUND: Procesiram naročilo {order_number}")
                
                # 1. Pridobi podrobne podatke iz Shopify-ja
                shopify_data = get_shopify_order_data(shopify_order_id, shop_domain=order_data.get('shopify_store_domain'))
                if not shopify_data:
                    current_app.logger.warning(f"BACKGROUND: Ni mogoče pridobiti podatkov iz Shopify za naročilo {order_number}")
                    continue
                
                # 2. Generiraj PDF (če še ni bil generiran)
                if not order_data['pdf_generated_at']:
                    current_app.logger.info(f"BACKGROUND: Generiram PDF za naročilo {order_number}")
                    pdf_path = generate_declaration_pdf(order_number)
                    
                    if pdf_path:
                        # Označi, da je PDF generiran
                        cursor.execute("""
                            UPDATE orders 
                            SET pdf_generated_at = CURRENT_TIMESTAMP 
                            WHERE order_number = %s
                        """, (order_number,))
                        current_app.logger.info(f"BACKGROUND: PDF uspešno generiran za naročilo {order_number}")
                    else:
                        # Ni PDF (npr. ni deklaracijskih vrstic) -> preklopi na warning in ne poskušaj več
                        current_app.logger.warning(f"BACKGROUND: Preskakujem generiranje PDF – ni veljavnih deklaracijskih vrstic za {order_number}")
                        cursor.execute("""
                            UPDATE orders
                            SET pdf_generated_at = CURRENT_TIMESTAMP
                            WHERE order_number = %s AND pdf_generated_at IS NULL
                        """, (order_number,))
                        continue
                
                # 3. Pošlji email (če še ni bil poslan)
                if not order_data['email_sent_at']:
                    current_app.logger.info(f"BACKGROUND: Pošiljam declaration email za naročilo {order_number}")
                    
                    customer_email = shopify_data.get('email')
                    if not customer_email:
                        current_app.logger.warning(f"BACKGROUND: Manjka email naslov za naročilo {order_number}")
                        continue
                    
                    # Pripravi parametre za poslji_email_s_pdf
                    try:
                        # Uporabi že ustvarjen PDF, če obstaja, sicer ga generiraj zdaj
                        clean_no = order_number.replace('#', '') if isinstance(order_number, str) else str(order_number)
                        pdf_path_local = f"{current_app.root_path}/pdf/{clean_no}.pdf"
                        # Če datoteka ne obstaja, poskusi ponovno generirati zdaj
                        import os
                        if not os.path.isfile(pdf_path_local):
                            current_app.logger.info(f"BACKGROUND: PDF datoteka manjka, generiram znova za {order_number}")
                            regen = generate_declaration_pdf(order_number)
                            if regen:
                                pdf_path_local = regen
                            else:
                                current_app.logger.warning(f"BACKGROUND: Ne morem generirati PDF-ja za {order_number}; preskakujem pošiljanje")
                                continue

                        email_sent = poslji_email_s_pdf(
                            recipient_email=customer_email,
                            order_number=order_number,
                            shopify_order_id=shopify_order_id,
                            pdf_path=pdf_path_local,
                            declaration_items=[],
                            status_url=shopify_data.get('order_status_url'),
                            shop_url=f"https://{order_data.get('shopify_store_domain')}" if order_data.get('shopify_store_domain') else f"https://{current_app.config['SHOP_NAME']}.myshopify.com",
                            country_code=shopify_data.get('shipping_address', {}).get('country_code', 'SI'),
                            line_items=shopify_data.get('line_items', [])
                        )
                    except Exception as e:
                        current_app.logger.error(f"BACKGROUND: Napaka pri pripravi/pošiljanju email-a za {order_number}: {e}")
                        email_sent = False
                    
                    if email_sent:
                        # Označi, da je declaration email poslan
                        cursor.execute("""
                            UPDATE orders 
                            SET email_sent_at = CURRENT_TIMESTAMP, email_recipient = %s 
                            WHERE order_number = %s
                        """, (customer_email, order_number))
                        current_app.logger.info(f"BACKGROUND: Declaration email uspešno poslan za naročilo {order_number}")
                    else:
                        current_app.logger.warning(f"BACKGROUND: Declaration email ni poslan za naročilo {order_number}")
                        continue
                
                processed_count += 1
                current_app.logger.info(f"BACKGROUND: Uspešno procesirano naročilo {order_number}")
                
            except Exception as e:
                current_app.logger.error(f"BACKGROUND: Napaka pri procesiranju naročila {order_data.get('order_number', 'N/A')}: {e}")
                traceback.print_exc()
                db.rollback()  # Ponastavi transakcijo za to naročilo
                continue
        
        # Commit vseh uspešno procesiranih naročil
        db.commit()
        
        if processed_count > 0:
            current_app.logger.info(f"BACKGROUND: Uspešno procesirano {processed_count} fulfilled naročil")
        else:
            current_app.logger.info("BACKGROUND: Nobeno fulfilled naročilo ni bilo procesirano")
            
    except Exception as e:
        current_app.logger.error(f"BACKGROUND: Napaka pri procesiranju fulfilled naročil: {e}")
        traceback.print_exc()
        db.rollback()
        
    finally:
        cursor.close()


def _store_declaration_error(cursor, order_number: str, reason: str) -> None:
    """Store declaration error in order and mark as missing data."""
    try:
        payload = json.dumps([reason])
    except Exception:
        payload = reason
    cursor.execute(
        """
        UPDATE orders
        SET status = 'manjkajo_podatki',
            has_missing_data = TRUE,
            missing_data_details = %s
        WHERE order_number = %s OR order_number = %s
        """,
        (payload, order_number, f"#{str(order_number).replace('#','')}")
    )


def _clear_missing_data(cursor, order_number: str) -> None:
    """Clear missing-data flags when declaration data is available."""
    cursor.execute(
        """
        UPDATE orders
        SET has_missing_data = FALSE,
            missing_data_details = NULL,
            status = CASE WHEN status = 'manjkajo_podatki' THEN NULL ELSE status END
        WHERE order_number = %s OR order_number = %s
        """,
        (order_number, f"#{str(order_number).replace('#','')}")
    )


def _ensure_declaration_rows(cursor, order_data: dict) -> bool:
    """Ensure declarations rows exist for order, create if missing."""
    order_number = order_data.get('order_number')
    if not order_number:
        return False

    # Build declarations from Shopify line_items if possible
    try:
        from blueprints.api_routes import _pridobi_podatke_za_deklaracijo_iz_shopify, _shrani_deklaracijo_v_bazo
    except Exception:
        _store_declaration_error(cursor, order_number, "Manjka generator deklaracijskih vrstic.")
        return False

    line_items_raw = order_data.get('line_items') or '[]'
    try:
        line_items = json.loads(line_items_raw) if isinstance(line_items_raw, str) else (line_items_raw or [])
    except Exception:
        line_items = []
    if not line_items:
        # Fallback: fetch order data from Shopify and update local row
        try:
            shopify_order_id = order_data.get('shopify_order_id')
            if shopify_order_id:
                from services.shopify_service import get_shopify_order_data
                sh = get_shopify_order_data(shopify_order_id, shop_domain=order_data.get('shopify_store_domain'))
                if sh:
                    line_items = sh.get('line_items') or []
                    if line_items:
                        try:
                            country_code = ((sh.get('shipping_address') or {}) if isinstance(sh.get('shipping_address'), dict) else {}).get('country_code')
                        except Exception:
                            country_code = None
                        cursor.execute(
                            """
                            UPDATE orders
                            SET line_items = %s,
                                country_code = COALESCE(country_code, %s),
                                status_url = COALESCE(status_url, %s),
                                customer_email = COALESCE(customer_email, %s)
                            WHERE order_number = %s OR order_number = %s
                            """,
                            (
                                json.dumps(line_items),
                                country_code,
                                sh.get('order_status_url'),
                                sh.get('email'),
                                order_number,
                                f"#{str(order_number).replace('#','')}"
                            )
                        )
        except Exception as e:
            current_app.logger.warning(f"BACKGROUND: Shopify fallback failed for {order_number}: {e}")
        if not line_items:
            cursor.execute(
                """
                SELECT 1 FROM declarations
                WHERE order_number = %s OR order_number = %s
                LIMIT 1
                """,
                (order_number, f"#{str(order_number).replace('#','')}")
            )
            if cursor.fetchone():
                _clear_missing_data(cursor, order_number)
                return True
            _store_declaration_error(cursor, order_number, "Manjkajo line_items za deklaracijo.")
            return False

    declaration_items, missing, warnings = _pridobi_podatke_za_deklaracijo_iz_shopify(
        line_items,
        cursor,
        shop_domain=order_data.get('shopify_store_domain') if isinstance(order_data, dict) else None,
    )
    if warnings:
        # Block PDF generation when expiry is too close; show warnings in UI only.
        current_app.logger.warning(
            f"BACKGROUND: Expiry block for {order_number}: {warnings}"
        )
        _clear_missing_data(cursor, order_number)
        return False
    if not declaration_items:
        # No perfume items -> no declaration needed; don't mark as missing.
        if not missing:
            _clear_missing_data(cursor, order_number)
            return False
        reason = "Ni bilo mogoče pridobiti podatkov za deklaracijo."
        try:
            reason = f"Manjkajo podatki: {', '.join(missing)}"
        except Exception:
            pass
        _store_declaration_error(cursor, order_number, reason)
        return False

    ok = _shrani_deklaracijo_v_bazo(order_number, declaration_items, cursor)
    if not ok:
        _store_declaration_error(cursor, order_number, "Napaka pri shranjevanju deklaracije.")
        return False
    _clear_missing_data(cursor, order_number)
    return True


def process_fulfilled_orders_daily(window_days: int = 1) -> None:
    """Run daily batch: ensure all fulfilled orders in window have PDF."""
    db = get_db()
    cursor = db.cursor()
    try:
        db.rollback()
        # Use Ljubljana local day window, but store as UTC
        lj = ZoneInfo("Europe/Ljubljana")
        now_local = datetime.now(lj)
        start_local = (now_local - timedelta(days=window_days)).replace(hour=0, minute=0, second=0, microsecond=0)
        end_local = now_local.replace(hour=23, minute=59, second=59, microsecond=999999)
        start_utc = start_local.astimezone(timezone.utc)
        end_utc = end_local.astimezone(timezone.utc)

        cursor.execute(
            """
            SELECT *
            FROM orders o
            WHERE (o.fulfilled_at IS NOT NULL OR o.shopify_fulfilled_at IS NOT NULL)
              AND COALESCE(o.fulfilled_at, o.shopify_fulfilled_at) BETWEEN %s AND %s
              AND (
                o.pdf_generated_at IS NULL
                OR NOT EXISTS (
                    SELECT 1 FROM declarations d
                    WHERE d.order_number = o.order_number
                       OR d.order_number = REPLACE(o.order_number, '#','')
                       OR d.order_number = CONCAT('#', REPLACE(o.order_number, '#',''))
                )
              )
            ORDER BY COALESCE(o.fulfilled_at, o.shopify_fulfilled_at) DESC
            """,
            (start_utc, end_utc),
        )
        rows = cursor.fetchall() or []
        if not rows:
            return

        processed = 0
        for order_data in rows:
            order_number = order_data.get('order_number') if isinstance(order_data, dict) else None
            if not order_number:
                continue
            if not _ensure_declaration_rows(cursor, order_data):
                continue
            # Commit declaration rows so PDF generator (new connection) can see them
            try:
                db.commit()
            except Exception:
                pass
            pdf_path = generate_declaration_pdf(order_number)
            if pdf_path:
                cursor.execute(
                    """
                    UPDATE orders
                    SET pdf_generated_at = CURRENT_TIMESTAMP
                    WHERE order_number = %s OR order_number = %s
                    """,
                    (order_number, f"#{str(order_number).replace('#','')}")
                )
                processed += 1
            else:
                _store_declaration_error(cursor, order_number, "Napaka pri generiranju PDF deklaracije.")
        db.commit()
        current_app.logger.info(f"BACKGROUND: Daily declarations generated={processed} / total={len(rows)}")

        # Phase 2: after PDF generation, upload to MK.
        # We collect both successes and failures (with reason) so the
        # admin report can show what went wrong per order.
        mk_uploaded_orders: list[str] = []
        mk_failed_orders: list[dict] = []  # {order_number, reason}
        try:
            cursor.execute(
                """
                SELECT order_number, shopify_order_id, mk_bill_id, mk_bill_type, mk_sales_order_id
                FROM orders
                WHERE (fulfilled_at IS NOT NULL OR shopify_fulfilled_at IS NOT NULL)
                  AND COALESCE(fulfilled_at, shopify_fulfilled_at) BETWEEN %s AND %s
                  AND pdf_generated_at IS NOT NULL
                  AND mk_decl_uploaded_at IS NULL
                ORDER BY COALESCE(fulfilled_at, shopify_fulfilled_at) DESC
                """,
                (start_utc, end_utc),
            )
            mk_rows = cursor.fetchall() or []
            if mk_rows:
                from services.mk_service import mk_attach_declaration_for_order
                for r in mk_rows:
                    on = r.get('order_number') if isinstance(r, dict) else None
                    if not on:
                        continue
                    try:
                        attach_res = mk_attach_declaration_for_order(
                            str(on),
                            shopify_order_id=(r.get('shopify_order_id') if isinstance(r, dict) else None),
                            mk_bill_id=(r.get('mk_bill_id') if isinstance(r, dict) else None),
                            mk_bill_type=(r.get('mk_bill_type') if isinstance(r, dict) else None),
                            mk_sales_order_id=(r.get('mk_sales_order_id') if isinstance(r, dict) else None),
                        )
                        if attach_res.get("success"):
                            cursor.execute(
                                """
                                UPDATE orders
                                SET mk_decl_uploaded_at = CURRENT_TIMESTAMP,
                                    mk_decl_upload_checked_at = NOW()
                                WHERE order_number = %s OR order_number = %s
                                """,
                                (on, f"#{str(on).replace('#','')}")
                            )
                            mk_uploaded_orders.append(on)
                        else:
                            reason = attach_res.get("error") or "unknown_error"
                            mk_failed_orders.append({
                                "order_number": on,
                                "reason": str(reason),
                            })
                            # Record that we tried so reconcile knows.
                            cursor.execute(
                                """
                                UPDATE orders
                                SET mk_decl_upload_checked_at = NOW()
                                WHERE order_number = %s OR order_number = %s
                                """,
                                (on, f"#{str(on).replace('#','')}")
                            )
                    except Exception as se:
                        current_app.logger.error(f"BACKGROUND: MK attach error for {on}: {se}")
                        mk_failed_orders.append({
                            "order_number": on,
                            "reason": f"exception: {se}",
                        })
                db.commit()
        except Exception as e:
            current_app.logger.error(f"BACKGROUND: MK upload phase failed: {e}")

        # Phase 2b: find fulfilled orders in window which still have NO PDF
        # (typically missing data, expired serija, no perfume items, ...). The
        # admin report needs to surface these prominently — they will NOT get
        # a customer email and need manual review.
        no_pdf_orders: list[dict] = []
        try:
            cursor.execute(
                """
                SELECT order_number, has_missing_data, missing_data_details, status
                FROM orders
                WHERE (fulfilled_at IS NOT NULL OR shopify_fulfilled_at IS NOT NULL)
                  AND COALESCE(fulfilled_at, shopify_fulfilled_at) BETWEEN %s AND %s
                  AND pdf_generated_at IS NULL
                ORDER BY COALESCE(fulfilled_at, shopify_fulfilled_at) DESC
                """,
                (start_utc, end_utc),
            )
            no_pdf_rows = cursor.fetchall() or []
            for r in no_pdf_rows:
                if not isinstance(r, dict):
                    continue
                on = r.get('order_number')
                if not on:
                    continue
                details = r.get('missing_data_details')
                reason_text = "Manjkajoči podatki" if r.get('has_missing_data') else "PDF ni generiran"
                if isinstance(details, str) and details:
                    try:
                        parsed = json.loads(details)
                        if isinstance(parsed, list) and parsed:
                            reason_text = "; ".join(str(x) for x in parsed)
                        elif isinstance(parsed, str) and parsed:
                            reason_text = parsed
                    except Exception:
                        reason_text = details
                no_pdf_orders.append({
                    "order_number": on,
                    "reason": reason_text,
                })
        except Exception as e:
            current_app.logger.error(f"BACKGROUND: no-PDF scan failed: {e}")

        # Phase 2c: orders that were already uploaded BEFORE this 21:00 run
        # (e.g. picked up by the hourly reconcile job). These belong in the
        # report so the admin sees the full picture for the day.
        prior_uploaded_orders: list[str] = []
        try:
            cursor.execute(
                """
                SELECT order_number
                FROM orders
                WHERE (fulfilled_at IS NOT NULL OR shopify_fulfilled_at IS NOT NULL)
                  AND COALESCE(fulfilled_at, shopify_fulfilled_at) BETWEEN %s AND %s
                  AND mk_decl_uploaded_at IS NOT NULL
                  AND NOT (mk_decl_uploaded_at >= %s AND mk_decl_uploaded_at <= %s)
                ORDER BY COALESCE(fulfilled_at, shopify_fulfilled_at) DESC
                """,
                (start_utc, end_utc, start_utc, end_utc),
            )
            prior_rows = cursor.fetchall() or []
            for r in prior_rows:
                if isinstance(r, dict) and r.get('order_number'):
                    prior_uploaded_orders.append(r['order_number'])
        except Exception as e:
            current_app.logger.error(f"BACKGROUND: prior-uploaded scan failed: {e}")
        # Email report (even if empty)
        try:
            # Stats for today (Ljubljana day)
            today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
            today_end = now_local.replace(hour=23, minute=59, second=59, microsecond=999999)
            today_start_utc = today_start.astimezone(timezone.utc)
            today_end_utc = today_end.astimezone(timezone.utc)

            cursor.execute(
                """
                SELECT COUNT(*) AS total
                FROM orders
                WHERE (fulfilled_at IS NOT NULL OR shopify_fulfilled_at IS NOT NULL)
                  AND COALESCE(fulfilled_at, shopify_fulfilled_at) BETWEEN %s AND %s
                """,
                (today_start_utc, today_end_utc),
            )
            fulfilled_today = (cursor.fetchone() or {}).get("total")

            cursor.execute(
                """
                SELECT COUNT(*) AS with_pdf
                FROM orders
                WHERE (fulfilled_at IS NOT NULL OR shopify_fulfilled_at IS NOT NULL)
                  AND COALESCE(fulfilled_at, shopify_fulfilled_at) BETWEEN %s AND %s
                  AND pdf_generated_at IS NOT NULL
                """,
                (today_start_utc, today_end_utc),
            )
            pdf_today = (cursor.fetchone() or {}).get("with_pdf")

            cursor.execute(
                """
                SELECT COUNT(*) AS with_mk
                FROM orders
                WHERE (fulfilled_at IS NOT NULL OR shopify_fulfilled_at IS NOT NULL)
                  AND COALESCE(fulfilled_at, shopify_fulfilled_at) BETWEEN %s AND %s
                  AND mk_decl_uploaded_at IS NOT NULL
                """,
                (today_start_utc, today_end_utc),
            )
            mk_today = (cursor.fetchone() or {}).get("with_mk")

            cursor.execute(
                """
                SELECT COUNT(*) AS missing_mk
                FROM orders
                WHERE (fulfilled_at IS NOT NULL OR shopify_fulfilled_at IS NOT NULL)
                  AND COALESCE(fulfilled_at, shopify_fulfilled_at) BETWEEN %s AND %s
                  AND mk_decl_uploaded_at IS NULL
                """,
                (today_start_utc, today_end_utc),
            )
            missing_mk_today = (cursor.fetchone() or {}).get("missing_mk")

            from services.email_service import poslji_mk_deklaracije_report
            poslji_mk_deklaracije_report(
                mk_uploaded_orders,
                window_days=window_days,
                stats={
                    "fulfilled_today": fulfilled_today,
                    "pdf_today": pdf_today,
                    "mk_today": mk_today,
                    "missing_mk_today": missing_mk_today,
                },
                failed_orders=mk_failed_orders,
                no_pdf_orders=no_pdf_orders,
                prior_uploaded_orders=prior_uploaded_orders,
            )
        except Exception as e:
            current_app.logger.error(f"BACKGROUND: MK report email failed: {e}")
    except Exception as e:
        db.rollback()
        current_app.logger.error(f"BACKGROUND: Daily declaration batch error: {e}")
        traceback.print_exc()
    finally:
        cursor.close()


def _sync_fulfilled_at_from_shopify(cursor, db, order_row: dict) -> bool:
    """Za posamezno naročilo iz lokalne DB preveri Shopify fulfillments REST.

    Če Shopify pravi, da ima naročilo aktivni fulfillment (status=success ali open),
    posodobi lokalna polja `fulfilled_at`, `shopify_fulfilled_at`, `shopify_fulfillment_id`
    in tracking polja. Vrne True, če je posodobil DB.

    Klicalec mora poskrbeti za commit (lahko skupinsko).
    """
    try:
        shopify_order_id = order_row.get('shopify_order_id') if isinstance(order_row, dict) else None
        if not shopify_order_id:
            return False
        shop_domain = order_row.get('shopify_store_domain') if isinstance(order_row, dict) else None
        from services.shopify_service import get_order_fulfillment_details
        details = get_order_fulfillment_details(shopify_order_id, shop_domain=shop_domain)
        if not details:
            return False
        # `get_order_fulfillment_details` vrne prvi (najnovejši) aktivni fulfillment kot dict.
        status = (details.get('status') or '').strip().lower()
        shipment_status = (details.get('shipment_status') or '').strip().lower()
        if status not in ('success', 'open'):
            return False
        created_at = details.get('created_at')
        fulfillment_id = details.get('id')
        tracking_no = (
            details.get('tracking_number')
            or (details.get('tracking_numbers') or [None])[0]
        )
        tracking_company = details.get('tracking_company')
        tracking_url = (
            details.get('tracking_url')
            or (details.get('tracking_urls') or [None])[0]
        )

        cursor.execute(
            """
            UPDATE orders
            SET fulfilled_at = COALESCE(fulfilled_at, NOW()),
                shopify_fulfilled_at = COALESCE(shopify_fulfilled_at, %s),
                shopify_fulfillment_id = COALESCE(shopify_fulfillment_id, %s),
                tracking_number = COALESCE(tracking_number, %s),
                tracking_company = COALESCE(tracking_company, %s),
                tracking_url = COALESCE(tracking_url, %s)
            WHERE shopify_order_id = %s
            """,
            (
                created_at,
                str(fulfillment_id) if fulfillment_id else None,
                tracking_no,
                tracking_company,
                tracking_url,
                str(shopify_order_id),
            ),
        )

        # Bonus: če je Shopify že rekel "delivered", poskusi tudi delivered_at.
        if shipment_status == 'delivered':
            cursor.execute(
                """
                UPDATE orders
                SET delivered_at = COALESCE(delivered_at, NOW()),
                    delivered_source = COALESCE(delivered_source, 'shopify_pull')
                WHERE shopify_order_id = %s
                """,
                (str(shopify_order_id),),
            )
        return True
    except Exception as e:
        try:
            current_app.logger.warning(
                f"BACKGROUND: shopify fulfillment sync error for "
                f"{order_row.get('order_number') if isinstance(order_row, dict) else order_row}: {e}"
            )
        except Exception:
            pass
        return False


def backfill_fulfillment_from_shopify(*, days: int = 14, limit: int = 300) -> dict:
    """Backfill orders with NULL fulfilled_at by pulling Shopify fulfillment status.

    Targets all orders in the last `days` where lokalni fulfilled_at IS NULL,
    even if status is `pripravljeno_za_posiljanje` or unset. Po backfillu jih
    bo hourly reconcile in 21:00 batch normalno procesiral (PDF + MK upload).
    """
    db = get_db()
    cursor = db.cursor()
    updated = 0
    checked = 0
    failed: list[dict] = []
    try:
        db.rollback()
        cursor.execute(
            """
            SELECT order_number, shopify_order_id, shopify_store_domain, status
            FROM orders
            WHERE fulfilled_at IS NULL
              AND shopify_fulfilled_at IS NULL
              AND shopify_order_id IS NOT NULL
              AND created_at > NOW() - (%s * INTERVAL '1 day')
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (int(days), int(limit)),
        )
        rows = cursor.fetchall() or []
        for r in rows:
            checked += 1
            try:
                if _sync_fulfilled_at_from_shopify(cursor, db, r):
                    updated += 1
                    db.commit()
                else:
                    # Ne commitamo no-op, ampak ne podaljšamo trans
                    db.rollback()
            except Exception as e:
                db.rollback()
                failed.append({
                    'order_number': r.get('order_number') if isinstance(r, dict) else None,
                    'reason': str(e),
                })
        return {"checked": checked, "updated": updated, "failed_count": len(failed), "failed": failed[:20]}
    except Exception as e:
        db.rollback()
        current_app.logger.error(f"BACKGROUND: backfill fulfillment error: {e}")
        traceback.print_exc()
        return {"checked": checked, "updated": updated, "error": str(e)}
    finally:
        cursor.close()


def reconcile_missing_declarations(hours_back: int = 72, limit: int = 500) -> dict:
    """Hourly reconciliation: ensure fulfilled orders have PDF and MK attachment.

    Also re-check older orders marked as missing data to avoid stale flags after
    series/INCI data is corrected.
    """
    db = get_db()
    cursor = db.cursor()
    updated = 0
    checked = 0
    checked_missing = 0
    try:
        db.rollback()

        # Phase 0: defensivni Shopify fulfillment sync.
        # Tukaj ulovimo naročila, ki so v Shopify-u fulfilled, ampak v naši
        # DB še nimajo `fulfilled_at` (npr. zaradi izgubljenega webhooka).
        # Brez tega bi 21:00 batch in spodnja faza Phase 1 takšna naročila
        # še naprej preskakovala in stranke ne bi prejele deklaracije.
        try:
            cursor.execute(
                """
                SELECT order_number, shopify_order_id, shopify_store_domain
                FROM orders
                WHERE fulfilled_at IS NULL
                  AND shopify_fulfilled_at IS NULL
                  AND shopify_order_id IS NOT NULL
                  AND created_at > NOW() - (%s * INTERVAL '1 hour')
                ORDER BY created_at DESC
                LIMIT 30
                """,
                (max(int(hours_back), 24),),
            )
            unfulfilled_local = cursor.fetchall() or []
            synced_via_pull = 0
            for r in unfulfilled_local:
                try:
                    if _sync_fulfilled_at_from_shopify(cursor, db, r):
                        synced_via_pull += 1
                        db.commit()
                    else:
                        db.rollback()
                except Exception as e:
                    db.rollback()
                    current_app.logger.warning(
                        f"BACKGROUND: pull fulfillment failed for {r.get('order_number') if isinstance(r, dict) else r}: {e}"
                    )
            if synced_via_pull:
                current_app.logger.info(
                    f"BACKGROUND: reconcile pulled {synced_via_pull} missing fulfillments from Shopify"
                )
        except Exception as e:
            current_app.logger.warning(f"BACKGROUND: defensive Shopify pull phase error: {e}")

        cursor.execute(
            """
            SELECT *
            FROM orders
            WHERE (fulfilled_at IS NOT NULL OR shopify_fulfilled_at IS NOT NULL)
              AND COALESCE(fulfilled_at, shopify_fulfilled_at) > NOW() - (%s * INTERVAL '1 hour')
              AND (pdf_generated_at IS NULL OR mk_decl_uploaded_at IS NULL OR has_missing_data = TRUE)
            ORDER BY COALESCE(fulfilled_at, shopify_fulfilled_at) DESC
            LIMIT %s
            """,
            (int(hours_back), int(limit)),
        )
        rows = cursor.fetchall() or []
        processed = set()

        for order_data in rows:
            checked += 1
            order_number = order_data.get('order_number') if isinstance(order_data, dict) else None
            if not order_number:
                continue
            processed.add(str(order_number).replace('#', ''))
            if order_data.get('pdf_generated_at') is None:
                if _ensure_declaration_rows(cursor, order_data):
                    try:
                        db.commit()
                    except Exception:
                        pass
                    pdf_path = generate_declaration_pdf(order_number)
                    if pdf_path:
                        cursor.execute(
                            """
                            UPDATE orders
                            SET pdf_generated_at = CURRENT_TIMESTAMP
                            WHERE order_number = %s OR order_number = %s
                            """,
                            (order_number, f"#{str(order_number).replace('#','')}")
                        )
                        updated += 1
            # Sync MK attachment if missing.
            #
            # IMPORTANT: do NOT call `sync_mk_declaration_uploads(order_numbers=[...])`
            # here. It performs many sequential MK API calls per order (each with
            # 5 retries) and, when called in a loop over up to 500 orders, can
            # take tens of minutes while holding a DB connection — eventually
            # exhausting the Postgres role connection pool and bringing the app
            # down. The nightly retail/declaration delta jobs cover the same
            # workload in a controlled batch.
            #
            # We attempt only the cheap `mk_attach_declaration_for_order` here
            # (when the PDF is already present) and record the check timestamp.
            if order_data.get('mk_decl_uploaded_at') is None and order_data.get('pdf_generated_at'):
                try:
                    from services.mk_service import mk_attach_declaration_for_order
                    attach_res = mk_attach_declaration_for_order(
                        str(order_number),
                        shopify_order_id=order_data.get('shopify_order_id'),
                        mk_bill_id=order_data.get('mk_bill_id'),
                        mk_bill_type=order_data.get('mk_bill_type'),
                        mk_sales_order_id=order_data.get('mk_sales_order_id'),
                    )
                    if attach_res.get("success"):
                        cursor.execute(
                            """
                            UPDATE orders
                            SET mk_decl_uploaded_at = CURRENT_TIMESTAMP,
                                mk_decl_upload_checked_at = NOW()
                            WHERE order_number = %s OR order_number = %s
                            """,
                            (order_number, f"#{str(order_number).replace('#','')}")
                        )
                    else:
                        # Only record that we tried — defer the expensive MK lookup
                        # to the nightly batch sync.
                        cursor.execute(
                            """
                            UPDATE orders
                            SET mk_decl_upload_checked_at = NOW()
                            WHERE order_number = %s OR order_number = %s
                            """,
                            (order_number, f"#{str(order_number).replace('#','')}")
                        )
                except Exception as se:
                    current_app.logger.error(f"BACKGROUND: MK attach error for {order_number}: {se}")
                # Commit per-order so the connection does not stay idle in
                # transaction across many slow MK calls.
                try:
                    db.commit()
                except Exception:
                    db.rollback()

        # Second pass: stale missing-data orders (older than hours_back)
        cursor.execute(
            """
            SELECT *
            FROM orders
            WHERE has_missing_data = TRUE
            ORDER BY created_at DESC NULLS LAST
            LIMIT %s
            """,
            (int(limit),),
        )
        missing_rows = cursor.fetchall() or []
        for order_data in missing_rows:
            order_number = order_data.get('order_number') if isinstance(order_data, dict) else None
            if not order_number:
                continue
            if str(order_number).replace('#', '') in processed:
                continue
            checked_missing += 1
            if not _ensure_declaration_rows(cursor, order_data):
                continue
            # Re-fetch latest order data
            cursor.execute(
                "SELECT * FROM orders WHERE order_number = %s OR order_number = %s",
                (order_number, f"#{str(order_number).replace('#','')}")
            )
            refreshed = cursor.fetchone()
            if not refreshed:
                continue
            if not (refreshed.get('fulfilled_at') or refreshed.get('shopify_fulfilled_at')):
                continue

            if refreshed.get('pdf_generated_at') is None:
                pdf_path = generate_declaration_pdf(order_number)
                if pdf_path:
                    cursor.execute(
                        """
                        UPDATE orders
                        SET pdf_generated_at = CURRENT_TIMESTAMP
                        WHERE order_number = %s OR order_number = %s
                        """,
                        (order_number, f"#{str(order_number).replace('#','')}")
                    )
                    updated += 1
                else:
                    continue

            if refreshed.get('mk_decl_uploaded_at') is None:
                try:
                    from services.mk_service import mk_attach_declaration_for_order
                    attach_res = mk_attach_declaration_for_order(
                        str(order_number),
                        shopify_order_id=refreshed.get('shopify_order_id'),
                        mk_bill_id=refreshed.get('mk_bill_id'),
                        mk_bill_type=refreshed.get('mk_bill_type'),
                        mk_sales_order_id=refreshed.get('mk_sales_order_id'),
                    )
                    if attach_res.get("success"):
                        cursor.execute(
                            """
                            UPDATE orders
                            SET mk_decl_uploaded_at = CURRENT_TIMESTAMP,
                                mk_decl_upload_checked_at = NOW()
                            WHERE order_number = %s OR order_number = %s
                            """,
                            (order_number, f"#{str(order_number).replace('#','')}")
                        )
                except Exception as se:
                    current_app.logger.error(f"BACKGROUND: MK sync error for {order_number}: {se}")

        db.commit()
        return {"checked": checked, "updated": updated, "checked_missing": checked_missing}
    except Exception as e:
        db.rollback()
        current_app.logger.error(f"BACKGROUND: Reconciliation error: {e}")
        traceback.print_exc()
        return {"checked": checked, "updated": updated, "checked_missing": checked_missing, "error": str(e)}
    finally:
        cursor.close()
